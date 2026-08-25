"use strict";

(() => {
    function applySingleSelection(path, displayName = "") {
        state.singlePath = path;
        $("#single-file-name").textContent = displayName || basename(path);
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

    function applyLocalInputs(payload) {
        if (state.operation !== "idle") return;
        const paths = Array.isArray(payload.paths)
            ? payload.paths.map((path) => String(path || "")).filter(Boolean)
            : [];
        if (!paths.length) return;

        const names = Array.isArray(payload.names)
            ? payload.names.map((name) => String(name || ""))
            : [];

        if (state.activeView === "batch") {
            applyBatchSelection(paths);
            return;
        }
        if (state.activeView === "ocr" && paths.length === 1) {
            applySingleSelection(paths[0], names[0]);
            return;
        }

        const targetView = paths.length === 1 ? "ocr" : "batch";
        setView(targetView);
        if (targetView === "ocr") applySingleSelection(paths[0], names[0]);
        else applyBatchSelection(paths);
    }

    function targetAcceptsTextPaste(target) {
        if (!(target instanceof HTMLElement)) return false;
        return target.isContentEditable || Boolean(target.closest("input, textarea, select"));
    }

    async function requestClipboardImage() {
        if (state.operation !== "idle") return;
        const result = await callNative("pasteClipboardImage");
        if (!result.ok) {
            showNotice(
                "Clipboard non disponibile",
                result.error || "Impossibile incollare l'immagine dagli appunti.",
                "",
                true,
            );
            return;
        }
        applyLocalInputs({
            paths: [result.path],
            names: [result.name || "Immagine dagli appunti.png"],
        });
    }

    function handlePaste(event) {
        if (targetAcceptsTextPaste(event.target)) return;
        if (state.operation !== "idle") return;
        event.preventDefault();
        void requestClipboardImage();
    }

    registerUiExtension({
        onBackendEvent(type, payload) {
            if (type === "files_dropped") applyLocalInputs(payload);
        },
        initialize() {
            $("#single-file-button").title = "Scegli file o trascinalo nella finestra (Ctrl+O)";
            $("#batch-file-button").title = "Scegli file o trascinali nella finestra";
            $("#single-file-display").setAttribute("aria-keyshortcuts", "Control+V");
            $("#single-file-display").setAttribute(
                "aria-description",
                "Puoi trascinare un'immagine o un PDF nella finestra oppure incollare un'immagine con Ctrl+V."
            );
            $("#batch-file-list").setAttribute(
                "aria-description",
                "Puoi trascinare uno o più documenti nella finestra; Ctrl+V aggiunge un'immagine dagli appunti come selezione locale."
            );
            document.addEventListener("paste", handlePaste);
        },
    });
})();
