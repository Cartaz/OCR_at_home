from __future__ import annotations

from pathlib import Path

import pytest

from core.event_bus import EventBus
from core.single_output_service import SingleOutputService


def _complete_image(service: SingleOutputService, source: Path, text: str) -> None:
    EventBus.emit(
        "ocr_started",
        {"mode": "single", "image_path": str(source), "is_pdf": False},
    )
    EventBus.emit(
        "ocr_completed",
        {
            "mode": "single",
            "image_path": str(source),
            "is_pdf": False,
            "text": text,
        },
    )


def test_single_output_uses_python_canonical_text(tmp_path: Path) -> None:
    service = SingleOutputService()
    source = tmp_path / "scan.png"
    try:
        _complete_image(service, source, "testo canonico")
        destination = service.save_result(tmp_path, source, "txt")
        assert destination.read_text(encoding="utf-8") == "testo canonico\n"
    finally:
        service.shutdown()


def test_new_ocr_invalidates_previous_result(tmp_path: Path) -> None:
    service = SingleOutputService()
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    try:
        _complete_image(service, first, "primo")
        EventBus.emit(
            "ocr_started",
            {"mode": "single", "image_path": str(second), "is_pdf": False},
        )
        with pytest.raises(RuntimeError):
            service.save_result(tmp_path, first, "txt")
    finally:
        service.shutdown()


def test_cancelled_ocr_cannot_be_saved(tmp_path: Path) -> None:
    service = SingleOutputService()
    source = tmp_path / "scan.png"
    try:
        EventBus.emit(
            "ocr_started",
            {"mode": "single", "image_path": str(source), "is_pdf": False},
        )
        EventBus.emit("ocr_cancelled", {"mode": "single"})
        with pytest.raises(RuntimeError):
            service.save_result(tmp_path, source, "txt")
    finally:
        service.shutdown()


def test_pdf_pages_and_combined_text_are_reconstructed_from_core_events(
    tmp_path: Path,
) -> None:
    service = SingleOutputService()
    source = tmp_path / "document.pdf"
    try:
        EventBus.emit(
            "ocr_started",
            {"mode": "single", "image_path": str(source), "is_pdf": True},
        )
        for page_num, text in ((1, "pagina uno"), (2, "pagina due")):
            EventBus.emit(
                "pdf_page_completed",
                {
                    "mode": "single",
                    "pdf_path": str(source),
                    "page_num": page_num,
                    "total_pages": 2,
                    "text": text,
                },
            )
        EventBus.emit(
            "ocr_completed",
            {
                "mode": "single",
                "image_path": str(source),
                "is_pdf": True,
                "text": "",
            },
        )

        combined = service.save_result(tmp_path, source, "md")
        assert combined.read_text(encoding="utf-8") == (
            "--- Pagina 1 ---\n"
            "pagina uno\n\n"
            "--- Pagina 2 ---\n"
            "pagina due\n"
        )

        pages = service.save_pdf_pages(tmp_path, source, "txt")
        assert [path.name for path in pages] == [
            "document-page-001.txt",
            "document-page-002.txt",
        ]
        assert pages[0].read_text(encoding="utf-8") == "pagina uno\n"
        assert pages[1].read_text(encoding="utf-8") == "pagina due\n"
    finally:
        service.shutdown()


def test_incomplete_pdf_sequence_is_not_savable(tmp_path: Path) -> None:
    service = SingleOutputService()
    source = tmp_path / "document.pdf"
    try:
        EventBus.emit(
            "ocr_started",
            {"mode": "single", "image_path": str(source), "is_pdf": True},
        )
        EventBus.emit(
            "pdf_page_completed",
            {
                "mode": "single",
                "pdf_path": str(source),
                "page_num": 1,
                "total_pages": 2,
                "text": "solo una pagina",
            },
        )
        EventBus.emit(
            "ocr_completed",
            {
                "mode": "single",
                "image_path": str(source),
                "is_pdf": True,
                "text": "",
            },
        )
        with pytest.raises(RuntimeError):
            service.save_result(tmp_path, source, "txt")
    finally:
        service.shutdown()
