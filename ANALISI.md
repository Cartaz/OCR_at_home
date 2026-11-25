# ANALISI — GLM OCR (audit completo, 2026-11-20)

> Solo analisi: nessun file del progetto è stato modificato (questo report è l'unica aggiunta).
> Legenda delle prove: **[ESEGUITO]** verificato eseguendo comandi · **[CODICE]** verificato leggendo il codice · **[SOSPETTO]** ipotesi non dimostrata.

## Riassunto in 5 righe

1. Il cuore dell'app (controller, cancellazione, processo `llama-server` posseduto dall'app, scritture atomiche) è solido. I 209 test passano e l'app si avvia: **va tenuta e sistemata, non riscritta**.
2. I problemi che contano davvero sono pochi: **Pillow bloccato a `<13` con 42 vulnerabilità note**, un **crash all'avvio con `settings.json` malformato** (il README sostiene il contrario) e un **lock che può bloccare la GUI o la chiusura** durante il caricamento del modello.
3. La documentazione contraddice il codice sul **prompt di produzione**: il codice usa `Text Recognition:`, mentre DECISION/README/ROADMAP dicono che resta `OCR`. Anche i metadati dei benchmark sono falsi (contesto 16K mai applicato).
4. Rimangono molti residui delle generazioni precedenti: API mai chiamate, costanti duplicate, logica multi-device/fallback in un'app solo SYCL, un'impostazione "lingua" finta e una "confidenza" sempre vuota.
5. Il tooling di benchmark (~5.500 righe, ~30% dei test) supera il core e vive dentro `tests/`. Una ventina di test controllano stringhe nel sorgente invece del comportamento. Va ridimensionato per ultimo.

---

## 1. Il progetto in breve

| Voce | Dettaglio |
|---|---|
| Scopo | OCR desktop locale per Linux (immagini, PDF, batch, clipboard) con il modello GLM-OCR (GGUF) servito da un `llama-server` compilato con SYCL (GPU Intel). |
| Stack | Python ≥3.12, PySide6/Qt WebEngine + QWebChannel, frontend HTML/CSS/JS vanilla, Pillow, NumPy, PyMuPDF, huggingface_hub; llama.cpp pinnato e compilato da `install.sh` con oneAPI. |
| Struttura | `config/` (costanti, settings), `core/` (controller, motore, backend llama, output, eventi), `ui/` (bridge Qt + `ui/web/`), `tests/` (unit + UI + **benchmark**), `install.sh`, `PKGBUILD`. |
| Dimensioni | ~18.700 righe tracciate; `core/`+`ui/`+`config/`+`main.py` ≈ 6.000, `tests/benchmark/` ≈ 5.500. |
| Avvio | `./install.sh` poi `.venv/bin/python main.py`. |

### Cosa ho provato davvero [ESEGUITO]

| Prova | Esito |
|---|---|
| `pip install -r requirements.txt -r requirements-dev.txt` in un venv pulito (Python 3.14.10, venv temporaneo fuori dal repo) | ✅ OK. Versioni risolte: PySide6 6.12.0, Pillow 12.3.0, NumPy 2.5.5, PyMuPDF 1.28.2, huggingface_hub 1.33.0, pytest 8.4.2. `pip check`: nessun conflitto. |
| `python -m compileall -q main.py config core ui tests` | ✅ OK |
| `pytest` (con `QT_QPA_PLATFORM=offscreen`) | ✅ **209 passed in 3.19s**, nessuno skip. Unico rumore: `Release of profile requested but WebEnginePage still not deleted` ×3 (teardown nei test WebEngine). |
| `pip-audit -r requirements.txt` | ❌ **42 advisory su Pillow 12.3.0**, tutte corrette in 13.0.0, che però il vincolo `<13` esclude. |
| Avvio reale `main.py` (Wayland, config/cache XDG isolate) | ✅ La UI si carica ("GLM OCR UI pronta"). Senza `llama-server` il caricamento del modello fallisce con un messaggio chiaro: "llama-server SYCL non trovato. Esegui install.sh." (comportamento atteso). Con SIGTERM la chiusura è pulita ("Segnale 15 ricevuto"). |
| Avvio in `offscreen` + SIGINT/SIGTERM | ⚠️ Core dump (SIGTRAP, rc 133). Si **riproduce anche con uno script minimo** QApplication + QWebEngineView senza codice del progetto, ma **non** su Wayland. È un artefatto di Qt WebEngine in modalità offscreen, non un bug del progetto. |
| Settings malformati (`[]`, tipi sbagliati) | ❌ Crash e valori non validati (vedi A2). |
| Scansione segreti nella cronologia git (154 commit, tutti i rami) | ✅ Nessun segreto, token o chiave trovato. |

**Cosa NON ho eseguito:** `install.sh`, perché compila llama.cpp con oneAPI, scarica GB di modelli e scrive in `~/.local/share`. Quindi non ho verificato inferenza reale, build SYCL o benchmark hardware. oneAPI è presente (`/opt/intel/oneapi/setvars.sh`), `llama-server` no.

---

## 2. Problemi trovati

### Gravità ALTA

**A1. Pillow bloccato su una versione vulnerabile** [ESEGUITO]
- `requirements.txt:3`: `Pillow>=10.0.0,<13`.
- pip-audit trova 42 advisory su 12.3.0 (l'ultima ammessa), tutte risolte in 13.0.0. L'app decodifica immagini arbitrarie da file, drag&drop e clipboard (`core/image_utils.py:18-26`), quindi è esattamente la superficie interessata.
- **Correzione:** `Pillow>=13.0.0,<14`, poi rilanciare la suite. Valutare anche un lock file o `pip-audit` in CI.

**A2. `settings.json` malformato manda in crash l'avvio; tipi non validati** [ESEGUITO]
- `config/settings.py:115`: `data.items()` su un JSON che non è un oggetto (es. `[]`) solleva `AttributeError`. L'eccezione non è nella lista catturata a `:153`, quindi `main()` muore prima di creare la finestra. Il README ("Malformed or older settings files are migrated or replaced by safe defaults rather than crashing startup") è falso per questo caso.
- `:146`: `cls(**filtered)` accetta qualsiasi tipo. Verificato: `window_width="big"`, `output_dir=5` e `preprocessing_enabled="no"` vengono tutti caricati. Il primo rompe `window.resize()` in `main.py:120`. L'ultimo vale `True`, quindi il preprocessing resta **attivo**.
- **Correzione:** validare che `data` sia un `dict` e fare una coercizione o validazione per campo (`int` con range, `bool` stretto, `str`). In caso di errore, ripiegare sul default del singolo campo. Aggiungere test.

**A3. Prompt di produzione: codice e documentazione si contraddicono** [CODICE]
- Il codice usa `Text Recognition:` (`core/llama_ocr_api.py:33`) con il commento "The canonical real-world benchmark selected the official text-recognition prompt" (`:26`).
- Invece `tests/benchmark/DECISION.md:3` dice "keep `OCR` as the default prompt", `tests/benchmark/README.md:153` dice "The production default remains `OCR` until labelled real-world evidence is reviewed", e `ROADMAP.md:59` ha **non spuntato** "Run and review the canonical labelled real-world suite before changing the production default".
- I runner scrivono nei risultati `"production_default_prompt": PROMPT_LEGACY_OCR` (`tests/benchmark/run_prompt_benchmark.py:266`, `tests/benchmark/benchmark_prompt_quality.py:697`), cioè un metadato falso.
- Quindi o il cambio (PR #42) ha saltato il gate che il progetto stesso si è dato, o la documentazione non è stata aggiornata. Non è possibile capire dal repo quale delle due.
- **Correzione:** decidere la verità (domanda per te: la suite reale è stata eseguita?), poi allineare DECISION, README del benchmark, ROADMAP e CHANGELOG, e leggere il prompt reale dai metadati del benchmark (`llama_ocr_api.OCR_PROMPT`).

### Gravità MEDIA

**M1. Lock tenuto per tutto il caricamento: possibile GUI bloccata e chiusura bloccata** [CODICE, non riprodotto: serve hardware/download]
- `core/ocr_engine.py:66-99`: `initialize()` tiene `_lifecycle_lock` per tutta la durata di `backend.initialize()`, cioè download dei GGUF più fino a 90 s di avvio server. Le proprietà `is_initialized`, `device` e `backend` (`:38-50`) prendono lo stesso lock.
- Conseguenza 1: `AppController.check_idle_model_unload` (`core/app_controller.py:550`) valuta `not self.model_ready` **prima** di `self.operation != OP_IDLE`. Con l'auto-unload attivo, il timer Qt (ogni 30 s, `ui/web_bridge.py:55-58`) può bloccare il thread GUI per tutto il caricamento.
- Conseguenza 2: il download (`core/llama_models.py:85`) non è annullabile. Chiudendo l'app al primo avvio durante il download, `shutdown()` aspetta 15 s il thread e poi `engine.shutdown()` resta bloccato sul lock fino alla fine del download (GB).
- **Correzione:** stato `initialized` letto senza il lock di lifecycle (flag atomico o lock dedicato e breve), invertire l'ordine del check idle, download annullabile o almeno non sotto lock.

**M2. Build di llama.cpp dentro il repo non ignorata da git** [ESEGUITO]
- `install.sh:7` clona e compila in `$SCRIPT_DIR/.cache/llama.cpp`, ma `.gitignore` non contiene `.cache/` (`git check-ignore .cache/llama.cpp/x` non trova nulla). Dopo l'installazione, `git status` si riempie e c'è il rischio di committare per sbaglio l'intero llama.cpp.
- **Correzione:** aggiungere `.cache/` al `.gitignore`.

**M3. Modelli scaricati senza pin di revisione né hash** [CODICE]
- `core/llama_models.py:85-89`: `hf_hub_download` senza `revision`. La "verifica" (`:20-27`) controlla solo il magic `GGUF` e una dimensione minima. Se il repo HF cambia, l'app scarica silenziosamente un modello diverso. Il README parla di "downloads/verifies".
- **Correzione:** `revision=<commit sha>` e confronto SHA-256 dei due file.

**M4. Benchmark: override del contesto 16K che non fa nulla e metadati falsi** [CODICE]
- `tests/benchmark/run_pipeline_benchmark.py:294-297` imposta `llama_backend.CONTEXT_SIZE = 16384` (monkey-patch di un globale di modulo). `LlamaServerBackend._start_server` (`core/llama_backend.py:195-211`) però non legge mai `CONTEXT_SIZE`, quindi il server parte con i default. I risultati dichiarano comunque `"context_size": 16384` (`:386`) e il log dice "fresh llama-server ctx=16384" (`:336`).
- **Correzione:** passare il profilo runtime tramite `tests/benchmark/runtime_backend.py` (che supporta gli argomenti CLI), oppure eliminare il runner pipeline se superato dalla suite v2.

**M5. Due modi diversi di ricostruire le pagine PDF** [CODICE]
- OCR singolo: pagine raccolte dagli eventi `pdf_page_completed` (`core/output_workflow.py:128-178`).
- Batch: il testo combinato viene ri-parsato cercando righe `--- Pagina N ---` (`core/output_workflow.py:348-354` → `core/output_writer.py:445-468`). Se il testo OCR contiene una riga del genere, il salvataggio per pagine fallisce o divide male. Il formato combinato è costruito due volte (`core/llama_ocr_api.py:249-251` e `core/output_workflow.py:163-170`).
- **Correzione:** `ocr_pdf` restituisce la lista delle pagine (es. `OCRResult.pages`) e entrambi i percorsi la usano. Eliminare `split_combined_pdf_text`.

**M6. Rilevamento SYCL euristico: possibili falsi positivi** [CODICE; falso positivo = SOSPETTO]
- `core/llama_gpu_detect.py:153-171` e `:68-116`: se `--list-devices` non mostra `SYCLn:`, il dispositivo è comunque dichiarato disponibile quando `libze_loader` esiste, `lspci` vede una GPU Intel e `--help`/`ldd` contengono parole come `dpc++` o `libsycl`. Il caso tipico è il runtime presente ma nessun device utilizzabile. Il server poi fallisce dopo fino a 90 s con un errore meno chiaro. Ogni rilevamento lancia fino a 5 sottoprocessi.
- **Correzione:** unica fonte di verità `llama-server --list-devices` (la stessa usata da `install.sh:95-107`).

**M7. PKGBUILD: un secondo percorso d'installazione non documentato e incoerente** [CODICE + `pacman -Ss`]
- `PKGBUILD:9-20`: dipende da `llama-cpp`/`ggml-sycl` di sistema (0.9.0 nei repo), non dal commit pinnato da `install.sh:11`. Il sorgente è `git+…` di HEAD senza pin, con `sha256sums=SKIP`. Installato in `/usr/share/glm-ocr`, `find_llama_server` (`core/llama_gpu_detect.py:40-47`) ripiega su `shutil.which`.
- Versioni incoerenti: `pkgver=1.0.0`, `AppMeta.VERSION="1.0.0"` (`config/constants.py:33`), `CHANGELOG.md:47` → `1.0.1`. Il README non menziona il PKGBUILD.
- **Correzione:** decidere se è supportato. Se sì: pin a tag/commit, versione unica, documentazione. Se no: rimuoverlo insieme al suo test (`tests/test_core/test_packaging.py`).

**M8. Codice morto e API "di compatibilità" mai usate** [CODICE, verificato con grep su `core/ ui/ main.py tests/`]
- `core/app_controller.py`: `run_ocr` (:560), `unload_model_sync` (:469) mai chiamati. `load_model_sync` (:391), `switch_device` (:650) e `cancel_batch` (:641) solo nei test. `get_available_devices` (:647), `subscribe` (:746), `save_single_result`/`save_single_pdf_pages` sincroni (:687-693) e le proprietà `engine`/`process_manager`/`hardware_detector` (:154-165, "Compatibility access") non sono usati dall'app.
- `core/output_workflow.py:190-216`: versioni sincrone dei salvataggi, duplicate delle asincrone (`:273-307`). `_normalize_format` è duplicato in `core/output_writer.py:58-62`.
- `core/process_manager.py`: `get_status` (:131), `is_active` (:127).
- `core/image_utils.py:38` `pdf_to_images`; `core/image_preprocessor.py:43` `binarize` + `_otsu_threshold` (solo test).
- `core/llama_backend.py`: `CONTEXT_SIZE`/`BATCH_SIZE` (:35-36), `_production_runtime_args` che restituisce `[]` (:42), `_optimal_thread_count` (:290, usato solo dal benchmark). `core/llama_gpu_detect.py:17` `GPU_OFFLOAD_PARTIAL_LAYERS`.
- `ui/event_bridge.py`: segnali `ocr_new_text`/`batch_new_text` (:21-22, connessi solo nei test), parametro `controller` e `wait_ms` inutilizzati. `ui/web_bridge.py`: `set_window` (:60) e il ramo `allow_close` (:530) per un attributo che `MainWindow` non ha.
- `config/constants.py`: `AppConstants` (:96) è un alias di `AppMeta`/`OCRDefaults` e il codice usa entrambi in modo intercambiabile. Mai usate: `DEFAULT_CONFIDENCE_THRESHOLD`, `PREPROCESS_DPI_TARGET`, `DEFAULT_PROCESSING_TIMEOUT_S`, `LLAMA_CPP_DEVICE`, `SUPPORTED_DEVICES`, `DESKTOP_DIR`. Di `UIConstraints` (:81) si usano solo larghezza e altezza finestra.
- `core/models.py` `StatusEnum` ed `core/exceptions.py` `OCRError` sono solo riesportati. `GGUF_MODEL_ID` è definito due volte (`config/constants.py`, `core/llama_models.py:16`).
- **Correzione:** eliminare. Nessun cambiamento di comportamento; aggiornare i test che li usano.

**M9. Logica multi-device/fallback rimasta in un'app solo SYCL** [CODICE]
- `HardwareDetector` restituisce sempre un solo device (`core/hardware_detector.py:39-46`). `AppController.initialize` gestisce un "fallback" verso lo stesso device (`core/app_controller.py:286-303`). `ComputeDevice` ha un valore legacy e `choices()/default()` (`config/settings.py:19-35`). `_start_server_with_fallback` dichiara nel docstring di non avere fallback (`core/llama_backend.py:136-143`). `Settings.default_device` è sempre forzato a SYCL al load.
- **Correzione:** ridurre a "backend SYCL disponibile sì/no". Rimuovere `default_device` dalle impostazioni (con migrazione silenziosa) e gli strati di switch device.

**M10. Funzionalità finte visibili all'utente** [CODICE]
- **Lingua OCR:** salvata e mostrata in Impostazioni ma mai usata nell'OCR. La UI stessa lo ammette ("Preferenza salvata per compatibilità…", `ui/web/index.html:310-319`). `ROADMAP.md` la lascia aperta ("either make it operational or remove it").
- **Confidenza:** il frontend mostra "confidenza N%" (`ui/web/app.js:203`) ma il backend restituisce sempre `None` (`core/llama_ocr_api.py:435-439`). Il batch fallito inventa `confidence=0.0` e un testo `"[Errore: …]"` come risultato (`core/process_manager.py:254`).
- **Correzione:** rimuovere entrambe (o implementare la lingua nel prompt con evidenza di benchmark).

**M11. Benchmark sovradimensionato, duplicato e dentro `tests/`** [CODICE + conteggio test ESEGUITO]
- `tests/benchmark/` ≈ 5.500 righe, quasi quanto `core/`+`ui/`+`config/`. Circa 60 dei 209 test testano il tooling di benchmark, sparsi in tre posti: `tests/benchmark/test_*`, `tests/test_core/test_benchmark_*` + `test_prompt_benchmark*`, `tests/test_benchmark_resume_integrity.py`.
- Convivono più generazioni: due runner per i prompt con `main` e metadati quasi identici (`run_prompt_benchmark.py` 296 righe + `benchmark_prompt_quality.py` 742), `run_pipeline_benchmark.py` (vedi M4), `run_realworld_suite.py` (wrapper da 18 righe) + `run_realworld_suite_v2.py` (1.309 righe).
- **Correzione:** spostare in `benchmarks/` di primo livello, tenere solo la suite canonica v2, archiviare (o lasciare alla cronologia git) i runner superati, consolidare i test.

**M12. Test che controllano stringhe nel sorgente invece del comportamento** [CODICE]
- Circa 25 test leggono i file sorgente e asseriscono presenza o assenza di testo: `tests/test_ui/test_startup_ui_regressions.py` (tutto), `tests/test_ui/test_web_ui.py` (tutto, inclusi i colori CSS `rgb(255, 102, 0)`), `tests/test_core/test_installer.py`, `test_shutdown_lifecycle.py`, `test_logging_policy.py`, `test_main_safety.py`, `test_backend_safety.py`, `test_packaging.py`, `test_model_memory_workflow.py:211`.
- Non proteggono il comportamento, si rompono a ogni refactor innocuo (anche rinominare una variabile) e passano anche se la funzione è rotta. Contraddicono la regola dello stesso `STRATEGIC_REVIEW.md` ("tests protect behavior rather than implementation accidents").
- **Correzione:** sostituire con test comportamentali dove il rischio è reale (shutdown, process group, log rotation); eliminare quelli puramente estetici o "storici" (file rimossi, nomi vecchi).

### Gravità BASSA (solo ciò che può confondere o rompere)

| # | Problema | Dove | Correzione |
|---|---|---|---|
| B1 | `pdf_page_count` inghiotte ogni eccezione e restituisce 0: un PDF cifrato o corrotto produce "Il PDF non contiene pagine". Ogni pagina riapre il PDF. [CODICE] | `core/image_utils.py:29-35`, `:59-76` | Propagare `ImageLoadError` con la causa; aprire il documento una volta. |
| B2 | Errori OCR incapsulati come `ModelLoadError`, quindi l'utente legge "Impossibile caricare il modello… OCR fallito per x". [CODICE] | `core/llama_backend.py:424-426` | Eccezione dedicata (es. `OCRProcessingError`). |
| B3 | Rilevamento "crash" del server tramite confronto di stringhe del messaggio d'errore. [CODICE] | `core/llama_backend.py:404-412` | Classificare per tipo di eccezione + `process.poll()`. |
| B4 | `EventBus` logga gli errori degli handler senza traceback. [CODICE] | `core/event_bus.py:77` | `logger.exception`. |
| B5 | `ProcessManager._jobs` cresce per tutta la sessione e trattiene il testo di ogni batch. [CODICE] | `core/process_manager.py:68` | Rimuovere il job a fine esecuzione. |
| B6 | Sessioni di staging orfane (immagini dagli appunti) dopo un crash restano per sempre in `~/.cache/glm-ocr/inputs`: tema privacy. [CODICE] | `core/input_staging.py:52-68` | All'avvio, pulire le `session-*` più vecchie. |
| B7 | `core/__init__.py` importa `AppController`, quindi importare qualunque `core.x` carica l'intera catena (rischio import circolari, test più lenti). [CODICE] | `core/__init__.py:3` | `__init__` vuoto. |
| B8 | `ONEAPI_DEVICE_SELECTOR=level_zero:0` fisso: su macchine con iGPU+dGPU sceglie il device 0. [SOSPETTO sull'impatto] | `core/llama_backend.py:217`, `install.sh:100,111` | Renderlo configurabile o documentarlo. |
| B9 | `Exec=` del `.desktop` non quotato: si rompe con percorsi contenenti spazi. [CODICE] | `install.sh:244` | Quotare i percorsi. |
| B10 | CHANGELOG fermo al 2026-08-25, mentre le PR #42/#43 (2026-09-04) cambiano prompt e runtime. Versioni disallineate (vedi M7). [CODICE] | `CHANGELOG.md` | Aggiornare. |
| B11 | La CI prova solo Python 3.12 (in locale gira 3.14) e non c'è un lock delle dipendenze. [CODICE] | `.github/workflows/tests.yml` | Matrice 3.12/3.14 e `pip-audit`. |
| B12 | Cronologia: workflow ora rimossi (`apply-benchmark-milestone.yml` & co.) applicavano patch **base64+gzip** con `contents: write`, cioè codice entrato nel repo senza revisione leggibile. Due rami remoti stantii (`benchmark-production-profile-resource-guard`, `stock-runtime-memory-recovery`). [ESEGUITO] | storia git | Nessuna azione sul codice; eliminare i rami remoti ed evitare la pratica in futuro. |

---

## 3. Piano di pulizia (dalle fasi più sicure alle più invasive)

| Fase | Contenuto | Rischio | Sforzo stimato |
|---|---|---|---|
| **0 — Sicurezza e igiene** | A1 (Pillow ≥13 + test), M2 (`.cache/` in `.gitignore`), A2 (loader settings robusto + test). | Molto basso | ~1 h |
| **1 — Verità documentale** | A3 (stabilire il prompt reale e allineare DECISION/README benchmark/ROADMAP/CHANGELOG), M4 (correggere o eliminare l'override 16K e i metadati falsi), B10, versione unica. *Richiede una tua risposta su A3.* | Basso | 1–2 h |
| **2 — Rimozione codice morto** | M8 completo, B7. Nessun cambio di comportamento; la suite resta verde. | Basso | 2–3 h |
| **3 — Bug di robustezza** | M1 (lock/ordine check/download annullabile), M5 (pagine PDF strutturate, un solo percorso), B1–B6. Ogni fix con un test comportamentale. | Medio | 4–6 h |
| **4 — Semplificazione SOLO SYCL** | M9 (via device/fallback/`ComputeDevice`/`default_device`), M6 (rilevamento solo `--list-devices`), M10 (lingua e confidenza), M3 (pin + hash modello), M7 (decidere sul PKGBUILD). | Medio (tocca settings e UI) | 4–6 h |
| **5 — Ristrutturazione test e benchmark** | M11 (spostare in `benchmarks/`, tenere solo la suite v2, consolidare i test), M12 (sostituire o eliminare i test "grep sul sorgente"), B11. | Più invasiva (molti file) ma senza impatto sull'app | 6–10 h |

Totale indicativo: **~2,5–3,5 giornate**. Le fasi 0–2 da sole (mezza giornata) eliminano i rischi reali e gran parte della confusione.

---

**Prossimo passo:** dimmi quali fasi eseguire. Per la fase 1 mi serve anche sapere se la suite real-world del benchmark è stata davvero eseguita prima del passaggio a `Text Recognition:`.

---

## 4. Stato dopo l'esecuzione di tutte le fasi (2026-11-25)

| # | Esito | Dove |
|---|---|---|
| A1 | Risolto: `Pillow>=13,<14`, `pip-audit` in CI (0 vulnerabilità note) | `requirements.txt`, CI |
| A2 | Risolto: validazione per campo, fallback al default, test con `[]`/tipi errati | `config/settings.py` |
| A3 | Deciso: il prompt di produzione resta `Text Recognition:` (scelto dalla suite real-world, PR #42); documentazione e metadati allineati | `benchmarks/DECISION.md`, `ROADMAP.md` |
| M1 | Risolto: lock solo sullo scambio del backend, controllo idle riordinato, download annullabile; test di regressione | `core/ocr_engine.py`, `core/app_controller.py`, `core/llama_models.py` |
| M2 | Risolto: `.cache/` in `.gitignore` | `.gitignore` |
| M3 | Risolto: revisione HF pinnata + SHA-256 verificato una volta per file | `core/llama_models.py` |
| M4 | Risolto: runner pipeline (override no-op) eliminato insieme ai runner superati | `benchmarks/` |
| M5 | Risolto: pagine PDF strutturate in un solo percorso | `core/models.py`, `core/output_workflow.py` |
| M6 | Risolto: solo `llama-server --list-devices` | `core/llama_gpu_detect.py` |
| M7 | Risolto: PKGBUILD da git con `pkgver()`, documentato come alternativa | `PKGBUILD`, `README.md` |
| M8, M9 | Risolto: codice morto e scaffolding multi-device rimossi | `core/`, `config/`, `ui/` |
| M10 | Risolto: "lingua" e "confidenza" rimosse | UI, `core/models.py` |
| M11 | Risolto: benchmark in `benchmarks/`, test consolidati | `benchmarks/` |
| M12 | Risolto: test grep-sul-sorgente eliminati, sostituiti da test comportamentali | `tests/` |
| B1–B11 | Risolti (B8: `ONEAPI_DEVICE_SELECTOR` dell'utente rispettato; B12 richiede solo di eliminare due rami remoti, non fatto) | vari |
| Nuovo | Trovato con test su hardware reale e risolto: `llama-server` ucciso a fine del thread che lo avviava (`PR_SET_PDEATHSIG`), con un riavvio a ogni OCR | `core/owned_process.py` |

Port UI: WebEngine → Qt Quick, layout verificato al pixel contro la UI web a 1237×836, 860×700 e 480×540. Memoria a riposo da ~360 MiB (5 processi) a ~190 MiB (1 processo).
