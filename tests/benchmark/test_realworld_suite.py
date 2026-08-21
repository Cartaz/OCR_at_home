"""Deterministic tests for the canonical real-world benchmark helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.benchmark.realworld_suite import (
    LEVELS,
    BenchmarkDocument,
    ConfigAggregate,
    DocumentAggregate,
    PipelineConfig,
    character_error_rate,
    parse_ground_truth_markdown,
    pareto_frontier,
    rotation_order,
    select_fastest_quality_gated_values,
    stage_a_configs,
    stage_b_configs,
    trimmed_mean,
    word_error_rate,
)


def _aggregate(config_id: str, accuracy: float, elapsed: float, *, cache_n: int = 0) -> ConfigAggregate:
    doc = DocumentAggregate(
        level="facile",
        successful_runs=5,
        expected_runs=5,
        valid=True,
        trimmed_cer=1.0 - accuracy,
        trimmed_wer=1.0 - accuracy,
        trimmed_char_accuracy=accuracy,
        trimmed_elapsed_s=elapsed,
        trimmed_request_elapsed_s=elapsed,
        trimmed_encoded_bytes=1000.0,
        cache_n_total=cache_n,
    )
    return ConfigAggregate(
        config_id=config_id,
        levels=("facile",),
        valid=True,
        macro_char_accuracy=accuracy,
        macro_cer=1.0 - accuracy,
        macro_wer=1.0 - accuracy,
        macro_elapsed_s=elapsed,
        macro_request_elapsed_s=elapsed,
        mean_encoded_bytes=1000.0,
        cache_n_total=cache_n,
        documents={"facile": doc},
    )


def test_ground_truth_parser_requires_three_strict_sections() -> None:
    markdown = """# FACILE

```text
Uno due tre.
```

# MEDIO

```text
Quattro cinque.
```

# DIFFICILE

```text
Sei sette.
```
"""
    parsed = parse_ground_truth_markdown(markdown)
    assert tuple(parsed) == LEVELS
    assert parsed["facile"] == "Uno due tre."
    assert parsed["difficile"] == "Sei sette."

    with pytest.raises(ValueError):
        parse_ground_truth_markdown("# FACILE\n```text\nsolo uno\n```\n")


def test_metrics_normalize_whitespace_and_app_pdf_markers_only() -> None:
    expected = "Hello world\nSecond line"
    actual = "--- Pagina 1 ---\nHello   world\n\nSecond line"
    assert character_error_rate(expected, actual) == 0.0
    assert word_error_rate(expected, actual) == 0.0


def test_five_run_trimmed_mean_discards_one_low_and_one_high() -> None:
    assert trimmed_mean([100.0, 2.0, 3.0, 4.0, -50.0], trim=1) == pytest.approx(3.0)


def test_rotation_schedule_changes_first_and_last_document() -> None:
    orders = [rotation_order(index) for index in range(1, 6)]
    assert orders[0] == ("facile", "medio", "difficile")
    assert orders[1] == ("medio", "difficile", "facile")
    assert orders[2] == ("difficile", "facile", "medio")
    assert len(set(orders)) == 5


def test_stage_a_keeps_all_variables_one_factor_at_a_time() -> None:
    groups = stage_a_configs("OCR")
    assert len(groups["pdf_dpi"]) == 7
    assert len(groups["max_image_dim"]) == 7
    assert len(groups["jpeg_quality"]) == 8
    assert len(groups["preprocessing_mode"]) == 4

    for config in groups["pdf_dpi"]:
        assert config.max_image_dim == 1920
        assert config.jpeg_quality == 85
        assert config.preprocessing_mode == "full"


def test_stage_b_can_generate_full_5x5x5x4_matrix() -> None:
    configs = stage_b_configs(
        prompt="OCR",
        selected={
            "pdf_dpi": [100, 125, 150, 175, 200],
            "max_image_dim": [1024, 1280, 1536, 1920, 2304],
            "jpeg_quality": [50, 60, 70, 80, 85],
            "preprocessing_mode": ["none", "contrast", "resize", "full"],
        },
    )
    assert len(configs) == 500
    assert len({config.signature() for config in configs}) == 500


def test_stage_b_selection_prefers_speed_only_inside_quality_gate() -> None:
    candidates = [
        ("very-fast-bad", _aggregate("bad", 0.9900, 1.0)),
        ("fast-good", _aggregate("fast-good", 0.9990, 2.0)),
        ("slower-best", _aggregate("best", 1.0000, 3.0)),
        ("cached", _aggregate("cached", 1.0000, 0.5, cache_n=12)),
    ]
    selected = select_fastest_quality_gated_values(
        candidates,
        top_n=5,
        tolerance_pp=0.25,
    )
    assert selected == ["fast-good", "slower-best"]


def test_pareto_frontier_removes_dominated_configuration() -> None:
    fast_good = _aggregate("fast-good", 0.999, 2.0)
    slow_same = _aggregate("slow-same", 0.999, 4.0)
    slower_best = _aggregate("best", 1.0, 3.0)
    frontier = pareto_frontier([fast_good, slow_same, slower_best])
    assert [item.config_id for item in frontier] == ["best", "fast-good"]


def test_document_model_identifies_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "easy.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    document = BenchmarkDocument("facile", pdf, "test")
    assert document.is_pdf is True
