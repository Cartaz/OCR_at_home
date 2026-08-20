# ui/event_bridge.py
"""Ponte tra l'EventBus e i Signal Qt per la comunicazione cross-thread.

Converte gli eventi asincroni dell'EventBus (emessi dai thread worker)
in Signal Qt thread-safe. Gestisce il worker QThread per il caricamento
del modello OCR.

Classes:
    ModelLoadWorker: Worker QThread per caricamento modello.
    EventBridge: Ponte EventBus → Signal Qt.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal, Slot

from core.app_controller import AppController
from core.event_bus import EventBus

logger = logging.getLogger(__name__)


class ModelLoadWorker(QObject):
    """Worker per il caricamento asincrono del modello OCR.

    Esegue il caricamento del modello in un QThread separato e
    comunica il risultato tramite Signal Qt (thread-safe).

    Args:
        controller: Controller dell'applicazione.
        device: Dispositivo target per l'inferenza.

    Signals:
        finished: Caricamento completato con successo.
        error: Caricamento fallito con messaggio di errore.
        progress: Messaggio di progresso del caricamento.
    """

    finished = Signal(str, str)  # backend, device
    error = Signal(str)          # error message
    progress = Signal(str)       # progress message

    def __init__(self, controller: AppController, device: str) -> None:
        """Inizializza il worker con controller e dispositivo target."""
        super().__init__()
        self._controller = controller
        self._device = device

    @Slot()
    def run(self) -> None:
        """Esegue il caricamento del modello nel thread worker."""
        try:
            self.progress.emit("Caricamento modello GLM-OCR in corso...")
            self._controller.load_model_sync(device=self._device)
            backend = self._controller.engine.backend
            actual_device = self._controller.engine.device
            self.finished.emit(backend, actual_device)
        except Exception as exc:
            self.error.emit(str(exc))


class EventBridge(QObject):
    """Ponte tra l'EventBus (thread worker) e i Signal Qt (thread GUI).

    Converte gli eventi dell'EventBus in Signal Qt per aggiornamenti
    UI thread-safe. I segnali sono separati per modalità OCR e Batch.

    Signals:
        ocr_new_text: Nuovo testo OCR.
        ocr_status_changed: Cambio stato OCR.
        ocr_error: Errore OCR.
        ocr_completed: OCR completato.
        batch_new_text: Nuovo testo dal batch.
        batch_status_changed: Cambio stato batch.
        batch_progress: Progresso batch (0-100).
        batch_error: Errore batch.
        batch_completed: Batch completato.
        model_loading: Caricamento modello avviato.
        model_loaded: Modello caricato con successo.
        model_load_error: Errore caricamento modello.
        model_load_progress: Progresso caricamento modello.
        process_started: Processo avviato.
        process_stopped: Processo fermato.
    """

    # -- Segnali OCR
    ocr_new_text = Signal(str)
    ocr_status_changed = Signal(str)
    ocr_error = Signal(str)
    ocr_completed = Signal()
    ocr_page_progress = Signal(str)  # "Pagina X/Y" per PDF multi-pagina

    # -- Segnali Batch
    batch_new_text = Signal(str)
    batch_status_changed = Signal(str)
    batch_progress = Signal(int)
    batch_error = Signal(str)
    batch_completed = Signal()

    # -- Segnali Modello
    model_loading = Signal(str)
    model_loaded = Signal(str, str)
    model_load_error = Signal(str)
    model_load_progress = Signal(str)

    # -- Segnali Processo
    process_started = Signal()
    process_stopped = Signal()

    def __init__(self, controller: AppController) -> None:
        """Inizializza il bridge e iscrive gli handler all'EventBus.

        Args:
            controller: Controller principale dell'applicazione.
        """
        super().__init__()
        self._controller = controller
        self._bus = EventBus()
        self._load_thread: QThread | None = None
        self._load_worker: ModelLoadWorker | None = None
        self._batch_running: bool = False
        self._subscribe_all()

    def _subscribe_all(self) -> None:
        """Iscrive tutti gli handler agli eventi dell'EventBus."""
        self._bus.subscribe("ocr_started", self._on_ocr_status)
        self._bus.subscribe("ocr_completed", self._on_ocr_completed)
        self._bus.subscribe("ocr_failed", self._on_ocr_failed)
        self._bus.subscribe("pdf_page_completed", self._on_pdf_page_completed)
        self._bus.subscribe("pdf_progress", self._on_pdf_progress)
        self._bus.subscribe("batch_progress", self._on_batch_progress)
        self._bus.subscribe("batch_completed", self._on_batch_completed_event)
        self._bus.subscribe("batch_failed", self._on_batch_failed)
        self._bus.subscribe("batch_task_completed", self._on_batch_task_completed)
        self._bus.subscribe("batch_task_failed", self._on_batch_task_failed)
        self._bus.subscribe("model_loading", self._on_model_loading)
        self._bus.subscribe("model_loaded", self._on_model_loaded)
        self._bus.subscribe("model_load_error", self._on_model_load_error)
        self._bus.subscribe("model_load_progress", self._on_model_load_progress)
        self._bus.subscribe("process_started", lambda _: self.process_started.emit())
        self._bus.subscribe("process_stopped", lambda _: self.process_stopped.emit())

    # -- Handler OCR

    def _on_ocr_status(self, data: object) -> None:
        """Converte evento OCR started in Signal Qt."""
        if isinstance(data, dict):
            self.ocr_status_changed.emit("running")

    def _on_ocr_completed(self, data: object) -> None:
        """Converte evento completamento OCR in Signal Qt.

        Per i PDF multi-pagina, il testo è già stato trasmesso
        pagina per pagina via pdf_page_completed, quindi non
        viene ri-emesso per evitare duplicazione nella GUI.
        """
        if self._batch_running:
            return
        if isinstance(data, dict):
            # Solo emetti il testo se NON è già stato trasmesso
            # pagina per pagina (PDF streaming)
            pages_streamed = data.get("pages_streamed", False)
            if not pages_streamed:
                text = data.get("text", "")
                if text:
                    self.ocr_new_text.emit(str(text))
            self.ocr_completed.emit()

    def _on_ocr_failed(self, data: object) -> None:
        """Converte evento fallimento OCR in Signal Qt."""
        if self._batch_running:
            return
        if isinstance(data, dict):
            self.ocr_error.emit(str(data.get("error", "Errore sconosciuto")))

    # -- Handler PDF streaming

    def _on_pdf_page_completed(self, data: object) -> None:
        """Converte evento completamento singola pagina PDF in Signal Qt.

        Ogni pagina completata viene mostrata subito nella GUI come
        checkpoint, senza aspettare la fine dell'intero PDF.
        """
        if self._batch_running:
            return
        if isinstance(data, dict):
            page_num = data.get("page_num", 0)
            total_pages = data.get("total_pages", 0)
            text = data.get("text", "")
            if text:
                # Aggiungi header pagina solo per PDF multi-pagina
                if total_pages > 1:
                    header = f"--- Pagina {page_num} ---"
                    self.ocr_new_text.emit(f"{header}\n{text}")
                else:
                    self.ocr_new_text.emit(str(text))

    def _on_pdf_progress(self, data: object) -> None:
        """Converte evento avanzamento PDF in Signal Qt.

        Aggiorna la barra di stato con il contatore di pagine.
        """
        if self._batch_running:
            return
        if isinstance(data, dict):
            page_num = data.get("page_num", 0)
            total_pages = data.get("total_pages", 0)
            self.ocr_page_progress.emit(f"Pagina {page_num}/{total_pages}")

    # -- Handler Batch

    def _on_batch_progress(self, data: object) -> None:
        """Converte evento progresso batch in Signal Qt."""
        self._batch_running = True
        if isinstance(data, dict):
            completed = data.get("completed", 0)
            total = data.get("total", 1)
            if total > 0:
                self.batch_progress.emit(int((completed / total) * 100))
            self.batch_status_changed.emit("running")

    def _on_batch_completed_event(self, data: object) -> None:
        """Converte evento completamento batch in Signal Qt."""
        self._batch_running = False
        self.batch_status_changed.emit("completed")
        self.batch_completed.emit()

    def _on_batch_failed(self, data: object) -> None:
        """Converte evento fallimento batch in Signal Qt."""
        if isinstance(data, dict):
            self.batch_error.emit(str(data.get("error", "Errore batch")))

    def _on_batch_task_completed(self, data: object) -> None:
        """Converte evento completamento singolo task batch in Signal Qt."""
        if isinstance(data, dict):
            text = data.get("text", "")
            image_path = data.get("image_path", "")
            if text:
                header = f"[{image_path}]" if image_path else ""
                self.batch_new_text.emit(f"{header}\n{text}" if header else str(text))

    def _on_batch_task_failed(self, data: object) -> None:
        """Converte evento fallimento singolo task batch in Signal Qt."""
        if isinstance(data, dict):
            image_path = data.get("image_path", "")
            error = data.get("error", "Errore sconosciuto")
            header = f"[{image_path}]" if image_path else ""
            self.batch_new_text.emit(f"{header}\n[Errore: {error}]")
            self.batch_error.emit(f"{image_path}: {error}" if image_path else str(error))

    # -- Handler Modello

    def _on_model_loading(self, data: object) -> None:
        """Converte evento caricamento modello in Signal Qt."""
        if isinstance(data, dict):
            self.model_loading.emit(str(data.get("device", "")))

    def _on_model_loaded(self, data: object) -> None:
        """Converte evento modello caricato in Signal Qt."""
        if isinstance(data, dict):
            self.model_loaded.emit(str(data.get("backend", "")), str(data.get("device", "")))

    def _on_model_load_error(self, data: object) -> None:
        """Converte evento errore caricamento in Signal Qt."""
        if isinstance(data, dict):
            self.model_load_error.emit(str(data.get("error", "Errore caricamento")))

    def _on_model_load_progress(self, data: object) -> None:
        """Converte evento progresso caricamento in Signal Qt."""
        if isinstance(data, dict):
            self.model_load_progress.emit(str(data.get("message", "")))

    # -- Caricamento modello via QThread

    def start_model_loading(self, device: str) -> None:
        """Avvia il caricamento del modello in un QThread separato.

        Args:
            device: Dispositivo target (llama-cpp / llama-cpp-sycl).
        """
        if self._is_load_thread_running():
            logger.info("Caricamento precedente in corso — cancello e avvio nuovo per %s", device)
            self._cancel_load_thread()

        self._load_thread = None
        self._load_worker = None

        self._load_thread = QThread()
        self._load_worker = ModelLoadWorker(self._controller, device)
        self._load_worker.moveToThread(self._load_thread)

        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.finished.connect(self._on_worker_finished)
        self._load_worker.error.connect(self._on_worker_error)
        self._load_worker.progress.connect(self.model_load_progress.emit)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.error.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._reset_load_thread_refs)

        self._load_thread.start()
        logger.info("Thread caricamento modello avviato per: %s", device)

    def _is_load_thread_running(self) -> bool:
        """Verifica se il thread di caricamento è in esecuzione."""
        if self._load_thread is None:
            return False
        try:
            return self._load_thread.isRunning()
        except RuntimeError:
            self._load_thread = None
            self._load_worker = None
            return False

    def _cancel_load_thread(self) -> None:
        """Cancella il thread di caricamento modello in corso."""
        if self._load_thread is None:
            return
        try:
            self._controller.engine.shutdown()
        except Exception:
            pass
        try:
            self._load_thread.quit()
            self._load_thread.wait(3000)
        except RuntimeError:
            pass
        self._load_thread = None
        self._load_worker = None

    @Slot()
    def _reset_load_thread_refs(self) -> None:
        """Resetta i riferimenti al thread worker dopo la terminazione."""
        self._load_thread = None
        self._load_worker = None

    @Slot(str, str)
    def _on_worker_finished(self, backend: str, device: str) -> None:
        """Slot chiamato al termine del caricamento del modello."""
        logger.info("Modello caricato — backend: %s, device: %s", backend, device)
        self.model_loaded.emit(backend, device)

    @Slot(str)
    def _on_worker_error(self, error_msg: str) -> None:
        """Slot chiamato in caso di errore nel caricamento."""
        logger.error("Errore caricamento modello: %s", error_msg)
        self.model_load_error.emit(error_msg)
