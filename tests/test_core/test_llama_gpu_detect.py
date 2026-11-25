"""SYCL detection relies only on `llama-server --list-devices`."""

from types import SimpleNamespace

from core import llama_gpu_detect


def _run(stdout: str, returncode: int = 0):
    return lambda *a, **k: SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def test_sycl_devices_are_parsed_from_list_devices(monkeypatch) -> None:
    monkeypatch.setattr(
        llama_gpu_detect.subprocess,
        "run",
        _run("Available devices:\n  SYCL0: Intel(R) Arc(TM) Graphics (14027 MiB, 14027 MiB free)\n"),
    )
    assert llama_gpu_detect.list_sycl_devices("/fake") == [
        "SYCL0: Intel(R) Arc(TM) Graphics (14027 MiB, 14027 MiB free)"
    ]


def test_cpu_or_vulkan_only_builds_are_not_sycl(monkeypatch) -> None:
    monkeypatch.setattr(llama_gpu_detect.subprocess, "run", _run("Available devices:\n  Vulkan0: Intel\n"))
    assert llama_gpu_detect.list_sycl_devices("/fake") == []


def test_failing_probe_is_not_a_device(monkeypatch) -> None:
    monkeypatch.setattr(llama_gpu_detect.subprocess, "run", _run("SYCL0: x", returncode=1))
    assert llama_gpu_detect.list_sycl_devices("/fake") == []
    assert llama_gpu_detect.list_sycl_devices(None) == []


def test_runtime_env_respects_a_user_device_selector(monkeypatch) -> None:
    monkeypatch.setenv("ONEAPI_DEVICE_SELECTOR", "level_zero:1")
    assert llama_gpu_detect.sycl_runtime_env()["ONEAPI_DEVICE_SELECTOR"] == "level_zero:1"
    monkeypatch.delenv("ONEAPI_DEVICE_SELECTOR")
    env = llama_gpu_detect.sycl_runtime_env()
    assert env["ONEAPI_DEVICE_SELECTOR"] == "level_zero:0"
    assert env["GGML_SYCL"] == "1"


def test_empty_device_description_does_not_swallow_the_next_line(monkeypatch) -> None:
    monkeypatch.setattr(llama_gpu_detect.subprocess, "run", _run("Available devices:\n  SYCL0:\nnext line\n"))
    assert llama_gpu_detect.list_sycl_devices("/fake") == ["SYCL0"]
