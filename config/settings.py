# config/settings.py
"""Impostazioni persistenti di GLM OCR."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from config.constants import AppMeta, OCRDefaults, UIConstraints

logger = logging.getLogger(__name__)


class ComputeDevice(str, Enum):
    """Backend di calcolo.

    GLM OCR è intenzionalmente SYCL-only. ``LLAMA_CPP`` resta soltanto come
    token legacy per riconoscere vecchi file di configurazione.
    """

    LLAMA_CPP = "llama-cpp"
    LLAMA_CPP_SYCL = "llama-cpp-sycl"

    @classmethod
    def choices(cls) -> list[str]:
        return [cls.LLAMA_CPP_SYCL.value]

    @classmethod
    def default(cls) -> ComputeDevice:
        return cls.LLAMA_CPP_SYCL


@dataclass(frozen=True)
class Settings:
    default_device: str = ComputeDevice.LLAMA_CPP_SYCL.value
    language: str = OCRDefaults.DEFAULT_OCR_LANGUAGE
    output_dir: str = str(Path.home() / "Documents" / "glm-ocr-output")
    preprocessing_enabled: bool = True
    batch_auto_save: bool = False
    batch_output_format: str = "txt"
    batch_save_pdf_pages: bool = False
    load_model_at_startup: bool = True
    model_auto_unload_minutes: int = 0
    model_path: str = str(AppMeta.GGUF_MODEL_DIR)
    window_width: int = UIConstraints.WINDOW_WIDTH
    window_height: int = UIConstraints.WINDOW_HEIGHT

    def with_(self, **overrides: object) -> Settings:
        current = asdict(self)
        for key, value in overrides.items():
            if key not in current:
                raise AttributeError(f"Settings non ha il campo '{key}'")
            current[key] = value
        return Settings(**current)

    def save(self) -> None:
        AppMeta.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(AppMeta.SETTINGS_PATH, "w", encoding="utf-8") as file:
            json.dump(asdict(self), file, indent=2, ensure_ascii=False)
        logger.info("Impostazioni salvate in %s", AppMeta.SETTINGS_PATH)

    @classmethod
    def load(cls) -> Settings:
        """Carica le impostazioni e forza qualsiasi device legacy su SYCL.

        Le chiavi non più supportate (per esempio la vecchia
        ``confidence_threshold``) vengono ignorate in modo compatibile.
        """
        if not AppMeta.SETTINGS_PATH.exists():
            logger.info("Nessun file impostazioni trovato, uso i default")
            return cls()

        try:
            with open(AppMeta.SETTINGS_PATH, "r", encoding="utf-8") as file:
                data = json.load(file)

            valid_keys = {field.name for field in cls.__dataclass_fields__.values()}
            filtered = {key: value for key, value in data.items() if key in valid_keys}

            configured = filtered.get("default_device")
            if configured != ComputeDevice.LLAMA_CPP_SYCL.value:
                filtered["default_device"] = ComputeDevice.LLAMA_CPP_SYCL.value
                logger.info(
                    "Migrazione dispositivo SYCL-only: %s → %s",
                    configured,
                    ComputeDevice.LLAMA_CPP_SYCL.value,
                )

            output_format = str(filtered.get("batch_output_format", "txt")).lower()
            filtered["batch_output_format"] = (
                output_format if output_format in {"txt", "md"} else "txt"
            )
            for key in (
                "batch_auto_save",
                "batch_save_pdf_pages",
                "load_model_at_startup",
            ):
                if key in filtered and not isinstance(filtered[key], bool):
                    filtered.pop(key)

            try:
                auto_unload = int(filtered.get("model_auto_unload_minutes", 0))
            except (TypeError, ValueError):
                auto_unload = 0
            filtered["model_auto_unload_minutes"] = (
                auto_unload if 0 <= auto_unload <= 1440 else 0
            )

            settings = cls(**filtered)
            logger.info(
                "Impostazioni caricate — device=%s, lang=%s",
                settings.default_device,
                settings.language,
            )
            return settings
        except (json.JSONDecodeError, TypeError, KeyError, OSError) as exc:
            logger.warning(
                "Impossibile caricare le impostazioni (%s), uso i default",
                exc,
            )
            return cls()
