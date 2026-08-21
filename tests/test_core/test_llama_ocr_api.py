"""Tests for llama-server OCR API response semantics."""

from __future__ import annotations

import json

from PIL import Image

from core import llama_ocr_api


class _FakeResponse:
    status = 200

    def read(self) -> bytes:
        return json.dumps(
            {
                "choices": [{"message": {"content": "testo riconosciuto"}}],
                "usage": {"completion_tokens": 2, "prompt_tokens": 1},
            }
        ).encode("utf-8")


class _FakeConnection:
    def __init__(self, *_args, **_kwargs) -> None:
        self.sock = None

    def request(self, *_args, **_kwargs) -> None:
        return None

    def getresponse(self) -> _FakeResponse:
        return _FakeResponse()

    def close(self) -> None:
        return None


def test_ocr_image_api_does_not_fabricate_confidence(monkeypatch) -> None:
    monkeypatch.setattr(llama_ocr_api.http.client, "HTTPConnection", _FakeConnection)
    image = Image.new("RGB", (32, 32), "white")

    text, confidence = llama_ocr_api.ocr_image_api(
        image,
        "http://127.0.0.1:12345",
    )

    assert text == "testo riconosciuto"
    assert confidence is None
