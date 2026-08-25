"""Application WebBridge capabilities beyond base OCR presentation."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Slot

from core.app_controller import OP_IDLE
from ui.web_bridge import WebBridge

logger = logging.getLogger(__name__)


class AppWebBridge(WebBridge):
    """Presentation adapter for model-memory and output actions."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # QTimer is native scheduling only; idle policy and state live in core.
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(30_000)
        self._idle_timer.timeout.connect(self._check_idle_unload)
        self._idle_timer.start()

    def _check_idle_unload(self) -> None:
        if self._shutdown:
            return
        try:
            self._controller.check_idle_model_unload()
        except Exception:
            logger.exception("Auto-unload modello non avviato")

    @Slot(str, result=str)
    def startSingleOcr(self, raw_path: str) -> str:
        try:
            path = self._validate_path(raw_path)
            queued = self._controller.start_ocr_or_queue(path)
            return self._json({"ok": True, "queued": queued})
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
            queued, job = self._controller.run_batch_or_queue(paths)
            return self._json(
                {
                    "ok": True,
                    "queued": queued,
                    "job_id": "" if job is None else job.job_id,
                }
            )
        except Exception as exc:
            logger.warning("Avvio batch rifiutato: %s", exc)
            self._error("Impossibile avviare il batch.", details=str(exc))
            return self._json({"ok": False, "error": str(exc)})

    @Slot(result=str)
    def unloadModel(self) -> str:
        try:
            if self._controller.operation != OP_IDLE:
                raise RuntimeError("Attendi la conclusione dell'operazione in corso")
            started = self._controller.request_model_unload()
            return self._json({"ok": True, "already_unloaded": not started})
        except Exception as exc:
            self._error("Impossibile scaricare il modello.", details=str(exc))
            return self._json({"ok": False, "error": str(exc)})

    @Slot(str, str, result=str)
    def saveSingleResult(self, source_path: str, file_format: str) -> str:
        try:
            request_id = self._controller.request_save_single_result(
                source_path,
                file_format,
            )
            return self._json({"ok": True, "request_id": request_id})
        except Exception as exc:
            logger.warning("Richiesta salvataggio risultato OCR rifiutata: %s", exc)
            return self._json({"ok": False, "error": str(exc)})

    @Slot(str, str, result=str)
    def saveSinglePdfPages(self, source_path: str, file_format: str) -> str:
        try:
            request_id = self._controller.request_save_single_pdf_pages(
                source_path,
                file_format,
            )
            return self._json({"ok": True, "request_id": request_id})
        except Exception as exc:
            logger.warning("Richiesta salvataggio pagine PDF rifiutata: %s", exc)
            return self._json({"ok": False, "error": str(exc)})

    @Slot(str, result=str)
    def updateSettings(self, payload_json: str) -> str:
        """Validate and persist output/model-memory preferences through core."""
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
            return self._json(
                {"ok": True, "settings": asdict(self._controller.settings)}
            )
        except Exception as exc:
            logger.warning("Salvataggio impostazioni fallito: %s", exc)
            return self._json({"ok": False, "error": str(exc)})

    def shutdown(self, wait_ms: int = 5000) -> None:
        self._idle_timer.stop()
        super().shutdown(wait_ms=wait_ms)