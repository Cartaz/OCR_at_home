"""Rilevamento backend GPU per llama.cpp (SYCL, Vulkan, CPU)."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

GPU_OFFLOAD_ALL_LAYERS = 99
GPU_OFFLOAD_PARTIAL_LAYERS = 20


def _project_root() -> Path:
    return Path(__file__).parent.parent


def venv_lib_dir() -> Path | None:
    lib_dir = _project_root() / ".venv" / "lib"
    return lib_dir if lib_dir.is_dir() else None


def venv_lib_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env) if base_env else dict(os.environ)
    lib_dir = venv_lib_dir()
    if lib_dir:
        existing = env.get("LD_LIBRARY_PATH", "")
        lib_str = str(lib_dir)
        if lib_str not in existing.split(":"):
            env["LD_LIBRARY_PATH"] = f"{lib_str}:{existing}" if existing else lib_str
    return env


def find_llama_server() -> str | None:
    project_root = _project_root()
    for base in (project_root / ".venv" / "bin", project_root):
        for name in ("llama-server", "llama-server.exe"):
            candidate = base / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return shutil.which("llama-server")


def _list_devices_text(server_path: str | None) -> str:
    """Interroga llama-server con l'API CLI ufficiale --list-devices."""
    if not server_path:
        return ""
    try:
        result = subprocess.run(
            [server_path, "--list-devices"],
            capture_output=True,
            text=True,
            timeout=15,
            env=venv_lib_env(),
        )
        if result.returncode == 0:
            return result.stdout + result.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def llama_server_supports_backend(server_path: str, backend: str) -> bool:
    """Verifica il backend compilato, con --list-devices come segnale forte."""
    env = venv_lib_env()
    devices = _list_devices_text(server_path).lower()
    if backend == "sycl" and re.search(r"\bsycl\d+\s*:", devices):
        return True
    if backend == "vulkan" and re.search(r"\bvulkan\d+\s*:", devices):
        return True

    try:
        for args in (["--version"], ["--help"]):
            try:
                result = subprocess.run(
                    [server_path, *args],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env,
                )
                text = (result.stdout + result.stderr).lower()
                if backend == "sycl" and any(
                    token in text
                    for token in (
                        "libggml-sycl",
                        "ggml_sycl",
                        "intelllvm",
                        "intel llvm",
                        "dpc++",
                    )
                ):
                    return True
                if backend == "vulkan" and "ggml_vulkan" in text:
                    return True
                if backend not in ("sycl", "vulkan") and backend in text:
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass

        # Le build shared del progetto locale espongono chiaramente il plugin
        # nel linkage dinamico. È il fallback più affidabile per versioni che
        # non implementano ancora --list-devices.
        try:
            result = subprocess.run(
                ["ldd", server_path],
                capture_output=True,
                text=True,
                timeout=10,
                env=env,
            )
            text = result.stdout.lower()
            if backend == "sycl" and any(
                token in text
                for token in ("libsycl", "libggml-sycl", "libze_loader")
            ):
                return True
            if backend == "vulkan" and (
                "libggml-vulkan" in text or "libvulkan" in text
            ):
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    except Exception as exc:
        logger.debug("Verifica backend %s fallita: %s", backend, exc)
    return False


def detect_gpu_backend(preferred_device: str | None = None) -> tuple[int, str]:
    """Rileva il backend rispettando la scelta esplicita dell'utente."""
    server_path = find_llama_server()
    if preferred_device == "llama-cpp-sycl":
        if _check_sycl(server_path):
            return GPU_OFFLOAD_ALL_LAYERS, "sycl"
        return 0, "unavailable"
    if preferred_device == "llama-cpp":
        if _check_vulkan(server_path):
            return GPU_OFFLOAD_ALL_LAYERS, "vulkan"
        return 0, "cpu"
    if _check_sycl(server_path):
        return GPU_OFFLOAD_ALL_LAYERS, "sycl"
    if _check_vulkan(server_path):
        return GPU_OFFLOAD_ALL_LAYERS, "vulkan"
    return 0, "cpu"


def _intel_gpu_present() -> bool:
    try:
        result = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    if result.returncode != 0:
        return False
    for line in result.stdout.lower().splitlines():
        if "intel" not in line:
            continue
        if any(
            kind in line
            for kind in (
                "vga compatible controller",
                "display controller",
                "3d controller",
            )
        ):
            return True
    return False


def _check_sycl(server_path: str | None) -> bool:
    devices = _list_devices_text(server_path)
    if re.search(r"\bSYCL\d+\s*:", devices, flags=re.IGNORECASE):
        return True

    # Fallback per vecchie versioni: Level Zero + GPU Intel + binary SYCL.
    ze_loader_found = any(
        Path(path).exists()
        for path in (
            "/usr/lib/libze_loader.so",
            "/usr/lib64/libze_loader.so",
            "/usr/local/lib/libze_loader.so",
        )
    )
    return bool(
        ze_loader_found
        and _intel_gpu_present()
        and server_path
        and llama_server_supports_backend(server_path, "sycl")
    )


def _check_vulkan(server_path: str | None) -> bool:
    devices = _list_devices_text(server_path)
    if re.search(r"\bVulkan\d+\s*:", devices, flags=re.IGNORECASE):
        return True

    try:
        result = subprocess.run(
            ["vulkaninfo", "--summary"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        text = result.stdout.lower()
        driver_ok = result.returncode == 0 and (
            "devicename" in text or "gpu" in text or "physical device" in text
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        driver_ok = False
    return bool(
        driver_ok
        and server_path
        and llama_server_supports_backend(server_path, "vulkan")
    )
