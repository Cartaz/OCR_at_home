"""Gerarchia delle eccezioni personalizzate per GLM OCR."""

from __future__ import annotations


class OCRError(Exception):
    """Eccezione base per tutti gli errori OCR; il messaggio è già per l'utente."""


class OCREngineNotInitializedError(OCRError):
    def __init__(self) -> None:
        super().__init__(
            "Il motore OCR non è stato inizializzato. "
            "Attendere il caricamento del modello prima di processare immagini."
        )


class ImageLoadError(OCRError):
    def __init__(self, image_path: str, reason: str = "") -> None:
        msg = f"Impossibile caricare l'immagine: {image_path}"
        if reason:
            msg += f" — {reason}"
        super().__init__(msg)
        self.image_path = image_path


class ModelLoadError(OCRError):
    def __init__(self, model_id: str, reason: str = "") -> None:
        msg = f"Impossibile caricare il modello: {model_id}"
        if reason:
            msg += f" — {reason}"
        super().__init__(msg)
        self.model_id = model_id


class OCRProcessingError(OCRError):
    """Il backend era pronto ma l'elaborazione di un documento è fallita."""

    def __init__(self, document: str, reason: str = "") -> None:
        msg = f"OCR fallito per {document}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.document = document


class BatchProcessingError(OCRError):
    def __init__(self, job_id: str, reason: str = "") -> None:
        msg = f"Job batch '{job_id}' fallito" if job_id else "Batch non avviato"
        if reason:
            msg += f" — {reason}"
        super().__init__(msg)
        self.job_id = job_id


class OperationBusyError(OCRError):
    """Un'altra operazione esclusiva sta già usando il motore."""

    def __init__(self, active_operation: str) -> None:
        super().__init__(
            f"Operazione non disponibile: '{active_operation}' è già in corso."
        )
        self.active_operation = active_operation


class OperationCancelledError(OCRError):
    """Operazione annullata esplicitamente dall'utente o dallo shutdown."""

    def __init__(self) -> None:
        super().__init__("Operazione annullata.")
