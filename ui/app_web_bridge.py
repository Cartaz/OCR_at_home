"""Application WebBridge capabilities beyond base OCR presentation."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QTimer, Slot

from core.app_controller import OP_IDLE
from core.exceptions import OperationCancelledError
from ui.web_bridge import WebBridge

logger = logging.getLogger(__name__)


class AppWebBridge(WebBridge):
    """Presentation adapter for model-memory and output actions."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pending_model_action: tuple[str, Callable[[], None]] | None = None
        self._pending_model_action_lock = threading.Lock()
        self._idle_since = time.monotonic()
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(30_000)
        self._idle_timer.timeout.connect(self._check_idle_unload)
        self._idle_timer.start()

    def _touch_idle_clock(self) -> None:
        self._idle_since = time.monotonic()

    def _clear_pending_model_action(self) -> None:
        with self._pending_model_action_lock:
            self._pending_model_action = None

    def _take_pending_model_action(self) -> tuple[str, Callable[[], None]] | None:
        with self._pending_model_action_lock:
            pending = self._pending_model_action
            self._pending_model_action = None
            return pending

    def _run_pending_model_action(self) -> None:
        pending = self._take_pending_model_action()
        if pending is None or self._shutdown:
            return
        label, action = pending
        try:
            action()
        except Exception as exc:
            logger.exception("Operazione accodata dopo model load fallita: %s", label)
            self._error(
                f"Impossibile avviare {label} dopo il caricamento del modello.",
                details=str(exc),
            )

    def _queue_after_model_load(self, label: str, action: Callable[[], None]) -> None:
        if self._controller.operation != OP_IDLE:
            raise RuntimeError("Attendi la conclusione dell'operazione in corso")
        with self._pending_model_action_lock:
            if self._pending_model_action is not None:
                raise RuntimeError("Un'operazione è già in attesa del caricamento modello")
            self._pending_model_action = (label, action)
        try:
            self._controller.request_model_load(
                self._controller.settings.default_device
            )
        except Exception:
            self._clear_pending_model_action()
            raise

    @Slot(str, object)
    def _on_core_event(self, event_name: str, payload: object) -> None:
        data = dict(payload) if isinstance(payload, dict) else {}
        if event_name == "operation_changed" and data.get("operation") == OP_IDLE:
            self._touch_idle_clock()

        super()._on_core_event(event_name, data)

        if event_name == "model_unloading":
            self._start_unload_worker()
        elif event_name == "model_unloaded":
            self._touch_idle_clock()

    def _start_model_worker(self, device: str) -> None:
        """Load/reload the model off-GUI and resume one queued OCR action."""
        with self._model_thread_lock:
            if self._shutdown:
                return
            if self._model_thread is not None and self._model_thread.is_alive():
                return

            def load() -> None:
                try:
                    self._controller.load_model_sync(device)
                    self._touch_idle_clock()
                    self._publish(
                        "model_loaded",
                        {
                            "device": self._controller.engine.device,
                            "backend": self._controller.engine.backend,
                        },
                    )
                    self._run_pending_model_action()
                except OperationCancelledError:
                    self._clear_pending_model_action()
                    self._publish("model_load_cancelled", {"device": device})
                except Exception as exc:
                    self._clear_pending_model_action()
                    logger.exception("Caricamento modello fallito")
                    self._publish(
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

    def _start_unload_worker(self) -> None:
        """Release model RAM/VRAM without blocking the Qt GUI thread."""
        with self._model_thread_lock:
            if self._shutdown:
                return
            if self._model_thread is not None and self._model_thread.is_alive():
                return

            def unload() -> None:
                try:
                    self._controller.unload_model_sync()
                except Exception as exc:
                    logger.exception("Scaricamento modello fallito")
                    self._publish("model_unload_failed", {"error": str(exc)})
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

    def _check_idle_unload(self) -> None:
        if self._shutdown:
            return
        minutes = int(self._controller.settings.model_auto_unload_minutes)
        if minutes <= 0:
            return
        if not self._controller.engine.is_initialized:
            return
        if self._controller.operation != OP_IDLE:
            return
        if time.monotonic() - self._idle_since < minutes * 60:
            return
        self._touch_idle_clock()
        logger.info("Auto-unload modello dopo %d minuti di inattività", minutes)
        try:
            self._controller.request_model_unload()
        except Exception:
            logger.exception("Auto-unload modello non avviato")

    @Slot(str, result=str)
    def startSingleOcr(self, raw_path: str) -> str:
        try:
            path = self._validate_path(raw_path)
            if self._controller.engine.is_initialized:
                self._controller.start_ocr(path)
                return self._json({"ok": True, "queued": False})
            self._queue_after_model_load(
                "l'OCR",
                lambda: self._controller.start_ocr(path),
            )
            return self._json({"ok": True, "queued": True})
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
            if len(raw_paths) > self._bootstrap_payload()["limits"]["max_batch_size"]:
                raise ValueError("Batch troppo grande")
            paths = [self._validate_path(str(path)) for path in raw_paths]
            if self._controller.engine.is_initialized:
                job = self._controller.run_batch(paths)
                return self._json({"ok": True, "queued": False, "job_id": job.job_id})

            def start_queued_batch() -> None:
                self._controller.run_batch(paths)

            self._queue_after_model_load("il batch", start_queued_batch)
            return self._json({"ok": True, "queued": True, "job_id": ""})
        except Exception as exc:
            logger.warning("Avvio batch rifiutato: %s", exc)
            self._error("Impossibile avviare il batch.", details=str(exc))
            return self._json({"ok": False, "error": str(exc)})

    @Slot(result=str)
    def unloadModel(self) -> str:
        try:
            if self._controller.operation != OP_IDLE:
                raise RuntimeError("Attendi la conclusione dell'operazione in corso")
            self._clear_pending_model_action()
            if not self._controller.engine.is_initialized:
                return self._json({"ok": True, "already_unloaded": True})
            self._controller.request_model_unload()
            return self._json({"ok": True, "already_unloaded": False})
        except Exception as exc:
            self._error("Impossibile scaricare il modello.", details=str(exc))
            return self._json({"ok": False, "error": str(exc)})

    @Slot(str, str, str, result=str)
    def saveSingleResult(
        self,
        source_path: str,
        displayed_text: str,
        file_format: str,
    ) -> str:
        """Persist the Python-owned canonical result; displayed_text is legacy UI input."""
        _ = displayed_text
        try:
            destination = self._controller.save_single_result(source_path, file_format)
            return self._json(
                {
                    "ok": True,
                    "path": str(destination),
                    "name": destination.name,
                }
            )
        except Exception as exc:
            logger.warning("Salvataggio risultato OCR fallito: %s", exc)
            return self._json({"ok": False, "error": str(exc)})

    @Slot(str, str, result=str)
    def saveSinglePdfPages(self, source_path: str, file_format: str) -> str:
        try:
            outputs = self._controller.save_single_pdf_pages(source_path, file_format)
            return self._json(
                {
                    "ok": True,
                    "paths": [str(path) for path in outputs],
                    "count": len(outputs),
                }
            )
        except Exception as exc:
            logger.warning("Salvataggio pagine PDF fallito: %s", exc)
            return self._json({"ok": False, "error": str(exc)})

    @Slot(str, result=str)
    def updateSettings(self, payload_json: str) -> str:
        """Persist output-workflow and model-memory preferences."""
        try:
            payload = json.loads(payload_json)
            if not isinstance(payload, dict):
                raise ValueError("Impostazioni non valide")
            allowed = {
                "language",
                "output_dir",
                "preprocessing_enabled",
                "batch_auto_save",
                "batch_output_format",
                "batch_save_pdf_pages",
                "load_model_at_startup",
                "model_auto_unload_minutes",
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
            for key in (
                "batch_auto_save",
                "batch_save_pdf_pages",
                "load_model_at_startup",
            ):
                if key in overrides:
                    overrides[key] = bool(overrides[key])
            if "batch_output_format" in overrides:
                fmt = str(overrides["batch_output_format"]).strip().lower().lstrip(".")
                if fmt not in {"txt", "md"}:
                    raise ValueError("Formato batch supportato: txt oppure md")
                overrides["batch_output_format"] = fmt
            if "model_auto_unload_minutes" in overrides:
                minutes = int(overrides["model_auto_unload_minutes"])
                if not 0 <= minutes <= 1440:
                    raise ValueError("Auto-unload modello deve essere tra 0 e 1440 minuti")
                overrides["model_auto_unload_minutes"] = minutes

            self._controller.update_settings(**overrides)
            self._touch_idle_clock()
            return self._json(
                {"ok": True, "settings": asdict(self._controller.settings)}
            )
        except Exception as exc:
            logger.warning("Salvataggio impostazioni fallito: %s", exc)
            return self._json({"ok": False, "error": str(exc)})

    def shutdown(self, wait_ms: int = 5000) -> None:
        self._idle_timer.stop()
        self._clear_pending_model_action()
        super().shutdown(wait_ms=wait_ms)
