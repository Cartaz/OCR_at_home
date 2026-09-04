"""Regression tests for the canonical real-world benchmark baseline guards."""

from __future__ import annotations

from tests.benchmark.runtime_backend import (
    RuntimeCapabilities,
    ServerRuntimeConfig,
    production_runtime_config,
    runtime_stage_a_values,
)


def test_realworld_baseline_is_stock_without_removing_context_candidates() -> None:
    baseline = production_runtime_config()
    assert baseline.context_size is None
    assert baseline.cli_args() == []

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

    assert ServerRuntimeConfig().context_size is None


def test_canonical_entrypoint_uses_stock_baseline_checkpoint_schema() -> None:
    from tests.benchmark import run_realworld_suite  # noqa: F401
    from tests.benchmark import run_realworld_suite_v2 as runner

    assert runner.CHECKPOINT_SCHEMA == 7
