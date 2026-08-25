"""Offscreen smoke test for the local Qt WebEngine shell."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from ui.window import MainWindow

ROOT = Path(__file__).parents[2]


def _load_window() -> tuple[QApplication, MainWindow]:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ROOT / "ui" / "web")
    result: list[bool] = []
    loop = QEventLoop()

    def finished(ok: bool) -> None:
        result.append(ok)
        loop.quit()

    window.loadFinished.connect(finished)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert result == [True], "Il frontend HTML locale non è caricabile"
    return app, window


def _close_window(window: MainWindow) -> None:
    window.allow_close = True
    window.close()
    window.deleteLater()


def _run_json_script(window: MainWindow, script: str) -> object:
    result: list[str] = []
    loop = QEventLoop()

    def finished(value: object) -> None:
        result.append(str(value))
        loop.quit()

    window.page().runJavaScript(script, finished)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    assert len(result) == 1
    return json.loads(result[0])


def test_main_web_frontend_loads_offscreen() -> None:
    app, window = _load_window()
    _close_window(window)
    _ = app


def test_output_settings_module_executes_in_real_webengine() -> None:
    app, window = _load_window()
    script = """
        (() => {
            applySettings({
                preprocessing_enabled: true,
                language: 'ita',
                output_dir: '/tmp/glm-ocr-test',
                batch_auto_save: true,
                batch_output_format: 'md',
                batch_save_pdf_pages: true
            });
            return JSON.stringify([
                document.querySelector('#batch-auto-save-toggle').checked,
                document.querySelector('#batch-output-format').value,
                document.querySelector('#batch-pdf-pages-toggle').checked,
                document.querySelector('#batch-output-format').disabled,
                document.querySelector('#save-single-pages-txt-button') !== null
            ]);
        })();
    """

    assert _run_json_script(window, script) == [True, "md", True, False, True]
    _close_window(window)
    _ = app


def test_model_memory_module_executes_in_real_webengine() -> None:
    app, window = _load_window()
    script = """
        (() => {
            state.devices = [{available: true, device_name: 'SYCL'}];
            state.modelReady = false;
            state.operation = 'idle';
            state.singlePath = '/tmp/scan.png';
            state.batchPaths = ['/tmp/scan.png'];
            applySettings({
                preprocessing_enabled: true,
                language: 'ita+eng',
                output_dir: '/tmp/glm-ocr-test',
                load_model_at_startup: false,
                model_auto_unload_minutes: 30
            });
            updateBackendPanel();
            updateOperationUi();
            return JSON.stringify([
                document.querySelector('#load-model-startup-toggle').checked,
                document.querySelector('#model-auto-unload-select').value,
                document.querySelector('#model-unload-button').disabled,
                document.querySelector('#model-reload-button').textContent,
                document.querySelector('#single-start-button').disabled,
                document.querySelector('#batch-start-button').disabled,
                document.querySelector('#backend-chip').textContent,
                document.querySelector('#sidebar-status-text').textContent
            ]);
        })();
    """

    assert _run_json_script(window, script) == [
        False,
        "30",
        True,
        "Carica modello",
        False,
        False,
        "Scaricato",
        "Modello scaricato",
    ]
    _close_window(window)
    _ = app


def test_batch_items_can_be_removed_only_before_start() -> None:
    app, window = _load_window()
    script = """
        (() => {
            state.modelReady = true;
            state.operation = 'idle';
            state.batchPaths = ['/tmp/one.png', '/tmp/two.pdf'];
            state.batchStates = new Map(state.batchPaths.map((path) => [path, 'In coda']));
            state.batchResults = new Map([
                ['/tmp/one.png', {ok: true, text: 'old'}]
            ]);
            renderBatchFiles();
            renderBatchResults();
            updateOperationUi();

            const before = document.querySelectorAll('.batch-remove-button').length;
            document.querySelector('.batch-remove-button').click();
            const afterRemoval = [
                [...state.batchPaths],
                state.batchStates.has('/tmp/one.png'),
                state.batchResults.has('/tmp/one.png'),
                document.querySelector('#batch-count-label').textContent,
                document.querySelector('#batch-start-button').disabled,
                document.querySelectorAll('.batch-remove-button').length
            ];

            state.operation = 'batch';
            updateOperationUi();
            const remove = document.querySelector('.batch-remove-button');
            const disabledDuringBatch = remove.disabled;
            remove.click();

            return JSON.stringify([
                before,
                afterRemoval,
                disabledDuringBatch,
                [...state.batchPaths]
            ]);
        })();
    """

    assert _run_json_script(window, script) == [
        2,
        [["/tmp/two.pdf"], False, False, "1 file selezionato", False, 1],
        True,
        ["/tmp/two.pdf"],
    ]
    _close_window(window)
    _ = app


def test_safe_controls_remain_available_during_model_load() -> None:
    script = (ROOT / "ui" / "web" / "app.js").read_text(encoding="utf-8")
    assert '$("#single-file-button").disabled = busy' in script
    assert '$("#batch-file-button").disabled = busy' in script
    assert '$("#global-cancel-button").classList.toggle("hidden", !busy' in script
    update_operation = script.split("function updateOperationUi()", 1)[1].split(
        "function setModelStatus", 1
    )[0]
    assert 'op === "model_loading"' not in update_operation
