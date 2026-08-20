# ui/widgets/ocr_tab.py
"""Scheda OCR — riconoscimento ottico su singola immagine.

Contiene l'interfaccia per la configurazione e il controllo
dell'OCR su singola immagine, con pannello configurazione,
azioni, area di testo e barra di stato.

Classes:
    OCRTab: Scheda per l'OCR su singola immagine.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from config.constants import AppMeta
from config.theme import ThemeColors
from core.app_controller import AppController
from core.models import StatusEnum
from ui.styles.components import status_label
from ui.widgets.card import Card
from ui.widgets.config_panel import ConfigPanel
from ui.widgets.ocr_tab_helpers import (
    build_actions_grid,
    build_status_bar,
    stat_label_style,
    status_to_indicator_state,
)
from ui.widgets.status_indicator import StatusIndicator

logger = logging.getLogger(__name__)


class OCRTab(QWidget):
    """Scheda per l'OCR su singola immagine.

    Args:
        controller: Controller principale dell'applicazione.
        parent: Widget genitore.
    """

    def __init__(
        self, controller: AppController, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._image_path: Path | None = None
        self._full_text: str = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Costruisce il layout completo della scheda OCR."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._add_config_card(layout)
        self._add_actions_card(layout)
        self._add_text_area(layout)
        self._add_status_bar(layout)

    def _add_config_card(self, layout: QVBoxLayout) -> None:
        """Aggiunge la card di configurazione."""
        card = Card("CONFIGURAZIONE OCR", self)
        content = card.content_layout()
        self._config_panel = ConfigPanel(
            self._controller.settings, self)
        # Aggiorna dispositivi
        devices = self._controller.get_available_devices()
        self._config_panel.update_devices(devices)
        # Collega il cambio dispositivo al controller per ricaricare il modello
        self._config_panel.device_changed.connect(self._on_device_changed)
        content.addWidget(self._config_panel)

        # Riga file
        file_row = QHBoxLayout()
        self._file_label = QLabel("Nessun file selezionato")
        self._file_label.setStyleSheet(
            f"color: {ThemeColors.TEXT_SECONDARY}; font-size: 12px;")
        file_row.addWidget(self._file_label, 1)
        self._browse_btn = QPushButton("Sfoglia...")
        self._browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(self._browse_btn)
        content.addLayout(file_row)

        layout.addWidget(card)

    def _add_actions_card(self, layout: QVBoxLayout) -> None:
        """Aggiunge la card delle azioni."""
        card = Card("AZIONI", self)
        content = card.content_layout()
        (grid, self._start_btn, self._stop_btn,
         self._refresh_btn, self._clear_btn,
         self._save_btn) = build_actions_grid()
        content.addLayout(grid)
        layout.addWidget(card)

        self._start_btn.action_requested.connect(self._on_start)
        self._stop_btn.action_requested.connect(self._on_stop)
        self._refresh_btn.action_requested.connect(self._on_refresh)
        self._clear_btn.action_requested.connect(self._on_clear)
        self._save_btn.action_requested.connect(self._on_save)

    def _add_text_area(self, layout: QVBoxLayout) -> None:
        """Aggiunge l'area di testo."""
        self._text_area = QTextEdit()
        self._text_area.setObjectName("transcriptionArea")
        self._text_area.setReadOnly(True)
        self._text_area.setPlaceholderText(
            "Seleziona un'immagine o un PDF e clicca 'Avvia OCR'...\n\n"
            "Supporta PNG, JPG, BMP, TIFF, WEBP, PDF.")
        self._text_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._text_area)

    def _add_status_bar(self, layout: QVBoxLayout) -> None:
        """Aggiunge la barra di stato."""
        (row, self._indicator, self._status_label,
         self._progress_label) = build_status_bar()
        layout.addWidget(row)

    # ── Azioni ───────────────────────────────────────────────────

    @Slot(str)
    def _on_device_changed(self, device: str) -> None:
        """Gestisce il cambio di dispositivo di inferenza.

        Ricarica il modello sul nuovo dispositivo tramite il controller.

        Args:
            device: Tipo di dispositivo selezionato (GPU/NPU/CPU).
        """
        current_device = self._controller.engine.device
        if device == current_device and self._controller.engine.is_initialized:
            return  # Nessun cambio necessario
        logger.info("Cambio dispositivo: %s → %s", current_device, device)
        self.update_status(StatusEnum.LOADING_MODEL.value)
        self._controller.switch_device(device)

    def _on_browse(self) -> None:
        """Apre il dialogo di selezione file."""
        extensions = " ".join(
            f"*{ext}" for ext in sorted(AppMeta.SUPPORTED_IMAGE_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleziona immagine", "", f"Immagini ({extensions})")
        if path:
            self._image_path = Path(path)
            self._file_label.setText(self._image_path.name)
            self._file_label.setToolTip(str(self._image_path))
            self._file_label.setStyleSheet(
                f"color: {ThemeColors.TEXT_PRIMARY}; font-size: 12px;")

    def _on_start(self) -> None:
        """Avvia l'OCR sull'immagine selezionata in modo asincrono."""
        if not self._image_path or not self._image_path.exists():
            QMessageBox.information(
                self, "Nessun file", "Seleziona un'immagine prima di avviare.")
            return
        self._text_area.clear()
        self._full_text = ""
        # Aggiorna impostazioni non legate al device (il cambio device
        # viene gestito da _on_device_changed che invoca switch_device).
        self._controller.update_settings(
            language=self._config_panel.language,
            preprocessing_enabled=self._config_panel.preprocessing_enabled,
        )
        # Assicurati che il modello sia caricato
        if not self._controller.engine.is_initialized:
            # Il caricamento avverrà via EventBridge; l'OCR partirà
            # automaticamente in on_model_loaded()
            self.update_status(StatusEnum.LOADING_MODEL.value)
            return
        # Avvia OCR asincrono — risultati via EventBridge signals
        self.enable_running_state()
        self.update_status(StatusEnum.PROCESSING.value)
        try:
            self._controller.start_ocr(self._image_path)
        except Exception as exc:
            self.show_error(str(exc))
            self.enable_idle_state()

    def _on_stop(self) -> None:
        """Ferma l'operazione in corso."""
        self.update_status(StatusEnum.STOPPED.value)

    def _on_refresh(self) -> None:
        """Aggiorna la lista dei dispositivi."""
        devices = self._controller.get_available_devices()
        self._config_panel.update_devices(devices)

    def _on_clear(self) -> None:
        """Cancella il testo."""
        self._text_area.clear()
        self._full_text = ""

    def _on_save(self) -> None:
        """Salva il testo OCR su file."""
        if not self._full_text.strip():
            QMessageBox.information(
                self, "Nessun testo", "Non c'è testo da salvare.")
            return
        default_name = (self._image_path.stem + ".txt") \
            if self._image_path else "ocr_output.txt"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Salva testo OCR", default_name, "File di testo (*.txt)")
        if save_path:
            try:
                Path(save_path).write_text(self._full_text, encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(
                    self, "Errore salvataggio",
                    f"Impossibile salvare:\n{exc}")

    # ── Slot per EventBridge ─────────────────────────────────────

    @Slot(str)
    def append_text(self, text: str) -> None:
        """Aggiunge testo all'area dei risultati.

        Args:
            text: Testo da aggiungere.
        """
        cursor = self._text_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text + "\n")
        self._text_area.setTextCursor(cursor)
        self._text_area.ensureCursorVisible()
        self._full_text += text + "\n"

    @Slot()
    def enable_running_state(self) -> None:
        """Abilita lo stato UI di esecuzione."""
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._browse_btn.setEnabled(False)
        self._config_panel.set_enabled(False)
        self._refresh_btn.setEnabled(False)

    @Slot()
    def enable_idle_state(self) -> None:
        """Abilita lo stato UI di riposo."""
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._browse_btn.setEnabled(True)
        self._config_panel.set_enabled(True)
        self._refresh_btn.setEnabled(True)
        self.update_status(StatusEnum.STOPPED.value)
        # Pulisci l'etichetta di progresso pagine al termine
        self._progress_label.setText("")

    @Slot(str)
    def update_status(self, status: str) -> None:
        """Aggiorna l'indicatore e l'etichetta di stato.

        Args:
            status: Nome dello stato.
        """
        self._indicator.set_state(status_to_indicator_state(status))
        self._status_label.setText(status_label(status))
        self._status_label.setStyleSheet(stat_label_style())

    @Slot(str)
    def show_error(self, message: str) -> None:
        """Mostra un errore nella barra di stato.

        Args:
            message: Messaggio di errore.
        """
        self._status_label.setText(f"Errore: {message}")
        self._status_label.setStyleSheet(
            f"color: {ThemeColors.STATUS_ERROR};")
        self._indicator.set_state(StatusIndicator.State.ERROR)

    @Slot(str)
    def show_progress_message(self, message: str) -> None:
        """Mostra un messaggio informativo nella barra di stato.

        Usato in particolare per i messaggi di progresso del
        caricamento modello (es. "Scaricamento GLM-OCR-Q8_0.gguf...").

        Args:
            message: Messaggio di progresso da mostrare.
        """
        self._status_label.setText(message)
        self._status_label.setStyleSheet(stat_label_style())

    @Slot(str)
    def update_page_progress(self, progress_text: str) -> None:
        """Aggiorna l'etichetta di progresso pagine PDF.

        Mostra il contatore "Pagina X/Y" nella barra di stato
        durante l'elaborazione di PDF multi-pagina.

        Args:
            progress_text: Testo del progresso (es. "Pagina 5/400").
        """
        self._progress_label.setText(progress_text)

    @Slot()
    def on_model_loaded(self) -> None:
        """Chiamato quando il modello è stato caricato."""
        self.update_status(StatusEnum.IDLE.value)
        # Se c'era un'immagine selezionata, avvia OCR asincrono
        if self._image_path and self._image_path.exists():
            self.enable_running_state()
            self.update_status(StatusEnum.PROCESSING.value)
            try:
                self._controller.start_ocr(self._image_path)
            except Exception as exc:
                self.show_error(str(exc))
                self.enable_idle_state()
