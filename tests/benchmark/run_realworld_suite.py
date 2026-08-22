"""Canonical entry point for the real-world GLM-OCR benchmark."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.benchmark import realworld_suite_v2 as _suite  # noqa: E402
from tests.benchmark import run_realworld_suite_v2 as _runner  # noqa: E402
from tests.benchmark.coherent_quality_reference import quality_reference  # noqa: E402
from tests.benchmark.ground_truth_parser import load_ground_truth  # noqa: E402

# Keep the v2 orchestration intact while routing the canonical public entry
# point through the hardened ground-truth parser and a coherent quality
# reference. The latter uses one real complete profile as the gate anchor,
# rather than an unattainable per-metric synthetic envelope.
_runner.load_ground_truth = load_ground_truth
_runner.quality_reference = quality_reference
_suite.quality_reference = quality_reference

# The canonical real-world baseline must not downscale supported PDF pages before
# the DPI sweep has a chance to measure their native rendered resolution. 8192px
# is effectively uncapped for the supported 72..600 DPI A4 range (long side at
# 600 DPI is about 7016px), while remaining inside llama_ocr_api's safety range.
# Production continues to use its independent 1920px default.
BENCHMARK_BASELINE_MAX_IMAGE_DIM = 8192
_original_production_baseline = _suite.production_baseline


def _canonical_production_baseline(*args, **kwargs):
    return replace(
        _original_production_baseline(*args, **kwargs),
        max_image_dim=BENCHMARK_BASELINE_MAX_IMAGE_DIM,
    )


# Functions such as prompt_configs() and stage_a_groups() resolve
# production_baseline through the _suite module globals at call time. Patch both
# modules as a guard for direct calls from the runner as well.
_suite.production_baseline = _canonical_production_baseline
_runner.production_baseline = _canonical_production_baseline

# Checkpoints created before the 16384-token, uncapped-resolution benchmark
# baseline may contain observations collected with ctx4096/ctx8192 and/or the
# historical 1920px cap. Reject them instead of mixing incompatible runs.
_runner.CHECKPOINT_SCHEMA = 5

main = _runner.main


if __name__ == "__main__":
    raise SystemExit(main())
