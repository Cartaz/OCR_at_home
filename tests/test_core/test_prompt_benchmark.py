"""Regression coverage for the manual GLM-OCR prompt benchmark helpers."""

from tests.benchmark.benchmark_prompt_quality import build_corpus, character_error_rate


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
