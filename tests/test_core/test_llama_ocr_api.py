"""Tests for llama-server OCR API response and prompt semantics."""

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
    last_payload: dict[str, object] | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        self.sock = None

    def request(self, _method, _path, *, body=None, headers=None) -> None:
        del headers
        if body is not None:
            self.__class__.last_payload = json.loads(body.decode("utf-8"))

    def getresponse(self) -> _FakeResponse:
        return _FakeResponse()

    def close(self) -> None:
        return None


def _last_prompt() -> str:
    payload = _FakeConnection.last_payload
    assert payload is not None
    messages = payload["messages"]
    assert isinstance(messages, list)
    content = messages[0]["content"]
    assert isinstance(content, list)
    return str(content[1]["text"])


def test_ocr_image_api_does_not_fabricate_confidence(monkeypatch) -> None:
    monkeypatch.setattr(llama_ocr_api.http.client, "HTTPConnection", _FakeConnection)
    image = Image.new("RGB", (32, 32), "white")

    text, confidence = llama_ocr_api.ocr_image_api(
        image,
        "http://127.0.0.1:12345",
    )

    assert text == "testo riconosciuto"
    assert confidence is None


def test_production_default_prompt_remains_legacy_ocr(monkeypatch) -> None:
    monkeypatch.setattr(llama_ocr_api.http.client, "HTTPConnection", _FakeConnection)
    image = Image.new("RGB", (32, 32), "white")

    llama_ocr_api.ocr_image_api(image, "http://127.0.0.1:12345")

    assert llama_ocr_api.OCR_PROMPT == "OCR"
    assert _last_prompt() == "OCR"


def test_official_task_prompt_can_be_selected_without_changing_default(monkeypatch) -> None:
    monkeypatch.setattr(llama_ocr_api.http.client, "HTTPConnection", _FakeConnection)
    image = Image.new("RGB", (32, 32), "white")

    llama_ocr_api.ocr_image_api(
        image,
        "http://127.0.0.1:12345",
        prompt=llama_ocr_api.PROMPT_TEXT_RECOGNITION,
    )

    assert llama_ocr_api.PROMPT_TEXT_RECOGNITION == "Text Recognition:"
    assert llama_ocr_api.PROMPT_TABLE_RECOGNITION == "Table Recognition:"
    assert llama_ocr_api.PROMPT_FORMULA_RECOGNITION == "Formula Recognition:"
    assert _last_prompt() == "Text Recognition:"
    assert llama_ocr_api.OCR_PROMPT == "OCR"
