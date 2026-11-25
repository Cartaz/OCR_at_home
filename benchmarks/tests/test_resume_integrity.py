"""Regression tests for canonical benchmark resume integrity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.benchmark.resume_integrity import (
    assert_resume_compatible,
    validate_resume_preflight,
)
from tests.benchmark.runtime_backend import RuntimeCapabilities


def _capabilities(
    *,
    version: str = "version: 0.1.2-dev (build 1, commit abc)",
    supported: dict[str, bool] | None = None,
) -> RuntimeCapabilities:
    return RuntimeCapabilities(
        server_path="/tmp/llama-server",
        version=version,
        supported=supported or {"context_size": True, "flash_attn": True},
    )


def _state() -> dict[str, object]:
    capabilities = _capabilities()
    return {
        "protocol": {
            "runs": 5,
            "top_values": 5,
            "beam_width": 5,
        },
        "runtime": {
            "llama_version": capabilities.version,
            "server_path": capabilities.server_path,
            "supported_variables": capabilities.supported,
        },
    }


def test_resume_accepts_same_protocol_and_runtime() -> None:
    assert_resume_compatible(
        _state(),
        runs=5,
        top_values=5,
        beam_width=5,
        capabilities=_capabilities(),
    )


def test_resume_rejects_top_values_change() -> None:
    with pytest.raises(SystemExit, match="top-values"):
        assert_resume_compatible(
            _state(),
            runs=5,
            top_values=3,
            beam_width=5,
            capabilities=_capabilities(),
        )


def test_resume_rejects_llama_server_version_change() -> None:
    with pytest.raises(SystemExit, match="llama-server diverso"):
        assert_resume_compatible(
            _state(),
            runs=5,
            top_values=5,
            beam_width=5,
            capabilities=_capabilities(version="version: different"),
        )


def test_resume_rejects_capability_change() -> None:
    with pytest.raises(SystemExit, match="flash_attn"):
        assert_resume_compatible(
            _state(),
            runs=5,
            top_values=5,
            beam_width=5,
            capabilities=_capabilities(
                supported={"context_size": True, "flash_attn": False}
            ),
        )


def test_preflight_without_resume_does_not_probe_runtime(monkeypatch) -> None:
    called = False

    def fail_if_called() -> RuntimeCapabilities:
        nonlocal called
        called = True
        raise AssertionError("runtime probe should not run")

    monkeypatch.setattr(
        "tests.benchmark.resume_integrity.detect_runtime_capabilities",
        fail_if_called,
    )

    validate_resume_preflight([])

    assert called is False


def test_preflight_reads_checkpoint_and_checks_runtime(tmp_path: Path, monkeypatch) -> None:
    resume_dir = tmp_path / "run"
    resume_dir.mkdir()
    (resume_dir / "checkpoint.json").write_text(
        json.dumps(_state()),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "tests.benchmark.resume_integrity.detect_runtime_capabilities",
        _capabilities,
    )

    validate_resume_preflight(["--resume", str(resume_dir)])
