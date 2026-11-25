"""OCREngine lifecycle (audit M1: no lock held across a model load)."""

from __future__ import annotations

import threading

import pytest

from core.cancellation import CancellationToken
from core.exceptions import ModelLoadError, OCREngineNotInitializedError, OperationCancelledError
from core.ocr_engine import OCREngine


class FakeBackend:
    def __init__(self, *, block: threading.Event | None = None, fail: Exception | None = None) -> None:
        self.block = block
        self.fail = fail
        self.started = threading.Event()
        self.shutdown_calls = 0

    def initialize(self, *, cancel_token=None) -> None:
        self.started.set()
        if self.block is not None:
            assert self.block.wait(timeout=3)
        if self.fail is not None:
            raise self.fail
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()

    def process_image(self, *_args, **_kwargs):
        return "processed"

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def test_cancelled_initialize_cleans_up_its_backend() -> None:
    backend = FakeBackend()
    engine = OCREngine(backend_factory=lambda: backend)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelledError):
        engine.initialize(cancel_token=token)
    assert engine.is_initialized is False


def test_backend_errors_become_model_load_errors() -> None:
    backend = FakeBackend(fail=RuntimeError("boom"))
    engine = OCREngine(backend_factory=lambda: backend)
    with pytest.raises(ModelLoadError, match="boom"):
        engine.initialize()
    assert backend.shutdown_calls == 1


def test_state_queries_do_not_block_during_a_load() -> None:
    release = threading.Event()
    backend = FakeBackend(block=release)
    engine = OCREngine(backend_factory=lambda: backend)
    loader = threading.Thread(target=engine.initialize)
    loader.start()
    assert backend.started.wait(timeout=1)

    answered = threading.Event()
    threading.Thread(target=lambda: (engine.is_initialized, answered.set())).start()
    assert answered.wait(timeout=0.5), "is_initialized blocked behind the model load"

    release.set()
    loader.join(timeout=2)
    assert engine.is_initialized is True
    engine.shutdown()


def test_shutdown_during_load_discards_the_late_backend() -> None:
    release = threading.Event()
    backend = FakeBackend(block=release)
    engine = OCREngine(backend_factory=lambda: backend)
    errors: list[BaseException] = []

    def load() -> None:
        try:
            engine.initialize()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    loader = threading.Thread(target=load)
    loader.start()
    assert backend.started.wait(timeout=1)
    engine.shutdown()  # must not wait for the load
    release.set()
    loader.join(timeout=2)

    assert engine.is_initialized is False
    assert backend.shutdown_calls == 1
    assert errors and isinstance(errors[0], OperationCancelledError)


def test_process_requires_initialized_backend(tmp_path) -> None:
    engine = OCREngine(backend_factory=FakeBackend)
    with pytest.raises(OCREngineNotInitializedError):
        engine.process_image(tmp_path / "x.png")


def test_shutdown_is_bounded_when_an_inference_is_stuck() -> None:
    started = threading.Event()
    never = threading.Event()

    class StuckBackend(FakeBackend):
        def process_image(self, *_args, **_kwargs):
            started.set()
            never.wait(5)

    backend = StuckBackend()
    engine = OCREngine(backend_factory=lambda: backend)
    engine.initialize()
    worker = threading.Thread(target=lambda: engine.process_image("x.png"), daemon=True)
    worker.start()
    assert started.wait(1)
    import time as _time

    t0 = _time.monotonic()
    engine.shutdown(inference_timeout=0.3)
    assert _time.monotonic() - t0 < 2
    assert backend.shutdown_calls == 1
    never.set()
