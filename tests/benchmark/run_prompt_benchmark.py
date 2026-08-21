"""Canonical Phase 2 GLM-OCR prompt-quality runner.

Repeated identical-image requests can be heavily accelerated by llama-server cache
state. This runner therefore treats wall-clock time as diagnostic only and uses
counterbalancing solely to avoid systematic quality-order bias. Prompt selection
is based on labelled-output quality, not cached request timing.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llama_backend import LlamaServerBackend  # noqa: E402
from core.llama_ocr_api import (  # noqa: E402
    PROMPT_FORMULA_RECOGNITION,
    PROMPT_LEGACY_OCR,
    PROMPT_TABLE_RECOGNITION,
    PROMPT_TEXT_RECOGNITION,
)
from tests.benchmark.benchmark_prompt_quality import (  # noqa: E402
    RunResult,
    Sample,
    _run_one,
    _run_warmup,
    build_corpus,
    load_manifest_corpus,
)


def build_per_sample_counterbalanced_schedule(
    samples: Sequence[Sample],
    prompts: Sequence[str],
    rounds: int,
) -> list[tuple[int, Sample, str]]:
    """Alternate first prompt for every individual sample on every round."""
    if rounds < 1:
        raise ValueError("rounds deve essere >= 1")
    if len(prompts) != 2:
        raise ValueError("Il confronto richiede esattamente 2 prompt")

    original_index = {sample.name: index for index, sample in enumerate(samples)}
    if len(original_index) != len(samples):
        raise ValueError("I nomi dei sample devono essere univoci")

    schedule: list[tuple[int, Sample, str]] = []
    for round_index in range(1, rounds + 1):
        ordered_samples = list(samples)
        if round_index % 2 == 0:
            ordered_samples.reverse()

        for sample in ordered_samples:
            prompt_order = list(prompts)
            # The original, stable sample index is used deliberately. Reversing
            # the traversal order must not cancel the per-sample alternation.
            if (round_index + original_index[sample.name]) % 2 == 0:
                prompt_order.reverse()
            for prompt in prompt_order:
                schedule.append((round_index, sample, prompt))
    return schedule


def quality_summary(results: Sequence[RunResult]) -> dict[str, dict[str, float | int]]:
    """Summarize accuracy only; elapsed time remains raw diagnostic metadata."""
    summary: dict[str, dict[str, float | int]] = {}
    for prompt in sorted({item.prompt for item in results}):
        group = [item for item in results if item.prompt == prompt]
        scored = [
            item.cer
            for item in group
            if item.cer is not None and item.error is None
        ]
        summary[prompt] = {
            "runs": len(group),
            "errors": sum(1 for item in group if item.error),
            "scored_runs": len(scored),
            "mean_cer": statistics.mean(scored) if scored else -1.0,
            "median_cer": statistics.median(scored) if scored else -1.0,
            "perfect_cer_runs": sum(1 for value in scored if value == 0.0),
        }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server-url",
        default="",
        help="Use an already-running compatible llama-server instead of owning one.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Default: benchmark-results/glm-ocr-prompts-<timestamp>.",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help="Use a labelled real-world corpus directory containing manifest.json.",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=2,
        help="Quality-comparison rounds. Two are sufficient for first-order counterbalancing.",
    )
    parser.add_argument(
        "--warmup-rounds",
        type=int,
        default=1,
        help="Unrecorded warm-up rounds for both text prompts.",
    )
    parser.add_argument(
        "--no-preprocessing",
        action="store_true",
        help="Disable the image preprocessing normally enabled by the app.",
    )
    parser.add_argument(
        "--specialized",
        action="store_true",
        help="Also record table/formula outputs with official task prompts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.rounds < 1:
        raise SystemExit("--rounds deve essere >= 1")
    if args.warmup_rounds < 0:
        raise SystemExit("--warmup-rounds deve essere >= 0")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or Path("benchmark-results") / (
        f"glm-ocr-prompts-{timestamp}"
    )
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.corpus_dir is None:
        corpus = build_corpus(output_dir / "corpus")
        corpus_source = "synthetic"
    else:
        corpus = load_manifest_corpus(args.corpus_dir)
        corpus_source = str(args.corpus_dir.expanduser().resolve())

    text_samples = [sample for sample in corpus if sample.task == "text"]
    if not text_samples:
        raise SystemExit("Il corpus non contiene sample task=text")

    managed_backend: LlamaServerBackend | None = None
    server_url = str(args.server_url).strip()
    if not server_url:
        managed_backend = LlamaServerBackend()
        print("[benchmark] Avvio llama-server SYCL posseduto dal benchmark...")
        managed_backend.initialize()
        server_url = managed_backend.server_url

    preprocessing_enabled = not args.no_preprocessing
    prompts = [PROMPT_LEGACY_OCR, PROMPT_TEXT_RECOGNITION]
    results: list[RunResult] = []

    try:
        if args.warmup_rounds:
            print(f"[benchmark] Warm-up non registrato: {args.warmup_rounds} round")
            _run_warmup(
                text_samples[0],
                server_url=server_url,
                prompts=prompts,
                preprocessing_enabled=preprocessing_enabled,
                warmup_rounds=args.warmup_rounds,
            )

        schedule = build_per_sample_counterbalanced_schedule(
            text_samples,
            prompts,
            args.rounds,
        )
        print(
            f"[benchmark] Confronto qualità: {args.rounds} round, "
            f"{len(schedule)} run registrati"
        )
        print(
            "[benchmark] Nota: i tempi sono diagnostici; richieste ripetute della "
            "stessa immagine possono beneficiare della cache llama-server."
        )

        for sequence_index, (round_index, sample, prompt) in enumerate(
            schedule,
            start=1,
        ):
            print(
                f"  [{sequence_index}/{len(schedule)}] round={round_index} "
                f"{sample.name} · {prompt}"
            )
            result = _run_one(
                sample,
                server_url=server_url,
                prompt=prompt,
                preprocessing_enabled=preprocessing_enabled,
                round_index=round_index,
                sequence_index=sequence_index,
            )
            results.append(result)
            if result.error:
                print(f"    ERRORE {result.error}")
            else:
                cer_text = "n/a" if result.cer is None else f"{result.cer:.4f}"
                print(f"    CER={cer_text} tempo(raw)={result.elapsed_s:.2f}s")

        if args.specialized:
            specialized = {
                "table": PROMPT_TABLE_RECOGNITION,
                "formula": PROMPT_FORMULA_RECOGNITION,
            }
            for sample in corpus:
                prompt = specialized.get(sample.task)
                if prompt is None:
                    continue
                print(f"[benchmark] Probe {sample.task}: {prompt}")
                result = _run_one(
                    sample,
                    server_url=server_url,
                    prompt=prompt,
                    preprocessing_enabled=preprocessing_enabled,
                    sequence_index=len(results) + 1,
                )
                results.append(result)
                if result.error:
                    print(f"  {sample.name}: ERRORE {result.error}")
                else:
                    print(
                        f"  {sample.name}: tempo(raw)={result.elapsed_s:.2f}s "
                        "(review manuale)"
                    )
    finally:
        if managed_backend is not None:
            print("[benchmark] Arresto llama-server posseduto dal benchmark...")
            managed_backend.shutdown()

    summary = quality_summary(results)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "server_url": server_url,
        "corpus_source": corpus_source,
        "preprocessing_enabled": preprocessing_enabled,
        "rounds": args.rounds,
        "warmup_rounds": args.warmup_rounds,
        "schedule": "per-sample-counterbalanced",
        "timing_interpretation": (
            "diagnostic-only: repeated identical-image requests may be cache-accelerated; "
            "do not select prompts from these wall-clock values"
        ),
        "production_default_prompt": PROMPT_LEGACY_OCR,
        "candidate_text_prompt": PROMPT_TEXT_RECOGNITION,
        "official_specialized_prompts": {
            "table": PROMPT_TABLE_RECOGNITION,
            "formula": PROMPT_FORMULA_RECOGNITION,
        },
        "quality_summary": summary,
        "results": [asdict(item) for item in results],
    }
    results_path = output_dir / "results.json"
    results_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n[benchmark] Riepilogo qualità")
    for prompt, values in summary.items():
        mean_cer = float(values["mean_cer"])
        cer_text = "n/a" if mean_cer < 0 else f"{mean_cer:.4f}"
        print(
            f"  {prompt}: runs={values['runs']}; scored={values['scored_runs']}; "
            f"mean CER={cer_text}; perfect={values['perfect_cer_runs']}; "
            f"errors={values['errors']}"
        )
    print("[benchmark] Timing: diagnostico soltanto (cache llama-server rilevata).")
    print(f"[benchmark] Risultati: {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
