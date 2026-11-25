"""Qt Quick shell: owns the QML engine, window geometry and teardown order."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer, QUrl
from PySide6.QtGui import QIcon, QWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from shiboken6 import delete

from config.constants import AppMeta, UIConstraints
from ui.backend import UiBackend

QML_ROOT = Path(__file__).resolve().parent / "qml"
SHADER_PACKAGE = QML_ROOT / "shaders" / "neumorphic.frag.qsb"


class QmlMainWindow(QObject):
    """Load ``Main.qml`` with ``backend`` and persist the window size."""

    def __init__(self, backend: UiBackend, *, icon_path: Path | None = None) -> None:
        super().__init__()
        if not SHADER_PACKAGE.is_file():
            raise RuntimeError(f"Shader QML mancante: {SHADER_PACKAGE}")
        self._backend = backend
        self._shutdown = False
        self._engine = QQmlApplicationEngine(self)
        self._engine.rootContext().setContextProperty("backend", backend)
        self._engine.load(QUrl.fromLocalFile(str(QML_ROOT / "Main.qml")))
        roots = self._engine.rootObjects()
        if not roots or not isinstance(roots[0], QQuickWindow):
            raise RuntimeError("Main.qml non ha creato una finestra Qt Quick valida")
        self._window: QQuickWindow = roots[0]
        self._window.setTitle(AppMeta.NAME)
        self._window.setMinimumWidth(UIConstraints.WINDOW_MIN_WIDTH)
        self._window.setMinimumHeight(UIConstraints.WINDOW_MIN_HEIGHT)
        settings = backend.settings
        self._window.resize(int(settings["window_width"]), int(settings["window_height"]))
        if icon_path is not None and icon_path.is_file():
            self._window.setIcon(QIcon(str(icon_path)))

        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(600)
        self._geometry_timer.timeout.connect(self._persist_geometry)
        self._window.installEventFilter(self)

    @property
    def window(self) -> QQuickWindow:
        return self._window

    def show(self) -> None:
        self._window.show()

    def restore(self) -> None:
        self._window.showNormal()
        self._window.raise_()
        self._window.requestActivate()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if watched is self._window and event.type() == QEvent.Type.Resize:
            self._geometry_timer.start()
        return super().eventFilter(watched, event)

    def _persist_geometry(self) -> None:
        if self._shutdown:
            return
        if self._window.visibility() != QWindow.Visibility.Windowed:
            return  # never store a maximized/fullscreen size as the normal size
        width, height = self._window.width(), self._window.height()
        settings = self._backend.settings
        if (width, height) != (settings["window_width"], settings["window_height"]):
            self._backend.saveWindowSize(width, height)

    def shutdown(self) -> None:
        """Destroy QML before the backend so no binding outlives its adapter."""
        if self._shutdown:
            return
        self._geometry_timer.stop()
        self._persist_geometry()
        self._shutdown = True
        self._window.removeEventFilter(self)
        self._window.hide()
        delete(self._window)
        delete(self._engine)
