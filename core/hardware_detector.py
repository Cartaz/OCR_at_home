# core/hardware_detector.py
"""Rilevamento dispositivi hardware per l'accelerazione OCR.

Rileva GPU Intel Arc e llama-server con supporto SYCL,
restituendo informazioni dettagliate su ciascun dispositivo.

L'applicazione usa esclusivamente llama.cpp + SYCL come backend.
llama-server deve essere compilato con GGML_SYCL=1 per l'accelerazione
GPU Intel Arc. La versione di pacman (CachyOS/Arch) è CPU-only,
quindi è necessario compilare da sorgente.

Requisiti per l'accelerazione GPU Intel Arc:
1. llama-server compilato con SYCL (IntelLLVM / icx)
2. Driver Level Zero (level-zero-loader)
3. Intel Compute Runtime (intel-compute-runtime)
4. GPU Intel Arc visibile via lspci
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from core.event_bus import EventBus
from core.models import HardwareInfo
from config.constants import AppConstants
from core.llama_gpu_detect import find_llama_server, llama_server_supports_backend

logger = logging.getLogger(__name__)


class HardwareDetector:
    """Rilevatore di dispositivi hardware per inferenza OCR.

    Rileva la presenza di llama-server e verifica il supporto SYCL
    per l'accelerazione GPU Intel Arc.

    Attributi:
        _devices: Lista cache dei dispositivi rilevati.
        _llama_cpp_available: Flag che indica se llama-server è disponibile.
        _sycl_available: Flag che indica se llama-server supporta SYCL.
        _sycl_drivers_ok: Flag che indica se i driver SYCL sono installati.
    """

    def __init__(self) -> None:
        """Inizializza il rilevatore con cache vuota."""
        self._devices: list[HardwareInfo] = []
        self._llama_cpp_available: bool = False
        self._sycl_available: bool = False
        self._sycl_drivers_ok: bool = False

    def detect(self) -> list[HardwareInfo]:
        """Rileva tutti i dispositivi di inferenza disponibili.

        Emette l'evento 'hardware_detected' con i risultati.

        Returns:
            Lista di HardwareInfo per ogni dispositivo trovato.
        """
        self._devices = []
        self._check_llama_cpp()
        self._add_llama_cpp_devices()

        EventBus.emit("hardware_detected", {
            "devices": [self._hw_to_dict(d) for d in self._devices],
        })
        return list(self._devices)

    def _check_llama_cpp(self) -> None:
        """Verifica la disponibilità di llama-server e il supporto SYCL."""
        # Usa find_llama_server() che cerca PRIMA nel venv
        # (shutil.which troverebbe solo /usr/bin/llama-server CPU-only)
        server_path = find_llama_server()
        if server_path:
            self._llama_cpp_available = True
            logger.info("llama-server trovato: %s", server_path)

            # Verifica supporto SYCL nel binary (con LD_LIBRARY_PATH)
            if llama_server_supports_backend(server_path, "sycl"):
                self._sycl_available = True
                logger.info("llama-server compilato con SYCL (GPU Intel Arc supportata)")
            else:
                self._sycl_available = False
                logger.warning(
                    "llama-server NON è compilato con supporto SYCL. "
                    "Il server girerebbe su CPU ignorando -ngl. "
                    "Soluzione: ricompila llama.cpp con GGML_SYCL=1. "
                    "Verifica con: llama-server --version"
                )
        else:
            # Cerca anche llama-mtmd-cli come alternativa
            mtmd_path = shutil.which("llama-mtmd-cli")
            if mtmd_path:
                self._llama_cpp_available = True
                logger.info("llama-mtmd-cli trovato: %s", mtmd_path)
            else:
                self._llama_cpp_available = False
                logger.info(
                    "llama-server non trovato nel PATH. "
                    "Per il backend GGUF: sudo pacman -S llama.cpp "
                    "oppure compila con SYCL da sorgente."
                )

        # Verifica driver SYCL (Level Zero + Intel Compute Runtime)
        ze_loader_found = any(
            Path(p).exists() for p in [
                "/usr/lib/libze_loader.so",
                "/usr/lib64/libze_loader.so",
                "/usr/local/lib/libze_loader.so",
            ]
        )
        icr_found = shutil.which("ocloc") is not None

        # Verifica GPU Intel via lspci
        intel_gpu_found = False
        try:
            result = subprocess.run(
                ["lspci"], capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and "VGA compatible controller: Intel" in result.stdout:
                intel_gpu_found = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        self._sycl_drivers_ok = ze_loader_found and icr_found and intel_gpu_found

        if self._sycl_drivers_ok:
            logger.info(
                "Driver SYCL completi: Level Zero=%s, Compute Runtime=%s, GPU Intel=%s",
                ze_loader_found, icr_found, intel_gpu_found,
            )
        else:
            logger.debug(
                "Driver SYCL non completi: Level Zero=%s, Compute Runtime=%s, GPU Intel=%s",
                ze_loader_found, icr_found, intel_gpu_found,
            )

    def _add_llama_cpp_devices(self) -> None:
        """Aggiunge llama.cpp come opzione dispositivo."""
        # Evita duplicati
        llama_present = any(
            d.device_type in (AppConstants.LLAMA_CPP_DEVICE, AppConstants.LLAMA_CPP_SYCL_DEVICE)
            for d in self._devices
        )
        if llama_present:
            return

        if self._llama_cpp_available:
            if self._sycl_available:
                # llama-server con SYCL — dispositivo raccomandato
                self._devices.append(HardwareInfo(
                    device_name="llama.cpp + SYCL (GPU Intel Arc) — Consigliato",
                    device_type=AppConstants.LLAMA_CPP_SYCL_DEVICE,
                    available=True,
                    memory_mb=0,
                ))
            else:
                # llama-server senza SYCL — solo CPU
                self._devices.append(HardwareInfo(
                    device_name="llama.cpp (solo CPU — ricompila con SYCL per GPU)",
                    device_type=AppConstants.LLAMA_CPP_DEVICE,
                    available=True,
                    memory_mb=0,
                ))
        else:
            self._devices.append(HardwareInfo(
                device_name="llama.cpp (installa: sudo pacman -S llama.cpp)",
                device_type=AppConstants.LLAMA_CPP_DEVICE,
                available=False,
                memory_mb=0,
            ))

    def get_default(self) -> HardwareInfo:
        """Restituisce il dispositivo di default preferito.

        Priorità: llama-cpp-sycl > llama-cpp.

        Returns:
            HardwareInfo del dispositivo di default.
        """
        if not self._devices:
            self.detect()
        priority = [
            AppConstants.LLAMA_CPP_SYCL_DEVICE,
            AppConstants.LLAMA_CPP_DEVICE,
        ]
        for pref in priority:
            for device in self._devices:
                if device.device_type == pref and device.available:
                    return device
        return self._devices[0] if self._devices else HardwareInfo()

    @staticmethod
    def _hw_to_dict(info: HardwareInfo) -> dict[str, Any]:
        """Converte un HardwareInfo in dizionario per l'event bus."""
        return {
            "device_name": info.device_name,
            "device_type": info.device_type,
            "available": info.available,
            "memory_mb": info.memory_mb,
        }
