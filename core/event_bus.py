# core/event_bus.py
"""Sistema di comunicazione centralizzato (Event Bus) thread-safe.

Implementa un event bus singleton che funga da canale di comunicazione
tra tutti i moduli dell'applicazione. Questo modulo è indipendente da
Qt e non importa mai moduli PySide6/PyQt6.

L'event bus supporta: registrazione di handler per tipo di evento
(subscribe), emissione di eventi (emit), e deregistrazione
(unsubscribe). I nomi degli eventi seguono il pattern modulo_azione_stato.

Gli handler vengono eseguiti sincronamente nel thread dell'emittente.
Le operazioni lunghe devono essere delegate a worker thread separati.
Gli errori nei singoli handler vengono catturati e loggati, senza
bloccare l'esecuzione degli handler successivi.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], None]


class EventBus:
    """Event bus singleton thread-safe per la comunicazione tra moduli.

    Pattern ispirato ad AllTranscribr. Utilizza un lock per garantire
    la thread-safety delle operazioni di subscribe/unsubscribe/emit.
    Gli handler sono memorizzati in un defaultdict(list) per evento.

    L'uso consigliato è tramite i metodi di classe:
        EventBus.subscribe("event", handler)
        EventBus.emit("event", {"key": "value"})
        EventBus.unsubscribe("event", handler)
        EventBus.reset()  # solo per test teardown
    """

    _instance: "EventBus | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "EventBus":
        """Crea o restituisce l'istanza singleton dell'EventBus."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._handlers = defaultdict(list)
                cls._instance._instance_lock = threading.Lock()
        return cls._instance

    def _subscribe(self, event_name: str, handler: Handler) -> None:
        with self._instance_lock:
            self._handlers[event_name].append(handler)
        logger.debug("Handler registrato per evento '%s'", event_name)

    def _unsubscribe(self, event_name: str, handler: Handler) -> None:
        with self._instance_lock:
            handlers = self._handlers.get(event_name, [])
            if handler in handlers:
                handlers.remove(handler)
                logger.debug("Handler rimosso per evento '%s'", event_name)

    def _emit(self, event_name: str, data: dict[str, Any] | None) -> None:
        event_data = data if data is not None else {}
        with self._instance_lock:
            handlers = list(self._handlers.get(event_name, []))
        logger.debug("Evento '%s' emesso con %d handler", event_name, len(handlers))
        for handler in handlers:
            try:
                handler(event_data)
            except Exception as exc:
                logger.error(
                    "Errore nell'handler per evento '%s': %s",
                    event_name, exc,
                )

    # --- API pubblica (metodi di classe che delegano al singleton) ---

    @classmethod
    def subscribe(cls, event_name: str, handler: Handler) -> None:
        """Registra un handler per un tipo di evento tramite il singleton.

        Args:
            event_name: Nome dell'evento (es. 'model_loaded').
            handler: Funzione callback che accetta un dict di dati.
        """
        cls()._subscribe(event_name, handler)

    @classmethod
    def unsubscribe(cls, event_name: str, handler: Handler) -> None:
        """Deregistra un handler per un tipo di evento tramite il singleton.

        Args:
            event_name: Nome dell'evento.
            handler: Handler precedentemente registrato.
        """
        cls()._unsubscribe(event_name, handler)

    @classmethod
    def emit(cls, event_name: str, data: dict[str, Any] | None = None) -> None:
        """Emette un evento, invocando tutti gli handler registrati.

        Gli handler vengono eseguiti sincronamente nel thread dell'emittente.
        Gli errori nei singoli handler sono catturati e loggati, senza
        bloccare l'esecuzione degli handler successivi.

        Args:
            event_name: Nome dell'evento da emettere.
            data: Dizionario di dati associati all'evento.
        """
        cls()._emit(event_name, data)

    @classmethod
    def reset(cls) -> None:
        """Resetta completamente il singleton.

        Rimuove tutti gli handler e azzera l'istanza. Usato
        esclusivamente per il teardown dei test.
        """
        with cls._lock:
            if cls._instance is not None:
                with cls._instance._instance_lock:
                    cls._instance._handlers.clear()
            cls._instance = None
