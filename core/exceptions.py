"""Gerarchia delle eccezioni personalizzate per GLM OCR."""

from __future__ import annotations


class OCRError(Exception):
    """Eccezione base per tutti gli errori OCR."""

    def __init__(
        self, message: str, details: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        base = self.message
        if self.details:
            details_str = ", ".join(
                f"{k}={v}" for k, v in self.details.items() if v
            )
            if details_str:
                base += f" [{details_str}]"
        return base


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
        super().__init__(
            msg, details={"image_path": image_path, "reason": reason},
        )
        self.image_path = image_path


class HardwareNotAvailableError(OCRError):
    def __init__(self, device_type: str) -> None:
        super().__init__(
            f"Dispositivo hardware '{device_type}' non disponibile.",
            details={"device_type": device_type},
        )
        self.device_type = device_type


class ModelLoadError(OCRError):
    def __init__(self, model_id: str, reason: str = "") -> None:
        msg = f"Impossibile caricare il modello: {model_id}"
        if reason:
            msg += f" — {reason}"
        super().__init__(
            msg, details={"model_id": model_id, "reason": reason},
        )
        self.model_id = model_id


class BatchProcessingError(OCRError):
    def __init__(self, job_id: str, reason: str = "") -> None:
        msg = f"Job batch '{job_id}' fallito"
        if reason:
            msg += f" — {reason}"
        super().__init__(
            msg, details={"job_id": job_id, "reason": reason},
        )
        self.job_id = job_id


class OperationBusyError(OCRError):
    """Un'altra operazione esclusiva sta già usando il motore."""

    def __init__(self, active_operation: str) -> None:
        super().__init__(
            f"Operazione non disponibile: '{active_operation}' è già in corso.",
            details={"active_operation": active_operation},
        )
        self.active_operation = active_operation


class OperationCancelledError(OCRError):
    """Operazione annullata esplicitamente dall'utente o dallo shutdown."""

    def __init__(self) -> None:
        super().__init__("Operazione annullata.")
