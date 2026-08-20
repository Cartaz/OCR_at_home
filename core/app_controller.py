# core/app_controller.py
"""Controller principale dell'applicazione GLM OCR.

Orchestra l'interazione tra il motore OCR, il gestore processi,
il rilevatore hardware e le impostazioni. Espone l'interfaccia
pubblica per il livello UI e comunica i cambiamenti di stato
esclusivamente tramite l'EventBus.

CRITICO: Questo modulo NON importa da PySide6, PyQt6 o qualsiasi
altro modulo Qt. Usa threading.Thread per l'OCR asincrono e
EventBus per la comunicazione con la UI.
"""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Callable

from config.settings import Settings
from core.event_bus import EventBus
from core.exceptions import OCREngineNotInitializedError
from core.hardware_detector import HardwareDetector
from core.models import BatchOCRJob, HardwareInfo, OCRResult
from core.ocr_engine import OCREngine
from core.process_manager import ProcessManager

logger = logging.getLogger(__name__)


class _OCRWorker:
    """Worker per l'esecuzione asincrona dell'OCR su singola immagine.

    Esegue l'OCR in un thread daemon e comunica i risultati tramite
    EventBus anziché segnali Qt.
    """

    def __init__(self, engine: OCREngine, image_path: Path, task_id: str) -> None:
        self._engine = engine
        self._image_path = image_path
        self._task_id = task_id

    def run(self) -> None:
        """Esegue l'OCR e emette eventi tramite EventBus."""
        try:
            result = self._engine.process_image(self._image_path)
            # process_image already emits ocr_started and ocr_completed
            logger.info(
                "OCR completato per %s (%.1f ms)",
                self._image_path.name, result.processing_time_ms,
            )
        except Exception as exc:
            logger.error("OCR fallito per %s: %s", self._image_path, exc)
            EventBus.emit("ocr_failed", {
                "task_id": self._task_id, "error": str(exc),
            })


class AppController:
    """Controller principale che coordina tutti i moduli dell'applicazione.

    Qt-free: usa threading.Thread + EventBus per comunicazione UI.

    Eventi: model_loading, config_changed, ocr_started, ocr_completed,
    ocr_failed.
    """

    def __init__(self, settings: Settings) -> None:
        """Inizializza il controller con le impostazioni utente."""
        self._settings: Settings = settings
        self._engine: OCREngine = OCREngine()
        self._process_manager: ProcessManager = ProcessManager(self._engine)
        self._hardware_detector: HardwareDetector = HardwareDetector()
        self._initialized: bool = False
        self._ocr_thread: threading.Thread | None = None

    # --- Proprietà ---

    @property
    def settings(self) -> Settings:
        """Impostazioni correnti dell'applicazione."""
        return self._settings

    @property
    def engine(self) -> OCREngine:
        """Motore OCR utilizzato per l'elaborazione."""
        return self._engine

    @property
    def hardware_detector(self) -> HardwareDetector:
        """Rilevatore di dispositivi hardware."""
        return self._hardware_detector

    @property
    def process_manager(self) -> ProcessManager:
        """Gestore dei processi batch."""
        return self._process_manager

    @property
    def is_model_loading(self) -> bool:
        """Indica se il caricamento del modello è in corso."""
        return False  # Model loading is handled by EventBridge QThread

    # --- Inizializzazione ---

    def initialize(self) -> None:
        """Rileva hardware e determina il dispositivo di default.

        Non avvia il caricamento del modello — quello è delegato al
        livello UI tramite EventBridge.start_model_loading().
        """
        logger.info("Inizializzazione controller applicazione...")
        devices = self._hardware_detector.detect()
        default_device: str = self._settings.default_device
        if not any(
            d.device_type == default_device and d.available for d in devices
        ):
            fallback = self._hardware_detector.get_default()
            default_device = fallback.device_type
            logger.info(
                "Dispositivo di default non disponibile, fallback a %s",
                default_device,
            )
        self._initialized = True
        logger.info("Controller applicazione inizializzato.")
        # Notifica la UI che il modello deve essere caricato.
        # Il layer UI (EventBridge) avvierà il QThread.
        EventBus.emit("model_loading", {"device": default_device})

    # --- Caricamento modello (sincrono, chiamato dal QThread worker) ---

    def load_model_sync(self, device: str) -> None:
        """Carica il modello OCR in modo sincrono.

        Questo metodo è progettato per essere chiamato dal ModelLoadWorker
        nel QThread di EventBridge. NON crea thread propri.

        Args:
            device: Dispositivo di inferenza (GPU/NPU/CPU).
        """
        self._engine.initialize(device=device)

    # --- API pubblica ---

    def run_ocr(self, image_path: Path) -> OCRResult:
        """Esegue l'OCR su una singola immagine (sincrono, per testing).

        Args:
            image_path: Percorso del file immagine da elaborare.

        Returns:
            OCRResult con testo estratto e metadati.

        Raises:
            OCREngineNotInitializedError: Se il motore non è inizializzato.
        """
        if not self._engine.is_initialized:
            raise OCREngineNotInitializedError()
        return self._engine.process_image(image_path)

    def start_ocr(self, image_path: Path) -> None:
        """Avvia l'OCR su una singola immagine in un thread background.

        I risultati vengono comunicati tramite EventBus:
        - ocr_started: elaborazione iniziata
        - ocr_completed: elaborazione completata con testo
        - ocr_failed: elaborazione fallita con errore

        Args:
            image_path: Percorso del file immagine da elaborare.

        Raises:
            OCREngineNotInitializedError: Se il motore non è inizializzato.
        """
        if not self._engine.is_initialized:
            raise OCREngineNotInitializedError()
        task_id = image_path.stem + "-" + uuid.uuid4().hex[:6]
        worker = _OCRWorker(self._engine, image_path, task_id)
        self._ocr_thread = threading.Thread(
            target=worker.run,
            name=f"ocr-worker-{task_id}",
            daemon=True,
        )
        self._ocr_thread.start()
        logger.info("Thread OCR avviato per: %s", image_path.name)

    def run_batch(self, image_paths: list[Path]) -> BatchOCRJob:
        """Esegue l'OCR su un batch di immagini.

        Args:
            image_paths: Lista dei percorsi delle immagini.

        Returns:
            BatchOCRJob con i task creati per ogni immagine.

        Raises:
            OCREngineNotInitializedError: Se il motore non è inizializzato.
        """
        if not self._engine.is_initialized:
            raise OCREngineNotInitializedError()
        return self._process_manager.submit_batch(image_paths)

    def cancel_batch(self, job_id: str) -> None:
        """Annulla un job batch in esecuzione.

        Args:
            job_id: Identificativo del job da annullare.
        """
        self._process_manager.cancel_batch(job_id)

    def cancel_active_batch(self) -> None:
        """Annulla il job batch attualmente in esecuzione, se presente."""
        self._process_manager.cancel_active_batch()

    def get_available_devices(self) -> list[HardwareInfo]:
        """Elenca i dispositivi di inferenza disponibili.

        Returns:
            Lista di HardwareInfo per ogni dispositivo rilevato.
        """
        return self._hardware_detector.detect()

    def switch_device(self, device_type: str) -> None:
        """Cambia il dispositivo di inferenza e ricarica il modello.

        Args:
            device_type: Tipo di dispositivo target (GPU/NPU/CPU).
        """
        logger.info(
            "Cambio dispositivo di inferenza: %s → %s",
            self._engine.device, device_type,
        )
        self._engine.shutdown()
        self._settings = self._settings.with_(default_device=device_type)
        self._settings.save()
        EventBus.emit("config_changed", {"default_device": device_type})
        # Notifica la UI per ricaricare il modello via EventBridge QThread
        EventBus.emit("model_loading", {"device": device_type})

    def update_settings(self, **overrides: object) -> None:
        """Aggiorna le impostazioni con gli override forniti.

        Args:
            **overrides: Campi da sostituire e loro nuovi valori.
        """
        self._settings = self._settings.with_(**overrides)
        self._settings.save()
        EventBus.emit("config_changed", overrides)
        logger.debug("Impostazioni aggiornate: %s", overrides)

    def shutdown(self) -> None:
        """Arresta il controller e rilascia tutte le risorse."""
        self._process_manager.shutdown()
        self._engine.shutdown()
        self._initialized = False
        logger.info("Controller applicazione arrestato.")

    def subscribe(self, event: str, handler: Callable) -> None:
        """Sottoscrive un handler per un evento tramite EventBus.

        Args:
            event: Nome dell'evento (es. 'model_loaded').
            handler: Funzione callback da invocare.
        """
        EventBus.subscribe(event, handler)
