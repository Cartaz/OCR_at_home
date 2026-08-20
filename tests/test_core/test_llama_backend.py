"""Test del backend llama-server senza avviare un modello reale."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.exceptions import ModelLoadError
from core.llama_backend import LlamaServerBackend


def test_single_pdf_disables_whole_document_replay(monkeypatch, tmp_path: Path) -> None:
    backend = LlamaServerBackend(preferred_device="llama-cpp")
    backend._initialized = True  # type: ignore[attr-defined]
    backend._server_url = "http://127.0.0.1:12345"  # type: ignore[attr-defined]
    backend._process = SimpleNamespace(poll=lambda: None)  # type: ignore[attr-defined]
    monkeypatch.setattr(backend, "_ensure_server_ready", lambda **kwargs: None)

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    calls = 0

    def failing_pdf(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("connection reset")

    monkeypatch.setattr("core.llama_backend.ocr_pdf", failing_pdf)

    with pytest.raises(ModelLoadError):
        backend.process_image(pdf, mode="single")

    assert calls == 1
