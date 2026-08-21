"""Color tokens shared by native Qt surfaces and the HTML frontend."""

from __future__ import annotations


class ThemeColors:
    """Dark neumorphic palette: one material surface and one accent color."""

    PRIMARY: str = "#FF6600"
    PRIMARY_DARK: str = "#FF6600"

    # Error/success semantics use copy and iconography rather than extra hues.
    DANGER: str = "#FF6600"
    DANGER_DARK: str = "#FF6600"

    BG_MAIN: str = "#141414"
    BG_CARD: str = "#141414"
    BG_SURFACE: str = "#141414"
    BG_SURFACE_ALT: str = "#141414"
    BG_HOVER: str = "#141414"
    BG_INSET: str = "#141414"

    BORDER: str = "rgba(255, 255, 255, 0.05)"
    BORDER_FOCUS: str = "#FF6600"

    TEXT_PRIMARY: str = "#E1E1E1"
    TEXT_SECONDARY: str = "#878787"
    TEXT_DISABLED: str = "#5A5A5A"
    TEXT_ON_ACCENT: str = "#141414"
    TEXT_ON_SELECTION: str = "#E1E1E1"

    BG_TOOLTIP: str = "#141414"
    BG_SELECTION: str = "#FF6600"
    BG_BADGE: str = "#141414"

    ICON_BORDER: str = "rgba(255, 255, 255, 0.05)"
    ICON_TEXT_SHADOW: str = "rgba(0, 0, 0, 0.72)"

    STATUS_RUNNING: str = "#FF6600"
    STATUS_ERROR: str = "#FF6600"
    STATUS_STOPPED: str = "#5A5A5A"
    STATUS_PAUSED: str = "#FF6600"
    STATUS_BUFFERING: str = "#878787"
    STATUS_LOADING: str = "#FF6600"
    STATUS_COMPLETED: str = "#FF6600"

    SCROLLBAR_BG: str = "#141414"
    SCROLLBAR_HANDLE: str = "#5A5A5A"

    FONT_FAMILY: str = "Inter"
    FONT_FAMILY_MONO: str = "ui-monospace"
    FONT_SIZE: int = 13

    ANIM_DURATION_MS: int = 180
    ANIM_PULSE_PERIOD_MS: int = 0
