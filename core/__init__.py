# core/__init__.py
"""Pacchetto core dell'applicazione GLM OCR.

Espone l'interfaccia pubblica del livello business logic.
L'unico backend supportato è llama.cpp + SYCL.
"""

from core.app_controller import AppController
from core.event_bus import EventBus
from core.exceptions import (
    BatchProcessingError,
    HardwareNotAvailableError,
    ImageLoadError,
    ModelLoadError,
    OCREngineNotInitializedError,
    OCRError,
)
from core.hardware_detector import HardwareDetector
from core.image_preprocessor import ImagePreprocessor
from core.models import (
    BatchOCRJob,
    HardwareInfo,
    JobStatus,
    OCRResult,
    OCRTask,
    StatusEnum,
    TaskStatus,
)
from core.ocr_engine import OCREngine
from core.process_manager import ProcessManager

__all__ = [
    "AppController",
    "BatchOCRJob",
    "BatchProcessingError",
    "EventBus",
    "HardwareDetector",
    "HardwareInfo",
    "HardwareNotAvailableError",
    "ImageLoadError",
    "ImagePreprocessor",
    "JobStatus",
    "ModelLoadError",
    "OCREngine",
    "OCREngineNotInitializedError",
    "OCRError",
    "OCRResult",
    "OCRTask",
    "ProcessManager",
    "StatusEnum",
    "TaskStatus",
]
