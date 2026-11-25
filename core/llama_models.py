"""Download e verifica dei modelli GGUF di GLM-OCR.

I file sono scaricati da una revisione Hugging Face pinnata e verificati con
SHA-256. La verifica completa avviene una sola volta: un marcatore accanto al
file registra hash, dimensione e mtime, così gli avvii successivi non rileggono
1,4 GB di modello.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from config.constants import AppMeta
from core.cancellation import CancellationToken
from core.event_bus import EventBus
from core.exceptions import ModelLoadError, OperationCancelledError

logger = logging.getLogger(__name__)

GGUF_MODEL_ID = "ggml-org/GLM-OCR-GGUF"
GGUF_MODEL_REVISION = "65a42de1148dbed2297e922b5dbc7d9b70c36578"
GGUF_CACHE_DIR = AppMeta.GGUF_MODEL_DIR


@dataclass(frozen=True)
class ModelFile:
    filename: str
    sha256: str
    size: int


GGUF_MODEL_FILES: dict[str, ModelFile] = {
    "main": ModelFile(
        "GLM-OCR-Q8_0.gguf",
        "45bc244a6446aff850521dc41f18bc8d7105ad5f0c2c8c28af04e7cc4f4d50b1",
        950_433_408,
    ),
    "mmproj": ModelFile(
        "mmproj-GLM-OCR-Q8_0.gguf",
        "9c4b58e33e316ed142eb5dcb41abec3844d3e6e5dc361ffb782c3fa9d175141f",
        484_403_648,
    ),
}


def _marker_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.verified")


def _sha256(path: Path, cancel_token: CancellationToken | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def _is_verified(
    path: Path, spec: ModelFile, cancel_token: CancellationToken | None = None
) -> bool:
    """Return True when ``path`` matches the pinned size and SHA-256."""
    try:
        stat = path.stat()
    except OSError:
        return False
    if stat.st_size != spec.size:
        return False
    stamp = f"{spec.sha256} {stat.st_size} {stat.st_mtime_ns}"
    marker = _marker_path(path)
    try:
        if marker.read_text(encoding="utf-8").strip() == stamp:
            return True
    except OSError:
        pass
    try:
        if _sha256(path, cancel_token) != spec.sha256:
            return False
    except OSError:
        return False
    try:
        marker.write_text(stamp + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Impossibile registrare la verifica di %s: %s", path, exc)
    return True


# filename -> (thread, outcome) of downloads that may outlive a cancelled load.
_DOWNLOADS: dict[str, tuple[threading.Thread, dict[str, object]]] = {}
_DOWNLOADS_LOCK = threading.Lock()


def _download(spec: ModelFile, cancel_token: CancellationToken | None) -> Path:
    """Download one file; cancellation returns immediately.

    ``hf_hub_download`` cannot be interrupted. It runs in a daemon thread so a
    cancelled load (or app shutdown) is not held hostage by a multi-GB
    transfer. The transfer itself continues in the background until it ends
    or the app exits; a retry joins it instead of starting a parallel one.
    """
    from huggingface_hub import hf_hub_download

    with _DOWNLOADS_LOCK:
        pending = _DOWNLOADS.get(spec.filename)
        if pending is None or not pending[0].is_alive():
            pending = None
    if pending is not None:
        # A previous (cancelled) attempt is still transferring this file:
        # wait for it instead of starting a second, lock-blocked download.
        worker, outcome = pending
        return _wait_download(worker, outcome, cancel_token)

    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            outcome["path"] = hf_hub_download(
                repo_id=GGUF_MODEL_ID,
                filename=spec.filename,
                revision=GGUF_MODEL_REVISION,
                local_dir=str(GGUF_CACHE_DIR),
            )
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            outcome["error"] = exc

    worker = threading.Thread(target=run, name=f"gguf-download-{spec.filename}", daemon=True)
    with _DOWNLOADS_LOCK:
        _DOWNLOADS[spec.filename] = (worker, outcome)
    worker.start()
    return _wait_download(worker, outcome, cancel_token)


def _wait_download(
    worker: threading.Thread,
    outcome: dict[str, object],
    cancel_token: CancellationToken | None,
) -> Path:
    while worker.is_alive():
        if cancel_token is not None and cancel_token.wait(0.25):
            raise OperationCancelledError()
        worker.join(0.25 if cancel_token is None else 0)
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return Path(str(outcome["path"]))


def ensure_gguf_models(
    cancel_token: CancellationToken | None = None,
) -> dict[str, Path]:
    """Return verified GGUF paths, downloading the pinned files when necessary."""
    GGUF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    model_paths = {key: GGUF_CACHE_DIR / spec.filename for key, spec in GGUF_MODEL_FILES.items()}

    for key, spec in GGUF_MODEL_FILES.items():
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        path = model_paths[key]
        if path.exists():
            EventBus.emit("model_load_progress", {"message": f"Verifica {spec.filename}..."})
            if _is_verified(path, spec, cancel_token):
                continue
            logger.warning("GGUF incompleto o diverso dalla revisione pinnata, riscarico: %s", path)
            try:
                path.unlink()
                _marker_path(path).unlink(missing_ok=True)
            except OSError as exc:
                raise ModelLoadError(GGUF_MODEL_ID, f"Impossibile rimuovere {path}: {exc}") from exc

        EventBus.emit("model_load_progress", {"message": f"Scaricamento {spec.filename}..."})
        try:
            downloaded = _download(spec, cancel_token)
            if downloaded != path:
                shutil.copy2(downloaded, path)
        except (ModelLoadError, OperationCancelledError):
            raise
        except Exception as exc:
            raise ModelLoadError(
                GGUF_MODEL_ID, f"Impossibile scaricare {spec.filename}: {exc}"
            ) from exc
        if not _is_verified(path, spec, cancel_token):
            raise ModelLoadError(
                GGUF_MODEL_ID, f"{spec.filename} non corrisponde all'hash SHA-256 atteso"
            )

    return model_paths
