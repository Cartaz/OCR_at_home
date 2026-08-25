"use strict";

(() => {
    const unloadButton = document.querySelector("#model-unload-button");
    const reloadButton = document.querySelector("#model-reload-button");
    const loadAtStartup = document.querySelector("#load-model-startup-toggle");
    const autoUnload = document.querySelector("#model-auto-unload-select");

    if (!unloadButton || !reloadButton || !loadAtStartup || !autoUnload) return;

    function backendAvailable() {
        return state.devices.some((device) => Boolean(device?.available));
    }

    function updateModelControls() {
        const busy = state.operation !== "idle";
        reloadButton.textContent = state.modelReady ? "Ricarica modello" : "Carica modello";
        reloadButton.disabled = busy || !backendAvailable();
        unloadButton.disabled = busy || !state.modelReady;

        if (!busy) {
            $("#single-start-button").disabled = !backendAvailable() || !state.singlePath;
            $("#batch-start-button").disabled = !backendAvailable() || state.batchPaths.length === 0;
        }

        if (!state.modelReady && !busy && backendAvailable()) {
            const chip = $("#backend-chip");
            chip.textContent = "Scaricato";
            chip.classList.remove("active");
            $("#sidebar-status-text").textContent = "Modello scaricato";
        }

        if (state.operation === "model_unloading") {
            $("#global-cancel-button").classList.add("hidden");
            $("#global-cancel-button").disabled = true;
            $("#sidebar-status-text").textContent = "Scaricamento modello";
            $("#ocr-operation-label").textContent = "In attesa";
            $("#ocr-operation-label").classList.remove("active");
            $("#batch-operation-label").textContent = "In attesa";
            $("#batch-operation-label").classList.remove("active");
        }
    }

    registerUiExtension({
        applySettings(settings) {
            loadAtStartup.checked = settings.load_model_at_startup !== false;
            const minutes = String(Number(settings.model_auto_unload_minutes || 0));
            if (![...autoUnload.options].some((option) => option.value === minutes)) {
                const option = document.createElement("option");
                option.value = minutes;
                option.textContent = `${minutes} minuti`;
                autoUnload.append(option);
            }
            autoUnload.value = minutes;
            updateModelControls();
        },
        collectSettings(payload) {
            payload.load_model_at_startup = loadAtStartup.checked;
            payload.model_auto_unload_minutes = Number(autoUnload.value || 0);
        },
        refreshUi() {
            updateModelControls();
        },
        onBackendEvent(type, payload) {
            if (type === "model_unloading") {
                setModelStatus("Scaricamento modello…", true);
            } else if (type === "model_unloaded") {
                state.modelReady = false;
                setModelStatus("Modello scaricato", false);
                updateBackendPanel();
                updateOperationUi();
            } else if (type === "model_unload_failed") {
                showNotice(
                    "Modello non scaricato",
                    "Il backend non è stato rilasciato correttamente.",
                    String(payload.error || "")
                );
            }
            updateModelControls();
        },
        initialize() {
            updateModelControls();
        },
    });

    unloadButton.addEventListener("click", async () => {
        const result = await callNative("unloadModel");
        if (!result.ok) {
            showNotice(
                "Modello non scaricato",
                result.error || "Impossibile rilasciare il backend."
            );
        }
    });
})();
