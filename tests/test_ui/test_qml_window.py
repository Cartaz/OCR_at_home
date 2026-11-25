"""Load the real QML interface offscreen and exercise it."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtQuickControls2 import QQuickStyle

from tests.test_ui.test_backend import FakeController
from ui.backend import UiBackend
from ui.window import QML_ROOT, SHADER_PACKAGE, QmlMainWindow


@pytest.fixture
def qml_messages():
    messages: list[str] = []

    def handler(mode, _context, message):
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            messages.append(message)

    previous = qInstallMessageHandler(handler)
    yield messages
    qInstallMessageHandler(previous)


def _process(qapp, rounds: int = 5) -> None:
    for _ in range(rounds):
        qapp.processEvents()


def test_main_window_loads_without_qml_warnings_and_renders(qapp, qml_messages, tmp_path) -> None:
    QQuickStyle.setStyle("Basic")
    backend = UiBackend(FakeController())
    window = QmlMainWindow(backend)
    try:
        window.window.resize(1100, 780)
        window.show()
        for view in ("ocr", "batch", "logs", "settings", "ocr"):
            backend.setView(view)
            _process(qapp)
        backend._notice("Titolo", "Messaggio", "dettagli", True)
        _process(qapp)
        image = window.window.grabWindow()
        assert not image.isNull()
        assert len({image.pixel(x, y) for x in range(0, image.width(), 37) for y in range(0, image.height(), 41)}) > 3
        relevant = [m for m in qml_messages if "qml" in m.lower() or "Main.qml" in m]
        assert relevant == []
    finally:
        window.shutdown()
        backend.shutdown()


@pytest.mark.parametrize("width", [480, 860, 1237])
def test_layout_breakpoints_load_cleanly(qapp, qml_messages, width) -> None:
    QQuickStyle.setStyle("Basic")
    backend = UiBackend(FakeController())
    window = QmlMainWindow(backend)
    try:
        window.window.resize(width, 700)
        window.show()
        _process(qapp)
        assert [m for m in qml_messages if ".qml" in m] == []
    finally:
        window.shutdown()
        backend.shutdown()


def test_compiled_shader_matches_its_source(tmp_path) -> None:
    import PySide6

    # The qsb binary ships with PySide6-Addons (requirements-dev.txt); the
    # runtime only needs the committed .qsb package.
    qsb = Path(PySide6.__file__).parent / "qsb"
    if not qsb.exists():
        pytest.skip("qsb non disponibile (installa requirements-dev.txt)")
    rebuilt = tmp_path / "neumorphic.frag.qsb"
    subprocess.run(
        [str(qsb), "--qt6", "-o", str(rebuilt), str(QML_ROOT / "shaders" / "neumorphic.frag")],
        check=True,
        capture_output=True,
    )
    assert rebuilt.read_bytes() == SHADER_PACKAGE.read_bytes(), (
        "Ricompila lo shader: pyside6-qsb --qt6 -o ui/qml/shaders/neumorphic.frag.qsb "
        "ui/qml/shaders/neumorphic.frag"
    )
