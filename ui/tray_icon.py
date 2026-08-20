# ui/tray_icon.py
"""Icona nel system tray con menu contestuale.

Fornisce un QSystemTrayIcon con menu per mostrare/nascondere la
finestra, avviare/fermare l'OCR e chiudere l'applicazione.
L'icona viene caricata dal file PNG specificato o dal tema di sistema.

Poiché QSystemTrayIcon non supporta l'aggiunta di Signal personalizzati
tramite ereditarietà, usiamo un oggetto SignalHelper interno che
espone i signal richiesti dal main.py.

Classes:
    TrayIcon: Icona nel system tray con menu contestuale.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from config.theme import ThemeColors

logger = logging.getLogger(__name__)


class _SignalHelper(QObject):
    """Helper per esporre Signal personalizzati dal TrayIcon.

    Necessario perché QSystemTrayIcon non permette di definire
    Signal nelle sottoclassi a causa delle metaclasse Qt.

    Signals:
        show_window_requested: Emesso quando l'utente vuole mostrare la finestra.
        quit_requested: Emesso quando l'utente vuole chiudere l'applicazione.
    """

    show_window_requested = Signal()
    quit_requested = Signal()


class TrayIcon(QSystemTrayIcon):
    """Icona nel system tray con menu contestuale.

    Offre un menu con azioni per mostrare la finestra principale,
    avviare/fermare l'OCR e chiudere l'applicazione.
    Supporta sia il caricamento da file PNG/SVG che dal tema di sistema.

    I signal personalizzati sono accessibili tramite l'attributo
    ``signals`` (istanza di _SignalHelper). Per comodità, gli
    attributi show_window_requested e quit_requested sono inoltrati
    direttamente sull'oggetto TrayIcon.

    Args:
        parent: Widget genitore (tipicamente QApplication).
        icon_path: Percorso del file icona (PNG o SVG), o None per icona di default.

    Example::

        tray = TrayIcon(parent=app, icon_path="/path/to/icon.png")
        tray.show_window_requested.connect(window.show)
        tray.quit_requested.connect(window.force_quit)
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        icon_path: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self._icon_path = icon_path
        self._start_action: Optional[QAction] = None
        self._stop_action: Optional[QAction] = None
        self._sig = _SignalHelper()

        # Inoltra i signal sull'oggetto TrayIcon per uso diretto
        self.show_window_requested = self._sig.show_window_requested
        self.quit_requested = self._sig.quit_requested

        self._set_icon()
        self._build_menu()

    # -- Icona ----------------------------------------------------------

    def _set_icon(self) -> None:
        """Imposta l'icona del tray dal file o dal tema di sistema."""
        icon = self._load_icon()
        self.setIcon(icon)

        if not self.isSystemTrayAvailable():
            logger.warning("System tray non disponibile")

    def _load_icon(self) -> QIcon:
        """Carica l'icona dal percorso specificato o dal tema di sistema.

        Tenta il caricamento nell'ordine:
          1. File PNG/SVG specificato
          2. Icona dal tema di sistema "com.glm-ocr.app"
          3. Icona dal tema di sistema "glm-ocr"
          4. Icona generata come fallback

        Returns:
            QIcon da utilizzare per il tray.
        """
        # 1. Prova il file specificato
        if self._icon_path:
            icon = QIcon(self._icon_path)
            if not icon.isNull():
                logger.info("Icona tray caricata da: %s", self._icon_path)
                return icon
            logger.warning("File icona non valido: %s", self._icon_path)

        # 2. Prova dal tema di sistema (ID desktop)
        icon = QIcon.fromTheme("com.glm-ocr.app")
        if not icon.isNull():
            logger.info("Icona tray caricata dal tema di sistema (com.glm-ocr.app)")
            return icon

        # 3. Prova dal tema di sistema (nome generico)
        icon = QIcon.fromTheme("glm-ocr")
        if not icon.isNull():
            logger.info("Icona tray caricata dal tema di sistema (glm-ocr)")
            return icon

        # 4. Fallback: icona generata (pallino teal)
        logger.info("Uso icona generata come fallback per il tray")
        return self._create_fallback_icon()

    @staticmethod
    def _create_fallback_icon() -> QIcon:
        """Crea un'icona di fallback come pallino teal.

        Returns:
            QIcon con un pallino teal 32x32.
        """
        from PySide6.QtGui import QPainter, QColor, QBrush, Qt

        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(ThemeColors.PRIMARY)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 28, 28)
        painter.end()
        return QIcon(pixmap)

    # -- Menu contestuale -----------------------------------------------

    def _build_menu(self) -> None:
        """Costruisce il menu contestuale del tray icon."""
        menu = QMenu()

        show_action = QAction("Mostra finestra", self)
        show_action.triggered.connect(self._on_show_window)
        menu.addAction(show_action)

        menu.addSeparator()

        self._start_action = QAction("Avvia OCR", self)
        menu.addAction(self._start_action)

        self._stop_action = QAction("Ferma OCR", self)
        menu.addAction(self._stop_action)

        menu.addSeparator()

        quit_action = QAction("Esci", self)
        quit_action.triggered.connect(self._on_quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

        # Doppio click mostra la finestra
        self.activated.connect(self._on_activated)

    # -- API Pubblica ---------------------------------------------------

    def is_visible(self) -> bool:
        """Verifica se l'icona tray è visibile.

        Returns:
            True se l'icona tray è visibile nel system tray.
        """
        return self.isVisible()

    def connect_start_action(self, handler: Callable) -> None:
        """Collega un handler all'azione "Avvia OCR".

        Args:
            handler: Funzione callback da invocare.
        """
        if self._start_action:
            self._start_action.triggered.connect(handler)

    def connect_stop_action(self, handler: Callable) -> None:
        """Collega un handler all'azione "Ferma OCR".

        Args:
            handler: Funzione callback da invocare.
        """
        if self._stop_action:
            self._stop_action.triggered.connect(handler)

    # -- Handler interni ------------------------------------------------

    def _on_show_window(self) -> None:
        """Emette il segnale show_window_requested."""
        self._sig.show_window_requested.emit()

    def _on_quit(self) -> None:
        """Emette il segnale quit_requested."""
        self._sig.quit_requested.emit()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Gestisce il doppio click sull'icona tray.

        Args:
            reason: Motivo dell'attivazione.
        """
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._sig.show_window_requested.emit()
