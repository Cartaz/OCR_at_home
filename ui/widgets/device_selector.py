# ui/widgets/device_selector.py
"""Selettore dispositivo di inferenza OCR.

Combo box con etichetta per selezionare il dispositivo di calcolo
tra quelli rilevati dal sistema. Include llama.cpp (GGUF) come
opzione primaria raccomandata.

Classes:
    DeviceSelector: Selettore dispositivo con segnale device_changed.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from config.theme import ThemeColors
from core.models import HardwareInfo


class DeviceSelector(QWidget):
    """Combo box per la selezione del dispositivo di inferenza.

    Mostra tutti i dispositivi rilevati dal sistema, con llama.cpp
    come opzione raccomandata. I dispositivi non disponibili sono
    mostrati con una nota.

    Args:
        parent: Widget genitore.

    Signals:
        device_changed: Emesso quando l'utente seleziona un dispositivo.
            Il payload è il tipo di dispositivo (str).
    """

    device_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel("Dispositivo:")
        label.setStyleSheet(
            f"color: {ThemeColors.TEXT_SECONDARY}; font-size: 12px;"
        )
        layout.addWidget(label)

        self._combo = QComboBox()
        self._combo.currentIndexChanged.connect(self._on_selection_changed)
        layout.addWidget(self._combo, 1)

        self._devices: list[HardwareInfo] = []

    def _on_selection_changed(self, index: int) -> None:
        """Emette il segnale quando cambia la selezione.

        Args:
            index: Indice della selezione corrente.
        """
        if 0 <= index < len(self._devices):
            self.device_changed.emit(self._devices[index].device_type)

    def update_devices(self, devices: list[HardwareInfo]) -> None:
        """Aggiorna la lista dei dispositivi disponibili.

        Mostra tutti i dispositivi, con nota per quelli non disponibili.
        llama.cpp viene mostrato per primo se disponibile.

        Args:
            devices: Lista delle informazioni hardware rilevate.
        """
        self._combo.blockSignals(True)
        self._combo.clear()
        self._devices = list(devices)

        # Ordina: llama-cpp-sycl prima, poi llama-cpp, poi gli altri
        sorted_devices = sorted(
            self._devices,
            key=lambda d: (
                0 if d.device_type == "llama-cpp-sycl" else
                1 if d.device_type == "llama-cpp" else
                2 if d.device_type == "GPU" else
                3 if d.device_type == "NPU" else
                4
            ),
        )
        self._devices = sorted_devices

        for dev in self._devices:
            label = dev.device_name
            if not dev.available:
                label += " (non pronto)"
            self._combo.addItem(label)

        # Seleziona il primo dispositivo disponibile
        for i, dev in enumerate(self._devices):
            if dev.available:
                self._combo.setCurrentIndex(i)
                break

        self._combo.blockSignals(False)
        if self._devices:
            self._on_selection_changed(self._combo.currentIndex())

    @property
    def current_device(self) -> str:
        """Tipo di dispositivo attualmente selezionato.

        Returns:
            Tipo di dispositivo (llama-cpp/GPU/NPU/CPU).
        """
        idx = self._combo.currentIndex()
        if 0 <= idx < len(self._devices):
            return self._devices[idx].device_type
        return "llama-cpp-sycl"
