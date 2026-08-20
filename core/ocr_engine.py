"""Motore OCR thread-safe basato su llama.cpp."""

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

BACKEND_LLAMA_CPP = OCRDefaults.LLAMA_CPP_DEVICE
BACKEND_LLAMA_CPP_SYCL = OCRDefaults.LLAMA_CPP_SYCL_DEVICE
_SUPPORTED_BACKENDS = {BACKEND_LLAMA_CPP, BACKEND_LLAMA_CPP_SYCL}


class OCREngine:
    """Gestisce lifecycle e accesso esclusivo al backend llama-server."""

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
                "llama-cpp",
                f"Backend non supportato: {device}",
            )
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()

        with self._lifecycle_lock:
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            if self._llama_backend is not None:
                self._shutdown_backend_locked()

            self._device = device
            self._backend = (
                BACKEND_LLAMA_CPP_SYCL
                if device == BACKEND_LLAMA_CPP_SYCL
                else BACKEND_LLAMA_CPP
            )

            backend: Any = None
            try:
                from core.llama_backend import LlamaServerBackend

                backend = LlamaServerBackend(preferred_device=device)
                backend.initialize(cancel_token=cancel_token)
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                # Pubblicare il backend solo dopo startup e cancellation check.
                self._llama_backend = backend
                self._initialized = True
            except Exception as exc:
                # Se la cancellazione/failure avviene dopo che il processo è
                # partito ma prima della pubblicazione, il backend locale deve
                # comunque essere chiuso: altrimenti resta un llama-server orfano.
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
                    "llama-cpp",
                    f"Impossibile inizializzare il backend llama.cpp: {exc}",
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
        # Blocca finché un'eventuale inferenza non ha restituito il controllo.
        # AppController cancella prima il token così l'I/O HTTP viene interrotto.
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
            logger.warning("Errore arresto backend llama.cpp: %s", exc)
