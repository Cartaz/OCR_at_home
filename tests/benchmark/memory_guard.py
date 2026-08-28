"""Benchmark-only host-memory isolation and telemetry helpers."""

from __future__ import annotations

import gc
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

MEMORY_ISOLATION_VERSION = 1
_DEFAULT_SAMPLE_INTERVAL_S = 0.20
_DEFAULT_SETTLE_TIMEOUT_S = 6.0
_DEFAULT_SETTLE_INTERVAL_S = 0.20
_DEFAULT_STABLE_SAMPLES = 3
_DEFAULT_STABLE_TOLERANCE_MIB = 64.0

_MEMINFO_FIELDS = (
    "MemTotal",
    "MemFree",
    "MemAvailable",
    "Cached",
    "AnonPages",
    "SwapTotal",
    "SwapFree",
)


@dataclass(frozen=True)
class SystemMemorySnapshot:
    monotonic_s: float
    mem_total_mib: float
    mem_free_mib: float
    mem_available_mib: float
    cached_mib: float
    anon_pages_mib: float
    swap_total_mib: float
    swap_free_mib: float

    @property
    def swap_used_mib(self) -> float:
        return max(0.0, self.swap_total_mib - self.swap_free_mib)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def parse_meminfo(
    text: str,
    *,
    monotonic_s: float | None = None,
) -> SystemMemorySnapshot:
    """Parse the stable subset of Linux /proc/meminfo used by the benchmark."""

    values: dict[str, float] = {}
    wanted = set(_MEMINFO_FIELDS)
    for raw_line in text.splitlines():
        key, separator, remainder = raw_line.partition(":")
        if not separator or key not in wanted:
            continue
        parts = remainder.split()
        if not parts:
            continue
        values[key] = float(parts[0]) / 1024.0

    missing = [key for key in _MEMINFO_FIELDS if key not in values]
    if missing:
        raise ValueError("Campi /proc/meminfo mancanti: " + ", ".join(missing))

    return SystemMemorySnapshot(
        monotonic_s=time.monotonic() if monotonic_s is None else float(monotonic_s),
        mem_total_mib=values["MemTotal"],
        mem_free_mib=values["MemFree"],
        mem_available_mib=values["MemAvailable"],
        cached_mib=values["Cached"],
        anon_pages_mib=values["AnonPages"],
        swap_total_mib=values["SwapTotal"],
        swap_free_mib=values["SwapFree"],
    )


def read_system_memory() -> SystemMemorySnapshot | None:
    if os.name != "posix":
        return None
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
        return parse_meminfo(text)
    except (OSError, ValueError):
        return None


def process_rss_mib(pid: int | None) -> float | None:
    if pid is None or os.name != "posix":
        return None
    try:
        with Path(f"/proc/{int(pid)}/status").open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except (OSError, ValueError):
        return None
    return None


@dataclass(frozen=True)
class _MemorySample:
    system: SystemMemorySnapshot | None
    server_rss_mib: float | None
    harness_rss_mib: float | None


class MemorySampler:
    """Low-overhead sampler for one OCR request.

    System memory is the primary signal on an integrated GPU because GPU
    allocations compete with the host for the same physical RAM.
    """

    def __init__(
        self,
        server_pid: int | None,
        *,
        interval_s: float = _DEFAULT_SAMPLE_INTERVAL_S,
        system_reader: Callable[[], SystemMemorySnapshot | None] = read_system_memory,
        rss_reader: Callable[[int | None], float | None] = process_rss_mib,
        harness_pid: int | None = None,
    ) -> None:
        self._server_pid = server_pid
        self._harness_pid = os.getpid() if harness_pid is None else int(harness_pid)
        self._interval_s = max(0.05, float(interval_s))
        self._system_reader = system_reader
        self._rss_reader = rss_reader
        self._samples: list[_MemorySample] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _safe_system_read(self) -> SystemMemorySnapshot | None:
        try:
            return self._system_reader()
        except Exception:
            return None

    def _safe_rss_read(self, pid: int | None) -> float | None:
        try:
            return self._rss_reader(pid)
        except Exception:
            return None

    def sample_now(self) -> None:
        self._samples.append(
            _MemorySample(
                system=self._safe_system_read(),
                server_rss_mib=self._safe_rss_read(self._server_pid),
                harness_rss_mib=self._safe_rss_read(self._harness_pid),
            )
        )

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval_s):
            self.sample_now()

    def start(self) -> None:
        if self._thread is not None:
            return
        self.sample_now()
        thread = threading.Thread(
            target=self._loop,
            name="benchmark-memory-sampler",
            daemon=True,
        )
        try:
            thread.start()
        except RuntimeError:
            self._thread = None
            return
        self._thread = thread

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop_event.set()
        thread.join(timeout=max(1.0, self._interval_s * 4))
        self.sample_now()
        self._thread = None

    def __enter__(self) -> "MemorySampler":
        self.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.stop()

    def to_dict(self) -> dict[str, object]:
        systems = [sample.system for sample in self._samples if sample.system is not None]
        server_rss = [
            float(sample.server_rss_mib)
            for sample in self._samples
            if sample.server_rss_mib is not None
        ]
        harness_rss = [
            float(sample.harness_rss_mib)
            for sample in self._samples
            if sample.harness_rss_mib is not None
        ]

        return {
            "supported": bool(systems),
            "sample_count": len(self._samples),
            "system_before": systems[0].to_dict() if systems else None,
            "system_after": systems[-1].to_dict() if systems else None,
            "mem_available_min_mib": (
                min(item.mem_available_mib for item in systems) if systems else None
            ),
            "mem_free_min_mib": (
                min(item.mem_free_mib for item in systems) if systems else None
            ),
            "cached_peak_mib": (
                max(item.cached_mib for item in systems) if systems else None
            ),
            "swap_used_peak_mib": (
                max(item.swap_used_mib for item in systems) if systems else None
            ),
            "server_rss_peak_mib": max(server_rss) if server_rss else None,
            "harness_rss_peak_mib": max(harness_rss) if harness_rss else None,
        }


@dataclass(frozen=True)
class CacheEvictionReport:
    supported: bool
    attempted_files: int
    advised_files: int
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "supported": self.supported,
            "attempted_files": self.attempted_files,
            "advised_files": self.advised_files,
            "errors": list(self.errors),
        }


def evict_file_cache(paths: Sequence[Path]) -> CacheEvictionReport:
    """Advise Linux to discard benchmark-owned clean file pages.

    This is deliberately targeted: it never uses global drop_caches and never
    requires elevated privileges.
    """

    fadvise = getattr(os, "posix_fadvise", None)
    advice = getattr(os, "POSIX_FADV_DONTNEED", None)
    if fadvise is None or advice is None:
        return CacheEvictionReport(False, 0, 0, ())

    attempted = 0
    advised = 0
    errors: list[str] = []
    seen: set[str] = set()

    for raw_path in paths:
        path = Path(raw_path).expanduser()
        key = str(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        attempted += 1
        fd: int | None = None
        try:
            fd = os.open(path, os.O_RDONLY)
            fadvise(fd, 0, 0, advice)
            advised += 1
        except OSError as exc:
            errors.append(f"{path}: {exc}")
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    return CacheEvictionReport(True, attempted, advised, tuple(errors))


@dataclass(frozen=True)
class MemoryStabilizationReport:
    supported: bool
    stable: bool
    elapsed_s: float
    sample_count: int
    available_spread_mib: float | None
    final: SystemMemorySnapshot | None

    def to_dict(self) -> dict[str, object]:
        return {
            "supported": self.supported,
            "stable": self.stable,
            "elapsed_s": self.elapsed_s,
            "sample_count": self.sample_count,
            "available_spread_mib": self.available_spread_mib,
            "final": self.final.to_dict() if self.final is not None else None,
        }


def wait_for_memory_stable(
    *,
    timeout_s: float = _DEFAULT_SETTLE_TIMEOUT_S,
    interval_s: float = _DEFAULT_SETTLE_INTERVAL_S,
    stable_samples: int = _DEFAULT_STABLE_SAMPLES,
    tolerance_mib: float = _DEFAULT_STABLE_TOLERANCE_MIB,
    snapshot_reader: Callable[[], SystemMemorySnapshot | None] = read_system_memory,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> MemoryStabilizationReport:
    stable_samples = max(2, int(stable_samples))
    interval_s = max(0.0, float(interval_s))
    timeout_s = max(0.0, float(timeout_s))
    tolerance_mib = max(0.0, float(tolerance_mib))

    started = clock()
    recent: list[SystemMemorySnapshot] = []
    total_samples = 0

    while True:
        snapshot = snapshot_reader()
        if snapshot is None:
            return MemoryStabilizationReport(
                supported=False,
                stable=True,
                elapsed_s=max(0.0, clock() - started),
                sample_count=total_samples,
                available_spread_mib=None,
                final=None,
            )

        total_samples += 1
        recent.append(snapshot)
        if len(recent) > stable_samples:
            recent.pop(0)

        if len(recent) == stable_samples:
            values = [item.mem_available_mib for item in recent]
            spread = max(values) - min(values)
            if spread <= tolerance_mib:
                return MemoryStabilizationReport(
                    supported=True,
                    stable=True,
                    elapsed_s=max(0.0, clock() - started),
                    sample_count=total_samples,
                    available_spread_mib=spread,
                    final=snapshot,
                )

        if clock() - started >= timeout_s:
            values = [item.mem_available_mib for item in recent]
            spread = max(values) - min(values) if values else None
            return MemoryStabilizationReport(
                supported=True,
                stable=False,
                elapsed_s=max(0.0, clock() - started),
                sample_count=total_samples,
                available_spread_mib=spread,
                final=snapshot,
            )

        sleep(interval_s)


def settle_benchmark_memory(
    paths: Sequence[Path],
    *,
    timeout_s: float = _DEFAULT_SETTLE_TIMEOUT_S,
) -> dict[str, object]:
    """Release benchmark-owned cache pressure and wait for host RAM to settle."""

    gc.collect()
    eviction = evict_file_cache(paths)
    stabilization = wait_for_memory_stable(timeout_s=timeout_s)
    return {
        "memory_isolation_version": MEMORY_ISOLATION_VERSION,
        "cache_eviction": eviction.to_dict(),
        "stabilization": stabilization.to_dict(),
    }
