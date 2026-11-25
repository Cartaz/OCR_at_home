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

from config.constants import AppMeta
from core.cancellation import CancellationToken
from core.event_bus import EventBus
from core.exceptions import ModelLoadError, OCRProcessingError, OperationCancelledError
from core.image_utils import is_pdf
from core.llama_gpu_detect import (
    GPU_OFFLOAD_ALL_LAYERS,
    find_llama_server,
    list_sycl_devices,
    sycl_runtime_env,
)
from core.llama_models import ensure_gguf_models
from core.llama_ocr_api import LlamaServerConnectionError, ocr_pdf, ocr_single_image
from core.models import OCRResult, combine_pdf_pages
from core.owned_process import spawn_owned_process

logger = logging.getLogger(__name__)

LLAMA_SERVER_HOST = "127.0.0.1"
N_PARALLEL = 1
MAX_OCR_RETRIES = 1
STARTUP_TIMEOUT_S = 90.0


class LlamaServerBackend:
    """Own one SYCL full-offload ``llama-server`` process for this application.

    Subclasses (the hardware benchmark) customize the runtime through
    :meth:`_runtime_args`, :meth:`_log_path` and :meth:`_startup_message`;
    process ownership, readiness and teardown stay here.
    """

    _LOG_MAX_BYTES = 5 * 1024 * 1024

    def __init__(self) -> None:
        self._process: subprocess.Popen[Any] | None = None
        self._process_group_id: int | None = None
        self._process_lock = threading.RLock()
        self._server_path: str | None = None
        self._model_paths: dict[str, Path] = {}
        self._initialized = False
        self._server_url = ""
        self._log_file: Any = None
        self._active_log_path: Path | None = None
        self._log_start_offset = 0

    # --- customization points ---------------------------------------------

    def _runtime_args(self) -> list[str]:
        """Production passes no tuning flags: llama.cpp keeps its stock defaults."""
        return []

    def _log_path(self) -> Path:
        return AppMeta.LLAMA_SERVER_LOG_PATH

    def _startup_message(self) -> str:
        return "Avvio llama-server (SYCL full offload)..."

    # --- lifecycle ----------------------------------------------------------

    @property
    def is_initialized(self) -> bool:
        return self._initialized

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

    def initialize(self, *, cancel_token: CancellationToken | None = None) -> None:
        """Locate runtime and models, then start a SYCL full-offload server."""
        try:
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            self._server_path = find_llama_server()
            if not self._server_path:
                raise ModelLoadError(
                    "llama-server", "llama-server SYCL non trovato. Esegui install.sh."
                )
            self._model_paths = ensure_gguf_models(cancel_token=cancel_token)
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            if not list_sycl_devices(self._server_path):
                raise ModelLoadError(
                    "llama-server",
                    "Nessun device SYCL esposto da llama-server. "
                    "CPU e Vulkan sono disabilitati: ricompila con GGML_SYCL=ON.",
                )
            self._start_server(cancel_token=cancel_token)
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

    def _start_server(self, *, cancel_token: CancellationToken | None) -> None:
        if not self._server_path:
            raise ModelLoadError("llama-server", "Percorso server mancante")
        main_model = self._model_paths.get("main")
        mmproj_model = self._model_paths.get("mmproj")
        if main_model is None or not main_model.is_file():
            raise ModelLoadError("llama-server", f"Modello GGUF non trovato: {main_model}")
        if mmproj_model is None or not mmproj_model.is_file():
            raise ModelLoadError(
                "llama-server", f"Proiettore multimodale non trovato: {mmproj_model}"
            )
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()

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
            *self._runtime_args(),
            "--parallel",
            str(N_PARALLEL),
            "--metrics",
        ]

        log_path = self._log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists() and log_path.stat().st_size > self._LOG_MAX_BYTES:
            log_path.unlink()
        log_start_offset = log_path.stat().st_size if log_path.exists() else 0

        EventBus.emit("model_load_progress", {"message": self._startup_message()})

        log_file: Any = None
        try:
            log_file = open(log_path, "a", encoding="utf-8")
            handle = spawn_owned_process(cmd, stdout=log_file, env=sycl_runtime_env())
            process = handle.process
        except Exception as exc:
            if log_file is not None:
                try:
                    log_file.close()
                except Exception:
                    pass
            raise ModelLoadError("llama-server", f"Impossibile avviare: {exc}") from exc

        with self._process_lock:
            self._log_file = log_file
            self._process = process
            self._process_group_id = handle.process_group_id
            self._server_url = url
            self._active_log_path = log_path
            self._log_start_offset = log_start_offset

        def stop_owned_process() -> None:
            # Runs on the cancelling (GUI) thread: only signal. The startup
            # loop below sees the cancellation and performs the blocking stop.
            self._signal_server_stop()

        if cancel_token is not None:
            cancel_token.register_closer(stop_owned_process)
        try:
            deadline = time.monotonic() + STARTUP_TIMEOUT_S
            while time.monotonic() < deadline:
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                if process.poll() is not None:
                    raise ModelLoadError(
                        "llama-server",
                        f"Terminato con codice {process.returncode}. "
                        f"Log: {self._read_log_tail(2000)}",
                    )
                if self.is_server_running:
                    logger.info("llama-server avviato: SYCL full offload")
                    return
                time.sleep(0.25)
        finally:
            if cancel_token is not None:
                cancel_token.unregister_closer(stop_owned_process)

        self._stop_server()
        raise ModelLoadError(
            "llama-server",
            f"Il server SYCL non ha risposto entro {int(STARTUP_TIMEOUT_S)} secondi",
        )

    def _read_log_tail(self, max_chars: int) -> str:
        """Return this server instance's log output (since its start), bounded."""
        with self._process_lock:
            log_path = self._active_log_path
            start_offset = self._log_start_offset
        if log_path is None:
            return ""
        try:
            size = log_path.stat().st_size
            with log_path.open("rb") as handle:
                handle.seek(min(max(0, start_offset), size))
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        return text[-max(0, int(max_chars)):]

    def _stop_server(self) -> None:
        """Terminate only this instance's owned process group, idempotently."""
        with self._process_lock:
            process = self._process
            process_group_id = self._process_group_id
            log_file = self._log_file
            self._process = None
            self._process_group_id = None
            self._log_file = None
            self._server_url = ""

        if process is not None:
            try:
                if os.name == "posix" and process_group_id is not None:
                    # Signal the group even when the leader already exited: this
                    # also removes surviving helper children instead of orphaning them.
                    os.killpg(process_group_id, signal.SIGTERM)
                elif process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                try:
                    if os.name == "posix" and process_group_id is not None:
                        os.killpg(process_group_id, signal.SIGKILL)
                    elif process.poll() is None:
                        process.kill()
                    process.wait(timeout=3)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    pass
            except Exception as exc:
                logger.warning("Errore arresto llama-server: %s", exc)

        if log_file is not None:
            try:
                log_file.close()
            except Exception:
                pass

    def _signal_server_stop(self) -> None:
        """Ask the owned server to exit without waiting for it."""
        with self._process_lock:
            process = self._process
            process_group_id = self._process_group_id
        if process is None or process.poll() is not None:
            return
        try:
            if os.name == "posix" and process_group_id is not None:
                os.killpg(process_group_id, signal.SIGTERM)
            else:
                process.terminate()
        except (ProcessLookupError, OSError):
            pass

    def _server_crashed(self) -> bool:
        with self._process_lock:
            process = self._process
        return process is None or process.poll() is not None

    def _ensure_server_ready(self, *, cancel_token: CancellationToken | None) -> None:
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if self.is_server_running:
            return
        logger.warning("llama-server SYCL non disponibile; riavvio")
        self._stop_server()
        self._start_server(cancel_token=cancel_token)

    def process_image(
        self,
        image_path: Path,
        *,
        mode: str = "single",
        cancel_token: CancellationToken | None = None,
        preprocessing_enabled: bool = True,
    ) -> OCRResult:
        if not self._initialized:
            raise ModelLoadError("llama-server", "Server non inizializzato")
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()

        self._ensure_server_ready(cancel_token=cancel_token)
        is_pdf_file = is_pdf(image_path)
        start = time.perf_counter()
        last_exc: Exception | None = None
        # A single-document PDF streams pages to the UI: replaying the whole
        # document after a crash would duplicate already shown pages.
        max_retries = 0 if is_pdf_file and mode == "single" else MAX_OCR_RETRIES

        for attempt in range(max_retries + 1):
            try:
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                if is_pdf_file:
                    pages = tuple(
                        ocr_pdf(
                            image_path,
                            self._server_url,
                            preprocessing_enabled=preprocessing_enabled,
                            cancel_token=cancel_token,
                            emit_events=(mode == "single"),
                            event_mode=mode,
                        )
                    )
                    text = combine_pdf_pages(pages)
                else:
                    pages = ()
                    text = ocr_single_image(
                        image_path,
                        self._server_url,
                        preprocessing_enabled=preprocessing_enabled,
                        cancel_token=cancel_token,
                    )
                return OCRResult(
                    text=text,
                    pages=pages,
                    processing_time_ms=(time.perf_counter() - start) * 1000,
                )
            except OperationCancelledError:
                raise
            except Exception as exc:
                last_exc = exc
                crashed = isinstance(exc, LlamaServerConnectionError) or self._server_crashed()
                if crashed and attempt < max_retries:
                    logger.warning(
                        "llama-server SYCL non raggiungibile durante OCR; riavvio e retry %d/%d",
                        attempt + 1,
                        max_retries,
                    )
                    self._stop_server()
                    self._start_server(cancel_token=cancel_token)
                    continue
                break

        raise OCRProcessingError(image_path.name, str(last_exc)) from last_exc

    def shutdown(self) -> None:
        self._initialized = False
        self._stop_server()
