"""Desktop window hosting the local HTML frontend."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


class LocalOnlyPage(QWebEnginePage):
    """Keep application navigation local and delegate web links to the OS."""

    _LOCAL_SCHEMES = {"file", "qrc", "about"}

    def acceptNavigationRequest(
        self,
        url: QUrl,
        navigation_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        _ = navigation_type, is_main_frame
        scheme = url.scheme().lower()
        if scheme in self._LOCAL_SCHEMES:
            return True
        if scheme in {"http", "https"}:
            QDesktopServices.openUrl(url)
        return False


class MainWindow(QWebEngineView):
    """QWebEngine shell restricted to the bundled local frontend."""

    def __init__(self, web_root: Path, parent=None) -> None:
        super().__init__(parent)
        self.setPage(LocalOnlyPage(self))

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
