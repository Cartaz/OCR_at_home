# config/__init__.py
"""Pacchetto configurazione dell'applicazione GLM OCR.

Espone l'interfaccia pubblica del livello configurazione.
"""

from config.constants import AppConstants, AppMeta, OCRDefaults, UIConstraints
from config.settings import ComputeDevice, Settings
from config.theme import ThemeColors

__all__ = [
    "AppConstants",
    "AppMeta",
    "ComputeDevice",
    "OCRDefaults",
    "Settings",
    "ThemeColors",
    "UIConstraints",
]
