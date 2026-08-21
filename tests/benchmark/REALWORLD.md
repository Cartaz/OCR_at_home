# Canonical real-world benchmark

`run_realworld_suite.py` is the long-form hardware benchmark used to choose the production OCR prompt and pipeline defaults from labelled real documents.

It is deliberately expensive. The canonical protocol uses five runs for every configuration, removes one best and one worst observation independently for every metric, and averages the middle three values.

## Corpus

Use exactly three representative documents:

1. **FACILE** — a digitally-generated PDF with normal printed text.
2. **MEDIO** — a dense scanned PDF containing a raster page with many details/text elements.
3. **DIFFICILE** — one clearly handwritten page with good handwriting; PDF or supported raster image.

Provide one Markdown ground-truth file using the exact structure in `realworld-ground-truth-template.md`:

```markdown
# FACILE

```text
exact transcription...
```

# MEDIO

```text
exact transcription...
```

# DIFFICILE

```text
exact transcription...
```
```

The parser is intentionally strict. The benchmark aborts if any section is missing or empty. Application-added `--- Pagina N ---` markers are removed before scoring; other OCR formatting remains part of the evaluated output.

## Canonical run

From the repository root, close the desktop OCR application and run:

```bash
.venv/bin/python tests/benchmark/run_realworld_suite.py
```

If file arguments are omitted, four native Qt file dialogs ask for FACILE, MEDIO, DIFFICILE and the ground-truth Markdown file.

The non-interactive equivalent is:

```bash
.venv/bin/python tests/benchmark/run_realworld_suite.py \
  --easy /path/digital.pdf \
  --medium /path/dense-scan.pdf \
  --hard /path/handwriting.png \
  --ground-truth /path/ground-truth.md \
  --no-dialog
```

Before inference the script prints the maximum number of OCR requests. Use `--plan-only` to validate inputs and inspect the plan without starting `llama-server`.

## Statistical protocol

Canonical defaults:

- 5 runs per configuration;
- trim 1 lowest/best and 1 highest/worst observation independently for each metric;
- mean of the remaining 3 observations;
- request order rotates across FACILE/MEDIO/DIFFICILE;
- one fresh app-owned `llama-server` per configuration;
- a non-corpus warm-up image is run after each server start;
- benchmark requests explicitly send `cache_prompt=false`;
- configurations with non-zero reported `cache_n` are excluded from speed-based decisions;
- FACILE/MEDIO/DIFFICILE have equal weight in macro accuracy.

The production application request remains unchanged: the cache override is benchmark-only.

## Prompt shootout

The first stage compares:

- `OCR`;
- `Text Recognition:`.

Both use the current production pipeline. The highest macro character accuracy wins unless both prompts are within the configured accuracy tolerance (default `0.25` percentage points); in that case the faster prompt is selected.

That chosen prompt is frozen for Stage A and Stage B, so the large pipeline matrix is not doubled unnecessarily.

## Stage A — one factor at a time

Starting from the production baseline, the suite sweeps one variable at a time:

### PDF DPI

`100, 125, 150, 175, 200, 250, 300`

DPI runs are scored only on PDF inputs because the value does not affect raster files.

### Maximum image dimension

`1024, 1280, 1536, 1920, 2304, 2560, 3072`

### JPEG quality

`50, 60, 70, 80, 85, 90, 95, 100`

### Preprocessing mode

- `none`
- `contrast`
- `resize`
- `full` — current production behavior (resize-if-needed + contrast)

Binarization is intentionally not included because it is not part of the current production `enhance()` pipeline and would be a separate algorithmic experiment.

For each variable, values outside the quality gate are removed first. Among the values that remain within `0.25` percentage points of the best Stage A character accuracy, the **five fastest values** are selected. Preprocessing has only four possible values, so at most four can advance.

If fewer than five values satisfy the quality gate, only the passing values advance; the suite never silently promotes a known quality regression merely to fill five slots.

## Stage B — finalist combinations

Stage B takes the Cartesian product of the selected Stage A values. With 5 DPI × 5 max dimensions × 5 JPEG values × 4 preprocessing modes, the maximum is **500 configurations**.

Every Stage B configuration still receives five runs and trimmed-mean scoring. A production-baseline control is measured at both the start and end of Stage B; their per-document timing average is used for the reported speedup baseline. Finalist order is deterministically shuffled with a fixed seed to reduce simple time/thermal ordering bias.

## Rankings

The suite writes:

- `ranking_accuracy.csv` — highest macro character accuracy first;
- `ranking_speed.csv` — lowest trimmed mean document time first;
- `ranking_recommended.csv` — speed-ranked configs inside the accuracy tolerance of the best result;
- `pareto.csv` — non-dominated speed/accuracy configurations;
- `summary.md` — human-readable recommendation;
- `results.json` — complete machine-readable benchmark state;
- `inputs.json` — filenames and SHA-256 identifiers;
- `outputs/` — raw OCR text for every run.

The recommended configuration is the **fastest configuration within the accuracy tolerance of the best measured Stage B accuracy**. This avoids arbitrary 50/50 speed-vs-quality scoring.

Character Error Rate (CER), Word Error Rate (WER), character accuracy, end-to-end time, request time, PDF render time, preprocessing time, sent image dimensions, JPEG bytes and llama.cpp cache/timing counters are retained.

## Resume

The benchmark writes `checkpoint.json` atomically after every document. If it is interrupted:

```bash
.venv/bin/python tests/benchmark/run_realworld_suite.py \
  --resume benchmark-results/realworld-YYYYMMDD-HHMMSS
```

The script re-hashes all four inputs and refuses to resume if any document or ground-truth file changed. Successful observations already present in the checkpoint are skipped; failed/missing observations can be retried.

You can also split the benchmark deliberately:

```bash
# Prompt only
.venv/bin/python tests/benchmark/run_realworld_suite.py --stop-after prompt

# Later resume through Stage A
.venv/bin/python tests/benchmark/run_realworld_suite.py --resume <dir> --stop-after stage-a

# Finally complete Stage B
.venv/bin/python tests/benchmark/run_realworld_suite.py --resume <dir>
```

## Privacy

`benchmark-results/` is ignored by Git. Real OCR outputs and transcriptions may contain private text and must remain local unless explicitly intended for publication.

## Non-canonical speed modes

`--keep-server` reuses one owned server across configurations. `--server-url` uses an external server. Both are useful for development, but the canonical speed comparison is the default mode with a fresh server per configuration.
