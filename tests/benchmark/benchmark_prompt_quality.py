"""Manual GLM-OCR prompt benchmark for the target llama.cpp/SYCL runtime.

CI exercises the deterministic helpers only. Actual inference is intentionally run
manually on hardware with a working SYCL llama-server.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llama_backend import LlamaServerBackend  # noqa: E402
from core.llama_ocr_api import (  # noqa: E402
    PROMPT_FORMULA_RECOGNITION,
    PROMPT_LEGACY_OCR,
    PROMPT_TABLE_RECOGNITION,
    PROMPT_TEXT_RECOGNITION,
    ocr_single_image,
)


@dataclass(frozen=True)
class Sample:
    name: str
    task: str
    image_path: Path
    expected_text: str
    score_mode: str = "cer"


@dataclass
class RunResult:
    sample: str
    task: str
    prompt: str
    elapsed_s: float
    round_index: int = 0
    sequence_index: int = 0
    output: str = ""
    cer: float | None = None
    error: str | None = None


def _font(size: int, *, mono: bool = False) -> ImageFont.ImageFont:
    names = ["DejaVuSansMono.ttf", "DejaVuSans.ttf"] if mono else [
        "DejaVuSans.ttf",
        "DejaVuSansMono.ttf",
    ]
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: Iterable[str],
    *,
    xy: tuple[int, int],
    font: ImageFont.ImageFont,
    fill: str | tuple[int, int, int] = "black",
    line_gap: int = 12,
) -> None:
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line or "Ag", font=font)
        y += max(1, bbox[3] - bbox[1]) + line_gap


def _make_clean_text(path: Path) -> Sample:
    expected = (
        "GLM OCR benchmark\n"
        "Questa pagina contiene testo italiano con accenti: qualità, perché, più.\n"
        "English line with punctuation: commas, periods, and numbers 12345."
    )
    image = Image.new("RGB", (1500, 700), "white")
    draw = ImageDraw.Draw(image)
    _draw_lines(
        draw,
        expected.splitlines(),
        xy=(80, 90),
        font=_font(38),
        line_gap=28,
    )
    image.save(path)
    return Sample("clean_text", "text", path, expected)


def _make_small_text(path: Path) -> Sample:
    expected = (
        "Testo piccolo per verificare la leggibilità.\n"
        "Riga due: abcdefghijklmnopqrstuvwxyz 0123456789.\n"
        "Riga tre: OCR locale, rapido e ripetibile."
    )
    image = Image.new("RGB", (1500, 700), "white")
    draw = ImageDraw.Draw(image)
    _draw_lines(
        draw,
        expected.splitlines(),
        xy=(90, 110),
        font=_font(22),
        line_gap=20,
    )
    image.save(path)
    return Sample("small_text", "text", path, expected)


def _make_noisy_text(path: Path) -> Sample:
    expected = (
        "Scansione simulata con rumore controllato.\n"
        "Il contenuto corretto deve restare leggibile.\n"
        "Numero documento: 2026-0815-A7."
    )
    image = Image.new("RGB", (1500, 700), (238, 238, 234))
    draw = ImageDraw.Draw(image)
    _draw_lines(
        draw,
        expected.splitlines(),
        xy=(85, 105),
        font=_font(34),
        fill=(35, 35, 35),
        line_gap=26,
    )
    rng = random.Random(20260821)
    for _ in range(9000):
        x = rng.randrange(image.width)
        y = rng.randrange(image.height)
        shade = rng.randrange(180, 235)
        draw.point((x, y), fill=(shade, shade, shade))
    image.save(path, quality=92)
    return Sample("noisy_scan", "text", path, expected)


def _make_table(path: Path) -> Sample:
    headers = ["Prodotto", "Q1", "Q2", "Totale"]
    rows = [
        ["Alpha", "12", "15", "27"],
        ["Beta", "8", "11", "19"],
        ["Gamma", "20", "18", "38"],
    ]
    image = Image.new("RGB", (1300, 720), "white")
    draw = ImageDraw.Draw(image)
    font = _font(30)
    x0, y0 = 100, 100
    col_w = [360, 220, 220, 260]
    row_h = 105
    xs = [x0]
    for width in col_w:
        xs.append(xs[-1] + width)
    for row_index in range(len(rows) + 2):
        y = y0 + row_index * row_h
        draw.line((x0, y, xs[-1], y), fill="black", width=3)
    for x in xs:
        draw.line((x, y0, x, y0 + (len(rows) + 1) * row_h), fill="black", width=3)
    for col, value in enumerate(headers):
        draw.text((xs[col] + 18, y0 + 28), value, font=font, fill="black")
    for row_idx, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            draw.text(
                (xs[col] + 18, y0 + row_idx * row_h + 28),
                value,
                font=font,
                fill="black",
            )
    image.save(path)
    expected = (
        "Prodotto | Q1 | Q2 | Totale\n"
        "Alpha | 12 | 15 | 27\n"
        "Beta | 8 | 11 | 19\n"
        "Gamma | 20 | 18 | 38"
    )
    return Sample("table", "table", path, expected, score_mode="manual")


def _make_formula(path: Path) -> Sample:
    expected = (
        "E = mc^2\n"
        "(a+b)^2 = a^2 + 2ab + b^2\n"
        "x = (-b +/- sqrt(b^2 - 4ac)) / (2a)"
    )
    image = Image.new("RGB", (1500, 700), "white")
    draw = ImageDraw.Draw(image)
    _draw_lines(
        draw,
        expected.splitlines(),
        xy=(100, 110),
        font=_font(38, mono=True),
        line_gap=34,
    )
    image.save(path)
    return Sample("formula", "formula", path, expected, score_mode="manual")


def _make_mixed_layout(path: Path) -> Sample:
    expected = (
        "Rapporto sintetico 2026\n"
        "Il sistema deve riconoscere testo e numeri nello stesso documento.\n"
        "Voce A 14\n"
        "Voce B 27"
    )
    image = Image.new("RGB", (1500, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 65), "Rapporto sintetico 2026", font=_font(46), fill="black")
    draw.text(
        (80, 155),
        "Il sistema deve riconoscere testo e numeri nello stesso documento.",
        font=_font(27),
        fill="black",
    )
    x0, y0, w, h = 160, 330, 900, 150
    draw.rectangle((x0, y0, x0 + w, y0 + h * 2), outline="black", width=3)
    draw.line((x0 + 620, y0, x0 + 620, y0 + h * 2), fill="black", width=3)
    draw.line((x0, y0 + h, x0 + w, y0 + h), fill="black", width=3)
    draw.text((x0 + 25, y0 + 48), "Voce A", font=_font(32), fill="black")
    draw.text((x0 + 680, y0 + 48), "14", font=_font(32), fill="black")
    draw.text((x0 + 25, y0 + h + 48), "Voce B", font=_font(32), fill="black")
    draw.text((x0 + 680, y0 + h + 48), "27", font=_font(32), fill="black")
    image.save(path)
    return Sample("mixed_layout", "text", path, expected)


def _write_corpus_manifest(directory: Path, samples: Sequence[Sample]) -> None:
    (directory / "corpus.json").write_text(
        json.dumps(
            [
                {
                    **asdict(sample),
                    "image_path": sample.image_path.name,
                }
                for sample in samples
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def build_corpus(directory: Path) -> list[Sample]:
    """Build the deterministic synthetic benchmark corpus."""
    directory.mkdir(parents=True, exist_ok=True)
    samples = [
        _make_clean_text(directory / "clean_text.png"),
        _make_small_text(directory / "small_text.png"),
        _make_noisy_text(directory / "noisy_scan.jpg"),
        _make_table(directory / "table.png"),
        _make_formula(directory / "formula.png"),
        _make_mixed_layout(directory / "mixed_layout.png"),
    ]
    _write_corpus_manifest(directory, samples)
    return samples


def load_manifest_corpus(directory: Path) -> list[Sample]:
    """Load a labelled real-world corpus from ``manifest.json``.

    Each entry requires ``image`` and ``expected_text``. ``name`` defaults to the
    image stem, ``task`` defaults to ``text`` and ``score_mode`` defaults to
    ``cer``. Paths must stay inside the supplied corpus directory.
    """
    directory = directory.expanduser().resolve()
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Manifest corpus mancante: {manifest_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Manifest corpus non leggibile: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError("Il manifest corpus deve essere una lista non vuota")

    samples: list[Sample] = []
    seen_names: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Voce manifest #{index} non valida")
        image_value = str(item.get("image", "")).strip()
        expected = str(item.get("expected_text", ""))
        if not image_value:
            raise ValueError(f"Voce manifest #{index}: campo 'image' mancante")
        image_path = (directory / image_value).resolve()
        try:
            image_path.relative_to(directory)
        except ValueError as exc:
            raise ValueError(
                f"Voce manifest #{index}: immagine fuori dalla directory corpus"
            ) from exc
        if not image_path.is_file():
            raise ValueError(f"Immagine corpus non trovata: {image_path}")
        name = str(item.get("name") or image_path.stem).strip()
        if not name or name in seen_names:
            raise ValueError(f"Nome sample duplicato/non valido: {name!r}")
        seen_names.add(name)
        task = str(item.get("task") or "text").strip().lower()
        if task not in {"text", "table", "formula"}:
            raise ValueError(f"Task non supportato per {name}: {task}")
        score_mode = str(item.get("score_mode") or "cer").strip().lower()
        if score_mode not in {"cer", "manual"}:
            raise ValueError(f"score_mode non supportato per {name}: {score_mode}")
        samples.append(
            Sample(
                name=name,
                task=task,
                image_path=image_path,
                expected_text=expected,
                score_mode=score_mode,
            )
        )
    return samples


def _normalize_for_cer(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text)).replace("\r", "\n")
    return " ".join(normalized.split())


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (char_a != char_b),
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(expected: str, actual: str) -> float:
    expected_norm = _normalize_for_cer(expected)
    actual_norm = _normalize_for_cer(actual)
    if not expected_norm:
        return 0.0 if not actual_norm else 1.0
    return _levenshtein(expected_norm, actual_norm) / len(expected_norm)


def build_counterbalanced_schedule(
    samples: Sequence[Sample],
    prompts: Sequence[str],
    rounds: int,
) -> list[tuple[int, Sample, str]]:
    """Return a deterministic order that alternates which prompt runs first.

    Reversing sample order on alternating rounds also reduces simple temporal
    drift from always affecting the same sample in the same position.
    """
    if rounds < 1:
        raise ValueError("rounds deve essere >= 1")
    if len(prompts) != 2:
        raise ValueError("Il confronto controbilanciato richiede esattamente 2 prompt")
    schedule: list[tuple[int, Sample, str]] = []
    for round_index in range(1, rounds + 1):
        ordered_samples = list(samples)
        if round_index % 2 == 0:
            ordered_samples.reverse()
        for sample_index, sample in enumerate(ordered_samples):
            prompt_order = list(prompts)
            if (round_index + sample_index) % 2 == 0:
                prompt_order.reverse()
            for prompt in prompt_order:
                schedule.append((round_index, sample, prompt))
    return schedule


def _run_one(
    sample: Sample,
    *,
    server_url: str,
    prompt: str,
    preprocessing_enabled: bool,
    round_index: int = 0,
    sequence_index: int = 0,
) -> RunResult:
    started = time.perf_counter()
    try:
        text, _confidence = ocr_single_image(
            sample.image_path,
            server_url,
            preprocessing_enabled=preprocessing_enabled,
            prompt=prompt,
        )
        elapsed = time.perf_counter() - started
        cer = (
            character_error_rate(sample.expected_text, text)
            if sample.score_mode == "cer"
            else None
        )
        return RunResult(
            sample=sample.name,
            task=sample.task,
            prompt=prompt,
            elapsed_s=elapsed,
            round_index=round_index,
            sequence_index=sequence_index,
            output=text,
            cer=cer,
        )
    except Exception as exc:
        return RunResult(
            sample=sample.name,
            task=sample.task,
            prompt=prompt,
            elapsed_s=time.perf_counter() - started,
            round_index=round_index,
            sequence_index=sequence_index,
            error=str(exc),
        )


def _summary(results: Sequence[RunResult]) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for prompt in sorted({item.prompt for item in results}):
        group = [item for item in results if item.prompt == prompt]
        scored = [
            item.cer
            for item in group
            if item.cer is not None and item.error is None
        ]
        elapsed = [item.elapsed_s for item in group if item.error is None]
        summary[prompt] = {
            "runs": len(group),
            "errors": sum(1 for item in group if item.error),
            "mean_cer": statistics.mean(scored) if scored else -1.0,
            "median_cer": statistics.median(scored) if scored else -1.0,
            "mean_elapsed_s": statistics.mean(elapsed) if elapsed else -1.0,
            "median_elapsed_s": statistics.median(elapsed) if elapsed else -1.0,
        }
    return summary


def paired_prompt_comparison(
    results: Sequence[RunResult],
    baseline_prompt: str = PROMPT_LEGACY_OCR,
    candidate_prompt: str = PROMPT_TEXT_RECOGNITION,
) -> dict[str, float | int]:
    """Compare timing/quality only within identical sample+round pairs."""
    by_key: dict[tuple[int, str], dict[str, RunResult]] = {}
    for result in results:
        if result.prompt not in {baseline_prompt, candidate_prompt}:
            continue
        by_key.setdefault((result.round_index, result.sample), {})[
            result.prompt
        ] = result

    time_deltas: list[float] = []
    cer_deltas: list[float] = []
    candidate_faster = 0
    baseline_faster = 0
    timing_ties = 0
    for pair in by_key.values():
        baseline = pair.get(baseline_prompt)
        candidate = pair.get(candidate_prompt)
        if baseline is None or candidate is None or baseline.error or candidate.error:
            continue
        delta = candidate.elapsed_s - baseline.elapsed_s
        time_deltas.append(delta)
        if abs(delta) < 1e-9:
            timing_ties += 1
        elif delta < 0:
            candidate_faster += 1
        else:
            baseline_faster += 1
        if baseline.cer is not None and candidate.cer is not None:
            cer_deltas.append(candidate.cer - baseline.cer)

    return {
        "paired_runs": len(time_deltas),
        "candidate_faster_pairs": candidate_faster,
        "baseline_faster_pairs": baseline_faster,
        "timing_ties": timing_ties,
        "mean_candidate_minus_baseline_s": (
            statistics.mean(time_deltas) if time_deltas else 0.0
        ),
        "median_candidate_minus_baseline_s": (
            statistics.median(time_deltas) if time_deltas else 0.0
        ),
        "mean_candidate_minus_baseline_cer": (
            statistics.mean(cer_deltas) if cer_deltas else 0.0
        ),
    }


def _run_warmup(
    sample: Sample,
    *,
    server_url: str,
    prompts: Sequence[str],
    preprocessing_enabled: bool,
    warmup_rounds: int,
) -> None:
    for warmup_index in range(warmup_rounds):
        order = list(prompts)
        if warmup_index % 2:
            order.reverse()
        for prompt in order:
            print(f"  warm-up {warmup_index + 1}/{warmup_rounds}: {prompt}")
            result = _run_one(
                sample,
                server_url=server_url,
                prompt=prompt,
                preprocessing_enabled=preprocessing_enabled,
            )
            if result.error:
                raise RuntimeError(f"Warm-up fallito con {prompt}: {result.error}")


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
        help="Benchmark output directory. Default: benchmark-results/glm-ocr-prompts-<timestamp>.",
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
        default=3,
        help="Repeated counterbalanced text-comparison rounds (default: 3).",
    )
    parser.add_argument(
        "--warmup-rounds",
        type=int,
        default=1,
        help="Unrecorded warm-up rounds for both text prompts (default: 1).",
    )
    parser.add_argument(
        "--no-preprocessing",
        action="store_true",
        help="Disable the same image preprocessing normally enabled by the app.",
    )
    parser.add_argument(
        "--specialized",
        action="store_true",
        help="Also record table/formula outputs using their official task prompts.",
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
            print(
                f"[benchmark] Warm-up non registrato: {args.warmup_rounds} round"
            )
            _run_warmup(
                text_samples[0],
                server_url=server_url,
                prompts=prompts,
                preprocessing_enabled=preprocessing_enabled,
                warmup_rounds=args.warmup_rounds,
            )

        schedule = build_counterbalanced_schedule(
            text_samples,
            prompts,
            args.rounds,
        )
        print(
            f"[benchmark] Confronto controbilanciato: {args.rounds} round, "
            f"{len(schedule)} run registrati"
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
                print(
                    f"    CER={result.cer:.4f} tempo={result.elapsed_s:.2f}s"
                )

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
                        f"  {sample.name}: tempo={result.elapsed_s:.2f}s "
                        "(review manuale)"
                    )
    finally:
        if managed_backend is not None:
            print("[benchmark] Arresto llama-server posseduto dal benchmark...")
            managed_backend.shutdown()

    summary = _summary(results)
    paired = paired_prompt_comparison(results)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "server_url": server_url,
        "corpus_source": corpus_source,
        "preprocessing_enabled": preprocessing_enabled,
        "rounds": args.rounds,
        "warmup_rounds": args.warmup_rounds,
        "schedule": "counterbalanced-by-sample-and-round",
        "production_default_prompt": PROMPT_LEGACY_OCR,
        "candidate_text_prompt": PROMPT_TEXT_RECOGNITION,
        "official_specialized_prompts": {
            "table": PROMPT_TABLE_RECOGNITION,
            "formula": PROMPT_FORMULA_RECOGNITION,
        },
        "summary": summary,
        "paired_comparison": paired,
        "results": [asdict(item) for item in results],
    }
    results_path = output_dir / "results.json"
    results_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n[benchmark] Riepilogo")
    for prompt, values in summary.items():
        mean_cer = float(values["mean_cer"])
        mean_time = float(values["mean_elapsed_s"])
        median_time = float(values["median_elapsed_s"])
        cer_text = "n/a" if mean_cer < 0 else f"{mean_cer:.4f}"
        time_text = "n/a" if mean_time < 0 else f"{mean_time:.2f}s"
        median_text = "n/a" if median_time < 0 else f"{median_time:.2f}s"
        print(
            f"  {prompt}: mean CER={cer_text}; mean={time_text}; "
            f"median={median_text}; errors={values['errors']}"
        )

    print("[benchmark] Confronto appaiato Text Recognition - OCR")
    print(
        "  pairs={paired_runs}; candidate_faster={candidate_faster_pairs}; "
        "ocr_faster={baseline_faster_pairs}; mean_delta={mean:.2f}s; "
        "median_delta={median:.2f}s; CER_delta={cer:.5f}".format(
            mean=float(paired["mean_candidate_minus_baseline_s"]),
            median=float(paired["median_candidate_minus_baseline_s"]),
            cer=float(paired["mean_candidate_minus_baseline_cer"]),
            **paired,
        )
    )
    print(f"[benchmark] Risultati: {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
