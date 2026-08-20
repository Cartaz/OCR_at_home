"""Regressioni di concorrenza per ProcessManager."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from core.exceptions import BatchProcessingError
from core.models import JobStatus, OCRResult
from core.process_manager import ProcessManager


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


class BlockingEngine:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def process_image(self, _path: Path, **_kwargs: object) -> OCRResult:
        self.started.set()
        self.release.wait(timeout=3)
        return OCRResult(text="ok", confidence=0.9)


def test_cancel_active_batch_when_no_active_job() -> None:
    engine = BlockingEngine()
    manager = ProcessManager(engine)  # type: ignore[arg-type]
    manager.cancel_active_batch()
    assert manager.active_job_id is None
    manager.shutdown()


def test_submit_batch_creates_correct_task_count() -> None:
    engine = BlockingEngine()
    manager = ProcessManager(engine)  # type: ignore[arg-type]
    job = manager.submit_batch([Path(f"img{i}.png") for i in range(5)])
    try:
        assert engine.started.wait(timeout=1)
        assert job.total_count == 5
        assert len(job.tasks) == 5
        assert manager.active_job_id == job.job_id
    finally:
        manager.cancel_active_batch()
        engine.release.set()
        assert _wait_until(lambda: manager.active_job_id is None)
        manager.shutdown()


def test_cancelled_job_stays_active_until_worker_really_exits() -> None:
    engine = BlockingEngine()
    manager = ProcessManager(engine)  # type: ignore[arg-type]
    job = manager.submit_batch([Path("a.png")])
    try:
        assert engine.started.wait(timeout=1)
        manager.cancel_batch(job.job_id)
        assert job.status == JobStatus.CANCELLED
        # La cancellazione è una richiesta: la risorsa resta occupata finché
        # il task in corso non restituisce il controllo al manager.
        assert manager.active_job_id == job.job_id
        with pytest.raises(BatchProcessingError):
            manager.submit_batch([Path("b.png")])
    finally:
        engine.release.set()
        assert _wait_until(lambda: manager.active_job_id is None)
        manager.shutdown()


def test_completed_batch_releases_active_job() -> None:
    class FastEngine:
        def process_image(self, _path: Path, **_kwargs: object) -> OCRResult:
            return OCRResult(text="ok", confidence=0.9)

    manager = ProcessManager(FastEngine())  # type: ignore[arg-type]
    job = manager.submit_batch([Path("a.png"), Path("b.png")])
    assert _wait_until(lambda: manager.active_job_id is None)
    assert job.status == JobStatus.COMPLETED
    assert job.completed_count == 2
    manager.shutdown()
