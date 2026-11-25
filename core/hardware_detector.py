"""Rilevamento (con cache) del runtime llama.cpp SYCL."""

from __future__ import annotations

import threading

from core.event_bus import EventBus
from core.llama_gpu_detect import find_llama_server, list_sycl_devices
from core.models import BackendStatus


class HardwareDetector:
    """Report whether the installed llama-server exposes a SYCL device."""

    def __init__(self) -> None:
        self._status: BackendStatus | None = None
        self._lock = threading.Lock()

    def detect(self, *, refresh: bool = False) -> BackendStatus:
        with self._lock:
            if self._status is not None and not refresh:
                return self._status

        server_path = find_llama_server()
        if not server_path:
            status = BackendStatus(False, "llama.cpp + SYCL (llama-server non installato)")
        else:
            devices = list_sycl_devices(server_path)
            if devices:
                status = BackendStatus(True, f"llama.cpp + {devices[0]}")
            else:
                status = BackendStatus(
                    False, "llama.cpp presente, ma nessun device SYCL disponibile"
                )

        with self._lock:
            self._status = status
        EventBus.emit(
            "hardware_detected",
            {"available": status.available, "label": status.label},
        )
        return status
