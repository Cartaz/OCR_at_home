"""Test del rilevamento dispositivi llama.cpp."""

from types import SimpleNamespace

from core import llama_gpu_detect


def test_sycl_list_devices_is_authoritative(monkeypatch) -> None:
    monkeypatch.setattr(
        llama_gpu_detect,
        "_list_devices_text",
        lambda _path: "Available devices:\n  SYCL0: Intel(R) Arc Graphics\n",
    )
    assert llama_gpu_detect._check_sycl("/fake/llama-server") is True


def test_vulkan_list_devices_is_authoritative(monkeypatch) -> None:
    monkeypatch.setattr(
        llama_gpu_detect,
        "_list_devices_text",
        lambda _path: "Available devices:\n  Vulkan0: AMD Radeon Graphics\n",
    )
    assert llama_gpu_detect._check_vulkan("/fake/llama-server") is True


def test_intel_display_controller_is_detected(monkeypatch) -> None:
    result = SimpleNamespace(
        returncode=0,
        stdout="00:02.0 Display controller: Intel Corporation Meteor Lake-P [Intel Arc Graphics]\n",
    )
    monkeypatch.setattr(llama_gpu_detect.subprocess, "run", lambda *a, **k: result)
    assert llama_gpu_detect._intel_gpu_present() is True
