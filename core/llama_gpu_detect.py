"""Rilevamento esclusivo del backend SYCL per llama.cpp."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

GPU_OFFLOAD_ALL_LAYERS = 99
# Alias mantenuto per compatibilità con codice/test esistenti. Non rappresenta
# più un profilo parziale: GLM OCR non deve ricadere sulla CPU.
GPU_OFFLOAD_PARTIAL_LAYERS = GPU_OFFLOAD_ALL_LAYERS


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
    """Verifica esclusivamente che il binary esponga SYCL."""
    if backend != "sycl":
        return False

    env = venv_lib_env()
    devices = _list_devices_text(server_path).lower()
    if re.search(r"\bsycl\d+\s*:", devices):
        return True

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
            if any(
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
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    try:
        result = subprocess.run(
            ["ldd", server_path],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        text = result.stdout.lower()
        return any(
            token in text
            for token in ("libsycl", "libggml-sycl", "libze_loader")
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def detect_gpu_backend(preferred_device: str | None = None) -> tuple[int, str]:
    """Restituisce SYCL oppure unavailable; non esistono fallback."""
    if preferred_device not in (None, "llama-cpp-sycl"):
        return 0, "unavailable"
    server_path = find_llama_server()
    if _check_sycl(server_path):
        return GPU_OFFLOAD_ALL_LAYERS, "sycl"
    return 0, "unavailable"


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
