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
    OCREngineNotInitializedError,
    OperationBusyError,
    OperationCancelledError,
)
from core.hardware_detector import HardwareDetector
from core.image_utils import is_pdf
from core.llama_backend import LlamaServerBackend
from core.models import BatchOCRJob
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
_JOIN_TIMEOUT_S = 15.0


@dataclass(frozen=True)
class _PendingUserOperation:
    kind: str
    paths: tuple[Path, ...]


class AppController:
    """Own application operations, hardware/model lifecycle and canonical services."""

    def __init__(self, settings: Settings, *, engine: OCREngine | None = None) -> None:
        self._settings = settings
        # The backend is created at every model load, so a changed context size
        # applies on the next (re)load.
        self._engine = engine or OCREngine(
            backend_factory=lambda: LlamaServerBackend(
                context_size=self._settings.llama_context_size
            )
        )
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
    def operation(self) -> str:
        with self._operation_lock:
            return self._operation

    @property
    def model_ready(self) -> bool:
        return self._engine.is_initialized

    @property
    def active_batch_id(self) -> str | None:
        return self._process_manager.active_job_id

    # --- operation state ------------------------------------------------------

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
            if self._shutdown_started or self._operation != operation:
                return
            self._operation = OP_IDLE
            self._idle_since = time.monotonic()
        EventBus.emit("operation_changed", {"operation": OP_IDLE})

    # --- hardware ---------------------------------------------------------------

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
        """Initialize hardware/model policy asynchronously; safe for the Qt thread."""
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

        started = self._start_hardware_worker(
            name="hardware-refresh-worker",
            task=lambda: self._hardware_detector.detect(refresh=True),
            failure_event="hardware_refresh_failed",
        )
        if started:
            EventBus.emit("hardware_refresh_started", {})
        return started

    def initialize(self) -> None:
        """Detect the backend and apply the configured startup policy."""
        if self._initialized:
            return
        status = self._hardware_detector.detect()
        if not status.available:
            logger.warning("Backend SYCL non disponibile: %s", status.label)
        if self._settings.load_model_at_startup:
            # Even without a detected device the load is attempted: it fails
            # with the precise reason, which the UI then shows to the user.
            # A failure to start the worker leaves initialization retryable.
            self.request_model_load()
            self._initialized = True
        else:
            self._initialized = True
            EventBus.emit("model_unloaded", {"reason": "startup_disabled"})

    # --- model lifecycle --------------------------------------------------------

    def request_model_load(self) -> None:
        """Start one asynchronous model load owned by the controller."""
        self._begin_operation(OP_MODEL_LOADING)
        token = CancellationToken()
        with self._operation_lock:
            self._model_load_token = token
        EventBus.emit("model_loading", {})
        try:
            self._start_model_worker("model-load-worker", lambda: self._run_model_load(token))
        except Exception:
            with self._operation_lock:
                self._model_load_token = None
            self._finish_operation(OP_MODEL_LOADING)
            raise

    def _run_model_load(self, token: CancellationToken) -> None:
        succeeded = False
        try:
            self._engine.initialize(cancel_token=token)
            token.raise_if_cancelled()
            EventBus.emit("model_loaded", {})
            succeeded = True
        except OperationCancelledError:
            self._clear_pending_user_operation()
            EventBus.emit("model_load_cancelled", {})
        except Exception as exc:
            self._clear_pending_user_operation()
            logger.exception("Caricamento modello fallito")
            EventBus.emit("model_load_failed", {"error": str(exc)})
        finally:
            with self._operation_lock:
                if self._model_load_token is token:
                    self._model_load_token = None
            self._release_model_worker()
            self._finish_operation(OP_MODEL_LOADING)
        if succeeded:
            self._resume_pending_user_operation()

    def _release_model_worker(self) -> None:
        """Release async model-worker ownership before publishing idle state."""
        with self._model_thread_lock:
            if self._model_thread is threading.current_thread():
                self._model_thread = None

    def _start_model_worker(self, name: str, target: Callable[[], None]) -> None:
        with self._model_thread_lock:
            if self._shutdown_started:
                raise OperationBusyError(OP_SHUTTING_DOWN)
            if self._model_thread is not None and self._model_thread.is_alive():
                raise OperationBusyError(self.operation)
            thread = threading.Thread(target=target, name=name, daemon=True)
            self._model_thread = thread
            thread.start()

    def cancel_model_loading(self) -> None:
        with self._operation_lock:
            token = self._model_load_token
        if token is not None:
            token.cancel()

    def request_model_unload(self) -> bool:
        """Start model unload off-GUI; return False when already unloaded."""
        if not self._engine.is_initialized:
            EventBus.emit("model_unloaded", {"reason": "already_unloaded"})
            return False
        self._begin_operation(OP_MODEL_UNLOADING)
        EventBus.emit("model_unloading", {})

        def unload() -> None:
            try:
                self._engine.shutdown()
                EventBus.emit("model_unloaded", {"reason": "requested"})
            except Exception as exc:
                logger.exception("Scaricamento modello fallito")
                EventBus.emit("model_unload_failed", {"error": str(exc)})
            finally:
                self._release_model_worker()
                self._finish_operation(OP_MODEL_UNLOADING)

        try:
            self._start_model_worker("model-unload-worker", unload)
        except Exception:
            self._finish_operation(OP_MODEL_UNLOADING)
            raise
        return True

    def check_idle_model_unload(self, *, now: float | None = None) -> bool:
        """Apply configured idle-unload policy; safe to call from a Qt timer."""
        minutes = int(self._settings.model_auto_unload_minutes)
        if minutes <= 0 or self.operation != OP_IDLE or not self.model_ready:
            return False
        current = time.monotonic() if now is None else float(now)
        with self._operation_lock:
            idle_since = self._idle_since
        if current - idle_since < minutes * 60:
            return False
        logger.info("Auto-unload modello dopo %d minuti di inattività", minutes)
        return self.request_model_unload()

    # --- queued operations ------------------------------------------------------

    def _queue_user_operation(self, pending: _PendingUserOperation) -> None:
        with self._operation_lock:
            if self._pending_user_operation is not None:
                raise OperationBusyError("queued_operation")
            if self._operation != OP_IDLE:
                raise OperationBusyError(self._operation)
            self._pending_user_operation = pending
        try:
            self.request_model_load()
        except Exception:
            self._clear_pending_user_operation()
            raise

    def _clear_pending_user_operation(self) -> None:
        with self._operation_lock:
            self._pending_user_operation = None

    def _resume_pending_user_operation(self) -> None:
        with self._operation_lock:
            pending = self._pending_user_operation
            self._pending_user_operation = None
        if pending is None or self._shutdown_started:
            return
        try:
            if pending.kind == _PENDING_OCR:
                self.start_ocr(pending.paths[0])
            else:
                self.run_batch(list(pending.paths))
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

    # --- OCR ----------------------------------------------------------------------

    def start_ocr(self, image_path: Path) -> None:
        if not self._engine.is_initialized:
            raise OCREngineNotInitializedError()

        path = Path(image_path)
        self._begin_operation(OP_OCR)
        token = CancellationToken()
        task_id = path.stem + "-" + uuid.uuid4().hex[:6]
        preprocessing_enabled = self._settings.preprocessing_enabled

        def run() -> None:
            pdf = is_pdf(path)
            base = {"mode": "single", "task_id": task_id, "image_path": str(path)}
            EventBus.emit("ocr_started", {**base, "is_pdf": pdf})
            try:
                result = self._engine.process_image(
                    path,
                    mode="single",
                    cancel_token=token,
                    preprocessing_enabled=preprocessing_enabled,
                )
                token.raise_if_cancelled()
                EventBus.emit(
                    "ocr_completed",
                    {
                        **base,
                        "text": result.text,
                        "pages": list(result.pages),
                        "time_ms": result.processing_time_ms,
                        "is_pdf": pdf,
                    },
                )
            except OperationCancelledError:
                EventBus.emit("ocr_cancelled", {"mode": "single", "task_id": task_id})
            except Exception as exc:
                logger.exception("OCR fallito per %s", path)
                EventBus.emit(
                    "ocr_failed",
                    {"mode": "single", "task_id": task_id, "error": str(exc)},
                )
            finally:
                with self._operation_lock:
                    if self._ocr_token is token:
                        self._ocr_token = None
                        self._ocr_thread = None
                self._finish_operation(OP_OCR)

        thread = threading.Thread(target=run, name=f"ocr-worker-{task_id}", daemon=True)
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

    def cancel_active_batch(self) -> None:
        self._process_manager.cancel_active_batch()

    # --- settings and output ----------------------------------------------------

    def update_settings(self, **overrides: object) -> None:
        """Validate, persist and publish settings; invalid values raise ``ValueError``."""
        updated = self._settings.with_(**overrides)
        updated.save()
        self._settings = updated
        if "model_auto_unload_minutes" in overrides:
            with self._operation_lock:
                self._idle_since = time.monotonic()
        EventBus.emit("config_changed", dict(overrides))

    def request_save_single_result(self, source_path: str, file_format: str) -> str:
        """Queue canonical combined output without blocking the caller thread."""
        return self._output_workflow.request_save_single_result(source_path, file_format)

    def request_save_single_pdf_pages(self, source_path: str, file_format: str) -> str:
        """Queue canonical PDF page outputs without blocking the caller thread."""
        return self._output_workflow.request_save_single_pdf_pages(source_path, file_format)

    # --- shutdown -----------------------------------------------------------------

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

        self._process_manager.shutdown()

        for name, thread in (
            ("OCR", ocr_thread),
            ("Hardware", hardware_thread),
            ("Model lifecycle", model_thread),
        ):
            if thread is not None and thread.is_alive():
                thread.join(timeout=_JOIN_TIMEOUT_S)
                if thread.is_alive():
                    logger.warning("%s worker non terminato entro il timeout", name)

        self._output_workflow.shutdown()
        self._engine.shutdown()
        self._initialized = False
