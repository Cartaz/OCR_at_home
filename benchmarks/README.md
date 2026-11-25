# GLM-OCR prompt benchmark

This directory contains the manual, hardware-backed benchmark used by Phase 2 of `ROADMAP.md`.

The benchmark exists to answer one question before production behavior changes:

> Does the official `Text Recognition:` prompt improve recognition quality over the current `OCR` prompt on the same local llama.cpp/SYCL pipeline?

## Authoritative prompt definitions

The task prompts are taken from the official `zai-org/GLM-OCR` repository:

- `Text Recognition:`
- `Table Recognition:`
- `Formula Recognition:`

Sources:

- https://github.com/zai-org/GLM-OCR/blob/main/glmocr/config.yaml
- https://github.com/zai-org/GLM-OCR/blob/main/examples/finetune/README.md

The official self-hosted config also uses task-specific prompts after layout analysis. This project currently sends a whole image/page directly to GLM-OCR through llama.cpp, so specialized table/formula results are recorded for inspection but are not treated as equivalent to the complete upstream layout pipeline.

## What the hardware baselines established

Two synthetic hardware runs are preserved under `baselines/`.

The first run showed a quality tie but had obvious warm/order bias. The second repeated run again produced a perfect quality tie: every recorded text request from both `OCR` and `Text Recognition:` reached CER `0.0000`.

The second run also exposed a strong llama-server cache effect for repeated identical images: a first request could take roughly 20–37 seconds while the immediately repeated request could complete around 1–1.6 seconds. Therefore repeated-image wall-clock measurements are **not valid evidence of intrinsic prompt speed**.

For prompt selection, this benchmark now treats:

- CER / labelled output quality as decision evidence;
- elapsed time as diagnostic metadata only.

## Canonical runner

Use `run_prompt_benchmark.py`. It fixes the per-sample counterbalancing bug found in the second baseline: every individual sample alternates which prompt runs first between rounds, independent of reversed traversal order.

From the repository root:

```bash
.venv/bin/python tests/benchmark/run_prompt_benchmark.py --specialized
```

Defaults are one unrecorded warm-up round and two recorded quality rounds. Two rounds are enough for first-order per-sample counterbalancing; more rounds can be requested when useful:

```bash
.venv/bin/python tests/benchmark/run_prompt_benchmark.py \
  --rounds 4 \
  --warmup-rounds 1 \
  --specialized
```

The runner creates and owns a `LlamaServerBackend`, starts the same SYCL/full-offload runtime used by the application, performs the benchmark, then shuts the process down in `finally`.

Do not keep the desktop application open while using this mode if RAM/VRAM is tight.

`benchmark_prompt_quality.py` remains the helper/library containing deterministic corpus generation, CER and manifest-loading functions. Its historical CLI output is preserved for reproducibility of the recorded baselines, but it is no longer the canonical decision runner.

## Synthetic corpus

Without extra arguments, the canonical runner generates the deterministic synthetic corpus at runtime. It covers:

- clean printed text;
- small text;
- noisy/scan-like text;
- a table;
- formulas;
- a mixed-layout page.

Text-oriented samples are scored with character error rate (CER) after conservative whitespace normalization. Table and formula samples can also be run with their official prompts and are stored as raw outputs for manual inspection.

The synthetic text comparison is now considered a quality tie. Further synthetic repetition is not required before moving to real documents.

## Run against an already-running compatible server

```bash
.venv/bin/python tests/benchmark/run_prompt_benchmark.py \
  --server-url http://127.0.0.1:PORT
```

In this mode the benchmark does not create or terminate the supplied server.

## Real-world labelled corpus

Synthetic pages are deterministic but too easy to decide a production OCR prompt. The runner can consume a directory of real images with a `manifest.json`:

```text
my-real-corpus/
├── manifest.json
├── scan-01.png
└── photo-02.jpg
```

Example manifest:

```json
[
  {
    "name": "scan-01",
    "image": "scan-01.png",
    "expected_text": "Trascrizione esatta del documento...",
    "task": "text"
  },
  {
    "name": "photo-02",
    "image": "photo-02.jpg",
    "expected_text": "Seconda trascrizione...",
    "task": "text",
    "score_mode": "cer"
  }
]
```

Run it with:

```bash
.venv/bin/python tests/benchmark/run_prompt_benchmark.py \
  --corpus-dir /percorso/my-real-corpus \
  --rounds 2
```

Supported `task` values are `text`, `table`, and `formula`; supported `score_mode` values are `cer` and `manual`. The prompt comparison itself uses `task=text` samples. Paths in the manifest are constrained to the corpus directory.

## Specialized prompt probes

`--specialized` additionally records:

- table samples with `Table Recognition:`;
- formula samples with `Formula Recognition:`.

The two synthetic table probes have been structurally correct. The formula probe repeated an operator transcription error (`+/-` rendered as `+ / -`), so formula mode is not yet considered validated.

## Output

By default results are written under:

```text
benchmark-results/glm-ocr-prompts-YYYYMMDD-HHMMSS/
```

`results.json` contains:

- per-sample model output;
- raw elapsed time for diagnostics;
- CER where applicable;
- round and execution sequence;
- an accuracy-only `quality_summary`;
- an explicit `timing_interpretation` warning that repeated-input timings may be cache-accelerated.

The production default remains `OCR` until labelled real-world evidence is reviewed and the roadmap item is explicitly completed.
