from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_main_uses_consolidated_non_blocking_web_bridge() -> None:
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from ui.web_bridge import WebBridge" in text
    assert "ResponsiveWebBridge" not in text
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


def test_language_is_presented_as_dropdown_and_unused_confidence_is_hidden() -> None:
    text = (ROOT / "ui" / "web" / "settings_ui.js").read_text(encoding="utf-8")
    assert 'document.createElement("select")' in text
    assert '["ita", "Italiano"]' in text
    assert '["eng", "English"]' in text
    assert '["ita+eng", "Italiano + English"]' in text
    assert "confidenceField.hidden = true" in text
    assert "rgb(20, 20, 20)" in text
    assert "rgb(255, 102, 0)" in text
