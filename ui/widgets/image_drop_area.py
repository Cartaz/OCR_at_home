# ui/widgets/image_drop_area.py
"""Area di drag-and-drop per la selezione delle immagini.

Supporta il trascinamento di file immagine e il click per aprire
il dialogo di selezione file. Emette un segnale con i percorsi
delle immagini selezionate.

Classes:
    ImageDropArea: Area di drop per immagini.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QLabel, QWidget

from config.constants import AppMeta
from config.theme import ThemeColors


class ImageDropArea(QLabel):
    """Area drag-and-drop per la selezione di immagini.

    L'area mostra un testo placeholder e cambia aspetto durante
    il drag-over. Il click apre un dialogo di selezione file.

    Args:
        parent: Widget genitore.

    Signals:
        images_selected: Emesso quando l'utente seleziona immagini.
            Il payload è una lista di percorsi Path.
    """

    images_selected = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("Trascina qui le immagini\no clicca per sfogliare")
        self.setMinimumHeight(80)
        self.setStyleSheet(
            f"background-color: {ThemeColors.BG_SURFACE}; "
            f"color: {ThemeColors.TEXT_SECONDARY}; "
            f"border: 2px dashed {ThemeColors.BORDER}; "
            f"border-radius: 6px; padding: 16px; font-size: 12px;"
        )

    def dragEnterEvent(self, event) -> None:
        """Accetta il drag se contiene file con estensione supportata.

        Args:
            event: Evento di drag enter.
        """
        if hasattr(event, 'mimeData') and event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            has_valid = any(
                Path(url.toLocalFile()).suffix.lower()
                in AppMeta.SUPPORTED_IMAGE_EXTENSIONS
                for url in urls
            )
            if has_valid:
                event.acceptProposedAction()
                self.setStyleSheet(
                    f"background-color: {ThemeColors.BG_SURFACE_ALT}; "
                    f"color: {ThemeColors.PRIMARY}; "
                    f"border: 2px dashed {ThemeColors.PRIMARY}; "
                    f"border-radius: 6px; padding: 16px; font-size: 12px;"
                )

    def dragLeaveEvent(self, event) -> None:
        """Ripristina lo stile normale quando il drag esce.

        Args:
            event: Evento di drag leave.
        """
        self.setStyleSheet(
            f"background-color: {ThemeColors.BG_SURFACE}; "
            f"color: {ThemeColors.TEXT_SECONDARY}; "
            f"border: 2px dashed {ThemeColors.BORDER}; "
            f"border-radius: 6px; padding: 16px; font-size: 12px;"
        )

    def dropEvent(self, event) -> None:
        """Processa i file rilasciati ed emette il segnale.

        Args:
            event: Evento di drop.
        """
        paths: list[Path] = []
        if hasattr(event, 'mimeData'):
            for url in event.mimeData().urls():
                p = Path(url.toLocalFile())
                if p.suffix.lower() in AppMeta.SUPPORTED_IMAGE_EXTENSIONS:
                    paths.append(p)
        if paths:
            self.images_selected.emit(paths)
        self.dragLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        """Apre il dialogo di selezione file al click.

        Args:
            event: Evento del mouse.
        """
        extensions = " ".join(
            f"*{ext}" for ext in sorted(AppMeta.SUPPORTED_IMAGE_EXTENSIONS)
        )
        filter_str = f"Immagini ({extensions})"
        files, _ = QFileDialog.getOpenFileNames(
            self, "Seleziona immagini", "", filter_str
        )
        if files:
            self.images_selected.emit([Path(f) for f in files])
