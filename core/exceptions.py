# core/exceptions.py
"""Gerarchia delle eccezioni personalizzate per GLM OCR.

Definisce eccezioni specifiche per ciascun dominio di errore
dell'applicazione. Ogni eccezione include contesto utile per il
debugging e la gestione dell'errore, con rappresentazioni stringa
che incorporano i dettagli rilevanti.
"""

from __future__ import annotations


class OCRError(Exception):
    """Eccezione base per tutti gli errori OCR.

    Attributi:
        message: Messaggio descrittivo dell'errore.
        details: Dizionario opzionale con dettagli aggiuntivi.
    """

    def __init__(
        self, message: str, details: dict[str, str] | None = None,
    ) -> None:
        """Inizializza l'eccezione OCR.

        Args:
            message: Messaggio descrittivo dell'errore.
            details: Dizionario opzionale con dettagli aggiuntivi.
        """
        super().__init__(message)
        self.message: str = message
        self.details: dict[str, str] = details or {}

    def __str__(self) -> str:
        """Restituisce una rappresentazione stringa con dettagli contestuali.

        Returns:
            Messaggio dell'errore con dettagli aggiuntivi se presenti.
        """
        base = self.message
        if self.details:
            details_str = ", ".join(
                f"{k}={v}" for k, v in self.details.items() if v
            )
            if details_str:
                base += f" [{details_str}]"
        return base


class OCREngineNotInitializedError(OCRError):
    """Eccezione sollevata quando il motore OCR non è stato inizializzato.

    Si verifica quando si tenta di usare il motore senza aver chiamato
    OCREngine.initialize() o quando l'inizializzazione è fallita.
    """

    def __init__(self) -> None:
        """Inizializza l'eccezione con messaggio specifico."""
        super().__init__(
            "Il motore OCR non è stato inizializzato. "
            "Chiamare OCREngine.initialize() prima di processare immagini.",
        )

    def __str__(self) -> str:
        """Restituisce la rappresentazione stringa dell'errore.

        Returns:
            Messaggio che indica l'engine non inizializzato.
        """
        return self.message


class ImageLoadError(OCRError):
    """Eccezione sollevata quando un'immagine non può essere caricata.

    Attributi:
        image_path: Percorso del file immagine che ha causato l'errore.
    """

    def __init__(self, image_path: str, reason: str = "") -> None:
        """Inizializza l'eccezione con percorso e motivo.

        Args:
            image_path: Percorso del file immagine.
            reason: Motivo opzionale del fallimento.
        """
        msg = f"Impossibile caricare l'immagine: {image_path}"
        if reason:
            msg += f" — {reason}"
        super().__init__(
            msg, details={"image_path": image_path, "reason": reason},
        )
        self.image_path: str = image_path

    def __str__(self) -> str:
        """Restituisce il messaggio con percorso immagine e motivo.

        Returns:
            Messaggio con contesto del percorso immagine.
        """
        return self.message


class HardwareNotAvailableError(OCRError):
    """Eccezione sollevata quando il dispositivo hardware richiesto non è disponibile.

    Attributi:
        device_type: Tipo di dispositivo non disponibile (GPU/NPU).
    """

    def __init__(self, device_type: str) -> None:
        """Inizializza l'eccezione con il tipo di dispositivo.

        Args:
            device_type: Tipo di dispositivo richiesto ma non disponibile.
        """
        super().__init__(
            f"Dispositivo hardware '{device_type}' non disponibile. "
            "Verificare che i driver Intel siano installati correttamente.",
            details={"device_type": device_type},
        )
        self.device_type: str = device_type

    def __str__(self) -> str:
        """Restituisce il messaggio con il tipo di dispositivo non disponibile.

        Returns:
            Messaggio che indica il dispositivo non disponibile.
        """
        return f"Hardware non disponibile: {self.device_type} — {self.message}"


class ModelLoadError(OCRError):
    """Eccezione sollevata quando il modello GLM non può essere caricato.

    Attributi:
        model_id: Identificativo o percorso del modello che ha causato l'errore.
    """

    def __init__(self, model_id: str, reason: str = "") -> None:
        """Inizializza l'eccezione con ID modello e motivo.

        Args:
            model_id: Identificativo o percorso del modello.
            reason: Motivo opzionale del fallimento.
        """
        msg = f"Impossibile caricare il modello: {model_id}"
        if reason:
            msg += f" — {reason}"
        super().__init__(
            msg, details={"model_id": model_id, "reason": reason},
        )
        self.model_id: str = model_id

    def __str__(self) -> str:
        """Restituisce il messaggio con ID modello e motivo.

        Returns:
            Messaggio con contesto dell'ID del modello.
        """
        return self.message


class BatchProcessingError(OCRError):
    """Eccezione sollevata quando un job batch fallisce in modo critico.

    Attributi:
        job_id: Identificativo del job batch fallito.
    """

    def __init__(self, job_id: str, reason: str = "") -> None:
        """Inizializza l'eccezione con ID job e motivo.

        Args:
            job_id: Identificativo del job batch.
            reason: Motivo opzionale del fallimento.
        """
        msg = f"Job batch '{job_id}' fallito"
        if reason:
            msg += f" — {reason}"
        super().__init__(
            msg, details={"job_id": job_id, "reason": reason},
        )
        self.job_id: str = job_id

    def __str__(self) -> str:
        """Restituisce il messaggio con ID job e motivo.

        Returns:
            Messaggio con contesto dell'ID del job batch.
        """
        return self.message
