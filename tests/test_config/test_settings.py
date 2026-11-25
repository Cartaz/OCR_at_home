"""Settings persistence and validation."""

import json

import pytest

from config.constants import AppMeta
from config.settings import Settings


@pytest.fixture
def settings_path(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(AppMeta, "SETTINGS_PATH", path)
    return path


def test_settings_is_frozen() -> None:
    with pytest.raises(AttributeError):
        Settings().batch_auto_save = True  # type: ignore[misc]


def test_with_validates_and_returns_a_new_instance() -> None:
    first = Settings()
    second = first.with_(batch_output_format=".MD", model_auto_unload_minutes=30)
    assert first is not second
    assert second.batch_output_format == "md"
    assert second.model_auto_unload_minutes == 30
    with pytest.raises(ValueError):
        first.with_(model_auto_unload_minutes=99999)
    with pytest.raises(ValueError):
        first.with_(output_dir="relative/dir")
    with pytest.raises(ValueError):
        first.with_(batch_auto_save="yes")
    with pytest.raises(AttributeError):
        first.with_(language="ita")


def test_model_memory_defaults_preserve_existing_startup_behavior() -> None:
    settings = Settings()
    assert settings.load_model_at_startup is True
    assert settings.model_auto_unload_minutes == 0


def test_save_atomically_replaces_existing_settings(settings_path, tmp_path) -> None:
    settings_path.write_text(json.dumps({"batch_auto_save": False}), encoding="utf-8")
    Settings(batch_auto_save=True).save()
    assert json.loads(settings_path.read_text(encoding="utf-8"))["batch_auto_save"] is True
    assert list(tmp_path.glob(".settings.json.*.tmp")) == []


def test_save_failure_preserves_previous_settings_file(settings_path, monkeypatch, tmp_path) -> None:
    original = json.dumps({"batch_auto_save": False})
    settings_path.write_text(original, encoding="utf-8")

    def fail_replace(_source, _destination) -> None:
        raise OSError("simulated publication failure")

    monkeypatch.setattr("config.settings.os.replace", fail_replace)
    with pytest.raises(OSError, match="publication failure"):
        Settings(batch_auto_save=True).save()
    assert settings_path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".settings.json.*.tmp")) == []


@pytest.mark.parametrize("content", ["[]", "42", '"text"', "{not json", "null"])
def test_malformed_file_never_breaks_startup(settings_path, content) -> None:
    settings_path.write_text(content, encoding="utf-8")
    assert Settings.load() == Settings()


def test_invalid_values_fall_back_per_field(settings_path) -> None:
    settings_path.write_text(
        json.dumps(
            {
                "window_width": "big",
                "output_dir": 5,
                "preprocessing_enabled": "no",
                "load_model_at_startup": False,
                "model_auto_unload_minutes": 99999,
                "batch_output_format": "pdf",
            }
        ),
        encoding="utf-8",
    )
    loaded = Settings.load()
    defaults = Settings()
    assert loaded.window_width == defaults.window_width
    assert loaded.output_dir == defaults.output_dir
    assert loaded.preprocessing_enabled is True
    assert loaded.model_auto_unload_minutes == 0
    assert loaded.batch_output_format == "txt"
    assert loaded.load_model_at_startup is False  # the valid field is kept


def test_legacy_keys_are_ignored(settings_path) -> None:
    settings_path.write_text(
        json.dumps(
            {
                "default_device": "llama-cpp",
                "language": "ita",
                "model_path": "/old",
                "confidence_threshold": 0.95,
                "batch_auto_save": True,
            }
        ),
        encoding="utf-8",
    )
    loaded = Settings.load()
    assert loaded.batch_auto_save is True
    assert not hasattr(loaded, "language")
