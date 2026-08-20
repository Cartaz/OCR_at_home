"""Interfaccia pubblica del core GLM OCR."""

from core.app_controller import AppController
from core.cancellation import CancellationToken
from core.event_bus import EventBus
from core.exceptions import BatchProcessingError, HardwareNotAvailableError, ImageLoadError, ModelLoadError, OCREngineNotInitializedError, OCRError, OperationBusyError, OperationCancelledError
from core.hardware_detector import HardwareDetector
from core.image_preprocessor import ImagePreprocessor
from core.models import BatchOCRJob, HardwareInfo, JobStatus, OCRResult, OCRTask, StatusEnum, TaskStatus
from core.ocr_engine import OCREngine
from core.process_manager import ProcessManager

__all__ = ["AppController", "BatchOCRJob", "BatchProcessingError", "CancellationToken", "EventBus", "HardwareDetector", "HardwareInfo", "HardwareNotAvailableError", "ImageLoadError", "ImagePreprocessor", "JobStatus", "ModelLoadError", "OCREngine", "OCREngineNotInitializedError", "OCRError", "OCRResult", "OCRTask", "OperationBusyError", "OperationCancelledError", "ProcessManager", "StatusEnum", "TaskStatus"]
