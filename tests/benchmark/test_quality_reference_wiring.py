"""Smoke-test canonical quality-reference ownership."""

from __future__ import annotations


def test_canonical_runner_uses_coherent_reference_explicitly() -> None:
    from tests.benchmark import canonical_policy
    from tests.benchmark import run_realworld_suite_v2 as runner
    from tests.benchmark.coherent_quality_reference import quality_reference

    assert canonical_policy.quality_reference is quality_reference
    assert runner.quality_reference is quality_reference
