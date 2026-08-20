"""Test del rilevamento SYCL-only di llama.cpp."""

from types import SimpleNamespace

from core import llama_gpu_detect


def test_sycl_list_devices_is_authoritative(monkeypatch) -> None:
    monkeypatch.setattr(
        llama_gpu_detect,
        "_list_devices_text",
        lambda _path: "Available devices:\n  SYCL0: Intel(R) Arc Graphics\n",
    )
    assert llama_gpu_detect._check_sycl("/fake/llama-server") is True


def test_generic_backend_request_is_rejected_without_cpu_or_vulkan(monkeypatch) -> None:
    monkeypatch.setattr(llama_gpu_detect, "find_llama_server", lambda: "/fake/server")
    monkeypatch.setattr(llama_gpu_detect, "_check_sycl", lambda _path: True)
    layers, backend = llama_gpu_detect.detect_gpu_backend("llama-cpp")
    assert layers == 0
    assert backend == "unavailable"


def test_no_sycl_returns_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(llama_gpu_detect, "find_llama_server", lambda: "/fake/server")
    monkeypatch.setattr(llama_gpu_detect, "_check_sycl", lambda _path: False)
    layers, backend = llama_gpu_detect.detect_gpu_backend("llama-cpp-sycl")
    assert layers == 0
    assert backend == "unavailable"


def test_intel_display_controller_is_detected(monkeypatch) -> None:
    result = SimpleNamespace(
        returncode=0,
        stdout="00:02.0 Display controller: Intel Corporation Meteor Lake-P [Intel Arc Graphics]\n",
    )
    monkeypatch.setattr(llama_gpu_detect.subprocess, "run", lambda *a, **k: result)
    assert llama_gpu_detect._intel_gpu_present() is True
