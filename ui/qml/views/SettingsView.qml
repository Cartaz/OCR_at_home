import QtQuick
import "../components"

// Settings view (#view-settings): backend panel + preferences form.
Column {
    id: root
    property bool compact: false
    property bool narrow: false

    function loadForm() {
        const s = backend.settings
        preprocess.checked = s.preprocessing_enabled
        loadAtStartup.checked = s.load_model_at_startup
        autoUnload.selectValue(s.model_auto_unload_minutes)
        outputDir.text = s.output_dir
        batchAutoSave.checked = s.batch_auto_save
        batchFormat.selectValue(s.batch_output_format)
        batchPages.checked = s.batch_save_pdf_pages
    }
    function collectForm() {
        return {
            preprocessing_enabled: preprocess.checked,
            load_model_at_startup: loadAtStartup.checked,
            model_auto_unload_minutes: autoUnload.currentValue,
            output_dir: outputDir.text,
            batch_auto_save: batchAutoSave.checked,
            batch_output_format: batchFormat.currentValue,
            batch_save_pdf_pages: batchPages.checked
        }
    }
    Component.onCompleted: loadForm()
    Connections {
        target: backend
        function onSettingsChanged() { root.loadForm() }
    }

    SectionHeading {
        x: 4
        width: root.width - 8
        narrow: root.narrow
        title: "Impostazioni e backend"
        description: "Preferenze persistenti e stato reale del runtime SYCL."
    }
    Item { width: 1; height: 22 }

    Item {
        id: grid
        width: root.width
        readonly property real gap: 24
        // CSS grid: minmax(280px, .8fr) minmax(360px, 1.2fr)
        readonly property real leftWidth: root.compact ? width : Math.max(280, (width - gap) * 0.4)
        readonly property real rightWidth: root.compact ? width : width - gap - leftWidth
        implicitHeight: root.compact ? backendPanel.height + gap + formPanel.height
                                     : Math.max(backendPanel.height, formPanel.height)

        Panel {
            id: backendPanel
            width: grid.leftWidth
            height: implicitHeight
            padding: root.narrow ? 17 : 22
            Item {
                width: parent.width
                height: Math.max(backendHeading.implicitHeight, chip.height)
                Column {
                    id: backendHeading
                    width: parent.width - chip.width - 16
                    anchors.verticalCenter: parent.verticalCenter
                    FieldLabel { text: "Backend di calcolo"; marginBottom: 3 }
                    MetaText { width: parent.width; text: "GLM OCR è configurato esclusivamente per llama.cpp + SYCL." }
                }
                Chip {
                    id: chip
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: backend.backendChipText
                    active: backend.backendChipActive
                }
            }
            Item { width: 1; height: 14 }
            Repeater {
                model: [
                    ["Device", backend.backendDevice],
                    ["Disponibilità", backend.backendAvailability],
                    ["Modello", backend.modelCachePath]
                ]
                Item {
                    required property var modelData
                    width: backendPanel.width - 2 * backendPanel.padding
                    height: dd.height + 23
                    Rectangle { width: parent.width; height: 1; color: Theme.hairline }
                    CssText { y: 12; text: modelData[0]; color: Theme.textMuted; font.pixelSize: 14 }
                    CssText {
                        id: dd
                        y: 12
                        x: root.narrow ? 98 : 116
                        width: parent.width - x
                        text: modelData[1]
                        color: Theme.textSecondary
                        font.pixelSize: 14
                        wrapMode: Text.Wrap
                    }
                }
            }
            Item { width: 1; height: 18 }
            Flow {
                width: parent.width
                spacing: 12
                NeuButton { text: "Rileva hardware"; enabled: !backend.busy; onClicked: backend.refreshHardware() }
                NeuButton { text: backend.reloadModelLabel; enabled: backend.canReloadModel; onClicked: backend.reloadModel() }
                NeuButton { text: "Scarica modello"; enabled: backend.canUnloadModel; onClicked: backend.unloadModel() }
            }
        }

        Panel {
            id: formPanel
            x: root.compact ? 0 : grid.leftWidth + grid.gap
            y: root.compact ? backendPanel.height + grid.gap : 0
            width: grid.rightWidth
            height: implicitHeight
            padding: root.narrow ? 17 : 22

            SettingRow {
                id: preprocess
                width: parent.width
                label: "Pre-elaborazione immagine"
                help: "Migliora contrasto e leggibilità prima dell'inferenza."
            }
            SettingRow {
                id: loadAtStartup
                width: parent.width
                label: "Carica modello all'avvio"
                help: "Se disattivato, l'interfaccia parte senza occupare RAM/VRAM e carica il modello al primo OCR."
            }
            Column {
                width: parent.width
                topPadding: 20
                FieldLabel { text: "Scarica modello dopo inattività"; marginBottom: 9 }
                NeuSelect {
                    id: autoUnload
                    width: parent.width
                    accessibleName: "Auto-unload modello"
                    model: [
                        { text: "Mai", value: 0 },
                        { text: "5 minuti", value: 5 },
                        { text: "15 minuti", value: 15 },
                        { text: "30 minuti", value: 30 },
                        { text: "60 minuti", value: 60 },
                        { text: "2 ore", value: 120 }
                    ]
                }
                CssText {
                    width: parent.width
                    marginTop: 8
                    text: "Il timer parte quando il backend torna inattivo; un nuovo OCR ricarica automaticamente il modello."
                    color: Theme.textMuted
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }
            }
            Column {
                width: parent.width
                topPadding: 20
                FieldLabel { text: "Directory output"; marginBottom: 9 }
                Row {
                    width: parent.width
                    spacing: 14
                    NeuTextField {
                        id: outputDir
                        width: parent.width - folderButton.width - 14
                        height: 46
                        accessibleName: "Directory output"
                    }
                    NeuButton {
                        id: folderButton
                        anchors.verticalCenter: outputDir.verticalCenter
                        variant: "icon"
                        iconName: "folder"
                        tooltip: "Scegli directory"
                        onClicked: {
                            const chosen = backend.chooseOutputDirectory(outputDir.text)
                            if (chosen.length) outputDir.text = chosen
                        }
                    }
                }
                CssText {
                    width: parent.width
                    marginTop: 8
                    text: "I risultati manuali e gli output batch automatici vengono scritti qui. I file esistenti non vengono sovrascritti."
                    color: Theme.textMuted
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }
            }
            SettingRow {
                id: batchAutoSave
                width: parent.width
                label: "Salvataggio automatico batch"
                help: "Salva ogni documento completato senza attendere la fine dell'intero batch."
            }
            Column {
                width: parent.width
                topPadding: 20
                FieldLabel { text: "Formato output batch"; marginBottom: 9 }
                NeuSelect {
                    id: batchFormat
                    width: parent.width
                    enabled: batchAutoSave.checked
                    accessibleName: "Formato output batch"
                    model: [{ text: "TXT", value: "txt" }, { text: "Markdown", value: "md" }]
                }
            }
            SettingRow {
                id: batchPages
                width: parent.width
                toggleEnabled: batchAutoSave.checked
                label: "Pagine PDF separate nel batch"
                help: "Oltre al file combinato, salva un file numerato per ogni pagina PDF."
            }
            Item {
                width: parent.width
                height: 62
                NeuButton {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    text: "Salva impostazioni"
                    primary: true
                    onClicked: backend.saveSettings(root.collectForm())
                }
            }
        }
    }
}
