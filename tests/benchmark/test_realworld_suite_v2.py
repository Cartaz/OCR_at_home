"""Deterministic tests for canonical benchmark protocol v2."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.benchmark.realworld_suite_v2 import (
    HANDWRITING_SEGMENTS,
    ConfigAggregate,
    DocumentAggregate,
    PipelineConfig,
    QualityAggregate,
    aggregate_config,
    beam_expand,
    classify_quality,
    parse_ground_truth_markdown,
    production_baseline,
    quality_reference,
    score_document,
    stage_a_groups,
    trim_for_runs,
    trimmed_mean,
)
from tests.benchmark.runtime_backend import RuntimeCapabilities, ServerRuntimeConfig
from tests.benchmark.realworld_suite_v2 import BenchmarkDocument, Observation


def _markdown() -> str:
    return """# FACILE

```text
Documento digitale.
```

# MEDIO

```text
Documento scansione.
```

# DIFFICILE

## MAIUSCOLO

```text
QUESTA E LA PRIMA PARTE DEL TESTO.
```

## SCRIPT

```text
Questa è la continuazione in script.
```

## CORSIVO

```text
Questa è la conclusione in corsivo.
```
"""


def test_ground_truth_requires_continuous_handwriting_three_segments() -> None:
    truth = parse_ground_truth_markdown(_markdown())
    assert tuple(truth.difficile_segments) == HANDWRITING_SEGMENTS
    assert truth.difficile.startswith("QUESTA E LA PRIMA")
    assert truth.difficile.endswith("conclusione in corsivo.")

    broken = _markdown().replace("## CORSIVO", "## ALTRO")
    with pytest.raises(ValueError):
        parse_ground_truth_markdown(broken)


def test_handwriting_is_scored_as_one_output_but_split_by_aligned_boundaries(tmp_path: Path) -> None:
    truth = parse_ground_truth_markdown(_markdown())
    document = BenchmarkDocument(
        "difficile",
        tmp_path / "hand.png",
        truth.difficile,
        truth.difficile_segments,
    )
    output = (
        "QUESTA E LA PRIMA PARTE DEL TESTO. "
        "Questa è la continuazione in script. "
        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    )
    _cer, _wer, overall, segments = score_document(document, output)
    assert overall < 1.0
    assert segments["maiuscolo"]["char_accuracy"] > 0.95
    assert segments["script"]["char_accuracy"] > 0.90
    assert segments["corsivo"]["char_accuracy"] < 0.50


def _config_aggregate(config_id: str, *, macro: float, elapsed: float, hard: float) -> ConfigAggregate:
    docs = {
        level: DocumentAggregate(
            level=level,
            successful_runs=5,
            expected_runs=5,
            valid=True,
            trimmed_cer=1.0 - macro,
            trimmed_wer=max(0.0, 1.0 - macro),
            trimmed_char_accuracy=macro,
            trimmed_elapsed_s=elapsed,
            trimmed_request_elapsed_s=elapsed,
            trimmed_encoded_bytes=1000.0,
            cache_n_total=0,
        )
        for level in ("facile", "medio", "difficile")
    }
    segments = {
        name: QualityAggregate(cer=1.0 - hard, wer=max(0.0, 1.0 - hard), char_accuracy=hard)
        for name in HANDWRITING_SEGMENTS
    }
    return ConfigAggregate(
        config_id=config_id,
        levels=("facile", "medio", "difficile"),
        valid=True,
        macro_char_accuracy=macro,
        macro_cer=1.0 - macro,
        macro_wer=max(0.0, 1.0 - macro),
        macro_elapsed_s=elapsed,
        macro_request_elapsed_s=elapsed,
        mean_encoded_bytes=1000.0,
        cache_n_total=0,
        documents=docs,
        hard_segments=segments,
    )


def test_quality_gate_is_relative_even_if_every_handwriting_score_is_poor() -> None:
    best = _config_aggregate("best", macro=0.90, elapsed=3.0, hard=0.43)
    close = _config_aggregate("close", macro=0.899, elapsed=2.0, hard=0.428)
    bad = _config_aggregate("bad", macro=0.88, elapsed=1.0, hard=0.35)
    reference = quality_reference([best, close, bad])
    assert classify_quality(best, reference).status == "PASS"
    assert classify_quality(close, reference).status == "PASS"
    assert classify_quality(bad, reference).status == "FAIL"


def test_quality_gate_protects_cursive_even_when_macro_accuracy_is_close() -> None:
    best = _config_aggregate("best", macro=0.995, elapsed=3.0, hard=0.95)
    candidate = _config_aggregate("candidate", macro=0.994, elapsed=1.0, hard=0.94)
    reference = quality_reference([best, candidate])
    gate = classify_quality(candidate, reference)
    assert gate.status in {"BORDERLINE", "FAIL"}
    assert any("accuracy" in reason for reason in gate.reasons)


def test_stage_a_contains_pipeline_and_supported_runtime_variables() -> None:
    capabilities = RuntimeCapabilities(
        server_path="/tmp/llama-server",
        version="test",
        supported={
            "context_size": True,
            "batch_size": True,
            "ubatch_size": True,
            "threads": True,
            "threads_batch": True,
            "flash_attn": True,
            "cache_type_k": True,
            "cache_type_v": True,
            "spec_type": True,
            "kv_offload": True,
            "op_offload": True,
        },
    )
    groups = stage_a_groups("OCR", capabilities)
    for variable in (
        "pdf_dpi",
        "max_image_dim",
        "jpeg_quality",
        "preprocessing_mode",
        "batch_size",
        "ubatch_size",
        "flash_attn",
        "cache_type_k",
        "cache_type_v",
        "spec_type",
    ):
        assert variable in groups
    assert any(config.runtime.spec_type == "draft-mtp" for config in groups["spec_type"])


def test_beam_expansion_skips_invalid_batch_ubatch_combinations() -> None:
    base = production_baseline("OCR", name="base")
    low_batch = PipelineConfig(
        name="low",
        prompt=base.prompt,
        preprocessing_mode=base.preprocessing_mode,
        pdf_dpi=base.pdf_dpi,
        max_image_dim=base.max_image_dim,
        jpeg_quality=base.jpeg_quality,
        runtime=ServerRuntimeConfig(batch_size=512, ubatch_size=512, threads=4, threads_batch=4),
    )
    configs = beam_expand([low_batch], "ubatch_size", [256, 512, 1024], step=1)
    assert {config.runtime.ubatch_size for config in configs} == {256, 512}


def test_runtime_profile_validation_and_trim_rules() -> None:
    resolved = ServerRuntimeConfig(threads=4, threads_batch=8).resolved()
    assert resolved.threads == 4
    assert resolved.threads_batch == 8
    with pytest.raises(ValueError):
        ServerRuntimeConfig(batch_size=256, ubatch_size=512, threads=4, threads_batch=4).resolved()
    assert trim_for_runs(5) == 1
    assert trim_for_runs(10) == 2
    assert trimmed_mean([1, 2, 3, 4, 100], trim=1) == pytest.approx(3.0)


def test_ten_run_aggregate_uses_two_sided_twenty_percent_trim() -> None:
    observations = []
    values = [0.80, 0.90, 0.91, 0.92, 0.93, 0.94, 0.95, 0.96, 0.97, 1.00]
    for index, accuracy in enumerate(values, start=1):
        observations.append(
            Observation(
                stage="x",
                config_id="cfg",
                run_index=index,
                level="facile",
                elapsed_s=float(index),
                cer=1.0 - accuracy,
                wer=1.0 - accuracy,
                char_accuracy=accuracy,
                output_file="",
                metrics={"pages": [{}]},
            )
        )
    aggregate = aggregate_config(observations, config_id="cfg", levels=("facile",), expected_runs=10)
    assert aggregate.valid
    assert aggregate.documents["facile"].trimmed_char_accuracy == pytest.approx(sum(values[2:8]) / 6)
