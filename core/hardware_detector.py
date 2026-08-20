"""Rilevamento cache-ato dei backend llama.cpp disponibili."""

from __future__ import annotations
from typing import Any
from config.constants import AppConstants
from core.event_bus import EventBus
from core.llama_gpu_detect import detect_gpu_backend, find_llama_server
from core.models import HardwareInfo


class HardwareDetector:
    def __init__(self) -> None:
        self._devices: list[HardwareInfo] = []
        self._detected = False

    def detect(self, *, refresh: bool = False) -> list[HardwareInfo]:
        if self._detected and not refresh:
            return list(self._devices)
        self._devices = []
        server_path = find_llama_server()
        if not server_path:
            self._devices.append(HardwareInfo(device_name="llama.cpp (llama-server non installato)", device_type=AppConstants.LLAMA_CPP_DEVICE, available=False, memory_mb=0))
        else:
            _layers, backend = detect_gpu_backend(AppConstants.LLAMA_CPP_SYCL_DEVICE)
            if backend == "sycl":
                self._devices.append(HardwareInfo(device_name="llama.cpp + SYCL (GPU Intel Arc) — Consigliato", device_type=AppConstants.LLAMA_CPP_SYCL_DEVICE, available=True, memory_mb=0))
            self._devices.append(HardwareInfo(device_name="llama.cpp generico (Vulkan se disponibile, altrimenti CPU)", device_type=AppConstants.LLAMA_CPP_DEVICE, available=True, memory_mb=0))
        self._detected = True
        EventBus.emit("hardware_detected", {"devices": [self._hw_to_dict(d) for d in self._devices]})
        return list(self._devices)

    def get_default(self) -> HardwareInfo:
        devices = self.detect()
        for preferred in (AppConstants.LLAMA_CPP_SYCL_DEVICE, AppConstants.LLAMA_CPP_DEVICE):
            for device in devices:
                if device.device_type == preferred and device.available:
                    return device
        return devices[0] if devices else HardwareInfo()

    @staticmethod
    def _hw_to_dict(info: HardwareInfo) -> dict[str, Any]:
        return {"device_name": info.device_name, "device_type": info.device_type, "available": info.available, "memory_mb": info.memory_mb}
