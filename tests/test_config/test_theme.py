"""Test per config/theme.py — verifica token di colore centralizzati.

Tests:
    - ThemeColors ha tutti i token richiesti dallo spec
    - I valori hex sono validi
"""
from config.theme import ThemeColors


REQUIRED_TOKENS = [
    "PRIMARY", "PRIMARY_DARK", "DANGER", "DANGER_DARK",
    "BG_MAIN", "BG_CARD", "BORDER", "TEXT_PRIMARY",
    "TEXT_SECONDARY", "TEXT_DISABLED", "BG_TOOLTIP", "BG_SELECTION",
    "STATUS_RUNNING", "STATUS_ERROR", "STATUS_STOPPED", "STATUS_PAUSED",
]


def test_theme_has_all_required_tokens() -> None:
    """Verifica che ThemeColors contenga tutti i token richiesti."""
    for token in REQUIRED_TOKENS:
        assert hasattr(ThemeColors, token), f"Token mancante: {token}"


def test_theme_values_are_strings() -> None:
    """Verifica che tutti i token di colore siano stringhe."""
    for token in REQUIRED_TOKENS:
        value = getattr(ThemeColors, token)
        assert isinstance(value, str), f"{token} non è una stringa"
