"""Regressioni per il coordinatore globale AppController."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from config.settings import Settings
from core.app_controller import OP_IDLE, OP_MODEL_LOADING, OP_OCR, AppController
from core.exceptions import OperationBusyError, OperationCancelledError
from core.models import HardwareInfo, OCRResult
from core.process_manager import ProcessManager


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


class FakeEngine:
    def __init__(self) -> None:
        self.is_initialized = True
        self.device = "llama-cpp"
        self.backend = "llama-cpp"
        self.started = threading.Event()
        self.release = threading.Event()
        self.shutdown_calls = 0
        self.initialize_calls: list[str] = []

    def process_image(self, _path: Path, **_kwargs: object) -> OCRResult:
        self.started.set()
        self.release.wait(timeout=3)
        return OCRResult(text="ok", confidence=0.9)

    def initialize(self, device: str, *, cancel_token=None) -> None:
        self.initialize_calls.append(device)
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        self.device = device
        self.is_initialized = True

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.is_initialized = False


class FakeDetector:
    def __init__(self) -> None:
        self.devices = [
            HardwareInfo(
                device_name="llama.cpp CPU",
                device_type="llama-cpp",
                available=True,
            ),
            HardwareInfo(
                device_name="llama.cpp SYCL",
                device_type="llama-cpp-sycl",
                available=True,
            ),
        ]

    def detect(self, *, refresh: bool = False):
        return list(self.devices)

    def get_default(self):
        return self.devices[0]


def _controller_with_fake_engine(monkeypatch) -> tuple[AppController, FakeEngine]:
    monkeypatch.setattr(Settings, "save", lambda self: None)
    controller = AppController(Settings(default_device="llama-cpp"))
    fake = FakeEngine()
    controller._engine = fake  # type: ignore[attr-defined]
    controller._hardware_detector = FakeDetector()  # type: ignore[attr-defined]
    controller._process_manager.shutdown()  # type: ignore[attr-defined]
    controller._process_manager = ProcessManager(  # type: ignore[attr-defined]
        fake,  # type: ignore[arg-type]
        on_job_finished=controller._on_batch_finished,  # type: ignore[attr-defined]
    )
    return controller, fake


def test_ocr_and_batch_are_mutually_exclusive(monkeypatch) -> None:
    controller, engine = _controller_with_fake_engine(monkeypatch)
    controller.start_ocr(Path("page.png"))
    assert engine.started.wait(timeout=1)
    assert controller.operation == OP_OCR

    with pytest.raises(OperationBusyError):
        controller.run_batch([Path("other.png")])

    controller.cancel_ocr()
    engine.release.set()
    assert _wait_until(lambda: controller.operation == OP_IDLE)
    controller.shutdown()


def test_switch_device_does_not_shutdown_engine_on_caller_thread(monkeypatch) -> None:
    controller, engine = _controller_with_fake_engine(monkeypatch)

    controller.switch_device("llama-cpp-sycl")
    assert controller.operation == OP_MODEL_LOADING
    assert engine.shutdown_calls == 0

    controller.load_model_sync("llama-cpp-sycl")
    assert controller.operation == OP_IDLE
    assert engine.initialize_calls == ["llama-cpp-sycl"]
    controller.shutdown()


def test_cancelled_model_load_releases_operation(monkeypatch) -> None:
    controller, engine = _controller_with_fake_engine(monkeypatch)
    controller.request_model_load("llama-cpp-sycl")
    controller.cancel_model_loading()

    with pytest.raises(OperationCancelledError):
        controller.load_model_sync("llama-cpp-sycl")

    assert controller.operation == OP_IDLE
    assert engine.initialize_calls == ["llama-cpp-sycl"]
    controller.shutdown()
