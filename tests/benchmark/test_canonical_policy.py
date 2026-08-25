"""Regression tests for explicit canonical benchmark policy ownership."""

from __future__ import annotations

import importlib

from tests.benchmark import canonical_policy
from tests.benchmark import realworld_suite_v2 as suite
from tests.benchmark import run_realworld_suite_v2 as runner


def test_canonical_policy_owns_current_baseline_and_schema() -> None:
    baseline = canonical_policy.production_baseline()
    assert baseline.max_image_dim == 8192
    assert baseline.runtime.context_size == 16384
    assert runner.CHECKPOINT_SCHEMA == canonical_policy.CHECKPOINT_SCHEMA == 5
    assert runner.production_baseline is canonical_policy.production_baseline
    assert runner.quality_reference is canonical_policy.quality_reference


def test_entrypoint_import_has_no_cross_module_mutation() -> None:
    suite_baseline = suite.production_baseline
    suite_quality = suite.quality_reference
    runner_baseline = runner.production_baseline
    runner_quality = runner.quality_reference

    from tests.benchmark import run_realworld_suite

    importlib.reload(run_realworld_suite)

    assert suite.production_baseline is suite_baseline
    assert suite.quality_reference is suite_quality
    assert runner.production_baseline is runner_baseline
    assert runner.quality_reference is runner_quality
