"""Controller centrale e coordinatore delle operazioni di GLM OCR."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
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
from core.output_workflow import OutputWorkflow
from core.process_manager import ProcessManager

logger = logging.getLogger(__name__)

OP_IDLE = "idle"
OP_MODEL_LOADING = "model_loading"
OP_MODEL_UNLOADING = "model_unloading"
OP_OCR = "ocr"
OP_BATCH = "batch"
OP_SHUTTING_DOWN = "shutting_down"

_PENDING_OCR = "ocr"
_PENDING_BATCH = "batch"


@dataclass(frozen=True)
class _PendingUserOperation:
    kind: str
    paths: tuple[Path, ...]


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
    """Own application operations, hardware/model lifecycle and canonical services."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = OCREngine()
        self._hardware_detector = HardwareDetector()
        self._operation_lock = threading.RLock()
        self._operation = OP_IDLE
        self._initialized = False
        self._shutdown_started = False
        self._idle_since = time.monotonic()

        self._hardware_thread: threading.Thread | None = None
        self._hardware_thread_lock = threading.Lock()

        self._ocr_thread: threading.Thread | None = None
        self._ocr_token: CancellationToken | None = None

        self._model_load_token: CancellationToken | None = None
        self._model_thread: threading.Thread | None = None
        self._model_thread_lock = threading.Lock()
        self._pending_user_operation: _PendingUserOperation | None = None

        self._output_workflow = OutputWorkflow(lambda: self._settings)
        self._process_manager = ProcessManager(
            self._engine,
            on_job_finished=self._on_batch_finished,
        )

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def engine(self) -> OCREngine:
        """Compatibility access; presentation code should prefer focused snapshots."""
        return self._engine

    @property
    def hardware_detector(self) -> HardwareDetector:
        return self._hardware_detector

    @property
    def process_manager(self) -> ProcessManager:
        """Compatibility access; presentation code should prefer active_batch_id."""
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

    @property
    def model_ready(self) -> bool:
        return self._engine.is_initialized

    @property
    def model_device(self) -> str:
        return self._engine.device

    @property
    def model_backend(self) -> str:
        return self._engine.backend

    @property
    def active_batch_id(self) -> str | None:
        return self._process_manager.active_job_id

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
            self._idle_since = time.monotonic()
        EventBus.emit("operation_changed", {"operation": OP_IDLE})

    def _prepare_model_load(self, device: str) -> CancellationToken:
        self._begin_operation(OP_MODEL_LOADING)
        token = CancellationToken()
        with self._operation_lock:
            self._model_load_token = token
        EventBus.emit("model_loading", {"device": device})
        return token

    def _start_hardware_worker(
        self,
        *,
        name: str,
        task: Callable[[], None],
        failure_event: str,
    ) -> bool:
        """Run one hardware probe outside Qt; hardware work has one controller owner."""
        with self._hardware_thread_lock:
            if self._shutdown_started:
                raise OperationBusyError(OP_SHUTTING_DOWN)
            if self._hardware_thread is not None and self._hardware_thread.is_alive():
                return False

            def run() -> None:
                try:
                    task()
                except Exception as exc:
                    logger.exception("Hardware worker %s fallito", name)
                    if not self._shutdown_started:
                        EventBus.emit(failure_event, {"error": str(exc)})
                finally:
                    with self._hardware_thread_lock:
                        if self._hardware_thread is threading.current_thread():
                            self._hardware_thread = None

            thread = threading.Thread(target=run, name=name, daemon=True)
            self._hardware_thread = thread
            thread.start()
            return True

    def request_initialize(self) -> bool:
        """Initialize hardware/model policy asynchronously; safe for the Qt bridge."""
        if self._initialized:
            return False
        return self._start_hardware_worker(
            name="backend-init-worker",
            task=self.initialize,
            failure_event="backend_initialization_failed",
        )

    def request_hardware_refresh(self) -> bool:
        """Refresh hardware asynchronously without blocking the GUI thread."""
        if self.operation != OP_IDLE:
            raise OperationBusyError(self.operation)

        def refresh() -> None:
            self._hardware_detector.detect(refresh=True)

        started = self._start_hardware_worker(
            name="hardware-refresh-worker",
            task=refresh,
            failure_event="hardware_refresh_failed",
        )
        if started:
            EventBus.emit("hardware_refresh_started", {})
        return started

    def initialize(self) -> None:
        """Detect hardware and asynchronously apply the configured startup policy."""
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
            self.request_model_load(default_device)
        else:
            EventBus.emit(
                "model_unloaded",
                {"device": default_device, "reason": "startup_disabled"},
            )

    def request_model_load(self, device: str) -> None:
        """Start one asynchronous model load owned by the controller."""
        self._prepare_model_load(device)
        try:
            self._start_model_load_worker(device)
        except Exception:
            with self._operation_lock:
                self._model_load_token = None
            self._finish_operation(OP_MODEL_LOADING)
            raise

    def _start_model_load_worker(self, device: str) -> None:
        with self._model_thread_lock:
            if self._shutdown_started:
                raise OperationBusyError(OP_SHUTTING_DOWN)
            if self._model_thread is not None and self._model_thread.is_alive():
                raise OperationBusyError(OP_MODEL_LOADING)

            def load() -> None:
                try:
                    self.load_model_sync(device)
                    EventBus.emit(
                        "model_loaded",
                        {
                            "device": self.model_device,
                            "backend": self.model_backend,
                        },
                    )
                    self._resume_pending_user_operation()
                except OperationCancelledError:
                    self._clear_pending_user_operation()
                    EventBus.emit("model_load_cancelled", {"device": device})
                except Exception as exc:
                    self._clear_pending_user_operation()
                    logger.exception("Caricamento modello fallito")
                    EventBus.emit(
                        "model_load_failed",
                        {"device": device, "error": str(exc)},
                    )
                finally:
                    with self._model_thread_lock:
                        if self._model_thread is threading.current_thread():
                            self._model_thread = None

            thread = threading.Thread(
                target=load,
                name="model-load-worker",
                daemon=True,
            )
            self._model_thread = thread
            thread.start()

    def cancel_model_loading(self) -> None:
        with self._operation_lock:
            token = self._model_load_token
        if token is not None:
            token.cancel()

    def load_model_sync(self, device: str) -> None:
        """Load the model in the calling thread; async ownership stays above it."""
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

    def request_model_unload(self) -> bool:
        """Start model unload off-GUI; return False when already unloaded."""
        if not self._engine.is_initialized:
            EventBus.emit(
                "model_unloaded",
                {"device": self._settings.default_device, "reason": "already_unloaded"},
            )
            return False
        self._begin_operation(OP_MODEL_UNLOADING)
        EventBus.emit(
            "model_unloading",
            {"device": self._engine.device},
        )
        try:
            self._start_model_unload_worker()
        except Exception:
            self._finish_operation(OP_MODEL_UNLOADING)
            raise
        return True

    def _start_model_unload_worker(self) -> None:
        with self._model_thread_lock:
            if self._shutdown_started:
                raise OperationBusyError(OP_SHUTTING_DOWN)
            if self._model_thread is not None and self._model_thread.is_alive():
                raise OperationBusyError(self.operation)

            def unload() -> None:
                try:
                    self.unload_model_sync()
                except Exception as exc:
                    logger.exception("Scaricamento modello fallito")
                    EventBus.emit("model_unload_failed", {"error": str(exc)})
                finally:
                    with self._model_thread_lock:
                        if self._model_thread is threading.current_thread():
                            self._model_thread = None

            thread = threading.Thread(
                target=unload,
                name="model-unload-worker",
                daemon=True,
            )
            self._model_thread = thread
            thread.start()

    def unload_model_sync(self) -> None:
        """Release the backend in the calling thread."""
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

    def _queue_user_operation(self, pending: _PendingUserOperation) -> None:
        with self._operation_lock:
            if self._pending_user_operation is not None:
                raise OperationBusyError("queued_operation")
            if self._operation != OP_IDLE:
                raise OperationBusyError(self._operation)
            self._pending_user_operation = pending
        try:
            self.request_model_load(self._settings.default_device)
        except Exception:
            self._clear_pending_user_operation()
            raise

    def _clear_pending_user_operation(self) -> None:
        with self._operation_lock:
            self._pending_user_operation = None

    def _take_pending_user_operation(self) -> _PendingUserOperation | None:
        with self._operation_lock:
            pending = self._pending_user_operation
            self._pending_user_operation = None
            return pending

    def _resume_pending_user_operation(self) -> None:
        pending = self._take_pending_user_operation()
        if pending is None or self._shutdown_started:
            return
        try:
            if pending.kind == _PENDING_OCR:
                self.start_ocr(pending.paths[0])
            elif pending.kind == _PENDING_BATCH:
                self.run_batch(list(pending.paths))
            else:
                raise RuntimeError(f"Operazione accodata sconosciuta: {pending.kind}")
        except Exception as exc:
            logger.exception("Operazione accodata dopo model load fallita")
            EventBus.emit(
                "queued_operation_failed",
                {"kind": pending.kind, "error": str(exc)},
            )

    def start_ocr_or_queue(self, image_path: Path) -> bool:
        """Start OCR now or queue exactly one OCR behind a model load."""
        path = Path(image_path)
        if self.model_ready:
            self.start_ocr(path)
            return False
        self._queue_user_operation(_PendingUserOperation(_PENDING_OCR, (path,)))
        return True

    def run_batch_or_queue(
        self,
        image_paths: list[Path],
    ) -> tuple[bool, BatchOCRJob | None]:
        """Start batch now or queue exactly one batch behind a model load."""
        paths = tuple(Path(path) for path in image_paths)
        if self.model_ready:
            return False, self.run_batch(list(paths))
        self._queue_user_operation(_PendingUserOperation(_PENDING_BATCH, paths))
        return True, None

    def check_idle_model_unload(self, *, now: float | None = None) -> bool:
        """Apply configured idle-unload policy; safe to call from a Qt timer."""
        minutes = int(self._settings.model_auto_unload_minutes)
        if minutes <= 0 or not self.model_ready or self.operation != OP_IDLE:
            return False
        current = time.monotonic() if now is None else float(now)
        with self._operation_lock:
            idle_since = self._idle_since
        if current - idle_since < minutes * 60:
            return False
        logger.info("Auto-unload modello dopo %d minuti di inattività", minutes)
        return self.request_model_unload()

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
        """Persist a validated device choice and asynchronously reload it."""
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

        previous = self._settings
        self._settings = self._settings.with_(default_device=device_type)
        try:
            self._settings.save()
            EventBus.emit("config_changed", {"default_device": device_type})
            self.request_model_load(device_type)
        except Exception:
            self._settings = previous
            raise

    def update_settings(self, **overrides: object) -> None:
        self._settings = self._settings.with_(**overrides)
        self._settings.save()
        if "model_auto_unload_minutes" in overrides:
            with self._operation_lock:
                self._idle_since = time.monotonic()
        EventBus.emit("config_changed", overrides)

    def save_single_result(self, source_path: str, file_format: str) -> Path:
        """Persist the canonical completed single-OCR result."""
        return self._output_workflow.save_single_result(source_path, file_format)

    def save_single_pdf_pages(self, source_path: str, file_format: str) -> list[Path]:
        """Persist canonical page texts from a completed single-PDF OCR."""
        return self._output_workflow.save_single_pdf_pages(source_path, file_format)

    def shutdown(self) -> None:
        """Cancel operations, join owned workers and release the backend."""
        with self._operation_lock:
            if self._shutdown_started:
                return
            self._shutdown_started = True
            self._operation = OP_SHUTTING_DOWN
            self._pending_user_operation = None
            ocr_token = self._ocr_token
            model_token = self._model_load_token
            ocr_thread = self._ocr_thread
        with self._hardware_thread_lock:
            hardware_thread = self._hardware_thread
        with self._model_thread_lock:
            model_thread = self._model_thread

        EventBus.emit("operation_changed", {"operation": OP_SHUTTING_DOWN})
        if ocr_token is not None:
            ocr_token.cancel()
        if model_token is not None:
            model_token.cancel()

        self._process_manager.cancel_active_batch()
        self._process_manager.shutdown()

        if ocr_thread is not None and ocr_thread.is_alive():
            ocr_thread.join(timeout=15)
        if hardware_thread is not None and hardware_thread.is_alive():
            hardware_thread.join(timeout=15)
            if hardware_thread.is_alive():
                logger.warning("Hardware worker non terminato entro il timeout")
        if model_thread is not None and model_thread.is_alive():
            model_thread.join(timeout=15)
            if model_thread.is_alive():
                logger.warning("Model lifecycle worker non terminato entro il timeout")

        self._output_workflow.shutdown()
        self._engine.shutdown()
        self._initialized = False

    def subscribe(self, event: str, handler: Callable) -> None:
        EventBus.subscribe(event, handler)