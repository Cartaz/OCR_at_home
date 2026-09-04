# Canonical real-world benchmark v2

`run_realworld_suite.py` is the long-form hardware benchmark used to choose the OCR prompt, image/PDF pipeline and relevant `llama-server` runtime settings from labelled real documents.

The benchmark is intentionally expensive. Production defaults are not changed by the suite itself.

## Corpus

Use exactly three representative documents:

1. **FACILE** — digitally generated PDF with normal printed text.
2. **MEDIO** — dense scanned PDF containing a raster page rich in text/details.
3. **DIFFICILE** — one handwritten page, processed as **one single OCR request**.

The handwritten page contains one continuous text whose writing style changes in order:

1. **MAIUSCOLO**
2. **SCRIPT**
3. **CORSIVO**

Do not create three handwritten files. Continuity is deliberate so the model can use the previous text as context while reading the later handwriting.

Use `realworld-ground-truth-template.md`. `DIFFICILE` must contain exactly:

````markdown
# DIFFICILE

## MAIUSCOLO

```text
first continuous part...
```

## SCRIPT

```text
continuation...
```

## CORSIVO

```text
final continuation...
```
````

The OCR output is aligned globally against the complete handwritten ground truth, then the aligned output is scored separately for MAIUSCOLO/SCRIPT/CORSIVO. The image itself is never cropped into three OCR requests.

## Run

Close the desktop OCR application first, then:

```bash
.venv/bin/python tests/benchmark/run_realworld_suite.py
```

Four Qt dialogs select FACILE, MEDIO, DIFFICILE and the Markdown ground truth.

Non-interactive:

```bash
.venv/bin/python tests/benchmark/run_realworld_suite.py \
  --easy /path/digital.pdf \
  --medium /path/dense-scan.pdf \
  --hard /path/handwriting.png \
  --ground-truth /path/ground-truth.md \
  --no-dialog
```

Validate the corpus and inspect the estimated plan without inference:

```bash
.venv/bin/python tests/benchmark/run_realworld_suite.py --plan-only
```

## Statistical protocol

Canonical settings:

- 5 runs for every normal configuration;
- discard one best and one worst value independently for every metric;
- average the middle 3;
- rotate FACILE/MEDIO/DIFFICILE order between runs;
- fresh app-owned `llama-server` for every tested profile, launched with Linux parent-death ownership so a killed benchmark cannot orphan it;
- targeted `POSIX_FADV_DONTNEED`, Python/C heap trimming and bounded recovery toward the invocation's clean `MemAvailable` baseline before and after every profile; no global `drop_caches` and no root requirement;
- non-corpus warm-up after every server start;
- `cache_prompt=false` on benchmark requests;
- any configuration reporting non-zero `cache_n` is excluded from speed decisions;
- FACILE/MEDIO/DIFFICILE have equal macro weight.

A **BORDERLINE** configuration automatically receives five additional runs. Ten-run results use a 20% two-sided trim: discard the two best and two worst values and average the middle six.

## Prompt shootout

Before tuning anything else:

- `OCR`
- `Text Recognition:`

are tested on the same real corpus. The selected prompt is then frozen for Stage A and Stage B.

## Stage A — one factor at a time

Stage A is one global OFAT sweep. It includes both image/pipeline variables and relevant `llama-server` runtime variables.

### Pipeline/input

**PDF DPI**

`100, 125, 150, 175, 200, 250, 300`

**Maximum image dimension**

`1024, 1280, 1536, 1920, 2304, 2560, 3072`

**JPEG quality**

`50, 60, 70, 80, 85, 90, 95, 100`

**Preprocessing**

- `none`
- `contrast`
- `resize`
- `full` — current production resize-if-needed + contrast

Binarization is excluded because it is a different preprocessing algorithm rather than a current-pipeline setting.

### llama-server runtime

The runner inspects the installed `llama-server --help` first and only sweeps variables supported by that build.

Current canonical candidates include:

- context size;
- batch size;
- ubatch size;
- generation thread count;
- batch/prompt thread count;
- Flash Attention (`auto`, `on`, `off`);
- KV cache K type (`f16`, `bf16`, `q8_0`, `q5_0`, `q4_0`);
- KV cache V type (`f16`, `bf16`, `q8_0`, `q5_0`, `q4_0`);
- speculative decoding (`none`, `draft-mtp`) when supported;
- KV offload on/off;
- operation offload on/off.

The benchmark runtime remains SYCL-only, full GPU-layer offload and `--parallel 1`, matching the application's architectural constraints. All tunable runtime flags are omitted in the baseline so the installed llama.cpp build uses its own stock defaults; Stage A then adds one explicit override at a time.

Variables intentionally not treated as OCR inference tuning include process priority/CPU affinity, multi-user parallelism, model load mode/mmap and partial `-ngl`: they either measure host scheduling/startup, a different concurrency workload, or violate the strict full-offload target.

Memory telemetry is sampled throughout every OCR request. Each observation records minimum host `MemAvailable`, minimum free RAM, peak cache, peak swap use, peak `llama-server` RSS and peak benchmark-harness RSS. This system-level signal is especially important on integrated GPUs, where GPU allocations compete with the host for the same physical RAM.

Memory-isolation protocol v3 adds an earlier hard safety floor of **1024 MiB MemAvailable**. If the sampler crosses that floor, it terminates only the benchmark-owned `llama-server`; it never kills unrelated applications. The observation is classified `resource_limit_confirmed`, the whole configuration becomes terminal for that stage, memory is stabilized, and the beam search moves to the next candidate instead of repeating a configuration that is already outside the machine's usable resource envelope.

If `llama-server` terminates for a non-memory reason, the retry is never sent to the dead port. The runner captures exit/log diagnostics, shuts down the owned process group, performs targeted cache eviction and memory stabilization, starts the exact same runtime profile again, performs the non-corpus warm-up and retries the document. Explicit OOM diagnostics are classified as resource limits; ordinary server crashes keep the existing single clean-restart recovery path.

Resume is resource-aware: terminal failures are stored under `terminal_config_failures`. Protocol v3 also refuses to continue after a profile if host RAM does not recover close to the invocation baseline within a bounded timeout; the checkpoint is preserved for a clean resume. Because the benchmark baseline now means actual stock llama.cpp runtime (no tuning flags), checkpoint schema 7 intentionally rejects older schema-6 runs instead of mixing incompatible baselines.

## Quality gates

Quality filtering is **relative**, not an arbitrary absolute handwriting threshold.

PASS requires:

- macro character-accuracy loss <= **0.25 percentage points** from the best valid candidate in the comparison;
- each FACILE/MEDIO/DIFFICILE accuracy loss <= **0.50 pp**;
- each document WER increase <= **1.00 pp**;
- each MAIUSCOLO/SCRIPT/CORSIVO accuracy loss <= **0.50 pp**;
- each handwriting subsegment WER increase <= **1.00 pp**;
- all required runs complete successfully;
- `cache_n == 0`.

BORDERLINE is the narrow band up to:

- macro loss **0.40 pp**;
- document/subsegment accuracy loss **0.75 pp**;
- WER increase **1.50 pp**.

BORDERLINE candidates get five extra runs before the final decision. Beyond those limits the value is FAIL.

This means that if every configuration is poor on cursive handwriting, the benchmark still works: the least-bad configurations can pass the **relative** gate. The report exposes the absolute MAIUSCOLO/SCRIPT/CORSIVO accuracies separately, but does not invent a universal adequacy threshold.

For every Stage A variable, quality filtering happens first; among PASS values the **five fastest** advance. If fewer than five pass, only the passing values advance.

## Stage B — controlled interaction search

A full Cartesian product becomes impractical once server variables are added. Stage B therefore uses a deterministic **beam search** with width 5.

The variables are introduced progressively. At each step:

1. the surviving profiles are combined with the Stage A finalists of the next variable;
2. invalid combinations such as `ubatch > batch` are skipped;
3. every candidate receives the normal five-run protocol;
4. quality gates are applied again;
5. BORDERLINE candidates receive five additional runs;
6. the five fastest PASS profiles survive to the next step.

The current value is always retained as a candidate, so introducing a new variable is never mandatory when it makes the profile worse.

A final confirmation re-runs the surviving complete profiles together with production-baseline controls. This final gate prevents cumulative small regressions from becoming a recommended configuration.

## Output

The result directory contains:

- `checkpoint.json` — atomic resumable state;
- `results.json` — full machine-readable results;
- `inputs.json` — input names and SHA-256 hashes;
- `summary.md` — final recommendation and handwriting breakdown;
- `ranking_accuracy.csv`;
- `ranking_speed.csv`;
- `ranking_recommended.csv`;
- `pareto.csv`;
- `outputs/` — raw OCR text from each run.

Ranking rows include pipeline values, runtime values, overall CER/WER/accuracy, speedup, JPEG transfer size and MAIUSCOLO/SCRIPT/CORSIVO metrics. Per-observation memory telemetry and any runtime-recovery classification are preserved in `checkpoint.json` and `results.json`.

## Resume

The benchmark checkpoints after every document. Resume with:

```bash
.venv/bin/python tests/benchmark/run_realworld_suite.py \
  --resume benchmark-results/realworld-v2-YYYYMMDD-HHMMSS
```

All four input hashes are checked before continuing. Memory isolation is part of the canonical protocol and uses checkpoint schema **7**. Schema 7 marks the stock-runtime baseline and recovery-to-baseline semantics; older checkpoints remain valid historical results but must not be resumed under the new protocol.

The run can also be deliberately split:

```bash
.venv/bin/python tests/benchmark/run_realworld_suite.py --stop-after prompt
.venv/bin/python tests/benchmark/run_realworld_suite.py --resume <dir> --stop-after stage-a
.venv/bin/python tests/benchmark/run_realworld_suite.py --resume <dir>
```

## Privacy

`benchmark-results/` is ignored by Git. Ground truth and real OCR output remain local unless explicitly published.
