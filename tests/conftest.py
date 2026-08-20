"""Fixture condivise per i test di GLM OCR.

Provides:
    event_bus: EventBus pulito per ogni test.
"""
import pytest
from core.event_bus import EventBus


@pytest.fixture(autouse=True)
def event_bus():
    """Resetta l'EventBus prima e dopo ogni test."""
    EventBus.reset()
    yield EventBus
    EventBus.reset()
