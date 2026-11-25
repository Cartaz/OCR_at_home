"""Motore OCR thread-safe basato esclusivamente su llama.cpp + SYCL."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from core.cancellation import CancellationToken
from core.exceptions import (
    ModelLoadError,
    OCREngineNotInitializedError,
    OperationBusyError,
    OperationCancelledError,
)
from core.llama_backend import LlamaServerBackend
from core.models import OCRResult

logger = logging.getLogger(__name__)


class OCREngine:
    """Own lifecycle of and exclusive access to the SYCL backend.

    ``_lifecycle_lock`` only guards swapping the backend reference: it is never
    held during model download or server startup, so state queries from the GUI
    thread stay instantaneous while a load is running. ``_generation`` makes a
    load that finishes after :meth:`shutdown` discard its own server instead of
    installing it.
    """

    def __init__(
        self,
        backend_factory: Callable[[], LlamaServerBackend] = LlamaServerBackend,
    ) -> None:
        self._backend_factory = backend_factory
        self._backend: LlamaServerBackend | None = None
        self._generation = 0
        self._lifecycle_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def is_initialized(self) -> bool:
        with self._lifecycle_lock:
            return self._backend is not None

    def initialize(self, *, cancel_token: CancellationToken | None = None) -> None:
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        with self._lifecycle_lock:
            previous = self._backend
            self._backend = None
            self._generation += 1
            generation = self._generation
        if previous is not None:
            self._stop_backend(previous)

        backend = self._backend_factory()
        try:
            backend.initialize(cancel_token=cancel_token)
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
        except Exception as exc:
            self._stop_backend(backend)
            if isinstance(exc, (ModelLoadError, OperationCancelledError)):
                raise
            raise ModelLoadError(
                "llama-server",
                f"Impossibile inizializzare il backend SYCL: {exc}",
            ) from exc

        with self._lifecycle_lock:
            if generation == self._generation:
                self._backend = backend
                return
        # shutdown() or another initialize() superseded this load meanwhile.
        self._stop_backend(backend)
        raise OperationCancelledError()

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
                backend = self._backend
            if backend is None:
                raise OCREngineNotInitializedError()
            return backend.process_image(
                Path(image_path),
                mode=mode,
                cancel_token=cancel_token,
                preprocessing_enabled=preprocessing_enabled,
            )
        finally:
            self._inference_lock.release()

    def shutdown(self) -> None:
        """Release the backend; waits for an in-flight inference to return."""
        with self._inference_lock:
            with self._lifecycle_lock:
                backend = self._backend
                self._backend = None
                self._generation += 1
            if backend is not None:
                self._stop_backend(backend)

    @staticmethod
    def _stop_backend(backend: LlamaServerBackend) -> None:
        try:
            backend.shutdown()
        except Exception as exc:
            logger.warning("Errore arresto backend llama.cpp SYCL: %s", exc)
