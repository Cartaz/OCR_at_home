"""Rilevamento backend GPU per llama.cpp (SYCL, Vulkan, CPU)."""

from __future__ import annotations

import logging
import os
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
            if candidate.is_file():
                return str(candidate)
    return shutil.which("llama-server")


def llama_server_supports_backend(server_path: str, backend: str) -> bool:
    env = venv_lib_env()
    try:
        for args in (["--version"], ["--help"]):
            try:
                result = subprocess.run(
                    [server_path, *args], capture_output=True, text=True,
                    timeout=10, env=env,
                )
                text = (result.stdout + result.stderr).lower()
                if backend == "sycl" and any(
                    token in text for token in (
                        "intelllvm", "intel llvm", "dpc++", " icx ",
                        "sycl", "level-zero", "level_zero",
                    )
                ):
                    return True
                if backend == "vulkan" and "vulkan" in text:
                    return True
                if backend not in ("sycl", "vulkan") and backend in text:
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
        try:
            result = subprocess.run(
                ["ldd", server_path], capture_output=True, text=True,
                timeout=10, env=env,
            )
            text = result.stdout.lower()
            if backend == "sycl" and any(
                token in text for token in ("libsycl", "libggml-sycl", "libze_loader")
            ):
                return True
            if backend == "vulkan" and "vulkan" in text:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
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
        result = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0 and "VGA compatible controller: Intel" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _check_sycl(server_path: str | None) -> bool:
    ze_loader_found = any(
        Path(path).exists() for path in (
            "/usr/lib/libze_loader.so", "/usr/lib64/libze_loader.so",
            "/usr/local/lib/libze_loader.so",
        )
    )
    icr_found = shutil.which("ocloc") is not None
    if not (ze_loader_found and icr_found and _intel_gpu_present()):
        return False
    return bool(server_path and llama_server_supports_backend(server_path, "sycl"))


def _check_vulkan(server_path: str | None) -> bool:
    try:
        result = subprocess.run(
            ["vulkaninfo", "--summary"], capture_output=True, text=True, timeout=10,
        )
        driver_ok = result.returncode == 0 and "Intel" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        driver_ok = False
    return bool(driver_ok and server_path and llama_server_supports_backend(server_path, "vulkan"))
