"""View-state adapter exposed to QML as ``backend``.

The QML files are a thin view: every piece of UI state (selection, progress,
results, notices, enabled/disabled rules) lives here so it can be unit-tested
without a scene graph. Application policy stays in ``core.AppController``.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    Property,
    QBuffer,
    QByteArray,
    QIODevice,
    QObject,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication

from config.constants import AppMeta, UIConstraints
from core.app_controller import (
    OP_BATCH,
    OP_IDLE,
    OP_MODEL_LOADING,
    OP_MODEL_UNLOADING,
    OP_OCR,
    OP_SHUTTING_DOWN,
    AppController,
)
from core.input_staging import InputStaging
from core.log_reader import read_log_tail
from ui.event_bridge import EventBridge

logger = logging.getLogger(__name__)

VIEW_TITLES = {
    "ocr": "Riconoscimento OCR",
    "batch": "Elaborazione batch",
    "logs": "Log applicazione",
    "settings": "Impostazioni",
}
OPERATION_LABELS = {
    OP_IDLE: "In attesa",
    OP_MODEL_LOADING: "Caricamento modello",
    OP_MODEL_UNLOADING: "Scaricamento modello",
    OP_OCR: "OCR in corso",
    OP_BATCH: "Batch in corso",
    OP_SHUTTING_DOWN: "Arresto",
}
CLIPBOARD_DISPLAY_NAME = "Immagine dagli appunti.png"
_STATE_QUEUED = "In coda"
_STATE_RUNNING = "In elaborazione"
_STATE_DONE = "Completato"
_STATE_ERROR = "Errore"
_STATE_CANCELLED = "Annullato"
_PROGRESS_HIDE_DELAY_MS = 700


def _basename(path: str) -> str:
    return Path(path).name if path else ""


class UiBackend(QObject):
    """Presentation state for the QML window; policy remains in the controller."""

    runtimeChanged = Signal()
    viewChanged = Signal()
    singleChanged = Signal()
    batchChanged = Signal()
    noticeChanged = Signal()
    settingsChanged = Signal()

    def __init__(
        self,
        controller: AppController,
        *,
        input_staging: InputStaging | None = None,
        choose_files: Callable[[bool], list[str]] | None = None,
        choose_directory: Callable[[str], str] | None = None,
        quit_application: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._input_staging = input_staging or InputStaging(
            AppMeta.INPUT_CACHE_DIR,
            max_bytes=AppMeta.MAX_IMAGE_SIZE_MB * 1024 * 1024,
        )
        self._choose_files = choose_files or _native_choose_files
        self._choose_directory = choose_directory or _native_choose_directory
        self._quit_application = quit_application or _quit_qt_application
        self._shutdown = False

        # runtime
        self._operation = controller.operation
        self._model_ready = controller.model_ready
        self._model_status_text = "Modello pronto" if self._model_ready else "Backend in inizializzazione"
        self._model_status_active = True
        self._backend_detected = False
        self._backend_available = False
        self._backend_label = ""
        self._view = "ocr"

        # single document
        self._single_path = ""
        self._single_name = ""
        self._single_text = ""
        self._single_is_pdf = False
        self._single_meta = "Il risultato apparirà qui."
        self._pdf_parts: list[str] = []
        self._completed_source = ""
        self._save_pending = False
        self._pending_request_id = ""
        self._single_progress = _Progress()

        # batch
        self._batch_paths: list[str] = []
        self._batch_states: dict[str, str] = {}
        self._batch_results: dict[str, tuple[bool, str]] = {}
        self._batch_progress = _Progress()

        # notice
        self._notice_visible = False
        self._notice_title = ""
        self._notice_message = ""
        self._notice_details = ""
        self._notice_urgent = False

        self._events = EventBridge(parent=self)
        self._events.event_received.connect(self._on_core_event)

        # Qt owns scheduling only; idle policy and state live in AppController.
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(30_000)
        self._idle_timer.timeout.connect(self._check_idle_unload)
        self._idle_timer.start()
        self._input_staging.purge_orphaned_sessions()

    # ------------------------------------------------------------------ helpers

    def _notice(self, title: str, message: str, details: str = "", urgent: bool = False) -> None:
        self._notice_visible = True
        self._notice_title = title
        self._notice_message = message
        self._notice_details = details
        self._notice_urgent = urgent
        self.noticeChanged.emit()

    def _set_operation(self, operation: str) -> None:
        self._operation = operation
        self.runtimeChanged.emit()
        self.batchChanged.emit()
        self.singleChanged.emit()

    def _set_model_status(self, text: str, active: bool) -> None:
        self._model_status_text = text
        self._model_status_active = active
        self.runtimeChanged.emit()

    def _is_idle(self) -> bool:
        return self._operation == OP_IDLE

    def _validate_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if not path.is_file():
            raise ValueError(f"File non trovato: {path}")
        if path.suffix.lower() not in AppMeta.SUPPORTED_IMAGE_EXTENSIONS:
            raise ValueError(f"Formato non supportato: {path.suffix or '(senza estensione)'}")
        max_bytes = AppMeta.MAX_IMAGE_SIZE_MB * 1024 * 1024
        if path.stat().st_size > max_bytes:
            raise ValueError(f"{path.name} supera il limite di {AppMeta.MAX_IMAGE_SIZE_MB} MB")
        return path.resolve()

    def _validate_many(self, raw_paths: list[str]) -> list[str]:
        if len(raw_paths) > AppMeta.MAX_BATCH_SIZE:
            raise ValueError(f"Massimo {AppMeta.MAX_BATCH_SIZE} file per batch.")
        validated: list[str] = []
        for raw in raw_paths:
            path = str(self._validate_path(str(raw)))
            if path not in validated:
                validated.append(path)
        return validated

    def _apply_single_selection(self, path: str, display_name: str = "") -> None:
        self._single_path = path
        self._single_name = display_name or _basename(path)
        self._single_meta = "Pronto per l'elaborazione."
        if self._completed_source != path:
            self._completed_source = ""
        self.singleChanged.emit()

    def _apply_batch_selection(self, paths: list[str]) -> None:
        self._batch_paths = list(paths)
        self._batch_states = {path: _STATE_QUEUED for path in self._batch_paths}
        self._batch_results.clear()
        self.batchChanged.emit()

    def _apply_local_inputs(self, paths: list[str], names: list[str] | None = None) -> None:
        """Route dropped/pasted inputs to the current view (or the natural one)."""
        if not self._is_idle() or not paths:
            return
        names = names or []
        if self._view == "batch":
            self._apply_batch_selection(paths)
            return
        if self._view == "ocr" and len(paths) == 1:
            self._apply_single_selection(paths[0], names[0] if names else "")
            return
        if len(paths) == 1:
            self.setView("ocr")
            self._apply_single_selection(paths[0], names[0] if names else "")
        else:
            self.setView("batch")
            self._apply_batch_selection(paths)

    def _hide_progress_later(self, progress: _Progress, signal: Any) -> None:
        def hide() -> None:
            # A new operation started meanwhile resets the value: keep it visible.
            if progress.value >= 1.0:
                progress.visible = False
                signal.emit()

        QTimer.singleShot(_PROGRESS_HIDE_DELAY_MS, self, hide)

    # ------------------------------------------------------------------ events

    @Slot(str, object)
    def _on_core_event(self, event_name: str, payload: object) -> None:
        if self._shutdown:
            return
        data: dict[str, Any] = dict(payload) if isinstance(payload, dict) else {}
        handler = getattr(self, f"_event_{event_name}", None)
        if handler is not None:
            handler(data)

    def _event_operation_changed(self, data: dict[str, Any]) -> None:
        self._set_operation(str(data.get("operation") or OP_IDLE))

    def _event_hardware_detected(self, data: dict[str, Any]) -> None:
        self._backend_detected = True
        self._backend_available = bool(data.get("available"))
        self._backend_label = str(data.get("label") or "")
        self.runtimeChanged.emit()
        self.singleChanged.emit()
        self.batchChanged.emit()

    def _error_event(self, message: str) -> Callable[[dict[str, Any]], None]:
        def handler(data: dict[str, Any]) -> None:
            self._notice("Operazione non disponibile", message, str(data.get("error") or ""), True)

        return handler

    def _event_backend_initialization_failed(self, data: dict[str, Any]) -> None:
        self._error_event("Impossibile inizializzare il backend OCR.")(data)

    def _event_hardware_refresh_failed(self, data: dict[str, Any]) -> None:
        self._error_event("Rilevamento hardware fallito.")(data)

    def _event_queued_operation_failed(self, data: dict[str, Any]) -> None:
        kind = str(data.get("kind") or "operazione")
        self._error_event(f"Impossibile avviare {kind} dopo il caricamento del modello.")(data)

    def _event_model_loading(self, _data: dict[str, Any]) -> None:
        self._model_ready = False
        self._set_model_status("Caricamento modello…", True)

    def _event_model_loaded(self, _data: dict[str, Any]) -> None:
        self._model_ready = True
        self._set_model_status("Modello pronto", True)

    def _event_model_load_progress(self, data: dict[str, Any]) -> None:
        self._set_model_status(str(data.get("message") or "Caricamento modello…"), True)

    def _event_model_load_cancelled(self, _data: dict[str, Any]) -> None:
        self._model_ready = False
        self._set_model_status("Caricamento annullato", False)

    def _event_model_load_failed(self, data: dict[str, Any]) -> None:
        self._model_ready = False
        self._set_model_status("Backend non pronto", False)
        self._notice(
            "Backend non disponibile",
            "Il modello OCR non è stato caricato.",
            str(data.get("error") or ""),
            True,
        )

    def _event_model_unloading(self, _data: dict[str, Any]) -> None:
        self._set_model_status("Scaricamento modello…", True)

    def _event_model_unloaded(self, _data: dict[str, Any]) -> None:
        self._model_ready = False
        self._set_model_status("Modello scaricato", False)

    def _event_model_unload_failed(self, data: dict[str, Any]) -> None:
        self._notice(
            "Modello non scaricato",
            "Il backend non è stato rilasciato correttamente.",
            str(data.get("error") or ""),
            True,
        )

    def _event_config_changed(self, data: dict[str, Any]) -> None:
        if set(data) - {"window_width", "window_height"}:
            self.settingsChanged.emit()

    def _event_ocr_started(self, data: dict[str, Any]) -> None:
        self._single_is_pdf = bool(data.get("is_pdf"))
        self._pdf_parts = []
        self._single_text = ""
        self._completed_source = ""
        self._single_meta = f"Elaborazione di {_basename(str(data.get('image_path') or self._single_path))}…"
        self._single_progress.show(
            "Preparazione PDF" if self._single_is_pdf else "Elaborazione immagine"
        )
        self.singleChanged.emit()

    def _event_pdf_progress(self, data: dict[str, Any]) -> None:
        if data.get("mode") != "single":
            return
        page = int(data.get("page_num") or 0)
        total = max(1, int(data.get("total_pages") or 1))
        self._single_progress.label = f"Pagina {page} di {total}"
        self._single_progress.set((page - 1) / total, f"{page} / {total}")
        self.singleChanged.emit()

    def _event_pdf_page_completed(self, data: dict[str, Any]) -> None:
        if data.get("mode") != "single":
            return
        page = int(data.get("page_num") or 0)
        total = max(1, int(data.get("total_pages") or 1))
        text = str(data.get("text") or "")
        self._pdf_parts.append(f"--- Pagina {page} ---\n{text}" if total > 1 else text)
        self._single_text = "\n\n".join(self._pdf_parts)
        self._single_progress.set(page / total, f"{page} / {total}")
        self.singleChanged.emit()

    def _event_ocr_completed(self, data: dict[str, Any]) -> None:
        self._single_text = str(data.get("text") or "")
        time_ms = float(data.get("time_ms") or 0)
        self._single_meta = f"{time_ms / 1000:.1f} s" if time_ms > 0 else "Elaborazione completata"
        self._completed_source = str(data.get("image_path") or self._single_path)
        self._single_progress.set(1.0, "Completato" if self._single_is_pdf else "100%")
        self.singleChanged.emit()
        self._hide_progress_later(self._single_progress, self.singleChanged)

    def _event_ocr_cancelled(self, _data: dict[str, Any]) -> None:
        self._single_progress.visible = False
        self._single_meta = "Operazione annullata."
        self._completed_source = ""
        self.singleChanged.emit()
        self._notice("OCR annullato", "L'elaborazione è stata interrotta.")

    def _event_ocr_failed(self, data: dict[str, Any]) -> None:
        self._single_progress.visible = False
        self._single_meta = "Elaborazione fallita."
        self._completed_source = ""
        self.singleChanged.emit()
        self._notice(
            "OCR non riuscito",
            "Il documento non è stato elaborato.",
            str(data.get("error") or ""),
            True,
        )

    def _event_batch_started(self, data: dict[str, Any]) -> None:
        self._batch_results.clear()
        self._batch_states = {path: _STATE_QUEUED for path in self._batch_paths}
        if self._batch_paths:
            self._batch_states[self._batch_paths[0]] = _STATE_RUNNING
        total = int(data.get("total_tasks") or len(self._batch_paths))
        self._batch_progress.show("Batch in corso", f"0 / {total}")
        self.batchChanged.emit()

    def _event_batch_task_completed(self, data: dict[str, Any]) -> None:
        path = str(data.get("image_path") or "")
        self._batch_states[path] = _STATE_DONE
        self._batch_results[path] = (True, str(data.get("text") or ""))
        self.batchChanged.emit()

    def _event_batch_task_failed(self, data: dict[str, Any]) -> None:
        path = str(data.get("image_path") or "")
        self._batch_states[path] = _STATE_ERROR
        self._batch_results[path] = (False, str(data.get("error") or "Errore sconosciuto"))
        self.batchChanged.emit()

    def _event_batch_progress(self, data: dict[str, Any]) -> None:
        completed = int(data.get("completed") or 0)
        total = max(1, int(data.get("total") or len(self._batch_paths) or 1))
        if completed < total:
            for path in self._batch_paths:
                if self._batch_states.get(path, _STATE_QUEUED) == _STATE_QUEUED:
                    self._batch_states[path] = _STATE_RUNNING
                    break
        self._batch_progress.set(completed / total, f"{completed} / {total}")
        self.batchChanged.emit()

    def _event_batch_completed(self, data: dict[str, Any]) -> None:
        count = len(self._batch_paths)
        self._batch_progress.label = "Batch completato"
        self._batch_progress.set(
            1.0, f"{data.get('completed') or count} / {data.get('total') or count}"
        )
        self.batchChanged.emit()
        self._hide_progress_later(self._batch_progress, self.batchChanged)

    def _event_batch_cancelled(self, _data: dict[str, Any]) -> None:
        for path in self._batch_paths:
            if self._batch_states.get(path) in (_STATE_QUEUED, _STATE_RUNNING):
                self._batch_states[path] = _STATE_CANCELLED
        self._batch_progress.label = "Batch annullato"
        self._batch_progress.value = 1.0
        self.batchChanged.emit()
        self._hide_progress_later(self._batch_progress, self.batchChanged)
        self._notice("Batch annullato", "L'elaborazione della coda è stata interrotta.")

    def _event_batch_failed(self, data: dict[str, Any]) -> None:
        self._batch_progress.label = "Batch terminato con errori"
        self._batch_progress.value = 1.0
        self.batchChanged.emit()
        self._hide_progress_later(self._batch_progress, self.batchChanged)
        self._notice(
            "Batch non completato",
            "Uno o più documenti non sono stati elaborati.",
            str(data.get("error") or ""),
            True,
        )

    def _finish_manual_save(self, data: dict[str, Any]) -> bool:
        request_id = str(data.get("request_id") or "")
        if not self._save_pending:
            return False
        if self._pending_request_id and request_id and request_id != self._pending_request_id:
            return False
        self._save_pending = False
        self._pending_request_id = ""
        self.singleChanged.emit()
        return True

    def _event_single_output_saved(self, data: dict[str, Any]) -> None:
        if not self._finish_manual_save(data):
            return
        if data.get("kind") == "pages":
            self._notice(
                "Pagine PDF salvate",
                f"{int(data.get('count') or 0)} file pagina salvati nella directory output configurata.",
                "\n".join(str(path) for path in data.get("paths") or []),
            )
        else:
            self._notice(
                "Risultato salvato",
                f"{data.get('name') or 'Risultato OCR'} salvato nella directory output configurata.",
                str(data.get("path") or ""),
            )

    def _event_single_output_save_failed(self, data: dict[str, Any]) -> None:
        if not self._finish_manual_save(data):
            return
        self._notice(
            "Pagine non salvate" if data.get("kind") == "pages" else "Risultato non salvato",
            "Impossibile scrivere il file di output.",
            str(data.get("error") or ""),
            True,
        )

    def _event_batch_output_save_failed(self, data: dict[str, Any]) -> None:
        source = str(data.get("image_path") or "")
        self._notice(
            "Output batch non salvato",
            f"Impossibile salvare {_basename(source)}." if source
            else "Impossibile salvare un risultato del batch.",
            str(data.get("error") or ""),
            True,
        )

    def _event_batch_output_summary(self, data: dict[str, Any]) -> None:
        saved = int(data.get("saved") or 0)
        failed = int(data.get("failed") or 0)
        output_dir = str(data.get("output_dir") or "")
        if failed == 0 and saved > 0:
            noun = "risultato salvato" if saved == 1 else "risultati salvati"
            self._notice("Output batch salvato", f"{saved} {noun} automaticamente.", output_dir)
        elif failed > 0:
            self._notice(
                "Salvataggio batch incompleto",
                f"{saved} salvati, {failed} non salvati.",
                output_dir,
                True,
            )

    # ------------------------------------------------------------------ runtime properties

    def _get_operation(self) -> str:
        return self._operation

    def _get_busy(self) -> bool:
        return not self._is_idle()

    def _get_model_ready(self) -> bool:
        return self._model_ready

    def _get_model_status_text(self) -> str:
        return self._model_status_text

    def _get_model_status_active(self) -> bool:
        return self._model_status_active

    def _get_sidebar_status_text(self) -> str:
        if not self._is_idle():
            return OPERATION_LABELS.get(self._operation, self._operation)
        if self._model_ready:
            return "Pronto"
        return "Modello scaricato" if self._backend_available else "Backend non pronto"

    def _get_sidebar_status_active(self) -> bool:
        return self._model_ready or not self._is_idle()

    def _get_global_cancel_visible(self) -> bool:
        return not self._is_idle() and self._operation not in (OP_SHUTTING_DOWN, OP_MODEL_UNLOADING)

    def _section_label(self, operation: str) -> str:
        return OPERATION_LABELS[operation] if self._operation == operation else "In attesa"

    def _get_ocr_operation_label(self) -> str:
        return self._section_label(OP_OCR)

    def _get_batch_operation_label(self) -> str:
        return self._section_label(OP_BATCH)

    def _get_backend_device(self) -> str:
        return self._backend_label or "llama.cpp + SYCL"

    def _get_backend_availability(self) -> str:
        if not self._backend_detected:
            return "Non rilevato"
        return "Disponibile" if self._backend_available else "Non disponibile"

    def _get_backend_chip_text(self) -> str:
        if self._model_ready:
            return "Pronto"
        if not self._backend_detected:
            return "Verifica"
        if self._backend_available:
            return "Scaricato" if self._is_idle() else "Disponibile"
        return "Non pronto"

    def _get_backend_chip_active(self) -> bool:
        return self._model_ready

    def _get_can_reload_model(self) -> bool:
        return self._is_idle() and self._backend_usable()

    def _get_reload_model_label(self) -> str:
        return "Ricarica modello" if self._model_ready else "Carica modello"

    def _get_can_unload_model(self) -> bool:
        return self._is_idle() and self._model_ready

    def _get_model_cache_path(self) -> str:
        return str(AppMeta.GGUF_MODEL_DIR)

    def _get_app_version(self) -> str:
        return AppMeta.VERSION

    def _get_semi_bold_weight(self) -> int:
        return semi_bold_weight()

    operation = Property(str, _get_operation, notify=runtimeChanged)
    busy = Property(bool, _get_busy, notify=runtimeChanged)
    modelReady = Property(bool, _get_model_ready, notify=runtimeChanged)
    modelStatusText = Property(str, _get_model_status_text, notify=runtimeChanged)
    modelStatusActive = Property(bool, _get_model_status_active, notify=runtimeChanged)
    sidebarStatusText = Property(str, _get_sidebar_status_text, notify=runtimeChanged)
    sidebarStatusActive = Property(bool, _get_sidebar_status_active, notify=runtimeChanged)
    globalCancelVisible = Property(bool, _get_global_cancel_visible, notify=runtimeChanged)
    ocrOperationLabel = Property(str, _get_ocr_operation_label, notify=runtimeChanged)
    batchOperationLabel = Property(str, _get_batch_operation_label, notify=runtimeChanged)
    backendDevice = Property(str, _get_backend_device, notify=runtimeChanged)
    backendAvailability = Property(str, _get_backend_availability, notify=runtimeChanged)
    backendChipText = Property(str, _get_backend_chip_text, notify=runtimeChanged)
    backendChipActive = Property(bool, _get_backend_chip_active, notify=runtimeChanged)
    canReloadModel = Property(bool, _get_can_reload_model, notify=runtimeChanged)
    reloadModelLabel = Property(str, _get_reload_model_label, notify=runtimeChanged)
    canUnloadModel = Property(bool, _get_can_unload_model, notify=runtimeChanged)
    modelCachePath = Property(str, _get_model_cache_path, constant=True)
    appVersion = Property(str, _get_app_version, constant=True)
    semiBoldWeight = Property(int, _get_semi_bold_weight, constant=True)

    # ------------------------------------------------------------------ view

    def _get_view(self) -> str:
        return self._view

    def _get_view_title(self) -> str:
        return VIEW_TITLES.get(self._view, "GLM OCR")

    view = Property(str, _get_view, notify=viewChanged)
    viewTitle = Property(str, _get_view_title, notify=viewChanged)

    @Slot(str)
    def setView(self, name: str) -> None:
        if name in VIEW_TITLES and name != self._view:
            self._view = name
            self.viewChanged.emit()

    # ------------------------------------------------------------------ single properties

    def _has_savable_result(self) -> bool:
        return bool(
            self._single_text
            and self._single_path
            and self._completed_source == self._single_path
        )

    def _get_single_name(self) -> str:
        return self._single_name or "Nessun file selezionato"

    def _get_single_path(self) -> str:
        return self._single_path

    def _get_single_text(self) -> str:
        return self._single_text

    def _get_single_meta(self) -> str:
        return self._single_meta

    def _get_can_choose_single(self) -> bool:
        return self._is_idle()

    def _backend_usable(self) -> bool:
        # A loaded model proves the runtime works even if a later probe failed.
        return self._model_ready or self._backend_available

    def _get_can_start_single(self) -> bool:
        return self._is_idle() and self._backend_usable() and bool(self._single_path)

    def _get_can_cancel_single(self) -> bool:
        return self._operation == OP_OCR

    def _get_can_save_single(self) -> bool:
        return self._has_savable_result() and not self._save_pending

    def _get_show_page_save(self) -> bool:
        return self._has_savable_result() and self._single_is_pdf

    def _get_can_copy_single(self) -> bool:
        return bool(self._single_text)

    def _get_single_progress_visible(self) -> bool:
        return self._single_progress.visible

    def _get_single_progress(self) -> float:
        return self._single_progress.value

    def _get_single_progress_label(self) -> str:
        return self._single_progress.label

    def _get_single_progress_value(self) -> str:
        return self._single_progress.text

    singleName = Property(str, _get_single_name, notify=singleChanged)
    singlePath = Property(str, _get_single_path, notify=singleChanged)
    singleText = Property(str, _get_single_text, notify=singleChanged)
    singleMeta = Property(str, _get_single_meta, notify=singleChanged)
    canChooseSingle = Property(bool, _get_can_choose_single, notify=singleChanged)
    canStartSingle = Property(bool, _get_can_start_single, notify=singleChanged)
    canCancelSingle = Property(bool, _get_can_cancel_single, notify=singleChanged)
    canSaveSingle = Property(bool, _get_can_save_single, notify=singleChanged)
    showPageSave = Property(bool, _get_show_page_save, notify=singleChanged)
    canCopySingle = Property(bool, _get_can_copy_single, notify=singleChanged)
    singleProgressVisible = Property(bool, _get_single_progress_visible, notify=singleChanged)
    singleProgress = Property(float, _get_single_progress, notify=singleChanged)
    singleProgressLabel = Property(str, _get_single_progress_label, notify=singleChanged)
    singleProgressValue = Property(str, _get_single_progress_value, notify=singleChanged)

    # ------------------------------------------------------------------ batch properties

    def _get_batch_files(self) -> list[dict[str, Any]]:
        return [
            {
                "path": path,
                "name": _basename(path),
                "state": self._batch_states.get(path, _STATE_QUEUED),
                "active": self._batch_states.get(path) in (_STATE_DONE, _STATE_RUNNING),
            }
            for path in self._batch_paths
        ]

    def _get_batch_results(self) -> list[dict[str, Any]]:
        rows = []
        for path in self._batch_paths:
            if path not in self._batch_results:
                continue
            ok, text = self._batch_results[path]
            rows.append(
                {
                    "path": path,
                    "name": _basename(path),
                    "ok": ok,
                    "text": text or "Nessun testo restituito.",
                }
            )
        return rows

    def _get_batch_count_label(self) -> str:
        count = len(self._batch_paths)
        return f"{count} {'file selezionato' if count == 1 else 'file selezionati'}"

    def _get_can_start_batch(self) -> bool:
        return self._is_idle() and self._backend_usable() and bool(self._batch_paths)

    def _get_can_cancel_batch(self) -> bool:
        return self._operation == OP_BATCH

    def _get_batch_progress_visible(self) -> bool:
        return self._batch_progress.visible

    def _get_batch_progress(self) -> float:
        return self._batch_progress.value

    def _get_batch_progress_label(self) -> str:
        return self._batch_progress.label

    def _get_batch_progress_value(self) -> str:
        return self._batch_progress.text

    batchFiles = Property("QVariantList", _get_batch_files, notify=batchChanged)
    batchResults = Property("QVariantList", _get_batch_results, notify=batchChanged)
    batchCountLabel = Property(str, _get_batch_count_label, notify=batchChanged)
    canStartBatch = Property(bool, _get_can_start_batch, notify=batchChanged)
    canCancelBatch = Property(bool, _get_can_cancel_batch, notify=batchChanged)
    batchProgressVisible = Property(bool, _get_batch_progress_visible, notify=batchChanged)
    batchProgress = Property(float, _get_batch_progress, notify=batchChanged)
    batchProgressLabel = Property(str, _get_batch_progress_label, notify=batchChanged)
    batchProgressValue = Property(str, _get_batch_progress_value, notify=batchChanged)

    # ------------------------------------------------------------------ notice properties

    def _get_notice_visible(self) -> bool:
        return self._notice_visible

    def _get_notice_title(self) -> str:
        return self._notice_title

    def _get_notice_message(self) -> str:
        return self._notice_message

    def _get_notice_details(self) -> str:
        return self._notice_details

    def _get_notice_urgent(self) -> bool:
        return self._notice_urgent

    noticeVisible = Property(bool, _get_notice_visible, notify=noticeChanged)
    noticeTitle = Property(str, _get_notice_title, notify=noticeChanged)
    noticeMessage = Property(str, _get_notice_message, notify=noticeChanged)
    noticeDetails = Property(str, _get_notice_details, notify=noticeChanged)
    noticeUrgent = Property(bool, _get_notice_urgent, notify=noticeChanged)

    @Slot()
    def dismissNotice(self) -> None:
        if self._notice_visible:
            self._notice_visible = False
            self.noticeChanged.emit()

    # ------------------------------------------------------------------ settings

    def _get_settings(self) -> dict[str, Any]:
        return asdict(self._controller.settings)

    settings = Property("QVariantMap", _get_settings, notify=settingsChanged)

    @Slot("QVariantMap", result=bool)
    def saveSettings(self, values: dict[str, Any]) -> bool:
        allowed = {
            "output_dir",
            "preprocessing_enabled",
            "batch_auto_save",
            "batch_output_format",
            "batch_save_pdf_pages",
            "load_model_at_startup",
            "model_auto_unload_minutes",
        }
        overrides = {key: value for key, value in dict(values).items() if key in allowed}
        if "model_auto_unload_minutes" in overrides:
            # QML numbers arrive as float.
            minutes = overrides["model_auto_unload_minutes"]
            if isinstance(minutes, float) and minutes.is_integer():
                overrides["model_auto_unload_minutes"] = int(minutes)
        try:
            self._controller.update_settings(**overrides)
        except Exception as exc:
            logger.warning("Salvataggio impostazioni fallito: %s", exc)
            self._notice("Impostazioni non salvate", str(exc), "", True)
            return False
        self.settingsChanged.emit()
        self._notice("Impostazioni salvate", "Le preferenze sono state aggiornate.")
        return True

    @Slot(int, int)
    def saveWindowSize(self, width: int, height: int) -> None:
        if width < UIConstraints.WINDOW_MIN_WIDTH or height < UIConstraints.WINDOW_MIN_HEIGHT:
            return  # e.g. a tiling WM squeezed the window: keep the last real size
        try:
            self._controller.update_settings(window_width=int(width), window_height=int(height))
        except Exception:
            logger.exception("Impossibile salvare le dimensioni finestra")

    @Slot(str, result=str)
    def chooseOutputDirectory(self, current: str) -> str:
        return self._choose_directory(current or str(Path.home()))

    # ------------------------------------------------------------------ actions

    @Slot()
    def initialize(self) -> None:
        if self._shutdown:
            return
        try:
            self._controller.request_initialize()
        except Exception as exc:
            logger.exception("Richiesta inizializzazione controller fallita")
            self._notice("Operazione non disponibile", "Impossibile inizializzare il backend OCR.", str(exc), True)

    @Slot()
    def chooseSingleFile(self) -> None:
        if not self._is_idle():
            return
        paths = self._choose_files(False)
        if not paths:
            return
        try:
            self._apply_single_selection(str(self._validate_path(paths[0])))
        except Exception as exc:
            self._notice("File non valido", str(exc), "", True)

    @Slot()
    def chooseBatchFiles(self) -> None:
        if not self._is_idle():
            return
        paths = self._choose_files(True)
        if not paths:
            return
        try:
            self._apply_batch_selection(self._validate_many(paths))
        except Exception as exc:
            self._notice("Selezione batch non valida", str(exc), "", True)

    @Slot("QVariantList")
    def acceptDroppedUrls(self, urls: list[Any]) -> None:
        if self._shutdown:
            return
        if not self._is_idle():
            self._notice(
                "Operazione non disponibile",
                "Attendi la conclusione dell'operazione prima di cambiare file.",
                "",
                True,
            )
            return
        local = []
        for url in urls:
            qurl = url if isinstance(url, QUrl) else QUrl(str(url))
            if qurl.isLocalFile():
                local.append(qurl.toLocalFile())
        if not local:
            return
        try:
            validated = self._validate_many(local)
        except Exception as exc:
            logger.warning("Drop file rifiutato: %s", exc)
            self._notice("Operazione non disponibile", "File trascinato non valido.", str(exc), True)
            return
        self._apply_local_inputs(validated)

    @Slot()
    def pasteClipboardImage(self) -> None:
        if self._shutdown or not self._is_idle():
            return
        try:
            image = QGuiApplication.clipboard().image()
            if image.isNull():
                raise ValueError("La clipboard non contiene un'immagine")
            data = QByteArray()
            buffer = QBuffer(data)
            if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
                raise RuntimeError("Impossibile preparare l'immagine clipboard")
            try:
                if not image.save(buffer, "PNG"):
                    raise RuntimeError("Impossibile convertire l'immagine clipboard in PNG")
            finally:
                buffer.close()
            staged = self._validate_path(str(self._input_staging.stage_png(bytes(data))))
        except Exception as exc:
            logger.warning("Immagine clipboard rifiutata: %s", exc)
            self._notice(
                "Clipboard non disponibile",
                str(exc) or "Impossibile incollare l'immagine dagli appunti.",
                "",
                True,
            )
            return
        self._apply_local_inputs([str(staged)], [CLIPBOARD_DISPLAY_NAME])

    @Slot()
    def startSingleOcr(self) -> None:
        if not self._single_path:
            return
        try:
            path = self._validate_path(self._single_path)
            self._controller.start_ocr_or_queue(path)
        except Exception as exc:
            logger.warning("Avvio OCR rifiutato: %s", exc)
            self._notice("OCR non avviato", str(exc) or "Operazione non disponibile.", "", True)

    @Slot()
    def startBatch(self) -> None:
        try:
            if not self._batch_paths:
                raise ValueError("Seleziona almeno un file")
            paths = [Path(path) for path in self._validate_many(self._batch_paths)]
            self._controller.run_batch_or_queue(paths)
        except Exception as exc:
            logger.warning("Avvio batch rifiutato: %s", exc)
            self._notice("Batch non avviato", str(exc) or "Operazione non disponibile.", "", True)

    @Slot(str)
    def removeBatchFile(self, path: str) -> None:
        if not self._is_idle() or path not in self._batch_paths:
            return
        self._batch_paths.remove(path)
        self._batch_states.pop(path, None)
        self._batch_results.pop(path, None)
        self.batchChanged.emit()

    @Slot()
    def cancelOperation(self) -> None:
        operation = self._controller.operation
        try:
            if operation == OP_MODEL_LOADING:
                self._controller.cancel_model_loading()
            elif operation == OP_OCR:
                self._controller.cancel_ocr()
            elif operation == OP_BATCH:
                self._controller.cancel_active_batch()
        except Exception as exc:
            self._notice("Operazione non disponibile", "Impossibile annullare l'operazione.", str(exc), True)

    @Slot()
    def reloadModel(self) -> None:
        try:
            if not self._is_idle():
                raise RuntimeError("Attendi la conclusione dell'operazione in corso")
            self._controller.request_model_load()
        except Exception as exc:
            self._notice("Modello non ricaricato", str(exc), "", True)

    @Slot()
    def unloadModel(self) -> None:
        try:
            if not self._is_idle():
                raise RuntimeError("Attendi la conclusione dell'operazione in corso")
            self._controller.request_model_unload()
        except Exception as exc:
            self._notice("Modello non scaricato", str(exc), "", True)

    @Slot()
    def refreshHardware(self) -> None:
        try:
            self._controller.request_hardware_refresh()
        except Exception as exc:
            self._notice("Rilevamento hardware fallito", str(exc), "", True)

    def _request_save(self, request: Callable[[str, str], str], fmt: str, failure: str) -> None:
        self._save_pending = True
        self._pending_request_id = ""
        self.singleChanged.emit()
        try:
            request_id = request(self._completed_source, fmt)
        except Exception as exc:
            self._save_pending = False
            self.singleChanged.emit()
            self._notice(failure, str(exc) or "Impossibile avviare il salvataggio.", "", True)
            return
        # The worker may already have finished (queued event not yet delivered):
        # only remember the id while the request is still pending.
        if self._save_pending:
            self._pending_request_id = request_id

    @Slot(str)
    def saveSingle(self, fmt: str) -> None:
        if not self._has_savable_result():
            self._notice(
                "Nessun risultato da salvare",
                "Completa l'OCR sul documento selezionato prima di salvare.",
            )
            return
        self._request_save(self._controller.request_save_single_result, fmt, "Risultato non salvato")

    @Slot(str)
    def saveSinglePages(self, fmt: str) -> None:
        if not (self._has_savable_result() and self._single_is_pdf):
            self._notice(
                "Pagine non disponibili",
                "Completa l'OCR di un PDF prima di salvare le pagine separate.",
            )
            return
        self._request_save(self._controller.request_save_single_pdf_pages, fmt, "Pagine non salvate")

    @Slot(str)
    def copyText(self, text: str) -> None:
        if text:
            QGuiApplication.clipboard().setText(text)

    @Slot(int, result=str)
    def readLogs(self, max_lines: int = 600) -> str:
        try:
            text = read_log_tail(AppMeta.LOG_PATH, max(20, min(int(max_lines), 2000)))
        except OSError as exc:
            return f"Impossibile leggere il log: {exc}"
        return text or "Nessuna riga di log disponibile."

    @Slot()
    def quit(self) -> None:
        self._quit_application()

    def _check_idle_unload(self) -> None:
        if self._shutdown:
            return
        try:
            self._controller.check_idle_model_unload()
        except Exception:
            logger.exception("Auto-unload modello non avviato")

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._idle_timer.stop()
        self._events.shutdown()
        self._input_staging.shutdown()
        self._controller.shutdown()


class _Progress:
    """Mutable progress-bar state for one section."""

    def __init__(self) -> None:
        self.visible = False
        self.value = 0.0
        self.label = ""
        self.text = ""

    def show(self, label: str, text: str = "") -> None:
        self.visible = True
        self.label = label
        self.value = 0.0
        self.text = text

    def set(self, value: float, text: str) -> None:
        self.value = max(0.0, min(1.0, float(value)))
        self.text = text


def semi_bold_weight() -> int:
    """Weight that renders CSS ``font-weight: 600`` like Chromium does.

    Without a SemiBold face Chromium picks the next heavier one (Bold), while
    Qt would fall back to Medium; mirror the CSS rule explicitly.
    """
    from PySide6.QtGui import QFont, QFontDatabase, QFontInfo

    family = QFontInfo(QGuiApplication.font()).family() if QGuiApplication.instance() else ""
    weights = {
        QFontDatabase.weight(family, style) for style in QFontDatabase.styles(family)
    } if family else set()
    return int(QFont.Weight.DemiBold) if int(QFont.Weight.DemiBold) in weights else int(QFont.Weight.Bold)


def _supported_filter() -> str:
    patterns = " ".join(f"*{ext}" for ext in sorted(AppMeta.SUPPORTED_IMAGE_EXTENSIONS))
    images = " ".join(
        f"*{ext}" for ext in sorted(AppMeta.SUPPORTED_IMAGE_EXTENSIONS) if ext != ".pdf"
    )
    return (
        f"Documenti supportati ({patterns});;Immagini ({images});;"
        "PDF (*.pdf);;Tutti i file (*)"
    )


def _native_choose_files(multiple: bool) -> list[str]:
    from PySide6.QtWidgets import QFileDialog

    if multiple:
        paths, _ = QFileDialog.getOpenFileNames(
            None, "Seleziona documenti OCR", str(Path.home()), _supported_filter()
        )
        return list(paths)
    path, _ = QFileDialog.getOpenFileName(
        None, "Seleziona immagine o PDF", str(Path.home()), _supported_filter()
    )
    return [path] if path else []


def _native_choose_directory(current: str) -> str:
    from PySide6.QtWidgets import QFileDialog

    return QFileDialog.getExistingDirectory(None, "Directory output", current)


def _quit_qt_application() -> None:
    app = QGuiApplication.instance()
    if app is not None:
        app.quit()
