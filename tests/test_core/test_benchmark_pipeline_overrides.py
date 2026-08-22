"""Regression tests for benchmark-only pipeline overrides."""

from __future__ import annotations

import json

import numpy as np
from PIL import Image

from core import llama_backend, llama_ocr_api
from core.image_preprocessor import ImagePreprocessor
from tests.benchmark import run_realworld_suite as canonical_realworld
from tests.benchmark.run_pipeline_benchmark import (
    BENCHMARK_CONTEXT_SIZE,
    BENCHMARK_MAX_IMAGE_DIM,
    pipeline_configs,
)


class _FakeResponse:
    status = 200

    def read(self) -> bytes:
        return json.dumps(
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"completion_tokens": 1, "prompt_tokens": 1},
                "timings": {"cache_n": 0},
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


def test_production_request_shape_does_not_force_cache_setting(monkeypatch) -> None:
    monkeypatch.setattr(llama_ocr_api.http.client, "HTTPConnection", _FakeConnection)
    llama_ocr_api.ocr_image_api(Image.new("RGB", (32, 32), "white"), "http://127.0.0.1:12345")
    payload = _FakeConnection.last_payload
    assert payload is not None
    assert "cache_prompt" not in payload


def test_benchmark_can_explicitly_disable_prompt_cache(monkeypatch) -> None:
    monkeypatch.setattr(llama_ocr_api.http.client, "HTTPConnection", _FakeConnection)
    metrics: dict[str, object] = {}
    llama_ocr_api.ocr_image_api(
        Image.new("RGB", (32, 32), "white"),
        "http://127.0.0.1:12345",
        cache_prompt=False,
        metrics=metrics,
    )
    payload = _FakeConnection.last_payload
    assert payload is not None
    assert payload["cache_prompt"] is False
    assert metrics["cache_prompt"] is False


def test_pipeline_benchmark_defaults_are_uncapped_and_16k_only() -> None:
    baseline = pipeline_configs()[0]
    assert BENCHMARK_CONTEXT_SIZE == 16384
    assert BENCHMARK_MAX_IMAGE_DIM == 8192
    assert baseline.name == "baseline"
    assert baseline.max_image_dim == 8192
    # Importing benchmark code must not change the production server default.
    assert llama_backend.CONTEXT_SIZE == 4096


def test_realworld_benchmark_baseline_is_uncapped_and_16k_only() -> None:
    baseline = canonical_realworld._suite.production_baseline("OCR", name="test")
    assert canonical_realworld.BENCHMARK_BASELINE_MAX_IMAGE_DIM == 8192
    assert baseline.max_image_dim == 8192
    assert baseline.runtime.context_size == 16384
    # Canonical benchmark overrides remain isolated from production defaults.
    assert llama_backend.CONTEXT_SIZE == 4096
    assert llama_ocr_api.MAX_IMAGE_DIM == 1920


def test_full_preprocessing_mode_is_equivalent_to_production_enhance() -> None:
    source = np.array(
        [
            [[20, 30, 40], [80, 90, 100]],
            [[150, 160, 170], [220, 230, 240]],
        ],
        dtype=np.uint8,
    )
    preprocessor = ImagePreprocessor()
    assert np.array_equal(preprocessor.enhance(source), preprocessor.apply_mode(source, "full"))


def test_explicit_preprocessing_modes_are_distinct_and_validated() -> None:
    source = np.zeros((4200, 10, 3), dtype=np.uint8)
    source[:, :, 0] = np.arange(4200, dtype=np.uint16)[:, None] % 255
    preprocessor = ImagePreprocessor()

    none = preprocessor.apply_mode(source, "none")
    resized = preprocessor.apply_mode(source, "resize")
    contrast = preprocessor.apply_mode(source, "contrast")

    assert none.shape == source.shape
    assert resized.shape[0] == 4096
    assert contrast.shape == source.shape

    try:
        preprocessor.apply_mode(source, "unknown")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown preprocessing mode must fail")
