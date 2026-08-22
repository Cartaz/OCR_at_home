"""Coherent quality reference for the canonical benchmark.

A quality reference must come from one complete measured profile. Building a
synthetic envelope from the best value of every metric can create a reference
that no real configuration ever achieved and therefore make every candidate
fail simultaneously.
"""

from __future__ import annotations

from collections.abc import Sequence

from tests.benchmark.realworld_suite_v2 import ConfigAggregate, QualityReference


def quality_reference(aggregates: Sequence[ConfigAggregate]) -> QualityReference:
    """Build the gate reference from the best complete cache-free profile.

    The anchor is the valid configuration with the highest macro character
    accuracy; elapsed time breaks exact accuracy ties. All document, WER and
    handwriting-segment reference values are taken from that same profile.
    Therefore the reference is physically attainable and the anchor itself is
    guaranteed to pass its own relative gates.
    """

    valid = [
        aggregate
        for aggregate in aggregates
        if aggregate.valid and aggregate.cache_n_total == 0
    ]
    if not valid:
        raise ValueError("Nessuna configurazione valida cache-free")

    anchor = max(
        valid,
        key=lambda aggregate: (
            aggregate.macro_char_accuracy,
            -aggregate.macro_elapsed_s,
        ),
    )

    return QualityReference(
        best_macro_accuracy=anchor.macro_char_accuracy,
        document_accuracy={
            level: document.trimmed_char_accuracy
            for level, document in anchor.documents.items()
        },
        document_wer={
            level: document.trimmed_wer
            for level, document in anchor.documents.items()
        },
        segment_accuracy={
            name: score.char_accuracy
            for name, score in anchor.hard_segments.items()
        },
        segment_wer={
            name: score.wer
            for name, score in anchor.hard_segments.items()
        },
    )
