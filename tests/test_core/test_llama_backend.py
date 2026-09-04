"""Test del backend llama-server SYCL senza avviare un modello reale."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.exceptions import ModelLoadError
from core.llama_backend import LlamaServerBackend, _production_runtime_args
from core.owned_process import owned_process_argv


def test_generic_backend_is_rejected_before_startup() -> None:
    backend = LlamaServerBackend(preferred_device="llama-cpp")
    with pytest.raises(ModelLoadError):
        backend.initialize()


def test_single_pdf_disables_whole_document_replay(monkeypatch, tmp_path: Path) -> None:
    backend = LlamaServerBackend(preferred_device="llama-cpp-sycl")
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


def test_production_runtime_args_leave_llama_cpp_tuning_stock() -> None:
    assert _production_runtime_args() == []


def test_linux_owned_process_uses_parent_death_exec_shim() -> None:
    args = owned_process_argv(["/tmp/llama-server", "--version"], owner_pid=1234)
    if __import__("os").name == "posix" and __import__("sys").platform.startswith("linux"):
        assert args[-4:] == ["1234", "--", "/tmp/llama-server", "--version"]
    else:
        assert args == ["/tmp/llama-server", "--version"]
