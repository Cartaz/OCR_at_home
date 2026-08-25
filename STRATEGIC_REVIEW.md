# Strategic programming reviews

This file makes the project's milestone review rule explicit and persistent. A milestone is not complete only because its feature tests pass: the touched area and the project as a whole must still be understandable and easy to evolve.

## Required milestone review

At each milestone boundary review the whole project and record the result here before starting the next feature milestone.

Check at least:

- whether complexity or special-case behavior increased;
- whether every important mutable state still has one obvious owner;
- whether module boundaries and public interfaces remain coherent;
- whether changes require edits in too many places (change amplification);
- whether layers leak implementation details upward or downward;
- whether duplicated state, validation or policy appeared;
- whether a tactical workaround or monkey-patch entered the design;
- whether concurrency, process ownership, shutdown and error paths remain deterministic;
- whether tests protect behavior rather than implementation accidents;
- what small design investment would make the next change simpler.

Important findings are resolved before continuing. A deferral is acceptable only when it is explicit, scoped and justified here.

## 2026-08-25 — Post-audit review

### Strong areas

- Core OCR/runtime code remains independent from DOM/CSS/JavaScript and largely independent from Qt.
- `OCREngine`, `ProcessManager` and `LlamaServerBackend` have clear process/concurrency ownership.
- The app-owned llama-server lifecycle is bounded and avoids global process killing or `shell=True`.
- Settings are Python-owned, immutable-by-replacement, migration-tolerant and stored outside the source tree.
- The local HTML frontend has a consistent dark-neumorphic design system and real WebEngine smoke coverage.

### Findings being resolved first

- CI baseline guards had drifted from the canonical 16384-token/schema-5 benchmark configuration.
- WebEngine did not explicitly reject remote main-frame navigation.
- `install.sh` accepted Python 3.11 even though the application contract is Python 3.12+.
- Root installation/runtime documentation was missing.

These items are handled in PR #17.

### Deferred architectural work

The following items are intentionally deferred from PR #17 because they are coupled and deserve a separately reviewable refactor rather than being mixed with baseline repair:

1. **Bridge depth/ownership** — `AppWebBridge` currently owns output-workflow and model-memory coordination that belongs behind controller/core interfaces. The target is a thin bridge that validates/converts/serializes only.
2. **Frontend monkey-patching** — `model_ui.js` and `save_ui.js` wrap global functions from `app.js`. Replace this with explicit vanilla-JS modules/registrations; do not introduce a frontend framework.
3. **Benchmark monkey-patching** — the canonical benchmark wrapper mutates imported module globals. Replace this with explicit canonical policy/configuration so importing a module cannot alter another module's behavior.
4. **GUI-thread I/O** — hardware refresh and durable output writes must not perform potentially slow subprocess/filesystem work synchronously in QWebChannel slots.
5. **Canonical completed OCR result** — Python should own the savable completed result rather than accepting the displayed text back from JavaScript as the persistence source.
6. **Controller information hiding** — reduce direct bridge access to `engine` and `process_manager` internals by exposing focused controller snapshots/actions.

### Design direction

Do not replace the existing architecture wholesale. Keep `AppController`, `OCREngine`, `ProcessManager`, QWebChannel and the current EventBus unless a concrete refactor proves they are the source of the problem. Prefer two or three deeper modules with narrow interfaces over additional indirection, factories, dependency-injection infrastructure or a frontend framework.
