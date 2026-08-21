"""Regression coverage for the manual GLM-OCR prompt benchmark helpers."""

import json

from PIL import Image

from core.llama_ocr_api import PROMPT_LEGACY_OCR, PROMPT_TEXT_RECOGNITION
from tests.benchmark.benchmark_prompt_quality import (
    RunResult,
    Sample,
    build_counterbalanced_schedule,
    build_corpus,
    character_error_rate,
    load_manifest_corpus,
    paired_prompt_comparison,
)


def test_benchmark_corpus_covers_required_document_classes(tmp_path) -> None:
    samples = build_corpus(tmp_path / "corpus")

    names = {sample.name for sample in samples}
    tasks = {sample.task for sample in samples}

    assert names == {
        "clean_text",
        "small_text",
        "noisy_scan",
        "table",
        "formula",
        "mixed_layout",
    }
    assert tasks == {"text", "table", "formula"}
    assert all(sample.image_path.is_file() for sample in samples)
    assert (tmp_path / "corpus" / "corpus.json").is_file()


def test_character_error_rate_is_zero_for_equivalent_whitespace() -> None:
    expected = "Riga uno\nRiga due"
    actual = "Riga uno   Riga due"
    assert character_error_rate(expected, actual) == 0.0


def test_character_error_rate_detects_text_difference() -> None:
    assert character_error_rate("abcdef", "abcxef") > 0.0


def test_counterbalanced_schedule_runs_each_prompt_once_per_sample_per_round(
    tmp_path,
) -> None:
    samples = [
        Sample("a", "text", tmp_path / "a.png", "A"),
        Sample("b", "text", tmp_path / "b.png", "B"),
    ]
    prompts = [PROMPT_LEGACY_OCR, PROMPT_TEXT_RECOGNITION]

    schedule = build_counterbalanced_schedule(samples, prompts, rounds=3)

    assert len(schedule) == 12
    for round_index in range(1, 4):
        for sample in samples:
            seen = [
                prompt
                for round_value, scheduled_sample, prompt in schedule
                if round_value == round_index and scheduled_sample.name == sample.name
            ]
            assert sorted(seen) == sorted(prompts)

    first_prompt_counts = {prompt: 0 for prompt in prompts}
    for index in range(0, len(schedule), 2):
        first_prompt_counts[schedule[index][2]] += 1
    assert first_prompt_counts[PROMPT_LEGACY_OCR] == first_prompt_counts[
        PROMPT_TEXT_RECOGNITION
    ]


def test_load_manifest_corpus_accepts_labelled_real_images(tmp_path) -> None:
    corpus_dir = tmp_path / "real-corpus"
    corpus_dir.mkdir()
    image_path = corpus_dir / "page.png"
    Image.new("RGB", (32, 32), "white").save(image_path)
    (corpus_dir / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "name": "page-one",
                    "image": "page.png",
                    "expected_text": "Testo atteso",
                    "task": "text",
                }
            ]
        ),
        encoding="utf-8",
    )

    samples = load_manifest_corpus(corpus_dir)

    assert len(samples) == 1
    assert samples[0].name == "page-one"
    assert samples[0].image_path == image_path.resolve()
    assert samples[0].expected_text == "Testo atteso"
    assert samples[0].score_mode == "cer"


def test_paired_prompt_comparison_uses_same_round_and_sample_only() -> None:
    results = [
        RunResult(
            "a",
            "text",
            PROMPT_LEGACY_OCR,
            10.0,
            round_index=1,
            cer=0.10,
        ),
        RunResult(
            "a",
            "text",
            PROMPT_TEXT_RECOGNITION,
            9.0,
            round_index=1,
            cer=0.05,
        ),
        RunResult(
            "a",
            "text",
            PROMPT_LEGACY_OCR,
            8.0,
            round_index=2,
            cer=0.00,
        ),
        RunResult(
            "a",
            "text",
            PROMPT_TEXT_RECOGNITION,
            9.0,
            round_index=2,
            cer=0.00,
        ),
    ]

    comparison = paired_prompt_comparison(results)

    assert comparison["paired_runs"] == 2
    assert comparison["candidate_faster_pairs"] == 1
    assert comparison["baseline_faster_pairs"] == 1
    assert comparison["mean_candidate_minus_baseline_s"] == 0.0
    assert comparison["mean_candidate_minus_baseline_cer"] == -0.025
