"""Smoke test the canonical benchmark module wiring without hardware."""

from __future__ import annotations


def test_canonical_entrypoint_imports_without_starting_runtime() -> None:
    from tests.benchmark import run_realworld_suite

    assert callable(run_realworld_suite.main)
