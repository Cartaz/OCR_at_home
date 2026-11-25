"""HardwareDetector caching and status."""

from core.event_bus import EventBus
from core.hardware_detector import HardwareDetector


def test_detect_uses_cache_until_refresh(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("core.hardware_detector.find_llama_server", lambda: "/fake/server")
    monkeypatch.setattr(
        "core.hardware_detector.list_sycl_devices",
        lambda _path: calls.append(1) or ["SYCL0: Intel Arc"],
    )
    detector = HardwareDetector()
    detector.detect()
    detector.detect()
    assert len(calls) == 1
    detector.detect(refresh=True)
    assert len(calls) == 2


def test_status_is_published(monkeypatch) -> None:
    monkeypatch.setattr("core.hardware_detector.find_llama_server", lambda: "/fake/server")
    monkeypatch.setattr("core.hardware_detector.list_sycl_devices", lambda _path: ["SYCL0: Intel Arc"])
    events: list[dict] = []
    EventBus.subscribe("hardware_detected", events.append)
    status = HardwareDetector().detect()
    assert status.available is True
    assert events == [{"available": True, "label": "llama.cpp + SYCL0: Intel Arc"}]


def test_missing_server_is_reported(monkeypatch) -> None:
    monkeypatch.setattr("core.hardware_detector.find_llama_server", lambda: None)
    status = HardwareDetector().detect()
    assert status.available is False
    assert "non installato" in status.label
