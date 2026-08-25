"""Preflight integrity checks for canonical real-world benchmark resumes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from tests.benchmark.realworld_suite_v2 import (
    DEFAULT_BEAM_WIDTH,
    DEFAULT_RUNS,
    DEFAULT_TOP_VALUES,
)
from tests.benchmark.runtime_backend import (
    RuntimeCapabilities,
    detect_runtime_capabilities,
)


def _parse_resume_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--top-values", type=int, default=DEFAULT_TOP_VALUES)
    parser.add_argument("--beam-width", type=int, default=DEFAULT_BEAM_WIDTH)
    args, _unknown = parser.parse_known_args(list(argv))
    return args


def _load_checkpoint(resume_dir: Path) -> dict[str, object]:
    checkpoint = resume_dir.expanduser().resolve() / "checkpoint.json"
    if not checkpoint.is_file():
        raise SystemExit(f"Checkpoint non trovato: {checkpoint}")
    try:
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Checkpoint non leggibile: {checkpoint}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Checkpoint non valido: {checkpoint}")
    return payload


def assert_resume_compatible(
    state: dict[str, object],
    *,
    runs: int,
    top_values: int,
    beam_width: int,
    capabilities: RuntimeCapabilities,
) -> None:
    """Reject a resume that would mix incompatible benchmark conditions."""
    protocol = state.get("protocol")
    if not isinstance(protocol, dict):
        raise SystemExit("Checkpoint privo della sezione protocol")

    expected_protocol = {
        "runs": int(runs),
        "top_values": int(top_values),
        "beam_width": int(beam_width),
    }
    for key, current in expected_protocol.items():
        stored = protocol.get(key)
        if stored is None or int(stored) != current:
            raise SystemExit(
                f"--{key.replace('_', '-')} deve coincidere col checkpoint "
                f"({stored!r} != {current!r})"
            )

    runtime = state.get("runtime")
    if not isinstance(runtime, dict):
        raise SystemExit("Checkpoint privo della sezione runtime")

    stored_version = str(runtime.get("llama_version") or "")
    if stored_version and stored_version != capabilities.version:
        raise SystemExit(
            "llama-server diverso dal checkpoint: "
            f"{stored_version!r} != {capabilities.version!r}. "
            "Non mescolare runtime diversi nella stessa suite."
        )

    stored_supported = runtime.get("supported_variables")
    if isinstance(stored_supported, dict):
        normalized = {str(key): bool(value) for key, value in stored_supported.items()}
        if normalized != capabilities.supported:
            changed = sorted(
                key
                for key in set(normalized) | set(capabilities.supported)
                if normalized.get(key) != capabilities.supported.get(key)
            )
            raise SystemExit(
                "Capability llama-server diverse dal checkpoint: "
                + ", ".join(changed)
            )


def validate_resume_preflight(argv: Sequence[str]) -> None:
    """Validate resume-only invariants before the canonical runner starts."""
    args = _parse_resume_args(argv)
    if args.resume is None:
        return
    state = _load_checkpoint(args.resume)
    assert_resume_compatible(
        state,
        runs=args.runs,
        top_values=args.top_values,
        beam_width=args.beam_width,
        capabilities=detect_runtime_capabilities(),
    )
