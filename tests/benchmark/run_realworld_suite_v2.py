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
    detect_runtime_capabilities,
    process_rss_mib,
)

BORDERLINE_RUNS = 10
SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}


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


def _run_document(stage: str, config: PipelineConfig, run_index: int, document: BenchmarkDocument, server_url: str, output_dir: Path, rss_mib: float | None) -> Observation:
    started = time.perf_counter()
    pages: list[dict[str, Any]] = []
    try:
        if document.is_pdf:
            output, _ = ocr_pdf(
                document.path,
                server_url,
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
                server_url,
                preprocessing_mode=config.preprocessing_mode,
                prompt=config.prompt,
                max_image_dim=config.max_image_dim,
                jpeg_quality=config.jpeg_quality,
                cache_prompt=False,
                metrics=metrics,
            )
            pages.append(metrics)
        elapsed = time.perf_counter() - started
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
            metrics={"pages": pages, "totals": _flatten(pages), "server_rss_mib": rss_mib},
            segment_scores=segment_scores,
        )
    except Exception as exc:
        return Observation(stage, config.name, run_index, document.level, time.perf_counter() - started, None, None, None, "", {"pages": pages, "totals": _flatten(pages), "server_rss_mib": rss_mib}, {}, str(exc))


def _record_startup_failure(stage: str, config: PipelineConfig, levels: Sequence[str], target_runs: int, state: dict[str, Any], output_dir: Path, message: str) -> None:
    for run_index in range(1, target_runs + 1):
        for level in levels:
            if _successful(state, stage, config.name, run_index, level) is None:
                _upsert(state, Observation(stage, config.name, run_index, level, 0.0, None, None, None, "", {"startup_failure": True}, {}, message))
    _save_state(output_dir, state)


def _run_config(stage: str, config: PipelineConfig, levels: Sequence[str], documents: Sequence[BenchmarkDocument], output_dir: Path, state: dict[str, Any], args: argparse.Namespace, *, target_runs: int = DEFAULT_RUNS) -> None:
    pending = [
        (run_index, level)
        for run_index in range(1, target_runs + 1)
        for level in levels
        if _successful(state, stage, config.name, run_index, level) is None
    ]
    if not pending:
        print(f"  [skip] {config.name}: checkpoint completo ({target_runs} run)")
        return

    backend: BenchmarkLlamaServerBackend | None = None
    startup_error: Exception | None = None
    for attempt in range(args.max_retries + 1):
        try:
            backend = BenchmarkLlamaServerBackend(config.runtime)
            print(f"  [server] {config.name} · {config.runtime.signature()}")
            backend.initialize()
            break
        except Exception as exc:
            startup_error = exc
            if backend is not None:
                backend.shutdown()
            backend = None
            if attempt < args.max_retries:
                print(f"  [server] retry startup {attempt + 1}/{args.max_retries}: {exc}")
                time.sleep(1.0)
    if backend is None:
        message = f"runtime profile unavailable: {startup_error}"
        print(f"  [server] FAIL: {message}")
        _record_startup_failure(stage, config, levels, target_runs, state, output_dir, message)
        return

    docs = {doc.level: doc for doc in documents}
    try:
        ocr_single_image(
            _make_warmup_image(output_dir),
            backend.server_url,
            preprocessing_mode="none",
            prompt=config.prompt,
            max_image_dim=min(config.max_image_dim, 1024),
            jpeg_quality=config.jpeg_quality,
            cache_prompt=False,
        )
        rss = process_rss_mib(backend.process_pid)
        for run_index in range(1, target_runs + 1):
            order = tuple(level for level in rotation_order(run_index) if level in levels)
            print(f"    run {run_index}/{target_runs}: {' -> '.join(order)}")
            for level in order:
                if _successful(state, stage, config.name, run_index, level) is not None:
                    continue
                observation: Observation | None = None
                for attempt in range(args.max_retries + 1):
                    observation = _run_document(stage, config, run_index, docs[level], backend.server_url, output_dir, rss)
                    if observation.error is None:
                        break
                    if attempt < args.max_retries:
                        print(f"      {level}: retry {attempt + 1}/{args.max_retries}")
                assert observation is not None
                _upsert(state, observation)
                _save_state(output_dir, state)
                if observation.error:
                    print(f"      {level}: ERRORE {observation.error}")
                else:
                    print(f"      {level}: acc={100 * float(observation.char_accuracy):.3f}% time={observation.elapsed_s:.2f}s cache_n={int(observation.metrics['totals']['cache_n'])}")
                    if level == "difficile":
                        parts = " · ".join(f"{name}={100 * observation.segment_scores[name]['char_accuracy']:.2f}%" for name in HANDWRITING_SEGMENTS)
                        print(f"        {parts}")
    finally:
        backend.shutdown()


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
        return initial, {aggregate.config_id: {"status": "FAIL", "reasons": ["no valid cache-free configs"]} for aggregate in initial}
    gates = {aggregate.config_id: classify_quality(aggregate, reference) for aggregate in initial}
    borderline_ids = {config_id for config_id, gate in gates.items() if gate.status == "BORDERLINE"}
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
        final_gates = {aggregate.config_id: type("Gate", (), {"status": "FAIL", "reasons": ("no valid cache-free configs",)})() for aggregate in aggregates}
    report = {
        aggregate.config_id: {
            "status": final_gates[aggregate.config_id].status,
            "reasons": list(final_gates[aggregate.config_id].reasons),
            "runs": BORDERLINE_RUNS if aggregate.config_id in borderline_ids else args.runs,
        }
        for aggregate in aggregates
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
