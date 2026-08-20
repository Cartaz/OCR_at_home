# ui/widgets/batch_tab_helpers.py
"""Funzioni di supporto per la scheda Batch OCR.

Contiene il builder della griglia azioni, il builder della barra di
stato e gli stili di supporto per la scheda Batch. La mappatura stati
→ indicatore è condivisa con la scheda OCR tramite
``ui.widgets._status_helpers.status_to_indicator_state``.

Functions:
    build_actions_grid: Crea la griglia dei pulsanti d'azione.
    build_status_bar: Crea la barra di stato.
    file_label_style: Stile per l'etichetta file.
    error_status_style: Stile per i messaggi di errore.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from config.theme import ThemeColors
from ui.widgets.action_button import ActionButton
from ui.widgets.status_indicator import StatusIndicator


def build_actions_grid() -> tuple:
    """Crea la griglia dei pulsanti per la scheda Batch.

    Returns:
        Tupla (grid, batch_btn, clear_btn, save_btn, stop_btn).
    """
    from PySide6.QtWidgets import QGridLayout

    grid = QGridLayout()
    grid.setSpacing(8)

    batch_btn = ActionButton("Avvia Batch", "Ctrl+B")
    clear_btn = ActionButton("Cancella", "Ctrl+L")
    save_btn = ActionButton("Salva Testo", "Ctrl+Shift+S")
    stop_btn = ActionButton("Ferma", "Ctrl+S", is_danger=True)

    grid.addWidget(batch_btn, 0, 0)
    grid.addWidget(stop_btn, 0, 1)
    grid.addWidget(clear_btn, 1, 0)
    grid.addWidget(save_btn, 1, 1)

    for col in range(2):
        grid.setColumnStretch(col, 1)

    stop_btn.setEnabled(False)
    return grid, batch_btn, clear_btn, save_btn, stop_btn


def build_status_bar() -> tuple:
    """Crea la barra di stato per il batch.

    Returns:
        Tupla (row_widget, indicator, status_label, progress_label, count_label).
    """
    row = QWidget()
    row.setObjectName("statusBar")
    hl = QHBoxLayout(row)
    hl.setContentsMargins(8, 2, 8, 2)
    hl.setSpacing(12)

    indicator = StatusIndicator()
    hl.addWidget(indicator)

    status_label = QLabel("Pronto")
    status_label.setStyleSheet(_STATUS_STYLE)
    hl.addWidget(status_label)

    hl.addStretch()

    progress_label = QLabel("")
    progress_label.setStyleSheet(_STATUS_STYLE)
    progress_label.setMinimumWidth(90)
    hl.addWidget(progress_label)

    count_label = QLabel("")
    count_label.setStyleSheet(_STATUS_STYLE)
    hl.addWidget(count_label)

    return row, indicator, status_label, progress_label, count_label


_STATUS_STYLE: str = (
    f"color: {ThemeColors.TEXT_SECONDARY}; "
    f"font-size: 12px; background: transparent;"
)


def file_label_style(has_file: bool = False) -> str:
    """Stile per l'etichetta del file selezionato.

    Args:
        has_file: True se un file è stato selezionato.

    Returns:
        Stringa CSS per l'etichetta.
    """
    color = ThemeColors.TEXT_PRIMARY if has_file else ThemeColors.TEXT_SECONDARY
    return f"color: {color}; font-size: 12px;"


def error_status_style() -> str:
    """Stile per i messaggi di errore nella barra di stato.

    Returns:
        Stringa CSS per il testo di errore.
    """
    return f"color: {ThemeColors.STATUS_ERROR}; font-size: 12px;"
