"""Desktop window hosting the local HTML frontend."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


class MainWindow(QWebEngineView):
    """QWebEngine shell whose close button performs a real window close."""

    def __init__(self, web_root: Path, parent=None) -> None:
        super().__init__(parent)

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
