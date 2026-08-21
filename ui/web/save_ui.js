"use strict";

(() => {
    let resultSourcePath = "";

    const txtButton = document.querySelector("#save-single-txt-button");
    const mdButton = document.querySelector("#save-single-md-button");
    const resultNode = document.querySelector("#single-result");
    const fileNameNode = document.querySelector("#single-file-name");

    if (!txtButton || !mdButton || !resultNode || !fileNameNode) return;

    function hasSavableResult() {
        return Boolean(
            state.singleText &&
            state.singlePath &&
            resultSourcePath &&
            resultSourcePath === state.singlePath
        );
    }

    function updateButtons() {
        const enabled = hasSavableResult();
        txtButton.disabled = !enabled;
        mdButton.disabled = !enabled;
    }

    function trackResult() {
        if (state.singleText && resultNode.textContent === state.singleText) {
            resultSourcePath = state.singlePath;
        } else if (!state.singleText) {
            resultSourcePath = "";
        }
        updateButtons();
    }

    function trackSelection() {
        if (resultSourcePath !== state.singlePath) updateButtons();
    }

    async function save(format) {
        if (!hasSavableResult()) {
            showNotice(
                "Nessun risultato da salvare",
                "Esegui l'OCR sul documento selezionato prima di salvare."
            );
            return;
        }
        const result = await callNative(
            "saveSingleResult",
            resultSourcePath,
            state.singleText,
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

    txtButton.addEventListener("click", () => save("txt"));
    mdButton.addEventListener("click", () => save("md"));

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

    updateButtons();
})();
