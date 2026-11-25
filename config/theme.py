"""Color tokens for native Qt surfaces (tray menu, tooltips).

The QML interface has its own ``ui/qml/Theme.qml`` with the same values.
"""

from __future__ import annotations


class ThemeColors:
    """Dark neumorphic palette: one material surface and one accent color."""

    PRIMARY: str = "#FF6600"
    BG_MAIN: str = "#141414"
    TEXT_PRIMARY: str = "#E1E1E1"
