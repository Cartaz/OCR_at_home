"""Pinned GGUF download and SHA-256 verification (audit M3)."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest

import core.llama_models as llama_models
from core.cancellation import CancellationToken
from core.exceptions import ModelLoadError, OperationCancelledError


def _spec(content: bytes, name: str = "model.gguf") -> llama_models.ModelFile:
    return llama_models.ModelFile(name, hashlib.sha256(content).hexdigest(), len(content))


@pytest.fixture
def one_file(monkeypatch, tmp_path):
    content = b"GGUF" + b"x" * 60
    spec = _spec(content)
    monkeypatch.setattr(llama_models, "GGUF_CACHE_DIR", tmp_path)
    monkeypatch.setattr(llama_models, "GGUF_MODEL_FILES", {"main": spec})
    return tmp_path, content, spec


def test_cancel_before_download_propagates_cancellation(one_file) -> None:
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelledError):
        llama_models.ensure_gguf_models(cancel_token=token)


def test_verified_file_is_hashed_once(one_file, monkeypatch) -> None:
    directory, content, spec = one_file
    (directory / spec.filename).write_bytes(content)
    hashed: list[Path] = []
    real = llama_models._sha256
    monkeypatch.setattr(llama_models, "_sha256", lambda path, token=None: hashed.append(path) or real(path, token))
    llama_models.ensure_gguf_models()
    llama_models.ensure_gguf_models()
    assert len(hashed) == 1


def test_tampered_file_is_redownloaded_from_pinned_revision(one_file, monkeypatch) -> None:
    directory, content, spec = one_file
    (directory / spec.filename).write_bytes(b"GGUF" + b"y" * 60)  # same size, wrong hash
    requests: list[dict] = []

    def fake_download(**kwargs):
        requests.append(kwargs)
        target = Path(kwargs["local_dir"]) / kwargs["filename"]
        target.write_bytes(content)
        return str(target)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    paths = llama_models.ensure_gguf_models()
    assert paths["main"].read_bytes() == content
    assert requests[0]["revision"] == llama_models.GGUF_MODEL_REVISION


def test_download_with_wrong_hash_is_rejected(one_file, monkeypatch) -> None:
    directory, _content, spec = one_file

    def fake_download(**kwargs):
        target = Path(kwargs["local_dir"]) / kwargs["filename"]
        target.write_bytes(b"GGUF" + b"z" * 60)
        return str(target)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    with pytest.raises(ModelLoadError, match="SHA-256"):
        llama_models.ensure_gguf_models()


def test_cancel_returns_without_waiting_for_a_stuck_download(one_file, monkeypatch) -> None:
    stuck = threading.Event()
    monkeypatch.setattr("huggingface_hub.hf_hub_download", lambda **_kw: stuck.wait(5))
    token = CancellationToken()
    threading.Timer(0.2, token.cancel).start()
    with pytest.raises(OperationCancelledError):
        llama_models.ensure_gguf_models(cancel_token=token)
    stuck.set()


def test_hashing_stops_when_the_load_is_cancelled(one_file) -> None:
    directory, content, spec = one_file
    (directory / spec.filename).write_bytes(content)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelledError):
        llama_models._is_verified(directory / spec.filename, spec, token)


def test_retry_joins_a_download_left_running_by_a_cancelled_load(one_file, monkeypatch) -> None:
    directory, content, spec = one_file
    release = threading.Event()
    calls: list[int] = []

    def slow_download(**kwargs):
        calls.append(1)
        assert release.wait(5)
        target = Path(kwargs["local_dir"]) / kwargs["filename"]
        target.write_bytes(content)
        return str(target)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", slow_download)
    monkeypatch.setattr(llama_models, "_DOWNLOADS", {})
    token = CancellationToken()
    threading.Timer(0.2, token.cancel).start()
    with pytest.raises(OperationCancelledError):
        llama_models.ensure_gguf_models(cancel_token=token)

    threading.Timer(0.2, release.set).start()
    paths = llama_models.ensure_gguf_models()
    assert paths["main"].read_bytes() == content
    assert calls == [1]
