"""LlamaServerBackend behavior that needs no real server."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.exceptions import ModelLoadError, OCRProcessingError
from core.llama_backend import LlamaServerBackend
from core.llama_ocr_api import LlamaServerConnectionError
from core.owned_process import owned_process_argv


def _ready_backend(monkeypatch) -> LlamaServerBackend:
    backend = LlamaServerBackend()
    backend._initialized = True  # type: ignore[attr-defined]
    backend._server_url = "http://127.0.0.1:12345"  # type: ignore[attr-defined]
    backend._process = SimpleNamespace(poll=lambda: None)  # type: ignore[attr-defined]
    monkeypatch.setattr(backend, "_ensure_server_ready", lambda **kwargs: None)
    return backend


def test_missing_server_fails_with_install_hint(monkeypatch) -> None:
    monkeypatch.setattr("core.llama_backend.find_llama_server", lambda: None)
    with pytest.raises(ModelLoadError, match="install.sh"):
        LlamaServerBackend().initialize()


def test_no_sycl_device_refuses_to_start(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("core.llama_backend.find_llama_server", lambda: "/fake/llama-server")
    monkeypatch.setattr("core.llama_backend.ensure_gguf_models", lambda **_kw: {})
    monkeypatch.setattr("core.llama_backend.list_sycl_devices", lambda _path: [])
    with pytest.raises(ModelLoadError, match="SYCL"):
        LlamaServerBackend().initialize()


def test_single_pdf_disables_whole_document_replay(monkeypatch, tmp_path: Path) -> None:
    backend = _ready_backend(monkeypatch)
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    calls = 0

    def failing_pdf(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise LlamaServerConnectionError("connection reset")

    monkeypatch.setattr("core.llama_backend.ocr_pdf", failing_pdf)
    with pytest.raises(OCRProcessingError, match="sample.pdf"):
        backend.process_image(pdf, mode="single")
    assert calls == 1


def test_non_connection_errors_are_not_retried(monkeypatch, tmp_path: Path) -> None:
    backend = _ready_backend(monkeypatch)
    image = tmp_path / "a.png"
    image.write_bytes(b"x")
    calls = 0

    def bad_image(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("Risposta non JSON da llama-server")

    monkeypatch.setattr("core.llama_backend.ocr_single_image", bad_image)
    restarts: list[int] = []
    monkeypatch.setattr(backend, "_start_server", lambda **_kw: restarts.append(1))
    with pytest.raises(OCRProcessingError):
        backend.process_image(image, mode="batch")
    assert calls == 1 and restarts == []


def test_pdf_result_keeps_pages(monkeypatch, tmp_path: Path) -> None:
    backend = _ready_backend(monkeypatch)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr("core.llama_backend.ocr_pdf", lambda *a, **k: ["uno", "due"])
    result = backend.process_image(pdf, mode="batch")
    assert result.pages == ("uno", "due")
    assert result.text == "--- Pagina 1 ---\nuno\n\n--- Pagina 2 ---\ndue"


def test_production_runtime_leaves_llama_cpp_tuning_stock() -> None:
    assert LlamaServerBackend()._runtime_args() == []


def test_linux_owned_process_uses_parent_death_exec_shim() -> None:
    args = owned_process_argv(["/tmp/llama-server", "--version"], owner_pid=1234)
    if __import__("os").name == "posix" and __import__("sys").platform.startswith("linux"):
        assert args[-4:] == ["1234", "--", "/tmp/llama-server", "--version"]
    else:
        assert args == ["/tmp/llama-server", "--version"]
