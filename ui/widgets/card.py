# ui/widgets/card.py
"""Card con intestazione in maiuscoletto per il raggruppamento di azioni.

Ogni card ha sfondo BG_CARD, bordo 1px BORDER, border-radius 6px,
padding interno 16px e margine esterno 8px. L'intestazione usa
small caps con letter-spacing 0.5px.

Classes:
    Card: Widget card con intestazione etichettata.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from config.theme import ThemeColors
from config.constants import UIConstraints


class Card(QWidget):
    """Card con intestazione in maiuscoletto per raggruppamento azioni.

    La card racchiude widget figli in un contenitore visivamente
    distinto con sfondo, bordo e intestazione formattata.

    Args:
        title: Testo dell'intestazione della card.
        parent: Widget genitore.
    """

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        """Inizializza la card con il titolo dato.

        Args:
            title: Testo dell'intestazione.
            parent: Widget genitore.
        """
        super().__init__(parent)
        self._setup_ui(title)

    def _setup_ui(self, title: str) -> None:
        """Configura il layout e lo stile della card.

        Args:
            title: Testo dell'intestazione.
        """
        padding = UIConstraints.CARD_PADDING
        margin = UIConstraints.CARD_MARGIN

        # Lo stile della Card è definito nel foglio di stile globale
        # (breeze_dark.py) tramite il selettore QWidget#cardWidget.
        # Questo evita che il QWidget {} locale si propaghi ai figli
        # causando clipping sui border-radius.
        self.setObjectName("cardWidget")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(margin, margin, margin, margin)

        inner = QVBoxLayout()
        inner.setContentsMargins(padding, padding, padding, padding)
        inner.setSpacing(8)

        header = QLabel(title)
        header.setFont(QFont(ThemeColors.FONT_FAMILY, 13, QFont.Weight.Medium))
        header.setStyleSheet(
            f"color: {ThemeColors.TEXT_SECONDARY}; "
            f"font-variant: small-caps; "
            f"letter-spacing: 0.5px; "
            f"border: none; "
            f"background: transparent; "
            f"padding: 0; "
            f"margin: 0 0 0 0;"
        )
        inner.addWidget(header)

        self._content_layout = QVBoxLayout()
        self._content_layout.setSpacing(8)
        inner.addLayout(self._content_layout)

        outer.addLayout(inner)

    def content_layout(self) -> QVBoxLayout:
        """Restituisce il layout di contenuto per aggiungere widget.

        Returns:
            Il QVBoxLayout interno in cui inserire i widget figli.
        """
        return self._content_layout
