"""Safe text-output helpers for OCR results.

The writer deliberately owns only filesystem concerns: source-derived names,
collision avoidance and atomic publication. OCR/business logic remains elsewhere.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Sequence

SUPPORTED_TEXT_FORMATS = {"txt", "md"}
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_PDF_PAGE_MARKER = re.compile(r"(?m)^--- Pagina (\d+) ---\n")


def safe_source_stem(source_path: str | Path) -> str:
    """Return a portable filename stem derived from the source document."""
    source = Path(source_path)
    name = source.name.strip()
    if name.startswith(".") and name.count(".") == 1:
        stem = ""
    else:
        stem = source.stem.strip().strip(".")
    stem = _INVALID_FILENAME_CHARS.sub("_", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or "ocr-result"


def split_combined_pdf_text(combined_text: str) -> list[str]:
    """Recover page texts from the deterministic combined PDF representation.

    Multi-page OCR output is produced internally as ``--- Pagina N ---`` blocks.
    Marker numbering is validated before splitting; malformed or ambiguous data is
    rejected rather than silently producing incorrectly numbered page files.
    A single-page PDF has no marker and is therefore represented by one element.
    """
    text = str(combined_text)
    matches = list(_PDF_PAGE_MARKER.finditer(text))
    if not matches:
        return [text]

    numbers = [int(match.group(1)) for match in matches]
    expected = list(range(1, len(matches) + 1))
    if numbers != expected:
        raise ValueError("Output PDF combinato con marcatori pagina non validi")

    pages: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages.append(text[start:end].strip("\n"))
    return pages


def _normalize_format(file_format: str) -> str:
    fmt = str(file_format).strip().lower().lstrip(".")
    if fmt not in SUPPORTED_TEXT_FORMATS:
        raise ValueError(f"Formato output non supportato: {file_format}")
    return fmt


def _candidate_path(directory: Path, stem: str, suffix: str, index: int) -> Path:
    name = f"{stem}{suffix}" if index == 1 else f"{stem}-{index}{suffix}"
    return directory / name


def _prepare_output_directory(output_dir: str | Path) -> Path:
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise OSError(f"Directory output non valida: {directory}")
    return directory


def _fsync_directory(directory: Path) -> None:
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
    finally:
        os.close(dir_fd)


def _write_atomic_unique(
    directory: Path,
    stem: str,
    content: str,
    suffix: str,
    *,
    allow_empty: bool = False,
) -> Path:
    if not allow_empty and not content.strip():
        raise ValueError("Nessun testo OCR da salvare")

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{stem}.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            if content and not content.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        index = 1
        while True:
            destination = _candidate_path(directory, stem, suffix, index)
            try:
                os.link(temp_path, destination)
                break
            except FileExistsError:
                index += 1

        _fsync_directory(directory)
        return destination
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def write_ocr_text(
    output_dir: str | Path,
    source_path: str | Path,
    text: str,
    file_format: str,
) -> Path:
    """Atomically publish OCR text without ever overwriting an existing file."""
    fmt = _normalize_format(file_format)
    directory = _prepare_output_directory(output_dir)
    return _write_atomic_unique(
        directory,
        safe_source_stem(source_path),
        str(text),
        f".{fmt}",
    )


def write_ocr_pages(
    output_dir: str | Path,
    source_path: str | Path,
    page_texts: Sequence[str],
    file_format: str,
) -> list[Path]:
    """Publish one collision-safe file per PDF page as one logical output set.

    Each individual file is published atomically. If a later page fails, files
    already published by this invocation are removed so a failed operation does
    not silently leave a partial page set behind.
    """
    if isinstance(page_texts, (str, bytes)) or not page_texts:
        raise ValueError("Nessuna pagina PDF da salvare")

    fmt = _normalize_format(file_format)
    directory = _prepare_output_directory(output_dir)
    base_stem = safe_source_stem(source_path)
    width = max(3, len(str(len(page_texts))))
    outputs: list[Path] = []
    try:
        for page_num, page_text in enumerate(page_texts, start=1):
            outputs.append(
                _write_atomic_unique(
                    directory,
                    f"{base_stem}-page-{page_num:0{width}d}",
                    str(page_text),
                    f".{fmt}",
                    allow_empty=True,
                )
            )
        return outputs
    except Exception as exc:
        cleanup_failures: list[str] = []
        for path in reversed(outputs):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError as cleanup_exc:
                cleanup_failures.append(f"{path}: {cleanup_exc}")
        _fsync_directory(directory)
        if cleanup_failures:
            raise OSError(
                "Salvataggio pagine fallito e cleanup output parziale incompleto: "
                + "; ".join(cleanup_failures)
            ) from exc
        raise