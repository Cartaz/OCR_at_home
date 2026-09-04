"""Canonical real-world GLM-OCR benchmark, protocol v2.

The benchmark tunes prompt, image/PDF pipeline and relevant llama-server runtime
variables. It uses one continuous handwritten page split only at scoring time
into MAIUSCOLO/SCRIPT/CORSIVO. Production defaults are never changed here.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llama_ocr_api import ocr_pdf, ocr_single_image  # noqa: E402
from tests.benchmark.canonical_policy import (  # noqa: E402
    CHECKPOINT_SCHEMA,
    fastest_quality_equivalent,
    load_ground_truth,
    production_baseline,
    prompt_configs,
    quality_reference,
    select_fastest_quality_gated_values,
    stage_a_groups,
)
from tests.benchmark.memory_guard import (  # noqa: E402
    MEMORY_ISOLATION_VERSION,
    MEMORY_PRESSURE_FLOOR_MIB,
    MemorySampler,
    process_rss_mib,
    settle_benchmark_memory,
)
from tests.benchmark.realworld_suite_v2 import (  # noqa: E402
    BENCHMARK_SEED,
    DEFAULT_BEAM_WIDTH,
    DEFAULT_RUNS,
    DEFAULT_TOP_VALUES,
    HANDWRITING_SEGMENTS,
    LEVELS,
    BenchmarkDocument,
    ConfigAggregate,
    Observation,
    PipelineConfig,
    affected_levels,
    aggregate_config,
    atomic_write_json,
    beam_expand,
    classify_quality,
    config_variable_value,
    documents_from_ground_truth,
    observation_from_dict,
    observation_to_dict,
    pareto_frontier,
    rotation_order,
    score_document,
    sha256_file,
)
from tests.benchmark.runtime_backend import (  # noqa: E402
    BenchmarkLlamaServerBackend,
    RuntimeCapabilities,
    ServerRuntimeConfig,
    benchmark_cache_paths,
    detect_runtime_capabilities,
)

BORDERLINE_RUNS = 10
RESOURCE_LIMIT_FAILURE_CLASSES = frozenset(
    {"resource_limit_confirmed", "resource_limit_suspected"}
)
SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}


class MemoryRecoveryError(RuntimeError):
    """The host did not return close enough to the invocation memory baseline."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--easy", type=Path)
    parser.add_argument("--medium", type=Path)
    parser.add_argument("--hard", type=Path)
    parser.add_argument("--ground-truth", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--top-values", type=int, default=DEFAULT_TOP_VALUES)
    parser.add_argument("--beam-width", type=int, default=DEFAULT_BEAM_WIDTH)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--no-dialog", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--stop-after", choices=("prompt", "stage-a", "stage-b"), default="stage-b")
    return parser.parse_args()


def _validate_cli(args: argparse.Namespace) -> None:
    if args.runs != 5:
        raise SystemExit("Il protocollo canonico usa esattamente --runs 5")
    if args.top_values < 1 or args.beam_width < 1:
        raise SystemExit("--top-values e --beam-width devono essere >= 1")
    if args.max_retries < 0:
        raise SystemExit("--max-retries deve essere >= 0")


def _select_file(title: str, filter_text: str) -> Path:
    try:
        from PySide6.QtWidgets import QApplication, QFileDialog
    except ImportError as exc:
        raise SystemExit("PySide6 necessario per i dialog file") from exc
    app = QApplication.instance() or QApplication([])
    filename, _ = QFileDialog.getOpenFileName(None, title, str(Path.home()), filter_text)
    if not filename:
        raise SystemExit(f"Selezione annullata: {title}")
    return Path(filename).expanduser().resolve()


def _resolve_paths(args: argparse.Namespace, state: dict[str, Any] | None) -> tuple[Path, Path, Path, Path]:
    if state is not None:
        stored = state["inputs"]
        return tuple(
            Path(value).expanduser().resolve()
            for value in (
                args.easy or stored["facile"]["path"],
                args.medium or stored["medio"]["path"],
                args.hard or stored["difficile"]["path"],
                args.ground_truth or stored["ground_truth"]["path"],
            )
        )  # type: ignore[return-value]
    if args.no_dialog and any(value is None for value in (args.easy, args.medium, args.hard, args.ground_truth)):
        raise SystemExit("Con --no-dialog specifica --easy --medium --hard --ground-truth")
    easy = args.easy.expanduser().resolve() if args.easy else _select_file("FACILE — PDF digitale", "PDF (*.pdf)")
    medium = args.medium.expanduser().resolve() if args.medium else _select_file("MEDIO — PDF scansione densa", "PDF (*.pdf)")
    hard = args.hard.expanduser().resolve() if args.hard else _select_file("DIFFICILE — manoscritto continuo", "Documenti (*.pdf *.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp *.gif)")
    truth = args.ground_truth.expanduser().resolve() if args.ground_truth else _select_file("GROUND TRUTH", "Markdown (*.md)")
    return easy, medium, hard, truth


def _input_metadata(documents: Sequence[BenchmarkDocument], truth_path: Path) -> dict[str, Any]:
    data = {
        doc.level: {"path": str(doc.path), "sha256": sha256_file(doc.path), "name": doc.path.name}
        for doc in documents
    }
    data["ground_truth"] = {"path": str(truth_path), "sha256": sha256_file(truth_path), "name": truth_path.name}
    return data


def _initial_state(inputs: dict[str, Any], args: argparse.Namespace, capabilities: RuntimeCapabilities) -> dict[str, Any]:
    return {
        "schema": CHECKPOINT_SCHEMA,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": inputs,
        "protocol": {
            "runs": args.runs,
            "borderline_runs": BORDERLINE_RUNS,
            "top_values": args.top_values,
            "beam_width": args.beam_width,
            "seed": BENCHMARK_SEED,
            "cache_prompt": False,
            "memory_isolation": MEMORY_ISOLATION_VERSION,
        },
        "runtime": {
            "llama_version": capabilities.version,
            "server_path": capabilities.server_path,
            "supported_variables": capabilities.supported,
        },
        "observations": [],
        "completed_stages": [],
    }


def _save_state(output_dir: Path, state: dict[str, Any]) -> None:
    atomic_write_json(output_dir / "checkpoint.json", state)


def _load_state(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "checkpoint.json"
    if not path.is_file():
        raise SystemExit(f"Checkpoint non trovato: {path}")
    state = json.loads(path.read_text(encoding="utf-8"))
    if int(state.get("schema", -1)) != CHECKPOINT_SCHEMA:
        raise SystemExit("Checkpoint di una versione precedente: avvia una nuova suite v2")
    return state


def _assert_inputs(state: dict[str, Any], inputs: dict[str, Any]) -> None:
    for key in (*LEVELS, "ground_truth"):
        if state["inputs"][key]["sha256"] != inputs[key]["sha256"]:
            raise SystemExit(f"Input modificato rispetto al checkpoint: {key}")


def _observations(state: dict[str, Any]) -> list[Observation]:
    return [observation_from_dict(item) for item in state.get("observations", [])]


def _successful(state: dict[str, Any], stage: str, config_id: str, run_index: int, level: str) -> Observation | None:
    for item in _observations(state):
        if item.key == (stage, config_id, run_index, level) and item.error is None:
            return item
    return None


def _memory_failure_class(memory: object) -> str | None:
    if not isinstance(memory, dict):
        return None
    if bool(memory.get("pressure_triggered")):
        return "resource_limit_confirmed"
    minimum = memory.get("mem_available_min_mib")
    if isinstance(minimum, (int, float)) and float(minimum) <= MEMORY_PRESSURE_FLOOR_MIB:
        return "resource_limit_confirmed"
    return None


def _observation_failure_class(observation: Observation) -> str | None:
    memory_class = _memory_failure_class(observation.metrics.get("memory"))
    if memory_class is not None:
        return memory_class

    recovery = observation.metrics.get("runtime_recovery")
    if isinstance(recovery, dict):
        failure_class = recovery.get("failure_class")
        if isinstance(failure_class, str) and failure_class:
            return failure_class

    direct = observation.metrics.get("failure_class")
    return direct if isinstance(direct, str) and direct else None


def _terminal_config_failure(
    state: dict[str, Any],
    stage: str,
    config_id: str,
) -> dict[str, Any] | None:
    failures = state.get("terminal_config_failures")
    if not isinstance(failures, dict):
        return None
    stage_failures = failures.get(stage)
    if not isinstance(stage_failures, dict):
        return None
    payload = stage_failures.get(config_id)
    return dict(payload) if isinstance(payload, dict) else None


def _record_terminal_config_failure(
    state: dict[str, Any],
    stage: str,
    config_id: str,
    payload: dict[str, Any],
) -> None:
    failures = state.get("terminal_config_failures")
    root = dict(failures) if isinstance(failures, dict) else {}
    stage_failures = root.get(stage)
    by_config = dict(stage_failures) if isinstance(stage_failures, dict) else {}
    by_config[config_id] = dict(payload)
    root[stage] = by_config
    state["terminal_config_failures"] = root


def _historical_resource_limit_failure(
    state: dict[str, Any],
    stage: str,
    config_id: str,
) -> dict[str, Any] | None:
    for observation in reversed(_observations(state)):
        if observation.stage != stage or observation.config_id != config_id:
            continue
        if observation.error is None:
            continue
        failure_class = _observation_failure_class(observation)
        if failure_class not in RESOURCE_LIMIT_FAILURE_CLASSES:
            continue
        return {
            "failure_class": failure_class,
            "source": "historical_observation",
            "run_index": observation.run_index,
            "level": observation.level,
            "error": observation.error,
            "memory": observation.metrics.get("memory"),
            "runtime_recovery": observation.metrics.get("runtime_recovery"),
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
        }
    return None


def _attempt_failure_class(
    observation: Observation,
    diagnostics: object,
) -> str:
    memory_class = _memory_failure_class(observation.metrics.get("memory"))
    if memory_class is not None:
        return memory_class
    if bool(getattr(diagnostics, "suspected_oom", False)):
        return (
            "resource_limit_confirmed"
            if bool(getattr(diagnostics, "process_exited", False))
            else "resource_limit_suspected"
        )
    if bool(getattr(diagnostics, "process_exited", False)):
        return "server_crash"
    return "request_error"

def _upsert(state: dict[str, Any], observation: Observation) -> None:
    rows = list(state.get("observations", []))
    payload = observation_to_dict(observation)
    key = observation.key
    for index, row in enumerate(rows):
        old = observation_from_dict(row)
        if old.key == key:
            rows[index] = payload
            break
    else:
        rows.append(payload)
    state["observations"] = rows


def _make_warmup_image(output_dir: Path) -> Path:
    path = output_dir / ".warmup.png"
    if not path.exists():
        image = Image.new("RGB", (512, 256), "white")
        draw = ImageDraw.Draw(image)
        draw.text((32, 64), "GLM OCR benchmark warmup 0123456789", fill="black")
        image.save(path)
    return path


def _flatten(page_metrics: Sequence[dict[str, Any]]) -> dict[str, float]:
    keys = ("request_elapsed_s", "render_elapsed_s", "preprocess_elapsed_s", "encoded_bytes", "cache_n")
    return {key: sum(float(item.get(key, 0.0) or 0.0) for item in page_metrics) for key in keys}


def _run_document(
    stage: str,
    config: PipelineConfig,
    run_index: int,
    document: BenchmarkDocument,
    backend: BenchmarkLlamaServerBackend,
    output_dir: Path,
    warm_rss_mib: float | None,
) -> Observation:
    started = time.perf_counter()
    pages: list[dict[str, Any]] = []
    sampler = MemorySampler(
        backend.process_pid,
        critical_available_mib=MEMORY_PRESSURE_FLOOR_MIB,
        on_critical=lambda _snapshot: backend.shutdown(),
    )
    try:
        with sampler:
            if document.is_pdf:
                output, _ = ocr_pdf(
                    document.path,
                    backend.server_url,
                    preprocessing_mode=config.preprocessing_mode,
                    emit_events=False,
                    prompt=config.prompt,
                    pdf_dpi=config.pdf_dpi,
                    max_image_dim=config.max_image_dim,
                    jpeg_quality=config.jpeg_quality,
                    cache_prompt=False,
                    page_metrics=pages,
                )
            else:
                metrics: dict[str, Any] = {}
                output, _ = ocr_single_image(
                    document.path,
                    backend.server_url,
                    preprocessing_mode=config.preprocessing_mode,
                    prompt=config.prompt,
                    max_image_dim=config.max_image_dim,
                    jpeg_quality=config.jpeg_quality,
                    cache_prompt=False,
                    metrics=metrics,
                )
                pages.append(metrics)
        elapsed = time.perf_counter() - started
        observation_metrics = {
            "pages": pages,
            "totals": _flatten(pages),
            "server_rss_mib": warm_rss_mib,
            "memory": sampler.to_dict(),
        }
        cer, wer, accuracy, segment_scores = score_document(document, output)
        path = output_dir / "outputs" / stage / config.name / document.level / f"run-{run_index:02d}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output.rstrip() + "\n", encoding="utf-8")
        return Observation(
            stage=stage,
            config_id=config.name,
            run_index=run_index,
            level=document.level,
            elapsed_s=elapsed,
            cer=cer,
            wer=wer,
            char_accuracy=accuracy,
            output_file=str(path.relative_to(output_dir)),
            metrics=observation_metrics,
            segment_scores=segment_scores,
        )
    except Exception as exc:
        return Observation(
            stage,
            config.name,
            run_index,
            document.level,
            time.perf_counter() - started,
            None,
            None,
            None,
            "",
            {
                "pages": pages,
                "totals": _flatten(pages),
                "server_rss_mib": warm_rss_mib,
                "memory": sampler.to_dict(),
            },
            {},
            str(exc),
        )


def _memory_cleanup_paths(documents: Sequence[BenchmarkDocument]) -> tuple[Path, ...]:
    return tuple(benchmark_cache_paths()) + tuple(doc.path for doc in documents)


def _settle_memory(
    paths: Sequence[Path],
    *,
    announce: bool = True,
    target_available_mib: float | None = None,
    enforce_recovery: bool = False,
) -> dict[str, Any]:
    report = settle_benchmark_memory(
        paths,
        target_available_mib=target_available_mib,
    )
    stabilization = report.get("stabilization")
    recovery = report.get("recovery")
    if announce and isinstance(stabilization, dict):
        final = stabilization.get("final")
        if isinstance(final, dict):
            stable = "yes" if stabilization.get("stable") else "no"
            suffix = ""
            if isinstance(recovery, dict):
                suffix = f" recovered={'yes' if recovery.get('recovered') else 'no'}"
            print(
                "  [memory] "
                f"available={float(final['mem_available_mib']):.0f} MiB "
                f"cached={float(final['cached_mib']):.0f} MiB "
                f"stable={stable}{suffix}"
            )
        elif stabilization.get("supported") is False:
            print("  [memory] host telemetry unavailable; isolation is advisory only")
    if enforce_recovery and isinstance(recovery, dict) and recovery.get("supported"):
        if not recovery.get("recovered"):
            final = recovery.get("final")
            available = (
                float(final.get("mem_available_mib", 0.0))
                if isinstance(final, dict)
                else 0.0
            )
            threshold = float(recovery.get("threshold_available_mib", 0.0))
            raise MemoryRecoveryError(
                "host memory did not recover after llama-server shutdown: "
                f"available={available:.0f} MiB, required>={threshold:.0f} MiB"
            )
    return report


def _recover_memory(
    paths: Sequence[Path],
    args: argparse.Namespace,
    *,
    announce: bool = False,
) -> dict[str, Any]:
    target = getattr(args, "memory_baseline_mib", None)
    return _settle_memory(
        paths,
        announce=announce,
        target_available_mib=target,
        enforce_recovery=target is not None,
    )


def _start_backend(
    config: PipelineConfig,
    output_dir: Path,
    args: argparse.Namespace,
    cleanup_paths: Sequence[Path],
) -> tuple[BenchmarkLlamaServerBackend | None, float | None, str | None]:
    startup_error: str | None = None
    for attempt in range(args.max_retries + 1):
        backend = BenchmarkLlamaServerBackend(config.runtime)
        try:
            backend.initialize()
            ocr_single_image(
                _make_warmup_image(output_dir),
                backend.server_url,
                preprocessing_mode="none",
                prompt=config.prompt,
                max_image_dim=min(config.max_image_dim, 1024),
                jpeg_quality=config.jpeg_quality,
                cache_prompt=False,
            )
            return backend, process_rss_mib(backend.process_pid), None
        except KeyboardInterrupt:
            backend.shutdown()
            raise
        except Exception as exc:
            diagnostics = backend.failure_diagnostics()
            suffix = " [suspected memory exhaustion]" if diagnostics.suspected_oom else ""
            startup_error = f"{exc}{suffix}"
            backend.shutdown()
            if attempt < args.max_retries:
                print(
                    f"  [server] retry startup {attempt + 1}/{args.max_retries}: "
                    f"{startup_error}"
                )
                _recover_memory(cleanup_paths, args, announce=False)
                time.sleep(1.0)
    return None, None, startup_error


def _recovery_failure_class(
    observation: Observation,
    attempts: Sequence[dict[str, Any]],
) -> str | None:
    if not attempts:
        return None
    if observation.error is None:
        return "recovered"

    classes = [
        str(item.get("failure_class"))
        for item in attempts
        if item.get("failure_class")
    ]
    if "resource_limit_confirmed" in classes:
        return "resource_limit_confirmed"
    if "resource_limit_suspected" in classes:
        return "resource_limit_suspected"
    if "server_crash" in classes:
        return "server_crash"
    return classes[-1] if classes else "request_error"


def _run_document_with_recovery(
    stage: str,
    config: PipelineConfig,
    run_index: int,
    document: BenchmarkDocument,
    backend: BenchmarkLlamaServerBackend,
    warm_rss_mib: float | None,
    output_dir: Path,
    args: argparse.Namespace,
    cleanup_paths: Sequence[Path],
) -> tuple[Observation, BenchmarkLlamaServerBackend | None, float | None]:
    attempts: list[dict[str, Any]] = []
    observation: Observation | None = None
    current_backend: BenchmarkLlamaServerBackend | None = backend
    current_rss = warm_rss_mib
    try:
        for attempt in range(args.max_retries + 1):
            assert current_backend is not None
            observation = _run_document(
                stage,
                config,
                run_index,
                document,
                current_backend,
                output_dir,
                current_rss,
            )

            memory_class = _memory_failure_class(observation.metrics.get("memory"))
            if observation.error is None and memory_class is None:
                break
            if observation.error is None and memory_class is not None:
                observation.error = (
                    "critical host memory pressure: "
                    f"MemAvailable <= {MEMORY_PRESSURE_FLOOR_MIB:.0f} MiB"
                )

            diagnostics = current_backend.failure_diagnostics()
            failure_class = _attempt_failure_class(observation, diagnostics)
            attempt_record: dict[str, Any] = {
                "attempt": attempt + 1,
                "error": observation.error,
                "failure_class": failure_class,
                "server": diagnostics.to_dict(),
                "memory": observation.metrics.get("memory"),
            }
            attempts.append(attempt_record)

            # A resource-limit signal is terminal for this configuration. A
            # second identical attempt only increases the chance that the host
            # OOM killer terminates unrelated processes.
            if failure_class in RESOURCE_LIMIT_FAILURE_CLASSES:
                break
            if attempt >= args.max_retries:
                break

            if diagnostics.process_exited:
                print(
                    f"      {document.level}: server terminated; "
                    f"clean restart {attempt + 1}/{args.max_retries}"
                )
                current_backend.shutdown()
                settle_report = _recover_memory(cleanup_paths, args, announce=False)
                attempt_record["memory_settle"] = settle_report
                restarted, restarted_rss, restart_error = _start_backend(
                    config,
                    output_dir,
                    args,
                    cleanup_paths,
                )
                if restarted is None:
                    attempt_record["restart_error"] = restart_error
                    observation.error = (
                        f"{observation.error}; server restart failed: {restart_error}"
                    )
                    current_backend = None
                    break
                current_backend = restarted
                current_rss = restarted_rss
            else:
                print(
                    f"      {document.level}: retry "
                    f"{attempt + 1}/{args.max_retries}"
                )

        assert observation is not None
        if attempts:
            observation.metrics["runtime_recovery"] = {
                "attempts": attempts,
                "recovered": observation.error is None,
                "failure_class": _recovery_failure_class(observation, attempts),
            }
        return observation, current_backend, current_rss
    except BaseException:
        if current_backend is not None:
            current_backend.shutdown()
        raise


def _record_startup_failure(stage: str, config: PipelineConfig, levels: Sequence[str], target_runs: int, state: dict[str, Any], output_dir: Path, message: str) -> None:
    for run_index in range(1, target_runs + 1):
        for level in levels:
            if _successful(state, stage, config.name, run_index, level) is None:
                _upsert(state, Observation(stage, config.name, run_index, level, 0.0, None, None, None, "", {"startup_failure": True}, {}, message))
    _save_state(output_dir, state)


def _run_config(
    stage: str,
    config: PipelineConfig,
    levels: Sequence[str],
    documents: Sequence[BenchmarkDocument],
    output_dir: Path,
    state: dict[str, Any],
    args: argparse.Namespace,
    *,
    target_runs: int = DEFAULT_RUNS,
) -> None:
    terminal = _terminal_config_failure(state, stage, config.name)
    if terminal is None:
        historical = _historical_resource_limit_failure(state, stage, config.name)
        if historical is not None:
            _record_terminal_config_failure(state, stage, config.name, historical)
            _save_state(output_dir, state)
            terminal = historical
    if terminal is not None:
        failure_class = terminal.get("failure_class", "resource_limit")
        print(f"  [skip] {config.name}: terminal {failure_class}")
        return

    pending = [
        (run_index, level)
        for run_index in range(1, target_runs + 1)
        for level in levels
        if _successful(state, stage, config.name, run_index, level) is None
    ]
    if not pending:
        print(f"  [skip] {config.name}: checkpoint completo ({target_runs} run)")
        return

    docs = {doc.level: doc for doc in documents}
    cleanup_paths = _memory_cleanup_paths(documents)
    backend: BenchmarkLlamaServerBackend | None = None
    rss: float | None = None

    _recover_memory(cleanup_paths, args, announce=True)
    print(f"  [server] {config.name} · {config.runtime.signature()}")

    try:
        backend, rss, startup_error = _start_backend(
            config,
            output_dir,
            args,
            cleanup_paths,
        )
        if backend is None:
            message = f"runtime profile unavailable: {startup_error}"
            print(f"  [server] FAIL: {message}")
            _record_startup_failure(stage, config, levels, target_runs, state, output_dir, message)
            if startup_error and "[suspected memory exhaustion]" in startup_error:
                _record_terminal_config_failure(
                    state,
                    stage,
                    config.name,
                    {
                        "failure_class": "resource_limit_suspected",
                        "source": "startup",
                        "error": startup_error,
                        "recorded_at": datetime.now().isoformat(timespec="seconds"),
                    },
                )
                _save_state(output_dir, state)
            return

        for run_index in range(1, target_runs + 1):
            order = tuple(level for level in rotation_order(run_index) if level in levels)
            print(f"    run {run_index}/{target_runs}: {' -> '.join(order)}")
            for level in order:
                if _successful(state, stage, config.name, run_index, level) is not None:
                    continue

                if backend is None or not backend.is_server_running:
                    if backend is not None:
                        backend.shutdown()
                    _recover_memory(cleanup_paths, args, announce=False)
                    backend, rss, startup_error = _start_backend(
                        config,
                        output_dir,
                        args,
                        cleanup_paths,
                    )
                    if backend is None:
                        observation = Observation(
                            stage=stage,
                            config_id=config.name,
                            run_index=run_index,
                            level=level,
                            elapsed_s=0.0,
                            cer=None,
                            wer=None,
                            char_accuracy=None,
                            output_file="",
                            metrics={
                                "startup_failure": True,
                                "failure_class": "server_restart_failed",
                            },
                            segment_scores={},
                            error=f"server restart failed: {startup_error}",
                        )
                        _upsert(state, observation)
                        _save_state(output_dir, state)
                        print(f"      {level}: ERRORE {observation.error}")
                        continue

                observation, backend, rss = _run_document_with_recovery(
                    stage,
                    config,
                    run_index,
                    docs[level],
                    backend,
                    rss,
                    output_dir,
                    args,
                    cleanup_paths,
                )
                _upsert(state, observation)
                _save_state(output_dir, state)
                failure_class = _observation_failure_class(observation)

                if failure_class in RESOURCE_LIMIT_FAILURE_CLASSES:
                    terminal_payload = {
                        "failure_class": failure_class,
                        "source": "current_observation",
                        "run_index": run_index,
                        "level": level,
                        "error": observation.error,
                        "memory": observation.metrics.get("memory"),
                        "runtime_recovery": observation.metrics.get("runtime_recovery"),
                        "recorded_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    _record_terminal_config_failure(
                        state,
                        stage,
                        config.name,
                        terminal_payload,
                    )
                    _save_state(output_dir, state)
                    if backend is not None:
                        backend.shutdown()
                        backend = None
                    print(
                        f"      {level}: RESOURCE LIMIT [{failure_class}] — "
                        "configurazione scartata"
                    )
                    return

                if observation.error:
                    suffix = f" [{failure_class}]" if failure_class else ""
                    print(f"      {level}: ERRORE {observation.error}{suffix}")
                else:
                    memory = observation.metrics.get("memory")
                    memory_suffix = ""
                    if isinstance(memory, dict):
                        minimum = memory.get("mem_available_min_mib")
                        peak = memory.get("server_rss_peak_mib")
                        if isinstance(minimum, (int, float)):
                            memory_suffix += f" mem_avail_min={minimum:.0f}MiB"
                        if isinstance(peak, (int, float)):
                            memory_suffix += f" server_rss_peak={peak:.0f}MiB"
                    print(
                        f"      {level}: "
                        f"acc={100 * float(observation.char_accuracy):.3f}% "
                        f"time={observation.elapsed_s:.2f}s "
                        f"cache_n={int(observation.metrics['totals']['cache_n'])}"
                        f"{memory_suffix}"
                    )
                    if level == "difficile":
                        parts = " · ".join(
                            f"{name}="
                            f"{100 * observation.segment_scores[name]['char_accuracy']:.2f}%"
                            for name in HANDWRITING_SEGMENTS
                        )
                        print(f"        {parts}")
    finally:
        if backend is not None:
            backend.shutdown()
        _recover_memory(cleanup_paths, args, announce=False)


def _aggregate(state: dict[str, Any], config: PipelineConfig, levels: Sequence[str], run_count: int) -> ConfigAggregate:
    return aggregate_config(_observations(state), config_id=config.name, levels=levels, expected_runs=run_count)


def _serialize_config(config: PipelineConfig) -> dict[str, Any]:
    return asdict(config)


def _deserialize_config(payload: dict[str, Any]) -> PipelineConfig:
    data = dict(payload)
    runtime = ServerRuntimeConfig(**dict(data.pop("runtime"))).resolved()
    return PipelineConfig(runtime=runtime, **data)


def _gate_and_retest(stage: str, configs: Sequence[PipelineConfig], levels: Sequence[str], documents: Sequence[BenchmarkDocument], output_dir: Path, state: dict[str, Any], args: argparse.Namespace) -> tuple[list[ConfigAggregate], dict[str, Any]]:
    initial = [_aggregate(state, config, levels, args.runs) for config in configs]
    try:
        reference = quality_reference(initial)
    except ValueError:
        report: dict[str, Any] = {}
        for aggregate in initial:
            terminal = _terminal_config_failure(state, stage, aggregate.config_id)
            report[aggregate.config_id] = {
                "status": "FAIL",
                "reasons": [
                    str(terminal.get("failure_class"))
                    if terminal is not None
                    else "no valid cache-free configs"
                ],
                "runs": args.runs,
                "terminal_failure": terminal,
            }
        return initial, report

    gates = {aggregate.config_id: classify_quality(aggregate, reference) for aggregate in initial}
    borderline_ids = {
        config_id
        for config_id, gate in gates.items()
        if gate.status == "BORDERLINE"
        and _terminal_config_failure(state, stage, config_id) is None
    }
    if borderline_ids:
        print(f"  [quality] BORDERLINE -> altre 5 run: {sorted(borderline_ids)}")
        for config in configs:
            if config.name in borderline_ids:
                _run_config(stage, config, levels, documents, output_dir, state, args, target_runs=BORDERLINE_RUNS)

    aggregates = [
        _aggregate(state, config, levels, BORDERLINE_RUNS if config.name in borderline_ids else args.runs)
        for config in configs
    ]
    try:
        final_reference = quality_reference(aggregates)
        final_gates = {aggregate.config_id: classify_quality(aggregate, final_reference) for aggregate in aggregates}
    except ValueError:
        final_gates = {
            aggregate.config_id: type(
                "Gate",
                (),
                {"status": "FAIL", "reasons": ("no valid cache-free configs",)},
            )()
            for aggregate in aggregates
        }

    report = {}
    for aggregate in aggregates:
        terminal = _terminal_config_failure(state, stage, aggregate.config_id)
        if terminal is not None:
            report[aggregate.config_id] = {
                "status": "FAIL",
                "reasons": [str(terminal.get("failure_class", "resource_limit"))],
                "runs": BORDERLINE_RUNS if aggregate.config_id in borderline_ids else args.runs,
                "terminal_failure": terminal,
            }
            continue
        report[aggregate.config_id] = {
            "status": final_gates[aggregate.config_id].status,
            "reasons": list(final_gates[aggregate.config_id].reasons),
            "runs": BORDERLINE_RUNS if aggregate.config_id in borderline_ids else args.runs,
        }
    return aggregates, report


def _prompt_stage(documents: Sequence[BenchmarkDocument], output_dir: Path, state: dict[str, Any], args: argparse.Namespace) -> str:
    print("\n=== PROMPT SHOOTOUT ===")
    configs = prompt_configs()
    for config in configs:
        _run_config("prompt", config, LEVELS, documents, output_dir, state, args)
    aggregates, gates = _gate_and_retest("prompt", configs, LEVELS, documents, output_dir, state, args)
    try:
        winner = fastest_quality_equivalent(aggregates)
    except ValueError:
        valid = [aggregate for aggregate in aggregates if aggregate.valid and aggregate.cache_n_total == 0]
        if not valid:
            raise RuntimeError("Entrambi i prompt sono invalidi")
        winner = max(valid, key=lambda aggregate: (aggregate.macro_char_accuracy, -aggregate.macro_elapsed_s))
        print("[prompt] Nessun PASS simultaneo ai gate; fallback alla migliore macro accuracy")
    config = next(item for item in configs if item.name == winner.config_id)
    state["chosen_prompt"] = config.prompt
    state["prompt_report"] = gates
    state["completed_stages"].append("prompt") if "prompt" not in state["completed_stages"] else None
    _save_state(output_dir, state)
    print(f"[prompt] scelto: {config.prompt}")
    return config.prompt


def _variable_baseline(configs: Sequence[PipelineConfig], variable: str, prompt: str) -> PipelineConfig:
    _ = configs
    return production_baseline(prompt, name=f"a_{variable}_baseline")


def _stage_a(prompt: str, capabilities: RuntimeCapabilities, documents: Sequence[BenchmarkDocument], output_dir: Path, state: dict[str, Any], args: argparse.Namespace) -> dict[str, list[Any]]:
    print("\n=== STAGE A — OFAT PIPELINE + LLAMA RUNTIME ===")
    groups = stage_a_groups(prompt, capabilities)
    selected: dict[str, list[Any]] = {}
    reports: dict[str, Any] = {}
    speed_gain: dict[str, float] = {}

    for variable, raw_configs in groups.items():
        levels = affected_levels(variable, documents)
        baseline = _variable_baseline(raw_configs, variable, prompt)
        configs: list[PipelineConfig] = []
        for config in raw_configs:
            configs.append(baseline if config.name == "stage_a_baseline" else config)
        dedup: dict[str, PipelineConfig] = {config.name: config for config in configs}
        configs = list(dedup.values())
        print(f"\n[Stage A] {variable} · {len(configs)} valori · {','.join(levels)}")
        for config in configs:
            print(f"  {config.name}: value={config_variable_value(config, variable)!r}")
            _run_config("stage_a", config, levels, documents, output_dir, state, args)

        aggregates, gate_report = _gate_and_retest("stage_a", configs, levels, documents, output_dir, state, args)
        pairs = [(config_variable_value(config, variable), aggregate) for config, aggregate in zip(configs, aggregates)]
        chosen, _ = select_fastest_quality_gated_values(pairs, top_n=args.top_values)
        if not chosen:
            raise RuntimeError(f"Nessun valore supera i quality gate per {variable}")
        selected[variable] = chosen
        baseline_aggregate = next((aggregate for config, aggregate in zip(configs, aggregates) if config.name == baseline.name), None)
        passing = [aggregate for aggregate in aggregates if gate_report[aggregate.config_id]["status"] == "PASS"]
        if baseline_aggregate and passing and baseline_aggregate.valid:
            fastest = min(passing, key=lambda aggregate: aggregate.macro_elapsed_s)
            speed_gain[variable] = baseline_aggregate.macro_elapsed_s / fastest.macro_elapsed_s
        else:
            speed_gain[variable] = 1.0
        reports[variable] = [
            {
                "value": config_variable_value(config, variable),
                "config": _serialize_config(config),
                "aggregate": _aggregate_dict(aggregate),
                "gate": gate_report[aggregate.config_id],
            }
            for config, aggregate in zip(configs, aggregates)
        ]
        print(f"  -> finalisti: {chosen}")

    order = sorted(selected, key=lambda variable: (-speed_gain.get(variable, 1.0), variable))
    state["stage_a_selected"] = selected
    state["stage_a_report"] = reports
    state["stage_a_variable_order"] = order
    state["stage_a_speed_gain"] = speed_gain
    if "stage_a" not in state["completed_stages"]:
        state["completed_stages"].append("stage_a")
    _save_state(output_dir, state)
    print(f"[Stage A] ordine beam per speed potential: {order}")
    return selected


def _aggregate_dict(aggregate: ConfigAggregate) -> dict[str, Any]:
    return asdict(aggregate)


def _stage_b(prompt: str, selected: dict[str, Sequence[Any]], documents: Sequence[BenchmarkDocument], output_dir: Path, state: dict[str, Any], args: argparse.Namespace) -> None:
    print("\n=== STAGE B — QUALITY-GATED BEAM SEARCH ===")
    order = list(state.get("stage_a_variable_order") or selected.keys())
    completed_steps = dict(state.get("stage_b_steps") or {})
    beam = [production_baseline(prompt, name="beam_seed")]

    for step, variable in enumerate(order, start=1):
        step_key = f"{step:02d}_{variable}"
        if step_key in completed_steps:
            beam = [_deserialize_config(item) for item in completed_steps[step_key]["beam"]]
            print(f"[Stage B] resume {step_key}: beam={len(beam)}")
            continue

        values = list(selected[variable])
        current_values = [config_variable_value(config, variable) for config in beam]
        for value in current_values:
            if value not in values:
                values.append(value)
        configs = beam_expand(beam, variable, values, step=step)
        rng = random.Random(BENCHMARK_SEED + step)
        rng.shuffle(configs)
        stage_name = f"stage_b_{step:02d}"
        print(f"\n[Stage B {step}/{len(order)}] {variable}: {len(configs)} candidati")
        for config in configs:
            _run_config(stage_name, config, LEVELS, documents, output_dir, state, args)
        aggregates, gate_report = _gate_and_retest(stage_name, configs, LEVELS, documents, output_dir, state, args)
        passing = [
            (config, aggregate)
            for config, aggregate in zip(configs, aggregates)
            if gate_report[aggregate.config_id]["status"] == "PASS"
        ]
        passing.sort(key=lambda item: (item[1].macro_elapsed_s, -item[1].macro_char_accuracy))
        if not passing:
            print(f"  [Stage B] nessun PASS introducendo {variable}; mantengo il beam precedente")
        else:
            beam = [replace(config, name=f"beam{step:02d}_{index}_{config.signature()}") for index, (config, _aggregate) in enumerate(passing[: args.beam_width], start=1)]
        completed_steps[step_key] = {
            "variable": variable,
            "values": values,
            "gate_report": gate_report,
            "beam": [_serialize_config(config) for config in beam],
        }
        state["stage_b_steps"] = completed_steps
        _save_state(output_dir, state)
        print(f"  -> beam sopravvissuto: {len(beam)}")

    _final_confirmation(prompt, beam, documents, output_dir, state, args)
    if "stage_b" not in state["completed_stages"]:
        state["completed_stages"].append("stage_b")
    _save_state(output_dir, state)


def _final_confirmation(prompt: str, beam: Sequence[PipelineConfig], documents: Sequence[BenchmarkDocument], output_dir: Path, state: dict[str, Any], args: argparse.Namespace) -> None:
    baseline_start = production_baseline(prompt, name="final_baseline_start")
    baseline_end = production_baseline(prompt, name="final_baseline_end")
    finalists = [replace(config, name=f"final_{index}_{config.signature()}") for index, config in enumerate(beam, start=1)]
    configs = [baseline_start, *finalists, baseline_end]
    print(f"\n=== FINAL CONFIRMATION — {len(finalists)} profili + 2 baseline ===")
    for config in configs:
        _run_config("final", config, LEVELS, documents, output_dir, state, args)
    aggregates, gate_report = _gate_and_retest("final", configs, LEVELS, documents, output_dir, state, args)
    finalist_pairs = [(config, aggregate) for config, aggregate in zip(configs, aggregates) if config not in (baseline_start, baseline_end)]
    valid_finalists = [aggregate for config, aggregate in finalist_pairs if gate_report[aggregate.config_id]["status"] == "PASS"]
    if not valid_finalists:
        raise RuntimeError("Nessun finalista supera i quality gate nella conferma")
    recommendation = fastest_quality_equivalent(valid_finalists)
    _export_results(output_dir, finalist_pairs, baseline_start, baseline_end, aggregates, recommendation, gate_report, state)


def _baseline_times(start: ConfigAggregate, end: ConfigAggregate) -> dict[str, float]:
    result: dict[str, float] = {}
    for level in LEVELS:
        values = [aggregate.documents[level].trimmed_elapsed_s for aggregate in (start, end) if aggregate.valid and level in aggregate.documents]
        if values:
            result[level] = sum(values) / len(values)
    return result


def _ranking_row(config: PipelineConfig, aggregate: ConfigAggregate, baseline: dict[str, float]) -> dict[str, Any]:
    ratios = [baseline[level] / doc.trimmed_elapsed_s for level, doc in aggregate.documents.items() if level in baseline and doc.valid]
    row: dict[str, Any] = {
        "config_id": aggregate.config_id,
        "macro_char_accuracy_pct": aggregate.macro_char_accuracy * 100,
        "macro_cer": aggregate.macro_cer,
        "macro_wer": aggregate.macro_wer,
        "macro_elapsed_s": aggregate.macro_elapsed_s,
        "speedup_vs_baseline": sum(ratios) / len(ratios) if ratios else 0.0,
        "mean_encoded_kib": aggregate.mean_encoded_bytes / 1024,
        "prompt": config.prompt,
        "preprocessing_mode": config.preprocessing_mode,
        "pdf_dpi": config.pdf_dpi,
        "max_image_dim": config.max_image_dim,
        "jpeg_quality": config.jpeg_quality,
    }
    row.update({f"runtime_{key}": value for key, value in config.runtime.to_dict().items()})
    for name in HANDWRITING_SEGMENTS:
        score = aggregate.hard_segments.get(name)
        row[f"hard_{name}_accuracy_pct"] = score.char_accuracy * 100 if score else ""
        row[f"hard_{name}_wer"] = score.wer if score else ""
    return row


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _export_results(output_dir: Path, finalist_pairs: Sequence[tuple[PipelineConfig, ConfigAggregate]], baseline_start_config: PipelineConfig, baseline_end_config: PipelineConfig, all_aggregates: Sequence[ConfigAggregate], recommendation: ConfigAggregate, gate_report: dict[str, Any], state: dict[str, Any]) -> None:
    aggregate_map = {aggregate.config_id: aggregate for aggregate in all_aggregates}
    start = aggregate_map[baseline_start_config.name]
    end = aggregate_map[baseline_end_config.name]
    baseline = _baseline_times(start, end)
    valid_pairs = [(config, aggregate) for config, aggregate in finalist_pairs if aggregate.valid and aggregate.cache_n_total == 0]
    accuracy = sorted(valid_pairs, key=lambda item: (-item[1].macro_char_accuracy, item[1].macro_elapsed_s))
    speed = sorted(valid_pairs, key=lambda item: (item[1].macro_elapsed_s, -item[1].macro_char_accuracy))
    frontier_ids = {aggregate.config_id for aggregate in pareto_frontier([aggregate for _config, aggregate in valid_pairs])}
    rows_accuracy = [_ranking_row(config, aggregate, baseline) for config, aggregate in accuracy]
    rows_speed = [_ranking_row(config, aggregate, baseline) for config, aggregate in speed]
    _write_csv(output_dir / "ranking_accuracy.csv", rows_accuracy)
    _write_csv(output_dir / "ranking_speed.csv", rows_speed)
    _write_csv(output_dir / "pareto.csv", [row for row in rows_accuracy if row["config_id"] in frontier_ids])
    pass_ids = {config_id for config_id, gate in gate_report.items() if gate["status"] == "PASS"}
    _write_csv(output_dir / "ranking_recommended.csv", [row for row in rows_speed if row["config_id"] in pass_ids])

    config_map = {config.name: config for config, _aggregate in valid_pairs}
    recommended_config = config_map[recommendation.config_id]
    recommended_row = _ranking_row(recommended_config, recommendation, baseline)
    state["final_summary"] = {
        "recommended_config": _serialize_config(recommended_config),
        "recommended_metrics": recommended_row,
        "baseline_document_times_s": baseline,
        "pareto_config_ids": sorted(frontier_ids),
        "quality_gate": gate_report,
    }
    _save_state(output_dir, state)

    lines = [
        "# GLM OCR canonical real-world benchmark v2",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Recommendation",
        "",
        f"- Config: `{recommendation.config_id}`",
        f"- Macro character accuracy: {recommended_row['macro_char_accuracy_pct']:.4f}%",
        f"- Mean document time: {recommended_row['macro_elapsed_s']:.3f}s",
        f"- Speedup vs production baseline: {recommended_row['speedup_vs_baseline']:.3f}x",
        "",
        "## Handwriting breakdown (single OCR request, continuous context)",
        "",
    ]
    for name in HANDWRITING_SEGMENTS:
        lines.append(f"- {name.upper()}: {recommended_row[f'hard_{name}_accuracy_pct']:.4f}%")
    lines.extend(["", "## Runtime", ""])
    for key, value in recommended_config.runtime.to_dict().items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "No absolute handwriting adequacy threshold is imposed: the report exposes measured capability instead of inventing one.", ""])
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def _write_results(output_dir: Path, state: dict[str, Any]) -> None:
    payload = dict(state)
    payload["checkpoint_file"] = "checkpoint.json"
    atomic_write_json(output_dir / "results.json", payload)


def _print_plan(args: argparse.Namespace, capabilities: RuntimeCapabilities) -> None:
    groups = stage_a_groups("OCR", capabilities)
    stage_a_configs_count = sum(len(configs) for configs in groups.values())
    prompt_requests = 2 * args.runs * len(LEVELS)
    stage_a_requests = stage_a_configs_count * args.runs * len(LEVELS)
    variables = len(groups)
    first = min(args.top_values + 1, args.beam_width + 1)
    beam_configs = first + max(0, variables - 1) * args.beam_width * (args.top_values + 1)
    stage_b_requests = beam_configs * args.runs * len(LEVELS)
    final_requests = (args.beam_width + 2) * args.runs * len(LEVELS)
    print("\n[Piano massimo indicativo]")
    print(f"  runtime: {capabilities.version}")
    print(f"  variabili Stage A: {variables} ({', '.join(groups)})")
    print(f"  prompt: ~{prompt_requests} OCR")
    print(f"  Stage A: <= {stage_a_requests} OCR")
    print(f"  Stage B beam: <= {stage_b_requests} OCR")
    print(f"  conferma finale: <= {final_requests} OCR")
    print("  Le configurazioni BORDERLINE ricevono automaticamente altre 5 run; il totale reale può quindi aumentare.")


def main() -> int:
    args = parse_args()
    _validate_cli(args)
    capabilities = detect_runtime_capabilities()

    if args.resume:
        output_dir = args.resume.expanduser().resolve()
        state = _load_state(output_dir)
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = (args.output_dir or Path("benchmark-results") / f"realworld-v2-{timestamp}").expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        state = None

    easy, medium, hard, truth_path = _resolve_paths(args, state)
    if easy.suffix.lower() != ".pdf" or medium.suffix.lower() != ".pdf" or hard.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise SystemExit("FACILE/MEDIO devono essere PDF; DIFFICILE deve essere PDF o immagine supportata")
    truth = load_ground_truth(truth_path)
    documents = documents_from_ground_truth(easy, medium, hard, truth)
    inputs = _input_metadata(documents, truth_path)

    if state is None:
        state = _initial_state(inputs, args, capabilities)
        _save_state(output_dir, state)
        atomic_write_json(output_dir / "inputs.json", inputs)
    else:
        _assert_inputs(state, inputs)
        if state["protocol"]["runs"] != args.runs or state["protocol"]["beam_width"] != args.beam_width:
            raise SystemExit("--runs/--beam-width devono coincidere col checkpoint")

    print("GLM OCR — canonical real-world benchmark v2")
    print(f"Output: {output_dir}")
    for doc in documents:
        print(f"  {doc.level.upper():10s} {doc.path.name} {inputs[doc.level]['sha256'][:12]}...")
    print("  DIFFICILE: singolo OCR con scoring MAIUSCOLO / SCRIPT / CORSIVO")
    unsupported = [key for key, value in capabilities.supported.items() if not value]
    if unsupported:
        print(f"  Runtime flags non supportati e quindi esclusi: {unsupported}")
    _print_plan(args, capabilities)
    if args.plan_only:
        return 0

    cleanup_paths = _memory_cleanup_paths(documents)
    baseline_report = _settle_memory(cleanup_paths, announce=True)
    stabilization = baseline_report.get("stabilization")
    baseline_final = stabilization.get("final") if isinstance(stabilization, dict) else None
    args.memory_baseline_mib = (
        float(baseline_final["mem_available_mib"])
        if isinstance(baseline_final, dict)
        else None
    )
    state["memory_session"] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_available_mib": args.memory_baseline_mib,
        "memory_isolation": MEMORY_ISOLATION_VERSION,
    }
    _save_state(output_dir, state)
    if args.memory_baseline_mib is not None:
        print(f"  [memory] session baseline={args.memory_baseline_mib:.0f} MiB available")

    try:
        prompt = str(state.get("chosen_prompt") or "")
        if not prompt:
            prompt = _prompt_stage(documents, output_dir, state, args)
        if args.stop_after == "prompt":
            _write_results(output_dir, state)
            return 0

        selected = state.get("stage_a_selected")
        if not selected:
            selected = _stage_a(prompt, capabilities, documents, output_dir, state, args)
        else:
            selected = {str(key): list(value) for key, value in dict(selected).items()}
            print("[resume] Stage A già completata")
        if args.stop_after == "stage-a":
            _write_results(output_dir, state)
            return 0

        _stage_b(prompt, selected, documents, output_dir, state, args)
        _write_results(output_dir, state)
    except MemoryRecoveryError as exc:
        print(f"\n[benchmark] STOP memoria: {exc}")
        print("[benchmark] Checkpoint conservato; libera RAM o riavvia e usa --resume")
        _save_state(output_dir, state)
        _write_results(output_dir, state)
        return 75
    except KeyboardInterrupt:
        print("\n[benchmark] Interrotto: checkpoint conservato")
        _save_state(output_dir, state)
        _write_results(output_dir, state)
        return 130

    print("\n=== COMPLETATO ===")
    summary = state.get("final_summary", {}).get("recommended_metrics", {})
    if summary:
        print(f"Raccomandata: {summary.get('config_id')}")
        print(f"Accuracy: {float(summary.get('macro_char_accuracy_pct', 0)):.4f}%")
        print(f"Speedup: {float(summary.get('speedup_vs_baseline', 0)):.3f}x")
    print(f"Report: {output_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
