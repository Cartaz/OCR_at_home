# ui/widgets/__init__.py
"""Pacchetto widget dell'interfaccia GLM OCR."""

from ui.widgets.action_button import ActionButton
from ui.widgets.batch_tab import BatchTab
from ui.widgets.card import Card
from ui.widgets.config_panel import ConfigPanel
from ui.widgets.device_selector import DeviceSelector
from ui.widgets.image_drop_area import ImageDropArea
from ui.widgets.ocr_tab import OCRTab
from ui.widgets.shortcut_badge import ShortcutBadge
from ui.widgets.status_indicator import StatusIndicator

__all__ = [
    "ActionButton",
    "BatchTab",
    "Card",
    "ConfigPanel",
    "DeviceSelector",
    "ImageDropArea",
    "OCRTab",
    "ShortcutBadge",
    "StatusIndicator",
]
