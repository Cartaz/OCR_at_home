"""Application WebBridge capabilities beyond OCR lifecycle presentation."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import Slot

from core.output_writer import (
    split_combined_pdf_text,
    write_ocr_pages,
    write_ocr_text,
)
from ui.web_bridge import WebBridge

logger = logging.getLogger(__name__)


class AppWebBridge(WebBridge):
    """WebBridge plus durable user-facing output actions."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._single_completed_source = ""
        self._single_pdf_pages: dict[str, dict[int, str]] = {}
        self._batch_saved_count = 0
        self._batch_save_failures = 0

    @staticmethod
    def _canonical_source(source_path: str) -> str:
        return str(Path(source_path).expanduser().resolve()) if source_path else ""

    @Slot(str, object)
    def _on_core_event(self, event_name: str, payload: object) -> None:
        data = dict(payload) if isinstance(payload, dict) else {}

        if event_name == "ocr_started":
            source = self._canonical_source(str(data.get("image_path") or ""))
            self._single_completed_source = ""
            if source:
                self._single_pdf_pages.pop(source, None)
        elif event_name == "pdf_page_completed" and data.get("mode") == "single":
            source = self._canonical_source(str(data.get("pdf_path") or ""))
            page_num = int(data.get("page_num") or 0)
            if source and page_num > 0:
                self._single_pdf_pages.setdefault(source, {})[page_num] = str(
                    data.get("text") or ""
                )
        elif event_name == "ocr_completed" and data.get("mode") == "single":
            self._single_completed_source = self._canonical_source(
                str(data.get("image_path") or "")
            )
        elif event_name in {"ocr_cancelled", "ocr_failed"}:
            self._single_completed_source = ""
        elif event_name == "batch_started":
            self._batch_saved_count = 0
            self._batch_save_failures = 0

        # Publish the core event first so the normal UI state is current before
        # any output-status event is emitted.
        super()._on_core_event(event_name, data)

        if event_name == "batch_task_completed":
            self._auto_save_batch_result(data)
        elif event_name == "batch_completed" and self._controller.settings.batch_auto_save:
            self._publish(
                "batch_output_summary",
                {
                    "saved": self._batch_saved_count,
                    "failed": self._batch_save_failures,
                    "output_dir": self._controller.settings.output_dir,
                },
            )

    def _require_completed_single(self, source_path: str) -> str:
        source = self._canonical_source(source_path)
        if not source or source != self._single_completed_source:
            raise RuntimeError(
                "Il risultato selezionato non corrisponde a un OCR completato."
            )
        return source

    def _auto_save_batch_result(self, data: dict[str, Any]) -> None:
        settings = self._controller.settings
        if not settings.batch_auto_save:
            return

        source = str(data.get("image_path") or "")
        text = str(data.get("text") or "")
        if not source:
            self._batch_save_failures += 1
            self._publish(
                "batch_output_save_failed",
                {"error": "Percorso sorgente batch mancante"},
            )
            return

        combined_path: Path | None = None
        page_paths: list[Path] = []
        try:
            combined_path = write_ocr_text(
                settings.output_dir,
                source,
                text,
                settings.batch_output_format,
            )
            if settings.batch_save_pdf_pages and Path(source).suffix.lower() == ".pdf":
                pages = split_combined_pdf_text(text)
                page_paths = write_ocr_pages(
                    settings.output_dir,
                    source,
                    pages,
                    settings.batch_output_format,
                )
            self._batch_saved_count += 1
            logger.info("Output batch salvato per %s in %s", source, combined_path)
            self._publish(
                "batch_output_saved",
                {
                    "image_path": source,
                    "path": str(combined_path),
                    "page_paths": [str(path) for path in page_paths],
                },
            )
        except Exception as exc:
            self._batch_save_failures += 1
            logger.warning("Salvataggio automatico batch fallito per %s: %s", source, exc)
            self._publish(
                "batch_output_save_failed",
                {
                    "image_path": source,
                    "error": str(exc),
                    "combined_path": str(combined_path) if combined_path else "",
                },
            )

    @Slot(str, str, str, result=str)
    def saveSingleResult(
        self,
        source_path: str,
        text: str,
        file_format: str,
    ) -> str:
        try:
            source = self._require_completed_single(source_path)
            destination = write_ocr_text(
                self._controller.settings.output_dir,
                source,
                text,
                file_format,
            )
            logger.info("Risultato OCR salvato in %s", destination)
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
            source = self._require_completed_single(source_path)
            page_map = self._single_pdf_pages.get(source) or {}
            page_numbers = sorted(page_map)
            if page_numbers != list(range(1, len(page_numbers) + 1)):
                raise RuntimeError("Sequenza pagine PDF incompleta o non valida")
            if not page_numbers:
                raise RuntimeError("Nessuna pagina PDF completata da salvare")
            outputs = write_ocr_pages(
                self._controller.settings.output_dir,
                source,
                [page_map[number] for number in page_numbers],
                file_format,
            )
            logger.info("Salvate %d pagine OCR separate per %s", len(outputs), source)
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
        """Persist base settings plus output-workflow preferences."""
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
            for key in ("batch_auto_save", "batch_save_pdf_pages"):
                if key in overrides:
                    overrides[key] = bool(overrides[key])
            if "batch_output_format" in overrides:
                fmt = str(overrides["batch_output_format"]).strip().lower().lstrip(".")
                if fmt not in {"txt", "md"}:
                    raise ValueError("Formato batch supportato: txt oppure md")
                overrides["batch_output_format"] = fmt

            self._controller.update_settings(**overrides)
            return self._json(
                {"ok": True, "settings": asdict(self._controller.settings)}
            )
        except Exception as exc:
            logger.warning("Salvataggio impostazioni fallito: %s", exc)
            return self._json({"ok": False, "error": str(exc)})
