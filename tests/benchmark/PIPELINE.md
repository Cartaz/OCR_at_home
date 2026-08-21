# GLM-OCR pipeline benchmark

This is the manual, hardware-backed benchmark for Phase 5 of `ROADMAP.md`.
It does **not** change production defaults. The desktop app continues to use:

- preprocessing: enabled;
- PDF render: 150 DPI;
- maximum image dimension: 1920 px;
- JPEG quality: 85;
- prompt: `OCR`.

## Goal

Measure OCR quality and pipeline cost together before changing any image/PDF default. The runner varies one factor at a time:

- preprocessing on/off;
- PDF DPI: 100 / 150 / 200 / 300;
- maximum image dimension: 1280 / 1600 / 1920 / 2560;
- JPEG quality: 70 / 85 / 95.

For each run it stores:

- CER against labelled ground truth;
- end-to-end elapsed time;
- llama-server request time/timings when exposed;
- rendered/preprocessing time for PDFs;
- JPEG bytes sent to llama-server;
- sent dimensions;
- llama-server `cache_n`.

## First pass

Close the desktop app if memory is tight, then run from the repository root:

```bash
.venv/bin/python tests/benchmark/run_pipeline_benchmark.py --quick
```

The quick suite evaluates five configurations: production baseline, preprocessing off, PDF 200 DPI, max dimension 1280, and JPEG quality 70.

## Performance-quality pass

Repeated image requests can be strongly accelerated by llama-server cache state. For latency decisions use:

```bash
.venv/bin/python tests/benchmark/run_pipeline_benchmark.py \
  --restart-server-per-config
```

This restarts the benchmark-owned llama-server before each configuration. Model startup is outside the measured OCR request, so it resets cache state without counting model load time as OCR latency.

Without `--restart-server-per-config`, wall-clock timing is diagnostic only. `results.json` records `cache_n` and the report separately counts cache-free runs.

## Synthetic corpus

The default corpus contains the existing deterministic raster text samples plus a two-page vector PDF. The PDF has one normal-size page and one small-text page so DPI changes have a meaningful target.

Synthetic data is suitable for screening obviously worse configurations. Production defaults should only change after the winning candidates are also checked against representative real documents.

## Real labelled corpus

The same `manifest.json` format used by the prompt benchmark is accepted:

```json
[
  {
    "name": "scan-01",
    "image": "scan-01.png",
    "expected_text": "Trascrizione esatta...",
    "task": "text"
  },
  {
    "name": "document-01",
    "image": "document-01.pdf",
    "expected_text": "--- Pagina 1 ---\nTesto...\n\n--- Pagina 2 ---\nTesto...",
    "task": "text"
  }
]
```

Run:

```bash
.venv/bin/python tests/benchmark/run_pipeline_benchmark.py \
  --corpus-dir /percorso/corpus \
  --restart-server-per-config
```

For multi-page PDFs the expected text must use the same `--- Pagina N ---` separators produced by the application.

## Decision rule

Do not change a production default because it is merely faster. A candidate should:

1. not regress labelled OCR quality;
2. ideally improve difficult-document CER or reduce transfer/request cost materially;
3. have latency evidence collected with controlled cache state;
4. be checked on real representative documents before merge.

The benchmark output is written to `benchmark-results/glm-ocr-pipeline-YYYYMMDD-HHMMSS/results.json`.
