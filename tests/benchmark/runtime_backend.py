"""Benchmark-only llama-server runtime tuning.

Production ``LlamaServerBackend`` is intentionally untouched.  This module uses
exactly the same SYCL runtime/model discovery and owned-process lifecycle, but
lets the canonical hardware benchmark vary inference/runtime flags.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Any

from config.constants import AppMeta
from core.event_bus import EventBus
from core.exceptions import ModelLoadError
from core.llama_backend import (
    LLAMA_SERVER_HOST,
    N_PARALLEL,
    LlamaServerBackend,
)
from core.llama_gpu_detect import GPU_OFFLOAD_ALL_LAYERS, find_llama_server, venv_lib_env

CACHE_TYPES = ("f16", "bf16", "q8_0", "q5_0", "q4_0")
FLASH_ATTN_VALUES = ("auto", "on", "off")
SPEC_TYPES = ("none", "draft-mtp")
BENCHMARK_BASELINE_CONTEXT_SIZE = 8192


@dataclass(frozen=True)
class ServerRuntimeConfig:
    context_size: int = 4096
    batch_size: int = 1024
    ubatch_size: int = 512
    threads: int = 0
    threads_batch: int = 0
    flash_attn: str = "auto"
    cache_type_k: str = "f16"
    cache_type_v: str = "f16"
    spec_type: str = "none"
    kv_offload: bool = True
    op_offload: bool = True

    def resolved(self) -> "ServerRuntimeConfig":
        optimal = LlamaServerBackend._optimal_thread_count()
        threads = int(self.threads) if int(self.threads) > 0 else optimal
        threads_batch = int(self.threads_batch) if int(self.threads_batch) > 0 else threads
        result = ServerRuntimeConfig(
            context_size=int(self.context_size),
            batch_size=int(self.batch_size),
            ubatch_size=int(self.ubatch_size),
            threads=threads,
            threads_batch=threads_batch,
            flash_attn=str(self.flash_attn).lower(),
            cache_type_k=str(self.cache_type_k).lower(),
            cache_type_v=str(self.cache_type_v).lower(),
            spec_type=str(self.spec_type).lower(),
            kv_offload=bool(self.kv_offload),
            op_offload=bool(self.op_offload),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if not 1024 <= int(self.context_size) <= 32768:
            raise ValueError("context_size fuori range 1024..32768")
        if not 32 <= int(self.batch_size) <= 8192:
            raise ValueError("batch_size fuori range 32..8192")
        if not 32 <= int(self.ubatch_size) <= int(self.batch_size):
            raise ValueError("ubatch_size deve essere 32..batch_size")
        if int(self.threads) < 1 or int(self.threads_batch) < 1:
            raise ValueError("threads/threads_batch devono essere >= 1")
        if self.flash_attn not in FLASH_ATTN_VALUES:
            raise ValueError(f"flash_attn non valido: {self.flash_attn}")
        if self.cache_type_k not in CACHE_TYPES or self.cache_type_v not in CACHE_TYPES:
            raise ValueError("tipo KV cache non supportato dalla suite")
        if self.spec_type not in SPEC_TYPES:
            raise ValueError(f"spec_type non valido: {self.spec_type}")

    def signature(self) -> str:
        r = self.resolved()
        return (
            f"ctx{r.context_size}-b{r.batch_size}-ub{r.ubatch_size}-"
            f"t{r.threads}-tb{r.threads_batch}-fa{r.flash_attn}-"
            f"k{r.cache_type_k}-v{r.cache_type_v}-spec{r.spec_type}-"
            f"kvo{int(r.kv_offload)}-opo{int(r.op_offload)}"
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.resolved())


def production_runtime_config() -> ServerRuntimeConfig:
    """Return the production-like benchmark baseline with a safe context budget.

    The application runtime remains untouched.  The real-world benchmark uses
    an 8192-token context baseline so DPI/image sweeps cannot be rejected merely
    because a long OCR transcription is truncated at the historical 4096-token
    benchmark context.  Stage A still explicitly tests smaller context sizes.
    """
    optimal = LlamaServerBackend._optimal_thread_count()
    return ServerRuntimeConfig(
        context_size=BENCHMARK_BASELINE_CONTEXT_SIZE,
        threads=optimal,
        threads_batch=optimal,
    ).resolved()


@dataclass(frozen=True)
class RuntimeCapabilities:
    server_path: str
    version: str
    supported: dict[str, bool]


def detect_runtime_capabilities() -> RuntimeCapabilities:
    server_path = find_llama_server()
    if not server_path:
        raise RuntimeError("llama-server non trovato; esegui ./install.sh")
    env = venv_lib_env()
    env.update(
        {
            "GGML_SYCL": "1",
            "ONEAPI_DEVICE_SELECTOR": "level_zero:0",
            "ZES_ENABLE_SYSMAN": "1",
        }
    )
    help_proc = subprocess.run(
        [server_path, "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=20,
        env=env,
        check=False,
    )
    help_text = help_proc.stdout or ""
    version_proc = subprocess.run(
        [server_path, "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=20,
        env=env,
        check=False,
    )
    version = (version_proc.stdout or "").strip().splitlines()
    supported = {
        "context_size": "--ctx-size" in help_text,
        "batch_size": "--batch-size" in help_text,
        "ubatch_size": "--ubatch-size" in help_text,
        "threads": "--threads " in help_text,
        "threads_batch": "--threads-batch" in help_text,
        "flash_attn": "--flash-attn" in help_text,
        "cache_type_k": "--cache-type-k" in help_text,
        "cache_type_v": "--cache-type-v" in help_text,
        "spec_type": "--spec-type" in help_text and "draft-mtp" in help_text,
        "kv_offload": "--kv-offload" in help_text,
        "op_offload": "--op-offload" in help_text,
    }
    return RuntimeCapabilities(
        server_path=server_path,
        version=version[0] if version else "unknown",
        supported=supported,
    )


def thread_candidates() -> tuple[int, ...]:
    n_cpu = os.cpu_count() or 8
    optimal = LlamaServerBackend._optimal_thread_count()
    values = {2, 4, max(2, n_cpu // 2), optimal, n_cpu}
    return tuple(sorted(value for value in values if 1 <= value <= n_cpu))


def runtime_stage_a_values(capabilities: RuntimeCapabilities) -> dict[str, list[Any]]:
    candidates: dict[str, list[Any]] = {
        "context_size": [2048, 3072, 4096, 6144, 8192],
        "batch_size": [256, 512, 1024, 1536, 2048, 4096],
        "ubatch_size": [128, 256, 512, 768, 1024],
        "threads": list(thread_candidates()),
        "threads_batch": list(thread_candidates()),
        "flash_attn": list(FLASH_ATTN_VALUES),
        "cache_type_k": list(CACHE_TYPES),
        "cache_type_v": list(CACHE_TYPES),
        "spec_type": list(SPEC_TYPES),
        "kv_offload": [True, False],
        "op_offload": [True, False],
    }
    return {
        key: values
        for key, values in candidates.items()
        if capabilities.supported.get(key, False)
    }


class BenchmarkLlamaServerBackend(LlamaServerBackend):
    """Owned SYCL backend with one explicit benchmark runtime profile."""

    def __init__(self, runtime: ServerRuntimeConfig) -> None:
        super().__init__()
        self.runtime = runtime.resolved()

    @property
    def process_pid(self) -> int | None:
        with self._process_lock:
            process = self._process
        return None if process is None else int(process.pid)

    def _start_server(
        self,
        *,
        gpu_layers: int,
        gpu_backend: str,
        cancel_token,
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
            raise ModelLoadError("llama-server", f"Modello GGUF non trovato: {main_model}")
        if mmproj_model is None or not mmproj_model.is_file():
            raise ModelLoadError("llama-server", f"Proiettore multimodale non trovato: {mmproj_model}")

        runtime = self.runtime
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
            "-c",
            str(runtime.context_size),
            "-b",
            str(runtime.batch_size),
            "-ub",
            str(runtime.ubatch_size),
            "-t",
            str(runtime.threads),
            "-tb",
            str(runtime.threads_batch),
            "--parallel",
            str(N_PARALLEL),
            "--cache-ram",
            "0",
            "--metrics",
            "-fa",
            runtime.flash_attn,
            "-ctk",
            runtime.cache_type_k,
            "-ctv",
            runtime.cache_type_v,
            "--spec-type",
            runtime.spec_type,
            "-kvo" if runtime.kv_offload else "-nkvo",
            "--op-offload" if runtime.op_offload else "--no-op-offload",
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
        log_path = AppMeta.CONFIG_DIR / "llama-server-benchmark.log"
        if log_path.exists() and log_path.stat().st_size > 10 * 1024 * 1024:
            log_path.unlink()

        EventBus.emit(
            "model_load_progress",
            {"message": f"Benchmark llama-server: {runtime.signature()}"},
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
            raise ModelLoadError("llama-server", f"Impossibile avviare benchmark runtime: {exc}") from exc

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
                        tail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
                    except OSError:
                        pass
                    raise ModelLoadError(
                        "llama-server",
                        f"Profilo runtime non avviabile (exit {process.returncode}): {tail}",
                    )
                if self.is_server_running:
                    return
                time.sleep(0.25)
        finally:
            if cancel_token is not None:
                cancel_token.unregister_closer(stop_owned_process)

        self._stop_server()
        raise ModelLoadError("llama-server", "Profilo runtime non pronto entro 90 secondi")


def process_rss_mib(pid: int | None) -> float | None:
    if pid is None or os.name != "posix":
        return None
    try:
        for line in open(f"/proc/{pid}/status", "r", encoding="utf-8"):
            if line.startswith("VmRSS:"):
                kib = float(line.split()[1])
                return kib / 1024.0
    except OSError:
        return None
    return None
