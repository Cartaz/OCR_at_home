"""Navigation-policy tests for the local-only Qt WebEngine page."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import QApplication

from ui.window import LocalOnlyPage


def _page() -> LocalOnlyPage:
    _app = QApplication.instance() or QApplication([])
    return LocalOnlyPage()


def test_local_navigation_is_allowed() -> None:
    page = _page()
    assert page.acceptNavigationRequest(
        QUrl("file:///tmp/index.html"),
        QWebEnginePage.NavigationType.NavigationTypeTyped,
        True,
    )
    assert page.acceptNavigationRequest(
        QUrl("qrc:///qtwebchannel/qwebchannel.js"),
        QWebEnginePage.NavigationType.NavigationTypeOther,
        True,
    )
    page.deleteLater()


def test_untrusted_non_web_schemes_are_rejected() -> None:
    page = _page()
    assert not page.acceptNavigationRequest(
        QUrl("javascript:alert(1)"),
        QWebEnginePage.NavigationType.NavigationTypeTyped,
        True,
    )
    assert not page.acceptNavigationRequest(
        QUrl("data:text/html,hello"),
        QWebEnginePage.NavigationType.NavigationTypeTyped,
        True,
    )
    page.deleteLater()
