"""Desktop window hosting the local HTML frontend."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QCloseEvent
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


class MainWindow(QWebEngineView):
    """QWebEngine shell with optional close-to-tray behavior."""

    def __init__(self, web_root: Path, parent=None) -> None:
        super().__init__(parent)
        self.allow_close = False
        self.hide_on_close = False

        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )

        self.page().setBackgroundColor(QColor("#141414"))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.load(QUrl.fromLocalFile(str((web_root / "index.html").resolve())))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if self.hide_on_close and not self.allow_close:
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)
