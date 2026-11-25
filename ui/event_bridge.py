"""Qt signal adapter for the core EventBus.

EventBus handlers run synchronously in the emitting (often worker) thread.
This adapter re-emits every event as a Qt signal so presentation code always
handles it on the GUI thread through a queued connection.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from core.event_bus import EventBus

FORWARDED_EVENTS = (
    "hardware_detected",
    "hardware_refresh_started",
    "hardware_refresh_failed",
    "backend_initialization_failed",
    "operation_changed",
    "model_loading",
    "model_loaded",
    "model_load_cancelled",
    "model_load_failed",
    "model_unloading",
    "model_unloaded",
    "model_unload_failed",
    "model_load_progress",
    "queued_operation_failed",
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


class EventBridge(QObject):
    """Forward core events to Qt without coupling the core to Qt."""

    event_received = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._subscriptions: list[tuple[str, Any]] = []
        self._shutdown = False
        for event_name in FORWARDED_EVENTS:
            handler = self._make_handler(event_name)
            EventBus.subscribe(event_name, handler)
            self._subscriptions.append((event_name, handler))

    def _make_handler(self, event_name: str):
        def handler(payload: dict[str, Any]) -> None:
            if not self._shutdown:
                self.event_received.emit(event_name, dict(payload))

        return handler

    def shutdown(self) -> None:
        """Detach from the EventBus; idempotent."""
        if self._shutdown:
            return
        self._shutdown = True
        for event_name, handler in self._subscriptions:
            EventBus.unsubscribe(event_name, handler)
        self._subscriptions.clear()
