"""Native bridge exposed to the HTML/JavaScript frontend through QWebChannel."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

from config.constants import AppMeta
from core.app_controller import (
    OP_BATCH,
    OP_IDLE,
    OP_MODEL_LOADING,
    OP_OCR,
    AppController,
)
from ui.event_bridge import EventBridge

logger = logging.getLogger(__name__)


class WebBridge(QObject):
    """Thin presentation bridge; operational state remains in Python core."""

    event = Signal(str)

    def __init__(
        self,
        controller: AppController,
        window: QWidget | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._window = window
        self._events = EventBridge(controller, parent=self)
        self._events.event_received.connect(self._on_core_event)
        self._init_thread: threading.Thread | None = None
        self._init_thread_lock = threading.Lock()
        self._devices_snapshot: list[dict[str, Any]] = []
        self._shutdown = False

    def set_window(self, window: QWidget) -> None:
        self._window = window

    @staticmethod
    def _json(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, default=str)

    def _publish(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        clean_payload = {
            key: value
            for key, value in (payload or {}).items()
            if value is not None
        }
        self.event.emit(
            self._json({"type": event_name, "payload": clean_payload})
        )

    def _error(self, message: str, *, details: str = "") -> None:
        self._publish("ui_error", {"message": message, "details": details})

    @Slot(str, object)
    def _on_core_event(self, event_name: str, payload: object) -> None:
        data = dict(payload) if isinstance(payload, dict) else {}
        if event_name == "hardware_detected":
            devices = data.get("devices")
            if isinstance(devices, list):
                self._devices_snapshot = [
                    dict(item) for item in devices if isinstance(item, dict)
                ]
        self._publish(event_name, data)
        if event_name == "queued_operation_failed":
            kind = str(data.get("kind") or "operazione")
            self._error(
                f"Impossibile avviare {kind} dopo il caricamento del modello.",
                details=str(data.get("error") or ""),
            )

    def _device_dicts(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        return [
            {
                "device_name": item.device_name,
                "device_type": item.device_type,
                "available": item.available,
                "memory_mb": item.memory_mb,
            }
            for item in self._controller.get_available_devices(refresh=refresh)
        ]

    def _bootstrap_payload(self) -> dict[str, Any]:
        """Return already-available UI state without probing hardware."""
        settings = asdict(self._controller.settings)
        return {
            "app": {
                "name": AppMeta.NAME,
                "version": AppMeta.VERSION,
                "description": AppMeta.DESCRIPTION,
            },
            "settings": settings,
            "runtime": {
                "operation": self._controller.operation,
                "model_ready": self._controller.model_ready,
                "device": self._controller.model_device,
                "backend": self._controller.model_backend,
                "active_batch_id": self._controller.active_batch_id,
            },
            "devices": list(self._devices_snapshot),
            "limits": {
                "max_batch_size": AppMeta.MAX_BATCH_SIZE,
                "max_image_size_mb": AppMeta.MAX_IMAGE_SIZE_MB,
                "extensions": sorted(AppMeta.SUPPORTED_IMAGE_EXTENSIONS),
            },
            "paths": {
                "model_cache": str(AppMeta.GGUF_MODEL_DIR),
                "log": str(AppMeta.LOG_PATH),
            },
        }

    @Slot(result=str)
    def bootstrap(self) -> str:
        try:
            return self._json({"ok": True, "data": self._bootstrap_payload()})
        except Exception as exc:
            logger.exception("Bootstrap UI fallito")
            return self._json({"ok": False, "error": str(exc)})

    @Slot()
    def initializeBackend(self) -> None:
        """Initialize hardware detection/controller off the Qt GUI thread."""
        with self._init_thread_lock:
            if self._shutdown:
                return
            if self._init_thread is not None and self._init_thread.is_alive():
                return

            def initialize() -> None:
                try:
                    self._controller.initialize()
                except Exception as exc:
                    logger.exception("Inizializzazione controller fallita")
                    if not self._shutdown:
                        self._error(
                            "Impossibile inizializzare il backend OCR.",
                            details=str(exc),
                        )
                finally:
                    with self._init_thread_lock:
                        if self._init_thread is threading.current_thread():
                            self._init_thread = None

            thread = threading.Thread(
                target=initialize,
                name="backend-init-worker",
                daemon=True,
            )
            self._init_thread = thread
            thread.start()

    @staticmethod
    def _dialog_filter() -> str:
        return (
            "Documenti supportati (*.png *.jpg *.jpeg *.bmp *.tiff *.tif "
            "*.webp *.pdf *.gif);;Immagini (*.png *.jpg *.jpeg *.bmp *.tiff "
            "*.tif *.webp *.gif);;PDF (*.pdf);;Tutti i file (*)"
        )

    def _validate_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if not path.is_file():
            raise ValueError(f"File non trovato: {path}")
        if path.suffix.lower() not in AppMeta.SUPPORTED_IMAGE_EXTENSIONS:
            raise ValueError(
                f"Formato non supportato: {path.suffix or '(senza estensione)'}"
            )
        max_bytes = AppMeta.MAX_IMAGE_SIZE_MB * 1024 * 1024
        if path.stat().st_size > max_bytes:
            raise ValueError(
                f"{path.name} supera il limite di {AppMeta.MAX_IMAGE_SIZE_MB} MB"
            )
        return path.resolve()

    @Slot(result=str)
    def chooseSingleFile(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self._window,
            "Seleziona immagine o PDF",
            str(Path.home()),
            self._dialog_filter(),
        )
        if not path:
            return self._json({"ok": True, "cancelled": True})
        try:
            valid = self._validate_path(path)
            return self._json(
                {
                    "ok": True,
                    "cancelled": False,
                    "path": str(valid),
                    "name": valid.name,
                }
            )
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)})

    @Slot(result=str)
    def chooseBatchFiles(self) -> str:
        paths, _ = QFileDialog.getOpenFileNames(
            self._window,
            "Seleziona documenti OCR",
            str(Path.home()),
            self._dialog_filter(),
        )
        if not paths:
            return self._json({"ok": True, "cancelled": True, "paths": []})
        if len(paths) > AppMeta.MAX_BATCH_SIZE:
            return self._json(
                {
                    "ok": False,
                    "error": f"Massimo {AppMeta.MAX_BATCH_SIZE} file per batch.",
                }
            )
        try:
            valid = [str(self._validate_path(path)) for path in paths]
            return self._json({"ok": True, "cancelled": False, "paths": valid})
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)})

    @Slot(str, result=str)
    def startSingleOcr(self, raw_path: str) -> str:
        try:
            path = self._validate_path(raw_path)
            self._controller.start_ocr(path)
            return self._json({"ok": True})
        except Exception as exc:
            logger.warning("Avvio OCR rifiutato: %s", exc)
            self._error("Impossibile avviare l'OCR.", details=str(exc))
            return self._json({"ok": False, "error": str(exc)})

    @Slot(str, result=str)
    def startBatch(self, paths_json: str) -> str:
        try:
            raw_paths = json.loads(paths_json)
            if not isinstance(raw_paths, list):
                raise ValueError("Elenco file batch non valido")
            if not raw_paths:
                raise ValueError("Seleziona almeno un file")
            if len(raw_paths) > AppMeta.MAX_BATCH_SIZE:
                raise ValueError(
                    f"Massimo {AppMeta.MAX_BATCH_SIZE} file per batch"
                )
            paths = [self._validate_path(str(path)) for path in raw_paths]
            job = self._controller.run_batch(paths)
            return self._json({"ok": True, "job_id": job.job_id})
        except Exception as exc:
            logger.warning("Avvio batch rifiutato: %s", exc)
            self._error("Impossibile avviare il batch.", details=str(exc))
            return self._json({"ok": False, "error": str(exc)})

    @Slot(result=str)
    def cancelOperation(self) -> str:
        try:
            operation = self._controller.operation
            if operation == OP_MODEL_LOADING:
                self._controller.cancel_model_loading()
            elif operation == OP_OCR:
                self._controller.cancel_ocr()
            elif operation == OP_BATCH:
                self._controller.cancel_active_batch()
            return self._json({"ok": True, "operation": operation})
        except Exception as exc:
            self._error(
                "Impossibile annullare l'operazione.",
                details=str(exc),
            )
            return self._json({"ok": False, "error": str(exc)})

    @Slot(result=str)
    def reloadModel(self) -> str:
        try:
            if self._controller.operation != OP_IDLE:
                raise RuntimeError("Attendi la conclusione dell'operazione in corso")
            self._controller.request_model_load(
                self._controller.settings.default_device
            )
            return self._json({"ok": True})
        except Exception as exc:
            self._error("Impossibile ricaricare il modello.", details=str(exc))
            return self._json({"ok": False, "error": str(exc)})

    @Slot(result=str)
    def refreshHardware(self) -> str:
        try:
            devices = self._device_dicts(refresh=True)
            self._devices_snapshot = list(devices)
            return self._json({"ok": True, "devices": devices})
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)})

    @Slot(str, result=str)
    def updateSettings(self, payload_json: str) -> str:
        try:
            payload = json.loads(payload_json)
            if not isinstance(payload, dict):
                raise ValueError("Impostazioni non valide")
            allowed = {
                "language",
                "output_dir",
                "preprocessing_enabled",
            }
            overrides = {
                key: value for key, value in payload.items() if key in allowed
            }
            if "language" in overrides:
                overrides["language"] = (
                    str(overrides["language"]).strip() or "ita+eng"
                )
            if "output_dir" in overrides:
                overrides["output_dir"] = str(
                    Path(str(overrides["output_dir"])).expanduser()
                )
            if "preprocessing_enabled" in overrides:
                overrides["preprocessing_enabled"] = bool(
                    overrides["preprocessing_enabled"]
                )
            self._controller.update_settings(**overrides)
            return self._json(
                {"ok": True, "settings": asdict(self._controller.settings)}
            )
        except Exception as exc:
            logger.warning("Salvataggio impostazioni fallito: %s", exc)
            return self._json({"ok": False, "error": str(exc)})

    @Slot(str, result=str)
    def chooseOutputDirectory(self, current: str) -> str:
        start = current or str(Path.home())
        path = QFileDialog.getExistingDirectory(
            self._window,
            "Directory output",
            start,
        )
        if not path:
            return self._json({"ok": True, "cancelled": True})
        return self._json({"ok": True, "cancelled": False, "path": path})

    @Slot(int, int)
    def setWindowSize(self, width: int, height: int) -> None:
        if width < 320 or height < 320:
            return
        try:
            self._controller.update_settings(
                window_width=width,
                window_height=height,
            )
        except Exception:
            logger.exception("Impossibile salvare le dimensioni finestra")

    @Slot(int, result=str)
    def getLogs(self, max_lines: int = 400) -> str:
        max_lines = max(20, min(int(max_lines), 2000))
        try:
            if not AppMeta.LOG_PATH.exists():
                return ""
            lines = AppMeta.LOG_PATH.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
            return "\n".join(lines[-max_lines:])
        except OSError as exc:
            return f"Impossibile leggere il log: {exc}"

    @Slot(str)
    def copyText(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    @Slot()
    def showWindow(self) -> None:
        window = self._window
        if window is None:
            return
        window.show()
        if hasattr(window, "showNormal"):
            window.showNormal()
        window.raise_()
        window.activateWindow()

    @Slot()
    def forceQuit(self) -> None:
        window = self._window
        if window is not None and hasattr(window, "allow_close"):
            setattr(window, "allow_close", True)
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def shutdown(self, wait_ms: int = 5000) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._events.shutdown(wait_ms=wait_ms)
        try:
            self._controller.cancel_model_loading()
            self._controller.cancel_ocr()
            self._controller.cancel_active_batch()
        except Exception:
            logger.exception("Errore durante la cancellazione in shutdown")

        with self._init_thread_lock:
            init_thread = self._init_thread
        if init_thread is not None and init_thread.is_alive():
            init_thread.join(timeout=max(0.0, wait_ms / 1000.0))

        self._controller.shutdown()
