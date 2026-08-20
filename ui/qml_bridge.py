"""Bridge Python ↔ QML: stato UI senza duplicare la logica core."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from config.constants import AppMeta
from core.app_controller import (
    OP_BATCH,
    OP_IDLE,
    OP_MODEL_LOADING,
    OP_OCR,
    AppController,
)
from ui.event_bridge import EventBridge

_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("ita+eng", "Italiano + Inglese"),
    ("eng", "Inglese"),
    ("ita", "Italiano"),
    ("fra", "Francese"),
    ("deu", "Tedesco"),
    ("spa", "Spagnolo"),
)

_STATUS_LABELS = {
    "idle": "Pronto",
    "running": "In esecuzione",
    "processing": "Elaborazione OCR...",
    "buffering": "Elaborazione...",
    "error": "Errore",
    "loading_model": "Caricamento modello...",
    "stopped": "Arrestato",
    "completed": "Completato",
    "draining": "Arresto in corso...",
}

_STATUS_COLORS = {
    "idle": "#6F757C",
    "running": "#35C46A",
    "processing": "#35C46A",
    "buffering": "#E7A33D",
    "error": "#E15A36",
    "loading_model": "#FF6600",
    "stopped": "#6F757C",
    "completed": "#35C46A",
    "draining": "#FF6600",
}


class QmlBridge(QObject):
    """Espone a QML un'unica vista coerente dello stato applicativo."""

    stateChanged = Signal()

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self._controller = controller
        self._event_bridge = EventBridge(controller)
        self._window: Any | None = None
        self._shutting_down = False
        self._operation = controller.operation

        self._language = controller.settings.language
        self._preprocessing = controller.settings.preprocessing_enabled
        self._devices: list[dict[str, Any]] = []
        self._selected_device = controller.settings.default_device

        self._image_path: Path | None = None
        self._ocr_text = ""
        self._ocr_status_text = "Pronto"
        self._ocr_status_color = _STATUS_COLORS["idle"]
        self._ocr_page_progress = ""

        self._batch_paths: list[Path] = []
        self._batch_text = ""
        self._batch_status_text = "Pronto"
        self._batch_status_color = _STATUS_COLORS["idle"]
        self._batch_progress_text = ""
        self._batch_completed_count = 0
        self._batch_total_count = 0

        self._connect_events()
        self._refresh_devices(emit=False, refresh=False)

    # ------------------------------------------------------------------
    # Window / lifecycle
    # ------------------------------------------------------------------

    def set_window(self, window: Any) -> None:
        self._window = window

    @Slot()
    def showWindow(self) -> None:
        if self._window is None:
            return
        self._window.show()
        try:
            self._window.raise_()
            self._window.requestActivate()
        except (AttributeError, RuntimeError):
            pass

    @Slot()
    def minimizeToTray(self) -> None:
        if self._window is not None:
            self._window.hide()

    @Slot()
    def handleWindowClose(self) -> None:
        self._shutdown_controller()

    @Slot()
    def forceQuit(self) -> None:
        self._shutdown_controller()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    @Slot()
    def shutdown(self) -> None:
        self._shutdown_controller()

    def _shutdown_controller(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        try:
            self._controller.shutdown()
        finally:
            self._event_bridge.shutdown()

    # ------------------------------------------------------------------
    # Proprietà globali
    # ------------------------------------------------------------------

    @Property(int, constant=True)
    def initialWindowWidth(self) -> int:
        return self._controller.settings.window_width

    @Property(int, constant=True)
    def initialWindowHeight(self) -> int:
        return self._controller.settings.window_height

    @Property(str, notify=stateChanged)
    def operation(self) -> str:
        return self._operation

    @Property(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self._operation != OP_IDLE

    @Property(bool, notify=stateChanged)
    def modelLoading(self) -> bool:
        return self._operation == OP_MODEL_LOADING

    @Property("QVariantList", notify=stateChanged)
    def devices(self) -> list[dict[str, Any]]:
        return self._devices

    @Property(int, notify=stateChanged)
    def deviceIndex(self) -> int:
        for index, item in enumerate(self._devices):
            if item["type"] == self._selected_device:
                return index
        return 0

    @Property(int, notify=stateChanged)
    def languageIndex(self) -> int:
        for index, (code, _label) in enumerate(_LANGUAGES):
            if code == self._language:
                return index
        return 0

    @Property(bool, notify=stateChanged)
    def preprocessingEnabled(self) -> bool:
        return self._preprocessing

    # ------------------------------------------------------------------
    # OCR properties
    # ------------------------------------------------------------------

    @Property(str, notify=stateChanged)
    def ocrFileName(self) -> str:
        return self._image_path.name if self._image_path else "Nessun file selezionato"

    @Property(str, notify=stateChanged)
    def ocrFilePath(self) -> str:
        return str(self._image_path) if self._image_path else ""

    @Property(str, notify=stateChanged)
    def ocrText(self) -> str:
        return self._ocr_text

    @Property(str, notify=stateChanged)
    def ocrStatusText(self) -> str:
        return self._ocr_status_text

    @Property(str, notify=stateChanged)
    def ocrStatusColor(self) -> str:
        return self._ocr_status_color

    @Property(str, notify=stateChanged)
    def ocrPageProgress(self) -> str:
        return self._ocr_page_progress

    @Property(bool, notify=stateChanged)
    def ocrRunning(self) -> bool:
        return self._operation == OP_OCR

    # ------------------------------------------------------------------
    # Batch properties
    # ------------------------------------------------------------------

    @Property(str, notify=stateChanged)
    def batchDropText(self) -> str:
        count = len(self._batch_paths)
        if count == 0:
            return "Trascina qui immagini o PDF\no clicca per sfogliare"
        if count == 1:
            return "1 file selezionato"
        return f"{count} file selezionati"

    @Property(str, notify=stateChanged)
    def batchText(self) -> str:
        return self._batch_text

    @Property(str, notify=stateChanged)
    def batchStatusText(self) -> str:
        return self._batch_status_text

    @Property(str, notify=stateChanged)
    def batchStatusColor(self) -> str:
        return self._batch_status_color

    @Property(str, notify=stateChanged)
    def batchProgressText(self) -> str:
        return self._batch_progress_text

    @Property(str, notify=stateChanged)
    def batchCountText(self) -> str:
        if self._batch_total_count <= 0:
            return ""
        return f"{self._batch_completed_count}/{self._batch_total_count}"

    @Property(bool, notify=stateChanged)
    def batchRunning(self) -> bool:
        return self._operation == OP_BATCH

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    @Slot(int)
    def setLanguageIndex(self, index: int) -> None:
        if self.busy:
            return
        if 0 <= index < len(_LANGUAGES):
            self._language = _LANGUAGES[index][0]
            self._controller.update_settings(language=self._language)
            self.stateChanged.emit()

    @Slot(bool)
    def setPreprocessing(self, enabled: bool) -> None:
        if self.busy:
            return
        self._preprocessing = bool(enabled)
        self._controller.update_settings(preprocessing_enabled=self._preprocessing)
        self.stateChanged.emit()

    @Slot(int)
    def setDeviceIndex(self, index: int) -> None:
        if self.busy or not (0 <= index < len(self._devices)):
            return
        item = self._devices[index]
        if not bool(item.get("available", False)):
            return
        device = str(item["type"])
        if device == self._selected_device and self._controller.engine.is_initialized:
            return

        previous = self._selected_device
        self._selected_device = device
        self.stateChanged.emit()
        try:
            self._controller.switch_device(device)
        except Exception as exc:
            self._selected_device = previous
            self._set_ocr_error(str(exc))
            self._set_batch_error(str(exc))
            self.stateChanged.emit()

    @Slot()
    def refreshDevices(self) -> None:
        if self.busy:
            return
        self._refresh_devices(emit=True, refresh=True)

    def _refresh_devices(self, *, emit: bool, refresh: bool) -> None:
        devices = self._controller.get_available_devices(refresh=refresh)
        devices = sorted(
            devices,
            key=lambda device: (
                0 if device.device_type == "llama-cpp-sycl" else
                1 if device.device_type == "llama-cpp" else 2
            ),
        )
        self._devices = [
            {
                "type": device.device_type,
                "label": device.device_name + ("" if device.available else " (non pronto)"),
                "available": device.available,
            }
            for device in devices
        ]
        known = {item["type"] for item in self._devices}
        if self._selected_device not in known:
            available = next(
                (item["type"] for item in self._devices if item["available"]),
                None,
            )
            if available is not None:
                self._selected_device = str(available)
        if emit:
            self.stateChanged.emit()

    # ------------------------------------------------------------------
    # OCR singolo
    # ------------------------------------------------------------------

    @Slot()
    def chooseOcrFile(self) -> None:
        if self.busy:
            return
        extensions = " ".join(
            f"*{ext}" for ext in sorted(AppMeta.SUPPORTED_IMAGE_EXTENSIONS)
        )
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Seleziona immagine o PDF",
            "",
            f"File supportati ({extensions})",
        )
        if path:
            self._image_path = Path(path)
            self.stateChanged.emit()

    @Slot()
    def startOcr(self) -> None:
        if self.busy:
            return
        if not self._image_path or not self._image_path.exists():
            QMessageBox.information(
                None,
                "Nessun file",
                "Seleziona un'immagine o PDF prima di avviare.",
            )
            return
        if not self._controller.engine.is_initialized:
            self._set_ocr_status("loading_model")
            self.stateChanged.emit()
            return

        self._ocr_text = ""
        self._ocr_page_progress = ""
        try:
            self._controller.start_ocr(self._image_path)
        except Exception as exc:
            self._set_ocr_error(str(exc))
            self.stateChanged.emit()

    @Slot()
    def stopOcr(self) -> None:
        if self._operation != OP_OCR:
            return
        self._controller.cancel_ocr()
        self._set_ocr_status("draining")
        self.stateChanged.emit()

    @Slot()
    def clearOcr(self) -> None:
        if self.busy:
            return
        self._ocr_text = ""
        self._ocr_page_progress = ""
        self.stateChanged.emit()

    @Slot()
    def saveOcr(self) -> None:
        if self.busy:
            return
        if not self._ocr_text.strip():
            QMessageBox.information(None, "Nessun testo", "Non c'è testo da salvare.")
            return
        default_name = self._image_path.stem + ".txt" if self._image_path else "ocr_output.txt"
        save_path, _ = QFileDialog.getSaveFileName(
            None,
            "Salva testo OCR",
            default_name,
            "File di testo (*.txt)",
        )
        if save_path:
            try:
                Path(save_path).write_text(self._ocr_text, encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(None, "Errore salvataggio", f"Impossibile salvare:\n{exc}")

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    @Slot()
    def chooseBatchFiles(self) -> None:
        if self.busy:
            return
        extensions = " ".join(
            f"*{ext}" for ext in sorted(AppMeta.SUPPORTED_IMAGE_EXTENSIONS)
        )
        files, _ = QFileDialog.getOpenFileNames(
            None,
            "Seleziona file",
            "",
            f"File supportati ({extensions})",
        )
        if files:
            self._batch_paths = [Path(file) for file in files]
            self.stateChanged.emit()

    @Slot("QVariantList")
    def setBatchDroppedUrls(self, urls: list[Any]) -> None:
        if self.busy:
            return
        paths: list[Path] = []
        for value in urls:
            if isinstance(value, QUrl):
                local = value.toLocalFile()
            else:
                qurl = QUrl(str(value))
                local = qurl.toLocalFile() if qurl.isLocalFile() else ""
            if not local:
                continue
            path = Path(local)
            if (
                path.is_file()
                and path.suffix.lower() in AppMeta.SUPPORTED_IMAGE_EXTENSIONS
            ):
                paths.append(path)
        if paths:
            self._batch_paths = paths
            self.stateChanged.emit()

    @Slot()
    def startBatch(self) -> None:
        if self.busy:
            return
        if not self._batch_paths:
            QMessageBox.information(
                None,
                "Nessun file",
                "Seleziona almeno un file prima di avviare il batch.",
            )
            return
        if not self._controller.engine.is_initialized:
            QMessageBox.information(
                None,
                "Modello non pronto",
                "Attendi il caricamento del modello prima di avviare il batch.",
            )
            return

        self._batch_text = ""
        self._batch_completed_count = 0
        self._batch_total_count = len(self._batch_paths)
        self._batch_progress_text = "0%"
        try:
            self._controller.run_batch(self._batch_paths)
        except Exception as exc:
            self._set_batch_error(str(exc))
            self.stateChanged.emit()

    @Slot()
    def stopBatch(self) -> None:
        if self._operation != OP_BATCH:
            return
        self._controller.cancel_active_batch()
        self._set_batch_status("draining")
        self.stateChanged.emit()

    @Slot()
    def clearBatch(self) -> None:
        if self.busy:
            return
        self._batch_text = ""
        self._batch_completed_count = 0
        self._batch_total_count = 0
        self._batch_progress_text = ""
        self.stateChanged.emit()

    @Slot()
    def saveBatch(self) -> None:
        if self.busy:
            return
        if not self._batch_text.strip():
            QMessageBox.information(None, "Nessun testo", "Non c'è testo da salvare.")
            return
        save_path, _ = QFileDialog.getSaveFileName(
            None,
            "Salva testo batch",
            "batch_ocr.txt",
            "File di testo (*.txt)",
        )
        if save_path:
            try:
                Path(save_path).write_text(self._batch_text, encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(None, "Errore salvataggio", f"Impossibile salvare:\n{exc}")

    # ------------------------------------------------------------------
    # EventBridge
    # ------------------------------------------------------------------

    def _connect_events(self) -> None:
        bridge = self._event_bridge
        bridge.operation_changed.connect(self._on_operation_changed)

        bridge.ocr_new_text.connect(self._on_ocr_new_text)
        bridge.ocr_status_changed.connect(self._on_ocr_status)
        bridge.ocr_error.connect(self._on_ocr_error)
        bridge.ocr_completed.connect(self._on_ocr_completed)
        bridge.ocr_cancelled.connect(self._on_ocr_cancelled)
        bridge.ocr_page_progress.connect(self._on_ocr_page_progress)

        bridge.batch_new_text.connect(self._on_batch_new_text)
        bridge.batch_status_changed.connect(self._on_batch_status)
        bridge.batch_progress.connect(self._on_batch_progress)
        bridge.batch_error.connect(self._on_batch_error)
        bridge.batch_completed.connect(self._on_batch_completed)
        bridge.batch_cancelled.connect(self._on_batch_cancelled)

        bridge.model_loading.connect(self._on_model_loading)
        bridge.model_loaded.connect(self._on_model_loaded)
        bridge.model_load_cancelled.connect(self._on_model_load_cancelled)
        bridge.model_load_error.connect(self._on_model_load_error)
        bridge.model_load_progress.connect(self._on_model_load_progress)

    @Slot(str)
    def _on_operation_changed(self, operation: str) -> None:
        self._operation = operation or OP_IDLE
        self.stateChanged.emit()

    @Slot(str)
    def _on_ocr_new_text(self, text: str) -> None:
        if self._ocr_text and not self._ocr_text.endswith("\n"):
            self._ocr_text += "\n"
        self._ocr_text += text
        if not self._ocr_text.endswith("\n"):
            self._ocr_text += "\n"
        self.stateChanged.emit()

    @Slot(str)
    def _on_ocr_status(self, status: str) -> None:
        self._set_ocr_status(status)
        self.stateChanged.emit()

    @Slot(str)
    def _on_ocr_error(self, message: str) -> None:
        self._ocr_page_progress = ""
        self._set_ocr_error(message)
        self.stateChanged.emit()

    @Slot()
    def _on_ocr_completed(self) -> None:
        self._ocr_page_progress = ""
        self._set_ocr_status("completed")
        self.stateChanged.emit()

    @Slot()
    def _on_ocr_cancelled(self) -> None:
        self._ocr_page_progress = ""
        self._set_ocr_status("stopped")
        self.stateChanged.emit()

    @Slot(str)
    def _on_ocr_page_progress(self, text: str) -> None:
        self._ocr_page_progress = text
        self.stateChanged.emit()

    @Slot(str)
    def _on_batch_new_text(self, text: str) -> None:
        if self._batch_text and not self._batch_text.endswith("\n"):
            self._batch_text += "\n"
        self._batch_text += text
        if not self._batch_text.endswith("\n"):
            self._batch_text += "\n"
        self.stateChanged.emit()

    @Slot(str)
    def _on_batch_status(self, status: str) -> None:
        self._set_batch_status(status)
        self.stateChanged.emit()

    @Slot(int, int)
    def _on_batch_progress(self, completed: int, total: int) -> None:
        self._batch_completed_count = max(0, completed)
        self._batch_total_count = max(0, total)
        if total > 0:
            percent = int(round((completed / total) * 100))
            self._batch_progress_text = f"{max(0, min(100, percent))}%"
        else:
            self._batch_progress_text = ""
        self.stateChanged.emit()

    @Slot(str)
    def _on_batch_error(self, message: str) -> None:
        self._set_batch_error(message)
        self.stateChanged.emit()

    @Slot()
    def _on_batch_completed(self) -> None:
        if self._batch_total_count > 0:
            self._batch_completed_count = self._batch_total_count
            self._batch_progress_text = "100%"
        self._set_batch_status("completed")
        self.stateChanged.emit()

    @Slot()
    def _on_batch_cancelled(self) -> None:
        self._set_batch_status("stopped")
        self.stateChanged.emit()

    @Slot(str)
    def _on_model_loading(self, device: str) -> None:
        self._set_ocr_status("loading_model")
        self._set_batch_status("loading_model")
        self.stateChanged.emit()
        self._event_bridge.start_model_loading(device)

    @Slot(str, str)
    def _on_model_loaded(self, _backend: str, device: str) -> None:
        if device:
            self._selected_device = device
        self._set_ocr_status("idle")
        self._set_batch_status("idle")
        self.stateChanged.emit()
        # Nessun auto-start: cambiare device non deve lanciare OCR per un
        # file precedentemente selezionato.

    @Slot()
    def _on_model_load_cancelled(self) -> None:
        self._set_ocr_status("stopped")
        self._set_batch_status("stopped")
        self.stateChanged.emit()

    @Slot(str)
    def _on_model_load_error(self, message: str) -> None:
        self._set_ocr_error(f"Caricamento modello: {message}")
        self._set_batch_error(f"Caricamento modello: {message}")
        self.stateChanged.emit()

    @Slot(str)
    def _on_model_load_progress(self, message: str) -> None:
        self._ocr_status_text = message
        self._ocr_status_color = "#A7ADB4"
        self._batch_status_text = message
        self._batch_status_color = "#A7ADB4"
        self.stateChanged.emit()

    def _set_ocr_status(self, status: str) -> None:
        self._ocr_status_text = _STATUS_LABELS.get(status, status)
        self._ocr_status_color = _STATUS_COLORS.get(status, "#A7ADB4")

    def _set_batch_status(self, status: str) -> None:
        self._batch_status_text = _STATUS_LABELS.get(status, status)
        self._batch_status_color = _STATUS_COLORS.get(status, "#A7ADB4")

    def _set_ocr_error(self, message: str) -> None:
        self._ocr_status_text = f"Errore: {message}"
        self._ocr_status_color = _STATUS_COLORS["error"]

    def _set_batch_error(self, message: str) -> None:
        self._batch_status_text = f"Errore: {message}"
        self._batch_status_color = _STATUS_COLORS["error"]
