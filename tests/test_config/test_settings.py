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


def test_model_memory_defaults_preserve_existing_startup_behavior() -> None:
    settings = Settings()
    assert settings.load_model_at_startup is True
    assert settings.model_auto_unload_minutes == 0


def test_legacy_generic_device_is_migrated_to_sycl(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"default_device": "llama-cpp", "language": "ita+eng"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(AppMeta, "SETTINGS_PATH", settings_path)
    loaded = Settings.load()
    assert loaded.default_device == "llama-cpp-sycl"


def test_legacy_confidence_threshold_is_ignored(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_device": "llama-cpp-sycl",
                "language": "ita",
                "confidence_threshold": 0.95,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(AppMeta, "SETTINGS_PATH", settings_path)

    loaded = Settings.load()

    assert loaded.language == "ita"
    assert not hasattr(loaded, "confidence_threshold")


def test_model_memory_settings_are_validated_on_load(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_device": "llama-cpp-sycl",
                "load_model_at_startup": False,
                "model_auto_unload_minutes": 30,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(AppMeta, "SETTINGS_PATH", settings_path)

    loaded = Settings.load()

    assert loaded.load_model_at_startup is False
    assert loaded.model_auto_unload_minutes == 30


def test_invalid_model_memory_settings_fall_back_safely(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_device": "llama-cpp-sycl",
                "load_model_at_startup": "yes",
                "model_auto_unload_minutes": 99999,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(AppMeta, "SETTINGS_PATH", settings_path)

    loaded = Settings.load()

    assert loaded.load_model_at_startup is True
    assert loaded.model_auto_unload_minutes == 0
