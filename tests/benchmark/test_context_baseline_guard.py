"""Regression tests for the canonical real-world benchmark baseline guards."""

from __future__ import annotations

from tests.benchmark.runtime_backend import (
    RuntimeCapabilities,
    ServerRuntimeConfig,
    production_runtime_config,
    runtime_stage_a_values,
)


def test_realworld_baseline_uses_16384_context_without_removing_smaller_candidates() -> None:
    baseline = production_runtime_config()
    assert baseline.context_size == 16384

    capabilities = RuntimeCapabilities(
        server_path="/tmp/llama-server",
        version="test",
        supported={"context_size": True},
    )
    assert runtime_stage_a_values(capabilities)["context_size"] == [
        2048,
        3072,
        4096,
        6144,
        8192,
        12288,
        16384,
    ]

    # The generic runtime profile remains neutral; only the canonical
    # production-like benchmark baseline receives the larger safety budget.
    assert ServerRuntimeConfig().context_size == 4096


def test_canonical_entrypoint_invalidates_pre_current_baseline_checkpoints() -> None:
    from tests.benchmark import run_realworld_suite  # noqa: F401
    from tests.benchmark import run_realworld_suite_v2 as runner

    assert runner.CHECKPOINT_SCHEMA == 5
