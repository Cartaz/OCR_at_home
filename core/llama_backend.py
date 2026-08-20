"""Backend GLM-OCR basato su un processo llama-server posseduto dall'app."""

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

from config.constants import AppMeta
from core.cancellation import CancellationToken
from core.event_bus import EventBus
from core.exceptions import ModelLoadError, OperationCancelledError
from core.llama_gpu_detect import GPU_OFFLOAD_ALL_LAYERS, GPU_OFFLOAD_PARTIAL_LAYERS, detect_gpu_backend, find_llama_server, venv_lib_env
from core.llama_models import ensure_gguf_models
from core.llama_ocr_api import ocr_pdf, ocr_single_image
from core.models import OCRResult

logger = logging.getLogger(__name__)
LLAMA_SERVER_HOST = "127.0.0.1"
CONTEXT_SIZE = 4096
BATCH_SIZE = 1024
N_PARALLEL = 1
MAX_OCR_RETRIES = 1


class LlamaServerBackend:
    """Gestisce esclusivamente il llama-server avviato da questa istanza."""

    def __init__(self, preferred_device: str = "llama-cpp-sycl") -> None:
        self._preferred_device = preferred_device
        self._process: subprocess.Popen[Any] | None = None
        self._process_lock = threading.RLock()
        self._server_path: str | None = None
        self._model_paths: dict[str, Path] = {}
        self._initialized = False
        self._server_port = 0
        self._server_url = ""
        self._gpu_layers = 0
        self._gpu_backend = "cpu"
        self._log_file: Any = None

    @property
    def is_initialized(self) -> bool: return self._initialized
    @property
    def gpu_layers(self) -> int: return self._gpu_layers
    @property
    def gpu_backend(self) -> str: return self._gpu_backend
    @property
    def server_url(self) -> str: return self._server_url

    @property
    def is_server_running(self) -> bool:
        with self._process_lock:
            process, url = self._process, self._server_url
        if process is None or process.poll() is not None or not url:
            return False
        try:
            with urlopen(Request(f"{url}/health"), timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def initialize(self, *, cancel_token: CancellationToken | None = None) -> None:
        if cancel_token is not None: cancel_token.raise_if_cancelled()
        self._server_path = find_llama_server()
        if not self._server_path:
            raise ModelLoadError("llama-server", "llama-server non trovato. Esegui install.sh oppure installa llama.cpp.")
        self._model_paths = ensure_gguf_models(cancel_token=cancel_token)
        self._gpu_layers, self._gpu_backend = detect_gpu_backend(self._preferred_device)
        if self._preferred_device == "llama-cpp-sycl" and self._gpu_backend != "sycl":
            raise ModelLoadError("llama-server", "Backend SYCL richiesto ma binary/driver SYCL non disponibile. Seleziona llama.cpp generico oppure ricompila con GGML_SYCL=1.")
        self._start_server_with_fallback(cancel_token=cancel_token)
        if cancel_token is not None: cancel_token.raise_if_cancelled()
        self._initialized = True

    @staticmethod
    def _allocate_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((LLAMA_SERVER_HOST, 0))
            return int(sock.getsockname()[1])

    def _start_server_with_fallback(self, *, cancel_token: CancellationToken | None = None) -> None:
        configs: list[tuple[int, str, str]] = []
        if self._gpu_backend in ("sycl", "vulkan") and self._gpu_layers > 0:
            configs.extend([
                (GPU_OFFLOAD_ALL_LAYERS, self._gpu_backend, f"GPU full offload ({self._gpu_backend.upper()})"),
                (GPU_OFFLOAD_PARTIAL_LAYERS, self._gpu_backend, f"GPU partial offload ({self._gpu_backend.upper()})"),
            ])
        if self._preferred_device != "llama-cpp-sycl": configs.append((0, "cpu", "CPU-only"))
        if not configs: configs.append((0, "cpu", "CPU-only"))
        last_error: Exception | None = None
        for gpu_layers, gpu_backend, label in configs:
            if cancel_token is not None: cancel_token.raise_if_cancelled()
            try:
                self._start_server(gpu_layers=gpu_layers, gpu_backend=gpu_backend, cancel_token=cancel_token)
                self._gpu_layers, self._gpu_backend = gpu_layers, gpu_backend
                logger.info("llama-server avviato: %s", label)
                return
            except OperationCancelledError:
                self._stop_server(); raise
            except ModelLoadError as exc:
                last_error = exc
                self._stop_server()
        raise ModelLoadError("llama-server", f"Nessun profilo di avvio riuscito: {last_error}")

    def _start_server(self, *, gpu_layers: int, gpu_backend: str, cancel_token: CancellationToken | None) -> None:
        if not self._server_path: raise ModelLoadError("llama-server", "Percorso server mancante")
        main_model, mmproj = self._model_paths.get("main"), self._model_paths.get("mmproj")
        if main_model is None or not main_model.is_file(): raise ModelLoadError("llama-server", f"Modello GGUF non trovato: {main_model}")
        port = self._allocate_port()
        url = f"http://{LLAMA_SERVER_HOST}:{port}"
        cmd = [self._server_path, "-m", str(main_model), "--port", str(port), "--host", LLAMA_SERVER_HOST, "-ngl", str(gpu_layers), "-c", str(CONTEXT_SIZE), "-b", str(BATCH_SIZE), "-t", str(self._optimal_thread_count()), "--parallel", str(N_PARALLEL), "--cache-ram", "0", "--metrics"]
        if mmproj is not None and mmproj.is_file(): cmd.extend(["--mmproj", str(mmproj)])
        env = venv_lib_env()
        if gpu_backend == "sycl" and gpu_layers > 0:
            env.update({"GGML_SYCL": "1", "ONEAPI_DEVICE_SELECTOR": "level_zero:0", "ZES_ENABLE_SYSMAN": "1"})
        AppMeta.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = AppMeta.CONFIG_DIR / "llama-server.log"
        if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024: log_path.unlink()
        EventBus.emit("model_load_progress", {"message": f"Avvio llama-server ({'GPU' if gpu_layers > 0 else 'CPU'})..."})
        try:
            log_file = open(log_path, "a", encoding="utf-8")
            process = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, env=env, start_new_session=(os.name == "posix"))
        except Exception as exc:
            raise ModelLoadError("llama-server", f"Impossibile avviare: {exc}") from exc
        with self._process_lock:
            self._log_file, self._process = log_file, process
            self._server_port, self._server_url = port, url
        def stop_owned_process() -> None: self._stop_server()
        if cancel_token is not None: cancel_token.register_closer(stop_owned_process)
        try:
            deadline = time.monotonic() + 90.0
            while time.monotonic() < deadline:
                if cancel_token is not None: cancel_token.raise_if_cancelled()
                if process.poll() is not None:
                    tail = ""
                    try: tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                    except OSError: pass
                    raise ModelLoadError("llama-server", f"Terminato con codice {process.returncode}. Log: {tail}")
                if self.is_server_running: return
                time.sleep(0.25)
        finally:
            if cancel_token is not None: cancel_token.unregister_closer(stop_owned_process)
        self._stop_server()
        raise ModelLoadError("llama-server", "Il server non ha risposto entro 90 secondi")

    @staticmethod
    def _optimal_thread_count() -> int:
        n_cpu = os.cpu_count() or 8
        return max(2, min(n_cpu, max(4, n_cpu - 2)))

    def _stop_server(self) -> None:
        """Termina SOLO il process group creato da questa istanza."""
        with self._process_lock:
            process, log_file = self._process, self._log_file
            self._process = self._log_file = None
            self._server_url = ""; self._server_port = 0
        if process is not None and process.poll() is None:
            try:
                if os.name == "posix": os.killpg(process.pid, signal.SIGTERM)
                else: process.terminate()
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    if process.poll() is None:
                        if os.name == "posix": os.killpg(process.pid, signal.SIGKILL)
                        else: process.kill()
                        process.wait(timeout=3)
                except Exception: pass
            except Exception as exc: logger.warning("Errore arresto llama-server: %s", exc)
        if log_file is not None:
            try: log_file.close()
            except Exception: pass

    def process_image(self, image_path: Path, *, mode: str = "single", cancel_token: CancellationToken | None = None, preprocessing_enabled: bool = True) -> OCRResult:
        from core.image_utils import is_pdf
        if not self._initialized: raise ModelLoadError("llama-server", "Server non inizializzato")
        if cancel_token is not None: cancel_token.raise_if_cancelled()
        self._check_server_alive()
        is_pdf_file = is_pdf(image_path)
        start = time.perf_counter(); last_exc: Exception | None = None
        for attempt in range(MAX_OCR_RETRIES + 1):
            try:
                if cancel_token is not None: cancel_token.raise_if_cancelled()
                if is_pdf_file:
                    text, confidence = ocr_pdf(image_path, self._server_url, preprocessing_enabled=preprocessing_enabled, cancel_token=cancel_token, emit_events=(mode == "single"), event_mode=mode)
                else:
                    text, confidence = ocr_single_image(image_path, self._server_url, preprocessing_enabled=preprocessing_enabled, cancel_token=cancel_token)
                elapsed_ms = (time.perf_counter() - start) * 1000
                device_label = "CPU (llama.cpp)"
                if self._gpu_layers > 0:
                    kind = "GPU" if self._gpu_layers >= GPU_OFFLOAD_ALL_LAYERS else "GPU+CPU"
                    device_label = f"{kind} {self._gpu_backend.upper()} (llama.cpp)"
                return OCRResult(text=text, confidence=confidence, processing_time_ms=elapsed_ms, device_used=device_label)
            except OperationCancelledError: raise
            except Exception as exc:
                last_exc = exc
                process = self._process
                crashed = process is None or process.poll() is not None or "Remote end closed connection" in str(exc)
                if crashed and attempt < MAX_OCR_RETRIES:
                    self._stop_server(); self._start_server_with_fallback(cancel_token=cancel_token); continue
                break
        raise ModelLoadError("llama-server", f"OCR fallito per {image_path.name}: {last_exc}")

    def _check_server_alive(self) -> None:
        with self._process_lock: process = self._process
        if process is None or process.poll() is not None:
            self._initialized = False
            raise ModelLoadError("llama-server", "Il processo llama-server non è attivo")
        if not self.is_server_running: raise ModelLoadError("llama-server", "llama-server non risponde al health check")

    def shutdown(self) -> None:
        self._stop_server(); self._initialized = False
