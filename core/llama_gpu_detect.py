"""Localizzazione di llama-server e verifica del device SYCL.

L'unica fonte di verità è ``llama-server --list-devices``: lo stesso controllo
che ``install.sh`` usa per accettare la build. Euristiche su librerie o GPU
presenti producevano falsi positivi e non sono più usate.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

GPU_OFFLOAD_ALL_LAYERS = 99
DEFAULT_ONEAPI_DEVICE_SELECTOR = "level_zero:0"
_SYCL_DEVICE_LINE = re.compile(r"^[ \t]*(SYCL\d+)[ \t]*:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE)


def _project_root() -> Path:
    return Path(__file__).parent.parent


def venv_lib_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env) if base_env else dict(os.environ)
    lib_dir = _project_root() / ".venv" / "lib"
    if lib_dir.is_dir():
        existing = env.get("LD_LIBRARY_PATH", "")
        lib_str = str(lib_dir)
        if lib_str not in existing.split(":"):
            env["LD_LIBRARY_PATH"] = f"{lib_str}:{existing}" if existing else lib_str
    return env


def sycl_runtime_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for every llama-server invocation (probe and server).

    ``ONEAPI_DEVICE_SELECTOR`` defaults to the first Level Zero GPU but an
    explicit value from the user's environment is respected, so systems with
    more than one Intel GPU can choose the device.
    """
    env = venv_lib_env(base_env)
    env.setdefault("ONEAPI_DEVICE_SELECTOR", DEFAULT_ONEAPI_DEVICE_SELECTOR)
    env["GGML_SYCL"] = "1"
    env["ZES_ENABLE_SYSMAN"] = "1"
    return env


def find_llama_server() -> str | None:
    venv_server = _project_root() / ".venv" / "bin" / "llama-server"
    if venv_server.is_file() and os.access(venv_server, os.X_OK):
        return str(venv_server)
    return shutil.which("llama-server")


def list_sycl_devices(server_path: str | None) -> list[str]:
    """Return the SYCL device descriptions exposed by ``server_path``."""
    if not server_path:
        return []
    try:
        result = subprocess.run(
            [server_path, "--list-devices"],
            capture_output=True,
            text=True,
            timeout=15,
            env=sycl_runtime_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("llama-server --list-devices non eseguibile: %s", exc)
        return []
    if result.returncode != 0:
        logger.warning(
            "llama-server --list-devices terminato con codice %s", result.returncode
        )
        return []
    text = result.stdout + result.stderr
    return [
        f"{match.group(1).upper()}: {match.group(2).strip()}".rstrip(": ")
        for match in _SYCL_DEVICE_LINE.finditer(text)
    ]
