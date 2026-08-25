from __future__ import annotations

from pathlib import Path

import pytest

from core.log_reader import read_log_tail


def test_missing_log_returns_empty_string(tmp_path: Path) -> None:
    assert read_log_tail(tmp_path / "missing.log", 20) == ""


def test_log_tail_returns_only_requested_lines(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    path.write_text("\n".join(f"line-{index}" for index in range(100)) + "\n", encoding="utf-8")

    assert read_log_tail(path, 3) == "line-97\nline-98\nline-99"


def test_log_tail_discards_partial_first_record_when_window_is_bounded(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    path.write_text(
        "old-record-that-will-be-cut\nrecent-one\nrecent-two\n",
        encoding="utf-8",
    )

    result = read_log_tail(path, 20, max_bytes=25)

    assert "old-record" not in result
    assert result.endswith("recent-two")


def test_log_tail_validates_bounds(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    path.write_text("one\n", encoding="utf-8")

    with pytest.raises(ValueError):
        read_log_tail(path, 0)
    with pytest.raises(ValueError):
        read_log_tail(path, 10, max_bytes=0)
