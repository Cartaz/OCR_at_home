"""Pure helpers for the extended canonical GLM-OCR hardware benchmark."""

from __future__ import annotations

import difflib
import hashlib
import math
import os
import re
import statistics
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Sequence

from core.llama_ocr_api import (
    JPEG_QUALITY,
    MAX_IMAGE_DIM,
    PDF_DPI,
    PROMPT_LEGACY_OCR,
    PROMPT_TEXT_RECOGNITION,
)
from tests.benchmark.runtime_backend import (
    RuntimeCapabilities,
    ServerRuntimeConfig,
    stock_runtime_config,
    runtime_stage_a_values,
)

LEVELS = ("facile", "medio", "difficile")
HANDWRITING_SEGMENTS = ("maiuscolo", "script", "corsivo")
PDF_DPI_VALUES = (100, 125, 150, 175, 200, 250, 300)
MAX_IMAGE_DIM_VALUES = (1024, 1280, 1536, 1920, 2304, 2560, 3072)
JPEG_QUALITY_VALUES = (50, 60, 70, 80, 85, 90, 95, 100)
PREPROCESSING_VALUES = ("none", "contrast", "resize", "full")
PIPELINE_VARIABLES = (
    "pdf_dpi",
    "max_image_dim",
    "jpeg_quality",
    "preprocessing_mode",
)
RUNTIME_VARIABLES = (
    "context_size",
    "batch_size",
    "ubatch_size",
    "threads",
    "threads_batch",
    "flash_attn",
    "cache_type_k",
    "cache_type_v",
    "spec_type",
    "kv_offload",
    "op_offload",
)
DEFAULT_RUNS = 5
DEFAULT_TRIM = 1
DEFAULT_TOP_VALUES = 5
DEFAULT_BEAM_WIDTH = 5
DEFAULT_MACRO_TOLERANCE_PP = 0.25
DEFAULT_DOCUMENT_TOLERANCE_PP = 0.50
DEFAULT_WER_TOLERANCE_PP = 1.00
BORDERLINE_MACRO_PP = 0.40
BORDERLINE_DOCUMENT_PP = 0.75
BORDERLINE_WER_PP = 1.50
BENCHMARK_SEED = 20260821


@dataclass(frozen=True)
class GroundTruth:
    facile: str
    medio: str
    difficile_segments: dict[str, str]

    @property
    def difficile(self) -> str:
        return "\n".join(self.difficile_segments[name] for name in HANDWRITING_SEGMENTS)


@dataclass(frozen=True)
class BenchmarkDocument:
    level: str
    path: Path
    expected_text: str
    segments: dict[str, str] = field(default_factory=dict)

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
    runtime: ServerRuntimeConfig = field(default_factory=stock_runtime_config)

    def signature(self) -> str:
        prompt_name = "text" if self.prompt == PROMPT_TEXT_RECOGNITION else "ocr"
        return (
            f"{prompt_name}-pre_{self.preprocessing_mode}-dpi_{self.pdf_dpi}-"
            f"max_{self.max_image_dim}-jpg_{self.jpeg_quality}-"
            f"{self.runtime.signature()}"
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
    segment_scores: dict[str, dict[str, float]] = field(default_factory=dict)
    error: str | None = None

    @property
    def key(self) -> tuple[str, str, int, str]:
        return self.stage, self.config_id, self.run_index, self.level


@dataclass(frozen=True)
class QualityAggregate:
    cer: float
    wer: float
    char_accuracy: float


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
    hard_segments: dict[str, QualityAggregate] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityGateResult:
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class QualityReference:
    best_macro_accuracy: float
    document_accuracy: dict[str, float]
    document_wer: dict[str, float]
    segment_accuracy: dict[str, float]
    segment_wer: dict[str, float]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
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
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (item_a != item_b)))
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


def trimmed_mean(values: Sequence[float], *, trim: int) -> float:
    ordered = sorted(float(value) for value in values)
    if trim < 0 or len(ordered) <= 2 * trim:
        raise ValueError("trim incompatibile con il numero di osservazioni")
    kept = ordered[trim : len(ordered) - trim] if trim else ordered
    return statistics.mean(kept)


def trim_for_runs(run_count: int) -> int:
    if run_count < 3:
        raise ValueError("servono almeno 3 run")
    return max(1, int(run_count) // 5)


def _section_body(markdown: str, title: str, next_titles: Sequence[str]) -> str:
    start_match = re.search(rf"(?im)^#\s+{re.escape(title)}\s*$", markdown)
    if start_match is None:
        raise ValueError(f"Sezione # {title} mancante")
    end = len(markdown)
    for next_title in next_titles:
        match = re.search(rf"(?im)^#\s+{re.escape(next_title)}\s*$", markdown[start_match.end() :])
        if match is not None:
            end = min(end, start_match.end() + match.start())
    return markdown[start_match.end() : end]


def _fenced_text(body: str, label: str) -> str:
    match = re.search(r"```(?:text)?\s*\n(.*?)\n```", body, flags=re.DOTALL | re.IGNORECASE)
    if match is None or not match.group(1).strip():
        raise ValueError(f"{label}: blocco ```text ... ``` mancante o vuoto")
    return match.group(1).strip()


def parse_ground_truth_markdown(markdown: str) -> GroundTruth:
    top_headers = re.findall(r"(?im)^#\s+(FACILE|MEDIO|DIFFICILE)\s*$", markdown)
    if top_headers != ["FACILE", "MEDIO", "DIFFICILE"]:
        raise ValueError("Servono esattamente # FACILE, # MEDIO, # DIFFICILE in quest'ordine")
    facile = _fenced_text(_section_body(markdown, "FACILE", ("MEDIO", "DIFFICILE")), "FACILE")
    medio = _fenced_text(_section_body(markdown, "MEDIO", ("DIFFICILE",)), "MEDIO")
    hard_body = _section_body(markdown, "DIFFICILE", ())
    subheaders = re.findall(r"(?im)^##\s+(MAIUSCOLO|SCRIPT|CORSIVO)\s*$", hard_body)
    if subheaders != ["MAIUSCOLO", "SCRIPT", "CORSIVO"]:
        raise ValueError("DIFFICILE deve contenere ## MAIUSCOLO, ## SCRIPT, ## CORSIVO in quest'ordine")
    segments: dict[str, str] = {}
    for index, heading in enumerate(("MAIUSCOLO", "SCRIPT", "CORSIVO")):
        start = re.search(rf"(?im)^##\s+{heading}\s*$", hard_body)
        assert start is not None
        end = len(hard_body)
        if index + 1 < len(HANDWRITING_SEGMENTS):
            next_heading = ("MAIUSCOLO", "SCRIPT", "CORSIVO")[index + 1]
            nxt = re.search(rf"(?im)^##\s+{next_heading}\s*$", hard_body[start.end() :])
            if nxt is not None:
                end = start.end() + nxt.start()
        segments[HANDWRITING_SEGMENTS[index]] = _fenced_text(hard_body[start.end() : end], heading)
    return GroundTruth(facile=facile, medio=medio, difficile_segments=segments)


def load_ground_truth(path: Path) -> GroundTruth:
    if path.suffix.lower() != ".md":
        raise ValueError("Il ground truth deve essere .md")
    return parse_ground_truth_markdown(path.read_text(encoding="utf-8"))


def documents_from_ground_truth(easy: Path, medium: Path, hard: Path, truth: GroundTruth) -> list[BenchmarkDocument]:
    docs = [
        BenchmarkDocument("facile", easy, truth.facile),
        BenchmarkDocument("medio", medium, truth.medio),
        BenchmarkDocument("difficile", hard, truth.difficile, dict(truth.difficile_segments)),
    ]
    validate_documents(docs)
    return docs


def validate_documents(documents: Sequence[BenchmarkDocument]) -> None:
    if tuple(doc.level for doc in documents) != LEVELS:
        raise ValueError("Ordine documenti atteso: facile, medio, difficile")
    for doc in documents:
        if not doc.path.is_file():
            raise ValueError(f"Documento non trovato: {doc.path}")
        if not doc.expected_text.strip():
            raise ValueError(f"Ground truth vuoto per {doc.level}")
    if not documents[0].is_pdf or not documents[1].is_pdf:
        raise ValueError("FACILE e MEDIO devono essere PDF")
    if tuple(documents[2].segments) != HANDWRITING_SEGMENTS:
        raise ValueError("DIFFICILE deve avere MAIUSCOLO/SCRIPT/CORSIVO")


def _map_expected_boundary(expected: str, actual: str, boundary: int) -> int:
    matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
    for _tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if i1 <= boundary <= i2:
            if i2 == i1:
                return j1
            ratio = (boundary - i1) / (i2 - i1)
            return max(0, min(len(actual), round(j1 + ratio * (j2 - j1))))
    return len(actual)


def score_document(document: BenchmarkDocument, output: str) -> tuple[float, float, float, dict[str, dict[str, float]]]:
    cer = character_error_rate(document.expected_text, output)
    wer = word_error_rate(document.expected_text, output)
    accuracy = max(0.0, min(1.0, 1.0 - cer))
    if document.level != "difficile" or not document.segments:
        return cer, wer, accuracy, {}

    expected_parts = [normalize_text(document.segments[name]) for name in HANDWRITING_SEGMENTS]
    expected_full = " ".join(expected_parts)
    actual_full = normalize_text(output)
    b1 = len(expected_parts[0])
    b2 = b1 + 1 + len(expected_parts[1])
    a1 = _map_expected_boundary(expected_full, actual_full, b1)
    a2 = _map_expected_boundary(expected_full, actual_full, b2)
    a1 = max(0, min(a1, len(actual_full)))
    a2 = max(a1, min(a2, len(actual_full)))
    actual_parts = (actual_full[:a1], actual_full[a1:a2], actual_full[a2:])
    scores: dict[str, dict[str, float]] = {}
    for name, expected_part, actual_part in zip(HANDWRITING_SEGMENTS, expected_parts, actual_parts):
        part_cer = character_error_rate(expected_part, actual_part)
        part_wer = word_error_rate(expected_part, actual_part)
        scores[name] = {
            "cer": part_cer,
            "wer": part_wer,
            "char_accuracy": max(0.0, min(1.0, 1.0 - part_cer)),
        }
    return cer, wer, accuracy, scores


def rotation_order(run_index: int) -> tuple[str, ...]:
    orders = (
        ("facile", "medio", "difficile"),
        ("medio", "difficile", "facile"),
        ("difficile", "facile", "medio"),
        ("facile", "difficile", "medio"),
        ("medio", "facile", "difficile"),
    )
    if run_index < 1:
        raise ValueError("run_index deve essere >=1")
    return orders[(run_index - 1) % len(orders)]


def production_baseline(prompt: str = PROMPT_LEGACY_OCR, *, name: str = "baseline") -> PipelineConfig:
    return PipelineConfig(name=name, prompt=prompt, runtime=stock_runtime_config())


def prompt_configs() -> list[PipelineConfig]:
    return [
        production_baseline(PROMPT_LEGACY_OCR, name="prompt_ocr"),
        production_baseline(PROMPT_TEXT_RECOGNITION, name="prompt_text_recognition"),
    ]


def _replace_variable(config: PipelineConfig, variable: str, value: Any, *, name: str) -> PipelineConfig | None:
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


def stage_a_groups(prompt: str, capabilities: RuntimeCapabilities) -> dict[str, list[PipelineConfig]]:
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
            config = _replace_variable(baseline, variable, value, name=f"a_{variable}_{str(value).lower()}")
            if config is not None:
                configs.append(config)
        if all(config.name != baseline.name for config in configs):
            configs.append(baseline)
        groups[variable] = configs
    return groups


def affected_levels(variable: str, documents: Sequence[BenchmarkDocument]) -> tuple[str, ...]:
    if variable == "pdf_dpi":
        return tuple(doc.level for doc in documents if doc.is_pdf)
    return tuple(doc.level for doc in documents)


def config_variable_value(config: PipelineConfig, variable: str) -> Any:
    if variable in PIPELINE_VARIABLES:
        return getattr(config, variable)
    if variable in RUNTIME_VARIABLES:
        return getattr(config.runtime.resolved(), variable)
    raise ValueError(f"Variabile sconosciuta: {variable}")


def _metric_total(metrics: Sequence[dict[str, Any]], key: str) -> float:
    return sum(float(item.get(key, 0.0) or 0.0) for item in metrics)


def aggregate_config(observations: Sequence[Observation], *, config_id: str, levels: Sequence[str], expected_runs: int) -> ConfigAggregate:
    trim = trim_for_runs(expected_runs)
    docs: dict[str, DocumentAggregate] = {}
    for level in levels:
        runs = [o for o in observations if o.config_id == config_id and o.level == level and o.error is None and o.run_index <= expected_runs]
        valid = len(runs) == expected_runs and all(o.cer is not None and o.wer is not None and o.char_accuracy is not None for o in runs)
        if valid:
            pages = [o.metrics.get("pages", []) for o in runs]
            docs[level] = DocumentAggregate(
                level=level,
                successful_runs=len(runs),
                expected_runs=expected_runs,
                valid=True,
                trimmed_cer=trimmed_mean([float(o.cer) for o in runs], trim=trim),
                trimmed_wer=trimmed_mean([float(o.wer) for o in runs], trim=trim),
                trimmed_char_accuracy=trimmed_mean([float(o.char_accuracy) for o in runs], trim=trim),
                trimmed_elapsed_s=trimmed_mean([o.elapsed_s for o in runs], trim=trim),
                trimmed_request_elapsed_s=trimmed_mean([_metric_total(p, "request_elapsed_s") for p in pages], trim=trim),
                trimmed_encoded_bytes=trimmed_mean([_metric_total(p, "encoded_bytes") for p in pages], trim=trim),
                cache_n_total=sum(int(_metric_total(p, "cache_n")) for p in pages),
            )
        else:
            docs[level] = DocumentAggregate(level, len(runs), expected_runs, False, math.inf, math.inf, -math.inf, math.inf, math.inf, math.inf, 0)

    hard_segments: dict[str, QualityAggregate] = {}
    if "difficile" in levels:
        hard_runs = [o for o in observations if o.config_id == config_id and o.level == "difficile" and o.error is None and o.run_index <= expected_runs]
        for segment in HANDWRITING_SEGMENTS:
            if len(hard_runs) == expected_runs and all(segment in o.segment_scores for o in hard_runs):
                hard_segments[segment] = QualityAggregate(
                    cer=trimmed_mean([o.segment_scores[segment]["cer"] for o in hard_runs], trim=trim),
                    wer=trimmed_mean([o.segment_scores[segment]["wer"] for o in hard_runs], trim=trim),
                    char_accuracy=trimmed_mean([o.segment_scores[segment]["char_accuracy"] for o in hard_runs], trim=trim),
                )

    valid = bool(docs) and all(doc.valid for doc in docs.values())
    if valid:
        macro_accuracy = statistics.mean(doc.trimmed_char_accuracy for doc in docs.values())
        macro_cer = statistics.mean(doc.trimmed_cer for doc in docs.values())
        macro_wer = statistics.mean(doc.trimmed_wer for doc in docs.values())
        macro_elapsed = statistics.mean(doc.trimmed_elapsed_s for doc in docs.values())
        macro_request = statistics.mean(doc.trimmed_request_elapsed_s for doc in docs.values())
        mean_bytes = statistics.mean(doc.trimmed_encoded_bytes for doc in docs.values())
    else:
        macro_accuracy, macro_cer, macro_wer = -math.inf, math.inf, math.inf
        macro_elapsed = macro_request = mean_bytes = math.inf
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
        cache_n_total=sum(doc.cache_n_total for doc in docs.values()),
        documents=docs,
        hard_segments=hard_segments,
    )


def quality_reference(aggregates: Sequence[ConfigAggregate]) -> QualityReference:
    valid = [a for a in aggregates if a.valid and a.cache_n_total == 0]
    if not valid:
        raise ValueError("Nessuna configurazione valida cache-free")
    levels = sorted({level for a in valid for level in a.documents})
    segments = sorted({name for a in valid for name in a.hard_segments})
    return QualityReference(
        best_macro_accuracy=max(a.macro_char_accuracy for a in valid),
        document_accuracy={level: max(a.documents[level].trimmed_char_accuracy for a in valid if level in a.documents) for level in levels},
        document_wer={level: min(a.documents[level].trimmed_wer for a in valid if level in a.documents) for level in levels},
        segment_accuracy={name: max(a.hard_segments[name].char_accuracy for a in valid if name in a.hard_segments) for name in segments},
        segment_wer={name: min(a.hard_segments[name].wer for a in valid if name in a.hard_segments) for name in segments},
    )


def classify_quality(aggregate: ConfigAggregate, reference: QualityReference) -> QualityGateResult:
    if not aggregate.valid:
        return QualityGateResult("FAIL", ("run incomplete/error",))
    if aggregate.cache_n_total != 0:
        return QualityGateResult("FAIL", (f"cache_n={aggregate.cache_n_total}",))

    pass_failures: list[str] = []
    borderline_failures: list[str] = []

    def check_loss(label: str, loss_pp: float, pass_limit: float, borderline_limit: float) -> None:
        if loss_pp > pass_limit:
            pass_failures.append(f"{label} loss {loss_pp:.3f}pp > {pass_limit:.3f}pp")
        if loss_pp > borderline_limit:
            borderline_failures.append(f"{label} loss {loss_pp:.3f}pp > {borderline_limit:.3f}pp")

    check_loss("macro accuracy", (reference.best_macro_accuracy - aggregate.macro_char_accuracy) * 100.0, DEFAULT_MACRO_TOLERANCE_PP, BORDERLINE_MACRO_PP)
    for level, doc in aggregate.documents.items():
        check_loss(f"{level} accuracy", (reference.document_accuracy[level] - doc.trimmed_char_accuracy) * 100.0, DEFAULT_DOCUMENT_TOLERANCE_PP, BORDERLINE_DOCUMENT_PP)
        check_loss(f"{level} WER", (doc.trimmed_wer - reference.document_wer[level]) * 100.0, DEFAULT_WER_TOLERANCE_PP, BORDERLINE_WER_PP)
    for name, score in aggregate.hard_segments.items():
        check_loss(f"{name} accuracy", (reference.segment_accuracy[name] - score.char_accuracy) * 100.0, DEFAULT_DOCUMENT_TOLERANCE_PP, BORDERLINE_DOCUMENT_PP)
        check_loss(f"{name} WER", (score.wer - reference.segment_wer[name]) * 100.0, DEFAULT_WER_TOLERANCE_PP, BORDERLINE_WER_PP)

    if borderline_failures:
        return QualityGateResult("FAIL", tuple(borderline_failures))
    if pass_failures:
        return QualityGateResult("BORDERLINE", tuple(pass_failures))
    return QualityGateResult("PASS", ())


def select_fastest_quality_gated_values(candidates: Sequence[tuple[Any, ConfigAggregate]], *, top_n: int) -> tuple[list[Any], dict[str, QualityGateResult]]:
    reference = quality_reference([aggregate for _value, aggregate in candidates])
    gates = {aggregate.config_id: classify_quality(aggregate, reference) for _value, aggregate in candidates}
    passing = [(value, aggregate) for value, aggregate in candidates if gates[aggregate.config_id].status == "PASS"]
    passing.sort(key=lambda item: (item[1].macro_elapsed_s, -item[1].macro_char_accuracy))
    return [value for value, _aggregate in passing[: max(1, int(top_n))]], gates


def fastest_quality_equivalent(aggregates: Sequence[ConfigAggregate]) -> ConfigAggregate:
    reference = quality_reference(aggregates)
    passing = [a for a in aggregates if classify_quality(a, reference).status == "PASS"]
    if not passing:
        raise ValueError("Nessuna configurazione supera il quality gate")
    return min(passing, key=lambda a: (a.macro_elapsed_s, -a.macro_char_accuracy))


def beam_expand(beam: Sequence[PipelineConfig], variable: str, values: Sequence[Any], *, step: int) -> list[PipelineConfig]:
    result: list[PipelineConfig] = []
    seen: set[str] = set()
    for base in beam:
        for value in values:
            config = _replace_variable(base, variable, value, name="")
            if config is None:
                continue
            signature = config.signature()
            if signature in seen:
                continue
            seen.add(signature)
            result.append(replace(config, name=f"b{step:02d}_{signature}"))
    return result


def pareto_frontier(aggregates: Sequence[ConfigAggregate]) -> list[ConfigAggregate]:
    valid = [a for a in aggregates if a.valid and a.cache_n_total == 0]
    frontier: list[ConfigAggregate] = []
    for candidate in valid:
        dominated = any(
            other.config_id != candidate.config_id
            and other.macro_char_accuracy >= candidate.macro_char_accuracy
            and other.macro_elapsed_s <= candidate.macro_elapsed_s
            and (other.macro_char_accuracy > candidate.macro_char_accuracy or other.macro_elapsed_s < candidate.macro_elapsed_s)
            for other in valid
        )
        if not dominated:
            frontier.append(candidate)
    return sorted(frontier, key=lambda a: (-a.macro_char_accuracy, a.macro_elapsed_s))


def atomic_write_json(path: Path, payload: Any) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


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
        char_accuracy=None if payload.get("char_accuracy") is None else float(payload["char_accuracy"]),
        output_file=str(payload.get("output_file", "")),
        metrics=dict(payload.get("metrics") or {}),
        segment_scores={str(k): dict(v) for k, v in dict(payload.get("segment_scores") or {}).items()},
        error=None if payload.get("error") is None else str(payload["error"]),
    )


def unique_configs(groups: Iterable[Iterable[PipelineConfig]]) -> list[PipelineConfig]:
    result: list[PipelineConfig] = []
    seen: set[str] = set()
    for group in groups:
        for config in group:
            if config.name not in seen:
                seen.add(config.name)
                result.append(config)
    return result
