"""Application WebBridge capabilities beyond OCR lifecycle presentation."""

from __future__ import annotations

import logging

from PySide6.QtCore import Slot

from core.output_writer import write_ocr_text
from ui.web_bridge import WebBridge

logger = logging.getLogger(__name__)


class AppWebBridge(WebBridge):
    """WebBridge plus durable user-facing output actions."""

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
