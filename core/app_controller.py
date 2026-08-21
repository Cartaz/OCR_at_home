"""Controller centrale e coordinatore delle operazioni di GLM OCR."""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Callable

from config.settings import Settings
from core.cancellation import CancellationToken
from core.event_bus import EventBus
from core.exceptions import (
    HardwareNotAvailableError,
    OCREngineNotInitializedError,
    OperationBusyError,
    OperationCancelledError,
)
from core.hardware_detector import HardwareDetector
from core.models import BatchOCRJob, HardwareInfo, OCRResult
from core.ocr_engine import OCREngine
from core.process_manager import ProcessManager

logger = logging.getLogger(__name__)

OP_IDLE = "idle"
OP_MODEL_LOADING = "model_loading"
OP_MODEL_UNLOADING = "model_unloading"
OP_OCR = "ocr"
OP_BATCH = "batch"
OP_SHUTTING_DOWN = "shutting_down"


class _OCRWorker:
    """Worker thread per un singolo documento OCR."""

    def __init__(
        self,
        engine: OCREngine,
        image_path: Path,
        task_id: str,
        token: CancellationToken,
        preprocessing_enabled: bool,
        on_finished: Callable[[], None],
    ) -> None:
        self._engine = engine
        self._image_path = image_path
        self._task_id = task_id
        self._token = token
        self._preprocessing_enabled = preprocessing_enabled
        self._on_finished = on_finished

    def run(self) -> None:
        from core.image_utils import is_pdf

        is_pdf_file = is_pdf(self._image_path)
        EventBus.emit(
            "ocr_started",
            {
                "mode": "single",
                "task_id": self._task_id,
                "is_pdf": is_pdf_file,
                "image_path": str(self._image_path),
            },
        )
        try:
            result = self._engine.process_image(
                self._image_path,
                mode="single",
                cancel_token=self._token,
                preprocessing_enabled=self._preprocessing_enabled,
            )
            self._token.raise_if_cancelled()
            EventBus.emit(
                "ocr_completed",
                {
                    "mode": "single",
                    "task_id": self._task_id,
                    "text": "" if is_pdf_file else result.text,
                    "confidence": result.confidence,
                    "time_ms": result.processing_time_ms,
                    "is_pdf": is_pdf_file,
                    "pages_streamed": is_pdf_file,
                    "image_path": str(self._image_path),
                },
            )
        except OperationCancelledError:
            EventBus.emit(
                "ocr_cancelled",
                {"mode": "single", "task_id": self._task_id},
            )
        except Exception as exc:
            logger.exception("OCR fallito per %s", self._image_path)
            EventBus.emit(
                "ocr_failed",
                {
                    "mode": "single",
                    "task_id": self._task_id,
                    "error": str(exc),
                },
            )
        finally:
            self._on_finished()


class AppController:
    """Coordina model loading, OCR, batch, unload e shutdown come operazioni esclusive."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = OCREngine()
        self._hardware_detector = HardwareDetector()
        self._operation_lock = threading.RLock()
        self._operation = OP_IDLE
        self._initialized = False
        self._shutdown_started = False
        self._ocr_thread: threading.Thread | None = None
        self._ocr_token: CancellationToken | None = None
        self._model_load_token: CancellationToken | None = None
        self._process_manager = ProcessManager(
            self._engine,
            on_job_finished=self._on_batch_finished,
        )

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def engine(self) -> OCREngine:
        return self._engine

    @property
    def hardware_detector(self) -> HardwareDetector:
        return self._hardware_detector

    @property
    def process_manager(self) -> ProcessManager:
        return self._process_manager

    @property
    def operation(self) -> str:
        with self._operation_lock:
            return self._operation

    @property
    def is_busy(self) -> bool:
        return self.operation != OP_IDLE

    @property
    def is_model_loading(self) -> bool:
        return self.operation == OP_MODEL_LOADING

    def _begin_operation(self, operation: str) -> None:
        with self._operation_lock:
            if self._shutdown_started or self._operation == OP_SHUTTING_DOWN:
                raise OperationBusyError(OP_SHUTTING_DOWN)
            if self._operation != OP_IDLE:
                raise OperationBusyError(self._operation)
            self._operation = operation
        EventBus.emit("operation_changed", {"operation": operation})

    def _finish_operation(self, operation: str) -> None:
        with self._operation_lock:
            if self._shutdown_started:
                return
            if self._operation != operation:
                return
            self._operation = OP_IDLE
        EventBus.emit("operation_changed", {"operation": OP_IDLE})

    def _prepare_model_load(self, device: str) -> None:
        self._begin_operation(OP_MODEL_LOADING)
        token = CancellationToken()
        with self._operation_lock:
            self._model_load_token = token
        EventBus.emit("model_loading", {"device": device})

    def initialize(self) -> None:
        """Rileva l'hardware e, se configurato, richiede il model load iniziale."""
        if self._initialized:
            return

        devices = self._hardware_detector.detect()
        default_device = self._settings.default_device
        configured_available = any(
            device.device_type == default_device and device.available
            for device in devices
        )

        if not configured_available:
            fallback = self._hardware_detector.get_default()
            if fallback.available:
                default_device = fallback.device_type
                self._settings = self._settings.with_(default_device=default_device)
                self._settings.save()
            else:
                logger.warning(
                    "Nessun backend llama.cpp disponibile; mantengo device configurato=%s",
                    default_device,
                )

        self._initialized = True
        if self._settings.load_model_at_startup:
            self._prepare_model_load(default_device)
        else:
            EventBus.emit(
                "model_unloaded",
                {"device": default_device, "reason": "startup_disabled"},
            )

    def request_model_load(self, device: str) -> None:
        """Richiede un model load senza modificare le impostazioni."""
        self._prepare_model_load(device)

    def cancel_model_loading(self) -> None:
        with self._operation_lock:
            token = self._model_load_token
        if token is not None:
            token.cancel()

    def load_model_sync(self, device: str) -> None:
        """Carica il modello nel thread chiamante, rispettando il coordinatore."""
        with self._operation_lock:
            token = self._model_load_token
            active = self._operation

        if active == OP_IDLE:
            self._begin_operation(OP_MODEL_LOADING)
            token = CancellationToken()
            with self._operation_lock:
                self._model_load_token = token
        elif active != OP_MODEL_LOADING:
            raise OperationBusyError(active)

        assert token is not None
        try:
            self._engine.initialize(device=device, cancel_token=token)
            token.raise_if_cancelled()
        finally:
            with self._operation_lock:
                if self._model_load_token is token:
                    self._model_load_token = None
            self._finish_operation(OP_MODEL_LOADING)

    def request_model_unload(self) -> None:
        """Richiede lo scaricamento del modello senza bloccare il chiamante UI."""
        if not self._engine.is_initialized:
            EventBus.emit(
                "model_unloaded",
                {"device": self._settings.default_device, "reason": "already_unloaded"},
            )
            return
        self._begin_operation(OP_MODEL_UNLOADING)
        EventBus.emit(
            "model_unloading",
            {"device": self._engine.device},
        )

    def unload_model_sync(self) -> None:
        """Rilascia il backend nel thread chiamante preservando la UI/controller."""
        active = self.operation
        if active == OP_IDLE:
            self._begin_operation(OP_MODEL_UNLOADING)
        elif active != OP_MODEL_UNLOADING:
            raise OperationBusyError(active)

        try:
            self._engine.shutdown()
            EventBus.emit(
                "model_unloaded",
                {"device": self._settings.default_device, "reason": "requested"},
            )
        finally:
            self._finish_operation(OP_MODEL_UNLOADING)

    def run_ocr(self, image_path: Path) -> OCRResult:
        """API sincrona usata soprattutto da test e integrazioni."""
        if not self._engine.is_initialized:
            raise OCREngineNotInitializedError()
        self._begin_operation(OP_OCR)
        token = CancellationToken()
        try:
            return self._engine.process_image(
                Path(image_path),
                mode="single",
                cancel_token=token,
                preprocessing_enabled=self._settings.preprocessing_enabled,
            )
        finally:
            self._finish_operation(OP_OCR)

    def start_ocr(self, image_path: Path) -> None:
        if not self._engine.is_initialized:
            raise OCREngineNotInitializedError()

        path = Path(image_path)
        self._begin_operation(OP_OCR)
        token = CancellationToken()
        task_id = path.stem + "-" + uuid.uuid4().hex[:6]

        def finished() -> None:
            with self._operation_lock:
                if self._ocr_token is token:
                    self._ocr_token = None
                self._ocr_thread = None
            self._finish_operation(OP_OCR)

        worker = _OCRWorker(
            self._engine,
            path,
            task_id,
            token,
            self._settings.preprocessing_enabled,
            finished,
        )
        thread = threading.Thread(
            target=worker.run,
            name=f"ocr-worker-{task_id}",
            daemon=True,
        )
        with self._operation_lock:
            self._ocr_token = token
            self._ocr_thread = thread
        try:
            thread.start()
        except Exception:
            with self._operation_lock:
                self._ocr_token = None
                self._ocr_thread = None
            self._finish_operation(OP_OCR)
            raise

    def cancel_ocr(self) -> None:
        with self._operation_lock:
            if self._operation != OP_OCR:
                return
            token = self._ocr_token
        if token is not None:
            token.cancel()

    def run_batch(self, image_paths: list[Path]) -> BatchOCRJob:
        if not self._engine.is_initialized:
            raise OCREngineNotInitializedError()
        self._begin_operation(OP_BATCH)
        try:
            return self._process_manager.submit_batch(
                [Path(path) for path in image_paths],
                preprocessing_enabled=self._settings.preprocessing_enabled,
            )
        except Exception:
            self._finish_operation(OP_BATCH)
            raise

    def _on_batch_finished(self, _job_id: str) -> None:
        self._finish_operation(OP_BATCH)

    def cancel_batch(self, job_id: str) -> None:
        self._process_manager.cancel_batch(job_id)

    def cancel_active_batch(self) -> None:
        self._process_manager.cancel_active_batch()

    def get_available_devices(self, *, refresh: bool = False) -> list[HardwareInfo]:
        return self._hardware_detector.detect(refresh=refresh)

    def switch_device(self, device_type: str) -> None:
        """Richiede il cambio device; il riavvio avviene nel model-load worker."""
        devices = self._hardware_detector.detect()
        if not any(
            device.device_type == device_type and device.available
            for device in devices
        ):
            raise HardwareNotAvailableError(device_type)

        if (
            self._engine.is_initialized
            and self._engine.device == device_type
            and self.operation == OP_IDLE
        ):
            if self._settings.default_device != device_type:
                self._settings = self._settings.with_(default_device=device_type)
                self._settings.save()
            return

        self._begin_operation(OP_MODEL_LOADING)
        token = CancellationToken()
        with self._operation_lock:
            self._model_load_token = token
        try:
            self._settings = self._settings.with_(default_device=device_type)
            self._settings.save()
            EventBus.emit("config_changed", {"default_device": device_type})
            EventBus.emit("model_loading", {"device": device_type})
        except Exception:
            with self._operation_lock:
                if self._model_load_token is token:
                    self._model_load_token = None
            self._finish_operation(OP_MODEL_LOADING)
            raise

    def update_settings(self, **overrides: object) -> None:
        self._settings = self._settings.with_(**overrides)
        self._settings.save()
        EventBus.emit("config_changed", overrides)

    def shutdown(self) -> None:
        """Cancella le operazioni, attende i worker e rilascia il backend."""
        with self._operation_lock:
            if self._shutdown_started:
                return
            self._shutdown_started = True
            self._operation = OP_SHUTTING_DOWN
            ocr_token = self._ocr_token
            model_token = self._model_load_token
            ocr_thread = self._ocr_thread

        EventBus.emit("operation_changed", {"operation": OP_SHUTTING_DOWN})
        if ocr_token is not None:
            ocr_token.cancel()
        if model_token is not None:
            model_token.cancel()

        self._process_manager.cancel_active_batch()
        self._process_manager.shutdown()

        if ocr_thread is not None and ocr_thread.is_alive():
            ocr_thread.join(timeout=15)

        self._engine.shutdown()
        self._initialized = False

    def subscribe(self, event: str, handler: Callable) -> None:
        EventBus.subscribe(event, handler)
