"""QWebChannel bridge dedicated to durable OCR output files."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Slot

from core.app_controller import AppController
from core.output_writer import write_ocr_text

logger = logging.getLogger(__name__)


class OutputBridge(QObject):
    """Filesystem-only bridge for saving OCR results.

    Keeping this separate from ``WebBridge`` prevents presentation/file-output
    concerns from growing inside the OCR lifecycle bridge.
    """

    def __init__(
        self,
        controller: AppController,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller

    @staticmethod
    def _json(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, default=str)

    @Slot(str, str, str, result=str)
    def saveSingleResult(
        self,
        source_path: str,
        text: str,
        file_format: str,
    ) -> str:
        try:
            destination = write_ocr_text(
                self._controller.settings.output_dir,
                source_path,
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
