"use strict";

(() => {
    let resultSourcePath = "";
    let completedSourcePath = "";

    const txtButton = document.querySelector("#save-single-txt-button");
    const mdButton = document.querySelector("#save-single-md-button");
    const pagesTxtButton = document.querySelector("#save-single-pages-txt-button");
    const pagesMdButton = document.querySelector("#save-single-pages-md-button");
    const resultNode = document.querySelector("#single-result");
    const fileNameNode = document.querySelector("#single-file-name");
    const batchAutoSave = document.querySelector("#batch-auto-save-toggle");
    const batchFormat = document.querySelector("#batch-output-format");
    const batchPdfPages = document.querySelector("#batch-pdf-pages-toggle");

    if (!txtButton || !mdButton || !pagesTxtButton || !pagesMdButton || !resultNode || !fileNameNode) return;

    function sameSource(a, b) {
        return Boolean(a && b && String(a) === String(b));
    }

    function hasSavableResult() {
        return Boolean(
            state.singleText &&
            state.singlePath &&
            resultSourcePath &&
            sameSource(resultSourcePath, state.singlePath) &&
            sameSource(completedSourcePath, state.singlePath)
        );
    }

    function updateButtons() {
        const enabled = hasSavableResult();
        txtButton.disabled = !enabled;
        mdButton.disabled = !enabled;

        const showPages = enabled && Boolean(state.singleIsPdf);
        pagesTxtButton.classList.toggle("hidden", !showPages);
        pagesMdButton.classList.toggle("hidden", !showPages);
        pagesTxtButton.disabled = !showPages;
        pagesMdButton.disabled = !showPages;
    }

    function updateBatchOptionState() {
        if (!batchAutoSave || !batchFormat || !batchPdfPages) return;
        const enabled = batchAutoSave.checked;
        batchFormat.disabled = !enabled;
        batchPdfPages.disabled = !enabled;
    }

    function trackResult() {
        if (
            state.singleText &&
            resultNode.textContent === state.singleText &&
            sameSource(completedSourcePath, state.singlePath)
        ) {
            resultSourcePath = completedSourcePath;
        } else if (!state.singleText || !sameSource(completedSourcePath, state.singlePath)) {
            resultSourcePath = "";
        }
        updateButtons();
    }

    function trackSelection() {
        if (!sameSource(completedSourcePath, state.singlePath)) resultSourcePath = "";
        updateButtons();
    }

    async function save(format) {
        if (!hasSavableResult()) {
            showNotice(
                "Nessun risultato da salvare",
                "Completa l'OCR sul documento selezionato prima di salvare."
            );
            return;
        }
        const result = await callNative(
            "saveSingleResult",
            resultSourcePath,
            format
        );
        if (!result.ok) {
            showNotice(
                "Risultato non salvato",
                result.error || "Impossibile scrivere il file di output."
            );
            return;
        }
        showNotice(
            "Risultato salvato",
            `${result.name} salvato nella directory output configurata.`,
            result.path || ""
        );
    }

    async function savePages(format) {
        if (!hasSavableResult() || !state.singleIsPdf) {
            showNotice(
                "Pagine non disponibili",
                "Completa l'OCR di un PDF prima di salvare le pagine separate."
            );
            return;
        }
        const result = await callNative(
            "saveSinglePdfPages",
            resultSourcePath,
            format
        );
        if (!result.ok) {
            showNotice(
                "Pagine non salvate",
                result.error || "Impossibile scrivere le pagine PDF."
            );
            return;
        }
        showNotice(
            "Pagine PDF salvate",
            `${result.count} file pagina salvati nella directory output configurata.`,
            (result.paths || []).join("\n")
        );
    }

    // Extend the main settings plumbing without duplicating its submit handler.
    const baseApplySettings = applySettings;
    applySettings = function applyOutputSettings(settings) {
        baseApplySettings(settings);
        if (batchAutoSave) batchAutoSave.checked = Boolean(settings.batch_auto_save);
        if (batchFormat) batchFormat.value = String(settings.batch_output_format || "txt");
        if (batchPdfPages) batchPdfPages.checked = Boolean(settings.batch_save_pdf_pages);
        updateBatchOptionState();
    };

    const baseCallNative = callNative;
    callNative = function callNativeWithOutputSettings(name, ...args) {
        if (name === "updateSettings" && typeof args[0] === "string") {
            try {
                const payload = JSON.parse(args[0]);
                if (batchAutoSave) payload.batch_auto_save = batchAutoSave.checked;
                if (batchFormat) payload.batch_output_format = batchFormat.value;
                if (batchPdfPages) payload.batch_save_pdf_pages = batchPdfPages.checked;
                args[0] = JSON.stringify(payload);
            } catch (_error) {
                // The base bridge will return the canonical validation error.
            }
        }
        return baseCallNative(name, ...args);
    };

    // Track real completion state and surface automatic-output failures/summaries.
    const baseHandleEvent = handleEvent;
    handleEvent = function handleOutputEvent(raw) {
        let message = null;
        try {
            message = JSON.parse(raw);
        } catch (_error) {
            // Let the base handler report malformed events.
        }

        baseHandleEvent(raw);

        const type = message?.type;
        const payload = message?.payload || {};
        if (type === "ocr_started") {
            completedSourcePath = "";
            resultSourcePath = "";
        } else if (type === "ocr_completed") {
            completedSourcePath = String(payload.image_path || state.singlePath || "");
            if (state.singleText && sameSource(completedSourcePath, state.singlePath)) {
                resultSourcePath = completedSourcePath;
            }
        } else if (type === "ocr_cancelled" || type === "ocr_failed") {
            completedSourcePath = "";
            resultSourcePath = "";
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
    };

    txtButton.addEventListener("click", () => save("txt"));
    mdButton.addEventListener("click", () => save("md"));
    pagesTxtButton.addEventListener("click", () => savePages("txt"));
    pagesMdButton.addEventListener("click", () => savePages("md"));
    batchAutoSave?.addEventListener("change", updateBatchOptionState);

    new MutationObserver(trackResult).observe(resultNode, {
        childList: true,
        characterData: true,
        subtree: true,
    });
    new MutationObserver(trackSelection).observe(fileNameNode, {
        childList: true,
        characterData: true,
        subtree: true,
    });

    updateBatchOptionState();
    updateButtons();
})();
