"""Backend GLM-OCR basato esclusivamente su llama-server + SYCL."""

from __future__ import annotations

import logging
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from config.constants import AppConstants, AppMeta
from core.cancellation import CancellationToken
from core.event_bus import EventBus
from core.exceptions import ModelLoadError, OperationCancelledError
from core.llama_gpu_detect import (
    GPU_OFFLOAD_ALL_LAYERS,
    detect_gpu_backend,
    find_llama_server,
    venv_lib_env,
)
from core.llama_models import ensure_gguf_models
from core.llama_ocr_api import ocr_pdf, ocr_single_image
from core.models import OCRResult

logger = logging.getLogger(__name__)

LLAMA_SERVER_HOST = "127.0.0.1"
# Compatibility aliases: canonical production values live in config.constants.
CONTEXT_SIZE = AppConstants.LLAMA_CONTEXT_SIZE
BATCH_SIZE = AppConstants.LLAMA_BATCH_SIZE
N_PARALLEL = 1
MAX_OCR_RETRIES = 1
SYCL_DEVICE = "llama-cpp-sycl"


def _production_runtime_args() -> list[str]:
    """Return the benchmark-selected production runtime flags for llama-server."""
    return [
        "-c",
        str(AppConstants.LLAMA_CONTEXT_SIZE),
        "-b",
        str(AppConstants.LLAMA_BATCH_SIZE),
        "-ub",
        str(AppConstants.LLAMA_UBATCH_SIZE),
        "-t",
        str(AppConstants.LLAMA_THREADS),
        "-tb",
        str(AppConstants.LLAMA_THREADS_BATCH),
        "-fa",
        AppConstants.LLAMA_FLASH_ATTN,
        "-ctk",
        AppConstants.LLAMA_CACHE_TYPE_K,
        "-ctv",
        AppConstants.LLAMA_CACHE_TYPE_V,
        "--spec-type",
        AppConstants.LLAMA_SPEC_TYPE,
        "-kvo" if AppConstants.LLAMA_KV_OFFLOAD else "-nkvo",
        "--op-offload" if AppConstants.LLAMA_OP_OFFLOAD else "--no-op-offload",
    ]

class LlamaServerBackend:
    """Gestisce esclusivamente un llama-server SYCL posseduto dall'app."""

    def __init__(self, preferred_device: str = SYCL_DEVICE) -> None:
        self._preferred_device = preferred_device
        self._process: subprocess.Popen[Any] | None = None
        self._process_lock = threading.RLock()
        self._server_path: str | None = None
        self._model_paths: dict[str, Path] = {}
        self._initialized = False
        self._server_port = 0
        self._server_url = ""
        self._gpu_layers = 0
        self._gpu_backend = "unavailable"
        self._log_file: Any = None

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def gpu_layers(self) -> int:
        return self._gpu_layers

    @property
    def gpu_backend(self) -> str:
        return self._gpu_backend

    @property
    def server_url(self) -> str:
        return self._server_url

    @property
    def is_server_running(self) -> bool:
        with self._process_lock:
            process = self._process
            url = self._server_url
        if process is None or process.poll() is not None or not url:
            return False
        try:
            with urlopen(Request(f"{url}/health"), timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def initialize(
        self, *, cancel_token: CancellationToken | None = None,
    ) -> None:
        """Trova runtime/modelli e avvia un server SYCL full-offload."""
        try:
            if self._preferred_device != SYCL_DEVICE:
                raise ModelLoadError(
                    "llama-server",
                    f"Backend non consentito: {self._preferred_device}. GLM OCR è SYCL-only.",
                )
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()

            self._server_path = find_llama_server()
            if not self._server_path:
                raise ModelLoadError(
                    "llama-server",
                    "llama-server SYCL non trovato. Esegui install.sh.",
                )

            self._model_paths = ensure_gguf_models(cancel_token=cancel_token)
            self._gpu_layers, self._gpu_backend = detect_gpu_backend(SYCL_DEVICE)
            if self._gpu_backend != "sycl":
                raise ModelLoadError(
                    "llama-server",
                    "Nessun device SYCL esposto da llama-server. "
                    "CPU e Vulkan sono disabilitati: ricompila con GGML_SYCL=ON.",
                )

            self._start_server_with_fallback(cancel_token=cancel_token)
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            self._initialized = True
        except Exception:
            self._initialized = False
            self._stop_server()
            raise

    @staticmethod
    def _allocate_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((LLAMA_SERVER_HOST, 0))
            return int(sock.getsockname()[1])

    def _start_server_with_fallback(
        self, *, cancel_token: CancellationToken | None = None,
    ) -> None:
        """Avvia esclusivamente il profilo SYCL full-offload.

        Il nome del metodo è mantenuto per compatibilità interna, ma non esiste
        alcun fallback: niente Vulkan, niente CPU-only e niente offload parziale.
        """
        if self._gpu_backend != "sycl":
            raise ModelLoadError(
                "llama-server",
                "Backend SYCL non disponibile; fallback disabilitati.",
            )
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        try:
            self._start_server(
                gpu_layers=GPU_OFFLOAD_ALL_LAYERS,
                gpu_backend="sycl",
                cancel_token=cancel_token,
            )
            self._gpu_layers = GPU_OFFLOAD_ALL_LAYERS
            self._gpu_backend = "sycl"
            logger.info("llama-server avviato: SYCL full offload")
        except OperationCancelledError:
            self._stop_server()
            raise
        except ModelLoadError:
            self._stop_server()
            raise

    def _start_server(
        self,
        *,
        gpu_layers: int,
        gpu_backend: str,
        cancel_token: CancellationToken | None,
    ) -> None:
        if not self._server_path:
            raise ModelLoadError("llama-server", "Percorso server mancante")
        if gpu_backend != "sycl" or gpu_layers < GPU_OFFLOAD_ALL_LAYERS:
            raise ModelLoadError(
                "llama-server",
                "Profilo non SYCL/full-offload rifiutato dalla configurazione strict.",
            )

        main_model = self._model_paths.get("main")
        mmproj_model = self._model_paths.get("mmproj")
        if main_model is None or not main_model.is_file():
            raise ModelLoadError(
                "llama-server", f"Modello GGUF non trovato: {main_model}"
            )
        if mmproj_model is None or not mmproj_model.is_file():
            raise ModelLoadError(
                "llama-server", f"Proiettore multimodale non trovato: {mmproj_model}"
            )

        port = self._allocate_port()
        url = f"http://{LLAMA_SERVER_HOST}:{port}"
        cmd = [
            self._server_path,
            "-m",
            str(main_model),
            "--mmproj",
            str(mmproj_model),
            "--port",
            str(port),
            "--host",
            LLAMA_SERVER_HOST,
            "-ngl",
            str(GPU_OFFLOAD_ALL_LAYERS),
            *_production_runtime_args(),
            "--parallel",
            str(N_PARALLEL),
            "--cache-ram",
            "0",
            "--metrics",
        ]

        env = venv_lib_env()
        env.update(
            {
                "GGML_SYCL": "1",
                "ONEAPI_DEVICE_SELECTOR": "level_zero:0",
                "ZES_ENABLE_SYSMAN": "1",
            }
        )

        AppMeta.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = AppMeta.CONFIG_DIR / "llama-server.log"
        if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
            log_path.unlink()

        EventBus.emit(
            "model_load_progress",
            {"message": "Avvio llama-server (SYCL full offload)..."},
        )

        log_file: Any = None
        try:
            log_file = open(log_path, "a", encoding="utf-8")
            process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=(os.name == "posix"),
            )
        except Exception as exc:
            if log_file is not None:
                try:
                    log_file.close()
                except Exception:
                    pass
            raise ModelLoadError(
                "llama-server", f"Impossibile avviare: {exc}"
            ) from exc

        with self._process_lock:
            self._log_file = log_file
            self._process = process
            self._server_port = port
            self._server_url = url

        def stop_owned_process() -> None:
            self._stop_server()

        if cancel_token is not None:
            cancel_token.register_closer(stop_owned_process)

        try:
            deadline = time.monotonic() + 90.0
            while time.monotonic() < deadline:
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                if process.poll() is not None:
                    tail = ""
                    try:
                        tail = log_path.read_text(
                            encoding="utf-8", errors="replace"
                        )[-2000:]
                    except OSError:
                        pass
                    raise ModelLoadError(
                        "llama-server",
                        f"Terminato con codice {process.returncode}. Log: {tail}",
                    )
                if self.is_server_running:
                    return
                time.sleep(0.25)
        finally:
            if cancel_token is not None:
                cancel_token.unregister_closer(stop_owned_process)

        self._stop_server()
        raise ModelLoadError(
            "llama-server", "Il server SYCL non ha risposto entro 90 secondi"
        )

    @staticmethod
    def _optimal_thread_count() -> int:
        n_cpu = os.cpu_count() or 8
        return max(2, min(n_cpu, max(4, n_cpu - 2)))

    def _stop_server(self) -> None:
        """Termina SOLO il process group creato da questa istanza."""
        with self._process_lock:
            process = self._process
            log_file = self._log_file
            self._process = None
            self._log_file = None
            self._server_url = ""
            self._server_port = 0

        if process is not None and process.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    if process.poll() is None:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                        process.wait(timeout=3)
                except Exception:
                    pass
            except Exception as exc:
                logger.warning("Errore arresto llama-server: %s", exc)

        if log_file is not None:
            try:
                log_file.close()
            except Exception:
                pass

    def _ensure_server_ready(
        self, *, cancel_token: CancellationToken | None,
    ) -> None:
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if self.is_server_running:
            return
        logger.warning("llama-server SYCL non disponibile; tento il riavvio strict")
        self._stop_server()
        self._start_server_with_fallback(cancel_token=cancel_token)
        if not self.is_server_running:
            raise ModelLoadError(
                "llama-server", "Server SYCL non disponibile dopo il riavvio"
            )

    def process_image(
        self,
        image_path: Path,
        *,
        mode: str = "single",
        cancel_token: CancellationToken | None = None,
        preprocessing_enabled: bool = True,
    ) -> OCRResult:
        from core.image_utils import is_pdf

        if not self._initialized:
            raise ModelLoadError("llama-server", "Server non inizializzato")
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()

        self._ensure_server_ready(cancel_token=cancel_token)
        is_pdf_file = is_pdf(image_path)
        start = time.perf_counter()
        last_exc: Exception | None = None

        max_retries = 0 if is_pdf_file and mode == "single" else MAX_OCR_RETRIES

        for attempt in range(max_retries + 1):
            try:
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                if is_pdf_file:
                    text, confidence = ocr_pdf(
                        image_path,
                        self._server_url,
                        preprocessing_enabled=preprocessing_enabled,
                        cancel_token=cancel_token,
                        emit_events=(mode == "single"),
                        event_mode=mode,
                    )
                else:
                    text, confidence = ocr_single_image(
                        image_path,
                        self._server_url,
                        preprocessing_enabled=preprocessing_enabled,
                        cancel_token=cancel_token,
                    )

                elapsed_ms = (time.perf_counter() - start) * 1000
                return OCRResult(
                    text=text,
                    confidence=confidence,
                    processing_time_ms=elapsed_ms,
                    device_used="GPU SYCL (llama.cpp)",
                )
            except OperationCancelledError:
                raise
            except Exception as exc:
                last_exc = exc
                with self._process_lock:
                    process = self._process
                crashed = (
                    process is None
                    or process.poll() is not None
                    or "remote end closed connection" in str(exc).lower()
                    or "connection reset" in str(exc).lower()
                    or "connection refused" in str(exc).lower()
                )
                if crashed and attempt < max_retries:
                    logger.warning(
                        "llama-server SYCL crashato durante OCR; riavvio e retry %d/%d",
                        attempt + 1,
                        max_retries,
                    )
                    self._stop_server()
                    self._start_server_with_fallback(cancel_token=cancel_token)
                    continue
                break

        raise ModelLoadError(
            "llama-server", f"OCR fallito per {image_path.name}: {last_exc}"
        )

    def shutdown(self) -> None:
        self._initialized = False
        self._stop_server()
