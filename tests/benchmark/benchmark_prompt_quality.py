"""Manual GLM-OCR prompt benchmark for the target llama.cpp/SYCL runtime.

This file is intentionally not named ``test_*.py``: CI verifies its syntax, while
actual inference is run manually on hardware with a working SYCL llama-server.
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
from typing import Iterable

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
    fill: str = "black",
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
    expected = "Prodotto | Q1 | Q2 | Totale\nAlpha | 12 | 15 | 27\nBeta | 8 | 11 | 19\nGamma | 20 | 18 | 38"
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


def build_corpus(directory: Path) -> list[Sample]:
    directory.mkdir(parents=True, exist_ok=True)
    samples = [
        _make_clean_text(directory / "clean_text.png"),
        _make_small_text(directory / "small_text.png"),
        _make_noisy_text(directory / "noisy_scan.jpg"),
        _make_table(directory / "table.png"),
        _make_formula(directory / "formula.png"),
        _make_mixed_layout(directory / "mixed_layout.png"),
    ]
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


def _run_one(
    sample: Sample,
    *,
    server_url: str,
    prompt: str,
    preprocessing_enabled: bool,
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
            output=text,
            cer=cer,
        )
    except Exception as exc:
        return RunResult(
            sample=sample.name,
            task=sample.task,
            prompt=prompt,
            elapsed_s=time.perf_counter() - started,
            error=str(exc),
        )


def _summary(results: list[RunResult]) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for prompt in sorted({item.prompt for item in results}):
        group = [item for item in results if item.prompt == prompt]
        scored = [item.cer for item in group if item.cer is not None and item.error is None]
        elapsed = [item.elapsed_s for item in group if item.error is None]
        summary[prompt] = {
            "runs": len(group),
            "errors": sum(1 for item in group if item.error),
            "mean_cer": statistics.mean(scored) if scored else -1.0,
            "mean_elapsed_s": statistics.mean(elapsed) if elapsed else -1.0,
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
        help="Benchmark output directory. Default: benchmark-results/glm-ocr-prompts-<timestamp>.",
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
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or Path("benchmark-results") / f"glm-ocr-prompts-{timestamp}"
    output_dir = output_dir.expanduser().resolve()
    corpus = build_corpus(output_dir / "corpus")

    managed_backend: LlamaServerBackend | None = None
    server_url = str(args.server_url).strip()
    if not server_url:
        managed_backend = LlamaServerBackend()
        print("[benchmark] Avvio llama-server SYCL posseduto dal benchmark...")
        managed_backend.initialize()
        server_url = managed_backend.server_url

    preprocessing_enabled = not args.no_preprocessing
    results: list[RunResult] = []
    try:
        text_samples = [sample for sample in corpus if sample.task == "text"]
        prompts = [PROMPT_LEGACY_OCR, PROMPT_TEXT_RECOGNITION]
        for prompt in prompts:
            print(f"[benchmark] Prompt: {prompt}")
            for sample in text_samples:
                result = _run_one(
                    sample,
                    server_url=server_url,
                    prompt=prompt,
                    preprocessing_enabled=preprocessing_enabled,
                )
                results.append(result)
                if result.error:
                    print(f"  {sample.name}: ERRORE {result.error}")
                else:
                    print(
                        f"  {sample.name}: CER={result.cer:.4f} "
                        f"tempo={result.elapsed_s:.2f}s"
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
                )
                results.append(result)
                if result.error:
                    print(f"  {sample.name}: ERRORE {result.error}")
                else:
                    print(f"  {sample.name}: tempo={result.elapsed_s:.2f}s (review manuale)")
    finally:
        if managed_backend is not None:
            print("[benchmark] Arresto llama-server posseduto dal benchmark...")
            managed_backend.shutdown()

    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "server_url": server_url,
        "preprocessing_enabled": preprocessing_enabled,
        "production_default_prompt": PROMPT_LEGACY_OCR,
        "candidate_text_prompt": PROMPT_TEXT_RECOGNITION,
        "official_specialized_prompts": {
            "table": PROMPT_TABLE_RECOGNITION,
            "formula": PROMPT_FORMULA_RECOGNITION,
        },
        "summary": _summary(results),
        "results": [asdict(item) for item in results],
    }
    results_path = output_dir / "results.json"
    results_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n[benchmark] Riepilogo")
    for prompt, values in payload["summary"].items():
        mean_cer = float(values["mean_cer"])
        mean_time = float(values["mean_elapsed_s"])
        cer_text = "n/a" if mean_cer < 0 else f"{mean_cer:.4f}"
        time_text = "n/a" if mean_time < 0 else f"{mean_time:.2f}s"
        print(
            f"  {prompt}: mean CER={cer_text}; mean time={time_text}; "
            f"errors={values['errors']}"
        )
    print(f"[benchmark] Risultati: {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
