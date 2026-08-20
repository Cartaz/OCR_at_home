# core/ocr_engine.py
"""Motore OCR basato su GLM-OCR con backend llama.cpp + SYCL.

Questo modulo implementa la logica core dell'OCR usando esclusivamente
llama.cpp con modello GGUF quantizzato tramite llama-server.
Supporta GPU offload completo via SYCL (nativo Intel Arc) con
fallback progressivo: full GPU → partial GPU → CPU-only.

Il modulo è indipendente da Qt e non importa mai moduli PySide6.
Non dipende da PyTorch, OpenVINO o HuggingFace Transformers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config.constants import AppConstants, OCRDefaults
from core.exceptions import (
    OCREngineNotInitializedError,
    ModelLoadError,
)
from core.image_preprocessor import ImagePreprocessor
from core.models import OCRResult

logger = logging.getLogger(__name__)

# Backend disponibili (solo llama.cpp, in due varianti)
BACKEND_LLAMA_CPP = OCRDefaults.LLAMA_CPP_DEVICE
BACKEND_LLAMA_CPP_SYCL = OCRDefaults.LLAMA_CPP_SYCL_DEVICE


class OCREngine:
    """Motore OCR con modello GLM-OCR e backend llama.cpp + SYCL.

    Gestisce il ciclo di vita del modello GLM-OCR in formato GGUF:
    caricamento tramite LlamaServerBackend, inferenza via API REST
    e rilascio delle risorse. Supporta GPU offload completo via SYCL.

    L'unico backend supportato è llama.cpp con modello GGUF
    quantizzato (Q8_0 raccomandato).
    """

    def __init__(self) -> None:
        """Inizializza il motore OCR in stato non inizializzato."""
        self._initialized: bool = False
        self._device: str = AppConstants.LLAMA_CPP_SYCL_DEVICE
        self._preprocessor: ImagePreprocessor = ImagePreprocessor()
        self._backend: str = BACKEND_LLAMA_CPP_SYCL
        self._llama_backend: Any = None  # LlamaServerBackend (lazy import)

    @property
    def is_initialized(self) -> bool:
        """Indica se il motore è stato inizializzato e pronto per l'uso."""
        return self._initialized

    @property
    def device(self) -> str:
        """Dispositivo di inferenza corrente (llama-cpp / llama-cpp-sycl)."""
        return self._device

    @property
    def backend(self) -> str:
        """Backend di inferenza utilizzato ('llama-cpp' o 'llama-cpp-sycl')."""
        return self._backend

    def initialize(self, device: str = AppConstants.LLAMA_CPP_SYCL_DEVICE) -> None:
        """Inizializza il motore OCR caricando il modello GGUF tramite llama.cpp.

        Usa llama-server con modello GGUF quantizzato. Supporta SYCL
        per accelerazione GPU Intel Arc e Vulkan come fallback.

        Args:
            device: Backend di inferenza:
                - "llama-cpp-sycl": SYCL per GPU Intel Arc (raccomandato)
                - "llama-cpp": Backend generico (Vulkan o CPU)

        Raises:
            ModelLoadError: Se il modello non può essere caricato.
        """
        logger.info("Inizializzazione motore OCR — device: %s", device)
        self._device = device

        if device == BACKEND_LLAMA_CPP_SYCL:
            self._backend = BACKEND_LLAMA_CPP_SYCL
        else:
            self._backend = BACKEND_LLAMA_CPP

        try:
            from core.llama_backend import LlamaServerBackend
            self._llama_backend = LlamaServerBackend()
            self._llama_backend.initialize()
            self._initialized = True

            gpu_layers = self._llama_backend.gpu_layers
            gpu_backend = self._llama_backend.gpu_backend
            gpu_info = ""
            if gpu_layers > 0:
                gpu_info = (
                    f", GPU offload: {gpu_layers} layer "
                    f"({gpu_backend.upper()})"
                )
            logger.info(
                "Motore OCR inizializzato (backend: llama.cpp, device: %s%s)",
                "GPU" if gpu_layers > 0 else "CPU ottimizzata",
                gpu_info,
            )
        except Exception as exc:
            raise ModelLoadError(
                "llama-cpp",
                f"Impossibile inizializzare il backend llama.cpp: {exc}\n"
                f"Assicurati che llama-server sia installato:\n"
                f"  sudo pacman -S llama.cpp",
            ) from exc

    def process_image(self, image_path: Path) -> OCRResult:
        """Elabora un'immagine o un PDF tramite llama-server per l'OCR.

        Args:
            image_path: Percorso del file immagine o PDF da elaborare.

        Returns:
            OCRResult con testo estratto, confidenza e tempi.

        Raises:
            OCREngineNotInitializedError: Se il motore non è inizializzato.
            ImageLoadError: Se l'immagine non può essere caricata.
        """
        if not self._initialized:
            raise OCREngineNotInitializedError()

        if self._llama_backend is not None:
            return self._llama_backend.process_image(image_path)

        raise OCREngineNotInitializedError()

    def shutdown(self) -> None:
        """Rilascia le risorse del motore OCR e ferma llama-server."""
        if self._llama_backend is not None:
            try:
                self._llama_backend.shutdown()
            except Exception as exc:
                logger.warning("Errore arresto backend llama.cpp: %s", exc)
            self._llama_backend = None

        self._initialized = False
        logger.info("Motore OCR arrestato, risorse rilasciate.")
