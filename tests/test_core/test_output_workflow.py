"""Tests for Python-owned OCR output state and persistence policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import Settings
from core.event_bus import EventBus
from core.output_workflow import OutputWorkflow


def _workflow(tmp_path: Path, **overrides: object) -> tuple[OutputWorkflow, list[Settings]]:
    settings = [Settings(output_dir=str(tmp_path)).with_(**overrides)]
    return OutputWorkflow(lambda: settings[0]), settings


def test_single_result_uses_python_owned_completed_text(tmp_path: Path) -> None:
    workflow, _settings = _workflow(tmp_path)
    source = str(tmp_path / "scan.png")
    try:
        with pytest.raises(RuntimeError):
            workflow.save_single_result(source, "txt")

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
                "text": "testo canonico",
            },
        )

        destination = workflow.save_single_result(source, "txt")
        assert destination.read_text(encoding="utf-8") == "testo canonico\n"
    finally:
        workflow.shutdown()


def test_pdf_result_requires_complete_page_sequence(tmp_path: Path) -> None:
    workflow, _settings = _workflow(tmp_path)
    source = str(tmp_path / "document.pdf")
    try:
        # An incomplete completion invalidates the whole temporary result.
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
            "ocr_completed",
            {"mode": "single", "image_path": source, "is_pdf": True},
        )
        with pytest.raises(RuntimeError):
            workflow.save_single_result(source, "txt")

        # A new complete OCR may then become the canonical savable result.
        EventBus.emit(
            "ocr_started",
            {"mode": "single", "image_path": source, "is_pdf": True},
        )
        for page_num, text in ((1, "pagina uno"), (2, "pagina due")):
            EventBus.emit(
                "pdf_page_completed",
                {
                    "mode": "single",
                    "pdf_path": source,
                    "page_num": page_num,
                    "total_pages": 2,
                    "text": text,
                },
            )
        EventBus.emit(
            "ocr_completed",
            {"mode": "single", "image_path": source, "is_pdf": True},
        )

        combined = workflow.save_single_result(source, "txt")
        assert combined.read_text(encoding="utf-8") == (
            "--- Pagina 1 ---\n"
            "pagina uno\n\n"
            "--- Pagina 2 ---\n"
            "pagina due\n"
        )
        pages = workflow.save_single_pdf_pages(source, "md")
        assert [path.name for path in pages] == [
            "document-page-001.md",
            "document-page-002.md",
        ]
    finally:
        workflow.shutdown()


def test_batch_autosave_freezes_start_settings(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    workflow, settings = _workflow(
        first_dir,
        batch_auto_save=True,
        batch_output_format="txt",
        batch_save_pdf_pages=True,
    )
    output_events: list[tuple[str, dict]] = []

    def capture(name: str):
        return lambda payload: output_events.append((name, dict(payload)))

    subscriptions = []
    for name in ("batch_output_saved", "batch_output_save_failed", "batch_output_summary"):
        handler = capture(name)
        EventBus.subscribe(name, handler)
        subscriptions.append((name, handler))

    source = str(tmp_path / "report.pdf")
    combined = "--- Pagina 1 ---\nuno\n\n--- Pagina 2 ---\ndue"
    try:
        EventBus.emit("batch_started", {"job_id": "job", "total_tasks": 1})
        settings[0] = settings[0].with_(
            output_dir=str(second_dir),
            batch_output_format="md",
            batch_save_pdf_pages=False,
        )
        EventBus.emit(
            "batch_task_completed",
            {"job_id": "job", "image_path": source, "text": combined},
        )
        EventBus.emit(
            "batch_completed",
            {"job_id": "job", "completed": 1, "total": 1},
        )

        assert (first_dir / "report.txt").is_file()
        assert (first_dir / "report-page-001.txt").read_text(encoding="utf-8") == "uno\n"
        assert (first_dir / "report-page-002.txt").read_text(encoding="utf-8") == "due\n"
        assert not second_dir.exists()

        summaries = [payload for name, payload in output_events if name == "batch_output_summary"]
        assert summaries[-1] == {
            "saved": 1,
            "failed": 0,
            "output_dir": str(first_dir),
        }
    finally:
        workflow.shutdown()
        for name, handler in subscriptions:
            EventBus.unsubscribe(name, handler)
