"""Primitive cooperative di cancellazione thread-safe."""

from __future__ import annotations

import threading
from collections.abc import Callable

from core.exceptions import OperationCancelledError


class CancellationToken:
    """Token di cancellazione per una singola operazione.

    I closer registrati vengono invocati una sola volta durante ``cancel()``.
    Sono usati anche per interrompere I/O bloccante (es. la socket HTTP
    verso llama-server), non solo per fare polling cooperativo.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._closers: set[Callable[[], None]] = set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            closers = tuple(self._closers)
            self._closers.clear()

        for closer in closers:
            try:
                closer()
            except Exception:
                pass

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelledError()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def register_closer(self, closer: Callable[[], None]) -> None:
        call_now = False
        with self._lock:
            if self._event.is_set():
                call_now = True
            else:
                self._closers.add(closer)
        if call_now:
            try:
                closer()
            except Exception:
                pass

    def unregister_closer(self, closer: Callable[[], None]) -> None:
        with self._lock:
            self._closers.discard(closer)
