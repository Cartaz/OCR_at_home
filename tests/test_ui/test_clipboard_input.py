"""Native clipboard-image bridge coverage."""

from __future__ import annotations

import json
from types import SimpleNamespace

from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

from core.app_controller import OP_IDLE, OP_OCR
from core.input_staging import InputStaging
from ui.web_bridge import WebBridge


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_clipboard_image_is_encoded_staged_and_validated(tmp_path) -> None:
    _ = _app()
    clipboard = QGuiApplication.clipboard()
    image = QImage(12, 8, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    clipboard.setImage(image)

    staging = InputStaging(tmp_path / "inputs", max_bytes=1024 * 1024)
    bridge = WebBridge(
        SimpleNamespace(operation=OP_IDLE),
        input_staging=staging,
    )

    result = json.loads(bridge.pasteClipboardImage())

    assert result["ok"] is True
    assert result["name"] == "Immagine dagli appunti.png"
    staged = tmp_path / "inputs" / staging.session_dir.name / result["path"].split("/")[-1]
    assert staged.resolve().as_posix() == result["path"]
    assert staged.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    bridge.deleteLater()
    staging.shutdown()
    clipboard.clear()


def test_clipboard_paste_is_rejected_while_operation_is_busy(tmp_path) -> None:
    _ = _app()
    staging = InputStaging(tmp_path / "inputs", max_bytes=1024 * 1024)
    bridge = WebBridge(
        SimpleNamespace(operation=OP_OCR),
        input_staging=staging,
    )

    result = json.loads(bridge.pasteClipboardImage())

    assert result == {
        "ok": False,
        "error": "Attendi la conclusione dell'operazione prima di cambiare file.",
    }
    assert staging.session_dir is None

    bridge.deleteLater()
    staging.shutdown()
