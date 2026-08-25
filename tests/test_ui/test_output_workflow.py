from __future__ import annotations

import json
from pathlib import Path

from config.settings import Settings
from core.event_bus import EventBus
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


def _bridge(tmp_path: Path, **overrides: object) -> tuple[AppWebBridge, _DummyController]:
    settings = Settings(output_dir=str(tmp_path)).with_(**overrides)
    controller = _DummyController(settings)
    return AppWebBridge(controller), controller


def _emit_single_image(source: str, text: str) -> None:
    EventBus.emit(
        "ocr_started",
        {"mode": "single", "image_path": source, "is_pdf": False},
    )
    EventBus.emit(
        "ocr_completed",
        {
            "mode": "single",
            "image_path": source,
            "is_pdf": False,
            "text": text,
        },
    )


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
        bridge.shutdown()


def test_single_result_cannot_be_saved_before_real_completion(tmp_path: Path) -> None:
    bridge, _controller = _bridge(tmp_path)
    source = str(tmp_path / "scan.png")
    try:
        rejected = json.loads(bridge.saveSingleResult(source, "txt"))
        assert rejected["ok"] is False
        assert not list(tmp_path.glob("scan*.txt"))

        _emit_single_image(source, "completo")
        saved = json.loads(bridge.saveSingleResult(source, "txt"))
        assert saved["ok"] is True
        assert Path(saved["path"]).read_text(encoding="utf-8") == "completo\n"
    finally:
        bridge.shutdown()


def test_single_pdf_pages_are_saved_only_after_complete_sequence(tmp_path: Path) -> None:
    bridge, _controller = _bridge(tmp_path)
    source = str(tmp_path / "document.pdf")
    try:
        EventBus.emit(
            "ocr_started",
            {"mode": "single", "image_path": source, "is_pdf": True},
        )
        EventBus.emit(
            "pdf_page_completed",
            {
                "mode": "single",
                "pdf_path": source,
                "page_num": 1,
                "total_pages": 2,
                "text": "pagina uno",
            },
        )
        EventBus.emit(
            "pdf_page_completed",
            {
                "mode": "single",
                "pdf_path": source,
                "page_num": 2,
                "total_pages": 2,
                "text": "pagina due",
            },
        )
        EventBus.emit(
            "ocr_completed",
            {"mode": "single", "image_path": source, "is_pdf": True},
        )

        result = json.loads(bridge.saveSinglePdfPages(source, "md"))
        assert result["ok"] is True
        assert result["count"] == 2
        assert [Path(path).name for path in result["paths"]] == [
            "document-page-001.md",
            "document-page-002.md",
        ]
    finally:
        bridge.shutdown()


def test_batch_autosave_uses_start_snapshot_and_saves_pdf_pages(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    bridge, controller = _bridge(
        first_dir,
        batch_auto_save=True,
        batch_output_format="txt",
        batch_save_pdf_pages=True,
    )
    events: list[dict] = []
    bridge.event.connect(lambda raw: events.append(json.loads(raw)))
    source = str(tmp_path / "report.pdf")
    combined = "--- Pagina 1 ---\nuno\n\n--- Pagina 2 ---\ndue"
    try:
        bridge._on_core_event("batch_started", {"job_id": "job", "total_tasks": 1})
        controller.settings = controller.settings.with_(
            output_dir=str(second_dir),
            batch_output_format="md",
            batch_save_pdf_pages=False,
        )
        bridge._on_core_event(
            "batch_task_completed",
            {"job_id": "job", "image_path": source, "text": combined},
        )
        bridge._on_core_event(
            "batch_completed",
            {"job_id": "job", "completed": 1, "total": 1},
        )

        assert (first_dir / "report.txt").is_file()
        assert (first_dir / "report-page-001.txt").read_text(encoding="utf-8") == "uno\n"
        assert (first_dir / "report-page-002.txt").read_text(encoding="utf-8") == "due\n"
        assert not second_dir.exists()

        summaries = [item for item in events if item["type"] == "batch_output_summary"]
        assert summaries[-1]["payload"]["saved"] == 1
        assert summaries[-1]["payload"]["failed"] == 0
        assert summaries[-1]["payload"]["output_dir"] == str(first_dir)
    finally:
        bridge.shutdown()
