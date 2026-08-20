# config/theme.py
"""Token cromatici condivisi dal layer Qt/Python.

Il frontend principale usa gli stessi valori in qml/Theme.qml.
"""

from __future__ import annotations


class ThemeColors:
    PRIMARY: str = "#FF6600"
    PRIMARY_DARK: str = "#C94F00"

    DANGER: str = "#E15A36"
    DANGER_DARK: str = "#8B3321"

    BG_MAIN: str = "#141414"
    BG_CARD: str = "#181818"
    BG_SURFACE: str = "#191919"
    BG_SURFACE_ALT: str = "#1D1D1D"
    BG_HOVER: str = "#202020"
    BG_INSET: str = "#101010"

    BORDER: str = "#252525"
    BORDER_FOCUS: str = "#FF6600"

    TEXT_PRIMARY: str = "#ECEFF1"
    TEXT_SECONDARY: str = "#A7ADB4"
    TEXT_DISABLED: str = "#6F757C"
    TEXT_ON_ACCENT: str = "#111111"
    TEXT_ON_SELECTION: str = "#111111"

    BG_TOOLTIP: str = "#1D1D1D"
    BG_SELECTION: str = "#FF6600"
    BG_BADGE: str = "#121212"

    ICON_BORDER: str = "rgba(0, 0, 0, 40)"
    ICON_TEXT_SHADOW: str = "rgba(0, 0, 0, 180)"

    STATUS_RUNNING: str = "#35C46A"
    STATUS_ERROR: str = "#E15A36"
    STATUS_STOPPED: str = "#6F757C"
    STATUS_PAUSED: str = "#FF6600"
    STATUS_BUFFERING: str = "#E7A33D"
    STATUS_LOADING: str = "#FF6600"
    STATUS_COMPLETED: str = "#35C46A"

    SCROLLBAR_BG: str = "#101010"
    SCROLLBAR_HANDLE: str = "#3A3A3A"

    FONT_FAMILY: str = "Noto Sans"
    FONT_FAMILY_MONO: str = "Sarasa Mono SC"
    FONT_SIZE: int = 13

    ANIM_DURATION_MS: int = 150
    ANIM_PULSE_PERIOD_MS: int = 1500
