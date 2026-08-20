# ui/styles/components.py
"""Componenti stilistici riutilizzabili per l'interfaccia GLM OCR.

Fornisce funzioni di utilità per la mappatura degli stati ai colori
e alle etichette localizzate.

Functions:
    status_color: Mappa uno stato al colore semantico corrispondente.
    status_label: Mappa uno stato all'etichetta localizzata italiana.
"""

from __future__ import annotations

from config.theme import ThemeColors


def status_color(status: str) -> str:
    """Restituisce il colore semantico per uno stato dell'applicazione.

    Args:
        status: Nome dello stato (es. 'running', 'error').

    Returns:
        Colore esadecimale dal tema Breeze Dark.
    """
    mapping: dict[str, str] = {
        "idle": ThemeColors.STATUS_STOPPED,
        "running": ThemeColors.STATUS_RUNNING,
        "processing": ThemeColors.STATUS_RUNNING,
        "buffering": ThemeColors.STATUS_BUFFERING,
        "error": ThemeColors.STATUS_ERROR,
        "loading_model": ThemeColors.STATUS_LOADING,
        "stopped": ThemeColors.STATUS_STOPPED,
        "completed": ThemeColors.STATUS_COMPLETED,
        "draining": ThemeColors.STATUS_PAUSED,
    }
    return mapping.get(status, ThemeColors.TEXT_SECONDARY)


def status_label(status: str) -> str:
    """Restituisce l'etichetta localizzata per uno stato.

    Args:
        status: Nome dello stato.

    Returns:
        Etichetta in italiano per lo stato.
    """
    mapping: dict[str, str] = {
        "idle": "Pronto",
        "running": "In esecuzione",
        "processing": "Elaborazione OCR...",
        "buffering": "Elaborazione...",
        "error": "Errore",
        "loading_model": "Caricamento modello...",
        "stopped": "Arrestato",
        "completed": "Completato",
        "draining": "Completamento...",
    }
    return mapping.get(status, status)
