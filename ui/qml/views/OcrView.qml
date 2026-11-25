import QtQuick
import "../components"

// Single-document view (#view-ocr).
Column {
    id: root
    property bool narrow: false
    property real viewportHeight: 800
    readonly property real resultMaxHeight: Math.min(viewportHeight * (narrow ? 0.48 : 0.52), 560)

    SectionHeading {
        objectName: "ocrHeading"
        x: 4
        width: root.width - 8
        narrow: root.narrow
        title: "Documento singolo"
        description: "Immagine o PDF, elaborazione locale sul backend SYCL."
        chipText: backend.ocrOperationLabel
        chipActive: backend.operation === "ocr"
    }
    Item { width: 1; height: 22 }

    Panel {
        objectName: "filePanel"
        width: root.width
        padding: root.narrow ? 17 : 22
        FieldLabel { text: "Documento"; marginBottom: 9 }
        Flow {
            width: parent.width
            spacing: 14
            NeuSurface {
                id: fileDisplay
                objectName: "singleFileDisplay"
                width: root.narrow ? parent.width : parent.width - chooseButton.width - 14
                height: 46
                radius: Theme.radiusMD
                shadow: Theme.insetSmall
                Accessible.role: Accessible.StaticText
                Accessible.name: backend.singleName
                Row {
                    x: 14
                    width: parent.width - 28
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 10
                    Icon { name: "file"; color: Theme.textMuted; anchors.verticalCenter: parent.verticalCenter }
                    CssText {
                        width: parent.width - 30
                        text: backend.singleName
                        color: Theme.textSecondary
                        font.pixelSize: 14
                        elide: Text.ElideMiddle
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
            NeuButton {
                id: chooseButton
                objectName: "singleFileButton"
                width: root.narrow ? parent.width : implicitWidth
                height: root.narrow ? 44 : 46
                text: "Scegli file"
                iconName: "folder"
                tooltip: "Scegli file o trascinalo nella finestra (Ctrl+O)"
                enabled: backend.canChooseSingle
                onClicked: backend.chooseSingleFile()
            }
        }
        Item { width: 1; height: 18 }
        Flow {
            width: parent.width
            spacing: 12
            NeuButton {
                objectName: "singleStartButton"
                text: "Avvia OCR"
                iconName: "play"
                primary: true
                tooltip: "Avvia OCR (Ctrl+Enter)"
                enabled: backend.canStartSingle
                onClicked: backend.startSingleOcr()
            }
            NeuButton {
                text: "Annulla"
                iconName: "stop"
                enabled: backend.canCancelSingle
                onClicked: backend.cancelOperation()
            }
        }
    }
    Item { width: 1; height: 26 }

    ProgressBlock {
        visible: backend.singleProgressVisible
        x: 4
        width: root.width - 8
        label: backend.singleProgressLabel
        valueText: backend.singleProgressValue
        value: backend.singleProgress
    }
    Item { width: 1; height: 26; visible: backend.singleProgressVisible }

    Panel {
        objectName: "resultPanel"
        width: root.width
        padding: root.narrow ? 17 : 22
        implicitHeight: Math.max(250, bodyHeight + 2 * padding)
        Item {
            id: resultToolbar
            // CSS flex-wrap: wrap only when heading + controls do not fit.
            readonly property bool wrapped: headingNatural.width + 16 + controls.rowWidth > width
            width: parent.width
            height: wrapped ? resultHeading.height + 16 + controls.height
                            : Math.max(resultHeading.height, controls.height)
            TextMetrics { id: headingNatural; font.pixelSize: 12; font.weight: Font.Bold; text: "Testo riconosciuto" }
            Column {
                id: resultHeading
                width: resultToolbar.wrapped ? parent.width : parent.width - controls.width - 16
                y: root.narrow || resultToolbar.wrapped ? 0 : (parent.height - height) / 2
                FieldLabel { text: "Testo riconosciuto"; marginBottom: 3 }
                MetaText { objectName: "singleResultMeta"; width: parent.width; text: backend.singleMeta }
            }
            Flow {
                id: controls
                x: resultToolbar.wrapped ? 0 : parent.width - width
                y: resultToolbar.wrapped ? resultHeading.height + 16 : 0
                // Flow needs an explicit width: on wide layouts it is the single-row width.
                readonly property real rowWidth: {
                    let total = 0, count = 0
                    for (let i = 0; i < children.length; ++i) {
                        if (children[i].visible) { total += children[i].implicitWidth; ++count }
                    }
                    return total + Math.max(0, count - 1) * spacing
                }
                width: resultToolbar.wrapped ? parent.width : rowWidth
                spacing: 14
                NeuButton { objectName: "saveTxtButton"; text: "TXT"; tooltip: "Salva come TXT"; enabled: backend.canSaveSingle; onClicked: backend.saveSingle("txt") }
                NeuButton { text: "MD"; tooltip: "Salva come Markdown"; enabled: backend.canSaveSingle; onClicked: backend.saveSingle("md") }
                NeuButton { visible: backend.showPageSave; text: "TXT pagine"; tooltip: "Salva ogni pagina PDF come TXT"; enabled: backend.canSaveSingle; onClicked: backend.saveSinglePages("txt") }
                NeuButton { visible: backend.showPageSave; text: "MD pagine"; tooltip: "Salva ogni pagina PDF come Markdown"; enabled: backend.canSaveSingle; onClicked: backend.saveSinglePages("md") }
                NeuButton {
                    variant: "icon"
                    iconName: "copy"
                    tooltip: "Copia testo (Ctrl+Shift+C)"
                    enabled: backend.canCopySingle
                    onClicked: backend.copyText(backend.singleText)
                }
            }
        }
        Item { width: 1; height: 14 }
        InsetTextView {
            id: resultView
            objectName: "singleResult"
            width: parent.width
            height: Math.max(190, Math.min(root.resultMaxHeight, flickable.contentHeight))
            text: backend.singleText.length ? backend.singleText : "Nessun risultato."
        }
    }
}
