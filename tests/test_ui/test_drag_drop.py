"""Drag-and-drop tests across the native shell, bridge and WebEngine UI."""

from __future__ import annotations

import json
from types import SimpleNamespace

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication

from core.app_controller import OP_IDLE, OP_OCR
from tests.test_ui.test_webengine_smoke import (
    _close_window,
    _load_window,
    _run_json_script,
)
from ui.web_bridge import WebBridge
from ui.window import MainWindow


class _MimeEvent:
    def __init__(self, mime: QMimeData) -> None:
        self._mime = mime

    def mimeData(self) -> QMimeData:
        return self._mime


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_native_drop_exposes_only_local_file_urls(tmp_path) -> None:
    _ = _app()
    local = tmp_path / "scan.png"
    local.write_bytes(b"test")
    mime = QMimeData()
    mime.setUrls(
        [
            QUrl.fromLocalFile(str(local)),
            QUrl("https://example.com/remote.png"),
        ]
    )

    assert MainWindow._local_drop_paths(_MimeEvent(mime)) == [str(local)]


def test_bridge_validates_and_publishes_dropped_files_atomically(tmp_path) -> None:
    _ = _app()
    controller = SimpleNamespace(operation=OP_IDLE)
    bridge = WebBridge(controller)
    events: list[dict[str, object]] = []
    bridge.event.connect(lambda raw: events.append(json.loads(raw)))

    first = tmp_path / "one.png"
    second = tmp_path / "two.pdf"
    first.write_bytes(b"image")
    second.write_bytes(b"pdf")

    bridge.accept_dropped_paths([str(first), str(first), str(second)])

    assert events == [
        {
            "type": "files_dropped",
            "payload": {
                "paths": [str(first.resolve()), str(second.resolve())],
                "names": ["one.png", "two.pdf"],
            },
        }
    ]
    bridge.deleteLater()


def test_bridge_rejects_drop_while_operation_is_running(tmp_path) -> None:
    _ = _app()
    controller = SimpleNamespace(operation=OP_OCR)
    bridge = WebBridge(controller)
    events: list[dict[str, object]] = []
    bridge.event.connect(lambda raw: events.append(json.loads(raw)))
    source = tmp_path / "scan.png"
    source.write_bytes(b"image")

    bridge.accept_dropped_paths([str(source)])

    assert events == [
        {
            "type": "ui_error",
            "payload": {
                "message": "Attendi la conclusione dell'operazione prima di cambiare file.",
                "details": "",
            },
        }
    ]
    bridge.deleteLater()


def test_webengine_routes_validated_drops_by_active_view() -> None:
    app, window = _load_window()
    script = """
        (() => {
            state.operation = 'idle';
            state.modelReady = true;
            state.devices = [{available: true, device_name: 'SYCL'}];

            setView('ocr');
            handleEvent(JSON.stringify({
                type: 'files_dropped',
                payload: {paths: ['/tmp/one.png']}
            }));
            const single = [
                state.activeView,
                state.singlePath,
                document.querySelector('#single-file-name').textContent,
                document.querySelector('#single-start-button').disabled
            ];

            setView('ocr');
            handleEvent(JSON.stringify({
                type: 'files_dropped',
                payload: {paths: ['/tmp/one.png', '/tmp/two.pdf']}
            }));
            const multiFromOcr = [
                state.activeView,
                [...state.batchPaths],
                document.querySelector('#batch-count-label').textContent
            ];

            setView('batch');
            handleEvent(JSON.stringify({
                type: 'files_dropped',
                payload: {paths: ['/tmp/only.pdf']}
            }));
            const oneInBatch = [
                state.activeView,
                [...state.batchPaths],
                document.querySelector('#batch-count-label').textContent
            ];

            setView('settings');
            handleEvent(JSON.stringify({
                type: 'files_dropped',
                payload: {paths: ['/tmp/from-settings.png']}
            }));
            const oneFromSettings = [state.activeView, state.singlePath];

            return JSON.stringify([
                single,
                multiFromOcr,
                oneInBatch,
                oneFromSettings,
                document.querySelector('#single-file-button').title,
                document.querySelector('#single-file-display').getAttribute('aria-description')
            ]);
        })();
    """

    assert _run_json_script(window, script) == [
        ["ocr", "/tmp/one.png", "one.png", False],
        ["batch", ["/tmp/one.png", "/tmp/two.pdf"], "2 file selezionati"],
        ["batch", ["/tmp/only.pdf"], "1 file selezionato"],
        ["ocr", "/tmp/from-settings.png"],
        "Scegli file o trascinalo nella finestra (Ctrl+O)",
        "Puoi trascinare un'immagine o un PDF nella finestra oppure incollare un'immagine con Ctrl+V.",
    ]
    _close_window(window)
    _ = app
