# ui/styles/breeze_dark.py
"""Foglio di stile QSS completo per il tema Breeze Dark.

Genera l'intero stylesheet dell'applicazione come stringa QSS,
referenziando esclusivamente i token semantici da config/theme.py.

Functions:
    build_stylesheet: Genera il foglio di stile QSS completo.
"""

from __future__ import annotations

from config.theme import ThemeColors


def build_stylesheet() -> str:
    """Genera il foglio di stile QSS completo per Breeze Dark.

    Tutti i colori, font e spaziature sono referenziati tramite
    i token semantici di ThemeColors.

    Returns:
        Stringa QSS completa per l'applicazione.
    """
    tc = ThemeColors
    ff = tc.FONT_FAMILY
    fs = tc.FONT_SIZE

    return f"""
    /* GLM OCR — Breeze Dark + Teal (token semantici) */
    QWidget {{
        font-family: "{ff}";
        font-size: {fs}px;
        color: {tc.TEXT_PRIMARY};
    }}
    QMainWindow {{
        background-color: {tc.BG_MAIN};
    }}
    #centralContainer {{
        background-color: {tc.BG_MAIN};
        border: none;
    }}

    /* ── Card ──────────────────────────────────────────────────────── */
    QWidget#cardWidget {{
        background-color: {tc.BG_CARD};
        border: 1px solid {tc.BORDER};
        border-radius: 6px;
    }}

    /* ── Schede (QTabWidget) ──────────────────────────────────────── */
    QTabWidget::pane {{
        border: 1px solid {tc.BORDER};
        border-radius: 6px;
        background-color: {tc.BG_CARD};
        padding: 4px;
    }}
    QTabBar::tab {{
        background-color: {tc.BG_SURFACE};
        color: {tc.TEXT_SECONDARY};
        border: 1px solid {tc.BORDER};
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        padding: 8px 24px;
        margin-right: 2px;
        min-width: 80px;
    }}
    QTabBar::tab:selected {{
        background-color: {tc.BG_CARD};
        color: {tc.PRIMARY};
        border-bottom: 2px solid {tc.PRIMARY};
        font-weight: bold;
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {tc.BG_SURFACE_ALT};
        color: {tc.TEXT_PRIMARY};
    }}

    /* ── Aree di testo ────────────────────────────────────────────── */
    QTextEdit#transcriptionArea,
    QTextEdit#fileTranscriptionArea {{
        background-color: {tc.BG_SURFACE};
        color: {tc.TEXT_PRIMARY};
        border: 1px solid {tc.BORDER};
        border-radius: 6px;
        padding: 12px;
        font-family: "{ff}";
        font-size: {fs + 1}px;
        selection-background-color: {tc.BG_SELECTION};
        selection-color: {tc.TEXT_ON_SELECTION};
    }}
    QTextEdit#transcriptionArea:focus,
    QTextEdit#fileTranscriptionArea:focus {{
        border: 1px solid {tc.BORDER_FOCUS};
    }}

    /* ── Barra di stato ───────────────────────────────────────────── */
    #statusBar {{
        background-color: {tc.BG_SURFACE};
        border-top: 1px solid {tc.BORDER};
        border-radius: 0;
        padding: 4px 8px;
        min-height: 28px;
    }}
    #statusBar QLabel {{
        color: {tc.TEXT_SECONDARY};
        font-size: {fs - 1}px;
        padding: 0;
        background: transparent;
    }}

    /* ── Pulsanti ─────────────────────────────────────────────────── */
    QPushButton {{
        background-color: {tc.BG_SURFACE_ALT};
        color: {tc.TEXT_PRIMARY};
        border: 1px solid {tc.BORDER};
        border-radius: 5px;
        padding: 7px 16px;
        min-height: 22px;
    }}
    QPushButton:hover {{
        background-color: {tc.BG_HOVER};
        border-color: {tc.PRIMARY_DARK};
    }}
    QPushButton:pressed {{
        background-color: {tc.PRIMARY_DARK};
        color: {tc.TEXT_ON_ACCENT};
    }}
    QPushButton:disabled {{
        background-color: {tc.BG_SURFACE};
        color: {tc.TEXT_DISABLED};
        border-color: {tc.BORDER};
    }}

    /* ── ComboBox ─────────────────────────────────────────────────── */
    QComboBox {{
        background-color: {tc.BG_SURFACE_ALT};
        color: {tc.TEXT_PRIMARY};
        border: 1px solid {tc.BORDER};
        border-radius: 4px;
        padding: 5px 10px;
        min-height: 20px;
    }}
    QComboBox:hover {{
        border-color: {tc.PRIMARY_DARK};
    }}
    QComboBox::drop-down {{
        border: none;
        padding-right: 8px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid {tc.TEXT_SECONDARY};
        margin-right: 6px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {tc.BG_SURFACE_ALT};
        color: {tc.TEXT_PRIMARY};
        border: 1px solid {tc.BORDER};
        border-radius: 4px;
        selection-background-color: {tc.BG_SELECTION};
        selection-color: {tc.TEXT_ON_SELECTION};
        outline: none;
    }}

    /* ── CheckBox ──────────────────────────────────────────────────── */
    QCheckBox {{
        color: {tc.TEXT_PRIMARY};
        spacing: 6px;
        min-height: 20px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {tc.BORDER};
        border-radius: 3px;
        background-color: {tc.BG_SURFACE_ALT};
    }}
    QCheckBox::indicator:checked {{
        background-color: {tc.PRIMARY};
        border-color: {tc.PRIMARY};
    }}
    QCheckBox::indicator:hover {{
        border-color: {tc.PRIMARY_DARK};
    }}

    /* ── Label ─────────────────────────────────────────────────────── */
    QLabel {{
        background: transparent;
        color: {tc.TEXT_PRIMARY};
    }}
    QLabel#titleLabel {{
        font-size: {fs + 4}px;
        font-weight: bold;
        color: {tc.PRIMARY};
        padding: 4px 0;
    }}
    QLabel#subtitleLabel {{
        font-size: {fs - 1}px;
        color: {tc.TEXT_SECONDARY};
        padding: 0 0 8px 0;
    }}

    /* ── ProgressBar ───────────────────────────────────────────────── */
    QProgressBar#fileProgressBar {{
        background-color: {tc.BG_SURFACE};
        border: 1px solid {tc.BORDER};
        border-radius: 4px;
        min-height: 8px;
        max-height: 12px;
        text-align: center;
        color: {tc.TEXT_SECONDARY};
        font-size: 10px;
    }}
    QProgressBar#fileProgressBar::chunk {{
        background-color: {tc.PRIMARY};
        border-radius: 3px;
    }}
    QProgressBar#bufferBar {{
        background-color: {tc.BG_SURFACE};
        border: 1px solid {tc.BORDER};
        border-radius: 4px;
        min-height: 8px;
        max-height: 8px;
        text-align: center;
    }}
    QProgressBar#bufferBar::chunk {{
        background-color: {tc.PRIMARY};
        border-radius: 3px;
    }}

    /* ── ScrollBar ─────────────────────────────────────────────────── */
    QScrollBar:vertical {{
        background: {tc.SCROLLBAR_BG};
        width: 10px;
        border: none;
        border-radius: 5px;
    }}
    QScrollBar::handle:vertical {{
        background: {tc.SCROLLBAR_HANDLE};
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {tc.TEXT_SECONDARY};
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: none;
    }}

    /* ── Menu ──────────────────────────────────────────────────────── */
    QMenu {{
        background-color: {tc.BG_SURFACE};
        border: 1px solid {tc.BORDER};
        border-radius: 6px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 6px 24px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background-color: {tc.BG_SELECTION};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {tc.BORDER};
        margin: 4px 8px;
    }}
    QToolTip {{
        background-color: {tc.BG_TOOLTIP};
        color: {tc.TEXT_PRIMARY};
        border: 1px solid {tc.BORDER};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    """
