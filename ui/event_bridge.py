"""Ponte thread-safe tra EventBus core e segnali Qt/QML."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot

from core.app_controller import AppController
from core.event_bus import EventBus
from core.exceptions import OperationCancelledError

logger = logging.getLogger(__name__)


class ModelLoadWorker(QObject):
    """Esegue AppController.load_model_sync() fuori dal thread GUI."""

    finished = Signal(str, str)  # backend, device
    cancelled = Signal()
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, controller: AppController, device: str) -> None:
        super().__init__()
        self._controller = controller
        self._device = device

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Caricamento modello GLM-OCR in corso...")
            self._controller.load_model_sync(device=self._device)
            self.finished.emit(
                self._controller.engine.backend,
                self._controller.engine.device,
            )
        except OperationCancelledError:
            self.cancelled.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class EventBridge(QObject):
    """Converte eventi core in segnali Qt e gestisce il model-load QThread."""

    # OCR singolo
    ocr_new_text = Signal(str)
    ocr_status_changed = Signal(str)
    ocr_error = Signal(str)
    ocr_completed = Signal()
    ocr_cancelled = Signal()
    ocr_page_progress = Signal(str)

    # Batch
    batch_new_text = Signal(str)
    batch_status_changed = Signal(str)
    batch_progress = Signal(int, int)  # completed, total
    batch_error = Signal(str)
    batch_completed = Signal()
    batch_cancelled = Signal()

    # Modello / coordinatore
    model_loading = Signal(str)
    model_loaded = Signal(str, str)
    model_load_cancelled = Signal()
    model_load_error = Signal(str)
    model_load_progress = Signal(str)
    operation_changed = Signal(str)

    # Compatibilità eventi processo
    process_started = Signal()
    process_stopped = Signal()

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self._controller = controller
        self._load_thread: QThread | None = None
        self._load_worker: ModelLoadWorker | None = None
        self._closed = False
        self._subscriptions: list[tuple[str, Callable[[dict[str, Any]], None]]] = []
        self._subscribe_all()

    def _subscribe(
        self,
        event_name: str,
        handler: Callable[[dict[str, Any]], None],
    ) -> None:
        EventBus.subscribe(event_name, handler)
        self._subscriptions.append((event_name, handler))

    def _subscribe_all(self) -> None:
        self._subscribe("ocr_started", self._on_ocr_started)
        self._subscribe("ocr_completed", self._on_ocr_completed)
        self._subscribe("ocr_failed", self._on_ocr_failed)
        self._subscribe("ocr_cancelled", self._on_ocr_cancelled)
        self._subscribe("pdf_page_completed", self._on_pdf_page_completed)
        self._subscribe("pdf_progress", self._on_pdf_progress)

        self._subscribe("batch_started", self._on_batch_started)
        self._subscribe("batch_progress", self._on_batch_progress)
        self._subscribe("batch_completed", self._on_batch_completed)
        self._subscribe("batch_cancelled", self._on_batch_cancelled)
        self._subscribe("batch_failed", self._on_batch_failed)
        self._subscribe("batch_task_completed", self._on_batch_task_completed)
        self._subscribe("batch_task_failed", self._on_batch_task_failed)

        self._subscribe("model_loading", self._on_model_loading)
        self._subscribe("model_load_progress", self._on_model_load_progress)
        self._subscribe("operation_changed", self._on_operation_changed)
        self._subscribe("process_started", self._on_process_started)
        self._subscribe("process_stopped", self._on_process_stopped)

    @staticmethod
    def _is_single(data: dict[str, Any]) -> bool:
        return str(data.get("mode", "single")) == "single"

    # ------------------------------------------------------------------
    # OCR singolo
    # ------------------------------------------------------------------

    def _on_ocr_started(self, data: dict[str, Any]) -> None:
        if self._is_single(data):
            self.ocr_status_changed.emit("processing")

    def _on_ocr_completed(self, data: dict[str, Any]) -> None:
        if not self._is_single(data):
            return
        if not bool(data.get("pages_streamed", False)):
            text = str(data.get("text", ""))
            if text:
                self.ocr_new_text.emit(text)
        self.ocr_completed.emit()

    def _on_ocr_failed(self, data: dict[str, Any]) -> None:
        if self._is_single(data):
            self.ocr_error.emit(str(data.get("error", "Errore OCR")))

    def _on_ocr_cancelled(self, data: dict[str, Any]) -> None:
        if self._is_single(data):
            self.ocr_cancelled.emit()

    def _on_pdf_page_completed(self, data: dict[str, Any]) -> None:
        if not self._is_single(data):
            return
        page_num = int(data.get("page_num", 0) or 0)
        total_pages = int(data.get("total_pages", 0) or 0)
        text = str(data.get("text", ""))
        if not text:
            return
        if total_pages > 1:
            self.ocr_new_text.emit(f"--- Pagina {page_num} ---\n{text}")
        else:
            self.ocr_new_text.emit(text)

    def _on_pdf_progress(self, data: dict[str, Any]) -> None:
        if not self._is_single(data):
            return
        page_num = int(data.get("page_num", 0) or 0)
        total_pages = int(data.get("total_pages", 0) or 0)
        self.ocr_page_progress.emit(f"Pagina {page_num}/{total_pages}")

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    def _on_batch_started(self, data: dict[str, Any]) -> None:
        total = int(data.get("total_tasks", 0) or 0)
        self.batch_status_changed.emit("running")
        self.batch_progress.emit(0, total)

    def _on_batch_progress(self, data: dict[str, Any]) -> None:
        completed = int(data.get("completed", 0) or 0)
        total = int(data.get("total", 0) or 0)
        self.batch_progress.emit(completed, total)

    def _on_batch_completed(self, data: dict[str, Any]) -> None:
        completed = int(data.get("completed", 0) or 0)
        total = int(data.get("total", 0) or 0)
        if total:
            self.batch_progress.emit(completed, total)
        self.batch_status_changed.emit("completed")
        self.batch_completed.emit()

    def _on_batch_cancelled(self, data: dict[str, Any]) -> None:
        completed = int(data.get("completed", 0) or 0)
        total = int(data.get("total", 0) or 0)
        self.batch_progress.emit(completed, total)
        self.batch_status_changed.emit("stopped")
        self.batch_cancelled.emit()

    def _on_batch_failed(self, data: dict[str, Any]) -> None:
        self.batch_error.emit(str(data.get("error", "Errore batch")))

    def _on_batch_task_completed(self, data: dict[str, Any]) -> None:
        text = str(data.get("text", ""))
        image_path = str(data.get("image_path", ""))
        if text:
            header = f"[{image_path}]" if image_path else ""
            self.batch_new_text.emit(
                f"{header}\n{text}" if header else text
            )

    def _on_batch_task_failed(self, data: dict[str, Any]) -> None:
        # Un singolo task fallito non cambia lo stato dell'intero batch:
        # il riepilogo batch_failed arriverà solo a fine job.
        image_path = str(data.get("image_path", ""))
        error = str(data.get("error", "Errore sconosciuto"))
        header = f"[{image_path}]" if image_path else ""
        self.batch_new_text.emit(
            f"{header}\n[Errore: {error}]" if header else f"[Errore: {error}]"
        )

    # ------------------------------------------------------------------
    # Modello / operazione globale
    # ------------------------------------------------------------------

    def _on_model_loading(self, data: dict[str, Any]) -> None:
        self.model_loading.emit(str(data.get("device", "")))

    def _on_model_load_progress(self, data: dict[str, Any]) -> None:
        self.model_load_progress.emit(str(data.get("message", "")))

    def _on_operation_changed(self, data: dict[str, Any]) -> None:
        self.operation_changed.emit(str(data.get("operation", "idle")))

    def _on_process_started(self, _data: dict[str, Any]) -> None:
        self.process_started.emit()

    def _on_process_stopped(self, _data: dict[str, Any]) -> None:
        self.process_stopped.emit()

    # ------------------------------------------------------------------
    # Model load QThread
    # ------------------------------------------------------------------

    def start_model_loading(self, device: str) -> None:
        if self._closed:
            return
        if self._is_load_thread_running():
            # Il coordinatore core impedisce model load concorrenti. Se si
            # arriva qui, ignorare l'evento duplicato è più sicuro che
            # terminare un QThread mentre sta toccando l'engine.
            logger.warning(
                "Richiesta model-load duplicata ignorata per %s", device
            )
            return

        thread = QThread(self)
        worker = ModelLoadWorker(self._controller, device)
        worker.moveToThread(thread)
        self._load_thread = thread
        self._load_worker = worker

        thread.started.connect(worker.run)
        worker.progress.connect(self.model_load_progress.emit)
        worker.finished.connect(self._on_worker_finished)
        worker.cancelled.connect(self._on_worker_cancelled)
        worker.error.connect(self._on_worker_error)

        worker.finished.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._reset_load_thread_refs)
        thread.finished.connect(thread.deleteLater)

        thread.start()
        logger.info("Thread model-load avviato per %s", device)

    def _is_load_thread_running(self) -> bool:
        thread = self._load_thread
        if thread is None:
            return False
        try:
            return thread.isRunning()
        except RuntimeError:
            self._load_thread = None
            self._load_worker = None
            return False

    @Slot()
    def _reset_load_thread_refs(self) -> None:
        self._load_thread = None
        self._load_worker = None

    @Slot(str, str)
    def _on_worker_finished(self, backend: str, device: str) -> None:
        if not self._closed:
            self.model_loaded.emit(backend, device)

    @Slot()
    def _on_worker_cancelled(self) -> None:
        if not self._closed:
            self.model_load_cancelled.emit()

    @Slot(str)
    def _on_worker_error(self, error_msg: str) -> None:
        logger.error("Errore caricamento modello: %s", error_msg)
        if not self._closed:
            self.model_load_error.emit(error_msg)

    def shutdown(self, wait_ms: int = 15000) -> None:
        """Deregistra gli handler e attende in sicurezza il model-load worker."""
        if self._closed:
            return
        self._closed = True

        for event_name, handler in self._subscriptions:
            EventBus.unsubscribe(event_name, handler)
        self._subscriptions.clear()

        self._controller.cancel_model_loading()
        thread = self._load_thread
        if thread is not None:
            try:
                thread.quit()
                if thread.isRunning() and not thread.wait(wait_ms):
                    logger.warning(
                        "Model-load QThread ancora attivo dopo %d ms", wait_ms
                    )
            except RuntimeError:
                pass

    def __del__(self) -> None:
        try:
            self.shutdown(wait_ms=1000)
        except Exception:
            pass
