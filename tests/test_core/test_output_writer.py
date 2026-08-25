from __future__ import annotations

from pathlib import Path

import pytest

from core.output_writer import (
    safe_source_stem,
    split_combined_pdf_text,
    write_ocr_pages,
    write_ocr_text,
)


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


def test_split_combined_pdf_text_recovers_ordered_pages() -> None:
    combined = "--- Pagina 1 ---\nuno\n\n--- Pagina 2 ---\ndue\nrighe"
    assert split_combined_pdf_text(combined) == ["uno", "due\nrighe"]


def test_split_combined_pdf_text_treats_unmarked_text_as_single_page() -> None:
    assert split_combined_pdf_text("pagina unica") == ["pagina unica"]


def test_split_combined_pdf_text_rejects_ambiguous_numbering() -> None:
    combined = "--- Pagina 1 ---\nuno\n--- Pagina 3 ---\ntre"
    with pytest.raises(ValueError, match="marcatori pagina"):
        split_combined_pdf_text(combined)


def test_write_ocr_pages_uses_numbered_collision_safe_names(tmp_path: Path) -> None:
    first = write_ocr_pages(tmp_path, "/docs/report.pdf", ["uno", ""], "txt")
    second = write_ocr_pages(tmp_path, "/docs/report.pdf", ["uno", "due"], "txt")

    assert [path.name for path in first] == [
        "report-page-001.txt",
        "report-page-002.txt",
    ]
    assert [path.name for path in second] == [
        "report-page-001-2.txt",
        "report-page-002-2.txt",
    ]
    assert first[0].read_text(encoding="utf-8") == "uno\n"
    assert first[1].read_text(encoding="utf-8") == ""
    assert second[1].read_text(encoding="utf-8") == "due\n"


def test_write_ocr_pages_rolls_back_files_if_later_page_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import core.output_writer as output_writer

    original = output_writer._write_atomic_unique
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second-page failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(output_writer, "_write_atomic_unique", fail_second)

    with pytest.raises(OSError, match="second-page failure"):
        write_ocr_pages(tmp_path, "/docs/report.pdf", ["uno", "due"], "txt")

    assert list(tmp_path.iterdir()) == []