"""Tests for Python-owned OCR output state and persistence policy."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from config.settings import Settings
from core.event_bus import EventBus
from core.output_workflow import OutputWorkflow


def _workflow(tmp_path: Path, **overrides: object) -> tuple[OutputWorkflow, list[Settings]]:
    settings = [Settings(output_dir=str(tmp_path)).with_(**overrides)]
    return OutputWorkflow(lambda: settings[0]), settings


def _save_and_wait(request, source: str, fmt: str) -> dict:
    done = threading.Event()
    payloads: list[dict] = []

    def handler(payload: dict) -> None:
        payloads.append(dict(payload))
        done.set()

    EventBus.subscribe("single_output_saved", handler)
    EventBus.subscribe("single_output_save_failed", handler)
    try:
        request(source, fmt)
        assert done.wait(timeout=3)
    finally:
        EventBus.unsubscribe("single_output_saved", handler)
        EventBus.unsubscribe("single_output_save_failed", handler)
    return payloads[0]


def test_single_result_uses_python_owned_completed_text(tmp_path: Path) -> None:
    workflow, _settings = _workflow(tmp_path)
    source = str(tmp_path / "scan.png")
    try:
        with pytest.raises(RuntimeError):
            workflow.request_save_single_result(source, "txt")

        EventBus.emit("ocr_started", {"mode": "single", "image_path": source, "is_pdf": False})
        EventBus.emit(
            "ocr_completed",
            {"mode": "single", "image_path": source, "is_pdf": False, "text": "testo canonico", "pages": []},
        )

        payload = _save_and_wait(workflow.request_save_single_result, source, "txt")
        assert Path(payload["path"]).read_text(encoding="utf-8") == "testo canonico\n"
        with pytest.raises(RuntimeError, match="pagina PDF"):
            workflow.request_save_single_pdf_pages(source, "txt")
    finally:
        workflow.shutdown()


def test_manual_save_request_returns_while_writer_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workflow, _settings = _workflow(tmp_path)
    source = str(tmp_path / "scan.png")
    writer_started = threading.Event()
    writer_release = threading.Event()
    saved_event = threading.Event()
    payloads: list[dict] = []

    def blocked_writer(*_args, **_kwargs) -> Path:
        writer_started.set()
        assert writer_release.wait(timeout=2)
        return tmp_path / "scan.txt"

    def capture(payload: dict) -> None:
        payloads.append(dict(payload))
        saved_event.set()

    monkeypatch.setattr("core.output_workflow.write_ocr_text", blocked_writer)
    EventBus.subscribe("single_output_saved", capture)
    try:
        EventBus.emit(
            "ocr_completed",
            {
                "mode": "single",
                "image_path": source,
                "is_pdf": False,
                "text": "testo canonico",
            },
        )

        request_id = workflow.request_save_single_result(source, "txt")
        assert request_id
        assert writer_started.wait(timeout=1)
        assert not saved_event.is_set()

        with pytest.raises(RuntimeError, match="già in corso"):
            workflow.request_save_single_result(source, "md")

        writer_release.set()
        assert saved_event.wait(timeout=1)
        assert payloads[-1] == {
            "request_id": request_id,
            "kind": "combined",
            "path": str(tmp_path / "scan.txt"),
            "name": "scan.txt",
        }
    finally:
        writer_release.set()
        EventBus.unsubscribe("single_output_saved", capture)
        workflow.shutdown()


def test_pdf_pages_come_from_the_structured_result(tmp_path: Path) -> None:
    """Audit M5: pages are never re-parsed from the combined text, so OCR text
    that itself contains a page marker cannot corrupt the page files."""
    workflow, _settings = _workflow(tmp_path)
    source = str(tmp_path / "document.pdf")
    tricky = "--- Pagina 7 ---\ncitazione nel testo"
    try:
        EventBus.emit("ocr_started", {"mode": "single", "image_path": source, "is_pdf": True})
        EventBus.emit(
            "ocr_completed",
            {
                "mode": "single",
                "image_path": source,
                "is_pdf": True,
                "text": f"--- Pagina 1 ---\npagina uno\n\n--- Pagina 2 ---\n{tricky}",
                "pages": ["pagina uno", tricky],
            },
        )
        payload = _save_and_wait(workflow.request_save_single_pdf_pages, source, "md")
        names = [Path(path).name for path in payload["paths"]]
        assert names == ["document-page-001.md", "document-page-002.md"]
        assert Path(payload["paths"][1]).read_text(encoding="utf-8") == tricky + "\n"
    finally:
        workflow.shutdown()


def test_cancelled_ocr_clears_the_completed_result(tmp_path: Path) -> None:
    workflow, _settings = _workflow(tmp_path)
    source = str(tmp_path / "scan.png")
    try:
        EventBus.emit("ocr_completed", {"mode": "single", "image_path": source, "text": "x", "pages": []})
        EventBus.emit("ocr_started", {"mode": "single", "image_path": source})
        with pytest.raises(RuntimeError):
            workflow.request_save_single_result(source, "txt")
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
            {"job_id": "job", "image_path": source, "text": combined, "pages": ["uno", "due"]},
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