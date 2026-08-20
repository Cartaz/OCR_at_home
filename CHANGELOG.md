# Changelog

## [1.0.1] — 2026-07-03 — Pulizia e bug fix

### Bug critici corretti

- **`BatchTab._on_batch`**: invocava `self._controller.start_model_loading(...)`
  che non esiste su `AppController` (esiste solo su `EventBridge`). Ora mostra
  un messaggio all'utente e rifiuta di avviare il batch finché il modello
  non è pronto, evitando un `AttributeError` in produzione.
- **`BatchTab._on_stop`**: accedeva all'attributo privato `pm._active_job_id`
  e passava una stringa vuota a `cancel_batch("")` che è una no-op, quindi
  il pulsante "Ferma" del batch non funzionava mai. Ora usa il nuovo metodo
  pubblico `AppController.cancel_active_batch()`.
- **`OCREngine.initialize`**: leggeva i campi privati
  `_gpu_layers` e `_gpu_backend` di `LlamaServerBackend`, rompendo
  l'incapsulamento. Aggiunte le property pubbliche `gpu_layers` e
  `gpu_backend` e aggiornato il codice chiamante.
- **`MainWindow._connect_bridge`**: il segnale `model_load_progress`
  era collegato a `OCRTab.update_status` (che mappa *stati* in colori)
  tramite un `hasattr`/`lambda` inutile, quindi i messaggi di progresso
  ("Scaricamento GLM-OCR-Q8_0.gguf…") non venivano mai mostrati
  all'utente. Aggiunto il metodo `show_progress_message` su `OCRTab`
  e `BatchTab` e il relativo handler su `MainWindow`.
- **`ProcessManager._process_task`**: usava `self._jobs.get(job_id, BatchOCRJob())`
  come fallback, producendo conteggi `0/0` se il job fosse stato cancellato
  tra il controllo e l'emit. Sostituito con una guardia esplicita.
- **`LlamaServerBackend._check_server_alive`**: dopo un crash non
  azzerava `_initialized`, lasciando il backend in uno stato
  inconsistente. Ora resetta correttamente il flag.
- **`ImagePreprocessor._enhance_contrast`**: ricalcolava la luminanza
  due volte (`gray` e poi `luminance = self._to_grayscale(result)` su una
  copia identica dell'input). Semplificato il flusso.
- **`ocr_single_image`** (llama_ocr_api): non applicava la pipeline di
  pre-elaborazione, dando risultati inconsistenti fra immagini singole
  e pagine PDF. Ora condivide lo stesso `_preprocessor` singleton.
- **`OCRTab._on_start`**: chiamava `update_settings(default_device=…)`
  salvando il device senza triggerare il caricamento del modello
  corrispondente. Ora il cambio device avviene esclusivamente tramite
  `_on_device_changed → controller.switch_device`.
- **`OCREngine.initialize`**: confrontava la stringa `"llama-cpp-sycl"`
  hardcodata invece di usare `BACKEND_LLAMA_CPP_SYCL`.
- **`main_window.py`**: il nuovo slot `_on_model_load_progress` era
  decorato con `@Slot(str)` ma `Slot` non era importato → `NameError`
  a runtime. Aggiunto l'import.
- **`main.py`**: il signal handler SIGINT non veniva mai invocato
  durante il loop Qt perché Python non riprende il controllo finché
  il loop non torna al C++. Aggiunto un `QTimer` di wakeup a 50ms che
  permette la consegna del segnale.

### Pulizia e refactoring

- **EventBus**: semplificata la struttura. Rimosso il pattern
  `_initialized` + `__new__` + `__init__` + `_get_instance` + `_do_*`
  duplicato. Ora `__new__` crea il singleton in modo atomico e i
  metodi pubblici `subscribe/emit/unsubscribe/reset` delegano
  direttamente all'istanza.
- **Helper UI condivisi**: estratto il mapping `status_to_indicator_state`
  (prima duplicato in `ocr_tab_helpers` e `batch_tab_helpers`) nel
  nuovo modulo `ui/widgets/_status_helpers.py`.
- **Import morti rimossi** in: `config/settings.py`, `core/ocr_engine.py`,
  `core/process_manager.py`, `core/image_preprocessor.py`,
  `core/llama_backend.py`, `core/app_controller.py`, `ui/main_window.py`,
  `ui/widgets/ocr_tab_helpers.py`, `ui/widgets/batch_tab.py`,
  `ui/widgets/config_panel.py`, `ui/widgets/status_indicator.py`
  (rimossi `QPropertyAnimation` e `Property`).
- **`install.sh`**: sostituiti i caratteri Unicode non ASCII
  (`╔╗╚╝║═──⚠✓ℹ`) con equivalenti ASCII (`+|=-!OK i`) per evitare
  problemi in bash con locale non UTF-8.
- **`PKGBUILD`**:
  - Sostituita la variabile `$git_url` non definita con uno
    `source=("git+https://github.com/glm-ocr/glm-ocr.git")` esplicito.
  - Aggiornate le `depends`: rimosso `ffmpeg` (non usato), aggiunti
    `python-pyside6`, `python-pillow`, `python-numpy`, `python-pymupdf`,
    `python-huggingface-hub`, `llama.cpp`.
  - Aggiornate le `makedepends`: aggiunto `cmake` e `gcc`.
  - Aggiunte `optdepends` per il supporto SYCL (intel-oneapi-basekit,
    level-zero-loader, level-zero-headers, intel-compute-runtime).
  - Corretto `pkgdesc` (prima citava GPU/NPU Intel genericamente,
    ora specifica llama.cpp + SYCL).

### Nuovi test

- `tests/test_core/test_process_manager.py` (4 test): verifica
  `cancel_active_batch`, `active_job_id`, `submit_batch`, `cancel_batch`.
- `tests/test_core/test_image_preprocessor.py` (5 test): verifica
  `enhance`, `binarize`, `_normalize_histogram`, `_to_grayscale`.

### Nuove API pubbliche

- `ProcessManager.cancel_active_batch()`: annulla il job attivo.
- `ProcessManager.active_job_id` (property): ID del job in esecuzione.
- `AppController.cancel_active_batch()`: delega al ProcessManager.
- `LlamaServerBackend.gpu_layers` (property): layer offloadati su GPU.
- `LlamaServerBackend.gpu_backend` (property): backend GPU attivo.
- `OCRTab.show_progress_message(msg)`: mostra messaggi informativi.
- `BatchTab.show_progress_message(msg)`: mostra messaggi informativi.

### Compatibilità

Tutti i test esistenti passano (10/10). Aggiunti 9 nuovi test (19/19 totali).
