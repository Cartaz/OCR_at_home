# core/process_manager.py
"""Gestore dei processi OCR batch per l'applicazione GLM OCR.

Questo modulo gestisce l'esecuzione di job batch contenenti più task
OCR. Coordina l'invio, l'annullamento e il monitoraggio dei job,
comunicando i cambiamenti di stato tramite l'event bus.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from config.constants import AppConstants
from core.event_bus import EventBus
from core.exceptions import BatchProcessingError
from core.models import BatchOCRJob, OCRTask, OCRResult, TaskStatus, JobStatus
from core.ocr_engine import OCREngine

logger = logging.getLogger(__name__)


class ProcessManager:
    """Gestore dei processi OCR batch con esecuzione in thread pool.

    Permette di sottomettere job batch contenenti più immagini, che
    vengono elaborate sequenzialmente in un thread worker. Supporta
    l'annullamento dei job e il monitoraggio dello stato tramite
    l'event bus.

    Attributi:
        _engine: Motore OCR utilizzato per l'elaborazione.
        _executor: Thread pool per l'esecuzione asincrona.
        _jobs: Dizionario job_id → BatchOCRJob.
        _active_job_id: ID del job attualmente in esecuzione, o None.
    """

    def __init__(self, engine: OCREngine) -> None:
        """Inizializza il gestore processi con il motore OCR specificato.

        Args:
            engine: Istanza di OCREngine da utilizzare per l'elaborazione.
        """
        self._engine = engine
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._jobs: dict[str, BatchOCRJob] = {}
        self._active_job_id: str | None = None
        self._cancel_event = threading.Event()

    def submit_batch(self, image_paths: list[Path]) -> BatchOCRJob:
        """Sottomette un nuovo job batch per l'elaborazione OCR.

        Crea un BatchOCRJob con un task per ogni immagine e avvia
        l'elaborazione asincrona in un thread worker.

        Args:
            image_paths: Lista dei percorsi delle immagini da elaborare.

        Returns:
            BatchOCRJob appena creato e sottomesso.

        Raises:
            BatchProcessingError: Se il batch supera il limite massimo.
        """
        if len(image_paths) > AppConstants.MAX_BATCH_SIZE:
            raise BatchProcessingError(
                "", f"Batch troppo grande: {len(image_paths)} immagini "
                f"(massimo {AppConstants.MAX_BATCH_SIZE})"
            )
        # Previene sovrascrittura di un batch attivo
        if self._active_job_id is not None:
            active_job = self._jobs.get(self._active_job_id)
            if active_job and active_job.status in (JobStatus.PENDING, JobStatus.RUNNING):
                raise BatchProcessingError(
                    self._active_job_id,
                    "Un batch e gia in esecuzione. Attendere il completamento o annullarlo."
                )
        tasks = [
            OCRTask(image_path=p, status=TaskStatus.PENDING)
            for p in image_paths
        ]
        job = BatchOCRJob(
            job_id=uuid.uuid4().hex[:12],
            tasks=tasks,
            status=JobStatus.PENDING,
        )
        self._jobs[job.job_id] = job
        self._cancel_event.clear()
        self._active_job_id = job.job_id
        self._executor.submit(self._execute_batch, job)
        EventBus.emit("batch_started", {
            "job_id": job.job_id,
            "total_tasks": job.total_count,
        })
        logger.info(
            "Job batch %s sottomesso: %d immagini",
            job.job_id, job.total_count,
        )
        return job

    def cancel_batch(self, job_id: str) -> None:
        """Richiede l'annullamento di un job batch in esecuzione.

        Args:
            job_id: ID del job da annullare.
        """
        if job_id in self._jobs:
            self._cancel_event.set()
            self._jobs[job_id].status = JobStatus.CANCELLED
            logger.info("Annullamento richiesto per job %s", job_id)

    def cancel_active_batch(self) -> None:
        """Annulla il job batch attualmente in esecuzione, se presente.

        Metodo di convenienza che evita al chiamante di dover accedere
        ad attributi privati per conoscere l'ID del job attivo.
        """
        if self._active_job_id is not None:
            self.cancel_batch(self._active_job_id)

    @property
    def active_job_id(self) -> str | None:
        """ID del job batch attualmente in esecuzione, o None."""
        return self._active_job_id

    def get_status(self) -> dict[str, Any]:
        """Restituisce lo stato di tutti i job gestiti.

        Returns:
            Dizionario con lo stato di ogni job.
        """
        return {
            jid: {
                "status": job.status.value,
                "completed": job.completed_count,
                "total": job.total_count,
            }
            for jid, job in self._jobs.items()
        }

    def _execute_batch(self, job: BatchOCRJob) -> None:
        """Esegue un job batch elaborando i task sequenzialmente.

        Args:
            job: Job batch da eseguire.
        """
        job.status = JobStatus.RUNNING
        for task in job.tasks:
            if self._cancel_event.is_set():
                task.status = TaskStatus.CANCELLED
                continue
            self._process_task(task, job.job_id)
        if not self._cancel_event.is_set():
            failed = sum(1 for t in job.tasks if t.status == TaskStatus.FAILED)
            job.status = (
                JobStatus.COMPLETED if failed == 0
                else JobStatus.FAILED
            )
        EventBus.emit("batch_completed", {"job_id": job.job_id})
        self._active_job_id = None
        logger.info(
            "Job batch %s completato: %d/%d task OK",
            job.job_id, job.completed_count, job.total_count,
        )

    def _process_task(self, task: OCRTask, job_id: str) -> None:
        """Elabora un singolo task OCR all'interno di un job batch.

        Args:
            task: Task OCR da elaborare.
            job_id: ID del job di appartenenza.
        """
        task.status = TaskStatus.RUNNING
        try:
            result = self._engine.process_image(task.image_path)
            task.result = result
            task.status = TaskStatus.COMPLETED
            # Emetti evento con il testo del task completato
            # per permettere alla UI di mostrare il risultato
            EventBus.emit("batch_task_completed", {
                "job_id": job_id,
                "task_id": task.task_id,
                "text": result.text,
                "confidence": result.confidence,
                "image_path": str(task.image_path),
            })
        except Exception as exc:
            logger.error("Task %s fallito: %s", task.task_id, exc)
            task.result = OCRResult(text=f"[Errore: {exc}]", confidence=0.0)
            task.status = TaskStatus.FAILED
            # Emetti evento di fallimento per mostrare l'errore nella UI
            EventBus.emit("batch_task_failed", {
                "job_id": job_id,
                "task_id": task.task_id,
                "error": str(exc),
                "image_path": str(task.image_path),
            })
        # Aggiorna il contatore di avanzamento del job. Il job è sempre
        # presente in _jobs (viene inserito in submit_batch), ma usiamo
        # una guardia per evitare KeyError in caso di race condition con
        # la cancellazione.
        job = self._jobs.get(job_id)
        if job is None:
            return
        completed = sum(
            1 for t in job.tasks
            if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
        )
        EventBus.emit("batch_progress", {
            "job_id": job_id,
            "completed": completed,
            "total": job.total_count,
        })

    def shutdown(self) -> None:
        """Arresta il gestore processi e rilascia le risorse."""
        self._cancel_event.set()
        self._executor.shutdown(wait=False)
        logger.info("ProcessManager arrestato.")
