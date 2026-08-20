"""Regressioni del lifecycle OCREngine."""

from __future__ import annotations

import sys
import types

import pytest

from core.cancellation import CancellationToken
from core.exceptions import ModelLoadError, OperationCancelledError
from core.ocr_engine import OCREngine


def test_initialize_cancellation_cleans_local_backend(monkeypatch) -> None:
    instances = []

    class FakeBackend:
        def __init__(self, preferred_device: str) -> None:
            self.preferred_device = preferred_device
            self.shutdown_calls = 0
            instances.append(self)

        def initialize(self, *, cancel_token=None) -> None:
            assert cancel_token is not None
            cancel_token.cancel()

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    module = types.ModuleType("core.llama_backend")
    module.LlamaServerBackend = FakeBackend  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.llama_backend", module)

    engine = OCREngine()
    token = CancellationToken()
    with pytest.raises(OperationCancelledError):
        engine.initialize("llama-cpp", cancel_token=token)

    assert len(instances) == 1
    assert instances[0].shutdown_calls == 1
    assert engine.is_initialized is False


def test_initialize_rejects_unknown_backend() -> None:
    engine = OCREngine()
    with pytest.raises(ModelLoadError):
        engine.initialize("not-a-backend")
