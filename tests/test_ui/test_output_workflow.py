from __future__ import annotations

import json
from pathlib import Path

from config.settings import Settings
from ui.app_web_bridge import AppWebBridge


class _DummyEngine:
    is_initialized = False
    device = "llama-cpp-sycl"
    backend = "llama-cpp-sycl"


class _DummyProcessManager:
    active_job_id = None


class _DummyController:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = _DummyEngine()
        self.process_manager = _DummyProcessManager()
        self.operation = "idle"
        self.saved_single: tuple[str, str] | None = None
        self.saved_pages: tuple[str, str] | None = None

    def update_settings(self, **overrides: object) -> None:
        self.settings = self.settings.with_(**overrides)

    def save_single_result(self, source_path: str, file_format: str) -> Path:
        self.saved_single = (source_path, file_format)
        destination = Path(self.settings.output_dir) / f"saved.{file_format}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("canonico\n", encoding="utf-8")
        return destination

    def save_single_pdf_pages(self, source_path: str, file_format: str) -> list[Path]:
        self.saved_pages = (source_path, file_format)
        destination = Path(self.settings.output_dir) / f"page-001.{file_format}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("pagina\n", encoding="utf-8")
        return [destination]

    def cancel_model_loading(self) -> None:
        pass

    def cancel_ocr(self) -> None:
        pass

    def cancel_active_batch(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _bridge(tmp_path: Path, **overrides: object) -> tuple[AppWebBridge, _DummyController]:
    settings = Settings(output_dir=str(tmp_path)).with_(**overrides)
    controller = _DummyController(settings)
    return AppWebBridge(controller), controller


def test_output_settings_are_validated_and_persisted_in_controller(tmp_path: Path) -> None:
    bridge, controller = _bridge(tmp_path)
    try:
        result = json.loads(
            bridge.updateSettings(
                json.dumps(
                    {
                        "batch_auto_save": True,
                        "batch_output_format": "MD",
                        "batch_save_pdf_pages": True,
                    }
                )
            )
        )
        assert result["ok"] is True
        assert controller.settings.batch_auto_save is True
        assert controller.settings.batch_output_format == "md"
        assert controller.settings.batch_save_pdf_pages is True

        invalid = json.loads(
            bridge.updateSettings(json.dumps({"batch_output_format": "pdf"}))
        )
        assert invalid["ok"] is False
        assert controller.settings.batch_output_format == "md"
    finally:
        bridge._events.shutdown()


def test_single_save_delegates_only_source_and_format_to_controller(tmp_path: Path) -> None:
    bridge, controller = _bridge(tmp_path)
    source = str(tmp_path / "scan.png")
    try:
        result = json.loads(bridge.saveSingleResult(source, "txt"))
        assert result["ok"] is True
        assert controller.saved_single == (source, "txt")
        assert Path(result["path"]).read_text(encoding="utf-8") == "canonico\n"
    finally:
        bridge._events.shutdown()


def test_pdf_page_save_delegates_to_controller(tmp_path: Path) -> None:
    bridge, controller = _bridge(tmp_path)
    source = str(tmp_path / "document.pdf")
    try:
        result = json.loads(bridge.saveSinglePdfPages(source, "md"))
        assert result["ok"] is True
        assert result["count"] == 1
        assert controller.saved_pages == (source, "md")
    finally:
        bridge._events.shutdown()
