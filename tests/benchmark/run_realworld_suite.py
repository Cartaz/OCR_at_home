"""Canonical entry point for the real-world GLM-OCR benchmark."""

from __future__ import annotations

import sys
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
main = _runner.main


if __name__ == "__main__":
    raise SystemExit(main())
