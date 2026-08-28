"""Regression tests for benchmark server crash recovery."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.benchmark import run_realworld_suite_v2 as runner
from tests.benchmark.realworld_suite_v2 import BenchmarkDocument, Observation, PipelineConfig


class _Diagnostics:
    def __init__(self, *, process_exited: bool, suspected_oom: bool) -> None:
        self.process_exited = process_exited
        self.suspected_oom = suspected_oom

    def to_dict(self) -> dict[str, object]:
        return {
            "process_exited": self.process_exited,
            "returncode": -9 if self.process_exited else None,
            "suspected_oom": self.suspected_oom,
            "log_tail": "out of memory" if self.suspected_oom else "",
        }


class _Backend:
    def __init__(self, diagnostics: _Diagnostics) -> None:
        self._diagnostics = diagnostics
        self.shutdown_calls = 0

    def failure_diagnostics(self) -> _Diagnostics:
        return self._diagnostics

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _observation(*, error: str | None) -> Observation:
    return Observation(
        stage="stage",
        config_id="config",
        run_index=1,
        level="medio",
        elapsed_s=1.0,
        cer=None if error else 0.01,
        wer=None if error else 0.02,
        char_accuracy=None if error else 0.99,
        output_file="",
        metrics={"memory": {"mem_available_min_mib": 2048.0}},
        segment_scores={},
        error=error,
    )


def test_dead_server_is_restarted_before_document_retry(monkeypatch) -> None:
    first_backend = _Backend(
        _Diagnostics(process_exited=True, suspected_oom=True)
    )
    second_backend = _Backend(
        _Diagnostics(process_exited=False, suspected_oom=False)
    )
    attempts = iter(
        (
            _observation(error="connection refused"),
            _observation(error=None),
        )
    )

    monkeypatch.setattr(runner, "_run_document", lambda *args, **kwargs: next(attempts))
    monkeypatch.setattr(
        runner,
        "_settle_memory",
        lambda *args, **kwargs: {"stabilization": {"stable": True}},
    )
    monkeypatch.setattr(
        runner,
        "_start_backend",
        lambda *args, **kwargs: (second_backend, 321.0, None),
    )

    observation, backend, warm_rss = runner._run_document_with_recovery(
        "stage",
        PipelineConfig(name="config"),
        1,
        BenchmarkDocument("medio", Path("medio.pdf"), "expected"),
        first_backend,
        123.0,
        Path("."),
        SimpleNamespace(max_retries=1),
        (),
    )

    assert observation.error is None
    assert backend is second_backend
    assert warm_rss == 321.0
    assert first_backend.shutdown_calls == 1
    recovery = observation.metrics["runtime_recovery"]
    assert recovery["recovered"] is True
    assert recovery["failure_class"] == "recovered"


def test_repeated_clean_oom_is_classified_as_confirmed_resource_limit(
    monkeypatch,
) -> None:
    first_backend = _Backend(
        _Diagnostics(process_exited=True, suspected_oom=True)
    )
    second_backend = _Backend(
        _Diagnostics(process_exited=True, suspected_oom=True)
    )
    attempts = iter(
        (
            _observation(error="connection refused"),
            _observation(error="connection refused"),
        )
    )

    monkeypatch.setattr(runner, "_run_document", lambda *args, **kwargs: next(attempts))
    monkeypatch.setattr(
        runner,
        "_settle_memory",
        lambda *args, **kwargs: {"stabilization": {"stable": True}},
    )
    monkeypatch.setattr(
        runner,
        "_start_backend",
        lambda *args, **kwargs: (second_backend, 321.0, None),
    )

    observation, _backend, _warm_rss = runner._run_document_with_recovery(
        "stage",
        PipelineConfig(name="config"),
        1,
        BenchmarkDocument("medio", Path("medio.pdf"), "expected"),
        first_backend,
        123.0,
        Path("."),
        SimpleNamespace(max_retries=1),
        (),
    )

    recovery = observation.metrics["runtime_recovery"]
    assert observation.error is not None
    assert recovery["recovered"] is False
    assert recovery["failure_class"] == "resource_limit_confirmed"
