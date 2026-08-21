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

## Methodology

The first hardware run produced a quality tie on the synthetic text corpus, but its timing was order-biased because every `OCR` request ran before every `Text Recognition:` request. That result is preserved under `baselines/` and is deliberately **not** used to change the production default.

The current runner removes that weakness by:

- performing unrecorded warm-up requests for both text prompts;
- repeating the comparison for multiple rounds;
- alternating which prompt runs first for each sample;
- reversing sample order on alternating rounds;
- calculating both aggregate and paired timing statistics;
- keeping CER comparisons paired by identical sample and round.

Default settings are one warm-up round and three recorded rounds.

## Synthetic corpus

Without extra arguments, `benchmark_prompt_quality.py` creates a deterministic synthetic corpus at runtime, so no binary fixtures need to be committed. It covers:

- clean printed text;
- small text;
- noisy/scan-like text;
- a table;
- formulas;
- a mixed-layout page.

Text-oriented samples are scored with character error rate (CER) after conservative whitespace normalization. Table and formula samples can also be run with their official prompts and are stored as raw outputs for manual inspection.

## Run the counterbalanced benchmark

From the repository root:

```bash
.venv/bin/python tests/benchmark/benchmark_prompt_quality.py --specialized
```

This now performs three counterbalanced rounds by default. To change the repetition count:

```bash
.venv/bin/python tests/benchmark/benchmark_prompt_quality.py \
  --rounds 2 \
  --warmup-rounds 1 \
  --specialized
```

The runner creates and owns a `LlamaServerBackend`, starts the same SYCL/full-offload runtime used by the application, performs the benchmark, then shuts the process down in `finally`.

Do not keep the desktop application open while using this mode if RAM/VRAM is tight.

## Run against an already-running compatible server

```bash
.venv/bin/python tests/benchmark/benchmark_prompt_quality.py \
  --server-url http://127.0.0.1:PORT
```

In this mode the benchmark does not create or terminate the supplied server.

## Real-world labelled corpus

Synthetic pages are useful for deterministic regressions but are too easy to decide a production OCR prompt. The runner can therefore consume a directory of real images with a `manifest.json`:

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
.venv/bin/python tests/benchmark/benchmark_prompt_quality.py \
  --corpus-dir /percorso/my-real-corpus \
  --rounds 3
```

Supported `task` values are `text`, `table`, and `formula`; supported `score_mode` values are `cer` and `manual`. The prompt comparison itself uses `task=text` samples. Paths in the manifest are constrained to the corpus directory.

## Specialized prompt probes

`--specialized` additionally records:

- table samples with `Table Recognition:`;
- formula samples with `Formula Recognition:`.

These raw results are evidence for later UI/task-mode work, not an automatic production default change. The first formula probe already demonstrated why this distinction matters: broadly correct LaTeX-like output still contained an operator transcription error.

## Output

By default results are written under:

```text
benchmark-results/glm-ocr-prompts-YYYYMMDD-HHMMSS/
```

The directory contains generated corpus images (for synthetic mode), `corpus.json`, and `results.json` with:

- per-sample output;
- elapsed time;
- CER where applicable;
- round and execution sequence;
- aggregate mean/median statistics;
- paired `Text Recognition:` minus `OCR` timing and CER deltas.

A negative paired timing delta means the candidate prompt was faster for the same sample/round. A negative paired CER delta means the candidate prompt had lower error.

The production default remains `OCR` until repeated and real-world benchmark evidence is reviewed and the roadmap item is explicitly completed.
