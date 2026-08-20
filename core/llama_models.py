# core/llama_models.py
"""Gestione download modelli GGUF per llama.cpp.

Scarica e verifica la disponibilità dei modelli GGUF (GLM-OCR Q8_0
+ mmproj) nella directory di cache, usando huggingface_hub.

Functions:
    ensure_gguf_models: Verifica e scarica i modelli GGUF.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from config.constants import AppConstants
from core.event_bus import EventBus
from core.exceptions import ModelLoadError

logger = logging.getLogger(__name__)

# Identificativo repository HuggingFace e nomi file
GGUF_MODEL_ID: str = "ggml-org/GLM-OCR-GGUF"
GGUF_MODEL_FILES: dict[str, str] = {
    "main": "GLM-OCR-Q8_0.gguf",
    "mmproj": "mmproj-GLM-OCR-Q8_0.gguf",
}
GGUF_CACHE_DIR: Path = AppConstants.GGUF_MODEL_DIR


def ensure_gguf_models() -> dict[str, Path]:
    """Verifica che i modelli GGUF siano disponibili, li scarica se necessario.

    Controlla la cache locale per i file modello. Se uno o più file
    mancano, li scarica da HuggingFace usando huggingface_hub.

    Returns:
        Dict con i percorsi dei file modello {'main': Path, 'mmproj': Path}.

    Raises:
        ModelLoadError: Se i modelli non possono essere scaricati.
    """
    GGUF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    model_paths: dict[str, Path] = {}
    need_download = False

    for key, filename in GGUF_MODEL_FILES.items():
        path = GGUF_CACHE_DIR / filename
        model_paths[key] = path
        if not path.exists():
            logger.info("Modello GGUF mancante: %s", filename)
            need_download = True

    if not need_download:
        logger.info("Modelli GGUF trovati nella cache: %s", GGUF_CACHE_DIR)
        return model_paths

    # Scarica i modelli mancanti
    logger.info("Download modelli GGUF da HuggingFace...")
    EventBus.emit("model_load_progress", {
        "message": "Download modelli GGUF (primo avvio)...",
    })

    try:
        from huggingface_hub import hf_hub_download
        for key, filename in GGUF_MODEL_FILES.items():
            path = model_paths[key]
            if path.exists():
                continue
            logger.info("Scaricamento %s...", filename)
            EventBus.emit("model_load_progress", {
                "message": f"Scaricamento {filename}...",
            })
            downloaded = hf_hub_download(
                repo_id=GGUF_MODEL_ID,
                filename=filename,
                local_dir=str(GGUF_CACHE_DIR),
            )
            downloaded_path = Path(downloaded)
            if downloaded_path != path:
                shutil.copy2(downloaded_path, path)
            logger.info("Scaricato: %s (%.1f MB)", filename, path.stat().st_size / 1e6)

    except Exception as exc:
        raise ModelLoadError(
            GGUF_MODEL_ID,
            f"Impossibile scaricare i modelli GGUF: {exc}. "
            f"Verifica la connessione internet o scarica manualmente da "
            f"https://huggingface.co/{GGUF_MODEL_ID}",
        ) from exc

    return model_paths
