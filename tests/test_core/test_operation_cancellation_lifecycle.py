"""End-to-end cancellation coverage across controller workers and ProcessManager."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from config.settings import Settings
from core.app_controller import OP_IDLE, AppController
from core.event_bus import EventBus
from core.models import OCRResult
from core.process_manager import ProcessManager


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


class CooperativeEngine:
    def __init__(self) -> None:
        self.is_initialized = True
        self.device = "llama-cpp-sycl"
        self.backend = "llama-cpp-sycl"
        self.started = threading.Event()
        self.shutdown_calls = 0

    def process_image(self, _path: Path, *, cancel_token=None, **_kwargs: object) -> OCRResult:
        self.started.set()
        assert cancel_token is not None
        cancel_token.wait(timeout=3)
        cancel_token.raise_if_cancelled()
        return OCRResult(text="unexpected completion", confidence=None)

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.is_initialized = False


def _controller(monkeypatch) -> tuple[AppController, CooperativeEngine]:
    monkeypatch.setattr(Settings, "save", lambda self: None)
    controller = AppController(Settings())
    engine = CooperativeEngine()
    controller._engine = engine  # type: ignore[attr-defined]
    controller._process_manager.shutdown()  # type: ignore[attr-defined]
    controller._process_manager = ProcessManager(  # type: ignore[attr-defined]
        engine,  # type: ignore[arg-type]
        on_job_finished=controller._on_batch_finished,  # type: ignore[attr-defined]
    )
    return controller, engine


def test_single_ocr_cancellation_reaches_worker_and_releases_operation(monkeypatch) -> None:
    controller, engine = _controller(monkeypatch)
    events: list[str] = []
    EventBus.subscribe("ocr_cancelled", lambda _payload: events.append("cancelled"))

    controller.start_ocr(Path("single.png"))
    assert engine.started.wait(timeout=1)

    controller.cancel_ocr()

    assert _wait_until(lambda: controller.operation == OP_IDLE)
    assert events == ["cancelled"]
    controller.shutdown()


def test_batch_cancellation_reaches_active_task_and_releases_operation(monkeypatch) -> None:
    controller, engine = _controller(monkeypatch)
    events: list[str] = []
    EventBus.subscribe("batch_cancelled", lambda _payload: events.append("cancelled"))

    job = controller.run_batch([Path("a.png"), Path("b.png")])
    assert engine.started.wait(timeout=1)

    controller.cancel_batch(job.job_id)

    assert _wait_until(lambda: controller.operation == OP_IDLE)
    assert _wait_until(lambda: controller.process_manager.active_job_id is None)
    assert events == ["cancelled"]
    controller.shutdown()
