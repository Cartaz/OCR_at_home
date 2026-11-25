"""Impostazioni persistenti di GLM OCR."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from config.constants import AppMeta, UIConstraints

logger = logging.getLogger(__name__)

_BOOL_FIELDS = frozenset(
    {
        "preprocessing_enabled",
        "batch_auto_save",
        "batch_save_pdf_pages",
        "load_model_at_startup",
    }
)
_INT_RANGES = {
    "model_auto_unload_minutes": (0, 1440),
    "window_width": (UIConstraints.WINDOW_MIN_WIDTH, 16384),
    "window_height": (UIConstraints.WINDOW_MIN_HEIGHT, 16384),
}
OUTPUT_FORMATS = frozenset({"txt", "md"})


def validate_setting(name: str, value: Any) -> Any:
    """Return the normalized value for one setting or raise ``ValueError``."""
    if name in _BOOL_FIELDS:
        if not isinstance(value, bool):
            raise ValueError(f"{name} deve essere un booleano")
        return value
    if name in _INT_RANGES:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} deve essere un intero")
        low, high = _INT_RANGES[name]
        if not low <= value <= high:
            raise ValueError(f"{name} deve essere compreso tra {low} e {high}")
        return value
    if name == "batch_output_format":
        fmt = str(value).strip().lower().lstrip(".") if isinstance(value, str) else ""
        if fmt not in OUTPUT_FORMATS:
            raise ValueError("Formato batch supportato: txt oppure md")
        return fmt
    if name == "output_dir":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("La directory output non può essere vuota")
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            raise ValueError("La directory output deve essere un percorso assoluto")
        return str(path)
    raise AttributeError(f"Settings non ha il campo '{name}'")


@dataclass(frozen=True)
class Settings:
    output_dir: str = str(Path.home() / "Documents" / "glm-ocr-output")
    preprocessing_enabled: bool = True
    batch_auto_save: bool = False
    batch_output_format: str = "txt"
    batch_save_pdf_pages: bool = False
    load_model_at_startup: bool = True
    model_auto_unload_minutes: int = 0
    window_width: int = UIConstraints.WINDOW_WIDTH
    window_height: int = UIConstraints.WINDOW_HEIGHT

    def with_(self, **overrides: object) -> Settings:
        """Return a copy with validated overrides; invalid values raise ``ValueError``."""
        current = asdict(self)
        for key, value in overrides.items():
            current[key] = validate_setting(key, value)
        return Settings(**current)

    def save(self) -> None:
        """Durably replace settings without exposing a truncated final JSON file."""
        directory = AppMeta.SETTINGS_PATH.parent
        directory.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{AppMeta.SETTINGS_PATH.name}.",
            suffix=".tmp",
            dir=directory,
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
                json.dump(asdict(self), file, indent=2, ensure_ascii=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            os.replace(temp_path, AppMeta.SETTINGS_PATH)
            try:
                dir_fd = os.open(directory, os.O_RDONLY)
            except OSError:
                dir_fd = -1
            if dir_fd >= 0:
                try:
                    try:
                        os.fsync(dir_fd)
                    except OSError:
                        pass
                finally:
                    os.close(dir_fd)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        logger.info("Impostazioni salvate in %s", AppMeta.SETTINGS_PATH)

    @classmethod
    def load(cls) -> Settings:
        """Load settings, replacing every malformed value with its default.

        Startup must never fail because of the settings file: a non-object
        JSON document, an unreadable file or a single invalid value only
        reverts the affected part to defaults. Keys from older versions
        (``default_device``, ``language``, ``model_path``,
        ``confidence_threshold``) are ignored.
        """
        path = AppMeta.SETTINGS_PATH
        if not path.exists():
            logger.info("Nessun file impostazioni trovato, uso i default")
            return cls()

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Impossibile leggere le impostazioni (%s), uso i default", exc)
            return cls()
        if not isinstance(data, dict):
            logger.warning("File impostazioni non valido (atteso un oggetto JSON), uso i default")
            return cls()

        values: dict[str, Any] = {}
        for field in fields(cls):
            if field.name not in data:
                continue
            try:
                values[field.name] = validate_setting(field.name, data[field.name])
            except ValueError as exc:
                logger.warning("Impostazione %s non valida (%s), uso il default", field.name, exc)
        settings = cls(**values)
        logger.info("Impostazioni caricate da %s", path)
        return settings
