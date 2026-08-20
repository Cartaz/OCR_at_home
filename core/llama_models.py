"""Gestione e validazione dei modelli GGUF."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from config.constants import AppConstants
from core.cancellation import CancellationToken
from core.event_bus import EventBus
from core.exceptions import ModelLoadError, OperationCancelledError

logger = logging.getLogger(__name__)

GGUF_MODEL_ID = "ggml-org/GLM-OCR-GGUF"
GGUF_MODEL_FILES = {
    "main": "GLM-OCR-Q8_0.gguf",
    "mmproj": "mmproj-GLM-OCR-Q8_0.gguf",
}
GGUF_CACHE_DIR = AppConstants.GGUF_MODEL_DIR
_MIN_MODEL_SIZE = {
    "main": 100 * 1024 * 1024,
    "mmproj": 10 * 1024 * 1024,
}


def _is_valid_gguf(path: Path, key: str) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < _MIN_MODEL_SIZE[key]:
            return False
        with path.open("rb") as handle:
            return handle.read(4) == b"GGUF"
    except OSError:
        return False


def ensure_gguf_models(
    cancel_token: CancellationToken | None = None,
) -> dict[str, Path]:
    """Restituisce file GGUF validati, scaricandoli quando necessario."""
    GGUF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    model_paths = {
        key: GGUF_CACHE_DIR / filename
        for key, filename in GGUF_MODEL_FILES.items()
    }

    if cancel_token is not None:
        cancel_token.raise_if_cancelled()

    for key, path in model_paths.items():
        if path.exists() and not _is_valid_gguf(path, key):
            logger.warning("GGUF incompleto/corrotto, riscarico: %s", path)
            try:
                path.unlink()
            except OSError as exc:
                raise ModelLoadError(
                    GGUF_MODEL_ID,
                    f"Impossibile rimuovere {path}: {exc}",
                ) from exc

    if all(_is_valid_gguf(path, key) for key, path in model_paths.items()):
        return model_paths

    EventBus.emit(
        "model_load_progress",
        {"message": "Download modelli GGUF (primo avvio)..."},
    )

    try:
        from huggingface_hub import hf_hub_download

        for key, filename in GGUF_MODEL_FILES.items():
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            path = model_paths[key]
            if _is_valid_gguf(path, key):
                continue

            EventBus.emit(
                "model_load_progress",
                {"message": f"Scaricamento {filename}..."},
            )
            downloaded = Path(
                hf_hub_download(
                    repo_id=GGUF_MODEL_ID,
                    filename=filename,
                    local_dir=str(GGUF_CACHE_DIR),
                )
            )
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            if downloaded != path:
                shutil.copy2(downloaded, path)
            if not _is_valid_gguf(path, key):
                raise ModelLoadError(
                    GGUF_MODEL_ID,
                    f"File GGUF non valido: {filename}",
                )
    except (ModelLoadError, OperationCancelledError):
        raise
    except Exception as exc:
        raise ModelLoadError(
            GGUF_MODEL_ID,
            f"Impossibile scaricare i modelli GGUF: {exc}",
        ) from exc

    return model_paths
