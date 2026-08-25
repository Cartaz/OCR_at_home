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
            state.devices = [{available: true, device_name: 'SYCL'}];
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


def test_keyboard_shortcuts_delegate_to_existing_controls() -> None:
    app, window = _load_window()
    script = """
        (() => {
            const calls = [];
            state.backend = {
                chooseSingleFile: (callback) => {
                    calls.push('open');
                    callback(JSON.stringify({ok: true, cancelled: true}));
                },
                startSingleOcr: (path, callback) => {
                    calls.push(`ocr:${path}`);
                    callback(JSON.stringify({ok: true}));
                },
                startBatch: (paths, callback) => {
                    calls.push(`batch:${paths}`);
                    callback(JSON.stringify({ok: true}));
                },
                copyText: (text) => calls.push(`copy:${text}`)
            };
            state.devices = [{available: true, device_name: 'SYCL'}];
            state.modelReady = true;
            state.operation = 'idle';
            state.singlePath = '/tmp/scan.png';
            state.batchPaths = ['/tmp/one.png', '/tmp/two.pdf'];
            renderSingleText('recognized');
            renderBatchFiles();
            updateOperationUi();

            const dispatch = (key, options = {}) => {
                const event = new KeyboardEvent('keydown', {
                    key,
                    ctrlKey: true,
                    bubbles: true,
                    cancelable: true,
                    ...options
                });
                const accepted = document.dispatchEvent(event);
                return !accepted;
            };

            setView('ocr');
            const openPrevented = dispatch('o');
            const ocrPrevented = dispatch('Enter');
            const normalCopyPrevented = dispatch('c');
            const copyPrevented = dispatch('c', {shiftKey: true});
            setView('batch');
            const batchPrevented = dispatch('Enter');

            return JSON.stringify([
                calls,
                openPrevented,
                ocrPrevented,
                normalCopyPrevented,
                copyPrevented,
                batchPrevented,
                document.querySelector('#single-file-button').getAttribute('aria-keyshortcuts'),
                document.querySelector('#single-start-button').getAttribute('aria-keyshortcuts'),
                document.querySelector('#copy-single-button').getAttribute('aria-keyshortcuts')
            ]);
        })();
    """

    result = _run_json_script(window, script)
    assert result[0] == [
        "open",
        "ocr:/tmp/scan.png",
        "copy:recognized",
        'batch:["/tmp/one.png","/tmp/two.pdf"]',
    ]
    assert result[1:6] == [True, True, False, True, True]
    assert result[6:] == ["Control+O", "Control+Enter", "Control+Shift+C"]
    _close_window(window)
    _ = app


def test_accessible_error_loading_and_progress_states() -> None:
    app, window = _load_window()
    script = """
        (() => {
            const origin = document.querySelector('#single-file-button');
            origin.focus();
            showNotice('Errore', 'Operazione fallita', 'dettaglio', true);
            const urgent = [
                document.querySelector('#notice').getAttribute('role'),
                document.querySelector('#notice').getAttribute('aria-live'),
                document.activeElement.id
            ];
            hideNotice();
            const restoredFocus = document.activeElement.id;

            showNotice('Salvato', 'Operazione completata');
            const polite = [
                document.querySelector('#notice').getAttribute('role'),
                document.querySelector('#notice').getAttribute('aria-live'),
                document.activeElement.id
            ];
            hideNotice();

            state.operation = 'ocr';
            updateOperationUi();
            const ocrBusy = document.querySelector('#view-ocr').getAttribute('aria-busy');
            state.operation = 'batch';
            updateOperationUi();
            const batchBusy = document.querySelector('#view-batch').getAttribute('aria-busy');
            state.operation = 'model_loading';
            updateOperationUi();
            const settingsBusy = document.querySelector('#view-settings').getAttribute('aria-busy');
            state.operation = 'idle';
            updateOperationUi();

            setProgress('#single-progress', 40, '2 / 5');
            setProgress('#batch-progress', 50, '3 / 6');
            return JSON.stringify([
                urgent,
                restoredFocus,
                polite,
                ocrBusy,
                batchBusy,
                settingsBusy,
                document.querySelector('#single-progress').getAttribute('aria-valuetext'),
                document.querySelector('#batch-progress').getAttribute('aria-valuetext'),
                document.querySelector('#single-result-meta').getAttribute('aria-live'),
                document.querySelector('#batch-count-label').getAttribute('aria-live')
            ]);
        })();
    """

    assert _run_json_script(window, script) == [
        ["alert", "assertive", "notice"],
        "single-file-button",
        ["status", "polite", "single-file-button"],
        "true",
        "true",
        "true",
        "2 / 5",
        "3 / 6",
        "polite",
        "polite",
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
