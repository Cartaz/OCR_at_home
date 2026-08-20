# ui/widgets/config_panel.py
"""Pannello di configurazione per l'OCR.

Contiene i controlli per la lingua, il dispositivo di inferenza
e le opzioni di pre-elaborazione delle immagini.

Classes:
    ConfigPanel: Pannello di configurazione OCR.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QVBoxLayout, QWidget,
)

from config.settings import Settings
from core.models import HardwareInfo
from ui.widgets.device_selector import DeviceSelector


# Mappa lingua → etichetta localizzata
LANG_MAP: dict[str, str] = {
    "ita+eng": "Italiano + Inglese",
    "eng": "Inglese",
    "ita": "Italiano",
    "fra": "Francese",
    "deu": "Tedesco",
    "spa": "Spagnolo",
}


class ConfigPanel(QWidget):
    """Pannello di configurazione per i parametri OCR.

    Args:
        settings: Impostazioni correnti dell'applicazione.
        parent: Widget genitore.

    Signals:
        config_changed: Emesso quando qualsiasi parametro cambia.
        device_changed: Emesso quando il dispositivo di inferenza cambia.
            Il payload è il tipo di dispositivo (str, es. "GPU", "CPU").
    """

    config_changed = Signal()
    device_changed = Signal(str)

    def __init__(
        self, settings: Settings, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Costruisce il layout del pannello di configurazione."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Riga 1: Lingua + Pre-elaborazione
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        self._lang_combo = QComboBox()
        for code, label in LANG_MAP.items():
            self._lang_combo.addItem(label, code)
        # Seleziona la lingua corrente
        idx = list(LANG_MAP.keys()).index(self._settings.language) \
            if self._settings.language in LANG_MAP else 0
        self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self.config_changed.emit)
        row1.addWidget(self._lang_combo, 1)

        self._preprocess_check = QCheckBox("Pre-elaborazione")
        self._preprocess_check.setChecked(self._settings.preprocessing_enabled)
        self._preprocess_check.stateChanged.connect(self.config_changed.emit)
        row1.addWidget(self._preprocess_check)

        layout.addLayout(row1)

        # Riga 2: Dispositivo
        self._device_selector = DeviceSelector(self)
        # Propaga il cambio dispositivo come segnale del ConfigPanel
        self._device_selector.device_changed.connect(self.device_changed.emit)
        layout.addWidget(self._device_selector)

    @property
    def language(self) -> str:
        """Codice lingua selezionato.

        Returns:
            Codice lingua ISO (es. 'ita+eng').
        """
        return self._lang_combo.currentData() or "ita+eng"

    @property
    def device(self) -> str:
        """Tipo di dispositivo selezionato.

        Returns:
            Tipo di dispositivo (GPU/NPU/CPU).
        """
        return self._device_selector.current_device

    @property
    def preprocessing_enabled(self) -> bool:
        """Indica se la pre-elaborazione è attiva.

        Returns:
            True se la pre-elaborazione è abilitata.
        """
        return self._preprocess_check.isChecked()

    def update_devices(self, devices: list[HardwareInfo]) -> None:
        """Aggiorna la lista dei dispositivi disponibili.

        Args:
            devices: Lista delle informazioni hardware.
        """
        self._device_selector.update_devices(devices)

    def set_enabled(self, enabled: bool) -> None:
        """Abilita o disabilita tutti i controlli del pannello.

        Args:
            enabled: True per abilitare, False per disabilitare.
        """
        self._lang_combo.setEnabled(enabled)
        self._preprocess_check.setEnabled(enabled)
        self._device_selector.setEnabled(enabled)
