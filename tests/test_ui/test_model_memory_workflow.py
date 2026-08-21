from __future__ import annotations

import json
import time
from pathlib import Path

from config.settings import Settings
from ui.app_web_bridge import AppWebBridge


class _DummyEngine:
    def __init__(self, initialized: bool = False) -> None:
        self.is_initialized = initialized
        self.device = "llama-cpp-sycl"
        self.backend = "llama-cpp-sycl"


class _DummyProcessManager:
    active_job_id = None


class _DummyController:
    def __init__(self, settings: Settings, *, initialized: bool = False) -> None:
        self.settings = settings
        self.engine = _DummyEngine(initialized)
        self.process_manager = _DummyProcessManager()
        self.operation = "idle"
        self.load_requests: list[str] = []
        self.unload_requests = 0
        self.started_ocr: list[Path] = []
        self.started_batches: list[list[Path]] = []

    def request_model_load(self, device: str) -> None:
        self.load_requests.append(device)
        self.operation = "model_loading"

    def request_model_unload(self) -> None:
        self.unload_requests += 1
        self.operation = "model_unloading"

    def start_ocr(self, path: Path) -> None:
        self.started_ocr.append(Path(path))
        self.operation = "ocr"

    def run_batch(self, paths: list[Path]):
        self.started_batches.append([Path(path) for path in paths])
        self.operation = "batch"

        class _Job:
            job_id = "job-1"

        return _Job()

    def update_settings(self, **overrides: object) -> None:
        self.settings = self.settings.with_(**overrides)

    def cancel_model_loading(self) -> None:
        pass

    def cancel_ocr(self) -> None:
        pass

    def cancel_active_batch(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _bridge(
    tmp_path: Path,
    *,
    initialized: bool = False,
    **overrides: object,
) -> tuple[AppWebBridge, _DummyController]:
    settings = Settings(output_dir=str(tmp_path)).with_(**overrides)
    controller = _DummyController(settings, initialized=initialized)
    return AppWebBridge(controller), controller


def _cleanup(bridge: AppWebBridge) -> None:
    bridge._idle_timer.stop()
    bridge._events.shutdown()


def test_single_ocr_is_queued_until_model_load_completes(tmp_path: Path) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(b"test")
    bridge, controller = _bridge(tmp_path, initialized=False)
    try:
        result = json.loads(bridge.startSingleOcr(str(source)))

        assert result == {"ok": True, "queued": True}
        assert controller.load_requests == ["llama-cpp-sycl"]
        assert controller.started_ocr == []

        controller.engine.is_initialized = True
        controller.operation = "idle"
        bridge._run_pending_model_action()

        assert controller.started_ocr == [source.resolve()]
    finally:
        _cleanup(bridge)


def test_batch_is_queued_until_model_load_completes(tmp_path: Path) -> None:
    first = tmp_path / "one.png"
    second = tmp_path / "two.pdf"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    bridge, controller = _bridge(tmp_path, initialized=False)
    try:
        result = json.loads(bridge.startBatch(json.dumps([str(first), str(second)])))

        assert result["ok"] is True
        assert result["queued"] is True
        assert controller.load_requests == ["llama-cpp-sycl"]

        controller.engine.is_initialized = True
        controller.operation = "idle"
        bridge._run_pending_model_action()

        assert controller.started_batches == [[first.resolve(), second.resolve()]]
    finally:
        _cleanup(bridge)


def test_explicit_unload_requests_backend_release_without_quitting(tmp_path: Path) -> None:
    bridge, controller = _bridge(tmp_path, initialized=True)
    try:
        result = json.loads(bridge.unloadModel())

        assert result["ok"] is True
        assert result["already_unloaded"] is False
        assert controller.unload_requests == 1
        assert controller.operation == "model_unloading"
    finally:
        _cleanup(bridge)


def test_idle_auto_unload_only_fires_after_configured_interval(tmp_path: Path) -> None:
    bridge, controller = _bridge(
        tmp_path,
        initialized=True,
        model_auto_unload_minutes=5,
    )
    try:
        bridge._idle_since = time.monotonic() - 4 * 60
        bridge._check_idle_unload()
        assert controller.unload_requests == 0

        bridge._idle_since = time.monotonic() - 6 * 60
        bridge._check_idle_unload()
        assert controller.unload_requests == 1
    finally:
        _cleanup(bridge)


def test_model_memory_settings_are_persisted_via_bridge(tmp_path: Path) -> None:
    bridge, controller = _bridge(tmp_path)
    try:
        result = json.loads(
            bridge.updateSettings(
                json.dumps(
                    {
                        "load_model_at_startup": False,
                        "model_auto_unload_minutes": 30,
                    }
                )
            )
        )

        assert result["ok"] is True
        assert controller.settings.load_model_at_startup is False
        assert controller.settings.model_auto_unload_minutes == 30

        invalid = json.loads(
            bridge.updateSettings(json.dumps({"model_auto_unload_minutes": 5000}))
        )
        assert invalid["ok"] is False
        assert controller.settings.model_auto_unload_minutes == 30
    finally:
        _cleanup(bridge)


def test_model_memory_ui_is_native_and_wired() -> None:
    root = Path(__file__).resolve().parents[2]
    html = (root / "ui" / "web" / "index.html").read_text(encoding="utf-8")
    js = (root / "ui" / "web" / "model_ui.js").read_text(encoding="utf-8")

    assert 'src="model_ui.js"' in html
    assert 'id="model-unload-button"' in html
    assert 'id="load-model-startup-toggle"' in html
    assert 'id="model-auto-unload-select"' in html
    assert 'value="0">Mai<' in html
    assert "unloadModel" in js
    assert "load_model_at_startup" in js
    assert "model_auto_unload_minutes" in js
    assert "!backendAvailable() || !state.singlePath" in js
