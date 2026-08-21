"""Tests for canonical benchmark ground-truth parsing."""

from __future__ import annotations

import pytest

from tests.benchmark.ground_truth_parser import parse_ground_truth_markdown


def test_plain_markdown_ground_truth_accepts_internal_headings() -> None:
    markdown = """# FACILE

21/08/26 CHANGELOG.md 1
# Changelog
## [1.0.1] — Pulizia e bug fix
- Riga esatta del documento.

# MEDIO

Testo della scansione densa.

# DIFFICILE

## MAIUSCOLO

PRIMA PARTE DEL TESTO CONTINUO.

## SCRIPT

Seconda parte dello stesso testo.

## CORSIVO

Terza parte dello stesso testo.
"""
    truth = parse_ground_truth_markdown(markdown)

    assert "# Changelog" in truth.facile
    assert "## [1.0.1]" in truth.facile
    assert truth.medio == "Testo della scansione densa."
    assert truth.difficile_segments == {
        "maiuscolo": "PRIMA PARTE DEL TESTO CONTINUO.",
        "script": "Seconda parte dello stesso testo.",
        "corsivo": "Terza parte dello stesso testo.",
    }


def test_fenced_format_remains_supported() -> None:
    markdown = """# FACILE
```text
Uno.
```
# MEDIO
```text
Due.
```
# DIFFICILE
## MAIUSCOLO
```text
Tre.
```
## SCRIPT
```text
Quattro.
```
## CORSIVO
```text
Cinque.
```
"""
    truth = parse_ground_truth_markdown(markdown)
    assert truth.facile == "Uno."
    assert truth.medio == "Due."
    assert truth.difficile == "Tre.\nQuattro.\nCinque."


def test_structure_is_still_strict() -> None:
    with pytest.raises(ValueError, match="FACILE, # MEDIO, # DIFFICILE"):
        parse_ground_truth_markdown("# FACILE\nUno\n# DIFFICILE\nDue\n")
