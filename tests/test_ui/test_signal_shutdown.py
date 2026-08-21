"""Signal-path regressions for the desktop entry point."""

from __future__ import annotations

import signal

import pytest

import main as app_main


class _FakeApp:
    def __init__(self) -> None:
        self.quit_calls = 0

    def quit(self) -> None:
        self.quit_calls += 1


class _FakeQApplication:
    current: _FakeApp | None = None

    @classmethod
    def instance(cls):
        return cls.current


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_signal_handler_requests_qt_event_loop_exit(monkeypatch, signum: int) -> None:
    app = _FakeApp()
    _FakeQApplication.current = app
    monkeypatch.setattr(app_main, "QApplication", _FakeQApplication)

    app_main._signal_handler(signum, None)

    assert app.quit_calls == 1


def test_signal_handler_without_qt_app_runs_controller_cleanup(monkeypatch) -> None:
    calls: list[str] = []
    _FakeQApplication.current = None
    monkeypatch.setattr(app_main, "QApplication", _FakeQApplication)
    monkeypatch.setattr(app_main, "_shutdown_controller_ref", lambda: calls.append("shutdown"))

    with pytest.raises(SystemExit) as exc:
        app_main._signal_handler(signal.SIGTERM, None)

    assert exc.value.code == 0
    assert calls == ["shutdown"]
