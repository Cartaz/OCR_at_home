"use strict";

(() => {
    let completedSourcePath = "";
    let manualSavePending = false;
    let pendingRequestId = "";

    const txtButton = document.querySelector("#save-single-txt-button");
    const mdButton = document.querySelector("#save-single-md-button");
    const pagesTxtButton = document.querySelector("#save-single-pages-txt-button");
    const pagesMdButton = document.querySelector("#save-single-pages-md-button");
    const batchAutoSave = document.querySelector("#batch-auto-save-toggle");
    const batchFormat = document.querySelector("#batch-output-format");
    const batchPdfPages = document.querySelector("#batch-pdf-pages-toggle");

    if (!txtButton || !mdButton || !pagesTxtButton || !pagesMdButton) return;

    function sameSource(a, b) {
        return Boolean(a && b && String(a) === String(b));
    }

    function hasSavableResult() {
        return Boolean(
            state.singleText &&
            state.singlePath &&
            sameSource(completedSourcePath, state.singlePath)
        );
    }

    function updateButtons() {
        const enabled = hasSavableResult() && !manualSavePending;
        txtButton.disabled = !enabled;
        mdButton.disabled = !enabled;

        const showPages = hasSavableResult() && Boolean(state.singleIsPdf);
        pagesTxtButton.classList.toggle("hidden", !showPages);
        pagesMdButton.classList.toggle("hidden", !showPages);
        pagesTxtButton.disabled = !showPages || manualSavePending;
        pagesMdButton.disabled = !showPages || manualSavePending;
    }

    function updateBatchOptionState() {
        if (!batchAutoSave || !batchFormat || !batchPdfPages) return;
        const enabled = batchAutoSave.checked;
        batchFormat.disabled = !enabled;
        batchPdfPages.disabled = !enabled;
    }

    function beginManualSave() {
        manualSavePending = true;
        pendingRequestId = "";
        updateButtons();
    }

    function finishManualSave(payload) {
        const eventRequestId = String(payload.request_id || "");
        if (!manualSavePending) return false;
        if (pendingRequestId && eventRequestId && pendingRequestId !== eventRequestId) {
            return false;
        }
        manualSavePending = false;
        pendingRequestId = "";
        updateButtons();
        return true;
    }

    async function requestManualSave(method, format, failureTitle) {
        beginManualSave();
        const result = await callNative(method, completedSourcePath, format);
        if (!result.ok) {
            manualSavePending = false;
            pendingRequestId = "";
            updateButtons();
            showNotice(
                failureTitle,
                result.error || "Impossibile avviare il salvataggio."
            );
            return;
        }
        // The worker can finish before this QWebChannel callback arrives. Never
        // restore pending state here; only remember the id if the event has not
        // already completed the request.
        if (manualSavePending) {
            pendingRequestId = String(result.request_id || "");
        }
    }

    async function save(format) {
        if (!hasSavableResult()) {
            showNotice(
                "Nessun risultato da salvare",
                "Completa l'OCR sul documento selezionato prima di salvare."
            );
            return;
        }
        await requestManualSave("saveSingleResult", format, "Risultato non salvato");
    }

    async function savePages(format) {
        if (!hasSavableResult() || !state.singleIsPdf) {
            showNotice(
                "Pagine non disponibili",
                "Completa l'OCR di un PDF prima di salvare le pagine separate."
            );
            return;
        }
        await requestManualSave("saveSinglePdfPages", format, "Pagine non salvate");
    }

    registerUiExtension({
        applySettings(settings) {
            if (batchAutoSave) batchAutoSave.checked = Boolean(settings.batch_auto_save);
            if (batchFormat) batchFormat.value = String(settings.batch_output_format || "txt");
            if (batchPdfPages) batchPdfPages.checked = Boolean(settings.batch_save_pdf_pages);
            updateBatchOptionState();
        },
        collectSettings(payload) {
            if (batchAutoSave) payload.batch_auto_save = batchAutoSave.checked;
            if (batchFormat) payload.batch_output_format = batchFormat.value;
            if (batchPdfPages) payload.batch_save_pdf_pages = batchPdfPages.checked;
        },
        onUiState(type) {
            if (type === "single_selection_changed" && !sameSource(completedSourcePath, state.singlePath)) {
                completedSourcePath = "";
                updateButtons();
            }
        },
        onBackendEvent(type, payload) {
            if (type === "ocr_started") {
                completedSourcePath = "";
            } else if (type === "ocr_completed") {
                completedSourcePath = String(payload.image_path || state.singlePath || "");
            } else if (type === "ocr_cancelled" || type === "ocr_failed") {
                completedSourcePath = "";
            } else if (type === "single_output_saved") {
                if (finishManualSave(payload)) {
                    if (payload.kind === "pages") {
                        showNotice(
                            "Pagine PDF salvate",
                            `${Number(payload.count || 0)} file pagina salvati nella directory output configurata.`,
                            (payload.paths || []).join("\n")
                        );
                    } else {
                        showNotice(
                            "Risultato salvato",
                            `${String(payload.name || "Risultato OCR")} salvato nella directory output configurata.`,
                            String(payload.path || "")
                        );
                    }
                }
            } else if (type === "single_output_save_failed") {
                if (finishManualSave(payload)) {
                    showNotice(
                        payload.kind === "pages" ? "Pagine non salvate" : "Risultato non salvato",
                        "Impossibile scrivere il file di output.",
                        String(payload.error || "")
                    );
                }
            } else if (type === "batch_output_save_failed") {
                showNotice(
                    "Output batch non salvato",
                    payload.image_path
                        ? `Impossibile salvare ${basename(payload.image_path)}.`
                        : "Impossibile salvare un risultato del batch.",
                    String(payload.error || "")
                );
            } else if (type === "batch_output_summary") {
                const saved = Number(payload.saved || 0);
                const failed = Number(payload.failed || 0);
                if (failed === 0 && saved > 0) {
                    showNotice(
                        "Output batch salvato",
                        `${saved} ${saved === 1 ? "risultato salvato" : "risultati salvati"} automaticamente.`,
                        String(payload.output_dir || "")
                    );
                } else if (failed > 0) {
                    showNotice(
                        "Salvataggio batch incompleto",
                        `${saved} salvati, ${failed} non salvati.`,
                        String(payload.output_dir || "")
                    );
                }
            }
            updateButtons();
        },
        initialize() {
            updateBatchOptionState();
            updateButtons();
        },
    });

    txtButton.addEventListener("click", () => save("txt"));
    mdButton.addEventListener("click", () => save("md"));
    pagesTxtButton.addEventListener("click", () => savePages("txt"));
    pagesMdButton.addEventListener("click", () => savePages("md"));
    batchAutoSave?.addEventListener("change", updateBatchOptionState);
})();
