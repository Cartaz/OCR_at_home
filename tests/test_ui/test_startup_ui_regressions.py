from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web"


def test_main_uses_consolidated_non_blocking_web_bridge() -> None:
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from ui.app_web_bridge import AppWebBridge" in text
    assert "bridge = AppWebBridge(" in text
    assert 'channel.registerObject("backend", bridge)' in text
    assert "ResponsiveWebBridge" not in text
    assert "settings_ui.js" not in text
    assert "runJavaScript" not in text
    assert 'logger.info("GLM OCR UI pronta")' in text


def test_initial_bootstrap_never_probes_hardware_on_gui_thread() -> None:
    text = (ROOT / "ui" / "web_bridge.py").read_text(encoding="utf-8")
    assert "def _bootstrap_payload" in text
    assert '"devices": list(self._devices_snapshot)' in text
    bootstrap = text.split("def _bootstrap_payload", 1)[1].split(
        "@Slot(result=str)", 1
    )[0]
    assert "_device_dicts" not in bootstrap
    assert 'name="backend-init-worker"' in text
    assert "self._controller.initialize()" in text


def test_language_selector_is_native_html_and_confidence_control_is_removed() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "settings.css").read_text(encoding="utf-8")

    assert '<select id="language-input" name="language"' in html
    assert '<option value="ita">Italiano</option>' in html
    assert '<option value="eng">English</option>' in html
    assert '<option value="ita+eng">Italiano + English</option>' in html
    assert 'href="settings.css"' in html
    assert "Soglia confidenza" not in html
    assert "confidence-input" not in html
    assert "confidence-output" not in html
    assert "confidence_threshold" not in js
    assert "confidence-input" not in js
    assert "confidence-output" not in js
    assert "ensureLanguageOption" in js
    assert "rgb(20, 20, 20)" in css
    assert "rgb(255, 102, 0)" in css
    assert not (WEB / "settings_ui.js").exists()


def test_single_result_and_pdf_page_save_controls_use_real_backend_actions() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    save_js = (WEB / "save_ui.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "app_web_bridge.py").read_text(encoding="utf-8")

    assert 'src="save_ui.js"' in html
    assert 'id="save-single-txt-button"' in html
    assert 'id="save-single-md-button"' in html
    assert 'id="save-single-pages-txt-button"' in html
    assert 'id="save-single-pages-md-button"' in html
    assert "saveSingleResult" in save_js
    assert "saveSinglePdfPages" in save_js
    assert "completedSourcePath" in save_js
    assert "def saveSingleResult" in bridge
    assert "def saveSinglePdfPages" in bridge
    assert "write_ocr_text" in bridge
    assert "write_ocr_pages" in bridge


def test_batch_autosave_controls_are_native_and_persistent() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    save_js = (WEB / "save_ui.js").read_text(encoding="utf-8")
    settings = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "app_web_bridge.py").read_text(encoding="utf-8")

    assert 'id="batch-auto-save-toggle"' in html
    assert 'id="batch-output-format"' in html
    assert 'id="batch-pdf-pages-toggle"' in html
    assert "batch_auto_save" in settings
    assert "batch_output_format" in settings
    assert "batch_save_pdf_pages" in settings
    assert "payload.batch_auto_save" in save_js
    assert "payload.batch_output_format" in save_js
    assert "payload.batch_save_pdf_pages" in save_js
    assert "_snapshot_batch_output" in bridge
    assert "batch_output_summary" in bridge
