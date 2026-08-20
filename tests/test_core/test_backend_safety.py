"""Test compatibilità dei parametri llama-server usati dal backend."""

from pathlib import Path


def test_backend_does_not_use_global_process_kill() -> None:
    source = (Path(__file__).parents[2] / "core" / "llama_backend.py").read_text(encoding="utf-8")
    assert "pkill" not in source
    assert "killall" not in source
