# config/theme.py
"""Token di colore semantici per il tema Breeze Dark.

Questo modulo definisce tutti i colori dell'applicazione come costanti
semantiche. Nessun componente UI deve contenere valori hex al di fuori
di ThemeColors.

Classes:
    ThemeColors: Token di colore centralizzati per Breeze Dark.
"""

from __future__ import annotations


class ThemeColors:
    """Token di colore semantici per Breeze Dark.

    Nessun componente UI può usare valori hex al di fuori di questa classe.
    I token sono organizzati per ruolo semantico, NON per valore cromatico.
    """

    # ── Accento primario — Teal ──────────────────────────────────────
    PRIMARY: str = "#00bfa5"
    PRIMARY_DARK: str = "#00695c"

    # ── Azioni distruttive / Avviso — Arancione ─────────────────────
    DANGER: str = "#db4105"
    DANGER_DARK: str = "#7a2400"

    # ── Colori neutrali e di supporto ────────────────────────────────
    BG_MAIN: str = "#1b1e20"
    BG_CARD: str = "#232629"
    BG_SURFACE: str = "#2a2e32"
    BG_SURFACE_ALT: str = "#31363b"
    BG_HOVER: str = "#3c4248"
    BORDER: str = "#3f4347"
    BORDER_FOCUS: str = "#00bfa5"

    TEXT_PRIMARY: str = "#eff0f1"
    TEXT_SECONDARY: str = "#a0a4a8"
    TEXT_DISABLED: str = "#6b7076"
    TEXT_ON_ACCENT: str = "#ffffff"
    TEXT_ON_SELECTION: str = "#ffffff"

    BG_TOOLTIP: str = "#2a2e32"
    BG_SELECTION: str = "#00695c"
    BG_BADGE: str = "rgba(255, 255, 255, 0.08)"

    # ── Icona Tray ───────────────────────────────────────────────────
    ICON_BORDER: str = "rgba(0, 0, 0, 40)"
    ICON_TEXT_SHADOW: str = "rgba(0, 0, 0, 180)"

    # ── Indicatori di stato ──────────────────────────────────────────
    STATUS_RUNNING: str = "#27ae60"
    STATUS_ERROR: str = "#db4105"
    STATUS_STOPPED: str = "#6b7076"
    STATUS_PAUSED: str = "#00bfa5"
    STATUS_BUFFERING: str = "#f39c12"
    STATUS_LOADING: str = "#00bfa5"
    STATUS_COMPLETED: str = "#27ae60"

    # ── Scrollbar ────────────────────────────────────────────────────
    SCROLLBAR_BG: str = "#2a2e32"
    SCROLLBAR_HANDLE: str = "#5c6066"

    # ── Tipografia ───────────────────────────────────────────────────
    FONT_FAMILY: str = "Noto Sans"
    FONT_FAMILY_MONO: str = "Sarasa Mono SC"
    FONT_SIZE: int = 13

    # ── Animazioni ───────────────────────────────────────────────────
    ANIM_DURATION_MS: int = 200
    ANIM_PULSE_PERIOD_MS: int = 1500
