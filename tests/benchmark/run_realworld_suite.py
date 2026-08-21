"""Canonical entry point for the real-world GLM-OCR benchmark."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.benchmark import run_realworld_suite_v2 as _runner  # noqa: E402
from tests.benchmark.ground_truth_parser import load_ground_truth  # noqa: E402

# The canonical runner accepts both plain Markdown section bodies and optional
# ```text ... ``` fences. Keep the v2 orchestration unchanged and replace only
# its ground-truth loader at the public entry point.
_runner.load_ground_truth = load_ground_truth
main = _runner.main


if __name__ == "__main__":
    raise SystemExit(main())
