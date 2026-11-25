"""Tests for session-owned transient OCR input staging."""

from pathlib import Path

import pytest

from core.input_staging import InputStaging


def test_stage_png_is_session_owned_and_removed_on_shutdown(tmp_path: Path) -> None:
    staging = InputStaging(tmp_path / "inputs", max_bytes=1024)

    staged = staging.stage_png(b"\x89PNG\r\n\x1a\ncontent")
    session_dir = staging.session_dir

    assert staged.is_file()
    assert staged.parent == session_dir
    assert staged.name.startswith("clipboard-")
    assert staged.suffix == ".png"
    assert staged.read_bytes() == b"\x89PNG\r\n\x1a\ncontent"

    staging.shutdown()

    assert session_dir is not None
    assert not session_dir.exists()
    assert staging.session_dir is None
    staging.shutdown()


def test_stage_png_rejects_empty_oversized_and_post_shutdown_payloads(tmp_path: Path) -> None:
    staging = InputStaging(tmp_path / "inputs", max_bytes=8)

    with pytest.raises(ValueError, match="vuota"):
        staging.stage_png(b"")
    with pytest.raises(ValueError, match="limite"):
        staging.stage_png(b"123456789")

    staging.shutdown()
    with pytest.raises(RuntimeError, match="arrestato"):
        staging.stage_png(b"png")


def test_orphaned_sessions_are_purged_but_live_ones_are_kept(tmp_path: Path) -> None:
    """Audit B6: clipboard images left by a crashed session are removed."""
    root = tmp_path / "inputs"
    live = InputStaging(root, max_bytes=1024)
    live.stage_png(b"\x89PNG\r\n\x1a\n")
    orphan = root / "session-crashed"
    orphan.mkdir()
    (orphan / "clipboard-old.png").write_bytes(b"\x89PNG")

    fresh = InputStaging(root, max_bytes=1024)
    assert fresh.purge_orphaned_sessions() == 1
    assert not orphan.exists()
    assert live.session_dir is not None and live.session_dir.exists()
    live.shutdown()
    fresh.shutdown()
