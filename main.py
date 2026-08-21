"""GLM OCR desktop entry point using a local HTML/CSS/JavaScript frontend."""

from __future__ import annotations

import atexit
import logging
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import QApplication

from config.constants import AppMeta
from config.settings import Settings
from config.theme import ThemeColors
from core.app_controller import AppController
from ui.tray_icon import TrayIcon
from ui.web_bridge import WebBridge
from ui.window import MainWindow

_controller_ref: list[AppController | None] = [None]


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


def _shutdown_controller_ref() -> None:
    controller = _controller_ref[0]
    if controller is None:
        return
    try:
        controller.shutdown()
    except Exception:
        logging.getLogger("GLM OCR").exception("Errore durante lo shutdown")


def _signal_handler(signum: int, _frame: object) -> None:
    logger = logging.getLogger("GLM OCR")
    logger.info("Segnale %s ricevuto, arresto in corso...", signum)
    app = QApplication.instance()
    if app is not None:
        app.quit()
    else:
        _shutdown_controller_ref()
        raise SystemExit(0)


def _native_aux_stylesheet() -> str:
    """Keep native tray menus/tooltips aligned with the single dark surface."""
    return f"""
    QMenu {{
        background: {ThemeColors.BG_MAIN};
        color: {ThemeColors.TEXT_PRIMARY};
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 10px;
        padding: 6px;
    }}
    QMenu::item {{
        background: {ThemeColors.BG_MAIN};
        padding: 8px 24px;
        border-radius: 7px;
    }}
    QMenu::item:selected {{
        background: {ThemeColors.BG_MAIN};
        color: {ThemeColors.PRIMARY};
    }}
    QMenu::separator {{
        height: 1px;
        background: rgba(255, 255, 255, 0.05);
        margin: 5px 8px;
    }}
    QToolTip {{
        background: {ThemeColors.BG_MAIN};
        color: {ThemeColors.TEXT_PRIMARY};
        border: 1px solid rgba(255, 102, 0, 0.55);
        padding: 5px 8px;
    }}
    """


def main() -> None:
    setup_logging()
    logger = logging.getLogger("GLM OCR")
    logger.info("Avvio GLM OCR (Qt WebEngine)...")

    settings = Settings.load()
    app = QApplication(sys.argv)
    app.setApplicationName(AppMeta.NAME)
    app.setApplicationDisplayName(AppMeta.NAME)
    app.setOrganizationName(AppMeta.ID)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(_native_aux_stylesheet())

    controller = AppController(settings=settings)
    _controller_ref[0] = controller
    atexit.register(_shutdown_controller_ref)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    sigint_timer = QTimer()
    sigint_timer.timeout.connect(lambda: None)
    sigint_timer.start(50)

    web_root = Path(__file__).parent / "ui" / "web"
    index_path = web_root / "index.html"
    if not index_path.is_file():
        logger.error("Frontend HTML mancante: %s", index_path)
        raise SystemExit(1)

    window = MainWindow(web_root)
    window.setWindowTitle(AppMeta.NAME)
    window.resize(settings.window_width, settings.window_height)
    window.setMinimumSize(420, 480)

    icon_path = Path(__file__).parent / "assets" / "icons" / "glm-ocr.svg"
    if icon_path.is_file():
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)
        window.setWindowIcon(icon)

    bridge = WebBridge(controller, window=window, parent=window)
    channel = QWebChannel(window.page())
    channel.registerObject("backend", bridge)
    window.page().setWebChannel(channel)

    tray = TrayIcon(
        icon_path=str(icon_path) if icon_path.is_file() else None,
        parent=app,
    )
    if tray.available:
        tray.show()
        tray.show_window_requested.connect(bridge.showWindow)
        tray.cancel_requested.connect(bridge.cancelOperation)
        tray.quit_requested.connect(bridge.forceQuit)

    # Closing the main window means closing the application. The tray remains
    # useful while the app is open but never keeps llama-server resident after
    # the window has been closed.
    app.setQuitOnLastWindowClosed(True)

    app.aboutToQuit.connect(tray.hide)
    app.aboutToQuit.connect(bridge.shutdown)
    ui_ready_logged = False

    def on_load_finished(ok: bool) -> None:
        nonlocal ui_ready_logged
        if not ok:
            logger.error("Impossibile caricare il frontend HTML: %s", index_path)
            return
        if not ui_ready_logged:
            logger.info("GLM OCR UI pronta")
            ui_ready_logged = True

    window.loadFinished.connect(on_load_finished)
    window.show()

    exit_code = 1
    try:
        exit_code = app.exec()
    finally:
        # Defensive second line of cleanup: shutdown is idempotent, and this
        # also covers event-loop exits that bypass a normal aboutToQuit path.
        bridge.shutdown()
        tray.hide()
        _shutdown_controller_ref()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
