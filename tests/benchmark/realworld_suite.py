"""Pure helpers for the canonical real-world GLM-OCR benchmark suite."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
import statistics
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from core.llama_ocr_api import (
    JPEG_QUALITY,
    MAX_IMAGE_DIM,
    PDF_DPI,
    PROMPT_LEGACY_OCR,
    PROMPT_TEXT_RECOGNITION,
)

LEVELS: tuple[str, ...] = ("facile", "medio", "difficile")
PDF_DPI_VALUES: tuple[int, ...] = (100, 125, 150, 175, 200, 250, 300)
MAX_IMAGE_DIM_VALUES: tuple[int, ...] = (1024, 1280, 1536, 1920, 2304, 2560, 3072)
JPEG_QUALITY_VALUES: tuple[int, ...] = (50, 60, 70, 80, 85, 90, 95, 100)
PREPROCESSING_VALUES: tuple[str, ...] = ("none", "contrast", "resize", "full")
DEFAULT_RUNS = 5
DEFAULT_TRIM = 1
DEFAULT_TOP_VALUES = 5
DEFAULT_ACCURACY_TOLERANCE_PP = 0.25
BENCHMARK_SEED = 20260821


@dataclass(frozen=True)
class BenchmarkDocument:
    level: str
    path: Path
    expected_text: str

    @property
    def is_pdf(self) -> bool:
        return self.path.suffix.lower() == ".pdf"


@dataclass(frozen=True)
class PipelineConfig:
    name: str
    prompt: str = PROMPT_LEGACY_OCR
    preprocessing_mode: str = "full"
    pdf_dpi: int = PDF_DPI
    max_image_dim: int = MAX_IMAGE_DIM
    jpeg_quality: int = JPEG_QUALITY

    def signature(self) -> str:
        prompt_name = "text" if self.prompt == PROMPT_TEXT_RECOGNITION else "ocr"
        return (
            f"{prompt_name}-pre_{self.preprocessing_mode}-dpi_{self.pdf_dpi}-"
            f"max_{self.max_image_dim}-jpg_{self.jpeg_quality}"
        )


@dataclass
class Observation:
    stage: str
    config_id: str
    run_index: int
    level: str
    elapsed_s: float
    cer: float | None
    wer: float | None
    char_accuracy: float | None
    output_file: str
    metrics: dict[str, Any]
    error: str | None = None

    @property
    def key(self) -> tuple[str, str, int, str]:
        return (self.stage, self.config_id, self.run_index, self.level)


@dataclass(frozen=True)
class DocumentAggregate:
    level: str
    successful_runs: int
    expected_runs: int
    valid: bool
    trimmed_cer: float
    trimmed_wer: float
    trimmed_char_accuracy: float
    trimmed_elapsed_s: float
    trimmed_request_elapsed_s: float
    trimmed_encoded_bytes: float
    cache_n_total: int


@dataclass(frozen=True)
class ConfigAggregate:
    config_id: str
    levels: tuple[str, ...]
    valid: bool
    macro_char_accuracy: float
    macro_cer: float
    macro_wer: float
    macro_elapsed_s: float
    macro_request_elapsed_s: float
    mean_encoded_bytes: float
    cache_n_total: int
    documents: dict[str, DocumentAggregate]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    """Normalize scoring text while removing only app-added PDF page markers."""
    value = unicodedata.normalize("NFKC", str(text)).replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"(?m)^\s*---\s*Pagina\s+\d+\s*---\s*$", "", value)
    return " ".join(value.split())


def _levenshtein_sequence(a: Sequence[Any], b: Sequence[Any]) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, item_a in enumerate(a, start=1):
        current = [i]
        for j, item_b in enumerate(b, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (item_a != item_b),
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(expected: str, actual: str) -> float:
    expected_norm = normalize_text(expected)
    actual_norm = normalize_text(actual)
    if not expected_norm:
        return 0.0 if not actual_norm else 1.0
    return _levenshtein_sequence(expected_norm, actual_norm) / len(expected_norm)


def word_error_rate(expected: str, actual: str) -> float:
    expected_words = normalize_text(expected).split()
    actual_words = normalize_text(actual).split()
    if not expected_words:
        return 0.0 if not actual_words else 1.0
    return _levenshtein_sequence(expected_words, actual_words) / len(expected_words)


def trimmed_mean(values: Sequence[float], *, trim: int = DEFAULT_TRIM) -> float:
    values = [float(value) for value in values]
    if trim < 0:
        raise ValueError("trim deve essere >= 0")
    if len(values) <= 2 * trim:
        raise ValueError("Valori insufficienti per la trimmed mean richiesta")
    ordered = sorted(values)
    kept = ordered[trim : len(ordered) - trim] if trim else ordered
    return statistics.mean(kept)


def parse_ground_truth_markdown(text: str) -> dict[str, str]:
    """Parse strict FACILE/MEDIO/DIFFICILE fenced-text sections."""
    headers = list(re.finditer(r"(?im)^\s*#\s+(FACILE|MEDIO|DIFFICILE)\s*$", str(text)))
    if len(headers) != 3:
        raise ValueError(
            "Il ground truth deve contenere esattamente le sezioni # FACILE, "
            "# MEDIO e # DIFFICILE"
        )

    result: dict[str, str] = {}
    for index, header in enumerate(headers):
        label = header.group(1).lower()
        start = header.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        body = str(text)[start:end]
        match = re.search(r"```(?:text)?\s*\n(.*?)\n```", body, flags=re.DOTALL | re.IGNORECASE)
        if match is None:
            raise ValueError(f"Sezione {label.upper()}: blocco ```text ... ``` mancante")
        value = match.group(1).strip()
        if not value:
            raise ValueError(f"Sezione {label.upper()}: trascrizione vuota")
        if label in result:
            raise ValueError(f"Sezione duplicata: {label.upper()}")
        result[label] = value

    if set(result) != set(LEVELS):
        raise ValueError("Ground truth incompleto")
    return result


def load_ground_truth(path: Path) -> dict[str, str]:
    if path.suffix.lower() != ".md":
        raise ValueError("Il ground truth deve essere un file .md")
    return parse_ground_truth_markdown(path.read_text(encoding="utf-8"))


def validate_documents(documents: Sequence[BenchmarkDocument]) -> None:
    if tuple(document.level for document in documents) != LEVELS:
        raise ValueError("I documenti devono essere ordinati come facile, medio, difficile")
    for document in documents:
        if not document.path.is_file():
            raise ValueError(f"Documento non trovato: {document.path}")
        if not document.expected_text.strip():
            raise ValueError(f"Ground truth vuoto per {document.level}")
    if not documents[0].is_pdf:
        raise ValueError("Il documento FACILE deve essere un PDF digitale")
    if not documents[1].is_pdf:
        raise ValueError("Il documento MEDIO deve essere un PDF da scansione")


def rotation_order(run_index: int) -> tuple[str, ...]:
    """Five-run order schedule that avoids a fixed first/last difficulty."""
    rotations = (
        ("facile", "medio", "difficile"),
        ("medio", "difficile", "facile"),
        ("difficile", "facile", "medio"),
        ("facile", "difficile", "medio"),
        ("medio", "facile", "difficile"),
    )
    if run_index < 1:
        raise ValueError("run_index deve essere >= 1")
    return rotations[(run_index - 1) % len(rotations)]


def production_baseline(prompt: str = PROMPT_LEGACY_OCR, *, name: str = "baseline") -> PipelineConfig:
    return PipelineConfig(name=name, prompt=prompt)


def prompt_configs() -> list[PipelineConfig]:
    return [
        production_baseline(PROMPT_LEGACY_OCR, name="prompt_ocr"),
        production_baseline(PROMPT_TEXT_RECOGNITION, name="prompt_text_recognition"),
    ]


def stage_a_configs(prompt: str) -> dict[str, list[PipelineConfig]]:
    """Build OFAT sweeps; the DPI baseline has its own matched PDF-only workload."""
    shared_baseline = production_baseline(prompt, name="stage_a_baseline")
    return {
        "pdf_dpi": [
            PipelineConfig(name=f"a_pdf_dpi_{value}", prompt=prompt, pdf_dpi=value)
            for value in PDF_DPI_VALUES
        ],
        "max_image_dim": [
            shared_baseline
            if value == MAX_IMAGE_DIM
            else PipelineConfig(name=f"a_maxdim_{value}", prompt=prompt, max_image_dim=value)
            for value in MAX_IMAGE_DIM_VALUES
        ],
        "jpeg_quality": [
            shared_baseline
            if value == JPEG_QUALITY
            else PipelineConfig(name=f"a_jpeg_{value}", prompt=prompt, jpeg_quality=value)
            for value in JPEG_QUALITY_VALUES
        ],
        "preprocessing_mode": [
            shared_baseline
            if value == "full"
            else PipelineConfig(name=f"a_pre_{value}", prompt=prompt, preprocessing_mode=value)
            for value in PREPROCESSING_VALUES
        ],
    }


def affected_levels(variable: str, documents: Sequence[BenchmarkDocument]) -> tuple[str, ...]:
    if variable == "pdf_dpi":
        return tuple(document.level for document in documents if document.is_pdf)
    return tuple(document.level for document in documents)


def config_variable_value(config: PipelineConfig, variable: str) -> Any:
    if variable not in {"pdf_dpi", "max_image_dim", "jpeg_quality", "preprocessing_mode"}:
        raise ValueError(f"Variabile sconosciuta: {variable}")
    return getattr(config, variable)


def _metric_total(metrics: Sequence[dict[str, Any]], key: str) -> float:
    return sum(float(item.get(key, 0.0) or 0.0) for item in metrics)


def aggregate_config(
    observations: Sequence[Observation],
    *,
    config_id: str,
    levels: Sequence[str],
    expected_runs: int = DEFAULT_RUNS,
    trim: int = DEFAULT_TRIM,
) -> ConfigAggregate:
    documents: dict[str, DocumentAggregate] = {}
    for level in levels:
        runs = [
            item
            for item in observations
            if item.config_id == config_id and item.level == level and item.error is None
        ]
        valid = len(runs) == expected_runs
        if valid:
            cers = [float(item.cer) for item in runs if item.cer is not None]
            wers = [float(item.wer) for item in runs if item.wer is not None]
            accuracies = [float(item.char_accuracy) for item in runs if item.char_accuracy is not None]
            elapsed = [item.elapsed_s for item in runs]
            request_elapsed = [_metric_total(item.metrics.get("pages", []), "request_elapsed_s") for item in runs]
            encoded_bytes = [_metric_total(item.metrics.get("pages", []), "encoded_bytes") for item in runs]
            cache_total = sum(int(_metric_total(item.metrics.get("pages", []), "cache_n")) for item in runs)
            doc = DocumentAggregate(
                level=level,
                successful_runs=len(runs),
                expected_runs=expected_runs,
                valid=True,
                trimmed_cer=trimmed_mean(cers, trim=trim),
                trimmed_wer=trimmed_mean(wers, trim=trim),
                trimmed_char_accuracy=trimmed_mean(accuracies, trim=trim),
                trimmed_elapsed_s=trimmed_mean(elapsed, trim=trim),
                trimmed_request_elapsed_s=trimmed_mean(request_elapsed, trim=trim),
                trimmed_encoded_bytes=trimmed_mean(encoded_bytes, trim=trim),
                cache_n_total=cache_total,
            )
        else:
            doc = DocumentAggregate(
                level=level,
                successful_runs=len(runs),
                expected_runs=expected_runs,
                valid=False,
                trimmed_cer=math.inf,
                trimmed_wer=math.inf,
                trimmed_char_accuracy=-math.inf,
                trimmed_elapsed_s=math.inf,
                trimmed_request_elapsed_s=math.inf,
                trimmed_encoded_bytes=math.inf,
                cache_n_total=sum(int(_metric_total(item.metrics.get("pages", []), "cache_n")) for item in runs),
            )
        documents[level] = doc

    valid = bool(documents) and all(item.valid for item in documents.values())
    if valid:
        macro_accuracy = statistics.mean(item.trimmed_char_accuracy for item in documents.values())
        macro_cer = statistics.mean(item.trimmed_cer for item in documents.values())
        macro_wer = statistics.mean(item.trimmed_wer for item in documents.values())
        macro_elapsed = statistics.mean(item.trimmed_elapsed_s for item in documents.values())
        macro_request = statistics.mean(item.trimmed_request_elapsed_s for item in documents.values())
        mean_bytes = statistics.mean(item.trimmed_encoded_bytes for item in documents.values())
    else:
        macro_accuracy = -math.inf
        macro_cer = math.inf
        macro_wer = math.inf
        macro_elapsed = math.inf
        macro_request = math.inf
        mean_bytes = math.inf

    return ConfigAggregate(
        config_id=config_id,
        levels=tuple(levels),
        valid=valid,
        macro_char_accuracy=macro_accuracy,
        macro_cer=macro_cer,
        macro_wer=macro_wer,
        macro_elapsed_s=macro_elapsed,
        macro_request_elapsed_s=macro_request,
        mean_encoded_bytes=mean_bytes,
        cache_n_total=sum(item.cache_n_total for item in documents.values()),
        documents=documents,
    )


def choose_quality_equivalent_fastest(
    aggregates: Sequence[ConfigAggregate],
    *,
    tolerance_pp: float = DEFAULT_ACCURACY_TOLERANCE_PP,
) -> ConfigAggregate:
    valid = [item for item in aggregates if item.valid and item.cache_n_total == 0]
    if not valid:
        raise ValueError("Nessuna configurazione valida e cache-free")
    best_accuracy = max(item.macro_char_accuracy for item in valid)
    tolerance = float(tolerance_pp) / 100.0
    eligible = [item for item in valid if item.macro_char_accuracy >= best_accuracy - tolerance]
    return min(eligible, key=lambda item: (item.macro_elapsed_s, -item.macro_char_accuracy))


def select_fastest_quality_gated_values(
    candidates: Sequence[tuple[Any, ConfigAggregate]],
    *,
    top_n: int = DEFAULT_TOP_VALUES,
    tolerance_pp: float = DEFAULT_ACCURACY_TOLERANCE_PP,
) -> list[Any]:
    valid = [
        (value, aggregate)
        for value, aggregate in candidates
        if aggregate.valid and aggregate.cache_n_total == 0
    ]
    if not valid:
        raise ValueError("Nessun valore Stage A valido e cache-free")
    best_accuracy = max(aggregate.macro_char_accuracy for _, aggregate in valid)
    tolerance = float(tolerance_pp) / 100.0
    eligible = [
        (value, aggregate)
        for value, aggregate in valid
        if aggregate.macro_char_accuracy >= best_accuracy - tolerance
    ]
    eligible.sort(key=lambda item: (item[1].macro_elapsed_s, -item[1].macro_char_accuracy))
    return [value for value, _aggregate in eligible[: max(1, int(top_n))]]


def stage_b_configs(
    *,
    prompt: str,
    selected: dict[str, Sequence[Any]],
) -> list[PipelineConfig]:
    required = {"pdf_dpi", "max_image_dim", "jpeg_quality", "preprocessing_mode"}
    if set(selected) != required:
        raise ValueError(f"Selezione Stage B incompleta: attese {sorted(required)}")

    configs: list[PipelineConfig] = []
    seen: set[str] = set()
    for dpi, max_dim, jpeg, pre in itertools.product(
        selected["pdf_dpi"],
        selected["max_image_dim"],
        selected["jpeg_quality"],
        selected["preprocessing_mode"],
    ):
        candidate = PipelineConfig(
            name="",
            prompt=prompt,
            preprocessing_mode=str(pre),
            pdf_dpi=int(dpi),
            max_image_dim=int(max_dim),
            jpeg_quality=int(jpeg),
        )
        signature = candidate.signature()
        if signature in seen:
            continue
        seen.add(signature)
        configs.append(
            PipelineConfig(
                name=f"b_{signature}",
                prompt=candidate.prompt,
                preprocessing_mode=candidate.preprocessing_mode,
                pdf_dpi=candidate.pdf_dpi,
                max_image_dim=candidate.max_image_dim,
                jpeg_quality=candidate.jpeg_quality,
            )
        )
    return configs


def speedup_vs_baseline(aggregate: ConfigAggregate, baseline_documents: dict[str, float]) -> float:
    ratios: list[float] = []
    for level, doc in aggregate.documents.items():
        baseline = baseline_documents.get(level)
        if baseline is None or baseline <= 0 or not doc.valid:
            continue
        ratios.append(baseline / doc.trimmed_elapsed_s)
    return statistics.mean(ratios) if ratios else 0.0


def pareto_frontier(aggregates: Sequence[ConfigAggregate]) -> list[ConfigAggregate]:
    valid = [item for item in aggregates if item.valid and item.cache_n_total == 0]
    frontier: list[ConfigAggregate] = []
    for candidate in valid:
        dominated = any(
            other.config_id != candidate.config_id
            and other.macro_char_accuracy >= candidate.macro_char_accuracy
            and other.macro_elapsed_s <= candidate.macro_elapsed_s
            and (
                other.macro_char_accuracy > candidate.macro_char_accuracy
                or other.macro_elapsed_s < candidate.macro_elapsed_s
            )
            for other in valid
        )
        if not dominated:
            frontier.append(candidate)
    return sorted(frontier, key=lambda item: (-item.macro_char_accuracy, item.macro_elapsed_s))


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def observation_to_dict(observation: Observation) -> dict[str, Any]:
    return asdict(observation)


def observation_from_dict(payload: dict[str, Any]) -> Observation:
    return Observation(
        stage=str(payload["stage"]),
        config_id=str(payload["config_id"]),
        run_index=int(payload["run_index"]),
        level=str(payload["level"]),
        elapsed_s=float(payload["elapsed_s"]),
        cer=None if payload.get("cer") is None else float(payload["cer"]),
        wer=None if payload.get("wer") is None else float(payload["wer"]),
        char_accuracy=(
            None if payload.get("char_accuracy") is None else float(payload["char_accuracy"])
        ),
        output_file=str(payload.get("output_file", "")),
        metrics=dict(payload.get("metrics") or {}),
        error=None if payload.get("error") is None else str(payload["error"]),
    )


def unique_configs(groups: Iterable[Iterable[PipelineConfig]]) -> list[PipelineConfig]:
    seen: set[str] = set()
    result: list[PipelineConfig] = []
    for group in groups:
        for config in group:
            if config.name in seen:
                continue
            seen.add(config.name)
            result.append(config)
    return result
