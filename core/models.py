"""Modelli dati dell'applicazione GLM OCR (indipendenti da Qt)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Sequence

PDF_PAGE_MARKER = "--- Pagina {number} ---"


def combine_pdf_pages(pages: Sequence[str]) -> str:
    """Return the single human-readable text used for a multi-page document."""
    if len(pages) == 1:
        return pages[0]
    return "\n\n".join(
        f"{PDF_PAGE_MARKER.format(number=number)}\n{text}"
        for number, text in enumerate(pages, start=1)
    )


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

    ``pages`` contiene il testo di ogni pagina per i PDF ed è vuoto per le
    immagini. GLM-OCR via llama.cpp non espone una confidenza calibrata, quindi
    il risultato non ne contiene una.
    """

    text: str = ""
    pages: tuple[str, ...] = ()
    processing_time_ms: float = 0.0


@dataclass
class OCRTask:
    """Task OCR singolo rappresentante un'immagine da elaborare."""

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    image_path: Path = field(default_factory=Path)
    status: TaskStatus = TaskStatus.PENDING


@dataclass
class BatchOCRJob:
    """Job batch contenente più task OCR da elaborare sequenzialmente."""

    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    tasks: list[OCRTask] = field(default_factory=list)
    status: JobStatus = JobStatus.PENDING

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)

    @property
    def total_count(self) -> int:
        return len(self.tasks)


@dataclass(frozen=True)
class BackendStatus:
    """Esito del rilevamento del runtime SYCL di llama.cpp."""

    available: bool
    label: str
