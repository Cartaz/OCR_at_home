# ui/widgets/ocr_tab_helpers.py
"""Funzioni di supporto per la scheda OCR.

Contiene la mappatura degli stati, il builder della griglia azioni,
il builder della barra di stato e gli stili di supporto.

Functions:
    build_actions_grid: Crea la griglia dei pulsanti d'azione.
    build_status_bar: Crea la barra di stato con indicatore.
    status_to_indicator_state: Mappa uno stato allo stato dell'indicatore.
    stat_label_style: Stile per le etichette della barra di stato.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from config.theme import ThemeColors
from ui.widgets._status_helpers import status_to_indicator_state
from ui.widgets.action_button import ActionButton
from ui.widgets.status_indicator import StatusIndicator

# Re-export per retrocompatibilità
__all__ = [
    "status_to_indicator_state",
    "build_actions_grid",
    "build_status_bar",
    "stat_label_style",
]


def build_actions_grid() -> tuple:
    """Crea la griglia dei pulsanti d'azione per la scheda OCR.

    Returns:
        Tupla (grid_layout, start_btn, stop_btn, refresh_btn, clear_btn, save_btn).
    """
    from PySide6.QtWidgets import QGridLayout

    grid = QGridLayout()
    grid.setSpacing(8)

    start_btn = ActionButton("Avvia OCR", "Ctrl+R")
    stop_btn = ActionButton("Ferma", "Ctrl+S", is_danger=True)
    refresh_btn = ActionButton("Aggiorna", "F5")
    clear_btn = ActionButton("Cancella", "Ctrl+L")
    save_btn = ActionButton("Salva Testo", "Ctrl+Shift+S")

    # Prima riga: 3 pulsanti
    grid.addWidget(start_btn, 0, 0)
    grid.addWidget(stop_btn, 0, 1)
    grid.addWidget(refresh_btn, 0, 2)

    # Seconda riga: 2 pulsanti centrati
    grid.addWidget(clear_btn, 1, 0)
    grid.addWidget(save_btn, 1, 1)

    for col in range(3):
        grid.setColumnStretch(col, 1)

    # Stato iniziale
    stop_btn.setEnabled(False)

    return grid, start_btn, stop_btn, refresh_btn, clear_btn, save_btn


def build_status_bar() -> tuple:
    """Crea la barra di stato con indicatore e etichette.

    Returns:
        Tupla (row_widget, indicator, status_label, progress_label).
    """
    row = QWidget()
    row.setObjectName("statusBar")
    hl = QHBoxLayout(row)
    hl.setContentsMargins(8, 2, 8, 2)
    hl.setSpacing(12)

    indicator = StatusIndicator()
    hl.addWidget(indicator)

    status_label = QLabel("Pronto")
    status_label.setStyleSheet(stat_label_style())
    hl.addWidget(status_label)

    hl.addStretch()

    progress_label = QLabel("")
    progress_label.setStyleSheet(stat_label_style())
    progress_label.setMinimumWidth(90)
    hl.addWidget(progress_label)

    return row, indicator, status_label, progress_label


def stat_label_style() -> str:
    """Stile per le etichette della barra di stato.

    Returns:
        Stringa CSS per le etichette di stato.
    """
    return (
        f"color: {ThemeColors.TEXT_SECONDARY}; "
        f"font-size: 12px; background: transparent;"
    )
