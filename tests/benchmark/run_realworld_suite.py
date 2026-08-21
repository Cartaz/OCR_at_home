"""Canonical real-world benchmark suite for GLM OCR.

Protocol:
1. Select three labelled documents: easy digital PDF, medium dense scanned PDF,
   difficult handwriting (PDF or raster image), plus a strict Markdown ground truth.
2. Prompt shootout: OCR vs Text Recognition:, five runs each.
3. Stage A: one-factor-at-a-time sweeps for PDF DPI, max image dimension,
   JPEG quality and preprocessing mode.
4. Stage B: combine the five fastest quality-gated values from each variable
   (all available preprocessing modes when fewer than five exist).
5. Every configuration is measured five times; for every metric the fastest/best
   and slowest/worst observation are removed and the mean of the middle three is
   used. Each configuration gets a fresh owned llama-server by default and each
   request explicitly disables prompt caching.

The suite is checkpointed after every document and can be resumed with --resume.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llama_backend import LlamaServerBackend  # noqa: E402
from core.llama_ocr_api import ocr_pdf, ocr_single_image  # noqa: E402
from tests.benchmark.realworld_suite import (  # noqa: E402
    BENCHMARK_SEED,
    DEFAULT_ACCURACY_TOLERANCE_PP,
    DEFAULT_RUNS,
    DEFAULT_TOP_VALUES,
    DEFAULT_TRIM,
    LEVELS,
    BenchmarkDocument,
    ConfigAggregate,
    Observation,
    PipelineConfig,
    affected_levels,
    aggregate_config,
    atomic_write_json,
    character_error_rate,
    choose_quality_equivalent_fastest,
    config_variable_value,
    load_ground_truth,
    observation_from_dict,
    observation_to_dict,
    pareto_frontier,
    production_baseline,
    prompt_configs,
    rotation_order,
    select_fastest_quality_gated_values,
    sha256_file,
    speedup_vs_baseline,
    stage_a_configs,
    stage_b_configs,
    unique_configs,
    validate_documents,
    word_error_rate,
)

CHECKPOINT_SCHEMA = 1
SUPPORTED_HARD_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--easy", type=Path, default=None, help="Digital PDF (FACILE).")
    parser.add_argument("--medium", type=Path, default=None, help="Dense scanned PDF (MEDIO).")
    parser.add_argument("--hard", type=Path, default=None, help="Handwritten page, PDF or image (DIFFICILE).")
    parser.add_argument("--ground-truth", type=Path, default=None, help="Markdown ground truth with FACILE/MEDIO/DIFFICILE sections.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--resume", type=Path, default=None, help="Resume an existing benchmark result directory.")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--trim", type=int, default=DEFAULT_TRIM)
    parser.add_argument("--top-values", type=int, default=DEFAULT_TOP_VALUES)
    parser.add_argument("--accuracy-tolerance-pp", type=float, default=DEFAULT_ACCURACY_TOLERANCE_PP)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument(
        "--stop-after",
        choices=("prompt", "stage-a", "stage-b"),
        default="stage-b",
        help="Useful for splitting a very long run across sessions.",
    )
    parser.add_argument("--plan-only", action="store_true", help="Validate inputs and print the maximum plan without inference.")
    parser.add_argument("--no-dialog", action="store_true", help="Fail instead of opening file dialogs for missing paths.")
    parser.add_argument(
        "--keep-server",
        action="store_true",
        help="Reuse one owned server across configurations. Faster but not the canonical latency protocol.",
    )
    parser.add_argument(
        "--server-url",
        default="",
        help="Use an external compatible server; implies no owned-server restart between configs.",
    )
    return parser.parse_args()


def _select_file(title: str, filter_text: str) -> Path:
    try:
        from PySide6.QtWidgets import QApplication, QFileDialog
    except ImportError as exc:
        raise SystemExit("PySide6 è necessario per la selezione guidata dei file") from exc

    app = QApplication.instance()
    owned = app is None
    if app is None:
        app = QApplication([])
    filename, _selected_filter = QFileDialog.getOpenFileName(None, title, str(Path.home()), filter_text)
    if owned:
        app.processEvents()
    if not filename:
        raise SystemExit(f"Selezione annullata: {title}")
    return Path(filename).expanduser().resolve()


def _resolve_input_paths(args: argparse.Namespace, state: dict[str, Any] | None) -> tuple[Path, Path, Path, Path]:
    if state is not None:
        stored = state.get("inputs", {})
        easy = Path(args.easy or stored.get("facile", {}).get("path", "")).expanduser().resolve()
        medium = Path(args.medium or stored.get("medio", {}).get("path", "")).expanduser().resolve()
        hard = Path(args.hard or stored.get("difficile", {}).get("path", "")).expanduser().resolve()
        truth = Path(args.ground_truth or stored.get("ground_truth", {}).get("path", "")).expanduser().resolve()
        return easy, medium, hard, truth

    missing = [args.easy is None, args.medium is None, args.hard is None, args.ground_truth is None]
    if any(missing) and args.no_dialog:
        raise SystemExit("Con --no-dialog devi specificare --easy --medium --hard --ground-truth")

    easy = (args.easy.expanduser().resolve() if args.easy else _select_file("FACILE — seleziona PDF digitale", "PDF (*.pdf)"))
    medium = (args.medium.expanduser().resolve() if args.medium else _select_file("MEDIO — seleziona PDF da scansione densa", "PDF (*.pdf)"))
    hard = (
        args.hard.expanduser().resolve()
        if args.hard
        else _select_file(
            "DIFFICILE — seleziona pagina scritta a mano",
            "Documenti (*.pdf *.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp *.gif)",
        )
    )
    truth = (
        args.ground_truth.expanduser().resolve()
        if args.ground_truth
        else _select_file("GROUND TRUTH — seleziona Markdown", "Markdown (*.md)")
    )
    return easy, medium, hard, truth


def _validate_cli(args: argparse.Namespace) -> None:
    if args.runs < 3 or args.runs % 2 == 0:
        raise SystemExit("--runs deve essere dispari e >= 3; il protocollo canonico usa 5")
    if args.trim < 0 or args.runs <= 2 * args.trim:
        raise SystemExit("--trim non è compatibile con il numero di run")
    if args.top_values < 1:
        raise SystemExit("--top-values deve essere >= 1")
    if args.accuracy_tolerance_pp < 0:
        raise SystemExit("--accuracy-tolerance-pp deve essere >= 0")
    if args.max_retries < 0:
        raise SystemExit("--max-retries deve essere >= 0")
    if args.server_url and args.keep_server:
        # External server already implies reuse; accepting both would be ambiguous in reports.
        raise SystemExit("--keep-server non serve insieme a --server-url")


def _load_checkpoint(output_dir: Path) -> dict[str, Any] | None:
    path = output_dir / "checkpoint.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("schema_version", -1)) != CHECKPOINT_SCHEMA:
        raise SystemExit("Checkpoint con schema incompatibile")
    return payload


def _make_documents(easy: Path, medium: Path, hard: Path, truth: Path) -> tuple[list[BenchmarkDocument], dict[str, str]]:
    if hard.suffix.lower() not in SUPPORTED_HARD_EXTENSIONS:
        raise SystemExit(f"Formato DIFFICILE non supportato: {hard.suffix}")
    ground_truth = load_ground_truth(truth)
    documents = [
        BenchmarkDocument("facile", easy, ground_truth["facile"]),
        BenchmarkDocument("medio", medium, ground_truth["medio"]),
        BenchmarkDocument("difficile", hard, ground_truth["difficile"]),
    ]
    validate_documents(documents)
    return documents, ground_truth


def _input_metadata(documents: Sequence[BenchmarkDocument], truth: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for document in documents:
        payload[document.level] = {
            "path": str(document.path),
            "filename": document.path.name,
            "sha256": sha256_file(document.path),
            "is_pdf": document.is_pdf,
        }
    payload["ground_truth"] = {
        "path": str(truth),
        "filename": truth.name,
        "sha256": sha256_file(truth),
    }
    return payload


def _assert_resume_inputs(state: dict[str, Any], inputs: dict[str, Any]) -> None:
    stored = state.get("inputs", {})
    for key in (*LEVELS, "ground_truth"):
        if stored.get(key, {}).get("sha256") != inputs.get(key, {}).get("sha256"):
            raise SystemExit(f"SHA-256 diverso per {key}: rifiuto il resume su input differenti")


def _initial_state(inputs: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": CHECKPOINT_SCHEMA,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": inputs,
        "protocol": {
            "runs": args.runs,
            "trim": args.trim,
            "top_values": args.top_values,
            "accuracy_tolerance_pp": args.accuracy_tolerance_pp,
            "max_retries": args.max_retries,
            "cache_prompt": False,
            "fresh_server_per_config": not bool(args.keep_server or args.server_url),
            "seed": BENCHMARK_SEED,
        },
        "chosen_prompt": None,
        "stage_a_selected": None,
        "stage_b_plan": None,
        "observations": [],
        "completed_stages": [],
    }


def _save_state(output_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    atomic_write_json(output_dir / "checkpoint.json", state)


def _observations(state: dict[str, Any]) -> list[Observation]:
    return [observation_from_dict(dict(item)) for item in state.get("observations", [])]


def _upsert_observation(state: dict[str, Any], observation: Observation) -> None:
    items = [observation_from_dict(dict(item)) for item in state.get("observations", [])]
    replaced = False
    for index, item in enumerate(items):
        if item.key == observation.key:
            items[index] = observation
            replaced = True
            break
    if not replaced:
        items.append(observation)
    state["observations"] = [observation_to_dict(item) for item in items]


def _successful_observation(state: dict[str, Any], *, stage: str, config_id: str, run_index: int, level: str) -> Observation | None:
    for observation in _observations(state):
        if observation.key == (stage, config_id, run_index, level) and observation.error is None:
            return observation
    return None


def _make_warmup_image(output_dir: Path) -> Path:
    path = output_dir / "warmup.png"
    if path.is_file():
        return path
    image = Image.new("RGB", (900, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.text((50, 70), "GLM OCR benchmark warm-up 12345", fill="black")
    draw.text((50, 130), "Questa immagine non appartiene al corpus valutato.", fill="black")
    image.save(path)
    return path


def _flatten_page_metrics(page_metrics: Sequence[dict[str, Any]]) -> dict[str, Any]:
    numeric_sum = {
        "encoded_bytes",
        "request_elapsed_s",
        "render_elapsed_s",
        "preprocess_elapsed_s",
        "load_elapsed_s",
        "cache_n",
        "prompt_n",
        "predicted_n",
    }
    totals: dict[str, Any] = {key: 0.0 for key in numeric_sum}
    for page in page_metrics:
        for key in numeric_sum:
            totals[key] += float(page.get(key, 0.0) or 0.0)
    totals["cache_n"] = int(totals["cache_n"])
    totals["encoded_bytes"] = int(totals["encoded_bytes"])
    return totals


def _run_document(
    *,
    stage: str,
    config: PipelineConfig,
    run_index: int,
    document: BenchmarkDocument,
    server_url: str,
    output_dir: Path,
) -> Observation:
    started = time.perf_counter()
    page_metrics: list[dict[str, Any]] = []
    try:
        if document.is_pdf:
            output, _confidence = ocr_pdf(
                document.path,
                server_url,
                preprocessing_mode=config.preprocessing_mode,
                emit_events=False,
                prompt=config.prompt,
                pdf_dpi=config.pdf_dpi,
                max_image_dim=config.max_image_dim,
                jpeg_quality=config.jpeg_quality,
                cache_prompt=False,
                page_metrics=page_metrics,
            )
        else:
            metrics: dict[str, Any] = {}
            output, _confidence = ocr_single_image(
                document.path,
                server_url,
                preprocessing_mode=config.preprocessing_mode,
                prompt=config.prompt,
                max_image_dim=config.max_image_dim,
                jpeg_quality=config.jpeg_quality,
                cache_prompt=False,
                metrics=metrics,
            )
            page_metrics.append(metrics)

        elapsed = time.perf_counter() - started
        cer = character_error_rate(document.expected_text, output)
        wer = word_error_rate(document.expected_text, output)
        char_accuracy = max(0.0, min(1.0, 1.0 - cer))
        output_path = (
            output_dir
            / "outputs"
            / stage
            / config.name
            / document.level
            / f"run-{run_index:02d}.txt"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output.rstrip() + "\n", encoding="utf-8")
        flat = _flatten_page_metrics(page_metrics)
        return Observation(
            stage=stage,
            config_id=config.name,
            run_index=run_index,
            level=document.level,
            elapsed_s=elapsed,
            cer=cer,
            wer=wer,
            char_accuracy=char_accuracy,
            output_file=str(output_path.relative_to(output_dir)),
            metrics={"pages": page_metrics, "totals": flat},
        )
    except Exception as exc:
        return Observation(
            stage=stage,
            config_id=config.name,
            run_index=run_index,
            level=document.level,
            elapsed_s=time.perf_counter() - started,
            cer=None,
            wer=None,
            char_accuracy=None,
            output_file="",
            metrics={"pages": page_metrics, "totals": _flatten_page_metrics(page_metrics)},
            error=str(exc),
        )


def _warmup(server_url: str, config: PipelineConfig, warmup_path: Path) -> None:
    ocr_single_image(
        warmup_path,
        server_url,
        preprocessing_mode="none",
        prompt=config.prompt,
        max_image_dim=min(config.max_image_dim, 1024),
        jpeg_quality=config.jpeg_quality,
        cache_prompt=False,
    )


def _print_run_result(observation: Observation) -> None:
    if observation.error:
        print(f"      ERRORE: {observation.error}")
        return
    totals = observation.metrics.get("totals", {})
    print(
        f"      accuracy={100.0 * float(observation.char_accuracy):.3f}% "
        f"CER={float(observation.cer):.5f} WER={float(observation.wer):.5f} "
        f"total={observation.elapsed_s:.2f}s request={float(totals.get('request_elapsed_s', 0.0)):.2f}s "
        f"JPEG={float(totals.get('encoded_bytes', 0)) / 1024:.1f}KiB "
        f"cache_n={int(totals.get('cache_n', 0))}"
    )


def _run_config(
    *,
    stage: str,
    config: PipelineConfig,
    levels: Sequence[str],
    documents: Sequence[BenchmarkDocument],
    output_dir: Path,
    state: dict[str, Any],
    args: argparse.Namespace,
    shared_backend: LlamaServerBackend | None,
    external_url: str,
) -> None:
    docs = {document.level: document for document in documents}
    pending = [
        (run_index, level)
        for run_index in range(1, args.runs + 1)
        for level in levels
        if _successful_observation(
            state,
            stage=stage,
            config_id=config.name,
            run_index=run_index,
            level=level,
        )
        is None
    ]
    if not pending:
        print(f"  [skip] {config.name}: già completo nel checkpoint")
        return

    owned_backend: LlamaServerBackend | None = None
    server_url = external_url
    if not server_url:
        if shared_backend is not None:
            server_url = shared_backend.server_url
        else:
            owned_backend = LlamaServerBackend()
            print(f"  [server] avvio fresh llama-server per {config.name}")
            owned_backend.initialize()
            server_url = owned_backend.server_url

    try:
        _warmup(server_url, config, _make_warmup_image(output_dir))
        for run_index in range(1, args.runs + 1):
            order = tuple(level for level in rotation_order(run_index) if level in levels)
            print(f"    run {run_index}/{args.runs}: {' -> '.join(order)}")
            for level in order:
                existing = _successful_observation(
                    state,
                    stage=stage,
                    config_id=config.name,
                    run_index=run_index,
                    level=level,
                )
                if existing is not None:
                    print(f"      {level}: checkpoint")
                    continue

                observation: Observation | None = None
                for attempt in range(args.max_retries + 1):
                    observation = _run_document(
                        stage=stage,
                        config=config,
                        run_index=run_index,
                        document=docs[level],
                        server_url=server_url,
                        output_dir=output_dir,
                    )
                    if observation.error is None:
                        break
                    if attempt < args.max_retries:
                        print(f"      {level}: retry {attempt + 1}/{args.max_retries}")
                        time.sleep(0.5)
                assert observation is not None
                _upsert_observation(state, observation)
                _save_state(output_dir, state)
                print(f"      {level}:")
                _print_run_result(observation)
    finally:
        if owned_backend is not None:
            owned_backend.shutdown()


def _aggregate(
    state: dict[str, Any],
    config: PipelineConfig,
    levels: Sequence[str],
    args: argparse.Namespace,
) -> ConfigAggregate:
    return aggregate_config(
        _observations(state),
        config_id=config.name,
        levels=levels,
        expected_runs=args.runs,
        trim=args.trim,
    )


def _print_aggregate(label: str, aggregate: ConfigAggregate) -> None:
    if not aggregate.valid:
        print(f"  {label}: INVALIDO")
        return
    print(
        f"  {label}: accuracy={aggregate.macro_char_accuracy * 100:.3f}% "
        f"CER={aggregate.macro_cer:.5f} WER={aggregate.macro_wer:.5f} "
        f"tempo={aggregate.macro_elapsed_s:.2f}s cache_n={aggregate.cache_n_total}"
    )


def _prompt_stage(
    *,
    documents: Sequence[BenchmarkDocument],
    output_dir: Path,
    state: dict[str, Any],
    args: argparse.Namespace,
    shared_backend: LlamaServerBackend | None,
    external_url: str,
) -> str:
    print("\n=== PROMPT SHOOTOUT ===")
    configs = prompt_configs()
    for config in configs:
        print(f"\n[prompt] {config.prompt}")
        _run_config(
            stage="prompt",
            config=config,
            levels=LEVELS,
            documents=documents,
            output_dir=output_dir,
            state=state,
            args=args,
            shared_backend=shared_backend,
            external_url=external_url,
        )

    aggregates = [_aggregate(state, config, LEVELS, args) for config in configs]
    print("\n[prompt] trimmed summary")
    for config, aggregate in zip(configs, aggregates):
        _print_aggregate(config.prompt, aggregate)
    winner = choose_quality_equivalent_fastest(
        aggregates,
        tolerance_pp=args.accuracy_tolerance_pp,
    )
    selected = next(config.prompt for config in configs if config.name == winner.config_id)
    state["chosen_prompt"] = selected
    if "prompt" not in state["completed_stages"]:
        state["completed_stages"].append("prompt")
    _save_state(output_dir, state)
    print(f"[prompt] selezionato: {selected}")
    return selected


def _stage_a(
    *,
    prompt: str,
    documents: Sequence[BenchmarkDocument],
    output_dir: Path,
    state: dict[str, Any],
    args: argparse.Namespace,
    shared_backend: LlamaServerBackend | None,
    external_url: str,
) -> dict[str, list[Any]]:
    print("\n=== STAGE A — ONE FACTOR AT A TIME ===")
    groups = stage_a_configs(prompt)
    baseline = production_baseline(prompt, name="stage_a_baseline")

    # Run the shared production baseline once on all documents.
    _run_config(
        stage="stage_a",
        config=baseline,
        levels=LEVELS,
        documents=documents,
        output_dir=output_dir,
        state=state,
        args=args,
        shared_backend=shared_backend,
        external_url=external_url,
    )

    selected: dict[str, list[Any]] = {}
    stage_a_report: dict[str, list[dict[str, Any]]] = {}
    for variable, configs in groups.items():
        levels = affected_levels(variable, documents)
        print(f"\n[stage A] {variable} · livelli: {', '.join(levels)}")
        for config in unique_configs([configs]):
            if config.name == baseline.name:
                continue
            print(
                f"\n  {config.name}: pre={config.preprocessing_mode} dpi={config.pdf_dpi} "
                f"max={config.max_image_dim} jpeg={config.jpeg_quality}"
            )
            _run_config(
                stage="stage_a",
                config=config,
                levels=levels,
                documents=documents,
                output_dir=output_dir,
                state=state,
                args=args,
                shared_backend=shared_backend,
                external_url=external_url,
            )

        candidates: list[tuple[Any, ConfigAggregate]] = []
        report_rows: list[dict[str, Any]] = []
        for config in configs:
            aggregate = _aggregate(state, config, levels, args)
            value = config_variable_value(config, variable)
            candidates.append((value, aggregate))
            report_rows.append(
                {
                    "value": value,
                    "config_id": config.name,
                    "valid": aggregate.valid,
                    "macro_char_accuracy": aggregate.macro_char_accuracy,
                    "macro_cer": aggregate.macro_cer,
                    "macro_wer": aggregate.macro_wer,
                    "macro_elapsed_s": aggregate.macro_elapsed_s,
                    "cache_n_total": aggregate.cache_n_total,
                }
            )
            _print_aggregate(str(value), aggregate)

        chosen_values = select_fastest_quality_gated_values(
            candidates,
            top_n=args.top_values,
            tolerance_pp=args.accuracy_tolerance_pp,
        )
        selected[variable] = chosen_values
        stage_a_report[variable] = report_rows
        print(f"  -> finalisti Stage B: {chosen_values}")

    state["stage_a_selected"] = selected
    state["stage_a_report"] = stage_a_report
    if "stage_a" not in state["completed_stages"]:
        state["completed_stages"].append("stage_a")
    _save_state(output_dir, state)
    return selected


def _average_baseline_documents(start: ConfigAggregate, end: ConfigAggregate) -> dict[str, float]:
    result: dict[str, float] = {}
    for level in LEVELS:
        values = [
            aggregate.documents[level].trimmed_elapsed_s
            for aggregate in (start, end)
            if aggregate.documents[level].valid
        ]
        if values:
            result[level] = sum(values) / len(values)
    return result


def _config_map(configs: Sequence[PipelineConfig]) -> dict[str, PipelineConfig]:
    return {config.name: config for config in configs}


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _ranking_row(
    aggregate: ConfigAggregate,
    config: PipelineConfig,
    baseline_documents: dict[str, float],
) -> dict[str, Any]:
    return {
        "config_id": aggregate.config_id,
        "prompt": config.prompt,
        "preprocessing_mode": config.preprocessing_mode,
        "pdf_dpi": config.pdf_dpi,
        "max_image_dim": config.max_image_dim,
        "jpeg_quality": config.jpeg_quality,
        "macro_char_accuracy_pct": aggregate.macro_char_accuracy * 100.0,
        "macro_cer": aggregate.macro_cer,
        "macro_wer": aggregate.macro_wer,
        "macro_elapsed_s": aggregate.macro_elapsed_s,
        "macro_request_elapsed_s": aggregate.macro_request_elapsed_s,
        "mean_encoded_kib": aggregate.mean_encoded_bytes / 1024.0,
        "speedup_vs_baseline": speedup_vs_baseline(aggregate, baseline_documents),
        "cache_n_total": aggregate.cache_n_total,
    }


def _export_stage_b(
    *,
    output_dir: Path,
    prompt: str,
    configs: Sequence[PipelineConfig],
    aggregates: Sequence[ConfigAggregate],
    baseline_start: ConfigAggregate,
    baseline_end: ConfigAggregate,
    state: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    config_by_id = _config_map(configs)
    baseline_documents = _average_baseline_documents(baseline_start, baseline_end)
    valid_pairs = [
        (config_by_id[aggregate.config_id], aggregate)
        for aggregate in aggregates
        if aggregate.valid and aggregate.cache_n_total == 0
    ]
    if not valid_pairs:
        raise RuntimeError("Stage B non contiene configurazioni valide cache-free")

    accuracy_sorted = sorted(valid_pairs, key=lambda item: (-item[1].macro_char_accuracy, item[1].macro_elapsed_s))
    speed_sorted = sorted(valid_pairs, key=lambda item: (item[1].macro_elapsed_s, -item[1].macro_char_accuracy))
    recommendation = choose_quality_equivalent_fastest(
        [aggregate for _config, aggregate in valid_pairs],
        tolerance_pp=args.accuracy_tolerance_pp,
    )
    recommendation_config = config_by_id[recommendation.config_id]
    frontier = pareto_frontier([aggregate for _config, aggregate in valid_pairs])

    fields = list(_ranking_row(valid_pairs[0][1], valid_pairs[0][0], baseline_documents).keys())
    _write_csv(
        output_dir / "ranking_accuracy.csv",
        fields,
        [_ranking_row(aggregate, config, baseline_documents) for config, aggregate in accuracy_sorted],
    )
    _write_csv(
        output_dir / "ranking_speed.csv",
        fields,
        [_ranking_row(aggregate, config, baseline_documents) for config, aggregate in speed_sorted],
    )
    _write_csv(
        output_dir / "pareto.csv",
        fields,
        [_ranking_row(aggregate, config_by_id[aggregate.config_id], baseline_documents) for aggregate in frontier],
    )

    best_accuracy = accuracy_sorted[0][1].macro_char_accuracy
    tolerance = args.accuracy_tolerance_pp / 100.0
    recommended_pool = [
        (config, aggregate)
        for config, aggregate in speed_sorted
        if aggregate.macro_char_accuracy >= best_accuracy - tolerance
    ]
    _write_csv(
        output_dir / "ranking_recommended.csv",
        fields,
        [_ranking_row(aggregate, config, baseline_documents) for config, aggregate in recommended_pool],
    )

    state["stage_b_summary"] = {
        "valid_configs": len(valid_pairs),
        "recommended_config": asdict(recommendation_config),
        "recommended_metrics": _ranking_row(recommendation, recommendation_config, baseline_documents),
        "best_accuracy_config": asdict(accuracy_sorted[0][0]),
        "best_accuracy_metrics": _ranking_row(accuracy_sorted[0][1], accuracy_sorted[0][0], baseline_documents),
        "fastest_config": asdict(speed_sorted[0][0]),
        "fastest_metrics": _ranking_row(speed_sorted[0][1], speed_sorted[0][0], baseline_documents),
        "pareto_config_ids": [item.config_id for item in frontier],
        "baseline_documents_s": baseline_documents,
    }
    _save_state(output_dir, state)

    lines = [
        "# GLM OCR real-world benchmark",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Protocol",
        "",
        f"- Prompt selected before pipeline tuning: `{prompt}`",
        f"- Runs per configuration: {args.runs}",
        f"- Trim: remove {args.trim} best/fastest and {args.trim} worst/slowest value(s) per metric",
        f"- Quality gate for Stage B/recommendation: {args.accuracy_tolerance_pp:.3f} percentage points",
        "- Prompt cache explicitly disabled for benchmark requests",
        "- Macro accuracy gives FACILE/MEDIO/DIFFICILE equal weight",
        "",
        "## Stage A finalists",
        "",
    ]
    for variable, values in dict(state.get("stage_a_selected") or {}).items():
        lines.append(f"- **{variable}**: `{values}`")

    rec_row = state["stage_b_summary"]["recommended_metrics"]
    best_row = state["stage_b_summary"]["best_accuracy_metrics"]
    fast_row = state["stage_b_summary"]["fastest_metrics"]
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"Recommended: `{recommendation.config_id}`",
            f"- Character accuracy: {rec_row['macro_char_accuracy_pct']:.4f}%",
            f"- CER: {rec_row['macro_cer']:.6f}",
            f"- WER: {rec_row['macro_wer']:.6f}",
            f"- Mean document time: {rec_row['macro_elapsed_s']:.3f}s",
            f"- Speed vs production baseline controls: {rec_row['speedup_vs_baseline']:.3f}x",
            "",
            "## Accuracy winner",
            "",
            f"`{best_row['config_id']}` — {best_row['macro_char_accuracy_pct']:.4f}% — {best_row['macro_elapsed_s']:.3f}s",
            "",
            "## Speed winner",
            "",
            f"`{fast_row['config_id']}` — {fast_row['macro_char_accuracy_pct']:.4f}% — {fast_row['macro_elapsed_s']:.3f}s",
            "",
            "## Pareto frontier",
            "",
        ]
    )
    for aggregate in frontier:
        row = _ranking_row(aggregate, config_by_id[aggregate.config_id], baseline_documents)
        lines.append(
            f"- `{aggregate.config_id}`: {row['macro_char_accuracy_pct']:.4f}% / "
            f"{row['macro_elapsed_s']:.3f}s / {row['speedup_vs_baseline']:.3f}x"
        )
    lines.extend(
        [
            "",
            "Raw OCR outputs are stored under `outputs/`; full observations and input hashes are in `results.json`.",
        ]
    )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _stage_b(
    *,
    prompt: str,
    selected: dict[str, Sequence[Any]],
    documents: Sequence[BenchmarkDocument],
    output_dir: Path,
    state: dict[str, Any],
    args: argparse.Namespace,
    shared_backend: LlamaServerBackend | None,
    external_url: str,
) -> None:
    print("\n=== STAGE B — FINALIST COMBINATIONS ===")
    configs = stage_b_configs(prompt=prompt, selected=selected)
    rng = random.Random(BENCHMARK_SEED)
    rng.shuffle(configs)
    state["stage_b_plan"] = [asdict(config) for config in configs]
    _save_state(output_dir, state)

    baseline_start_config = production_baseline(prompt, name="b_baseline_start")
    baseline_end_config = production_baseline(prompt, name="b_baseline_end")
    print(f"[stage B] combinazioni: {len(configs)} + 2 baseline controls")

    _run_config(
        stage="stage_b",
        config=baseline_start_config,
        levels=LEVELS,
        documents=documents,
        output_dir=output_dir,
        state=state,
        args=args,
        shared_backend=shared_backend,
        external_url=external_url,
    )

    for index, config in enumerate(configs, start=1):
        print(
            f"\n[stage B {index}/{len(configs)}] {config.name} "
            f"pre={config.preprocessing_mode} dpi={config.pdf_dpi} "
            f"max={config.max_image_dim} jpeg={config.jpeg_quality}"
        )
        _run_config(
            stage="stage_b",
            config=config,
            levels=LEVELS,
            documents=documents,
            output_dir=output_dir,
            state=state,
            args=args,
            shared_backend=shared_backend,
            external_url=external_url,
        )

    _run_config(
        stage="stage_b",
        config=baseline_end_config,
        levels=LEVELS,
        documents=documents,
        output_dir=output_dir,
        state=state,
        args=args,
        shared_backend=shared_backend,
        external_url=external_url,
    )

    aggregates = [_aggregate(state, config, LEVELS, args) for config in configs]
    baseline_start = _aggregate(state, baseline_start_config, LEVELS, args)
    baseline_end = _aggregate(state, baseline_end_config, LEVELS, args)
    _export_stage_b(
        output_dir=output_dir,
        prompt=prompt,
        configs=configs,
        aggregates=aggregates,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        state=state,
        args=args,
    )
    if "stage_b" not in state["completed_stages"]:
        state["completed_stages"].append("stage_b")
    _save_state(output_dir, state)


def _write_results(output_dir: Path, state: dict[str, Any]) -> None:
    payload = dict(state)
    payload["checkpoint_file"] = "checkpoint.json"
    atomic_write_json(output_dir / "results.json", payload)


def _print_plan(args: argparse.Namespace) -> None:
    # Maximum assumes 5/5/5/4 Stage B finalists.
    prompt_ocr = 2 * args.runs * 3
    # Stage A: one baseline on 3 docs, six non-baseline DPI configs on 2 PDFs,
    # six maxdim, seven JPEG and three preprocessing variants on all 3 docs.
    stage_a_ocr = args.runs * (3 + 6 * 2 + 6 * 3 + 7 * 3 + 3 * 3)
    stage_b_combos = min(args.top_values, 7) * min(args.top_values, 7) * min(args.top_values, 8) * min(args.top_values, 4)
    stage_b_ocr = (stage_b_combos + 2) * args.runs * 3
    print("\n[piano massimo]")
    print(f"  prompt shootout: {prompt_ocr} OCR")
    print(f"  Stage A:         {stage_a_ocr} OCR")
    print(f"  Stage B:         max {stage_b_combos} combinazioni, {stage_b_ocr} OCR")
    print(f"  Totale massimo: {prompt_ocr + stage_a_ocr + stage_b_ocr} OCR + warm-up per configurazione")
    print("  Ogni configurazione usa 5 run nel protocollo canonico; le metriche sono trimmed mean.")


def main() -> int:
    args = parse_args()
    _validate_cli(args)

    if args.resume:
        output_dir = args.resume.expanduser().resolve()
        state = _load_checkpoint(output_dir)
        if state is None:
            raise SystemExit(f"Checkpoint non trovato in {output_dir}")
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = (args.output_dir or Path("benchmark-results") / f"realworld-{timestamp}").expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        state = None

    easy, medium, hard, truth = _resolve_input_paths(args, state)
    documents, _ground_truth = _make_documents(easy, medium, hard, truth)
    inputs = _input_metadata(documents, truth)

    if state is None:
        state = _initial_state(inputs, args)
        _save_state(output_dir, state)
        atomic_write_json(output_dir / "inputs.json", inputs)
    else:
        _assert_resume_inputs(state, inputs)
        protocol = state.get("protocol", {})
        if int(protocol.get("runs", args.runs)) != args.runs or int(protocol.get("trim", args.trim)) != args.trim:
            raise SystemExit("--runs/--trim devono coincidere con il checkpoint")

    print("GLM OCR — real-world benchmark suite")
    print(f"Output: {output_dir}")
    for document in documents:
        print(f"  {document.level.upper():10s} {document.path.name} sha256={inputs[document.level]['sha256'][:12]}...")
    print(f"  GROUND TRUTH {truth.name} sha256={inputs['ground_truth']['sha256'][:12]}...")
    _print_plan(args)
    if args.plan_only:
        return 0

    shared_backend: LlamaServerBackend | None = None
    external_url = str(args.server_url).strip()
    if not external_url and args.keep_server:
        shared_backend = LlamaServerBackend()
        print("[server] avvio llama-server condiviso (--keep-server)")
        shared_backend.initialize()
        external_url = shared_backend.server_url

    try:
        prompt = str(state.get("chosen_prompt") or "")
        if not prompt:
            prompt = _prompt_stage(
                documents=documents,
                output_dir=output_dir,
                state=state,
                args=args,
                shared_backend=shared_backend,
                external_url=external_url,
            )
        else:
            print(f"[resume] prompt già selezionato: {prompt}")
        _write_results(output_dir, state)
        if args.stop_after == "prompt":
            return 0

        selected = state.get("stage_a_selected")
        if not selected:
            selected = _stage_a(
                prompt=prompt,
                documents=documents,
                output_dir=output_dir,
                state=state,
                args=args,
                shared_backend=shared_backend,
                external_url=external_url,
            )
        else:
            selected = {str(key): list(value) for key, value in dict(selected).items()}
            print(f"[resume] Stage A già selezionata: {selected}")
        _write_results(output_dir, state)
        if args.stop_after == "stage-a":
            return 0

        _stage_b(
            prompt=prompt,
            selected=selected,
            documents=documents,
            output_dir=output_dir,
            state=state,
            args=args,
            shared_backend=shared_backend,
            external_url=external_url,
        )
        _write_results(output_dir, state)
    except KeyboardInterrupt:
        print("\n[benchmark] Interrotto dall'utente. Checkpoint conservato.")
        _save_state(output_dir, state)
        _write_results(output_dir, state)
        return 130
    finally:
        if shared_backend is not None:
            shared_backend.shutdown()

    summary = state.get("stage_b_summary", {})
    print("\n=== COMPLETATO ===")
    if summary:
        rec = summary.get("recommended_metrics", {})
        print(f"Raccomandata: {rec.get('config_id')}")
        print(f"Accuracy: {float(rec.get('macro_char_accuracy_pct', 0.0)):.4f}%")
        print(f"Tempo medio documento: {float(rec.get('macro_elapsed_s', 0.0)):.3f}s")
        print(f"Speedup baseline: {float(rec.get('speedup_vs_baseline', 0.0)):.3f}x")
    print(f"Report: {output_dir / 'summary.md'}")
    print(f"Risultati: {output_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
