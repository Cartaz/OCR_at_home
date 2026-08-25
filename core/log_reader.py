"""Bounded helpers for presenting application log tails."""

from __future__ import annotations

from pathlib import Path

DEFAULT_MAX_BYTES = 256 * 1024


def read_log_tail(
    path: str | Path,
    max_lines: int,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> str:
    """Return recent log lines while reading at most ``max_bytes`` from disk.

    The UI polls this helper while the log view is open. Reading from the end
    prevents latency and memory usage from growing with the lifetime of the log
    file. A first partial line is discarded when the byte window begins in the
    middle of an older record.
    """
    line_limit = int(max_lines)
    byte_limit = int(max_bytes)
    if line_limit <= 0:
        raise ValueError("max_lines deve essere > 0")
    if byte_limit <= 0:
        raise ValueError("max_bytes deve essere > 0")

    log_path = Path(path)
    try:
        size = log_path.stat().st_size
    except FileNotFoundError:
        return ""
    if size <= 0:
        return ""

    start = max(0, size - byte_limit)
    with log_path.open("rb") as handle:
        handle.seek(start)
        raw = handle.read(byte_limit)

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    return "\n".join(lines[-line_limit:])
