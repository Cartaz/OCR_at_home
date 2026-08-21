"""Deterministic tests for Phase 5 image/PDF pipeline controls."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from core.llama_ocr_api import (
    JPEG_QUALITY,
    MAX_IMAGE_DIM,
    PDF_DPI,
    _prepare_image_payload,
    ocr_pdf,
)


def test_production_pipeline_defaults_remain_unchanged() -> None:
    assert PDF_DPI == 150
    assert MAX_IMAGE_DIM == 1920
    assert JPEG_QUALITY == 85


def test_prepare_image_payload_respects_dimension_and_quality_overrides() -> None:
    image = Image.new("RGB", (3000, 1000), "white")

    encoded_1280, metrics_1280 = _prepare_image_payload(
        image,
        max_image_dim=1280,
        jpeg_quality=70,
    )
    encoded_2560, metrics_2560 = _prepare_image_payload(
        image,
        max_image_dim=2560,
        jpeg_quality=95,
    )

    first = Image.open(io.BytesIO(base64.b64decode(encoded_1280)))
    second = Image.open(io.BytesIO(base64.b64decode(encoded_2560)))

    assert first.size == (1280, 426)
    assert second.size == (2560, 853)
    assert metrics_1280["sent_width"] == 1280
    assert metrics_1280["jpeg_quality"] == 70
    assert metrics_2560["sent_width"] == 2560
    assert metrics_2560["jpeg_quality"] == 95
    assert metrics_2560["encoded_bytes"] > metrics_1280["encoded_bytes"]


@pytest.mark.parametrize(
    ("max_dim", "quality"),
    [(255, 85), (8193, 85), (1920, 0), (1920, 101)],
)
def test_prepare_image_payload_rejects_invalid_benchmark_values(
    max_dim: int,
    quality: int,
) -> None:
    with pytest.raises(ValueError):
        _prepare_image_payload(
            Image.new("RGB", (100, 100), "white"),
            max_image_dim=max_dim,
            jpeg_quality=quality,
        )


def test_pdf_pipeline_forwards_dpi_encoding_options_and_collects_page_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    observed: dict[str, object] = {}

    monkeypatch.setattr("core.llama_ocr_api.pdf_page_count", lambda _path: 1)

    def render(_path: Path, page_num: int, *, dpi: int):
        observed["page_num"] = page_num
        observed["dpi"] = dpi
        return Image.new("RGB", (2200, 1400), "white")

    def api(
        _image,
        _server_url: str,
        *,
        max_image_dim: int,
        jpeg_quality: int,
        metrics: dict,
        **_kwargs,
    ):
        observed["max_image_dim"] = max_image_dim
        observed["jpeg_quality"] = jpeg_quality
        metrics.update(
            {
                "encoded_bytes": 12345,
                "sent_width": 1600,
                "sent_height": 1018,
                "request_elapsed_s": 0.5,
            }
        )
        return "testo", None

    monkeypatch.setattr("core.llama_ocr_api.pdf_page_to_image", render)
    monkeypatch.setattr("core.llama_ocr_api.ocr_image_api", api)

    page_metrics: list[dict] = []
    text, confidence = ocr_pdf(
        pdf,
        "http://127.0.0.1:9999",
        preprocessing_enabled=False,
        emit_events=False,
        pdf_dpi=220,
        max_image_dim=1600,
        jpeg_quality=72,
        page_metrics=page_metrics,
    )

    assert text == "testo"
    assert confidence is None
    assert observed == {
        "page_num": 1,
        "dpi": 220,
        "max_image_dim": 1600,
        "jpeg_quality": 72,
    }
    assert len(page_metrics) == 1
    assert page_metrics[0]["pdf_dpi"] == 220
    assert page_metrics[0]["preprocessing_enabled"] is False
    assert page_metrics[0]["encoded_bytes"] == 12345
