"""Test per core/models.py — verifica modelli dati.

Tests:
    - StatusEnum ha tutti gli stati richiesti
    - BatchOCRJob calcola correttamente completed_count e total_count
    - OCRResult non inventa una confidenza quando il backend non la fornisce
"""
from core.models import (
    BatchOCRJob,
    JobStatus,
    OCRResult,
    OCRTask,
    StatusEnum,
    TaskStatus,
)


def test_status_enum_has_required_states() -> None:
    """Verifica che StatusEnum contenga gli stati necessari."""
    required = ["IDLE", "RUNNING", "PROCESSING", "ERROR", "STOPPED", "COMPLETED"]
    for state in required:
        assert hasattr(StatusEnum, state), f"Stato mancante: {state}"


def test_batch_job_counts() -> None:
    """Verifica il calcolo dei conteggi in BatchOCRJob."""
    job = BatchOCRJob(tasks=[
        OCRTask(status=TaskStatus.COMPLETED),
        OCRTask(status=TaskStatus.RUNNING),
        OCRTask(status=TaskStatus.PENDING),
    ])
    assert job.total_count == 3
    assert job.completed_count == 1


def test_ocr_result_confidence_is_unknown_by_default() -> None:
    result = OCRResult(text="testo")
    assert result.confidence is None
