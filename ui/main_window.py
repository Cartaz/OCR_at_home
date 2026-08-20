# ui/main_window.py
"""Finestra principale di GLM OCR con schede OCR e Batch.

Hub UI centrale con QTabWidget che ospita la scheda OCR per il
riconoscimento su singola immagine e la scheda Batch per
l'elaborazione multipla. Comunica con core tramite AppController
ed EventBridge.

Classes:
    MainWindow: Finestra principale dell'applicazione.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Slot
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget,
)

from core.app_controller import AppController
from core.models import StatusEnum
from ui.event_bridge import EventBridge
from ui.styles import build_stylesheet
from ui.tray_icon import TrayIcon
from ui.widgets.batch_tab import BatchTab
from ui.widgets.ocr_tab import OCRTab

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Finestra principale dell'applicazione GLM OCR.

    Utilizza un QTabWidget con due schede:
      - OCR: riconoscimento ottico su singola immagine
      - Batch: elaborazione OCR su multiple immagini

    Args:
        controller: Controller principale dell'applicazione.
    """

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self._controller = controller
        self._tray_icon: TrayIcon | None = None

        self._setup_ui()
        self._connect_bridge()
        self.setStyleSheet(build_stylesheet())
        self.setWindowTitle("GLM OCR")
        self.resize(controller.settings.window_width,
                     controller.settings.window_height)

        # -- Scorciatoie da tastiera ------------------------------------
        self._quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self._quit_shortcut.activated.connect(self.force_quit)
        self._minimize_shortcut = QShortcut(QKeySequence("Ctrl+M"), self)
        self._minimize_shortcut.activated.connect(self._minimize_to_tray)

    # ==================================================================
    # Costruzione UI
    # ==================================================================

    def _setup_ui(self) -> None:
        """Costruisce il layout completo dell'interfaccia."""
        central = QWidget()
        central.setObjectName("centralContainer")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(8)

        self._add_title(root)
        self._add_tabs(root)

    def _add_title(self, layout: QVBoxLayout) -> None:
        """Aggiunge titolo e sottotitolo."""
        title = QLabel("GLM OCR")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        subtitle = QLabel(
            "Riconoscimento ottico con llama.cpp + SYCL")
        subtitle.setObjectName("subtitleLabel")
        layout.addWidget(subtitle)

    def _add_tabs(self, layout: QVBoxLayout) -> None:
        """Aggiunge il widget a schede con OCR e Batch."""
        self._tab_widget = QTabWidget()
        self._tab_widget.setObjectName("mainTabs")

        self._ocr_tab = OCRTab(self._controller, self)
        self._batch_tab = BatchTab(self._controller, self)

        self._tab_widget.addTab(self._ocr_tab, "OCR")
        self._tab_widget.addTab(self._batch_tab, "Batch")

        layout.addWidget(self._tab_widget)

    # ==================================================================
    # EventBridge — Thread-safe UI updates
    # ==================================================================

    def _connect_bridge(self) -> None:
        """Collega l'EventBridge ai componenti UI di ciascuna scheda."""
        self._bridge = EventBridge(self._controller)

        # -- Segnali OCR -----------------------------------------------
        self._bridge.ocr_new_text.connect(self._ocr_tab.append_text)
        self._bridge.ocr_status_changed.connect(self._ocr_tab.update_status)
        self._bridge.ocr_error.connect(self._ocr_tab.show_error)
        self._bridge.ocr_completed.connect(self._ocr_tab.enable_idle_state)

        # -- Segnali Batch ---------------------------------------------
        self._bridge.batch_new_text.connect(self._batch_tab.append_text)
        self._bridge.batch_status_changed.connect(self._batch_tab.update_status)
        self._bridge.batch_progress.connect(self._batch_tab.update_progress)
        self._bridge.batch_error.connect(self._batch_tab.show_error)
        self._bridge.batch_completed.connect(self._batch_tab.on_completed)

        # -- Segnali Modello -------------------------------------------
        self._bridge.model_loading.connect(self._on_model_loading)
        self._bridge.model_loaded.connect(self._on_model_loaded)
        self._bridge.model_load_error.connect(self._on_model_load_error)
        self._bridge.model_load_progress.connect(self._on_model_load_progress)

        # -- Segnali PDF streaming ----------------------------------------
        self._bridge.ocr_page_progress.connect(self._ocr_tab.update_page_progress)

    def _on_model_loading(self, device: str) -> None:
        """Gestisce l'inizio del caricamento del modello.

        Aggiorna la UI e avvia il caricamento tramite il QThread
        dell'EventBridge (non tramite il thread del controller).

        Args:
            device: Dispositivo target del caricamento.
        """
        self._ocr_tab.update_status(StatusEnum.LOADING_MODEL.value)
        self._batch_tab.update_status(StatusEnum.LOADING_MODEL.value)
        # Avvia il caricamento del modello nel QThread dell'EventBridge
        self._bridge.start_model_loading(device)

    def _on_model_loaded(self, backend: str, device: str) -> None:
        """Gestisce il completamento del caricamento del modello.

        Args:
            backend: Backend utilizzato (llama-cpp / llama-cpp-sycl).
            device: Dispositivo di inferenza.
        """
        self._ocr_tab.on_model_loaded()
        self._batch_tab.update_status(StatusEnum.IDLE.value)
        logger.info("Modello caricato — backend: %s, device: %s", backend, device)

    def _on_model_load_error(self, error_msg: str) -> None:
        """Gestisce l'errore di caricamento del modello.

        Args:
            error_msg: Messaggio di errore.
        """
        self._ocr_tab.show_error(f"Caricamento modello: {error_msg}")
        self._batch_tab.show_error(f"Caricamento modello: {error_msg}")

    @Slot(str)
    def _on_model_load_progress(self, message: str) -> None:
        """Mostra i messaggi di progresso del caricamento modello.

        I messaggi vengono emessi da LlamaServerBackend (es.
        "Scaricamento GLM-OCR-Q8_0.gguf...") e mostrati nella barra
        di stato della scheda OCR.

        Args:
            message: Messaggio di progresso.
        """
        self._ocr_tab.show_progress_message(message)
        self._batch_tab.show_progress_message(message)

    # ==================================================================
    # API Pubblica (per TrayIcon e main.py)
    # ==================================================================

    def on_start(self) -> None:
        """Avvia l'OCR (chiamato dal tray)."""
        self._ocr_tab._on_start()

    def on_stop(self) -> None:
        """Ferma l'OCR (chiamato dal tray)."""
        self._ocr_tab._on_stop()

    @property
    def bridge(self) -> EventBridge:
        """Riferimento all'EventBridge."""
        return self._bridge

    # ==================================================================
    # Eventi finestra
    # ==================================================================

    def closeEvent(self, event: QCloseEvent) -> None:
        """Chiude l'applicazione quando l'utente preme X.

        Args:
            event: Evento di chiusura della finestra.
        """
        self._controller.shutdown()
        event.accept()

    def set_tray_icon(self, tray_icon: TrayIcon) -> None:
        """Imposta il riferimento al tray icon.

        Args:
            tray_icon: Istanza di TrayIcon.
        """
        self._tray_icon = tray_icon

    def force_quit(self) -> None:
        """Ferma i thread e chiude l'applicazione."""
        self._controller.shutdown()
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _minimize_to_tray(self) -> None:
        """Riduce la finestra a icona volante nel tray."""
        self.hide()
