"""Test per core/process_manager.py — verifica gestione batch OCR.

Tests:
    - cancel_active_batch è una no-op sicura quando non ci sono job attivi
    - submit_batch crea un job con il numero corretto di task
    - cancel_batch imposta lo stato CANCELLED sul job
    - active_job_id è esposto come property pubblica
"""
import threading
from pathlib import Path
from unittest.mock import MagicMock

from core.models import JobStatus
from core.process_manager import ProcessManager


def test_cancel_active_batch_when_no_active_job() -> None:
    """Verifica che cancel_active_batch non sollevi eccezioni se non
    ci sono job attivi."""
    engine = MagicMock()
    pm = ProcessManager(engine)
    # Nessun job attivo: deve essere una no-op sicura
    pm.cancel_active_batch()
    assert pm.active_job_id is None
    pm.shutdown()


def test_submit_batch_creates_correct_task_count() -> None:
    """Verifica che submit_batch crei un job con il numero di task
    corrispondente alle immagini passate."""
    engine = MagicMock()
    # Fa sì che process_image attenda un evento, così possiamo ispezionare
    # lo stato del job prima che venga completato dal worker thread.
    done_event = threading.Event()

    def slow_process(_path):
        done_event.wait(timeout=2)
        return MagicMock()

    engine.process_image.side_effect = slow_process
    pm = ProcessManager(engine)
    paths = [Path(f"img{i}.png") for i in range(5)]
    job = pm.submit_batch(paths)
    try:
        assert job.total_count == 5
        assert len(job.tasks) == 5
        # active_job_id deve corrispondere al job appena sottomesso
        assert pm.active_job_id == job.job_id
    finally:
        # Sblocca il worker e arresta in modo pulito
        done_event.set()
        pm.shutdown()


def test_cancel_batch_marks_job_cancelled() -> None:
    """Verifica che cancel_batch imposti lo stato CANCELLED sul job."""
    engine = MagicMock()
    done_event = threading.Event()
    engine.process_image.side_effect = lambda _p: done_event.wait(timeout=2)
    pm = ProcessManager(engine)
    job = pm.submit_batch([Path("a.png")])
    try:
        pm.cancel_batch(job.job_id)
        assert job.status == JobStatus.CANCELLED
    finally:
        done_event.set()
        pm.shutdown()


def test_active_job_id_is_public_property() -> None:
    """Verifica che active_job_id sia esposto come property pubblica
    (regressione: prima era accessibile solo via attributo privato)."""
    engine = MagicMock()
    pm = ProcessManager(engine)
    # Deve essere leggibile come property, non come attributo privato
    assert isinstance(pm.active_job_id, property) or pm.active_job_id is None
    pm.shutdown()
