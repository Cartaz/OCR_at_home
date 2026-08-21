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
                # Hard-link publication is atomic and fails when the target
                # already exists, so no concurrent writer can be overwritten.
                os.link(temp_path, destination)
                break
            except FileExistsError:
                index += 1

        try:
            dir_fd = os.open(directory, os.O_RDONLY)
        except OSError:
            dir_fd = -1
        if dir_fd >= 0:
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
            finally:
                os.close(dir_fd)

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
    """Publish one collision-safe output file per PDF page.

    Empty OCR pages are represented by an empty file so page numbering remains
    faithful to the source PDF. Each page is independently atomically published
    and existing files are never replaced.
    """
    if isinstance(page_texts, (str, bytes)) or not page_texts:
        raise ValueError("Nessuna pagina PDF da salvare")

    fmt = _normalize_format(file_format)
    directory = _prepare_output_directory(output_dir)
    base_stem = safe_source_stem(source_path)
    width = max(3, len(str(len(page_texts))))
    outputs: list[Path] = []
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
