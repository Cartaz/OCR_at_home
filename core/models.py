# core/models.py
"""Modelli dati dell'applicazione GLM OCR.

Definisce le dataclass per i risultati OCR, i task, i job batch,
le informazioni hardware e gli enumeratori di stato. Include
StatusEnum per il tracciamento dello stato dell'applicazione,
ispirato al pattern di AllTranscribr. Nessun modello dipende
da moduli Qt.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class StatusEnum(str, Enum):
    """Stato globale dell'applicazione OCR.

    Eredita da str per serializzazione JSON diretta.
    Pattern ispirato ad AllTranscribr.
    """

    IDLE = "idle"
    RUNNING = "running"
    PROCESSING = "processing"
    BUFFERING = "buffering"
    ERROR = "error"
    LOADING_MODEL = "loading_model"
    STOPPED = "stopped"
    COMPLETED = "completed"


class TaskStatus(Enum):
    """Stato di un singolo task OCR."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(Enum):
    """Stato di un job batch OCR."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OCRResult:
    """Risultato di una singola elaborazione OCR.

    ``pages`` contiene il testo grezzo di ogni pagina quando la sorgente è un
    PDF; resta vuoto per immagini normali. Il testo combinato rimane in ``text``
    per compatibilità con il resto del programma.
    """

    text: str = ""
    confidence: float | None = None
    processing_time_ms: float = 0.0
    device_used: str = "CPU"
    pages: list[str] = field(default_factory=list)


@dataclass
class OCRTask:
    """Task OCR singolo rappresentante un'immagine da elaborare."""

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    image_path: Path = field(default_factory=Path)
    status: TaskStatus = TaskStatus.PENDING
    result: OCRResult | None = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class BatchOCRJob:
    """Job batch contenente più task OCR da elaborare sequenzialmente."""

    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    tasks: list[OCRTask] = field(default_factory=list)
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)

    @property
    def total_count(self) -> int:
        return len(self.tasks)


@dataclass
class HardwareInfo:
    """Informazioni su un dispositivo hardware per l'inferenza."""

    device_name: str = ""
    device_type: str = "CPU"
    available: bool = False
    memory_mb: int = 0
