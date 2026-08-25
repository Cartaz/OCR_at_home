"""Regression coverage for application/llama-server shutdown semantics."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_closing_main_window_is_a_real_application_exit() -> None:
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    window = (ROOT / "ui" / "window.py").read_text(encoding="utf-8")

    assert "app.setQuitOnLastWindowClosed(True)" in main
    assert "hide_on_close" not in main
    assert "def closeEvent(" not in window
    assert "self.hide()" not in window


def test_event_loop_exit_has_defensive_backend_cleanup() -> None:
    main = (ROOT / "main.py").read_text(encoding="utf-8")

    assert "app.aboutToQuit.connect(bridge.shutdown)" in main
    assert "finally:" in main
    assert "bridge.shutdown()" in main.split("finally:", 1)[1]


def test_owned_llama_server_is_terminated_as_a_process_group() -> None:
    backend = (ROOT / "core" / "llama_backend.py").read_text(encoding="utf-8")

    assert 'start_new_session=(os.name == "posix")' in backend
    assert "os.killpg(process.pid, signal.SIGTERM)" in backend
    assert "process.wait(timeout=5)" in backend
    assert "os.killpg(process.pid, signal.SIGKILL)" in backend
    assert "process.wait(timeout=3)" in backend
    assert "def shutdown(self) -> None:" in backend
    assert "self._stop_server()" in backend.split("def shutdown(self) -> None:", 1)[1]
