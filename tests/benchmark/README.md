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

## What the runner generates

`benchmark_prompt_quality.py` creates a deterministic synthetic corpus at runtime, so no binary fixtures need to be committed. It covers:

- clean printed text;
- small text;
- noisy/scan-like text;
- a table;
- formulas;
- a mixed-layout page.

Text-oriented samples are scored with character error rate (CER) after conservative whitespace normalization. Table and formula samples can also be run with their official prompts and are stored as raw outputs for manual inspection.

## Run with a benchmark-owned llama-server

From the repository root:

```bash
.venv/bin/python tests/benchmark/benchmark_prompt_quality.py
```

The runner creates and owns a `LlamaServerBackend`, starts the same SYCL/full-offload runtime used by the application, performs the benchmark, then shuts the process down in `finally`.

Do not keep the desktop application open while using this mode if RAM/VRAM is tight.

## Run against an already-running compatible server

```bash
.venv/bin/python tests/benchmark/benchmark_prompt_quality.py \
  --server-url http://127.0.0.1:PORT
```

In this mode the benchmark does not create or terminate the supplied server.

## Include specialized prompt probes

```bash
.venv/bin/python tests/benchmark/benchmark_prompt_quality.py --specialized
```

This additionally records:

- table image with `Table Recognition:`;
- formula image with `Formula Recognition:`.

These raw results are evidence for later UI/task-mode work, not an automatic production default change.

## Output

By default results are written under:

```text
benchmark-results/glm-ocr-prompts-YYYYMMDD-HHMMSS/
```

The directory contains generated corpus images, `corpus.json`, and `results.json` with per-sample output, elapsed time, CER where applicable, and aggregate prompt statistics.

The production default remains `OCR` until benchmark evidence is reviewed and the roadmap item is explicitly completed.
