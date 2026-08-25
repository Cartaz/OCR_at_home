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

#### Remaining important findings at that milestone

1. **GUI-thread hardware probing.** `WebBridge.refreshHardware()` still performed `get_available_devices(refresh=True)` synchronously in a QWebChannel slot and backend initialization used a bridge-owned worker.
2. **GUI-thread filesystem I/O.** Manual OCR save actions still called durable output writers synchronously through QWebChannel, while log polling read the whole file.
3. **Frontend monkey-patching.** `save_ui.js` and `model_ui.js` replaced shared global functions and depended on script ordering.
4. **Base/subclass bridge duplication.** `WebBridge` contained implementations overridden by `AppWebBridge`.
5. **Global EventBus.** It remained an implicit dependency and was deliberately deferred because replacing it was disproportionate to the concrete problems being solved.

#### Decision before next milestone

Resolve hardware probing first, then bounded log/output I/O and frontend monkey-patching. EventBus replacement remains deferred unless it becomes a concrete obstacle.

## 2026-08-25 — Post responsiveness/ownership milestone review

### What is now resolved

- Hardware initialization and manual refresh run through one controller-owned hardware worker lane. `WebBridge` no longer owns an initialization thread and QWebChannel does not execute detector subprocess probes directly.
- Application logs rotate at a bounded size and the UI reads only a bounded tail rather than the full historical file on every poll.
- `app.js` exposes explicit vanilla-JS extension hooks; `save_ui.js` and `model_ui.js` no longer monkey-patch shared functions, and save readiness no longer depends on `MutationObserver` inference.
- Manual OCR persistence is asynchronous from the GUI perspective. `OutputWorkflow` owns exactly one manual-output worker, snapshots the canonical result/settings before dispatch, and emits completion/failure events. QWebChannel save slots return a request id immediately and never perform durable output writes themselves.
- Manual-output shutdown is bounded and deterministic; a second manual save is rejected while the owned worker is alive.
- The final PR validation for this sequence passed Python compilation, package/shell syntax and the complete test suite: 165 tests green, including deliberately blocked hardware/output workers and WebEngine/UI smoke coverage.

### Strategic assessment

Complexity decreased in the presentation layer and moved downward only where the lower module is the natural owner. The new asynchronous paths do not introduce a generic worker framework, task queue, dependency-injection system or second event bus. Hardware lifecycle stays with `AppController`; durable result state and persistence stay with `OutputWorkflow`; filesystem publication stays with `output_writer`; Qt/JavaScript only request actions and display events.

The most important mutable states now have clear owners: operation/model/hardware coordination in `AppController`, batch processing in `ProcessManager`, model backend lifecycle in `OCREngine`/`LlamaServerBackend`, completed OCR/output policy in `OutputWorkflow`, and presentation-only state in JavaScript. The refactors therefore reduce hidden dependencies and change amplification rather than merely relocating code.

### Remaining findings and explicit deferrals

1. **Bridge inheritance/duplication — next architectural cleanup candidate.** `WebBridge` still defines OCR/batch/settings slots that `AppWebBridge` overrides. This is understandable today but creates two apparent implementations for some public QWebChannel actions. Review whether collapsing to one bridge or extracting focused validation helpers makes the interface shallower without changing behavior.
2. **Small settings writes still occur synchronously from presentation calls.** `updateSettings()` and debounced window-size persistence eventually call the small settings abstraction synchronously. These writes are bounded local configuration I/O and are not currently observed as a responsiveness problem, unlike hardware probes or OCR output `fsync`. Defer worker machinery unless measurement or a concrete failure justifies it.
3. **Path validation performs local metadata I/O in the bridge.** `Path.is_file()`, suffix checks and `stat()` are intentionally retained at the input boundary. They are small validation operations; moving them to a worker would complicate native file-selection flow without current evidence of benefit.
4. **Global EventBus remains implicit infrastructure.** It now cleanly carries core events to `EventBridge` and `OutputWorkflow`, and current ownership is understandable. Replacing it would be a broad migration with no demonstrated payoff; defer until a concrete dependency or testing problem appears.
5. **Compatibility accessors on `AppController`.** Direct `engine` and `process_manager` properties remain for tests/integrations even though presentation code now uses focused APIs. Keep them for compatibility unless their presence starts encouraging layer leakage.

### Decision before further feature work

Review the `WebBridge`/`AppWebBridge` inheritance boundary next because it is the clearest remaining source of duplicated public behavior and cognitive load. Do not introduce asynchronous infrastructure for tiny settings/path metadata operations without evidence. Keep the EventBus unless a concrete next change demonstrates that it is the source of complexity.

## 2026-08-25 — Post single-bridge milestone review

### What is now resolved

- `AppWebBridge` has been removed completely; there is one concrete `WebBridge` and one implementation for every QWebChannel slot.
- `main.py`, model-memory tests and output-workflow bridge tests all instantiate the same bridge type.
- The Qt idle timer moved into `WebBridge` as a native scheduling concern only; the auto-unload decision remains in `AppController`.
- The merged bridge still contains no domain algorithms, output writers, model/hardware workers or persistent operational state. Its responsibilities are limited to input validation/conversion, serialization, native dialogs/clipboard/window integration, Qt scheduling and delegation.
- PR #27 reduced the presentation layer overall (`+110/-206` across the reviewable change) and its GitHub Actions run passed Python compilation, package/shell syntax and the complete unit/UI suite.

### Strategic assessment

Collapsing the inheritance boundary reduced cognitive load without moving business logic upward. The previous subclass no longer represented a distinct abstraction: it existed mainly to override public slots already present on the base class. A single adapter therefore has a larger source file but a substantially simpler public mental model: one QWebChannel object, one implementation path, one shutdown path.

The remaining settings normalization in `WebBridge.updateSettings()` is not currently considered accidental duplication with `Settings.load()`. The two paths serve different abstraction levels: the bridge validates/converts untrusted UI inputs before delegation, while `Settings.load()` repairs/migrates persisted configuration. Moving all bridge validation into `Settings` would blur that distinction and would not currently reduce change amplification enough to justify another abstraction.

### Remaining explicit deferrals

1. **Small settings writes on the Qt thread.** Persisting the compact local JSON settings file remains synchronous. This is intentionally deferred because no measurable responsiveness problem has been observed and adding a settings worker would increase lifecycle/concurrency surface area.
2. **Local path metadata validation.** `is_file()`/`stat()` remain in the bridge input boundary. They are bounded validation operations and currently fit the bridge contract.
3. **Global EventBus.** It remains implicit infrastructure but is no longer obstructing ownership or testing. Replacing it now would be speculative architecture.
4. **Compatibility accessors on `AppController`.** Direct `engine`/`process_manager` properties remain for tests/integrations. Production presentation code uses focused APIs, so removal is deferred until there is a concrete compatibility decision.

### Decision before further cleanup

No further architectural migration is justified solely by the current strategic review. Before changing more structure, perform targeted bug hunting for concrete correctness, race, shutdown or error-path issues. Treat any new friction as a design signal, but do not refactor the settings/EventBus/accessor deferrals without evidence.

## 2026-08-25 — Post-cleanup bug-hunting review

### Concrete bugs found and resolved

1. **Lifecycle events could disappear before reaching the UI.** `EventBridge` was not subscribed to several completion/failure events already consumed by `WebBridge`/JavaScript, including model load results and backend/hardware failures. PR #28 completed the existing EventBus→Qt contract and added behavioral forwarding coverage.
2. **Failed multipage saves could leave silent partial output sets.** `write_ocr_pages()` published pages independently. PR #29 now rolls back only the files created by the current invocation if a later page fails, fsyncs the directory after rollback, and surfaces rollback failure explicitly. Collision-safe pre-existing files remain untouched.
3. **Batch result events could race ahead of `batch_started`.** `ProcessManager` previously submitted its worker before emitting the start event. A fast worker could therefore produce task/completion events before `OutputWorkflow` froze batch output settings. PR #30 now reserves the job, publishes `batch_started`, then makes the worker executable; submit and Future registration remain protected together, and submit failure closes the lifecycle with `batch_failed`. A deliberately eager executor test reproduces the historical race deterministically.
4. **Settings publication could destroy the last valid configuration.** `Settings.save()` previously truncated the canonical JSON before the new state was durable. PR #31 now writes and fsyncs a same-directory temporary file, publishes it with atomic replacement, fsyncs the parent directory where supported, and preserves the previous settings file if publication fails.
5. **A synchronous startup worker-start failure could make initialization permanently non-retryable.** `AppController.initialize()` marked itself initialized before the startup model worker was successfully launched. PR #32 now sets the initialization guard only after that request succeeds; a deterministic regression verifies that a failed first attempt returns to idle and a second attempt can initialize normally.

All five fixes stayed inside the modules that already owned the affected responsibility; no new manager, event system, worker framework or compatibility layer was introduced. Their full GitHub Actions validations passed Python compilation, package/shell syntax and the complete test suite.

### Remaining shutdown limitation

`ProcessManager.shutdown()` cancels the active token and waits for the single batch worker. The normal llama-server HTTP path is actively cancellable because the token closes the socket, and the HTTP connection also has a finite timeout. However, a pathological native/local operation inside image/PDF loading, rendering or preprocessing could theoretically block Python execution beyond that cancellation point. A thread timeout would not make engine destruction safe and would only create a false bounded-shutdown guarantee while the worker could still access the engine.

This is therefore an explicit operational limitation, not a deferred one-line fix. If real hangs are observed in those native stages, the correct design response is process isolation (or another genuinely interruptible execution boundary) for the affected heavy work, with deterministic child-process termination. Do not add a timeout that abandons a live thread and then destroys shared OCR resources.

### Strategic assessment after bug hunting

The bug hunt validated the current ownership model rather than exposing a need for another architecture. The failures were local contract/order/durability problems: incomplete event forwarding, non-transactional logical page publication, worker activation occurring before lifecycle publication, non-atomic settings replacement, and premature startup initialization state. Each was fixed by strengthening the existing owner and adding deterministic regression coverage.

No current evidence justifies replacing EventBus, moving tiny settings writes to worker infrastructure, removing compatibility accessors, or introducing a generic retry/transaction framework. Future structural work should continue to be driven by an observed failure, change amplification or ownership leak rather than by cleanup for its own sake.

### Decision after the bug-hunting cycle

Stop structural cleanup here. The audited areas now have explicit ownership, deterministic tests for the observed races/failure paths, and no remaining local defect that warrants additional architecture. Resume feature/milestone work; repeat the strategic whole-project review at the next milestone boundary.

### Design direction

Do not replace the existing architecture wholesale. Keep `AppController`, `OCREngine`, `ProcessManager`, QWebChannel and the current EventBus unless a concrete refactor proves they are the source of the problem. Prefer deeper modules with narrow interfaces over additional indirection, factories, dependency-injection infrastructure or a frontend framework.

## 2026-08-25 — Post Phase 7 daily-use UX milestone review

### Complexity and ownership

Phase 7 reduced user interaction cost without moving operational authority into JavaScript. Single/batch selection remains temporary presentation state; filesystem validation remains at the Python bridge boundary; drag-and-drop acquisition remains native Qt; clipboard persistence is isolated in the focused `InputStaging` core service. `main.py` remains wiring-only and no new persistent application state was added.

The clipboard feature initially expanded the responsibility of `drop_ui.js`; the milestone review treated that naming mismatch as architectural drift rather than leaving it in place. The module was renamed to `input_ui.js`, where drag-and-drop and clipboard now share the same local-input selection transitions. This removes duplicated presentation behavior and gives future local input methods one obvious integration point.

`InputStaging` is intentionally small but deep: callers provide PNG bytes and receive a local path, while session-directory creation, size enforcement, publication cleanup and idempotent shutdown remain hidden. JavaScript never receives raw clipboard bytes or arbitrary filesystem access. `WebBridge` performs only the Qt-specific `QImage`→PNG adaptation and delegates storage ownership downward.

### Concurrency, lifecycle and failure paths

Phase 7 introduced no new background worker or polling mechanism. Clipboard conversion/staging is bounded local work and is rejected while another user operation is active. Transient files are removed deterministically during bridge shutdown. Existing OCR/model/process cancellation ownership remains unchanged.

The final drag/drop work also exposed a real model-lifecycle race: `operation` could become `idle` before the asynchronous model worker released ownership. That was fixed at the owner boundary in `AppController`, and a deterministic regression now asserts that every lifecycle transition to `idle` observes no owned model worker.

### Tests and change amplification

Behavioral coverage is split by responsibility: core tests exercise transient staging and cleanup; bridge tests exercise native clipboard conversion and busy rejection; native-shell tests exercise local URL filtering; real Qt WebEngine tests exercise drag/drop routing, clipboard routing, accessibility metadata and preservation of ordinary text paste. Tests therefore protect contracts rather than source-string accidents.

Adding clipboard support did not require changes to OCR/domain algorithms, persistence/output workflow, model runtime, batch processing or `main.py`. The main cross-layer changes were the expected input boundary, presentation adapter/module and focused tests, indicating controlled change amplification.

### Remaining explicit deferrals

The previously recorded deferrals remain unchanged: tiny settings writes and local path metadata checks stay synchronous; EventBus remains because it is not currently a source of concrete complexity; compatibility accessors remain for tests/integrations. None became harder to reason about during Phase 7.

### Decision after Phase 7

Phase 7 is strategically complete. No additional abstraction or cleanup is justified before the next roadmap work. Continue with measured benchmark/quality work and repository maintenance, and repeat the whole-project strategic review at the next milestone boundary.
