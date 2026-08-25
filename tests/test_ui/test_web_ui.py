"""Static regressions for the HTML/CSS/JS presentation layer."""

from pathlib import Path

ROOT = Path(__file__).parents[2]
WEB = ROOT / "ui" / "web"


def test_web_frontend_uses_required_neumorphic_tokens() -> None:
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    lowered = css.lower()
    assert "--surface: rgb(20, 20, 20);" in css
    assert "--accent: rgb(255, 102, 0);" in css
    assert "--shadow-raised:" in css
    assert "--shadow-inset:" in css
    assert "--shadow-active-inset-glow:" in css
    assert "prefers-reduced-motion" in css
    assert "linear-gradient" not in lowered
    assert "radial-gradient" not in lowered
    assert "#181818" not in lowered
    assert "#1a1a1a" not in lowered
    assert "#202020" not in lowered
    assert "#242424" not in lowered


def test_web_frontend_is_native_and_semantic() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    lowered = html.lower()
    assert 'qrc:///qtwebchannel/qwebchannel.js' in html
    assert '<nav' in lowered
    assert '<main' in lowered
    assert '<section' in lowered
    assert '<button' in lowered
    assert '<label' in lowered
    assert 'react' not in lowered
    assert 'vue' not in lowered
    assert 'bootstrap' not in lowered
    assert 'tailwind' not in lowered


def test_javascript_calls_real_backend_actions() -> None:
    js = (WEB / "app.js").read_text(encoding="utf-8")
    for method in (
        "bootstrap",
        "initializeBackend",
        "chooseSingleFile",
        "startSingleOcr",
        "chooseBatchFiles",
        "startBatch",
        "cancelOperation",
        "updateSettings",
        "getLogs",
    ):
        assert method in js
    assert "mock" not in js.lower()


def test_single_save_does_not_roundtrip_ocr_text_to_python() -> None:
    js = (WEB / "save_ui.js").read_text(encoding="utf-8")
    save_call = js.split('"saveSingleResult"', 1)[1].split(");", 1)[0]
    assert "completedSourcePath" in save_call
    assert "format" in save_call
    assert "state.singleText" not in save_call
    assert "resultSourcePath" not in js


def test_main_uses_webengine_not_qml() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "QWebChannel" in source
    assert "MainWindow" in source
    assert "QQmlApplicationEngine" not in source
    assert "Main.qml" not in source


def test_package_recipe_no_longer_requires_removed_qml_tree() -> None:
    source = (ROOT / "PKGBUILD").read_text(encoding="utf-8")
    assert '"$srcdir/$pkgname/ui"' in source
    assert '"$srcdir/$pkgname/qml"' not in source