# core/llama_gpu_detect.py
"""Rilevamento backend GPU per llama.cpp (SYCL, Vulkan, CPU).

Contiene funzioni per individuare l'eseguibile llama-server nel
sistema, verificare il supporto SYCL/Vulkan nel binary compilato,
e determinare il backend GPU ottimale per l'inferenza.

IMPORTANTE: il binary compilato con SYCL vive nel venv (.venv/bin/llama-server)
e le librerie condivise (.so) sono in .venv/lib/. Questo per evitare che
aggiornamenti pacman (CachyOS/Arch) sovrascrivano il binary SYCL con una
versione CPU-only. Pertanto:

1. find_llama_server() cerca PRIMA nel venv, poi nel progetto, poi nel PATH
2. Tutti i subprocess che eseguono llama-server o ldd devono avere
   LD_LIBRARY_PATH che include .venv/lib/
3. llama_server_supports_backend() e _check_sycl_in_binary() impostano
   LD_LIBRARY_PATH prima di eseguire ldd o --version

Functions:
    find_llama_server: Cerca llama-server nel sistema (priorità venv).
    venv_lib_dir: Restituisce il percorso .venv/lib/ del progetto.
    venv_lib_env: Restituisce un dict env con LD_LIBRARY_PATH corretto.
    llama_server_supports_backend: Verifica backend GPU nel binary.
    detect_gpu_backend: Rileva il backend GPU disponibile.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Numero di layer GPU da offloadare.
# 99 = tutti i layer — elimina il ping-pong CPU↔GPU che è il
# bottleneck principale su GPU integrate (Intel Arc).
GPU_OFFLOAD_ALL_LAYERS: int = 99
GPU_OFFLOAD_PARTIAL_LAYERS: int = 20  # Fallback se full offload fallisce


def _project_root() -> Path:
    """Restituisce la directory radice del progetto (dove sta main.py)."""
    return Path(__file__).parent.parent


def venv_lib_dir() -> Path | None:
    """Restituisce il percorso della directory .venv/lib/ del progetto.

    Returns:
        Percorso di .venv/lib/ se esiste, None altrimenti.
    """
    lib_dir = _project_root() / ".venv" / "lib"
    if lib_dir.is_dir():
        return lib_dir
    return None


def venv_lib_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Restituisce un dizionario env con LD_LIBRARY_PATH che include .venv/lib/.

    Questo è essenziale per:
    - ldd: trovare libggml-sycl.so e le altre .so
    - llama-server --version: caricare i plugin SYCL
    - llama-server: caricare i backend SYCL/Vulkan a runtime

    Args:
        base_env: Dizionario ambiente di partenza (default: os.environ).

    Returns:
        Dizionario ambiente con LD_LIBRARY_PATH aggiornato.
    """
    env = dict(base_env) if base_env else dict(os.environ)
    lib_dir = venv_lib_dir()
    if lib_dir:
        existing = env.get("LD_LIBRARY_PATH", "")
        lib_str = str(lib_dir)
        if lib_str not in existing.split(":"):
            env["LD_LIBRARY_PATH"] = f"{lib_str}:{existing}" if existing else lib_str
    return env


def find_llama_server() -> str | None:
    """Cerca l'eseguibile llama-server nel sistema.

    Priorità di ricerca (la più alta per prima):
    1. Nel virtual environment (.venv/bin/) — binary compilato con SYCL,
       immune da aggiornamenti pacman che sovrascrivono /usr/bin/llama-server
    2. Nella directory radice del progetto
    3. Nel PATH di sistema (potrebbe essere CPU-only)

    Returns:
        Percorso dell'eseguibile, o None se non trovato.
    """
    project_root = _project_root()

    # 1. Nel virtual environment bin — PRIORITÀ MASSIMA
    #    Il binary SYCL compilato da install.sh vive qui.
    venv_bin = project_root / ".venv" / "bin"
    for name in ("llama-server", "llama-server.exe"):
        candidate = venv_bin / name
        if candidate.exists():
            logger.info("llama-server trovato nel venv: %s", candidate)
            return str(candidate)

    # 2. Nella directory del progetto
    for name in ("llama-server", "llama-server.exe"):
        candidate = project_root / name
        if candidate.exists():
            logger.info("llama-server trovato nel progetto: %s", candidate)
            return str(candidate)

    # 3. Nel PATH di sistema (ATTENZIONE: potrebbe essere CPU-only)
    server_path = shutil.which("llama-server")
    if server_path:
        logger.info("llama-server trovato nel PATH: %s", server_path)
        return server_path

    return None


def llama_server_supports_backend(server_path: str, backend: str) -> bool:
    """Verifica se llama-server è compilato con il supporto per un backend GPU.

    Usa più metodi per rilevare il backend compilato nel binary:
    1. --version: controlla il compilatore usato (IntelLLVM = SYCL)
    2. --help: cerca il nome del backend nell'output (versioni vecchie)
    3. ldd: verifica le librerie collegate (fallback)

    Tutti i comandi subprocess vengono eseguiti con LD_LIBRARY_PATH
    che include .venv/lib/ per permettere a ldd di risolvere
    libggml-sycl.so e le altre librerie condivise SYCL.

    Args:
        server_path: Percorso dell'eseguibile llama-server.
        backend: Nome del backend ("sycl", "vulkan", "cuda", ecc.)

    Returns:
        True se il backend è supportato dal binary, False altrimenti.
    """
    env = venv_lib_env()

    try:
        # Metodo 1: --version per compilatore IntelLLVM
        try:
            result = subprocess.run(
                [server_path, "--version"],
                capture_output=True, text=True, timeout=10,
                env=env,
            )
            version_text = (result.stdout + result.stderr).lower()

            if backend == "sycl":
                if "intelllvm" in version_text or "intel llvm" in version_text:
                    return True
                if "dpc++" in version_text or " icx " in version_text:
                    return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Metodo 2: --help per il nome del backend
        try:
            result = subprocess.run(
                [server_path, "--help"],
                capture_output=True, text=True, timeout=10,
                env=env,
            )
            help_text = (result.stdout + result.stderr).lower()

            if backend == "sycl":
                if "sycl" in help_text or "level-zero" in help_text or "level_zero" in help_text:
                    return True
            elif backend == "vulkan":
                if "vulkan" in help_text:
                    return True
            elif backend == "cuda":
                if "cuda" in help_text:
                    return True
            else:
                if backend in help_text:
                    return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Metodo 3: ldd per librerie collegate
        # CRITICO: ldd ha bisogno di LD_LIBRARY_PATH per trovare
        # le .so in .venv/lib/ (libggml-sycl.so, etc.)
        if backend == "sycl":
            try:
                result = subprocess.run(
                    ["ldd", server_path],
                    capture_output=True, text=True, timeout=10,
                    env=env,
                )
                ldd_text = result.stdout.lower()
                # Cerca sia libsycl (SYCL runtime) che libggml-sycl (backend)
                # che libze_loader (Level Zero)
                if ("libsycl" in ldd_text or "libggml-sycl" in ldd_text
                        or "libze_loader" in ldd_text):
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        return False
    except Exception as exc:
        logger.debug("Impossibile verificare backend %s: %s", backend, exc)
        return False


def detect_gpu_backend() -> tuple[int, str]:
    """Rileva il backend GPU disponibile per llama.cpp.

    Priorità di rilevamento:
    1. SYCL (Intel Level Zero) — backend nativo per GPU Intel Arc
    2. Vulkan — backend portabile, fallback se SYCL non disponibile

    IMPORTANTE: non basta che i driver siano installati — llama-server deve
    essere compilato con il supporto per il backend. Questa funzione verifica
    ENTRAMBE le condizioni: driver presenti E supporto nel binary.

    Returns:
        Tuple (numero_layer_gpu, tipo_backend) dove tipo_backend è
        "sycl", "vulkan", o "cpu".
    """
    server_path = find_llama_server()

    # 1. Verifica SYCL
    sycl_available = _check_sycl(server_path)

    if sycl_available:
        logger.info("SYCL con GPU Intel rilevato — backend nativo (ottimale)")
        return GPU_OFFLOAD_ALL_LAYERS, "sycl"

    # 2. Verifica Vulkan
    if _check_vulkan(server_path):
        logger.info("Vulkan con GPU Intel rilevato — offload GPU possibile")
        return GPU_OFFLOAD_ALL_LAYERS, "vulkan"

    return 0, "cpu"


def _check_sycl(server_path: str | None) -> bool:
    """Verifica se SYCL è disponibile (driver + supporto nel binary).

    Args:
        server_path: Percorso di llama-server, o None.

    Returns:
        True se SYCL è utilizzabile.
    """
    # Verifica Level Zero loader
    ze_loader_found = any(
        Path(p).exists() for p in [
            "/usr/lib/libze_loader.so",
            "/usr/lib64/libze_loader.so",
            "/usr/local/lib/libze_loader.so",
        ]
    )

    # Verifica Intel Compute Runtime
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

    driver_available = ze_loader_found and icr_found and intel_gpu_found

    if not driver_available:
        logger.debug(
            "SYCL driver non completi: Level Zero=%s, Compute Runtime=%s, GPU Intel=%s",
            ze_loader_found, icr_found, intel_gpu_found,
        )
        return False

    # Verifica che llama-server sia compilato con SYCL
    if server_path and llama_server_supports_backend(server_path, "sycl"):
        logger.info(
            "SYCL rilevato: Level Zero=%s, Compute Runtime=%s, GPU Intel=%s",
            ze_loader_found, icr_found, intel_gpu_found,
        )
        return True

    logger.warning(
        "Driver SYCL presenti (Level Zero=%s, Compute Runtime=%s, GPU Intel=%s) "
        "ma llama-server NON è compilato con supporto SYCL. "
        "Soluzione: ricompila llama.cpp con SYCL oppure usa Vulkan.",
        ze_loader_found, icr_found, intel_gpu_found,
    )
    return False


def _check_vulkan(server_path: str | None) -> bool:
    """Verifica se Vulkan è disponibile (driver + supporto nel binary).

    Args:
        server_path: Percorso di llama-server, o None.

    Returns:
        True se Vulkan è utilizzabile.
    """
    vulkan_driver_available = False
    try:
        result = subprocess.run(
            ["vulkaninfo", "--summary"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and "Intel" in result.stdout:
            vulkan_driver_available = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception as exc:
        logger.debug("Errore rilevamento driver Vulkan: %s", exc)

    if not vulkan_driver_available:
        return False

    if server_path and llama_server_supports_backend(server_path, "vulkan"):
        return True

    logger.warning(
        "Driver Vulkan presenti ma llama-server NON è compilato con supporto Vulkan. "
        "Soluzione: installa llama.cpp con supporto Vulkan "
        "(yay -S llama-cpp-git o compila con GGML_VULKAN=1).",
    )
    return False
