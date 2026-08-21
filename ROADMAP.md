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
- [ ] Make the language selector native HTML rather than post-load DOM injection.
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

- [ ] Build a small repeatable OCR evaluation corpus covering:
  - clean printed text;
  - small text;
  - scans/noisy pages;
  - tables;
  - formulas;
  - mixed-layout pages.
- [ ] Verify GLM-OCR prompt modes against authoritative model documentation.
- [ ] Benchmark the current `OCR` prompt against official text-recognition prompt(s).
- [ ] Add explicit OCR modes only when benchmark evidence supports them:
  - Text;
  - Formula;
  - Table;
  - structured extraction/schema mode if supported by the active backend.
- [ ] Reassess the language preference after prompt-mode work; either make it operational or remove it.

Acceptance criteria:
- Prompt changes have reproducible before/after results.
- Default behavior never regresses silently.

## Phase 3 — Real output workflow

Goal: turn OCR results into durable files without inventing behavior that does not exist.

- [ ] Add `Save result` for single OCR.
- [ ] Support `.txt` and `.md` output.
- [ ] Add optional automatic batch saving to configured output directory.
- [ ] Use source-derived filenames and safe collision handling.
- [ ] Use atomic writes; never silently overwrite existing files.
- [ ] For PDFs, support a single combined output and optionally per-page output.
- [ ] Make the output-directory setting operational and update its UI description accordingly.

Acceptance criteria:
- Every save action reports success/failure truthfully.
- Existing files are never destroyed without explicit user intent.

## Phase 4 — Model memory management

Goal: let the user reclaim RAM/VRAM without quitting the application.

- [ ] Add `Unload model` / `Stop backend` action.
- [ ] Keep the UI alive after unloading.
- [ ] Allow explicit reload and safe automatic reload before OCR.
- [ ] Evaluate an optional `Load model at startup` setting.
- [ ] Evaluate optional idle auto-unload after a configurable interval.
- [ ] Ensure every unload/reload path owns and terminates only the app-created `llama-server` process group.

Acceptance criteria:
- RAM/VRAM is released after unload.
- No orphan `llama-server` remains after unload, reload, cancellation or exit.

## Phase 5 — Image/PDF pipeline benchmarking

Goal: tune preprocessing and rendering only from measured accuracy/performance data.

- [ ] Benchmark PDF render DPI (including current 150 DPI behavior).
- [ ] Benchmark preprocessing enabled/disabled by document class.
- [ ] Benchmark maximum image dimension.
- [ ] Benchmark JPEG quality / transfer cost.
- [ ] Measure OCR quality and end-to-end latency together.
- [ ] Change defaults only if results justify the change.

Acceptance criteria:
- Every tuning change has a recorded benchmark rationale.

## Phase 6 — End-to-end lifecycle and failure testing

Goal: prevent regressions around the external runtime and long-running operations.

- [ ] Add a fake `llama-server` process fixture for lifecycle tests.
- [ ] Cover startup -> ready -> shutdown.
- [ ] Cover window close, UI quit, SIGINT and SIGTERM.
- [ ] Cover cancellation during model loading.
- [ ] Cover server crash and retry behavior.
- [ ] Assert no orphan child/process group remains.
- [ ] Cover cancellation during single OCR and batch OCR.

Acceptance criteria:
- Process lifecycle behavior is testable in CI without real SYCL hardware.

## Phase 7 — Daily-use UX

Goal: improve speed of use without adding decorative complexity.

- [ ] Drag and drop images/PDFs.
- [ ] Paste image from clipboard.
- [ ] Keyboard shortcuts (`Ctrl+O`, OCR start shortcut, copy result).
- [ ] Remove individual files from a batch before starting.
- [ ] Review empty/error/loading states for clarity and accessibility.

Acceptance criteria:
- Features reduce steps without hiding backend state or errors.

## Phase 8 — Repository and release maintenance

Goal: make installation, troubleshooting and upgrades predictable.

- [ ] Add a concise `README.md` covering:
  - Intel/SYCL requirements;
  - `chmod +x install.sh && ./install.sh`;
  - `.venv/bin/python main.py`;
  - first model download/startup;
  - configuration/log/model paths;
  - troubleshooting.
- [ ] Add/verify log rotation.
- [ ] Review dependency version policy for reproducibility without introducing `pyproject.toml`.
- [ ] Keep `CHANGELOG.md` aligned with user-visible changes.
- [ ] Periodically remove dead compatibility code and stale tests.

Acceptance criteria:
- A clean checkout can be installed and diagnosed using repository documentation alone.

## Implementation order

1. Phase 1 correctness.
2. Phase 2 prompt/quality benchmark.
3. Phase 3 output workflow.
4. Phase 4 model memory management.
5. Phase 6 lifecycle tests (some tests may be pulled forward when relevant).
6. Phase 5 pipeline tuning.
7. Phase 7 UX.
8. Phase 8 repository/release maintenance continuously as needed.

The roadmap is intentionally conservative: correctness and measurable OCR quality take precedence over feature count.
