"""Canonical entry point for the real-world GLM-OCR benchmark."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.benchmark.run_realworld_suite_v2 import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
