"""GLM OCR desktop entry point (Qt Quick interface)."""

from __future__ import annotations

import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from config.constants import AppMeta
from config.settings import Settings
from config.theme import ThemeColors
from core.app_controller import AppController
from ui.backend import UiBackend
from ui.tray_icon import TrayIcon
from ui.window import QmlMainWindow

ICON_PATH = Path(__file__).parent / "assets" / "icons" / "glm-ocr.svg"


def setup_logging() -> None:
    AppMeta.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(
                AppMeta.LOG_PATH,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            ),
        ],
    )


def _native_aux_stylesheet() -> str:
    """Keep the native tray menu and tooltips aligned with the dark surface."""
    return f"""
    QMenu {{
        background: {ThemeColors.BG_MAIN};
        color: {ThemeColors.TEXT_PRIMARY};
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 10px;
        padding: 6px;
    }}
    QMenu::item {{ padding: 8px 24px; border-radius: 7px; }}
    QMenu::item:selected {{ color: {ThemeColors.PRIMARY}; }}
    QMenu::separator {{ height: 1px; background: rgba(255, 255, 255, 0.05); margin: 5px 8px; }}
    QToolTip {{
        background: {ThemeColors.BG_MAIN};
        color: {ThemeColors.TEXT_PRIMARY};
        border: 1px solid rgba(255, 102, 0, 0.55);
        padding: 5px 8px;
    }}
    """


def main() -> int:
    setup_logging()
    logger = logging.getLogger("GLM OCR")
    logger.info("Avvio %s %s (Qt Quick)...", AppMeta.NAME, AppMeta.VERSION)

    settings = Settings.load()
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv)
    app.setApplicationName(AppMeta.NAME)
    app.setApplicationDisplayName(AppMeta.NAME)
    app.setApplicationVersion(AppMeta.VERSION)
    app.setOrganizationName(AppMeta.ID)
    app.setDesktopFileName(AppMeta.ID)
    app.setStyleSheet(_native_aux_stylesheet())
    font = QFont()
    font.setFamilies(["Inter", "sans-serif"])
    font.setPixelSize(14)
    app.setFont(font)
    if ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    # Python runs signal handlers only when the interpreter gets control: a
    # cheap timer wakes it while the Qt event loop is idle.
    def request_quit(signum: int, _frame: object) -> None:
        logger.info("Segnale %s ricevuto, arresto in corso...", signum)
        # Queued: also honoured when the signal arrives before app.exec().
        QTimer.singleShot(0, app.quit)

    for handled in (signal.SIGINT, signal.SIGTERM):
        signal.signal(handled, request_quit)
    signal_wakeup = QTimer()
    signal_wakeup.timeout.connect(lambda: None)
    signal_wakeup.start(200)

    controller = AppController(settings=settings)
    backend = UiBackend(controller)
    window: QmlMainWindow | None = None
    tray: TrayIcon | None = None
    try:
        window = QmlMainWindow(backend, icon_path=ICON_PATH)
        tray = TrayIcon(icon_path=str(ICON_PATH) if ICON_PATH.is_file() else None, parent=app)
        if tray.available:
            tray.show_window_requested.connect(window.restore)
            tray.cancel_requested.connect(backend.cancelOperation)
            tray.quit_requested.connect(app.quit)
            tray.show()
        window.show()
        logger.info("GLM OCR UI pronta")
        backend.initialize()
        return app.exec()
    finally:
        # QML first (bindings), then the adapter and the controller-owned
        # llama-server. Each step is idempotent.
        if tray is not None:
            tray.hide()
        if window is not None:
            window.shutdown()
        backend.shutdown()


if __name__ == "__main__":
    sys.exit(main())
