# ui/widgets/batch_tab.py
"""Scheda Batch — OCR su multiple immagini.

Supporta l'elaborazione batch di più immagini contemporaneamente,
con indicatore di progresso e salvataggio dei risultati.

Classes:
    BatchTab: Scheda per l'OCR batch.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QFileDialog, QMessageBox, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from config.theme import ThemeColors
from core.app_controller import AppController
from ui.styles.components import status_label as _status_label
from ui.widgets._status_helpers import status_to_indicator_state
from ui.widgets.batch_tab_helpers import (
    build_actions_grid,
    build_status_bar,
    error_status_style,
)
from ui.widgets.card import Card
from ui.widgets.image_drop_area import ImageDropArea

logger = logging.getLogger(__name__)


class BatchTab(QWidget):
    """Scheda per l'OCR batch su multiple immagini.

    Args:
        controller: Controller principale dell'applicazione.
        parent: Widget genitore.
    """

    def __init__(
        self, controller: AppController, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._image_paths: list[Path] = []
        self._full_text: str = ""
        self._completed_count: int = 0
        self._total_count: int = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Costruisce il layout completo della scheda Batch."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._add_config_card(layout)
        self._add_actions_card(layout)
        self._add_text_area(layout)
        self._add_status_bar(layout)

    def _add_config_card(self, layout: QVBoxLayout) -> None:
        """Aggiunge la card di configurazione."""
        card = Card("CONFIGURAZIONE BATCH", self)
        content = card.content_layout()

        # Area di drop
        self._drop_area = ImageDropArea(self)
        self._drop_area.images_selected.connect(self._on_images_selected)
        content.addWidget(self._drop_area)

        layout.addWidget(card)

    def _add_actions_card(self, layout: QVBoxLayout) -> None:
        """Aggiunge la card delle azioni."""
        card = Card("AZIONI", self)
        content = card.content_layout()
        (grid, self._batch_btn, self._clear_btn,
         self._save_btn, self._stop_btn) = build_actions_grid()
        content.addLayout(grid)
        layout.addWidget(card)

        self._batch_btn.action_requested.connect(self._on_batch)
        self._stop_btn.action_requested.connect(self._on_stop)
        self._clear_btn.action_requested.connect(self._on_clear)
        self._save_btn.action_requested.connect(self._on_save)

    def _add_text_area(self, layout: QVBoxLayout) -> None:
        """Aggiunge l'area di testo."""
        self._text_area = QTextEdit()
        self._text_area.setObjectName("fileTranscriptionArea")
        self._text_area.setReadOnly(True)
        self._text_area.setPlaceholderText(
            "Trascina le immagini qui sopra o clicca per sfogliare...\n\n"
            "Il testo estratto apparirà in quest'area.")
        self._text_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._text_area)

    def _add_status_bar(self, layout: QVBoxLayout) -> None:
        """Aggiunge la barra di stato."""
        (row, self._indicator, self._status_label,
         self._progress_label, self._count_label) = build_status_bar()
        layout.addWidget(row)

    # ── Azioni ───────────────────────────────────────────────────

    def _on_images_selected(self, paths: list[Path]) -> None:
        """Gestisce la selezione di immagini.

        Args:
            paths: Lista dei percorsi delle immagini selezionate.
        """
        self._image_paths = paths
        count = len(paths)
        self._drop_area.setText(
            f"{count} immagin{'i' if count > 1 else 'e'} "
            f"selezionat{'e' if count > 1 else 'a'}")

    def _on_batch(self) -> None:
        """Avvia l'elaborazione batch.

        Se il modello non è ancora inizializzato, mostra un messaggio
        e attende il completamento del caricamento prima di avviare
        il batch (l'EventBridge notificherà quando pronto).
        """
        if not self._image_paths:
            QMessageBox.information(
                self, "Nessuna immagine",
                "Seleziona almeno un'immagine prima di avviare.")
            return
        if not self._controller.engine.is_initialized:
            QMessageBox.information(
                self, "Modello non pronto",
                "Attendi il caricamento del modello prima di avviare il batch.")
            return
        self._text_area.clear()
        self._full_text = ""
        self._completed_count = 0
        self._total_count = len(self._image_paths)
        self._count_label.setText(f"0/{self._total_count}")

        try:
            self._controller.run_batch(self._image_paths)
        except Exception as exc:
            self.show_error(str(exc))
            return
        self._apply_state(running=True)

    def _on_stop(self) -> None:
        """Ferma il batch in corso annullando il job attivo."""
        self._controller.cancel_active_batch()
        self._apply_state(running=False)

    def _on_clear(self) -> None:
        """Cancella il testo e azzera i contatori."""
        self._text_area.clear()
        self._full_text = ""
        self._completed_count = 0
        self._progress_label.setText("")
        self._count_label.setText("")

    def _on_save(self) -> None:
        """Salva il testo su file."""
        if not self._full_text.strip():
            QMessageBox.information(
                self, "Nessun testo", "Non c'è testo da salvare.")
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Salva testo batch", "batch_ocr.txt",
            "File di testo (*.txt)")
        if save_path:
            try:
                Path(save_path).write_text(
                    self._full_text, encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(
                    self, "Errore salvataggio",
                    f"Impossibile salvare:\n{exc}")

    # ── Slot per EventBridge ─────────────────────────────────────

    @Slot(str)
    def append_text(self, text: str) -> None:
        """Aggiunge testo all'area dei risultati.

        Args:
            text: Testo OCR estratto.
        """
        self._completed_count += 1
        cursor = self._text_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text + "\n")
        self._text_area.setTextCursor(cursor)
        self._text_area.ensureCursorVisible()
        self._full_text += text + "\n"
        self._count_label.setText(
            f"{self._completed_count}/{self._total_count}")

    @Slot(str)
    def update_status(self, status: str) -> None:
        """Aggiorna lo stato della scheda.

        Args:
            status: Nome dello stato.
        """
        self._indicator.set_state(status_to_indicator_state(status))
        self._status_label.setText(_status_label(status))
        if status == "completed":
            self._apply_state(running=False, completed=True)

    @Slot(int)
    def update_progress(self, percent: int) -> None:
        """Aggiorna la progressione.

        Args:
            percent: Percentuale di avanzamento (0-100).
        """
        self._progress_label.setText(f"{percent}/100")

    @Slot(str)
    def show_error(self, message: str) -> None:
        """Mostra un errore nella barra di stato.

        Args:
            message: Messaggio di errore.
        """
        self._status_label.setText(f"Errore: {message}")
        self._status_label.setStyleSheet(error_status_style())

    @Slot(str)
    def show_progress_message(self, message: str) -> None:
        """Mostra un messaggio informativo nella barra di stato.

        Usato per i messaggi di progresso del caricamento modello.

        Args:
            message: Messaggio di progresso da mostrare.
        """
        self._status_label.setText(message)
        self._status_label.setStyleSheet(error_status_style().replace(
            ThemeColors.STATUS_ERROR, ThemeColors.TEXT_SECONDARY))

    @Slot()
    def on_completed(self) -> None:
        """Segnala il completamento del batch."""
        self._apply_state(running=False, completed=True)

    # ── Stato interno ────────────────────────────────────────────

    def _apply_state(
        self, running: bool = False, completed: bool = False,
    ) -> None:
        """Aggiorna lo stato dei controlli.

        Args:
            running: True se il batch è in esecuzione.
            completed: True se il batch è completato.
        """
        self._batch_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._save_btn.setEnabled(
            not running and bool(self._full_text.strip()))
        self._clear_btn.setEnabled(not running)
        if completed:
            self._progress_label.setText("100/100")
