# Prompt decision

Current production prompt: **`Text Recognition:`** (`core/llama_ocr_api.py`, `OCR_PROMPT`).

History:

1. Two synthetic hardware runs (2026-08-21, `baselines/`) produced a quality tie between `OCR` and `Text Recognition:` (CER 0.0000 on every text sample). Timing was order- and cache-biased and was not used.
2. The decision rule required labelled real-world evidence before changing the default.
3. The canonical real-world suite v2 (`REALWORLD.md`) was run on the target SYCL hardware and selected `Text Recognition:`; PR #42 (2026-09-04) promoted it to production together with a tuned runtime profile.
4. PR #43 (2026-09-04) reverted only the runtime tuning to llama.cpp's stock defaults; the prompt decision stands.

`OCR` remains defined (`PROMPT_LEGACY_OCR`) as the benchmark's historical comparison arm. A new production prompt again requires a labelled real-world run of the canonical suite.
