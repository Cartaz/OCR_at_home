"""EventBridge forwards core events as Qt signals and detaches cleanly."""

from __future__ import annotations

from core.event_bus import EventBus
from ui.event_bridge import FORWARDED_EVENTS, EventBridge


def test_events_are_forwarded_with_a_payload_copy(qapp) -> None:
    bridge = EventBridge()
    received: list[tuple[str, dict]] = []
    bridge.event_received.connect(lambda name, data: received.append((name, data)))
    payload = {"operation": "ocr"}

    EventBus.emit("operation_changed", payload)
    payload["operation"] = "mutated"

    assert received == [("operation_changed", {"operation": "ocr"})]
    bridge.shutdown()


def test_unknown_events_are_not_forwarded(qapp) -> None:
    bridge = EventBridge()
    received: list[str] = []
    bridge.event_received.connect(lambda name, _data: received.append(name))
    EventBus.emit("not_a_ui_event", {})
    assert received == []
    assert "ocr_completed" in FORWARDED_EVENTS
    bridge.shutdown()


def test_shutdown_unsubscribes_from_event_bus(qapp) -> None:
    bridge = EventBridge()
    received: list[str] = []
    bridge.event_received.connect(lambda name, _data: received.append(name))
    bridge.shutdown()
    bridge.shutdown()
    EventBus.emit("model_loaded", {})
    assert received == []
