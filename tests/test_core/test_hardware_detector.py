"""Test hardware detector cache/refresh."""

from core.hardware_detector import HardwareDetector


def test_detect_uses_cache_until_refresh(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("core.hardware_detector.find_llama_server", lambda: "/fake/server")

    def detect_backend(_preferred):
        calls.append(1)
        return 0, "cpu"

    monkeypatch.setattr("core.hardware_detector.detect_gpu_backend", detect_backend)
    detector = HardwareDetector()
    detector.detect()
    detector.detect()
    assert len(calls) == 1
    detector.detect(refresh=True)
    assert len(calls) == 2
