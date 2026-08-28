"""Regression tests for benchmark-only llama-server diagnostics."""

from __future__ import annotations

from types import SimpleNamespace

from tests.benchmark.runtime_backend import (
    BenchmarkLlamaServerBackend,
    ServerRuntimeConfig,
)


def test_failure_diagnostics_do_not_inherit_old_oom_log_entries(tmp_path) -> None:
    backend = BenchmarkLlamaServerBackend(ServerRuntimeConfig(threads=2, threads_batch=2))
    log_path = tmp_path / "llama-server-benchmark.log"
    old = "ZE_RESULT_ERROR_OUT_OF_DEVICE_MEMORY\n"
    current = "server exited after connection reset\n"
    log_path.write_text(old + current, encoding="utf-8")

    backend._process = SimpleNamespace(poll=lambda: 1)  # type: ignore[attr-defined]
    backend._benchmark_log_path = log_path  # type: ignore[attr-defined]
    backend._benchmark_log_start_offset = len(old.encode("utf-8"))  # type: ignore[attr-defined]

    diagnostics = backend.failure_diagnostics()

    assert diagnostics.process_exited is True
    assert diagnostics.returncode == 1
    assert diagnostics.suspected_oom is False
    assert current.strip() in diagnostics.log_tail
    assert "OUT_OF_DEVICE_MEMORY" not in diagnostics.log_tail


def test_failure_diagnostics_recognize_current_oom_marker(tmp_path) -> None:
    backend = BenchmarkLlamaServerBackend(ServerRuntimeConfig(threads=2, threads_batch=2))
    log_path = tmp_path / "llama-server-benchmark.log"
    log_path.write_text(
        "ggml-sycl: ZE_RESULT_ERROR_OUT_OF_DEVICE_MEMORY\n",
        encoding="utf-8",
    )

    backend._process = SimpleNamespace(poll=lambda: 1)  # type: ignore[attr-defined]
    backend._benchmark_log_path = log_path  # type: ignore[attr-defined]
    backend._benchmark_log_start_offset = 0  # type: ignore[attr-defined]

    diagnostics = backend.failure_diagnostics()

    assert diagnostics.suspected_oom is True
