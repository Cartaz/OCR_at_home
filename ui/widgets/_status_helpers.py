# ui/widgets/_status_helpers.py
"""Helper condivisi per la mappatura stati applicazione → indicatori UI.

Le schede OCR e Batch condividono la stessa mappatura tra stati
applicativi (StatusEnum) e stati visivi dell'indicatore. Centralizzare
questa logica evita derive tra le due schede.
"""

from __future__ import annotations

from ui.widgets.status_indicator import StatusIndicator


# Mappa stati applicazione → stato indicatore visivo.
# "draining" è mappato su PAUSED per retrocompatibilità.
STATUS_TO_INDICATOR: dict[str, StatusIndicator.State] = {
    "idle": StatusIndicator.State.IDLE,
    "running": StatusIndicator.State.RUNNING,
    "processing": StatusIndicator.State.RUNNING,
    "buffering": StatusIndicator.State.BUFFERING,
    "error": StatusIndicator.State.ERROR,
    "loading_model": StatusIndicator.State.LOADING,
    "stopped": StatusIndicator.State.STOPPED,
    "completed": StatusIndicator.State.COMPLETED,
    "draining": StatusIndicator.State.PAUSED,
}


def status_to_indicator_state(status: str) -> StatusIndicator.State:
    """Converte uno stato applicazione nello stato dell'indicatore.

    Args:
        status: Nome dello stato applicazione (es. 'running').

    Returns:
        Stato dell'indicatore corrispondente. IDLE se non riconosciuto.
    """
    return STATUS_TO_INDICATOR.get(status, StatusIndicator.State.IDLE)
