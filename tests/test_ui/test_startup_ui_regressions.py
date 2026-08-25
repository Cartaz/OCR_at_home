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


def test_initial_bootstrap_and_hardware_refresh_never_probe_on_gui_thread() -> None:
    bridge = (ROOT / "ui" / "web_bridge.py").read_text(encoding="utf-8")
    controller = (ROOT / "core" / "app_controller.py").read_text(encoding="utf-8")

    assert "def _bootstrap_payload" in bridge
    assert '"devices": list(self._devices_snapshot)' in bridge
    bootstrap = bridge.split("def _bootstrap_payload", 1)[1].split(
        "@Slot(result=str)", 1
    )[0]
    assert "get_available_devices" not in bootstrap
    assert "threading.Thread" not in bridge
    assert "_init_thread" not in bridge
    assert "self._controller.request_initialize()" in bridge
    assert "self._controller.request_hardware_refresh()" in bridge
    assert "get_available_devices(refresh=True)" not in bridge

    assert 'name="backend-init-worker"' in controller
    assert 'name="hardware-refresh-worker"' in controller
    assert "self._hardware_detector.detect(refresh=True)" in controller


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


def test_single_result_and_pdf_page_save_controls_delegate_to_core_output_workflow() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    save_js = (WEB / "save_ui.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "app_web_bridge.py").read_text(encoding="utf-8")
    controller = (ROOT / "core" / "app_controller.py").read_text(encoding="utf-8")
    output = (ROOT / "core" / "output_workflow.py").read_text(encoding="utf-8")
    event_bridge = (ROOT / "ui" / "event_bridge.py").read_text(encoding="utf-8")

    assert 'src="save_ui.js"' in html
    assert 'id="save-single-txt-button"' in html
    assert 'id="save-single-md-button"' in html
    assert 'id="save-single-pages-txt-button"' in html
    assert 'id="save-single-pages-md-button"' in html
    assert "saveSingleResult" in save_js
    assert "saveSinglePdfPages" in save_js
    assert "completedSourcePath" in save_js
    assert "single_output_saved" in save_js
    assert "single_output_save_failed" in save_js

    assert "def saveSingleResult" in bridge
    assert "def saveSinglePdfPages" in bridge
    assert "self._controller.request_save_single_result" in bridge
    assert "self._controller.request_save_single_pdf_pages" in bridge
    assert "self._controller.save_single_result(" not in bridge
    assert "self._controller.save_single_pdf_pages(" not in bridge
    assert "write_ocr_text" not in bridge
    assert "write_ocr_pages" not in bridge
    assert "threading" not in bridge

    assert "def save_single_result" in controller
    assert "def save_single_pdf_pages" in controller
    assert "def request_save_single_result" in controller
    assert "def request_save_single_pdf_pages" in controller
    assert "def request_save_single_result" in output
    assert "def request_save_single_pdf_pages" in output
    assert "manual-output-" in output
    assert "write_ocr_text" in output
    assert "write_ocr_pages" in output
    assert '"single_output_saved"' in event_bridge
    assert '"single_output_save_failed"' in event_bridge


def test_batch_autosave_controls_are_native_and_core_owned() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    save_js = (WEB / "save_ui.js").read_text(encoding="utf-8")
    settings = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "app_web_bridge.py").read_text(encoding="utf-8")
    output = (ROOT / "core" / "output_workflow.py").read_text(encoding="utf-8")
    event_bridge = (ROOT / "ui" / "event_bridge.py").read_text(encoding="utf-8")

    assert 'id="batch-auto-save-toggle"' in html
    assert 'id="batch-output-format"' in html
    assert 'id="batch-pdf-pages-toggle"' in html
    assert "batch_auto_save" in settings
    assert "batch_output_format" in settings
    assert "batch_save_pdf_pages" in settings
    assert "payload.batch_auto_save" in save_js
    assert "payload.batch_output_format" in save_js
    assert "payload.batch_save_pdf_pages" in save_js
    assert "_snapshot_batch_output" not in bridge
    assert "_batch_output_snapshot" not in bridge
    assert "BatchOutputOptions" in output
    assert "batch_output_summary" in output
    assert '"batch_output_summary"' in event_bridge


def test_frontend_modules_use_explicit_extensions_without_monkey_patching() -> None:
    app_js = (WEB / "app.js").read_text(encoding="utf-8")
    save_js = (WEB / "save_ui.js").read_text(encoding="utf-8")
    model_js = (WEB / "model_ui.js").read_text(encoding="utf-8")

    assert "function registerUiExtension" in app_js
    assert 'runExtensionHook("applySettings", settings)' in app_js
    assert 'runExtensionHook("collectSettings", payload)' in app_js
    assert 'runExtensionHook("onBackendEvent", type, payload)' in app_js
    assert 'notifyUiState("single_selection_changed"' in app_js

    for module in (save_js, model_js):
        assert "registerUiExtension({" in module
        assert "const baseApplySettings" not in module
        assert "const baseCallNative" not in module
        assert "const baseHandleEvent" not in module
        assert "applySettings = function" not in module
        assert "callNative = function" not in module
        assert "handleEvent = function" not in module
        assert "updateOperationUi = function" not in module
        assert "updateBackendPanel = function" not in module

    assert "MutationObserver" not in save_js