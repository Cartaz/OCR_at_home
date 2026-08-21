"""Safe text-output helpers for OCR results.

The writer deliberately owns only filesystem concerns: source-derived names,
collision avoidance and atomic publication. OCR/business logic remains elsewhere.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

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


def _candidate_path(directory: Path, stem: str, suffix: str, index: int) -> Path:
    name = f"{stem}{suffix}" if index == 1 else f"{stem}-{index}{suffix}"
    return directory / name


def write_ocr_text(
    output_dir: str | Path,
    source_path: str | Path,
    text: str,
    file_format: str,
) -> Path:
    """Atomically publish OCR text without ever overwriting an existing file.

    The complete temporary file is hard-linked into place. ``os.link`` is
    atomic and fails if the destination already exists, so a concurrent writer
    cannot be overwritten. The temporary name is removed after publication.
    """
    fmt = str(file_format).strip().lower().lstrip(".")
    if fmt not in SUPPORTED_TEXT_FORMATS:
        raise ValueError(f"Formato output non supportato: {file_format}")

    content = str(text)
    if not content.strip():
        raise ValueError("Nessun testo OCR da salvare")

    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise OSError(f"Directory output non valida: {directory}")

    stem = safe_source_stem(source_path)
    suffix = f".{fmt}"

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

        # Persist the new directory entry where supported. Failure to fsync the
        # directory is non-fatal on platforms that do not expose directory fds.
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
