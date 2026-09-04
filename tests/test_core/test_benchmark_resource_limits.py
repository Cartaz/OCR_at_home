"""Regression tests for benchmark resource-limit safety and resume semantics."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.benchmark import run_realworld_suite_v2 as runner
from tests.benchmark.memory_guard import (
    MEMORY_ISOLATION_VERSION,
    MEMORY_PRESSURE_FLOOR_MIB,
    MemorySampler,
    SystemMemorySnapshot,
)
from tests.benchmark.realworld_suite_v2 import (
    BenchmarkDocument,
    Observation,
    PipelineConfig,
    observation_to_dict,
)


def _snapshot(available_mib: float, *, monotonic_s: float) -> SystemMemorySnapshot:
    return SystemMemorySnapshot(
        monotonic_s=monotonic_s,
        mem_total_mib=16000.0,
        mem_free_mib=max(0.0, available_mib - 512.0),
        mem_available_mib=available_mib,
        cached_mib=1024.0,
        anon_pages_mib=4096.0,
        swap_total_mib=16000.0,
        swap_free_mib=15000.0,
    )


class _Diagnostics:
    process_exited = False
    suspected_oom = False

    def to_dict(self) -> dict[str, object]:
        return {
            "process_exited": False,
            "returncode": None,
            "suspected_oom": False,
            "log_tail": "",
        }


class _Backend:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    @property
    def is_server_running(self) -> bool:
        return True

    def failure_diagnostics(self) -> _Diagnostics:
        return _Diagnostics()

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _failed_observation(*, available_mib: float) -> Observation:
    return Observation(
        stage="stage",
        config_id="config",
        run_index=1,
        level="medio",
        elapsed_s=1.0,
        cer=None,
        wer=None,
        char_accuracy=None,
        output_file="",
        metrics={
            "memory": {
                "mem_available_min_mib": available_mib,
                "pressure_triggered": available_mib <= MEMORY_PRESSURE_FLOOR_MIB,
            }
        },
        segment_scores={},
        error="connection refused",
    )


def test_memory_sampler_triggers_owned_process_guard_once() -> None:
    readings = iter(
        (
            _snapshot(1200.0, monotonic_s=0.0),
            _snapshot(200.0, monotonic_s=0.1),
            _snapshot(180.0, monotonic_s=0.2),
        )
    )
    critical: list[float] = []
    sampler = MemorySampler(
        10,
        system_reader=lambda: next(readings),
        rss_reader=lambda _pid: 1.0,
        harness_pid=20,
        critical_available_mib=MEMORY_PRESSURE_FLOOR_MIB,
        on_critical=lambda snapshot: critical.append(snapshot.mem_available_mib),
    )

    sampler.sample_now()
    sampler.sample_now()
    sampler.sample_now()
    metrics = sampler.to_dict()

    assert MEMORY_ISOLATION_VERSION == 3
    assert critical == [200.0]
    assert metrics["pressure_triggered"] is True
    assert metrics["critical_available_mib"] == MEMORY_PRESSURE_FLOOR_MIB
    assert metrics["pressure_snapshot"]["mem_available_mib"] == 200.0


def test_low_memory_failure_is_terminal_without_retry(monkeypatch) -> None:
    backend = _Backend()
    calls = 0

    def run_once(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _failed_observation(available_mib=128.0)

    monkeypatch.setattr(runner, "_run_document", run_once)
    monkeypatch.setattr(
        runner,
        "_start_backend",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("resource-limit request must not restart")
        ),
    )

    observation, returned_backend, _rss = runner._run_document_with_recovery(
        "stage",
        PipelineConfig(name="config"),
        1,
        BenchmarkDocument("medio", Path("medio.pdf"), "expected"),
        backend,
        10.0,
        Path("."),
        SimpleNamespace(max_retries=1),
        (),
    )

    assert calls == 1
    assert returned_backend is backend
    assert observation.metrics["runtime_recovery"]["failure_class"] == "resource_limit_confirmed"


def test_run_config_stops_after_first_resource_limit(monkeypatch, tmp_path: Path) -> None:
    backend = _Backend()
    calls: list[str] = []

    monkeypatch.setattr(
        runner,
        "_settle_memory",
        lambda *_args, **_kwargs: {"stabilization": {"stable": True}},
    )
    monkeypatch.setattr(
        runner,
        "_start_backend",
        lambda *_args, **_kwargs: (backend, 10.0, None),
    )

    def fail_first(_stage, _config, _run_index, document, *_args, **_kwargs):
        calls.append(document.level)
        observation = _failed_observation(available_mib=128.0)
        observation.level = document.level
        observation.metrics["runtime_recovery"] = {
            "attempts": [],
            "recovered": False,
            "failure_class": "resource_limit_confirmed",
        }
        return observation, backend, 10.0

    monkeypatch.setattr(runner, "_run_document_with_recovery", fail_first)

    state: dict[str, object] = {"observations": []}
    documents = (
        BenchmarkDocument("facile", Path("easy.pdf"), "easy"),
        BenchmarkDocument("medio", Path("medium.pdf"), "medium"),
    )
    runner._run_config(
        "stage",
        PipelineConfig(name="config"),
        ("facile", "medio"),
        documents,
        tmp_path,
        state,  # type: ignore[arg-type]
        SimpleNamespace(max_retries=1),
    )

    assert calls == ["facile"]
    terminal = state["terminal_config_failures"]["stage"]["config"]
    assert terminal["failure_class"] == "resource_limit_confirmed"
    assert backend.shutdown_calls >= 1


def test_resume_promotes_old_low_memory_error_to_terminal(monkeypatch, tmp_path: Path) -> None:
    old = _failed_observation(available_mib=94.0)
    old.metrics["runtime_recovery"] = {
        "attempts": [],
        "recovered": False,
        "failure_class": "request_error",
    }
    state: dict[str, object] = {"observations": [observation_to_dict(old)]}

    monkeypatch.setattr(
        runner,
        "_start_backend",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("historical resource limit must be skipped")
        ),
    )

    runner._run_config(
        "stage",
        PipelineConfig(name="config"),
        ("medio",),
        (BenchmarkDocument("medio", Path("medium.pdf"), "expected"),),
        tmp_path,
        state,  # type: ignore[arg-type]
        SimpleNamespace(max_retries=1),
    )

    terminal = state["terminal_config_failures"]["stage"]["config"]
    assert terminal["failure_class"] == "resource_limit_confirmed"
    assert terminal["source"] == "historical_observation"
