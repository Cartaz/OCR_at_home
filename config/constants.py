"""Costanti globali dell'applicazione GLM OCR.

I percorsi sono calcolati con pathlib.Path e le variabili d'ambiente XDG.
"""

from __future__ import annotations

import os
from pathlib import Path


def _xdg_config_home() -> Path:
    """Restituisce il percorso XDG_CONFIG_HOME conforme alla specifica."""
    return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))


def _xdg_cache_home() -> Path:
    """Restituisce il percorso XDG_CACHE_HOME conforme alla specifica."""
    return Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))


class AppMeta:
    """Metadati, percorsi e limiti di input dell'applicazione."""

    NAME: str = "GLM OCR"
    VERSION: str = "1.1.0"
    ID: str = "com.glm-ocr.app"
    DESCRIPTION: str = "Riconoscimento ottico con motore GLM-OCR (llama.cpp + SYCL)"
    CONFIG_DIR: Path = _xdg_config_home() / "glm-ocr"
    SETTINGS_PATH: Path = CONFIG_DIR / "settings.json"
    LOG_PATH: Path = CONFIG_DIR / "glm-ocr.log"
    LLAMA_SERVER_LOG_PATH: Path = CONFIG_DIR / "llama-server.log"

    GGUF_MODEL_DIR: Path = _xdg_cache_home() / "glm-ocr" / "models" / "gguf"
    INPUT_CACHE_DIR: Path = _xdg_cache_home() / "glm-ocr" / "inputs"

    SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset({
        ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif",
        ".webp", ".pdf", ".gif",
    })
    MAX_BATCH_SIZE: int = 50
    MAX_IMAGE_SIZE_MB: int = 50


class OCRDefaults:
    """Valori della pipeline OCR di produzione.

    I parametri di tuning di ``llama-server`` non vivono qui: la produzione
    lascia al binario llama.cpp installato i suoi default nativi. Il benchmark
    parte dalla stessa baseline stock e applica override solo ai candidati.
    """

    PREPROCESS_MAX_DIMENSION: int = 4096
    LLAMA_MAX_TOKENS: int = 4096
    LLAMA_PDF_DPI: int = 150
    LLAMA_JPEG_QUALITY: int = 80
    LLAMA_MAX_IMAGE_DIM: int = 8192
    LLAMA_HTTP_TIMEOUT_S: int = 600


class UIConstraints:
    """Dimensioni della finestra principale."""

    WINDOW_WIDTH: int = 1100
    WINDOW_HEIGHT: int = 780
    WINDOW_MIN_WIDTH: int = 420
    WINDOW_MIN_HEIGHT: int = 480
