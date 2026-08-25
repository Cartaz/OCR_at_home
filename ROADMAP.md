# GLM OCR Roadmap

This roadmap is the persistent implementation plan for the project. Items are checked only after code, tests and CI are complete.

## Status legend

- [ ] planned
- [~] in progress
- [x] completed

## Phase 1 — Correctness and UI consolidation

Goal: make every value and control shown by the application truthful, then remove temporary compatibility layers introduced during the UI rebuild.

- [x] Remove fabricated OCR confidence values.
  - `OCRResult.confidence` becomes optional/unknown when the backend does not provide a real score.
  - Do not show a percentage when no real confidence exists.
  - Remove the unused confidence-threshold setting from the active configuration/UI path.
  - Existing `settings.json` files containing the legacy key must continue to load safely.
- [x] Consolidate the non-blocking WebEngine startup into `WebBridge`.
  - Preserve immediate first-frame rendering.
  - Remove `ResponsiveWebBridge` once equivalent behavior is covered by tests.
- [x] Make the language selector native HTML rather than post-load DOM injection.
  - Preserve Italiano / English / Italiano + English choices.
  - Keep the UI explicit that language is not currently forced in the GLM-OCR prompt.
  - Remove `settings_ui.js` after equivalent markup/style is integrated.
- [x] Keep shutdown/process-lifecycle regressions covered.

Acceptance criteria:
- No fabricated confidence is exposed anywhere.
- Startup remains non-blocking.
- No visual regression in the current dark-neumorphic UI.
- Full CI green.

## Phase 2 — Prompt and OCR quality validation

Goal: improve recognition quality using measured evidence rather than intuition.

- [x] Build a small repeatable OCR evaluation corpus covering:
  - clean printed text;
  - small text;
  - scans/noisy pages;
  - tables;
  - formulas;
  - mixed-layout pages.
- [x] Verify GLM-OCR prompt modes against authoritative model documentation.
- [~] Benchmark the current `OCR` prompt against official text-recognition prompt(s).
  - [x] First hardware-backed synthetic baseline completed: both prompts reached CER 0.0000 on all four text samples.
  - [x] Preserve the first baseline and document why its timing comparison is order-biased.
  - [x] Run and review the repeated synthetic benchmark: 24/24 text runs reached CER 0.0000, confirming a quality tie.
  - [x] Document the strong repeated-input llama-server cache effect; cached wall-clock timings are not prompt-selection evidence.
  - [x] Add a canonical cache-aware runner with true per-sample prompt-order alternation and accuracy-only decision summaries.
  - [x] Add support for labelled real-world corpora through `manifest.json`.
  - [x] Build the canonical three-level real-world suite with an automatic `OCR` vs `Text Recognition:` shootout.
    - FACILE: digital PDF.
    - MEDIO: dense scanned PDF.
    - DIFFICILE: one continuous handwritten page, scored overall and separately as MAIUSCOLO / SCRIPT / CORSIVO without splitting the OCR request.
    - Five-run trimmed means, strict Markdown ground truth and cache-free timing.
  - [ ] Run and review the canonical labelled real-world suite before changing the production default.
- [ ] Add explicit OCR modes only when benchmark evidence supports them:
  - Text;
  - Formula;
  - Table;
  - structured extraction/schema mode if supported by the active backend.
  - Two specialized synthetic baselines: table output matched all cells; formula output repeatedly mistranscribed the `+/-` operator, so formula mode is not validated yet.
- [ ] Reassess the language preference after prompt-mode work; either make it operational or remove it.

Acceptance criteria:
- Prompt changes have reproducible before/after results.
- Default behavior never regresses silently.
- A production prompt change requires labelled real-world evidence.
- Repeated identical-image cache timings are never presented as intrinsic prompt performance.

## Phase 3 — Real output workflow

Goal: turn OCR results into durable files without inventing behavior that does not exist.

- [x] Add `Save result` for single OCR.
- [x] Support `.txt` and `.md` output.
- [x] Add optional automatic batch saving to configured output directory.
  - Each completed task is persisted immediately rather than waiting for the whole batch.
  - Output directory, format and PDF-page policy are frozen at batch start for consistency.
- [x] Use source-derived filenames and safe collision handling.
- [x] Use atomic publication; never silently overwrite existing files.
- [x] PDF output workflow.
  - [x] Save the combined OCR result for a PDF as one `.txt` or `.md` file.
  - [x] Optionally save one numbered file per PDF page for single OCR and batch OCR.
- [x] Make the output-directory setting operational and update its UI description accordingly.
- [x] Reject manual save actions for cancelled, failed or otherwise incomplete single OCR results.

Acceptance criteria:
- Every save action reports success/failure truthfully.
- Existing files are never destroyed without explicit user intent.
- A newly selected source cannot accidentally save the previous document's OCR text under its filename.
- A partial/cancelled PDF cannot be presented as a completed savable result.
- One running batch cannot silently switch output directory/format because settings changed mid-run.
- Output controls execute successfully in the real Qt WebEngine smoke test.

## Phase 4 — Model memory management

Goal: let the user reclaim RAM/VRAM without quitting the application.

- [x] Add `Unload model` / `Stop backend` action.
- [x] Keep the UI alive after unloading.
- [x] Allow explicit reload and safe automatic reload before OCR/batch.
  - At most one user operation can wait for model loading at a time.
  - Cancelling/failing model load clears the queued operation.
- [x] Add optional `Load model at startup` setting.
  - Default remains enabled to preserve existing behavior after upgrade.
- [x] Add optional idle auto-unload after a configurable interval.
  - Default is disabled.
  - The idle clock restarts when the backend returns to idle.
- [x] Keep unload/reload on worker threads so Qt WebEngine remains responsive.
- [x] Preserve app-owned process semantics: no global `pkill` and no changes to the existing process-group termination logic in `LlamaServerBackend`.
- [x] Cover settings, controller coordination, queued reload behavior, explicit/idle unload and real WebEngine model-memory controls in CI.
- [x] Validate on real SYCL hardware that unload releases RAM/VRAM and removes the app-owned `llama-server` PID; then revalidate automatic reload and final exit.
  - Hardware validation completed successfully on 2026-08-21.

Acceptance criteria:
- RAM/VRAM is released after unload.
- No orphan app-owned `llama-server` remains after unload, reload, cancellation or exit.
- The UI remains usable while the model is unloaded and a new OCR transparently reloads it.

## Phase 5 — Pipeline and llama-server benchmarking

Goal: tune OCR input preparation and the relevant llama.cpp runtime from measured accuracy/performance data, without changing production defaults until hardware evidence exists.

- [x] Build benchmark-only pipeline overrides without changing production defaults.
  - PDF DPI, max image dimension and JPEG quality are independently selectable.
  - Preprocessing is separable into `none`, `contrast`, `resize` and `full`; `full` remains equivalent to production behavior.
  - Benchmark requests explicitly disable llama.cpp prompt caching while production requests preserve their existing payload shape.
- [x] Build benchmark-only llama-server runtime profiles without changing the production backend.
  - Detect supported flags from the installed pinned `llama-server --help`.
  - Sweep context size, batch, ubatch, generation threads, prompt/batch threads, Flash Attention, KV K/V cache types, MTP speculative decoding when supported, KV offload and operation offload.
  - Keep SYCL-only, full GPU-layer offload and `--parallel 1` fixed as architectural constraints.
  - Record server RSS as an additional diagnostic.
- [x] Build the canonical real-world benchmark protocol v2.
  - Three labelled difficulty levels: digital PDF, dense scanned PDF and one continuous handwritten page.
  - The handwritten OCR remains one request; global alignment produces MAIUSCOLO / SCRIPT / CORSIVO submetrics.
  - Five runs per configuration; remove one best/fastest and one worst/slowest metric value and average the middle three.
  - Rotate document order, use a non-corpus warm-up and a fresh app-owned server per profile.
  - Apply relative hard quality gates to macro accuracy, every document, every handwriting subsegment and WER.
  - BORDERLINE configurations automatically receive five more runs; ten-run results use a two-sided 20% trim.
  - Stage A sweeps every supported pipeline/runtime variable one factor at a time and advances the five fastest PASS values.
  - Stage B uses a deterministic quality-gated beam search (width 5) rather than an impractical full Cartesian product.
  - Invalid runtime combinations such as `ubatch > batch` are skipped.
  - The current value remains a Stage B candidate so adding a variable is never mandatory.
  - Finalists are re-run with production baseline controls before recommendation, preventing cumulative small quality losses from being accepted silently.
  - CER, WER, character accuracy, end-to-end/request/render/preprocess timing, JPEG bytes, sent dimensions, cache counters, runtime values and handwriting submetrics are retained.
  - Emit accuracy/speed/recommended rankings, Pareto frontier, raw outputs, SHA-256 input identity and resumable checkpoints.
  - `benchmark-results/` is ignored because real OCR output can contain private text.
- [ ] Execute and review the canonical hardware benchmark on the three labelled documents.
  - [ ] Prompt shootout.
  - [ ] Pipeline/input Stage A sweeps.
  - [ ] llama-server runtime Stage A sweeps.
  - [ ] Quality-gated Stage B beam search.
  - [ ] Final confirmation against production baseline controls.
- [ ] Review absolute capability separately for FACILE, MEDIO, DIFFICILE, MAIUSCOLO, SCRIPT and CORSIVO.
  - No arbitrary absolute handwriting threshold is imposed before seeing real results.
  - If all handwriting candidates are poor, relative selection still identifies the least-bad profile while the report preserves the absolute limitation.
- [ ] Change production prompt/pipeline/runtime defaults only if the final hardware results justify the change.

Acceptance criteria:
- Every tuning change has a recorded benchmark rationale.
- No candidate can hide a large handwriting regression behind a good macro average.
- The recommended configuration is the fastest complete profile that survives the final accuracy/word-error gates against the measured reference set.
- Cached requests are not accepted as speed evidence.
- Unsupported or non-starting runtime profiles fail as benchmark candidates rather than changing/falling back the production runtime.

## Phase 6 — End-to-end lifecycle and failure testing

Goal: prevent regressions around the external runtime and long-running operations.

- [x] Add a fake `llama-server` process fixture for lifecycle tests.
  - Uses a real local HTTP subprocess so CI exercises production `Popen`, health-check and process-group teardown logic without SYCL/GGUF inference.
- [x] Cover startup -> ready -> shutdown.
- [x] Cover window close, UI quit, SIGINT and SIGTERM.
  - Existing window/quit wiring regressions plus explicit SIGINT/SIGTERM handler tests cover all desktop exit routes.
- [x] Cover cancellation during model loading.
  - Cancellation closes the owned process while startup is still waiting for health readiness.
- [x] Cover server crash and retry behavior.
  - A simulated connection reset kills the first server and verifies exactly one successful restart/retry.
- [x] Assert no orphan child/process group remains.
  - The fake server spawns a child in its session; shutdown must remove both PIDs and the process group.
- [x] Cover cancellation during single OCR and batch OCR.
  - Cooperative tokens are exercised through the real controller worker and ProcessManager paths until the operation returns to `idle`.
- [x] Verify shutdown remains idempotent after an already-crashed server.

Acceptance criteria:
- Process lifecycle behavior is testable in CI without real SYCL hardware.
- The same app-owned process-group semantics used in production are exercised by CI.
- Full CI green.

## Phase 7 — Daily-use UX

Goal: improve speed of use without adding decorative complexity.

- [ ] Drag and drop images/PDFs.
- [ ] Paste image from clipboard.
- [x] Keyboard shortcuts (`Ctrl+O`, OCR start shortcut, copy result).
  - `Ctrl+O` opens the single-file picker, `Ctrl+Enter` starts OCR or batch according to the active view, and `Ctrl+Shift+C` copies the OCR result.
  - Shortcuts activate existing controls and therefore inherit disabled/busy rules; normal `Ctrl+C` remains untouched.
  - Controls expose `aria-keyshortcuts`/tooltips and real Qt WebEngine coverage dispatches keyboard events through the production listener.
- [x] Remove individual files from a batch before starting.
  - Batch selection remains temporary JavaScript presentation state; no new backend API was introduced.
  - Removal is disabled outside `idle`, so a submitted/running queue cannot be mutated from the UI.
  - Real Qt WebEngine coverage verifies selection cleanup, count/start state and busy protection.
- [x] Review empty/error/loading states for clarity and accessibility.
  - Operational views expose `aria-busy` from the same state that drives the UI controls.
  - Progressbars publish meaningful `aria-valuetext`; result/count changes remain polite live updates.
  - Urgent failures use assertive alert semantics with focus restoration, while informational/success notices remain non-intrusive.
  - Real Qt WebEngine coverage verifies notice roles/focus, busy states and progress text.

Acceptance criteria:
- Features reduce steps without hiding backend state or errors.

## Phase 8 — Repository and release maintenance

Goal: make installation, troubleshooting and upgrades predictable.

- [x] Add a concise `README.md` covering:
  - Intel/SYCL requirements;
  - `chmod +x install.sh && ./install.sh`;
  - `.venv/bin/python main.py`;
  - first model download/startup;
  - configuration/log/model paths;
  - troubleshooting.
- [x] Add/verify log rotation.
- [x] Review dependency version policy for reproducibility without introducing `pyproject.toml`.
  - Runtime dependencies keep tested minimums and major-version ceilings.
  - Test-only dependencies live in `requirements-dev.txt`.
  - llama.cpp remains pinned separately by `install.sh`.
- [x] Keep `CHANGELOG.md` aligned with user-visible changes.
- [~] Periodically remove dead compatibility code and stale tests.
  - The 2026-08-25 strategic cleanup removed bridge/frontend/benchmark compatibility paths that no longer represented useful abstractions.

Acceptance criteria:
- A clean checkout can be installed and diagnosed using repository documentation alone.

## Implementation order

1. Phase 1 correctness.
2. Phase 2 prompt/quality benchmark.
3. Phase 3 output workflow.
4. Phase 4 model memory management.
5. Phase 6 lifecycle tests.
6. Phase 5 pipeline/runtime tuning.
7. Phase 7 UX.
8. Phase 8 repository/release maintenance continuously as needed.

The roadmap is intentionally conservative: correctness and measurable OCR quality take precedence over feature count.
