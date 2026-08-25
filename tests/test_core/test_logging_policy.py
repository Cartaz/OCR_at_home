from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_application_log_is_rotated_and_ui_reads_a_bounded_tail() -> None:
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "web_bridge.py").read_text(encoding="utf-8")

    assert "RotatingFileHandler" in main
    assert "maxBytes=5 * 1024 * 1024" in main
    assert "backupCount=3" in main
    assert "read_log_tail(AppMeta.LOG_PATH, max_lines)" in bridge

    get_logs = bridge.split("def getLogs", 1)[1].split("@Slot(str)", 1)[0]
    assert "read_text" not in get_logs
