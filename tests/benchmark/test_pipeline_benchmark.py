"""Deterministic tests for the manual Phase 5 benchmark runner."""

from __future__ import annotations

from pathlib import Path

import fitz

from tests.benchmark.benchmark_prompt_quality import Sample
from tests.benchmark.run_pipeline_benchmark import (
    PipelineRun,
    _build_synthetic_pdf,
    config_applies_to_sample,
    pipeline_configs,
    summarize,
)


def test_quick_suite_is_one_factor_at_a_time() -> None:
    configs = pipeline_configs(quick=True)
    assert [item.name for item in configs] == [
        "baseline",
        "preprocess_off",
        "pdf_dpi_200",
        "maxdim_1280",
        "jpeg_70",
    ]
    baseline = configs[0]
    for candidate in configs[1:]:
        changed = sum(
            [
                candidate.preprocessing_enabled != baseline.preprocessing_enabled,
                candidate.pdf_dpi != baseline.pdf_dpi,
                candidate.max_image_dim != baseline.max_image_dim,
                candidate.jpeg_quality != baseline.jpeg_quality,
            ]
        )
        assert changed == 1


def test_pdf_dpi_variants_are_skipped_for_raster_samples(tmp_path: Path) -> None:
    raster = Sample("image", "text", tmp_path / "image.png", "abc")
    pdf = Sample("pdf", "text", tmp_path / "document.pdf", "abc")
    dpi_config = next(item for item in pipeline_configs() if item.name == "pdf_dpi_200")

    assert config_applies_to_sample(dpi_config, raster) is False
    assert config_applies_to_sample(dpi_config, pdf) is True


def test_synthetic_pdf_contains_two_vector_pages_and_labelled_ground_truth(tmp_path: Path) -> None:
    sample = _build_synthetic_pdf(tmp_path)
    assert sample.image_path.is_file()
    assert sample.task == "text"
    assert "--- Pagina 1 ---" in sample.expected_text
    assert "--- Pagina 2 ---" in sample.expected_text

    document = fitz.open(sample.image_path)
    try:
        assert document.page_count == 2
        assert "Pipeline PDF benchmark" in document[0].get_text()
        assert "Testo piccolo" in document[1].get_text()
    finally:
        document.close()


def test_summary_tracks_quality_transfer_cache_and_cache_free_timing() -> None:
    results = [
        PipelineRun(
            config="baseline",
            sample="a",
            source_type="image",
            elapsed_s=10.0,
            cer=0.0,
            metrics=[
                {
                    "encoded_bytes": 1000,
                    "request_elapsed_s": 8.0,
                    "cache_n": 0,
                }
            ],
        ),
        PipelineRun(
            config="baseline",
            sample="b",
            source_type="image",
            elapsed_s=2.0,
            cer=0.1,
            metrics=[
                {
                    "encoded_bytes": 2000,
                    "request_elapsed_s": 1.0,
                    "cache_n": 512,
                }
            ],
        ),
    ]

    values = summarize(results)["baseline"]
    assert values["runs"] == 2
    assert values["errors"] == 0
    assert values["mean_cer"] == 0.05
    assert values["worst_cer"] == 0.1
    assert values["mean_encoded_bytes"] == 1500.0
    assert values["cache_n_total"] == 512
    assert values["cache_free_runs"] == 1
    assert values["mean_cache_free_elapsed_s"] == 10.0
