# Prompt decision gate

Current production decision: **keep `OCR` as the default prompt**.

Evidence so far:

- the first synthetic hardware run produced CER `0.0000` for both `OCR` and `Text Recognition:` on all four text samples;
- the first timing means cannot be compared fairly because all `OCR` runs executed before all candidate runs;
- `Table Recognition:` produced correct HTML for the first synthetic table probe;
- `Formula Recognition:` produced broadly correct LaTeX-like output but mistranscribed the `+/-` operator.

Before changing the production default, Phase 2 requires:

1. a repeated counterbalanced synthetic run using the current benchmark runner;
2. at least one labelled real-world text corpus;
3. review of paired CER and timing deltas rather than unpaired means.

This file records the decision rule so later implementation does not silently treat an encouraging single run as sufficient evidence.
