# config/constants.py
"""Costanti globali dell'applicazione GLM OCR.

Le costanti sono raggruppate in classi per dominio. I percorsi sono
calcolati dinamicamente con pathlib.Path e variabili d'ambiente XDG.

Classes:
    AppMeta: Metadati dell'applicazione.
    OCRDefaults: Valori predefiniti della pipeline OCR.
    UIConstraints: Vincoli e dimensioni dell'interfaccia.
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
    """Metadati identificativi dell'applicazione GLM OCR."""

    NAME: str = "GLM OCR"
    VERSION: str = "1.0.0"
    ID: str = "com.glm-ocr.app"
    DESCRIPTION: str = "Riconoscimento ottico con motore GLM-OCR (llama.cpp + SYCL)"
    LICENSE: str = "MIT"
    CONFIG_DIR: Path = _xdg_config_home() / "glm-ocr"
    SETTINGS_PATH: Path = _xdg_config_home() / "glm-ocr" / "settings.json"
    LOG_PATH: Path = _xdg_config_home() / "glm-ocr" / "glm-ocr.log"
    DESKTOP_DIR: Path = Path.home() / ".local" / "share" / "applications"

    GGUF_MODEL_ID: str = "ggml-org/GLM-OCR-GGUF"
    GGUF_MODEL_DIR: Path = _xdg_cache_home() / "glm-ocr" / "models" / "gguf"
    INPUT_CACHE_DIR: Path = _xdg_cache_home() / "glm-ocr" / "inputs"

    SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset({
        ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif",
        ".webp", ".pdf", ".gif",
    })
    MAX_BATCH_SIZE: int = 50
    MAX_IMAGE_SIZE_MB: int = 50


class OCRDefaults:
    """Valori predefiniti della pipeline OCR.

    I parametri di tuning di ``llama-server`` non vivono qui: la produzione
    lascia al binario llama.cpp installato i suoi default nativi. Il benchmark
    parte dalla stessa baseline stock e applica override solo ai candidati.
    """

    DEFAULT_OCR_LANGUAGE: str = "ita+eng"
    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.5
    DEFAULT_PROCESSING_TIMEOUT_S: int = 600
    PREPROCESS_DPI_TARGET: int = 300
    PREPROCESS_MAX_DIMENSION: int = 4096

    LLAMA_MAX_TOKENS: int = 4096
    LLAMA_PDF_DPI: int = 150
    LLAMA_JPEG_QUALITY: int = 80
    LLAMA_MAX_IMAGE_DIM: int = 8192
    LLAMA_HTTP_TIMEOUT_S: int = 600

    # ``llama-cpp`` resta come token legacy per migrare vecchi settings, ma
    # non è un device supportato dall'applicazione. GLM OCR è SYCL-only.
    LLAMA_CPP_DEVICE: str = "llama-cpp"
    LLAMA_CPP_SYCL_DEVICE: str = "llama-cpp-sycl"
    SUPPORTED_DEVICES: frozenset[str] = frozenset({LLAMA_CPP_SYCL_DEVICE})


class UIConstraints:
    """Vincoli e dimensioni dell'interfaccia utente."""

    WINDOW_WIDTH: int = 480
    WINDOW_HEIGHT: int = 540
    CARD_PADDING: int = 16
    CARD_MARGIN: int = 8
    CARD_BORDER_RADIUS: int = 6
    BUTTON_MIN_HEIGHT: int = 30
    STATUS_DOT_DIAMETER: int = 8
    SHORTCUT_BADGE_FONT_SIZE: int = 10
    MAX_GRID_COLUMNS: int = 2
    STATS_UPDATE_INTERVAL_MS: int = 1000


class AppConstants:
    """Classe di compatibilità che unisce i token delle altre classi."""

    APP_NAME = AppMeta.NAME
    APP_VERSION = AppMeta.VERSION
    APP_ID = AppMeta.ID
    APP_DESCRIPTION = AppMeta.DESCRIPTION
    ORG_NAME = AppMeta.ID

    MAX_BATCH_SIZE = AppMeta.MAX_BATCH_SIZE
    MAX_IMAGE_SIZE_MB = AppMeta.MAX_IMAGE_SIZE_MB
    SUPPORTED_IMAGE_EXTENSIONS = AppMeta.SUPPORTED_IMAGE_EXTENSIONS

    DEFAULT_OCR_LANGUAGE = OCRDefaults.DEFAULT_OCR_LANGUAGE
    DEFAULT_CONFIDENCE_THRESHOLD = OCRDefaults.DEFAULT_CONFIDENCE_THRESHOLD
    DEFAULT_PROCESSING_TIMEOUT_S = OCRDefaults.DEFAULT_PROCESSING_TIMEOUT_S
    PREPROCESS_DPI_TARGET = OCRDefaults.PREPROCESS_DPI_TARGET
    PREPROCESS_MAX_DIMENSION = OCRDefaults.PREPROCESS_MAX_DIMENSION

    LLAMA_MAX_TOKENS = OCRDefaults.LLAMA_MAX_TOKENS
    LLAMA_PDF_DPI = OCRDefaults.LLAMA_PDF_DPI
    LLAMA_JPEG_QUALITY = OCRDefaults.LLAMA_JPEG_QUALITY
    LLAMA_MAX_IMAGE_DIM = OCRDefaults.LLAMA_MAX_IMAGE_DIM
    LLAMA_HTTP_TIMEOUT_S = OCRDefaults.LLAMA_HTTP_TIMEOUT_S

    LLAMA_CPP_DEVICE = OCRDefaults.LLAMA_CPP_DEVICE
    LLAMA_CPP_SYCL_DEVICE = OCRDefaults.LLAMA_CPP_SYCL_DEVICE
    SUPPORTED_DEVICES = OCRDefaults.SUPPORTED_DEVICES

    GGUF_MODEL_ID = AppMeta.GGUF_MODEL_ID
    GGUF_MODEL_DIR = AppMeta.GGUF_MODEL_DIR

    XDG_CONFIG_SUBDIR = "glm-ocr"
    SETTINGS_FILENAME = "settings.json"
