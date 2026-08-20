"""Motore OCR thread-safe basato esclusivamente su llama.cpp + SYCL."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from config.constants import AppConstants, OCRDefaults
from core.cancellation import CancellationToken
from core.exceptions import (
    ModelLoadError,
    OCREngineNotInitializedError,
    OperationBusyError,
    OperationCancelledError,
)
from core.models import OCRResult

logger = logging.getLogger(__name__)

BACKEND_LLAMA_CPP_SYCL = OCRDefaults.LLAMA_CPP_SYCL_DEVICE
_SUPPORTED_BACKENDS = {BACKEND_LLAMA_CPP_SYCL}


class OCREngine:
    """Gestisce lifecycle e accesso esclusivo al backend SYCL."""

    def __init__(self) -> None:
        self._initialized = False
        self._device = AppConstants.LLAMA_CPP_SYCL_DEVICE
        self._backend = BACKEND_LLAMA_CPP_SYCL
        self._llama_backend: Any = None
        self._lifecycle_lock = threading.RLock()
        self._inference_lock = threading.Lock()

    @property
    def is_initialized(self) -> bool:
        with self._lifecycle_lock:
            return self._initialized

    @property
    def device(self) -> str:
        with self._lifecycle_lock:
            return self._device

    @property
    def backend(self) -> str:
        with self._lifecycle_lock:
            return self._backend

    def initialize(
        self,
        device: str = AppConstants.LLAMA_CPP_SYCL_DEVICE,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        if device not in _SUPPORTED_BACKENDS:
            raise ModelLoadError(
                "llama-server",
                f"Backend non supportato: {device}. GLM OCR è configurato SYCL-only.",
            )
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()

        with self._lifecycle_lock:
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            if self._llama_backend is not None:
                self._shutdown_backend_locked()

            self._device = AppConstants.LLAMA_CPP_SYCL_DEVICE
            self._backend = BACKEND_LLAMA_CPP_SYCL

            backend: Any = None
            try:
                from core.llama_backend import LlamaServerBackend

                backend = LlamaServerBackend(
                    preferred_device=AppConstants.LLAMA_CPP_SYCL_DEVICE
                )
                backend.initialize(cancel_token=cancel_token)
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                self._llama_backend = backend
                self._initialized = True
            except Exception as exc:
                if backend is not None:
                    try:
                        backend.shutdown()
                    except Exception:
                        logger.exception("Errore cleanup backend dopo initialize fallita")
                self._initialized = False
                self._llama_backend = None
                if isinstance(exc, (ModelLoadError, OperationCancelledError)):
                    raise
                raise ModelLoadError(
                    "llama-server",
                    f"Impossibile inizializzare il backend SYCL: {exc}",
                ) from exc

    def process_image(
        self,
        image_path: Path,
        *,
        mode: str = "single",
        cancel_token: CancellationToken | None = None,
        preprocessing_enabled: bool = True,
    ) -> OCRResult:
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if not self._inference_lock.acquire(blocking=False):
            raise OperationBusyError("inference")
        try:
            with self._lifecycle_lock:
                if not self._initialized or self._llama_backend is None:
                    raise OCREngineNotInitializedError()
                backend = self._llama_backend
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            return backend.process_image(
                Path(image_path),
                mode=mode,
                cancel_token=cancel_token,
                preprocessing_enabled=preprocessing_enabled,
            )
        finally:
            self._inference_lock.release()

    def shutdown(self) -> None:
        with self._inference_lock:
            with self._lifecycle_lock:
                self._shutdown_backend_locked()
                self._initialized = False

    def _shutdown_backend_locked(self) -> None:
        backend = self._llama_backend
        self._llama_backend = None
        self._initialized = False
        if backend is None:
            return
        try:
            backend.shutdown()
        except Exception as exc:
            logger.warning("Errore arresto backend llama.cpp SYCL: %s", exc)
