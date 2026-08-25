"""Real Qt WebEngine coverage for clipboard paste routing."""

from tests.test_ui.test_webengine_smoke import (
    _close_window,
    _load_window,
    _run_json_script,
)


def test_clipboard_paste_routes_through_local_input_selection() -> None:
    app, window = _load_window()

    dispatched = _run_json_script(
        window,
        """
        (() => {
            state.operation = 'idle';
            state.modelReady = true;
            state.devices = [{available: true, device_name: 'SYCL'}];
            state.backend = {
                pasteClipboardImage(callback) {
                    window.__pasteCalls = (window.__pasteCalls || 0) + 1;
                    callback(JSON.stringify({
                        ok: true,
                        path: '/tmp/clipboard-001.png',
                        name: 'Immagine dagli appunti.png'
                    }));
                }
            };
            updateOperationUi();
            setView('ocr');
            const event = new Event('paste', {bubbles: true, cancelable: true});
            document.body.dispatchEvent(event);
            return JSON.stringify([event.defaultPrevented, window.__pasteCalls || 0]);
        })();
        """,
    )
    assert dispatched == [True, 1]

    applied = _run_json_script(
        window,
        """
        (() => JSON.stringify([
            state.activeView,
            state.singlePath,
            document.querySelector('#single-file-name').textContent,
            document.querySelector('#single-file-display').getAttribute('aria-keyshortcuts'),
            document.querySelector('#single-file-display').getAttribute('aria-description')
        ]))();
        """,
    )
    assert applied == [
        "ocr",
        "/tmp/clipboard-001.png",
        "Immagine dagli appunti.png",
        "Control+V",
        "Puoi trascinare un'immagine o un PDF nella finestra oppure incollare un'immagine con Ctrl+V.",
    ]

    _close_window(window)
    _ = app


def test_clipboard_paste_does_not_override_text_field_paste() -> None:
    app, window = _load_window()

    result = _run_json_script(
        window,
        """
        (() => {
            state.operation = 'idle';
            state.backend = {
                pasteClipboardImage(callback) {
                    window.__textPasteCalls = (window.__textPasteCalls || 0) + 1;
                    callback(JSON.stringify({ok: false, error: 'should not run'}));
                }
            };
            setView('settings');
            const input = document.querySelector('#output-dir-input');
            const event = new Event('paste', {bubbles: true, cancelable: true});
            input.dispatchEvent(event);
            return JSON.stringify([
                event.defaultPrevented,
                window.__textPasteCalls || 0
            ]);
        })();
        """,
    )

    assert result == [False, 0]
    _close_window(window)
    _ = app
