"""Test per core/event_bus.py — verifica sistema di comunicazione.

Tests:
    - Subscribe ed emit funzionano correttamente
    - Unsubscribe rimuove l'handler
    - Reset pulisce tutti gli handler
    - Errori nei singoli handler non bloccano gli altri
"""
from core.event_bus import EventBus


def test_subscribe_and_emit() -> None:
    """Verifica che un handler iscritto riceva gli eventi."""
    received = []
    EventBus.subscribe("test_event", lambda data: received.append(data))
    EventBus.emit("test_event", {"key": "value"})
    assert len(received) == 1
    assert received[0]["key"] == "value"


def test_unsubscribe_removes_handler() -> None:
    """Verifica che unsubscribe rimuova l'handler."""
    received = []
    handler = lambda data: received.append(data)
    EventBus.subscribe("test_event", handler)
    EventBus.unsubscribe("test_event", handler)
    EventBus.emit("test_event", {})
    assert len(received) == 0


def test_reset_clears_all_handlers() -> None:
    """Verifica che reset pulisca tutti gli handler."""
    received = []
    EventBus.subscribe("test_event", lambda data: received.append(data))
    EventBus.reset()
    EventBus.emit("test_event", {})
    assert len(received) == 0


def test_handler_error_does_not_block_others() -> None:
    """Verifica che un errore in un handler non blocchi i successivi."""
    results = []

    def bad_handler(data):
        raise ValueError("Errore di test")

    def good_handler(data):
        results.append("ok")

    EventBus.subscribe("test_event", bad_handler)
    EventBus.subscribe("test_event", good_handler)
    EventBus.emit("test_event", {})
    assert "ok" in results
