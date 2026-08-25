from __future__ import annotations

import json
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
        self.started_ocr: list[Path] = []
        self.started_batches: list[list[Path]] = []
        self.idle_checks = 0
        self.unload_requests = 0

    @property
    def model_ready(self) -> bool:
        return self.engine.is_initialized

    @property
    def model_device(self) -> str:
        return self.engine.device

    @property
    def model_backend(self) -> str:
        return self.engine.backend

    @property
    def active_batch_id(self):
        return self.process_manager.active_job_id

    def start_ocr_or_queue(self, path: Path) -> bool:
        if self.engine.is_initialized:
            self.started_ocr.append(Path(path))
            self.operation = "ocr"
            return False
        return True

    def run_batch_or_queue(self, paths: list[Path]):
        if self.engine.is_initialized:
            self.started_batches.append([Path(path) for path in paths])
            self.operation = "batch"

            class _Job:
                job_id = "job-1"

            return False, _Job()
        return True, None

    def request_model_load(self, _device: str) -> None:
        self.operation = "model_loading"

    def request_model_unload(self) -> bool:
        self.unload_requests += 1
        if not self.engine.is_initialized:
            return False
        self.operation = "model_unloading"
        return True

    def check_idle_model_unload(self) -> bool:
        self.idle_checks += 1
        return False

    def update_settings(self, **overrides: object) -> None:
        self.settings = self.settings.with_(**overrides)

    def save_single_result(self, source_path: str, file_format: str) -> Path:
        return Path(self.settings.output_dir) / f"{Path(source_path).stem}.{file_format}"

    def save_single_pdf_pages(self, source_path: str, file_format: str) -> list[Path]:
        return [
            Path(self.settings.output_dir)
            / f"{Path(source_path).stem}-page-001.{file_format}"
        ]

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


def test_single_ocr_queue_decision_is_owned_by_controller(tmp_path: Path) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(b"test")
    bridge, controller = _bridge(tmp_path, initialized=False)
    try:
        result = json.loads(bridge.startSingleOcr(str(source)))

        assert result == {"ok": True, "queued": True}
        assert controller.started_ocr == []
        assert not hasattr(bridge, "_pending_model_action")
    finally:
        _cleanup(bridge)


def test_batch_queue_decision_is_owned_by_controller(tmp_path: Path) -> None:
    first = tmp_path / "one.png"
    second = tmp_path / "two.pdf"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    bridge, controller = _bridge(tmp_path, initialized=False)
    try:
        result = json.loads(bridge.startBatch(json.dumps([str(first), str(second)])))

        assert result["ok"] is True
        assert result["queued"] is True
        assert result["job_id"] == ""
        assert controller.started_batches == []
    finally:
        _cleanup(bridge)


def test_ready_ocr_delegates_directly_to_controller(tmp_path: Path) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(b"test")
    bridge, controller = _bridge(tmp_path, initialized=True)
    try:
        result = json.loads(bridge.startSingleOcr(str(source)))

        assert result == {"ok": True, "queued": False}
        assert controller.started_ocr == [source.resolve()]
    finally:
        _cleanup(bridge)


def test_explicit_unload_only_requests_core_lifecycle(tmp_path: Path) -> None:
    bridge, controller = _bridge(tmp_path, initialized=True)
    try:
        result = json.loads(bridge.unloadModel())

        assert result["ok"] is True
        assert result["already_unloaded"] is False
        assert controller.unload_requests == 1
        assert controller.operation == "model_unloading"
        assert not hasattr(bridge, "_model_thread")
    finally:
        _cleanup(bridge)


def test_idle_timer_only_triggers_core_policy_check(tmp_path: Path) -> None:
    bridge, controller = _bridge(
        tmp_path,
        initialized=True,
        model_auto_unload_minutes=5,
    )
    try:
        bridge._check_idle_unload()
        assert controller.idle_checks == 1
        assert controller.unload_requests == 0
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
