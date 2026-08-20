"""Rilevamento cache-ato del solo backend llama.cpp SYCL."""

from __future__ import annotations

from typing import Any

from config.constants import AppConstants
from core.event_bus import EventBus
from core.llama_gpu_detect import detect_gpu_backend, find_llama_server
from core.models import HardwareInfo


class HardwareDetector:
    """Espone un solo device: llama.cpp compilato con SYCL."""

    def __init__(self) -> None:
        self._devices: list[HardwareInfo] = []
        self._detected = False

    def detect(self, *, refresh: bool = False) -> list[HardwareInfo]:
        if self._detected and not refresh:
            return list(self._devices)

        server_path = find_llama_server()
        available = False
        label = "llama.cpp + SYCL (non pronto)"

        if server_path:
            _layers, backend = detect_gpu_backend(AppConstants.LLAMA_CPP_SYCL_DEVICE)
            available = backend == "sycl"
            label = (
                "llama.cpp + SYCL (GPU Intel)"
                if available
                else "llama.cpp presente, ma nessun device SYCL disponibile"
            )
        else:
            label = "llama.cpp + SYCL (llama-server non installato)"

        self._devices = [
            HardwareInfo(
                device_name=label,
                device_type=AppConstants.LLAMA_CPP_SYCL_DEVICE,
                available=available,
                memory_mb=0,
            )
        ]
        self._detected = True
        EventBus.emit(
            "hardware_detected",
            {"devices": [self._hw_to_dict(device) for device in self._devices]},
        )
        return list(self._devices)

    def get_default(self) -> HardwareInfo:
        devices = self.detect()
        return devices[0] if devices else HardwareInfo(
            device_name="llama.cpp + SYCL (non disponibile)",
            device_type=AppConstants.LLAMA_CPP_SYCL_DEVICE,
            available=False,
            memory_mb=0,
        )

    @staticmethod
    def _hw_to_dict(info: HardwareInfo) -> dict[str, Any]:
        return {
            "device_name": info.device_name,
            "device_type": info.device_type,
            "available": info.available,
            "memory_mb": info.memory_mb,
        }
