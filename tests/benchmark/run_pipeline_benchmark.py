"""Phase 5 GLM-OCR image/PDF pipeline benchmark.

The production defaults are not changed by this module. It evaluates one factor
at a time (preprocessing, PDF DPI, maximum image dimension and JPEG quality),
records OCR quality plus transfer/runtime diagnostics, and can restart the owned
llama-server between configurations to remove repeated-request cache state from
performance comparisons.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.llama_backend as llama_backend  # noqa: E402
from core.llama_backend import LlamaServerBackend  # noqa: E402
from core.llama_ocr_api import (  # noqa: E402
    JPEG_QUALITY,
    MAX_IMAGE_DIM,
    OCR_PROMPT,
    PDF_DPI,
    ocr_pdf,
    ocr_single_image,
)
from tests.benchmark.benchmark_prompt_quality import (  # noqa: E402
    Sample,
    build_corpus,
    character_error_rate,
    load_manifest_corpus,
)


# Benchmark-only limits. Production remains at its current 4096-token context
# and 1920px image cap. 8192px is effectively uncapped for the supported PDF
# range up to 600 DPI (an A4 page is ~7016px on its long side at 600 DPI).
BENCHMARK_CONTEXT_SIZE = 16384
BENCHMARK_MAX_IMAGE_DIM = 8192


@dataclass(frozen=True)
class PipelineConfig:
    name: str
    preprocessing_enabled: bool = True
    pdf_dpi: int = PDF_DPI
    max_image_dim: int = BENCHMARK_MAX_IMAGE_DIM
    jpeg_quality: int = JPEG_QUALITY


@dataclass
class PipelineRun:
    config: str
    sample: str
    source_type: str
    elapsed_s: float
    output: str = ""
    cer: float | None = None
    error: str | None = None
    metrics: list[dict[str, Any]] = field(default_factory=list)


def pipeline_configs(*, quick: bool = False) -> list[PipelineConfig]:
    baseline = PipelineConfig("baseline")
    configs = [
        baseline,
        PipelineConfig("preprocess_off", preprocessing_enabled=False),
        PipelineConfig("pdf_dpi_100", pdf_dpi=100),
        PipelineConfig("pdf_dpi_200", pdf_dpi=200),
        PipelineConfig("pdf_dpi_300", pdf_dpi=300),
        PipelineConfig("maxdim_1280", max_image_dim=1280),
        PipelineConfig("maxdim_1600", max_image_dim=1600),
        PipelineConfig("maxdim_2560", max_image_dim=2560),
        PipelineConfig("jpeg_70", jpeg_quality=70),
        PipelineConfig("jpeg_95", jpeg_quality=95),
    ]
    if quick:
        keep = {"baseline", "preprocess_off", "pdf_dpi_200", "maxdim_1280", "jpeg_70"}
        return [item for item in configs if item.name in keep]
    return configs


def config_applies_to_sample(config: PipelineConfig, sample: Sample) -> bool:
    is_pdf = sample.image_path.suffix.lower() == ".pdf"
    # DPI has no effect on raster-image inputs, so do not spend an inference on
    # a configuration that is byte-for-byte identical to the baseline there.
    if not is_pdf and config.name.startswith("pdf_dpi_"):
        return False
    return sample.task == "text" and sample.score_mode == "cer"


def _build_synthetic_pdf(directory: Path) -> Sample:
    import fitz

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "vector_text.pdf"
    page_texts = [
        (
            "Pipeline PDF benchmark\n"
            "Testo vettoriale a dimensione normale.\n"
            "Numero pagina 1: 12345."
        ),
        (
            "Testo piccolo su PDF vettoriale.\n"
            "Accenti: qualità, più, perché.\n"
            "Numero pagina 2: 67890."
        ),
    ]

    doc = fitz.open()
    try:
        for index, text in enumerate(page_texts):
            page = doc.new_page(width=595, height=842)
            fontsize = 15 if index == 0 else 8.5
            y = 100.0
            for line in text.splitlines():
                page.insert_text((72, y), line, fontsize=fontsize, fontname="helv")
                y += fontsize * 1.8
        doc.save(path)
    finally:
        doc.close()

    expected = "\n\n".join(
        f"--- Pagina {index} ---\n{text}"
        for index, text in enumerate(page_texts, start=1)
    )
    return Sample(
        name="vector_pdf",
        task="text",
        image_path=path,
        expected_text=expected,
        score_mode="cer",
    )


def build_pipeline_corpus(directory: Path) -> list[Sample]:
    samples = [sample for sample in build_corpus(directory) if sample.task == "text"]
    samples.append(_build_synthetic_pdf(directory))
    return samples


def _flatten_metrics(metrics: Sequence[dict[str, Any]]) -> dict[str, float | int]:
    encoded = [int(item.get("encoded_bytes", 0) or 0) for item in metrics]
    requests = [float(item.get("request_elapsed_s", 0.0) or 0.0) for item in metrics]
    render = [float(item.get("render_elapsed_s", 0.0) or 0.0) for item in metrics]
    preprocess = [float(item.get("preprocess_elapsed_s", 0.0) or 0.0) for item in metrics]
    cache = [int(item.get("cache_n", 0) or 0) for item in metrics]
    return {
        "encoded_bytes_total": sum(encoded),
        "request_elapsed_s_total": sum(requests),
        "render_elapsed_s_total": sum(render),
        "preprocess_elapsed_s_total": sum(preprocess),
        "cache_n_total": sum(cache),
    }


def run_sample(sample: Sample, config: PipelineConfig, server_url: str) -> PipelineRun:
    started = time.perf_counter()
    metrics: list[dict[str, Any]] = []
    try:
        if sample.image_path.suffix.lower() == ".pdf":
            output, _confidence = ocr_pdf(
                sample.image_path,
                server_url,
                preprocessing_enabled=config.preprocessing_enabled,
                emit_events=False,
                prompt=OCR_PROMPT,
                pdf_dpi=config.pdf_dpi,
                max_image_dim=config.max_image_dim,
                jpeg_quality=config.jpeg_quality,
                page_metrics=metrics,
            )
            source_type = "pdf"
        else:
            item_metrics: dict[str, Any] = {
                "preprocessing_enabled": config.preprocessing_enabled,
                "pdf_dpi": None,
            }
            preprocess_started = time.perf_counter()
            output, _confidence = ocr_single_image(
                sample.image_path,
                server_url,
                preprocessing_enabled=config.preprocessing_enabled,
                prompt=OCR_PROMPT,
                max_image_dim=config.max_image_dim,
                jpeg_quality=config.jpeg_quality,
                metrics=item_metrics,
            )
            # For raster inputs this duration includes load+preprocess+request;
            # request_elapsed_s below lets the report separate server time.
            item_metrics["pipeline_elapsed_s"] = time.perf_counter() - preprocess_started
            metrics.append(item_metrics)
            source_type = "image"

        elapsed = time.perf_counter() - started
        return PipelineRun(
            config=config.name,
            sample=sample.name,
            source_type=source_type,
            elapsed_s=elapsed,
            output=output,
            cer=character_error_rate(sample.expected_text, output),
            metrics=metrics,
        )
    except Exception as exc:
        return PipelineRun(
            config=config.name,
            sample=sample.name,
            source_type="pdf" if sample.image_path.suffix.lower() == ".pdf" else "image",
            elapsed_s=time.perf_counter() - started,
            error=str(exc),
            metrics=metrics,
        )


def summarize(results: Sequence[PipelineRun]) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for config_name in sorted({item.config for item in results}):
        group = [item for item in results if item.config == config_name]
        good = [item for item in group if not item.error]
        cers = [float(item.cer) for item in good if item.cer is not None]
        elapsed = [item.elapsed_s for item in good]
        flattened = [_flatten_metrics(item.metrics) for item in good]
        bytes_total = [float(item["encoded_bytes_total"]) for item in flattened]
        request_s = [float(item["request_elapsed_s_total"]) for item in flattened]
        cache_n = [int(item["cache_n_total"]) for item in flattened]
        cache_free_elapsed = [
            run.elapsed_s
            for run, flat in zip(good, flattened)
            if int(flat["cache_n_total"]) == 0
        ]
        summary[config_name] = {
            "runs": len(group),
            "errors": sum(1 for item in group if item.error),
            "mean_cer": statistics.mean(cers) if cers else -1.0,
            "worst_cer": max(cers) if cers else -1.0,
            "mean_elapsed_s": statistics.mean(elapsed) if elapsed else -1.0,
            "median_elapsed_s": statistics.median(elapsed) if elapsed else -1.0,
            "mean_encoded_bytes": statistics.mean(bytes_total) if bytes_total else -1.0,
            "mean_request_elapsed_s": statistics.mean(request_s) if request_s else -1.0,
            "cache_n_total": sum(cache_n),
            "cache_free_runs": len(cache_free_elapsed),
            "mean_cache_free_elapsed_s": (
                statistics.mean(cache_free_elapsed) if cache_free_elapsed else -1.0
            ),
        }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server-url",
        default="",
        help="Use an already-running compatible llama-server.",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help="Use a labelled corpus manifest instead of the synthetic corpus.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Destination for results.json and generated synthetic corpus.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run a reduced five-configuration first pass.",
    )
    parser.add_argument(
        "--restart-server-per-config",
        action="store_true",
        help=(
            "Restart the owned llama-server before every pipeline configuration. "
            "Slower, but recommended when comparing latency because cache state is reset."
        ),
    )
    return parser.parse_args()


def _new_benchmark_backend() -> LlamaServerBackend:
    """Create the owned benchmark server with a benchmark-only 16K context."""
    llama_backend.CONTEXT_SIZE = BENCHMARK_CONTEXT_SIZE
    return LlamaServerBackend()


def main() -> int:
    args = parse_args()
    if args.server_url and args.restart_server_per_config:
        raise SystemExit("--restart-server-per-config non è compatibile con --server-url")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or Path("benchmark-results") / f"glm-ocr-pipeline-{timestamp}"
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.corpus_dir is None:
        corpus = build_pipeline_corpus(output_dir / "corpus")
        corpus_source = "synthetic"
    else:
        corpus = load_manifest_corpus(args.corpus_dir)
        corpus_source = str(args.corpus_dir.expanduser().resolve())

    configs = pipeline_configs(quick=args.quick)
    results: list[PipelineRun] = []
    shared_backend: LlamaServerBackend | None = None
    external_url = str(args.server_url).strip()

    if not external_url and not args.restart_server_per_config:
        shared_backend = _new_benchmark_backend()
        print("[pipeline] Avvio llama-server SYCL condiviso (ctx=16384)...")
        shared_backend.initialize()
        external_url = shared_backend.server_url

    try:
        for config_index, config in enumerate(configs, start=1):
            owned_backend: LlamaServerBackend | None = None
            server_url = external_url
            if args.restart_server_per_config:
                owned_backend = _new_benchmark_backend()
                print(
                    f"[pipeline] [{config_index}/{len(configs)}] "
                    f"fresh llama-server ctx={BENCHMARK_CONTEXT_SIZE} per {config.name}..."
                )
                owned_backend.initialize()
                server_url = owned_backend.server_url
            else:
                print(f"[pipeline] [{config_index}/{len(configs)}] {config.name}")

            try:
                applicable = [
                    sample for sample in corpus if config_applies_to_sample(config, sample)
                ]
                for sample_index, sample in enumerate(applicable, start=1):
                    print(
                        f"  [{sample_index}/{len(applicable)}] {sample.name} "
                        f"pre={config.preprocessing_enabled} dpi={config.pdf_dpi} "
                        f"max={config.max_image_dim} jpeg={config.jpeg_quality}"
                    )
                    result = run_sample(sample, config, server_url)
                    results.append(result)
                    if result.error:
                        print(f"    ERRORE: {result.error}")
                    else:
                        flat = _flatten_metrics(result.metrics)
                        print(
                            f"    CER={result.cer:.4f} total={result.elapsed_s:.2f}s "
                            f"request={flat['request_elapsed_s_total']:.2f}s "
                            f"JPEG={flat['encoded_bytes_total'] / 1024:.1f}KiB "
                            f"cache_n={flat['cache_n_total']}"
                        )
            finally:
                if owned_backend is not None:
                    owned_backend.shutdown()
    finally:
        if shared_backend is not None:
            print("[pipeline] Arresto llama-server condiviso...")
            shared_backend.shutdown()

    summary = summarize(results)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "corpus_source": corpus_source,
        "production_defaults": {
            "context_size": 4096,
            "preprocessing_enabled": True,
            "pdf_dpi": PDF_DPI,
            "max_image_dim": MAX_IMAGE_DIM,
            "jpeg_quality": JPEG_QUALITY,
            "prompt": OCR_PROMPT,
        },
        "benchmark_defaults": {
            "context_size": BENCHMARK_CONTEXT_SIZE,
            "max_image_dim": BENCHMARK_MAX_IMAGE_DIM,
            "resolution_policy": "effectively uncapped for supported PDF DPI range",
        },
        "restart_server_per_config": bool(args.restart_server_per_config),
        "timing_interpretation": (
            "Comparable latency requires --restart-server-per-config. Without it, "
            "cache_n and repeated-image cache state make wall-clock timing diagnostic only."
        ),
        "configs": [asdict(item) for item in configs],
        "summary": summary,
        "results": [asdict(item) for item in results],
    }
    results_path = output_dir / "results.json"
    results_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n[pipeline] Riepilogo")
    for name, values in summary.items():
        cer = float(values["mean_cer"])
        elapsed = float(values["mean_elapsed_s"])
        cache_free = float(values["mean_cache_free_elapsed_s"])
        print(
            f"  {name}: mean CER={'n/a' if cer < 0 else f'{cer:.4f}'}; "
            f"mean={elapsed:.2f}s; cache-free="
            f"{'n/a' if cache_free < 0 else f'{cache_free:.2f}s'}; "
            f"JPEG={float(values['mean_encoded_bytes']) / 1024:.1f}KiB; "
            f"cache_n={values['cache_n_total']}; errors={values['errors']}"
        )
    if not args.restart_server_per_config:
        print(
            "[pipeline] Timing condiviso: diagnostico. Per decisioni di latenza usa "
            "--restart-server-per-config."
        )
    print(f"[pipeline] Risultati: {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
