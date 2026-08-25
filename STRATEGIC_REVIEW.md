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

### Findings resolved in the first cleanup sequence

- CI baseline guards were aligned with the canonical 16384-token/schema-5 benchmark configuration.
- WebEngine now explicitly rejects non-local application navigation and delegates HTTP/HTTPS to the system browser.
- `install.sh` now enforces Python 3.12+ and verifies critical Python/Qt imports.
- Root installation/runtime documentation now describes implemented behavior.
- The canonical benchmark no longer mutates imported module globals; canonical policy is explicit.
- Completed single-OCR output and frozen batch-output policy are owned by `core/output_workflow.py` through `AppController`.
- JavaScript no longer sends displayed OCR text back to Python as the persistence source.
- Model load/unload workers, queued OCR/batch resumption and idle auto-unload policy are owned by `AppController`; Qt retains only the scheduling timer and presentation bridge.
- Presentation code uses focused controller runtime properties instead of reading engine/process-manager internals for bootstrap state.

### 2026-08-25 — Post model-lifecycle milestone review

#### Complexity and ownership

The cleanup reduced rather than moved complexity. Output policy has one owner (`OutputWorkflow`), model lifecycle has one operational owner (`AppController`), and the bridge no longer owns duplicate model/output state. Existing low-level runtime/process ownership in `OCREngine`, `ProcessManager` and `LlamaServerBackend` remains unchanged.

No new framework, event bus, dependency-injection layer or speculative abstraction was introduced. The controller became deeper because it now hides lifecycle coordination that presentation code previously had to understand; this is intentional information hiding rather than layer growth.

#### Remaining important findings

1. **GUI-thread hardware probing — next priority.** `WebBridge.refreshHardware()` still performs `get_available_devices(refresh=True)` synchronously in a QWebChannel slot. The detector may launch `llama-server --list-devices`, version/help probes and `lspci`, so refresh can freeze Qt for seconds. Backend initialization is also scheduled by a bridge-owned `_init_thread`. Target: controller-owned asynchronous hardware initialization/refresh with events; bridge only requests the action and serializes state.
2. **GUI-thread filesystem I/O.** Manual OCR save actions still call durable output writers synchronously through a QWebChannel slot, including `fsync` and potentially many PDF page files. `getLogs()` also reads the whole log file synchronously and the frontend polls it. Target: move potentially slow output/log work behind focused Python services/workers without adding bridge-owned worker policy.
3. **Frontend monkey-patching.** `save_ui.js` and `model_ui.js` still replace globals such as `applySettings`, `callNative`, `handleEvent`, `updateOperationUi` and `updateBackendPanel`. This creates script-order dependencies and obscures call flow. Target: explicit vanilla-JS registration/hooks or ES modules; no framework and no build step.
4. **Base/subclass bridge duplication.** `WebBridge` still contains base implementations of OCR/batch/settings actions that `AppWebBridge` overrides. Once asynchronous hardware ownership is moved down, review whether one bridge with focused helpers is clearer than the current inheritance boundary.
5. **Global EventBus.** It remains an implicit dependency across core modules. It is deliberately deferred because current ownership refactors do not require replacing it and a broad event-system migration would be disproportionate. Reassess only if it materially obstructs the next changes.

#### Decision before next milestone

Resolve GUI-thread hardware probing before feature work. It is a correctness/responsiveness issue and also enables removal of the remaining bridge-owned initialization thread. After that, address synchronous output/log I/O, then remove frontend monkey-patching. EventBus replacement remains deferred with explicit justification.

### Design direction

Do not replace the existing architecture wholesale. Keep `AppController`, `OCREngine`, `ProcessManager`, QWebChannel and the current EventBus unless a concrete refactor proves they are the source of the problem. Prefer two or three deeper modules with narrow interfaces over additional indirection, factories, dependency-injection infrastructure or a frontend framework.
