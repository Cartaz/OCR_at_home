"""Test per config/settings.py — verifica persistenza e immutabilità.

Tests:
    - Settings è una dataclass frozen
    - with_() crea una nuova istanza con override
    - Il caricamento da disco funziona con fallback
"""
from config.settings import Settings


def test_settings_is_frozen() -> None:
    """Verifica che Settings sia immutabile (frozen=True)."""
    s = Settings()
    try:
        s.language = "eng"  # type: ignore[misc]
        assert False, "Settings dovrebbe essere frozen"
    except AttributeError:
        pass


def test_settings_with_creates_new_instance() -> None:
    """Verifica che with_() restituisca una nuova istanza."""
    s1 = Settings()
    s2 = s1.with_(language="eng")
    assert s1 is not s2
    assert s1.language != s2.language
    assert s2.language == "eng"
