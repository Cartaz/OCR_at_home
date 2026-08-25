"""Regressioni per il coordinatore globale AppController."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from config.settings import Settings
from core.app_controller import (
    OP_IDLE,
    OP_MODEL_LOADING,
    OP_OCR,
    AppController,
)
from core.event_bus import EventBus
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
    def __init__(self, *, initialized: bool = True) -> None:
        self.is_initialized = initialized
        self.device = "llama-cpp" if initialized else ""
        self.backend = "llama-cpp" if initialized else ""
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.initialize_started = threading.Event()
        self.initialize_release = threading.Event()
        self.initialize_release.set()
        self.shutdown_calls = 0
        self.initialize_calls: list[str] = []

    def process_image(self, _path: Path, **_kwargs: object) -> OCRResult:
        self.started.set()
        self.release.wait(timeout=3)
        return OCRResult(text="ok", confidence=0.9)

    def initialize(self, device: str, *, cancel_token=None) -> None:
        self.initialize_calls.append(device)
        self.initialize_started.set()
        while not self.initialize_release.wait(timeout=0.01):
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        self.device = device
        self.backend = device
        self.is_initialized = True

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.is_initialized = False
        self.device = ""
        self.backend = ""


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


class BlockingDetector(FakeDetector):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.refresh_values: list[bool] = []

    def detect(self, *, refresh: bool = False):
        self.refresh_values.append(refresh)
        self.started.set()
        assert self.release.wait(timeout=2), "test detector was never released"
        return list(self.devices)


class FakeUnavailableDetector:
    def __init__(self) -> None:
        self.devices = [
            HardwareInfo(
                device_name="llama.cpp non disponibile",
                device_type="llama-cpp",
                available=False,
            )
        ]

    def detect(self, *, refresh: bool = False):
        return list(self.devices)

    def get_default(self):
        return self.devices[0]


def _controller_with_fake_engine(
    monkeypatch,
    *,
    initialized: bool = True,
    settings: Settings | None = None,
) -> tuple[AppController, FakeEngine]:
    monkeypatch.setattr(Settings, "save", lambda self: None)
    controller = AppController(settings or Settings(default_device="llama-cpp"))
    fake = FakeEngine(initialized=initialized)
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
    engine.release.clear()
    controller.start_ocr(Path("page.png"))
    assert engine.started.wait(timeout=1)
    assert controller.operation == OP_OCR

    with pytest.raises(OperationBusyError):
        controller.run_batch([Path("other.png")])

    controller.cancel_ocr()
    engine.release.set()
    assert _wait_until(lambda: controller.operation == OP_IDLE)
    controller.shutdown()


def test_switch_device_runs_model_load_on_controller_worker(monkeypatch) -> None:
    controller, engine = _controller_with_fake_engine(monkeypatch)

    controller.switch_device("llama-cpp-sycl")

    assert engine.initialize_started.wait(timeout=1)
    assert _wait_until(lambda: controller.operation == OP_IDLE)
    assert engine.initialize_calls == ["llama-cpp-sycl"]
    assert engine.shutdown_calls == 0
    assert controller.model_device == "llama-cpp-sycl"
    controller.shutdown()


def test_cancelled_async_model_load_releases_operation(monkeypatch) -> None:
    controller, engine = _controller_with_fake_engine(monkeypatch, initialized=False)
    engine.initialize_release.clear()

    controller.request_model_load("llama-cpp-sycl")
    assert controller.operation == OP_MODEL_LOADING
    assert engine.initialize_started.wait(timeout=1)

    controller.cancel_model_loading()

    assert _wait_until(lambda: controller.operation == OP_IDLE)
    assert engine.initialize_calls == ["llama-cpp-sycl"]
    assert engine.is_initialized is False
    controller.shutdown()


def test_request_initialize_returns_while_hardware_probe_is_running(monkeypatch) -> None:
    monkeypatch.setattr(Settings, "save", lambda self: None)
    controller = AppController(
        Settings(default_device="llama-cpp", load_model_at_startup=False)
    )
    detector = BlockingDetector()
    controller._hardware_detector = detector  # type: ignore[attr-defined]

    assert controller.request_initialize() is True
    assert detector.started.wait(timeout=1)
    hardware_thread = controller._hardware_thread  # type: ignore[attr-defined]
    assert hardware_thread is not None and hardware_thread.is_alive()
    assert controller._initialized is False  # type: ignore[attr-defined]

    detector.release.set()
    assert _wait_until(lambda: controller._initialized)  # type: ignore[attr-defined]
    assert _wait_until(lambda: controller._hardware_thread is None)  # type: ignore[attr-defined]
    assert detector.refresh_values == [False]
    controller.shutdown()


def test_request_hardware_refresh_returns_while_probe_is_running(monkeypatch) -> None:
    controller, _engine = _controller_with_fake_engine(monkeypatch)
    detector = BlockingDetector()
    controller._hardware_detector = detector  # type: ignore[attr-defined]

    assert controller.request_hardware_refresh() is True
    assert detector.started.wait(timeout=1)
    hardware_thread = controller._hardware_thread  # type: ignore[attr-defined]
    assert hardware_thread is not None and hardware_thread.is_alive()
    assert controller.request_hardware_refresh() is False

    detector.release.set()
    assert _wait_until(lambda: controller._hardware_thread is None)  # type: ignore[attr-defined]
    assert detector.refresh_values == [True]
    controller.shutdown()


def test_initialize_preserves_configured_device_if_nothing_is_available(monkeypatch) -> None:
    saved: list[str] = []
    monkeypatch.setattr(
        Settings,
        "save",
        lambda self: saved.append(self.default_device),
    )
    controller = AppController(
        Settings(default_device="llama-cpp-sycl", load_model_at_startup=False)
    )
    controller._hardware_detector = FakeUnavailableDetector()  # type: ignore[attr-defined]

    controller.initialize()

    assert controller.settings.default_device == "llama-cpp-sycl"
    assert controller.operation == OP_IDLE
    assert saved == []
    controller.shutdown()


def test_initialize_can_leave_model_unloaded(monkeypatch) -> None:
    monkeypatch.setattr(Settings, "save", lambda self: None)
    controller = AppController(
        Settings(default_device="llama-cpp-sycl", load_model_at_startup=False)
    )
    controller._hardware_detector = FakeDetector()  # type: ignore[attr-defined]

    controller.initialize()

    assert controller.operation == OP_IDLE
    assert controller.model_ready is False
    controller.shutdown()


def test_initialize_remains_retryable_if_model_worker_cannot_start(monkeypatch) -> None:
    monkeypatch.setattr(Settings, "save", lambda self: None)
    controller = AppController(
        Settings(default_device="llama-cpp-sycl", load_model_at_startup=True)
    )
    engine = FakeEngine(initialized=False)
    controller._engine = engine  # type: ignore[attr-defined]
    controller._hardware_detector = FakeDetector()  # type: ignore[attr-defined]
    attempts = 0

    def start_model_load(device: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("simulated thread start failure")
        controller.load_model_sync(device)

    monkeypatch.setattr(controller, "_start_model_load_worker", start_model_load)

    with pytest.raises(RuntimeError, match="thread start failure"):
        controller.initialize()

    assert controller._initialized is False  # type: ignore[attr-defined]
    assert controller.operation == OP_IDLE

    controller.initialize()

    assert controller._initialized is True  # type: ignore[attr-defined]
    assert controller.operation == OP_IDLE
    assert engine.is_initialized is True
    assert attempts == 2
    controller.shutdown()


def test_model_can_be_unloaded_and_loaded_again_without_closing_controller(monkeypatch) -> None:
    controller, engine = _controller_with_fake_engine(monkeypatch)

    assert controller.request_model_unload() is True
    assert _wait_until(lambda: engine.shutdown_calls == 1)
    assert _wait_until(lambda: controller.operation == OP_IDLE)
    assert engine.is_initialized is False

    controller.request_model_load("llama-cpp-sycl")
    assert engine.initialize_started.wait(timeout=1)
    assert _wait_until(lambda: controller.operation == OP_IDLE)
    assert engine.is_initialized is True
    assert engine.initialize_calls == ["llama-cpp-sycl"]
    controller.shutdown()


def test_model_lifecycle_releases_worker_before_publishing_idle(monkeypatch) -> None:
    controller, engine = _controller_with_fake_engine(monkeypatch)
    idle_worker_snapshots: list[threading.Thread | None] = []

    def observe_operation(payload: dict[str, object]) -> None:
        if payload.get("operation") == OP_IDLE:
            idle_worker_snapshots.append(
                controller._model_thread  # type: ignore[attr-defined]
            )

    EventBus.subscribe("operation_changed", observe_operation)

    assert controller.request_model_unload() is True
    assert _wait_until(lambda: controller.operation == OP_IDLE)
    assert engine.is_initialized is False

    controller.request_model_load("llama-cpp-sycl")
    assert engine.initialize_started.wait(timeout=1)
    assert _wait_until(lambda: controller.operation == OP_IDLE)
    assert engine.is_initialized is True

    assert len(idle_worker_snapshots) >= 2
    assert all(worker is None for worker in idle_worker_snapshots)
    controller.shutdown()


def test_single_ocr_is_resumed_after_controller_owned_model_load(monkeypatch) -> None:
    controller, engine = _controller_with_fake_engine(monkeypatch, initialized=False)
    engine.release.clear()

    queued = controller.start_ocr_or_queue(Path("page.png"))

    assert queued is True
    assert engine.initialize_started.wait(timeout=1)
    assert engine.started.wait(timeout=1)
    assert controller.operation == OP_OCR

    engine.release.set()
    assert _wait_until(lambda: controller.operation == OP_IDLE)
    controller.shutdown()


def test_idle_auto_unload_policy_lives_in_controller(monkeypatch) -> None:
    settings = Settings(
        default_device="llama-cpp",
        model_auto_unload_minutes=5,
    )
    controller, engine = _controller_with_fake_engine(
        monkeypatch,
        settings=settings,
    )
    controller._idle_since = 100.0  # type: ignore[attr-defined]

    assert controller.check_idle_model_unload(now=399.0) is False
    assert engine.shutdown_calls == 0

    assert controller.check_idle_model_unload(now=401.0) is True
    assert _wait_until(lambda: engine.shutdown_calls == 1)
    assert _wait_until(lambda: controller.operation == OP_IDLE)
    controller.shutdown()


def test_shutdown_cancels_and_joins_model_load_worker(monkeypatch) -> None:
    controller, engine = _controller_with_fake_engine(monkeypatch, initialized=False)
    engine.initialize_release.clear()

    controller.request_model_load("llama-cpp-sycl")
    assert engine.initialize_started.wait(timeout=1)

    controller.shutdown()

    assert controller.operation != OP_MODEL_LOADING
    model_thread = controller._model_thread  # type: ignore[attr-defined]
    assert model_thread is None or not model_thread.is_alive()
