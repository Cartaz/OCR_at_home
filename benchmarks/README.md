# GLM-OCR hardware benchmark

This directory holds the manual, hardware-backed benchmark that decides production OCR defaults (prompt, image/PDF pipeline, `llama-server` runtime flags). It needs a working SYCL `llama-server` and the GGUF models, so it never runs in CI; its deterministic helpers are unit-tested under `benchmarks/tests/` and run with the normal `pytest`.

## Canonical runner

```bash
.venv/bin/python benchmarks/run_realworld_suite.py --help
```

`run_realworld_suite.py` validates any resume checkpoint against the current protocol and runtime, then runs the real-world suite v2 described in [`REALWORLD.md`](REALWORLD.md): three labelled documents (FACILE, MEDIO, DIFFICILE with MAIUSCOLO/SCRIPT/CORSIVO segments), five-run trimmed means, cache-free timing, quality gates and memory-isolation guards. [`QUALITY_REFERENCE.md`](QUALITY_REFERENCE.md) explains how the quality reference is chosen.

The baseline of every comparison is the production configuration: the production prompt and llama.cpp's stock runtime defaults (no tuning flags). Candidates add one explicit override at a time.

## Decisions and history

- [`DECISION.md`](DECISION.md) records the production prompt decision.
- `baselines/` preserves the two earlier synthetic prompt runs (2026-08-21). They showed a quality tie between `OCR` and `Text Recognition:` and a strong repeated-image cache effect, which is why wall-clock time on repeated identical requests is never used as prompt evidence.

The task prompts come from the official `zai-org/GLM-OCR` repository (`Text Recognition:`, `Table Recognition:`, `Formula Recognition:`): https://github.com/zai-org/GLM-OCR/blob/main/glmocr/config.yaml. This project sends a whole image/page directly to GLM-OCR through llama.cpp, so table/formula prompts are not equivalent to the upstream layout pipeline and are not production modes.
