# main.py
"""GLM OCR — entry point con frontend Qt Quick/QML."""

from __future__ import annotations

import atexit
import logging
import signal
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from config.constants import AppMeta
from config.settings import Settings
from config.theme import ThemeColors
from core.app_controller import AppController
from ui.qml_bridge import QmlBridge
from ui.tray_icon import TrayIcon


def setup_logging() -> None:
    AppMeta.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(AppMeta.LOG_PATH, encoding="utf-8"),
        ],
    )


def _kill_orphan_llama_server() -> None:
    try:
        subprocess.run(
            ["pkill", "llama-server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


_controller_ref: list[AppController | None] = [None]


def _signal_handler(signum: int, frame: object) -> None:
    logger = logging.getLogger("GLM OCR")
    logger.info("Segnale %s ricevuto, arresto in corso...", signum)

    if _controller_ref[0] is not None:
        try:
            _controller_ref[0].shutdown()
        except Exception:
            pass

    _kill_orphan_llama_server()
    sys.exit(0)


def _widget_aux_stylesheet() -> str:
    """Tema dei soli widget rimasti: tray menu e dialoghi non nativi."""
    return f"""
    QMenu {{
        background-color: #1A1A1A;
        color: {ThemeColors.TEXT_PRIMARY};
        border: 1px solid #292929;
        border-radius: 8px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 7px 24px;
        border-radius: 5px;
    }}
    QMenu::item:selected {{
        background-color: {ThemeColors.PRIMARY};
        color: {ThemeColors.TEXT_ON_ACCENT};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: #292929;
        margin: 5px 8px;
    }}
    QToolTip {{
        background-color: #1D1D1D;
        color: {ThemeColors.TEXT_PRIMARY};
        border: 1px solid #2A2A2A;
        padding: 4px 8px;
    }}
    """


def main() -> None:
    setup_logging()
    logger = logging.getLogger("GLM OCR")
    logger.info("Avvio GLM OCR (Qt Quick/QML)...")

    settings = Settings.load()
    logger.info(
        "Impostazioni caricate — device=%s, lang=%s",
        settings.default_device,
        settings.language,
    )

    QQuickStyle.setStyle("Basic")

    app = QApplication(sys.argv)
    app.setApplicationName(AppMeta.NAME)
    app.setApplicationDisplayName(AppMeta.NAME)
    app.setOrganizationName(AppMeta.ID)
    app.setQuitOnLastWindowClosed(True)
    app.setStyleSheet(_widget_aux_stylesheet())

    controller = AppController(settings=settings)
    _controller_ref[0] = controller

    atexit.register(_kill_orphan_llama_server)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    _sigint_timer = QTimer()
    _sigint_timer.timeout.connect(lambda: None)
    _sigint_timer.start(50)

    bridge = QmlBridge(controller)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", bridge)

    qml_path = Path(__file__).parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        logger.error("Impossibile caricare la UI QML: %s", qml_path)
        sys.exit(1)

    window = engine.rootObjects()[0]
    bridge.set_window(window)

    icon_path = Path(__file__).parent / "assets" / "icons" / "glm-ocr.svg"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)
        try:
            window.setIcon(icon)
        except (AttributeError, RuntimeError):
            pass

    tray = TrayIcon(
        parent=app,
        icon_path=str(icon_path) if icon_path.exists() else None,
    )
    tray.show()

    tray.show_window_requested.connect(bridge.showWindow)
    tray.connect_start_action(bridge.startOcr)
    tray.connect_stop_action(bridge.stopOcr)
    tray.quit_requested.connect(bridge.forceQuit)

    controller.initialize()

    logger.info("GLM OCR pronto")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
