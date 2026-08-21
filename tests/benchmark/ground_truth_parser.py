"""Ground-truth parser for the canonical real-world benchmark.

The section structure is strict, while the transcription body can be either
plain Markdown text or wrapped in a ```text ... ``` fence.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from tests.benchmark.realworld_suite_v2 import GroundTruth, HANDWRITING_SEGMENTS


def _section_body(markdown: str, title: str, next_titles: Sequence[str]) -> str:
    start_match = re.search(rf"(?im)^#\s+{re.escape(title)}\s*$", markdown)
    if start_match is None:
        raise ValueError(f"Sezione # {title} mancante")

    end = len(markdown)
    remainder = markdown[start_match.end() :]
    for next_title in next_titles:
        match = re.search(rf"(?im)^#\s+{re.escape(next_title)}\s*$", remainder)
        if match is not None:
            end = min(end, start_match.end() + match.start())
    return markdown[start_match.end() : end]


def _transcription_text(body: str, label: str) -> str:
    """Return fenced text when present, otherwise the plain section body."""
    fence = re.search(
        r"```(?:text)?\s*\n(.*?)\n```",
        body,
        flags=re.DOTALL | re.IGNORECASE,
    )
    value = fence.group(1) if fence is not None else body
    value = value.strip()
    if not value:
        raise ValueError(f"{label}: trascrizione mancante o vuota")
    return value


def parse_ground_truth_markdown(markdown: str) -> GroundTruth:
    top_headers = re.findall(r"(?im)^#\s+(FACILE|MEDIO|DIFFICILE)\s*$", markdown)
    if top_headers != ["FACILE", "MEDIO", "DIFFICILE"]:
        raise ValueError(
            "Servono esattamente # FACILE, # MEDIO, # DIFFICILE in quest'ordine"
        )

    facile = _transcription_text(
        _section_body(markdown, "FACILE", ("MEDIO", "DIFFICILE")),
        "FACILE",
    )
    medio = _transcription_text(
        _section_body(markdown, "MEDIO", ("DIFFICILE",)),
        "MEDIO",
    )

    hard_body = _section_body(markdown, "DIFFICILE", ())
    headings = ("MAIUSCOLO", "SCRIPT", "CORSIVO")
    subheaders = re.findall(
        r"(?im)^##\s+(MAIUSCOLO|SCRIPT|CORSIVO)\s*$",
        hard_body,
    )
    if subheaders != list(headings):
        raise ValueError(
            "DIFFICILE deve contenere ## MAIUSCOLO, ## SCRIPT, ## CORSIVO in quest'ordine"
        )

    segments: dict[str, str] = {}
    for index, heading in enumerate(headings):
        start = re.search(rf"(?im)^##\s+{heading}\s*$", hard_body)
        assert start is not None
        end = len(hard_body)
        if index + 1 < len(headings):
            next_heading = headings[index + 1]
            nxt = re.search(
                rf"(?im)^##\s+{next_heading}\s*$",
                hard_body[start.end() :],
            )
            if nxt is not None:
                end = start.end() + nxt.start()
        segments[HANDWRITING_SEGMENTS[index]] = _transcription_text(
            hard_body[start.end() : end],
            heading,
        )

    return GroundTruth(
        facile=facile,
        medio=medio,
        difficile_segments=segments,
    )


def load_ground_truth(path: Path) -> GroundTruth:
    if path.suffix.lower() != ".md":
        raise ValueError("Il ground truth deve essere .md")
    return parse_ground_truth_markdown(path.read_text(encoding="utf-8"))
