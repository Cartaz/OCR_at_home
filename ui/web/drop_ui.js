"use strict";

(() => {
    function applySingleSelection(path) {
        state.singlePath = path;
        $("#single-file-name").textContent = basename(path);
        $("#single-file-display").title = path;
        $("#single-result-meta").textContent = "Pronto per l'elaborazione.";
        notifyUiState("single_selection_changed", { path: state.singlePath });
        updateOperationUi();
    }

    function applyBatchSelection(paths) {
        state.batchPaths = [...paths];
        state.batchStates = new Map(state.batchPaths.map((path) => [path, "In coda"]));
        state.batchResults.clear();
        renderBatchFiles();
        renderBatchResults();
        updateOperationUi();
    }

    function applyDroppedFiles(payload) {
        if (state.operation !== "idle") return;
        const paths = Array.isArray(payload.paths)
            ? payload.paths.map((path) => String(path || "")).filter(Boolean)
            : [];
        if (!paths.length) return;

        if (state.activeView === "batch") {
            applyBatchSelection(paths);
            return;
        }
        if (state.activeView === "ocr" && paths.length === 1) {
            applySingleSelection(paths[0]);
            return;
        }

        const targetView = paths.length === 1 ? "ocr" : "batch";
        setView(targetView);
        if (targetView === "ocr") applySingleSelection(paths[0]);
        else applyBatchSelection(paths);
    }

    registerUiExtension({
        onBackendEvent(type, payload) {
            if (type === "files_dropped") applyDroppedFiles(payload);
        },
        initialize() {
            $("#single-file-button").title = "Scegli un file o trascinalo nella finestra";
            $("#batch-file-button").title = "Scegli file o trascinali nella finestra";
            $("#single-file-display").setAttribute(
                "aria-description",
                "Puoi anche trascinare un'immagine o un PDF nella finestra."
            );
            $("#batch-file-list").setAttribute(
                "aria-description",
                "Puoi anche trascinare uno o più documenti nella finestra."
            );
        },
    });
})();
