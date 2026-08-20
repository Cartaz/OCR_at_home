"""Test di EventBridge: separazione OCR/Batch e cleanup EventBus."""

from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from core.event_bus import EventBus
from ui.event_bridge import EventBridge

_APP: QApplication | None = None


def _app() -> QApplication:
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


def test_batch_task_events_do_not_pollute_single_ocr() -> None:
    app = _app()
    EventBus.reset()
    controller = MagicMock()
    controller.cancel_model_loading = MagicMock()
    bridge = EventBridge(controller)
    ocr_text: list[str] = []
    batch_text: list[str] = []
    bridge.ocr_new_text.connect(ocr_text.append)
    bridge.batch_new_text.connect(batch_text.append)

    EventBus.emit(
        "batch_task_completed",
        {"text": "batch", "image_path": "/tmp/a.png"},
    )
    assert ocr_text == []
    assert batch_text and "batch" in batch_text[0]
    bridge.shutdown(wait_ms=1)
    EventBus.reset()
    _ = app


def test_shutdown_unsubscribes_from_event_bus() -> None:
    app = _app()
    EventBus.reset()
    controller = MagicMock()
    controller.cancel_model_loading = MagicMock()
    bridge = EventBridge(controller)
    output: list[str] = []
    bridge.ocr_new_text.connect(output.append)
    bridge.shutdown(wait_ms=1)

    EventBus.emit(
        "ocr_completed",
        {"mode": "single", "text": "late", "pages_streamed": False},
    )
    assert output == []
    EventBus.reset()
    _ = app
