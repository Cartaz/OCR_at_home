# Phase 2 baseline — repeated synthetic SYCL run — 2026-08-21

This baseline records the second hardware-backed run from the target SYCL environment.

## Configuration

- corpus: deterministic synthetic corpus
- preprocessing: enabled
- warm-up rounds: 1
- recorded rounds: 3
- recorded text runs: 24
- production prompt: `OCR`
- candidate prompt: `Text Recognition:`
- specialized probes enabled

## Quality result

Both text prompts achieved CER `0.0000` on every recorded text run:

- `OCR`: 12/12 runs at CER `0.0000`
- `Text Recognition:`: 12/12 runs at CER `0.0000`

Therefore the synthetic corpus provides no evidence that changing the production prompt improves text-recognition accuracy.

## Timing result is cache-contaminated

The run exposed a strong repeated-input cache effect in llama-server. Examples:

- `small_text`: `Text Recognition:` repeatedly took about 20–21 s when first, while the immediately following `OCR` request took about 1.6 s.
- `noisy_scan`: `OCR` repeatedly took about 19–21 s when first, while the immediately following `Text Recognition:` request took about 1.1–1.2 s.
- `mixed_layout`: a first request could take about 36–37 s while the repeated request could complete around 1.4 s.

The reported aggregate timing values (`OCR` mean 7.68 s, `Text Recognition:` mean 12.08 s) therefore do **not** represent intrinsic prompt speed.

The previous schedule also alternated prompt order by current list position after reversing sample order, which did not guarantee that each individual sample changed first-prompt assignment between rounds. Timing conclusions from this baseline are intentionally rejected.

## Specialized prompts

### Table

`Table Recognition:` again returned structurally correct HTML containing every synthetic table cell. Runtime: about 17.34 s.

### Formula

`Formula Recognition:` again produced broadly correct LaTeX-like output but repeated the `+/-` transcription as `+ / -` instead of a proper `\pm`/equivalent operator. Runtime: about 18.95 s.

## Decision

- Keep `OCR` as the production default.
- Treat the synthetic **quality** comparison as a tie.
- Do not use repeated identical-image wall-clock timings for prompt selection.
- Require labelled real-world evidence before changing the production prompt.
- Keep table/formula modes experimental until task-specific quality scoring is broader.
