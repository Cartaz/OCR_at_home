"""Test che main.py non introduca terminazioni globali di llama-server."""

from pathlib import Path


def test_main_has_no_global_pkill() -> None:
    source = (Path(__file__).parents[2] / "main.py").read_text(encoding="utf-8")
    assert "pkill" not in source
    assert "subprocess.run" not in source
