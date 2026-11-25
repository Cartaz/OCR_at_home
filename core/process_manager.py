"""Gestore robusto dei job OCR batch."""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from config.constants import AppMeta
from core.cancellation import CancellationToken
from core.event_bus import EventBus
from core.exceptions import BatchProcessingError, OperationCancelledError
from core.models import BatchOCRJob, JobStatus, OCRTask, TaskStatus
from core.ocr_engine import OCREngine

logger = logging.getLogger(__name__)


class ProcessManager:
    """Esegue un solo batch alla volta con token di cancellazione per-job.

    Only the active job is retained: results travel through events and are not
    accumulated here for the whole session.
    """

    def __init__(
        self,
        engine: OCREngine,
        on_job_finished: Callable[[str], None] | None = None,
    ) -> None:
        self._engine = engine
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr-batch")
        self._active_job: BatchOCRJob | None = None
        self._active_token: CancellationToken | None = None
        self._lock = threading.RLock()
        self._on_job_finished = on_job_finished
        self._shutting_down = False
        self._idle = threading.Event()
        self._idle.set()

    def submit_batch(
        self, image_paths: list[Path], *, preprocessing_enabled: bool = True,
    ) -> BatchOCRJob:
        if not image_paths:
            raise BatchProcessingError("", "Il batch è vuoto")
        if len(image_paths) > AppMeta.MAX_BATCH_SIZE:
            raise BatchProcessingError(
                "",
                f"Batch troppo grande: {len(image_paths)} immagini "
                f"(massimo {AppMeta.MAX_BATCH_SIZE})",
            )

        with self._lock:
            if self._shutting_down:
                raise BatchProcessingError("", "ProcessManager in arresto")
            # Un job cancellato resta attivo finché il worker non è realmente
            # uscito. Non si riusa la risorsa prima di quel momento.
            if self._active_job is not None:
                raise BatchProcessingError(
                    self._active_job.job_id,
                    "Un batch è già in esecuzione o in fase di arresto.",
                )
            tasks = [OCRTask(image_path=Path(p)) for p in image_paths]
            job = BatchOCRJob(job_id=uuid.uuid4().hex[:12], tasks=tasks)
            token = CancellationToken()
            self._active_job = job
            self._active_token = token
            self._idle.clear()

        # Subscribers such as OutputWorkflow must freeze batch policy before the
        # worker is allowed to emit task/completion events.
        EventBus.emit(
            "batch_started",
            {"job_id": job.job_id, "total_tasks": job.total_count},
        )

        try:
            with self._lock:
                if self._shutting_down:
                    raise BatchProcessingError(job.job_id, "ProcessManager in arresto")
                self._executor.submit(self._execute_batch, job, token, preprocessing_enabled)
        except Exception as exc:
            self._release(job)
            job.status = JobStatus.FAILED
            EventBus.emit("batch_failed", {"job_id": job.job_id, "error": str(exc)})
            raise

        return job

    def _release(self, job: BatchOCRJob) -> None:
        with self._lock:
            if self._active_job is job:
                self._active_job = None
                self._active_token = None
                self._idle.set()

    def cancel_active_batch(self) -> None:
        with self._lock:
            job = self._active_job
            token = self._active_token
            if job is None or token is None:
                return
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                return
            job.status = JobStatus.CANCELLED
        token.cancel()

    @property
    def active_job_id(self) -> str | None:
        with self._lock:
            return None if self._active_job is None else self._active_job.job_id

    def _execute_batch(
        self, job: BatchOCRJob, token: CancellationToken, preprocessing_enabled: bool,
    ) -> None:
        try:
            job.status = JobStatus.CANCELLED if token.is_cancelled else JobStatus.RUNNING
            for task in job.tasks:
                if token.is_cancelled:
                    break
                self._process_task(
                    task, job, token, preprocessing_enabled=preprocessing_enabled
                )

            if token.is_cancelled:
                self._emit_cancelled(job)
                return

            failed = sum(1 for task in job.tasks if task.status == TaskStatus.FAILED)
            if failed:
                job.status = JobStatus.FAILED
                EventBus.emit(
                    "batch_failed",
                    {
                        "job_id": job.job_id,
                        "error": f"{failed} task falliti su {job.total_count}",
                        "failed": failed,
                        "total": job.total_count,
                    },
                )
            else:
                job.status = JobStatus.COMPLETED
                EventBus.emit(
                    "batch_completed",
                    {
                        "job_id": job.job_id,
                        "completed": job.completed_count,
                        "total": job.total_count,
                    },
                )
        except OperationCancelledError:
            self._emit_cancelled(job)
        except Exception as exc:
            job.status = JobStatus.FAILED
            logger.exception("Errore critico nel batch %s", job.job_id)
            EventBus.emit("batch_failed", {"job_id": job.job_id, "error": str(exc)})
        finally:
            self._release(job)
            if self._on_job_finished is not None:
                try:
                    self._on_job_finished(job.job_id)
                except Exception:
                    logger.exception("Errore callback fine batch")

    def _emit_cancelled(self, job: BatchOCRJob) -> None:
        for task in job.tasks:
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                task.status = TaskStatus.CANCELLED
        job.status = JobStatus.CANCELLED
        EventBus.emit(
            "batch_cancelled",
            {
                "job_id": job.job_id,
                "completed": self._terminal_task_count(job),
                "total": job.total_count,
            },
        )

    def _process_task(
        self,
        task: OCRTask,
        job: BatchOCRJob,
        token: CancellationToken,
        *,
        preprocessing_enabled: bool,
    ) -> None:
        token.raise_if_cancelled()
        task.status = TaskStatus.RUNNING
        try:
            result = self._engine.process_image(
                task.image_path,
                mode="batch",
                cancel_token=token,
                preprocessing_enabled=preprocessing_enabled,
            )
            token.raise_if_cancelled()
            task.status = TaskStatus.COMPLETED
            EventBus.emit(
                "batch_task_completed",
                {
                    "job_id": job.job_id,
                    "task_id": task.task_id,
                    "text": result.text,
                    "pages": list(result.pages),
                    "image_path": str(task.image_path),
                },
            )
        except OperationCancelledError:
            task.status = TaskStatus.CANCELLED
            raise
        except Exception as exc:
            task.status = TaskStatus.FAILED
            EventBus.emit(
                "batch_task_failed",
                {
                    "job_id": job.job_id,
                    "task_id": task.task_id,
                    "error": str(exc),
                    "image_path": str(task.image_path),
                },
            )

        EventBus.emit(
            "batch_progress",
            {
                "job_id": job.job_id,
                "completed": self._terminal_task_count(job),
                "total": job.total_count,
            },
        )

    @staticmethod
    def _terminal_task_count(job: BatchOCRJob) -> int:
        return sum(
            1
            for task in job.tasks
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        )

    def shutdown(self, wait_seconds: float = 15.0) -> None:
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True
            token = self._active_token
        if token is not None:
            token.cancel()
        # Wait (bounded) so the engine is not torn down under a cooperative
        # worker; a worker stuck in non-cancellable work must not block exit.
        self._executor.shutdown(wait=False, cancel_futures=True)
        if not self._idle.wait(timeout=wait_seconds):
            logger.warning("Worker batch non terminato entro %.0f s allo shutdown", wait_seconds)
