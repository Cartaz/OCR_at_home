"use strict";

const state = {
    backend: null,
    activeView: "ocr",
    operation: "idle",
    modelReady: false,
    devices: [],
    limits: { max_batch_size: 50, max_image_size_mb: 50, extensions: [] },
    singlePath: "",
    singleText: "",
    singleIsPdf: false,
    pdfParts: [],
    batchPaths: [],
    batchStates: new Map(),
    batchResults: new Map(),
    batchJobId: "",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const uiExtensions = [];

function registerUiExtension(extension) {
    if (extension && typeof extension === "object") uiExtensions.push(extension);
}

function runExtensionHook(name, ...args) {
    for (const extension of uiExtensions) {
        const hook = extension[name];
        if (typeof hook === "function") hook(...args);
    }
}

function basename(path) {
    return String(path || "").split(/[\\/]/).pop() || "";
}

function parseNative(raw) {
    try {
        return JSON.parse(raw);
    } catch (error) {
        return { ok: false, error: `Risposta backend non valida: ${error}` };
    }
}

function callNative(name, ...args) {
    return new Promise((resolve) => {
        if (!state.backend || typeof state.backend[name] !== "function") {
            resolve({ ok: false, error: `Metodo backend non disponibile: ${name}` });
            return;
        }
        state.backend[name](...args, (raw) => resolve(parseNative(raw)));
    });
}

function setView(name) {
    state.activeView = name;
    $$(".nav-item").forEach((button) => {
        const active = button.dataset.view === name;
        button.classList.toggle("active", active);
        if (active) button.setAttribute("aria-current", "page");
        else button.removeAttribute("aria-current");
    });
    $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
    const active = $(`#view-${name}`);
    $("#view-title").textContent = active?.dataset.title || "GLM OCR";
    if (name === "logs") refreshLogs();
}

function showNotice(title, message, details = "") {
    $("#notice-title").textContent = title;
    $("#notice-message").textContent = message;
    $("#notice-details").textContent = details;
    const hasDetails = Boolean(details && details.trim());
    $("#notice-details-wrap").classList.toggle("hidden", !hasDetails);
    $("#notice-details-wrap").open = false;
    $("#notice").classList.remove("hidden");
}

function hideNotice() {
    $("#notice").classList.add("hidden");
}

function operationLabel(operation) {
    const labels = {
        idle: "In attesa",
        model_loading: "Caricamento modello",
        model_unloading: "Scaricamento modello",
        ocr: "OCR in corso",
        batch: "Batch in corso",
        shutting_down: "Arresto",
    };
    return labels[operation] || operation;
}

function refreshBatchRemovalControls() {
    const disabled = state.operation !== "idle";
    $$(".batch-remove-button").forEach((button) => {
        button.disabled = disabled;
    });
}

function updateOperationUi() {
    const op = state.operation;
    const busy = op !== "idle";
    const label = operationLabel(op);

    $("#ocr-operation-label").textContent = op === "ocr" ? label : "In attesa";
    $("#ocr-operation-label").classList.toggle("active", op === "ocr");
    $("#batch-operation-label").textContent = op === "batch" ? label : "In attesa";
    $("#batch-operation-label").classList.toggle("active", op === "batch");

    $("#single-file-button").disabled = busy;
    $("#single-start-button").disabled = busy || !state.modelReady || !state.singlePath;
    $("#single-cancel-button").disabled = op !== "ocr";
    $("#batch-file-button").disabled = busy;
    $("#batch-start-button").disabled = busy || !state.modelReady || state.batchPaths.length === 0;
    $("#batch-cancel-button").disabled = op !== "batch";
    $("#model-reload-button").disabled = busy;
    $("#hardware-refresh-button").disabled = busy;
    $("#global-cancel-button").classList.toggle("hidden", !busy || op === "shutting_down");
    $("#global-cancel-button").disabled = !busy || op === "shutting_down";
    refreshBatchRemovalControls();

    const sidebarText = op === "idle" ? (state.modelReady ? "Pronto" : "Backend non pronto") : label;
    $("#sidebar-status-text").textContent = sidebarText;
    $("#sidebar-status-dot").classList.toggle("active", state.modelReady || busy);
    runExtensionHook("refreshUi", "operation");
}

function setModelStatus(text, active = false) {
    $("#model-status-text").textContent = text;
    $("#model-status").classList.toggle("active", active);
}

function updateBackendPanel() {
    const device = state.devices[0] || null;
    $("#backend-device").textContent = device?.device_name || "llama.cpp + SYCL";
    $("#backend-availability").textContent = device ? (device.available ? "Disponibile" : "Non disponibile") : "Non rilevato";
    const chip = $("#backend-chip");
    if (state.modelReady) {
        chip.textContent = "Pronto";
        chip.classList.add("active");
    } else if (device?.available) {
        chip.textContent = "Disponibile";
        chip.classList.remove("active");
    } else {
        chip.textContent = "Non pronto";
        chip.classList.remove("active");
    }
    runExtensionHook("refreshUi", "backend");
}

function setProgress(rootSelector, percent, valueText) {
    const root = $(rootSelector);
    const value = Math.max(0, Math.min(100, Number(percent) || 0));
    root.setAttribute("aria-valuenow", String(Math.round(value)));
    root.querySelector(".progress-fill").style.width = `${value}%`;
    if (valueText !== undefined) {
        const target = rootSelector === "#single-progress" ? $("#single-progress-value") : $("#batch-progress-value");
        target.textContent = valueText;
    }
}

function renderSingleText(text) {
    state.singleText = text || "";
    $("#single-result").textContent = state.singleText || "Nessun risultato.";
    $("#copy-single-button").disabled = !state.singleText;
}

function formatResultMeta(payload) {
    const parts = [];
    if (Number.isFinite(Number(payload.confidence))) parts.push(`confidenza ${Math.round(Number(payload.confidence) * 100)}%`);
    if (Number(payload.time_ms) > 0) parts.push(`${(Number(payload.time_ms) / 1000).toFixed(1)} s`);
    return parts.length ? parts.join(" · ") : "Elaborazione completata";
}

function removeBatchPath(path) {
    if (state.operation !== "idle") return;
    const index = state.batchPaths.indexOf(path);
    if (index < 0) return;
    state.batchPaths.splice(index, 1);
    state.batchStates.delete(path);
    state.batchResults.delete(path);
    renderBatchFiles();
    renderBatchResults();
    updateOperationUi();
}

function renderBatchFiles() {
    const list = $("#batch-file-list");
    list.replaceChildren();
    $("#batch-count-label").textContent = `${state.batchPaths.length} ${state.batchPaths.length === 1 ? "file selezionato" : "file selezionati"}`;
    if (!state.batchPaths.length) {
        const row = document.createElement("li");
        row.className = "empty-row";
        row.textContent = "Nessun documento in coda.";
        list.append(row);
        return;
    }
    for (const path of state.batchPaths) {
        const row = document.createElement("li");
        row.className = "batch-file-row";
        const name = document.createElement("span");
        name.className = "batch-file-name";
        name.textContent = basename(path);
        name.title = path;
        const controls = document.createElement("div");
        controls.className = "inline-controls";
        const status = document.createElement("span");
        const value = state.batchStates.get(path) || "In coda";
        status.className = "batch-file-state";
        if (["Completato", "In elaborazione"].includes(value)) status.classList.add("active");
        status.textContent = value;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "icon-button compact batch-remove-button";
        remove.textContent = "×";
        remove.title = `Rimuovi ${basename(path)} dalla coda`;
        remove.setAttribute("aria-label", remove.title);
        remove.disabled = state.operation !== "idle";
        remove.addEventListener("click", () => removeBatchPath(path));
        controls.append(status, remove);
        row.append(name, controls);
        list.append(row);
    }
}

function renderBatchResults() {
    const root = $("#batch-results");
    root.replaceChildren();
    if (!state.batchResults.size) {
        const empty = document.createElement("p");
        empty.className = "empty-copy";
        empty.textContent = "Nessun risultato.";
        root.append(empty);
        return;
    }
    for (const path of state.batchPaths) {
        const item = state.batchResults.get(path);
        if (!item) continue;
        const details = document.createElement("details");
        details.className = `batch-result-item ${item.ok ? "completed" : ""}`;
        const summary = document.createElement("summary");
        const name = document.createElement("span");
        name.textContent = basename(path);
        const status = document.createElement("span");
        status.textContent = item.ok ? "Completato" : "Errore";
        summary.append(name, status);
        const pre = document.createElement("pre");
        pre.textContent = item.text || item.error || "Nessun testo restituito.";
        details.append(summary, pre);
        root.append(details);
    }
}

function updateBatchState(path, label) {
    state.batchStates.set(path, label);
    renderBatchFiles();
}

function ensureLanguageOption(value) {
    const select = $("#language-input");
    const normalized = String(value || "ita+eng");
    if (![...select.options].some((option) => option.value === normalized)) {
        const option = document.createElement("option");
        option.value = normalized;
        option.textContent = normalized;
        select.append(option);
    }
    select.value = normalized;
}

function applySettings(settings) {
    $("#preprocess-toggle").checked = Boolean(settings.preprocessing_enabled);
    ensureLanguageOption(settings.language);
    $("#output-dir-input").value = String(settings.output_dir || "");
    runExtensionHook("applySettings", settings);
}

function collectSettings() {
    const payload = {
        preprocessing_enabled: $("#preprocess-toggle").checked,
        language: $("#language-input").value,
        output_dir: $("#output-dir-input").value,
    };
    runExtensionHook("collectSettings", payload);
    return payload;
}

function notifyUiState(type, payload = {}) {
    runExtensionHook("onUiState", type, payload);
}

function handleEvent(raw) {
    let message;
    try {
        message = JSON.parse(raw);
    } catch (error) {
        showNotice("Errore UI", "Evento backend non leggibile.", String(error));
        return;
    }
    const type = message.type;
    const payload = message.payload || {};

    switch (type) {
        case "operation_changed":
            state.operation = String(payload.operation || "idle");
            updateOperationUi();
            break;
        case "hardware_detected":
            if (Array.isArray(payload.devices)) state.devices = payload.devices;
            updateBackendPanel();
            break;
        case "model_loading":
            state.modelReady = false;
            setModelStatus("Caricamento modello…", true);
            updateBackendPanel();
            updateOperationUi();
            break;
        case "model_loaded":
            state.modelReady = true;
            setModelStatus("Modello pronto", true);
            updateBackendPanel();
            updateOperationUi();
            break;
        case "model_load_progress":
            setModelStatus(String(payload.message || "Caricamento modello…"), true);
            break;
        case "model_load_cancelled":
            state.modelReady = false;
            setModelStatus("Caricamento annullato", false);
            updateBackendPanel();
            updateOperationUi();
            break;
        case "model_load_failed":
            state.modelReady = false;
            setModelStatus("Backend non pronto", false);
            updateBackendPanel();
            updateOperationUi();
            showNotice("Backend non disponibile", "Il modello OCR non è stato caricato.", String(payload.error || ""));
            break;
        case "config_changed":
            break;
        case "ocr_started":
            state.singleIsPdf = Boolean(payload.is_pdf);
            state.pdfParts = [];
            renderSingleText("");
            $("#single-result-meta").textContent = `Elaborazione di ${basename(payload.image_path || state.singlePath)}…`;
            $("#single-progress-block").classList.remove("hidden");
            $("#single-progress-label").textContent = state.singleIsPdf ? "Preparazione PDF" : "Elaborazione immagine";
            setProgress("#single-progress", 0, "");
            break;
        case "pdf_progress": {
            const page = Number(payload.page_num || 0);
            const total = Math.max(1, Number(payload.total_pages || 1));
            $("#single-progress-label").textContent = `Pagina ${page} di ${total}`;
            setProgress("#single-progress", ((page - 1) / total) * 100, `${page} / ${total}`);
            break;
        }
        case "pdf_page_completed": {
            if (payload.mode !== "single") break;
            const page = Number(payload.page_num || 0);
            const total = Math.max(1, Number(payload.total_pages || 1));
            const text = String(payload.text || "");
            state.pdfParts.push(total > 1 ? `--- Pagina ${page} ---\n${text}` : text);
            renderSingleText(state.pdfParts.join("\n\n"));
            setProgress("#single-progress", (page / total) * 100, `${page} / ${total}`);
            break;
        }
        case "ocr_completed":
            if (!Boolean(payload.is_pdf)) renderSingleText(String(payload.text || ""));
            $("#single-result-meta").textContent = formatResultMeta(payload);
            setProgress("#single-progress", 100, state.singleIsPdf ? "Completato" : "100%");
            setTimeout(() => $("#single-progress-block").classList.add("hidden"), 700);
            break;
        case "ocr_cancelled":
            $("#single-progress-block").classList.add("hidden");
            $("#single-result-meta").textContent = "Operazione annullata.";
            showNotice("OCR annullato", "L'elaborazione è stata interrotta.");
            break;
        case "ocr_failed":
            $("#single-progress-block").classList.add("hidden");
            $("#single-result-meta").textContent = "Elaborazione fallita.";
            showNotice("OCR non riuscito", "Il documento non è stato elaborato.", String(payload.error || ""));
            break;
        case "batch_started":
            state.batchJobId = String(payload.job_id || "");
            state.batchResults.clear();
            state.batchStates = new Map(state.batchPaths.map((path) => [path, "In coda"]));
            if (state.batchPaths.length) state.batchStates.set(state.batchPaths[0], "In elaborazione");
            renderBatchFiles();
            renderBatchResults();
            $("#batch-progress-block").classList.remove("hidden");
            $("#batch-progress-label").textContent = "Batch in corso";
            setProgress("#batch-progress", 0, `0 / ${Number(payload.total_tasks || state.batchPaths.length)}`);
            break;
        case "batch_task_completed": {
            const path = String(payload.image_path || "");
            updateBatchState(path, "Completato");
            state.batchResults.set(path, { ok: true, text: String(payload.text || "") });
            renderBatchResults();
            break;
        }
        case "batch_task_failed": {
            const path = String(payload.image_path || "");
            updateBatchState(path, "Errore");
            state.batchResults.set(path, { ok: false, error: String(payload.error || "Errore sconosciuto") });
            renderBatchResults();
            break;
        }
        case "batch_progress": {
            const completed = Number(payload.completed || 0);
            const total = Math.max(1, Number(payload.total || state.batchPaths.length || 1));
            const runningPath = state.batchPaths.find((path) => (state.batchStates.get(path) || "In coda") === "In coda");
            if (runningPath && completed < total) updateBatchState(runningPath, "In elaborazione");
            setProgress("#batch-progress", (completed / total) * 100, `${completed} / ${total}`);
            break;
        }
        case "batch_completed":
            setProgress("#batch-progress", 100, `${payload.completed || state.batchPaths.length} / ${payload.total || state.batchPaths.length}`);
            $("#batch-progress-label").textContent = "Batch completato";
            setTimeout(() => $("#batch-progress-block").classList.add("hidden"), 700);
            break;
        case "batch_cancelled":
            for (const path of state.batchPaths) {
                if (["In coda", "In elaborazione"].includes(state.batchStates.get(path))) state.batchStates.set(path, "Annullato");
            }
            renderBatchFiles();
            $("#batch-progress-label").textContent = "Batch annullato";
            showNotice("Batch annullato", "L'elaborazione della coda è stata interrotta.");
            break;
        case "batch_failed":
            $("#batch-progress-label").textContent = "Batch terminato con errori";
            showNotice("Batch non completato", "Uno o più documenti non sono stati elaborati.", String(payload.error || ""));
            break;
        case "ui_error":
            showNotice("Operazione non disponibile", String(payload.message || "Errore"), String(payload.details || ""));
            break;
        default:
            break;
    }
    runExtensionHook("onBackendEvent", type, payload);
}

async function refreshLogs() {
    if (!state.backend) return;
    const text = await new Promise((resolve) => state.backend.getLogs(600, resolve));
    const output = $("#log-output");
    output.textContent = text || "Nessuna riga di log disponibile.";
    if ($("#log-autoscroll").checked) output.scrollTop = output.scrollHeight;
}

function bindHandlers() {
    $$(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
    $("#notice-close").addEventListener("click", hideNotice);

    $("#single-file-button").addEventListener("click", async () => {
        const result = await callNative("chooseSingleFile");
        if (!result.ok) {
            showNotice("File non valido", result.error || "Impossibile selezionare il file.");
            return;
        }
        if (result.cancelled) return;
        state.singlePath = result.path;
        $("#single-file-name").textContent = result.name || basename(result.path);
        $("#single-file-display").title = result.path;
        $("#single-result-meta").textContent = "Pronto per l'elaborazione.";
        notifyUiState("single_selection_changed", { path: state.singlePath });
        updateOperationUi();
    });

    $("#single-start-button").addEventListener("click", async () => {
        if (!state.singlePath) return;
        const result = await callNative("startSingleOcr", state.singlePath);
        if (!result.ok) showNotice("OCR non avviato", result.error || "Operazione non disponibile.");
    });

    $("#single-cancel-button").addEventListener("click", () => callNative("cancelOperation"));
    $("#global-cancel-button").addEventListener("click", () => callNative("cancelOperation"));
    $("#copy-single-button").addEventListener("click", () => {
        if (state.singleText) state.backend?.copyText(state.singleText);
    });

    $("#batch-file-button").addEventListener("click", async () => {
        const result = await callNative("chooseBatchFiles");
        if (!result.ok) {
            showNotice("Selezione batch non valida", result.error || "Impossibile selezionare i file.");
            return;
        }
        if (result.cancelled) return;
        state.batchPaths = result.paths || [];
        state.batchStates = new Map(state.batchPaths.map((path) => [path, "In coda"]));
        state.batchResults.clear();
        renderBatchFiles();
        renderBatchResults();
        updateOperationUi();
    });

    $("#batch-start-button").addEventListener("click", async () => {
        const result = await callNative("startBatch", JSON.stringify(state.batchPaths));
        if (!result.ok) showNotice("Batch non avviato", result.error || "Operazione non disponibile.");
    });
    $("#batch-cancel-button").addEventListener("click", () => callNative("cancelOperation"));
    $("#log-refresh-button").addEventListener("click", refreshLogs);
    $("#copy-log-button").addEventListener("click", () => state.backend?.copyText($("#log-output").textContent || ""));

    $("#output-dir-button").addEventListener("click", async () => {
        const result = await callNative("chooseOutputDirectory", $("#output-dir-input").value);
        if (result.ok && !result.cancelled) $("#output-dir-input").value = result.path;
        else if (!result.ok) showNotice("Directory non disponibile", result.error || "Impossibile selezionare la directory.");
    });

    $("#settings-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const result = await callNative("updateSettings", JSON.stringify(collectSettings()));
        if (result.ok) {
            applySettings(result.settings);
            showNotice("Impostazioni salvate", "Le preferenze sono state aggiornate.");
        } else {
            showNotice("Impostazioni non salvate", result.error || "Errore sconosciuto.");
        }
    });

    $("#hardware-refresh-button").addEventListener("click", async () => {
        const result = await callNative("refreshHardware");
        if (result.ok) {
            state.devices = result.devices || [];
            updateBackendPanel();
        } else {
            showNotice("Rilevamento hardware fallito", result.error || "Errore sconosciuto.");
        }
    });

    $("#model-reload-button").addEventListener("click", async () => {
        const result = await callNative("reloadModel");
        if (!result.ok) showNotice("Modello non ricaricato", result.error || "Operazione non disponibile.");
    });

    $("#quit-button").addEventListener("click", () => state.backend?.forceQuit());

    let resizeTimer = 0;
    window.addEventListener("resize", () => {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(() => {
            if (state.backend) state.backend.setWindowSize(window.innerWidth, window.innerHeight);
        }, 600);
    });

    window.setInterval(() => {
        if (state.activeView === "logs") refreshLogs();
    }, 1800);
}

async function bootstrap() {
    const result = await callNative("bootstrap");
    if (!result.ok) {
        showNotice("Avvio UI incompleto", "Impossibile leggere lo stato dell'applicazione.", result.error || "");
        return;
    }
    const data = result.data;
    state.operation = data.runtime.operation || "idle";
    state.modelReady = Boolean(data.runtime.model_ready);
    state.devices = data.devices || [];
    state.limits = data.limits || state.limits;

    applySettings(data.settings || {});
    $("#model-cache-path").textContent = data.paths?.model_cache || "—";
    updateBackendPanel();
    updateOperationUi();
    if (state.modelReady) setModelStatus("Modello pronto", true);
    else setModelStatus("Backend in inizializzazione", true);

    state.backend.initializeBackend();
}

function connectBackend() {
    if (typeof qt === "undefined" || !qt.webChannelTransport || typeof QWebChannel === "undefined") {
        showNotice("Bridge non disponibile", "La UI deve essere avviata da main.py, non aperta direttamente nel browser.");
        setModelStatus("Bridge non disponibile", false);
        return;
    }
    new QWebChannel(qt.webChannelTransport, (channel) => {
        state.backend = channel.objects.backend;
        state.backend.event.connect(handleEvent);
        bootstrap();
    });
}

document.addEventListener("DOMContentLoaded", () => {
    bindHandlers();
    setView("ocr");
    renderBatchFiles();
    renderBatchResults();
    runExtensionHook("initialize");
    connectBackend();
});
