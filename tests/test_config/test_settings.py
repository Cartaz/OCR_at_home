"""Test per config/settings.py."""

import json

from config.constants import AppMeta
from config.settings import ComputeDevice, Settings


def test_settings_is_frozen() -> None:
    settings = Settings()
    try:
        settings.language = "eng"  # type: ignore[misc]
        assert False, "Settings dovrebbe essere frozen"
    except AttributeError:
        pass


def test_settings_with_creates_new_instance() -> None:
    first = Settings()
    second = first.with_(language="eng")
    assert first is not second
    assert first.language != second.language
    assert second.language == "eng"


def test_compute_device_choices_are_sycl_only() -> None:
    assert ComputeDevice.choices() == ["llama-cpp-sycl"]


def test_legacy_generic_device_is_migrated_to_sycl(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"default_device": "llama-cpp", "language": "ita+eng"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(AppMeta, "SETTINGS_PATH", settings_path)
    loaded = Settings.load()
    assert loaded.default_device == "llama-cpp-sycl"
