"""Offscreen smoke test for the local Qt WebEngine shell."""

from __future__ import annotations

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


def test_main_web_frontend_loads_offscreen() -> None:
    app, window = _load_window()
    _close_window(window)
    _ = app


def test_output_settings_module_executes_in_real_webengine() -> None:
    app, window = _load_window()
    result: list[object] = []
    loop = QEventLoop()
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
            return [
                document.querySelector('#batch-auto-save-toggle').checked,
                document.querySelector('#batch-output-format').value,
                document.querySelector('#batch-pdf-pages-toggle').checked,
                document.querySelector('#batch-output-format').disabled,
                document.querySelector('#save-single-pages-txt-button') !== null
            ];
        })();
    """

    def finished(value: object) -> None:
        result.append(value)
        loop.quit()

    window.page().runJavaScript(script, finished)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()

    assert result == [[True, "md", True, False, True]]
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
