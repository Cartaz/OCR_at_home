"use strict";

(() => {
    const languageInput = document.getElementById("language-input");
    if (languageInput && languageInput.tagName !== "SELECT") {
        const currentValue = String(languageInput.value || "ita+eng");
        const select = document.createElement("select");
        select.id = "language-input";
        select.name = "language";
        select.setAttribute("aria-label", "Lingua OCR configurata");

        const choices = [
            ["ita", "Italiano"],
            ["eng", "English"],
            ["ita+eng", "Italiano + English"],
        ];
        if (!choices.some(([value]) => value === currentValue)) {
            choices.push([currentValue, currentValue]);
        }
        for (const [value, label] of choices) {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = label;
            select.append(option);
        }
        select.value = currentValue;

        const parent = languageInput.parentElement;
        if (parent) {
            parent.classList.add("language-select-field");
            languageInput.replaceWith(select);
            const chevron = document.createElement("span");
            chevron.className = "select-chevron";
            chevron.setAttribute("aria-hidden", "true");
            chevron.textContent = "⌄";
            parent.append(chevron);
        }

        const field = select.closest(".form-field");
        const help = field?.querySelector(".field-help");
        if (help) {
            help.textContent = "Preferenza salvata per compatibilità; il prompt GLM-OCR attuale resta neutro e non forza la lingua.";
        }
    }

    const confidenceInput = document.getElementById("confidence-input");
    const confidenceField = confidenceInput?.closest(".form-field");
    if (confidenceField) {
        confidenceField.hidden = true;
        confidenceField.setAttribute("aria-hidden", "true");
    }

    const style = document.createElement("style");
    style.textContent = `
        .language-select-field { position: relative; }
        .language-select-field select {
            width: 100%;
            min-width: 0;
            border: 0;
            outline: 0;
            padding: 0 38px 0 0;
            background: rgb(20, 20, 20);
            color: rgb(218, 218, 218);
            font: inherit;
            line-height: inherit;
            appearance: none;
            color-scheme: dark;
            cursor: pointer;
        }
        .language-select-field select option {
            background: rgb(20, 20, 20);
            color: rgb(218, 218, 218);
        }
        .language-select-field .select-chevron {
            position: absolute;
            top: 50%;
            right: 12px;
            transform: translateY(-54%);
            color: rgb(255, 102, 0);
            font-size: 18px;
            line-height: 1;
            pointer-events: none;
        }
    `;
    document.head.append(style);
})();
