"""Regression tests for benchmark-only memory isolation."""

from __future__ import annotations

import os
from pathlib import Path

from tests.benchmark.memory_guard import (
    MemorySampler,
    SystemMemorySnapshot,
    evict_file_cache,
    parse_meminfo,
    wait_for_memory_stable,
)


def _snapshot(available_mib: float, *, monotonic_s: float) -> SystemMemorySnapshot:
    return SystemMemorySnapshot(
        monotonic_s=monotonic_s,
        mem_total_mib=16000.0,
        mem_free_mib=max(0.0, available_mib - 1000.0),
        mem_available_mib=available_mib,
        cached_mib=3500.0,
        anon_pages_mib=1800.0,
        swap_total_mib=16000.0,
        swap_free_mib=15500.0,
    )


def test_parse_meminfo_matches_linux_kib_units() -> None:
    snapshot = parse_meminfo(
        """
MemTotal:       15774520 kB
MemFree:         1325616 kB
MemAvailable:    4993636 kB
Cached:          3744912 kB
AnonPages:       1721688 kB
SwapTotal:      15773692 kB
SwapFree:       15360900 kB
""",
        monotonic_s=1.0,
    )

    assert snapshot.mem_available_mib == 4993636 / 1024
    assert snapshot.cached_mib == 3744912 / 1024
    assert snapshot.swap_used_mib == (15773692 - 15360900) / 1024


def test_wait_for_memory_stable_uses_available_memory_spread() -> None:
    readings = iter(
        (
            _snapshot(4000.0, monotonic_s=0.0),
            _snapshot(4500.0, monotonic_s=0.1),
            _snapshot(4800.0, monotonic_s=0.2),
            _snapshot(4810.0, monotonic_s=0.3),
            _snapshot(4805.0, monotonic_s=0.4),
        )
    )
    clock_values = iter((0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7))

    report = wait_for_memory_stable(
        timeout_s=2.0,
        interval_s=0.0,
        stable_samples=3,
        tolerance_mib=16.0,
        snapshot_reader=lambda: next(readings),
        sleep=lambda _seconds: None,
        clock=lambda: next(clock_values),
    )

    assert report.supported is True
    assert report.stable is True
    assert report.final is not None
    assert report.final.mem_available_mib == 4805.0
    assert report.available_spread_mib == 10.0


def test_memory_sampler_tracks_system_and_both_process_peaks() -> None:
    systems = iter(
        (
            _snapshot(5000.0, monotonic_s=0.0),
            _snapshot(3200.0, monotonic_s=0.1),
        )
    )
    rss = {
        10: iter((1000.0, 1400.0)),
        20: iter((300.0, 450.0)),
    }

    sampler = MemorySampler(
        10,
        system_reader=lambda: next(systems),
        rss_reader=lambda pid: next(rss[int(pid)]),
        harness_pid=20,
    )
    sampler.sample_now()
    sampler.sample_now()
    metrics = sampler.to_dict()

    assert metrics["mem_available_min_mib"] == 3200.0
    assert metrics["server_rss_peak_mib"] == 1400.0
    assert metrics["harness_rss_peak_mib"] == 450.0
    assert metrics["swap_used_peak_mib"] == 500.0


def test_cache_eviction_is_targeted_and_deduplicated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "model.gguf"
    source.write_bytes(b"GGUF" + b"x" * 4096)
    calls: list[tuple[int, int, int, int]] = []

    monkeypatch.setattr(
        os,
        "posix_fadvise",
        lambda fd, offset, length, advice: calls.append((fd, offset, length, advice)),
        raising=False,
    )
    monkeypatch.setattr(os, "POSIX_FADV_DONTNEED", 4, raising=False)

    report = evict_file_cache((source, source, tmp_path / "missing.gguf"))

    assert report.supported is True
    assert report.attempted_files == 1
    assert report.advised_files == 1
    assert len(calls) == 1
    assert calls[0][1:] == (0, 0, 4)
