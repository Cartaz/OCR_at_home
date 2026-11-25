"""Data models."""

from core.models import BatchOCRJob, OCRResult, OCRTask, TaskStatus, combine_pdf_pages


def test_batch_job_counts() -> None:
    job = BatchOCRJob(tasks=[
        OCRTask(status=TaskStatus.COMPLETED),
        OCRTask(status=TaskStatus.RUNNING),
        OCRTask(status=TaskStatus.PENDING),
    ])
    assert job.total_count == 3
    assert job.completed_count == 1


def test_ocr_result_has_no_invented_confidence() -> None:
    result = OCRResult(text="testo")
    assert not hasattr(result, "confidence")
    assert result.pages == ()


def test_combined_pdf_text_marks_pages_only_when_needed() -> None:
    assert combine_pdf_pages(["solo"]) == "solo"
    assert combine_pdf_pages(["a", "b"]) == "--- Pagina 1 ---\na\n\n--- Pagina 2 ---\nb"
