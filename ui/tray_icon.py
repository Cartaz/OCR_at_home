"""Minimal native system tray integration for the desktop shell."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon(QObject):
    show_window_requested = Signal()
    cancel_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon_path: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        icon = QIcon(icon_path) if icon_path else QIcon()
        self._tray = QSystemTrayIcon(icon, parent)
        self._tray.setToolTip("GLM OCR")

        menu = QMenu()
        show_action = QAction("Mostra GLM OCR", menu)
        cancel_action = QAction("Annulla operazione", menu)
        quit_action = QAction("Esci", menu)
        show_action.triggered.connect(self.show_window_requested.emit)
        cancel_action.triggered.connect(self.cancel_requested.emit)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(show_action)
        menu.addAction(cancel_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._menu = menu

        self._tray.activated.connect(self._on_activated)

    @property
    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        if self.available:
            self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window_requested.emit()
