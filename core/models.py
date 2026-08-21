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
    """Stato di un job OCR batch."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OCRResult:
    """Risultato di una singola elaborazione OCR.

    Attributi:
        text: Testo estratto dall'immagine.
        confidence: Confidenza reale fornita dal backend, oppure ``None`` quando
            il backend non espone una misura affidabile. GLM-OCR via llama.cpp
            attualmente non fornisce questo dato.
        processing_time_ms: Tempo di elaborazione in millisecondi.
        device_used: Dispositivo utilizzato.
    """

    text: str = ""
    confidence: float | None = None
    processing_time_ms: float = 0.0
    device_used: str = "CPU"


@dataclass
class OCRTask:
    """Task OCR singolo rappresentante un'immagine da elaborare.

    Attributi:
        task_id: Identificativo univoco del task.
        image_path: Percorso del file immagine.
        status: Stato corrente del task.
        result: Risultato OCR, None se non ancora completato.
        created_at: Timestamp di creazione del task.
    """

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    image_path: Path = field(default_factory=Path)
    status: TaskStatus = TaskStatus.PENDING
    result: OCRResult | None = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class BatchOCRJob:
    """Job batch contenente più task OCR da elaborare sequenzialmente.

    Attributi:
        job_id: Identificativo univoco del job.
        tasks: Lista di task OCR componenti il batch.
        status: Stato corrente del job.
        created_at: Timestamp di creazione del job.
    """

    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    tasks: list[OCRTask] = field(default_factory=list)
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def completed_count(self) -> int:
        """Numero di task completati nel batch."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)

    @property
    def total_count(self) -> int:
        """Numero totale di task nel batch."""
        return len(self.tasks)


@dataclass
class HardwareInfo:
    """Informazioni su un dispositivo hardware per l'inferenza."""

    device_name: str = ""
    device_type: str = "CPU"
    available: bool = False
    memory_mb: int = 0
