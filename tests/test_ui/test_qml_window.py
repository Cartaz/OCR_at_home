"""Load the real QML interface offscreen and exercise it."""

from __future__ import annotations


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


def test_compiled_shader_was_rebuilt_from_the_current_source() -> None:
    """qsb output is not byte-reproducible across machines, so the committed
    package records the SHA-256 of the source it was compiled from. Editing
    neumorphic.frag without recompiling (and updating the hash) fails here;
    the QML tests above prove the committed package actually renders."""
    import hashlib

    source = QML_ROOT / "shaders" / "neumorphic.frag"
    recorded = (QML_ROOT / "shaders" / "neumorphic.frag.qsb.source-sha256").read_text().strip()
    assert SHADER_PACKAGE.is_file()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == recorded, (
        "Ricompila lo shader e aggiorna l'hash:\n"
        "  qsb --qt6 -o ui/qml/shaders/neumorphic.frag.qsb ui/qml/shaders/neumorphic.frag\n"
        "  sha256sum ui/qml/shaders/neumorphic.frag | cut -d' ' -f1 "
        "> ui/qml/shaders/neumorphic.frag.qsb.source-sha256"
    )
