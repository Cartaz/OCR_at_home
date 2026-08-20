"""Test hardware detector SYCL-only e cache/refresh."""

from core.hardware_detector import HardwareDetector


def test_detect_uses_cache_until_refresh(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("core.hardware_detector.find_llama_server", lambda: "/fake/server")

    def detect_backend(_preferred):
        calls.append(1)
        return 99, "sycl"

    monkeypatch.setattr("core.hardware_detector.detect_gpu_backend", detect_backend)
    detector = HardwareDetector()
    detector.detect()
    detector.detect()
    assert len(calls) == 1
    detector.detect(refresh=True)
    assert len(calls) == 2


def test_detector_exposes_only_sycl(monkeypatch) -> None:
    monkeypatch.setattr("core.hardware_detector.find_llama_server", lambda: "/fake/server")
    monkeypatch.setattr(
        "core.hardware_detector.detect_gpu_backend",
        lambda _preferred: (99, "sycl"),
    )
    devices = HardwareDetector().detect()
    assert len(devices) == 1
    assert devices[0].device_type == "llama-cpp-sycl"
    assert devices[0].available is True
