# config/settings.py
"""Impostazioni utente persistenti per GLM OCR.

Gestisce tutte le impostazioni dell'applicazione tramite dataclass
congelata. La persistenza avviene in JSON nella directory XDG
appropriata, conforme alla XDG Base Directory Specification.

Classes:
    ComputeDevice: Enum dei backend di calcolo (llama.cpp).
    Settings: Impostazioni immutabili dell'applicazione.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from config.constants import AppMeta, OCRDefaults, UIConstraints

logger = logging.getLogger(__name__)


class ComputeDevice(str, Enum):
    """Dispositivo di calcolo per l'inferenza OCR.

    L'applicazione supporta esclusivamente llama.cpp come backend.
    SYCL è il backend raccomandato per GPU Intel Arc.
    """

    LLAMA_CPP = "llama-cpp"
    LLAMA_CPP_SYCL = "llama-cpp-sycl"

    @classmethod
    def choices(cls) -> list[str]:
        """Restituisce tutti i valori disponibili.

        Returns:
            Lista degli identificativi dei dispositivi.
        """
        return [m.value for m in cls]

    @classmethod
    def default(cls) -> ComputeDevice:
        """Restituisce il dispositivo predefinito.

        Returns:
            llama-cpp-sycl come scelta ottimale (SYCL + GGUF quantizzato).
        """
        return cls.LLAMA_CPP_SYCL


@dataclass(frozen=True)
class Settings:
    """Impostazioni immutabili dell'applicazione GLM OCR.

    Crea una copia modificata con:
        new_settings = settings.with_(default_device="llama-cpp")

    Attributes:
        default_device: Dispositivo di inferenza predefinito.
        language: Lingua OCR predefinita.
        output_dir: Directory di output per i risultati.
        preprocessing_enabled: Attiva la pre-elaborazione immagini.
        model_path: Percorso della directory modelli GGUF.
        confidence_threshold: Soglia di confidenza minima.
        window_width: Larghezza iniziale finestra.
        window_height: Altezza iniziale finestra.
    """

    # ── OCR ──────────────────────────────────────────────────────
    default_device: str = ComputeDevice.LLAMA_CPP_SYCL.value
    language: str = OCRDefaults.DEFAULT_OCR_LANGUAGE
    output_dir: str = str(Path.home() / "Documents" / "glm-ocr-output")
    preprocessing_enabled: bool = True
    model_path: str = str(AppMeta.GGUF_MODEL_DIR)
    confidence_threshold: float = OCRDefaults.DEFAULT_CONFIDENCE_THRESHOLD

    # ── UI ────────────────────────────────────────────────────────
    window_width: int = UIConstraints.WINDOW_WIDTH
    window_height: int = UIConstraints.WINDOW_HEIGHT

    # ── Copia con override ────────────────────────────────────────
    def with_(self, **overrides: object) -> Settings:
        """Restituisce una nuova Settings con i campi indicati sostituiti.

        Args:
            **overrides: Campi da sostituire e loro nuovi valori.

        Returns:
            Una nuova istanza di Settings con gli override applicati.

        Raises:
            AttributeError: Se un campo non esiste nella dataclass.
        """
        current = asdict(self)
        for key, value in overrides.items():
            if key not in current:
                raise AttributeError(f"Settings non ha il campo '{key}'")
            current[key] = value
        return Settings(**current)

    # ── Persistenza ───────────────────────────────────────────────
    def save(self) -> None:
        """Serializza le impostazioni in JSON su disco.

        Salva nella directory XDG_CONFIG_HOME/glm-ocr/settings.json.
        """
        AppMeta.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        with open(AppMeta.SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Impostazioni salvate in %s", AppMeta.SETTINGS_PATH)

    @classmethod
    def load(cls) -> Settings:
        """Carica le impostazioni da disco, con fallback ai default.

        Migra automaticamente i dispositivi obsoleti (GPU, NPU, CPU)
        al backend corrente (llama-cpp-sycl).

        Returns:
            Istanza di Settings con valori da disco o predefiniti.
        """
        if not AppMeta.SETTINGS_PATH.exists():
            logger.info("Nessun file impostazioni trovato, uso i default")
            return cls()

        try:
            with open(AppMeta.SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in valid_keys}

            # Migrazione: se il dispositivo è un tipo obsoleto,
            # migra al backend corrente (llama-cpp-sycl)
            device = filtered.get("default_device")
            valid_devices = (
                ComputeDevice.LLAMA_CPP.value,
                ComputeDevice.LLAMA_CPP_SYCL.value,
            )
            if device not in valid_devices:
                old_device = device
                filtered["default_device"] = ComputeDevice.default().value
                logger.info(
                    "Migrazione dispositivo: %s → %s (backend GGUF)",
                    old_device, filtered["default_device"],
                )

            settings = cls(**filtered)
            logger.info("Impostazioni caricate — device=%s, lang=%s",
                        settings.default_device, settings.language)
            return settings
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Impossibile caricare le impostazioni (%s), uso i default", exc)
            return cls()
