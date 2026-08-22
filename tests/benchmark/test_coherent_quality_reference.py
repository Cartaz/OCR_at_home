"""Regression tests for attainable benchmark quality references."""

from __future__ import annotations

from tests.benchmark.coherent_quality_reference import quality_reference
from tests.benchmark.realworld_suite_v2 import (
    ConfigAggregate,
    DocumentAggregate,
    QualityAggregate,
    classify_quality,
    select_fastest_quality_gated_values,
)


def _aggregate(
    config_id: str,
    *,
    macro: float,
    elapsed: float,
    facile: float,
    medio: float,
    difficile: float,
    maiuscolo: float,
    script: float,
    corsivo: float,
) -> ConfigAggregate:
    accuracies = {
        "facile": facile,
        "medio": medio,
        "difficile": difficile,
    }
    docs = {
        level: DocumentAggregate(
            level=level,
            successful_runs=5,
            expected_runs=5,
            valid=True,
            trimmed_cer=1.0 - accuracy,
            trimmed_wer=1.0 - accuracy,
            trimmed_char_accuracy=accuracy,
            trimmed_elapsed_s=elapsed,
            trimmed_request_elapsed_s=elapsed,
            trimmed_encoded_bytes=1000.0,
            cache_n_total=0,
        )
        for level, accuracy in accuracies.items()
    }
    hard = {
        "maiuscolo": QualityAggregate(1.0 - maiuscolo, 1.0 - maiuscolo, maiuscolo),
        "script": QualityAggregate(1.0 - script, 1.0 - script, script),
        "corsivo": QualityAggregate(1.0 - corsivo, 1.0 - corsivo, corsivo),
    }
    return ConfigAggregate(
        config_id=config_id,
        levels=("facile", "medio", "difficile"),
        valid=True,
        macro_char_accuracy=macro,
        macro_cer=1.0 - macro,
        macro_wer=1.0 - macro,
        macro_elapsed_s=elapsed,
        macro_request_elapsed_s=elapsed,
        mean_encoded_bytes=1000.0,
        cache_n_total=0,
        documents=docs,
        hard_segments=hard,
    )


def test_reference_uses_one_complete_profile_instead_of_metric_envelope() -> None:
    # Mirrors the failure mode seen in the real DPI sweep: different profiles
    # can win different submetrics. A per-metric envelope is unattainable and
    # can make every real profile fail simultaneously.
    baseline = _aggregate(
        "dpi150",
        macro=0.8884,
        elapsed=78.0,
        facile=0.9828,
        medio=0.9779,
        difficile=0.7045,
        maiuscolo=0.1871,
        script=0.9807,
        corsivo=0.9609,
    )
    low_dpi = _aggregate(
        "dpi100",
        macro=0.8841,
        elapsed=31.0,
        facile=0.9781,
        medio=0.9779,
        difficile=0.6964,
        maiuscolo=0.1905,
        script=0.9775,
        corsivo=0.9336,
    )
    mid_dpi = _aggregate(
        "dpi125",
        macro=0.8842,
        elapsed=48.0,
        facile=0.9807,
        medio=0.9779,
        difficile=0.6937,
        maiuscolo=0.1871,
        script=0.9839,
        corsivo=0.9219,
    )

    reference = quality_reference([baseline, low_dpi, mid_dpi])

    assert reference.best_macro_accuracy == baseline.macro_char_accuracy
    assert reference.segment_accuracy["maiuscolo"] == baseline.hard_segments["maiuscolo"].char_accuracy
    assert reference.segment_accuracy["script"] == baseline.hard_segments["script"].char_accuracy
    assert classify_quality(baseline, reference).status == "PASS"


def test_selector_cannot_end_with_zero_passes_when_valid_profiles_exist(monkeypatch) -> None:
    baseline = _aggregate(
        "baseline",
        macro=0.90,
        elapsed=3.0,
        facile=0.90,
        medio=0.90,
        difficile=0.90,
        maiuscolo=0.90,
        script=0.90,
        corsivo=0.90,
    )
    tradeoff = _aggregate(
        "tradeoff",
        macro=0.899,
        elapsed=1.0,
        facile=0.905,
        medio=0.895,
        difficile=0.897,
        maiuscolo=0.905,
        script=0.895,
        corsivo=0.897,
    )

    # select_fastest_quality_gated_values resolves quality_reference from its
    # defining module at call time; patching that module is exactly what the
    # canonical entry point does.
    import tests.benchmark.realworld_suite_v2 as suite

    monkeypatch.setattr(suite, "quality_reference", quality_reference)
    chosen, gates = select_fastest_quality_gated_values(
        [(150, baseline), (125, tradeoff)],
        top_n=5,
    )

    assert chosen
    assert 150 in chosen
    assert gates["baseline"].status == "PASS"
