"""Gestore robusto dei job OCR batch."""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from config.constants import AppConstants
from core.cancellation import CancellationToken
from core.event_bus import EventBus
from core.exceptions import BatchProcessingError, OperationCancelledError
from core.models import BatchOCRJob, JobStatus, OCRResult, OCRTask, TaskStatus
from core.ocr_engine import OCREngine

logger = logging.getLogger(__name__)


class ProcessManager:
    """Esegue un solo batch alla volta con token di cancellazione per-job."""

    def __init__(
        self,
        engine: OCREngine,
        on_job_finished: Callable[[str], None] | None = None,
    ) -> None:
        self._engine = engine
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr-batch")
        self._jobs: dict[str, BatchOCRJob] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._futures: dict[str, Future[None]] = {}
        self._active_job_id: str | None = None
        self._lock = threading.RLock()
        self._on_job_finished = on_job_finished
        self._shutting_down = False

    def submit_batch(
        self, image_paths: list[Path], *, preprocessing_enabled: bool = True,
    ) -> BatchOCRJob:
        if not image_paths:
            raise BatchProcessingError("", "Il batch è vuoto")
        if len(image_paths) > AppConstants.MAX_BATCH_SIZE:
            raise BatchProcessingError(
                "",
                f"Batch troppo grande: {len(image_paths)} immagini "
                f"(massimo {AppConstants.MAX_BATCH_SIZE})",
            )

        with self._lock:
            if self._shutting_down:
                raise BatchProcessingError("", "ProcessManager in arresto")
            # Un job cancellato resta attivo finché il worker non è realmente
            # uscito. Non si riusa la risorsa prima di quel momento.
            if self._active_job_id is not None:
                raise BatchProcessingError(
                    self._active_job_id,
                    "Un batch è già in esecuzione o in fase di arresto.",
                )

            tasks = [OCRTask(image_path=Path(p), status=TaskStatus.PENDING) for p in image_paths]
            job = BatchOCRJob(
                job_id=uuid.uuid4().hex[:12], tasks=tasks, status=JobStatus.PENDING
            )
            token = CancellationToken()
            self._jobs[job.job_id] = job
            self._tokens[job.job_id] = token
            self._active_job_id = job.job_id

        # Subscribers such as OutputWorkflow must freeze batch policy before the
        # worker is allowed to emit task/completion events.
        EventBus.emit(
            "batch_started",
            {"job_id": job.job_id, "total_tasks": job.total_count},
        )

        try:
            # Keep submit + Future registration under the same lock. A real
            # worker may run immediately, but its final cleanup cannot race the
            # registration and leave a completed Future stranded in _futures.
            with self._lock:
                if self._shutting_down:
                    raise BatchProcessingError(job.job_id, "ProcessManager in arresto")
                future = self._executor.submit(
                    self._execute_batch, job, token, preprocessing_enabled
                )
                self._futures[job.job_id] = future
        except Exception as exc:
            with self._lock:
                if self._active_job_id == job.job_id:
                    self._active_job_id = None
                self._tokens.pop(job.job_id, None)
                self._futures.pop(job.job_id, None)
            job.status = JobStatus.FAILED
            EventBus.emit(
                "batch_failed",
                {"job_id": job.job_id, "error": str(exc)},
            )
            raise

        return job

    def cancel_batch(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            token = self._tokens.get(job_id)
            if job is None or token is None:
                return
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                return
            job.status = JobStatus.CANCELLED
        token.cancel()

    def cancel_active_batch(self) -> None:
        with self._lock:
            job_id = self._active_job_id
        if job_id is not None:
            self.cancel_batch(job_id)

    @property
    def active_job_id(self) -> str | None:
        with self._lock:
            return self._active_job_id

    @property
    def is_active(self) -> bool:
        return self.active_job_id is not None

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                jid: {
                    "status": job.status.value,
                    "completed": job.completed_count,
                    "total": job.total_count,
                }
                for jid, job in self._jobs.items()
            }

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
                for task in job.tasks:
                    if task.status == TaskStatus.PENDING:
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
        except Exception as exc:
            job.status = JobStatus.FAILED
            logger.exception("Errore critico nel batch %s", job.job_id)
            EventBus.emit("batch_failed", {"job_id": job.job_id, "error": str(exc)})
        finally:
            with self._lock:
                if self._active_job_id == job.job_id:
                    self._active_job_id = None
                self._tokens.pop(job.job_id, None)
                self._futures.pop(job.job_id, None)
            if self._on_job_finished is not None:
                try:
                    self._on_job_finished(job.job_id)
                except Exception:
                    logger.exception("Errore callback fine batch")

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
            task.result = result
            task.status = TaskStatus.COMPLETED
            EventBus.emit(
                "batch_task_completed",
                {
                    "job_id": job.job_id,
                    "task_id": task.task_id,
                    "text": result.text,
                    "confidence": result.confidence,
                    "image_path": str(task.image_path),
                },
            )
        except OperationCancelledError:
            task.status = TaskStatus.CANCELLED
            raise
        except Exception as exc:
            task.result = OCRResult(text=f"[Errore: {exc}]", confidence=0.0)
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

    def shutdown(self) -> None:
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True
            tokens = tuple(self._tokens.values())
        for token in tokens:
            token.cancel()
        # wait=True evita di distruggere l'engine mentre il worker lo usa.
        self._executor.shutdown(wait=True, cancel_futures=True)
