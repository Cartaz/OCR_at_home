from __future__ import annotations

from pathlib import Path

import pytest

from core.output_writer import safe_source_stem, write_ocr_text


def test_safe_source_stem_is_portable() -> None:
    assert safe_source_stem("/tmp/report:2026?.pdf") == "report_2026_"
    assert safe_source_stem("/tmp/.pdf") == "ocr-result"


def test_write_ocr_text_creates_requested_format(tmp_path: Path) -> None:
    path = write_ocr_text(tmp_path, "/docs/report.pdf", "testo OCR", "txt")

    assert path == tmp_path / "report.txt"
    assert path.read_text(encoding="utf-8") == "testo OCR\n"


def test_write_ocr_text_never_overwrites_existing_file(tmp_path: Path) -> None:
    existing = tmp_path / "report.md"
    existing.write_text("originale\n", encoding="utf-8")

    first = write_ocr_text(tmp_path, "/docs/report.pdf", "nuovo", "md")
    second = write_ocr_text(tmp_path, "/docs/report.pdf", "ancora", "md")

    assert existing.read_text(encoding="utf-8") == "originale\n"
    assert first.name == "report-2.md"
    assert second.name == "report-3.md"
    assert first.read_text(encoding="utf-8") == "nuovo\n"
    assert second.read_text(encoding="utf-8") == "ancora\n"


def test_write_ocr_text_rejects_empty_content_and_unknown_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Nessun testo"):
        write_ocr_text(tmp_path, "source.png", "   ", "txt")

    with pytest.raises(ValueError, match="Formato output"):
        write_ocr_text(tmp_path, "source.png", "test", "pdf")


def test_writer_leaves_no_temporary_files_after_success(tmp_path: Path) -> None:
    write_ocr_text(tmp_path, "scan.png", "ok", "txt")
    assert [path.name for path in tmp_path.iterdir()] == ["scan.txt"]
