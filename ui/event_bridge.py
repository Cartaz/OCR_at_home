"""Qt signal adapter for the core EventBus.

This module contains no visual code. It converts synchronous, potentially
cross-thread EventBus callbacks into Qt signals that can safely be consumed by
the desktop presentation layer.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from core.event_bus import EventBus


class EventBridge(QObject):
    """Forward core events to Qt without coupling the core to Qt."""

    event_received = Signal(str, object)
    ocr_new_text = Signal(str)
    batch_new_text = Signal(str)

    _EVENTS = (
        "hardware_detected",
        "operation_changed",
        "model_loading",
        "model_unloading",
        "model_unloaded",
        "model_load_progress",
        "config_changed",
        "ocr_started",
        "ocr_completed",
        "ocr_cancelled",
        "ocr_failed",
        "pdf_progress",
        "pdf_page_completed",
        "single_output_saved",
        "single_output_save_failed",
        "batch_started",
        "batch_progress",
        "batch_task_completed",
        "batch_task_failed",
        "batch_completed",
        "batch_cancelled",
        "batch_failed",
        "batch_output_saved",
        "batch_output_save_failed",
        "batch_output_summary",
    )

    def __init__(self, controller: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._subscriptions: list[tuple[str, Any]] = []
        self._shutdown = False
        for event_name in self._EVENTS:
            handler = self._make_handler(event_name)
            EventBus.subscribe(event_name, handler)
            self._subscriptions.append((event_name, handler))

    def _make_handler(self, event_name: str):
        def handler(payload: dict[str, Any]) -> None:
            if self._shutdown:
                return
            data = dict(payload)
            if event_name == "pdf_page_completed" and data.get("mode") == "single":
                text = str(data.get("text", ""))
                if text:
                    self.ocr_new_text.emit(text)
            elif event_name == "ocr_completed" and data.get("mode") == "single":
                if not bool(data.get("pages_streamed")):
                    text = str(data.get("text", ""))
                    if text:
                        self.ocr_new_text.emit(text)
            elif event_name == "batch_task_completed":
                text = str(data.get("text", ""))
                path = str(data.get("image_path", ""))
                rendered = f"{path}\n{text}" if path else text
                if rendered:
                    self.batch_new_text.emit(rendered)
            self.event_received.emit(event_name, data)

        return handler

    def shutdown(self, wait_ms: int = 1000) -> None:
        """Detach from EventBus; ``wait_ms`` is retained for API compatibility."""
        _ = wait_ms
        if self._shutdown:
            return
        self._shutdown = True
        for event_name, handler in self._subscriptions:
            EventBus.unsubscribe(event_name, handler)
        self._subscriptions.clear()