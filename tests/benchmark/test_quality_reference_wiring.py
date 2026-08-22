"""Smoke-test canonical quality-reference wiring."""

from __future__ import annotations


def test_canonical_entrypoint_wires_coherent_reference() -> None:
    from tests.benchmark import realworld_suite_v2 as suite
    from tests.benchmark import run_realworld_suite  # noqa: F401
    from tests.benchmark import run_realworld_suite_v2 as runner
    from tests.benchmark.coherent_quality_reference import quality_reference

    assert suite.quality_reference is quality_reference
    assert runner.quality_reference is quality_reference
