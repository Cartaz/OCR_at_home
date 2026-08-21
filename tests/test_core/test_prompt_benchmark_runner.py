from __future__ import annotations

from pathlib import Path

from tests.benchmark.benchmark_prompt_quality import RunResult, Sample
from tests.benchmark.run_prompt_benchmark import (
    build_per_sample_counterbalanced_schedule,
    quality_summary,
)


def _samples(tmp_path: Path) -> list[Sample]:
    samples = []
    for name in ("a", "b", "c"):
        path = tmp_path / f"{name}.png"
        path.write_bytes(b"x")
        samples.append(Sample(name, "text", path, name))
    return samples


def test_each_sample_alternates_first_prompt_between_rounds(tmp_path: Path) -> None:
    prompts = ["OCR", "Text Recognition:"]
    schedule = build_per_sample_counterbalanced_schedule(
        _samples(tmp_path), prompts, rounds=2
    )

    first_by_sample_round: dict[tuple[str, int], str] = {}
    for round_index, sample, prompt in schedule:
        first_by_sample_round.setdefault((sample.name, round_index), prompt)

    for sample_name in ("a", "b", "c"):
        assert first_by_sample_round[(sample_name, 1)] != first_by_sample_round[
            (sample_name, 2)
        ]


def test_quality_summary_ignores_wall_clock_for_decision() -> None:
    results = [
        RunResult("a", "text", "OCR", 20.0, cer=0.0),
        RunResult("a", "text", "Text Recognition:", 1.0, cer=0.0),
    ]

    summary = quality_summary(results)

    assert summary["OCR"]["mean_cer"] == 0.0
    assert summary["Text Recognition:"]["mean_cer"] == 0.0
    assert "mean_elapsed_s" not in summary["OCR"]
    assert "mean_elapsed_s" not in summary["Text Recognition:"]
