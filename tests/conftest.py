"""Shared fixtures for GLM OCR tests."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.event_bus import EventBus  # noqa: E402


@pytest.fixture(autouse=True)
def event_bus():
    """Reset the EventBus before and after every test."""
    EventBus.reset()
    yield EventBus
    EventBus.reset()


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
