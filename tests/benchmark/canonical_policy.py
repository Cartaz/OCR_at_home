"""Explicit policy for the canonical real-world GLM-OCR benchmark.

The runner imports this module directly instead of mutating helpers at import
time.  Pure scoring/data helpers stay in ``realworld_suite_v2``; this module owns
only the policy choices that distinguish the canonical benchmark protocol.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from core.llama_ocr_api import PROMPT_LEGACY_OCR, PROMPT_TEXT_RECOGNITION
from tests.benchmark.coherent_quality_reference import quality_reference
from tests.benchmark.ground_truth_parser import load_ground_truth
from tests.benchmark.realworld_suite_v2 import (
    JPEG_QUALITY_VALUES,
    MAX_IMAGE_DIM_VALUES,
    PDF_DPI_VALUES,
    PIPELINE_VARIABLES,
    PREPROCESSING_VALUES,
    RUNTIME_VARIABLES,
    ConfigAggregate,
    PipelineConfig,
    classify_quality,
    config_variable_value,
)
from tests.benchmark.runtime_backend import (
    RuntimeCapabilities,
    production_runtime_config,
    runtime_stage_a_values,
)

CHECKPOINT_SCHEMA = 5
BENCHMARK_BASELINE_MAX_IMAGE_DIM = 8192


def production_baseline(
    prompt: str = PROMPT_LEGACY_OCR,
    *,
    name: str = "baseline",
) -> PipelineConfig:
    """Return the canonical production-like baseline used by the hardware suite."""
    return PipelineConfig(
        name=name,
        prompt=prompt,
        max_image_dim=BENCHMARK_BASELINE_MAX_IMAGE_DIM,
        runtime=production_runtime_config(),
    )


def prompt_configs() -> list[PipelineConfig]:
    return [
        production_baseline(PROMPT_LEGACY_OCR, name="prompt_ocr"),
        production_baseline(
            PROMPT_TEXT_RECOGNITION,
            name="prompt_text_recognition",
        ),
    ]


def _replace_variable(
    config: PipelineConfig,
    variable: str,
    value: Any,
    *,
    name: str,
) -> PipelineConfig | None:
    if variable in PIPELINE_VARIABLES:
        return replace(config, name=name, **{variable: value})
    if variable in RUNTIME_VARIABLES:
        runtime = replace(config.runtime, **{variable: value})
        try:
            runtime = runtime.resolved()
        except ValueError:
            return None
        return replace(config, name=name, runtime=runtime)
    raise ValueError(f"Variabile sconosciuta: {variable}")


def stage_a_groups(
    prompt: str,
    capabilities: RuntimeCapabilities,
) -> dict[str, list[PipelineConfig]]:
    """Build OFAT groups from the canonical baseline without global overrides."""
    baseline = production_baseline(prompt, name="stage_a_baseline")
    values: dict[str, list[Any]] = {
        "pdf_dpi": list(PDF_DPI_VALUES),
        "max_image_dim": list(MAX_IMAGE_DIM_VALUES),
        "jpeg_quality": list(JPEG_QUALITY_VALUES),
        "preprocessing_mode": list(PREPROCESSING_VALUES),
    }
    values.update(runtime_stage_a_values(capabilities))

    groups: dict[str, list[PipelineConfig]] = {}
    for variable, candidates in values.items():
        configs: list[PipelineConfig] = []
        baseline_value = config_variable_value(baseline, variable)
        for value in candidates:
            if value == baseline_value:
                configs.append(baseline)
                continue
            config = _replace_variable(
                baseline,
                variable,
                value,
                name=f"a_{variable}_{str(value).lower()}",
            )
            if config is not None:
                configs.append(config)
        if all(config.name != baseline.name for config in configs):
            configs.append(baseline)
        groups[variable] = configs
    return groups


def select_fastest_quality_gated_values(
    candidates: Sequence[tuple[Any, ConfigAggregate]],
    *,
    top_n: int,
) -> tuple[list[Any], dict[str, Any]]:
    reference = quality_reference([aggregate for _value, aggregate in candidates])
    gates = {
        aggregate.config_id: classify_quality(aggregate, reference)
        for _value, aggregate in candidates
    }
    passing = [
        (value, aggregate)
        for value, aggregate in candidates
        if gates[aggregate.config_id].status == "PASS"
    ]
    passing.sort(
        key=lambda item: (
            item[1].macro_elapsed_s,
            -item[1].macro_char_accuracy,
        )
    )
    return [value for value, _aggregate in passing[: max(1, int(top_n))]], gates


def fastest_quality_equivalent(
    aggregates: Sequence[ConfigAggregate],
) -> ConfigAggregate:
    reference = quality_reference(aggregates)
    passing = [
        aggregate
        for aggregate in aggregates
        if classify_quality(aggregate, reference).status == "PASS"
    ]
    if not passing:
        raise ValueError("Nessuna configurazione supera il quality gate")
    return min(
        passing,
        key=lambda aggregate: (
            aggregate.macro_elapsed_s,
            -aggregate.macro_char_accuracy,
        ),
    )
