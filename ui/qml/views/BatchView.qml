import QtQuick
import QtQuick.Controls.Basic as Basic
import "../components"

// Batch view (#view-batch).
Column {
    id: root
    property bool narrow: false
    property real viewportHeight: 800
    readonly property real resultMaxHeight: Math.min(viewportHeight * (narrow ? 0.48 : 0.52), 560)
    property var openResults: ({})

    SectionHeading {
        x: 4
        width: root.width - 8
        narrow: root.narrow
        title: "Batch OCR"
        description: "Elaborazione sequenziale di più documenti, con cancellazione reale."
        chipText: backend.batchOperationLabel
        chipActive: backend.operation === "batch"
    }
    Item { width: 1; height: 22 }

    Panel {
        width: root.width
        padding: root.narrow ? 17 : 22
        Item {
            id: queueToolbar
            readonly property bool wrapped: queueNatural.width + 16 + pick.width > width
            width: parent.width
            height: wrapped ? queueHeading.height + 16 + pick.height : Math.max(queueHeading.height, pick.height)
            TextMetrics { id: queueNatural; font.pixelSize: 12; font.weight: Font.Bold; text: "Coda documenti" }
            Column {
                id: queueHeading
                width: queueToolbar.wrapped ? parent.width : parent.width - pick.width - 16
                y: root.narrow || queueToolbar.wrapped ? 0 : (parent.height - height) / 2
                FieldLabel { text: "Coda documenti"; marginBottom: 3 }
                MetaText { width: parent.width; text: backend.batchCountLabel }
            }
            NeuButton {
                id: pick
                x: queueToolbar.wrapped ? 0 : parent.width - width
                y: queueToolbar.wrapped ? queueHeading.height + 16 : 0
                text: "Scegli file"
                iconName: "folderPlus"
                tooltip: "Scegli file o trascinali nella finestra"
                enabled: !backend.busy
                onClicked: backend.chooseBatchFiles()
            }
        }
        Item { width: 1; height: 14 }
        NeuSurface {
            width: parent.width
            height: Math.min(250, listColumn.implicitHeight + 14)
            radius: Theme.radiusMD
            shadow: Theme.insetSmall
            Flickable {
                anchors.fill: parent
                anchors.topMargin: 7
                anchors.bottomMargin: 7
                clip: true
                contentHeight: listColumn.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                Basic.ScrollBar.vertical: NeuScrollBar {}
                Column {
                    id: listColumn
                    width: parent.width
                    CssText {
                        visible: backend.batchFiles.length === 0
                        width: parent.width
                        marginTop: 18
                        marginBottom: 18
                        horizontalAlignment: Text.AlignHCenter
                        text: "Nessun documento in coda."
                        color: Theme.textMuted
                        font.pixelSize: 14
                    }
                    Repeater {
                        model: backend.batchFiles
                        Item {
                            required property var modelData
                            required property int index
                            width: listColumn.width
                            // border-top (1px) + 7px padding around the 34px remove button
                            height: (index > 0 ? 1 : 0) + Math.max(42, remove.height + 14)
                            Rectangle { visible: index > 0; width: parent.width; height: 1; color: Theme.hairline }
                            CssText {
                                x: 14
                                width: parent.width - 28 - controls.width - 12
                                y: (index > 0 ? 1 : 0) + (parent.height - (index > 0 ? 1 : 0) - height) / 2
                                text: modelData.name
                                color: Theme.textSecondary
                                font.pixelSize: 14
                                elide: Text.ElideRight
                            }
                            Row {
                                id: controls
                                anchors.right: parent.right
                                anchors.rightMargin: 14
                                y: (index > 0 ? 1 : 0) + 7
                                spacing: 14
                                CssText {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.state
                                    color: modelData.active ? Theme.accent : Theme.textMuted
                                    font.pixelSize: 11
                                    font.weight: Theme.semiBold
                                }
                                NeuButton {
                                    id: remove
                                    variant: "compact"
                                    text: "×"
                                    tooltip: "Rimuovi " + modelData.name + " dalla coda"
                                    enabled: !backend.busy
                                    onClicked: backend.removeBatchFile(modelData.path)
                                }
                            }
                        }
                    }
                }
            }
        }
        Item { width: 1; height: 18 }
        Flow {
            width: parent.width
            spacing: 12
            NeuButton {
                text: "Avvia batch"
                iconName: "play"
                primary: true
                tooltip: "Avvia batch (Ctrl+Enter)"
                enabled: backend.canStartBatch
                onClicked: backend.startBatch()
            }
            NeuButton {
                text: "Annulla"
                iconName: "stop"
                enabled: backend.canCancelBatch
                onClicked: backend.cancelOperation()
            }
        }
    }
    Item { width: 1; height: 26 }

    ProgressBlock {
        visible: backend.batchProgressVisible
        x: 4
        width: root.width - 8
        label: backend.batchProgressLabel
        valueText: backend.batchProgressValue
        value: backend.batchProgress
    }
    Item { width: 1; height: 26; visible: backend.batchProgressVisible }

    Panel {
        width: root.width
        padding: root.narrow ? 17 : 22
        implicitHeight: Math.max(250, bodyHeight + 2 * padding)
        Column {
            width: parent.width
            FieldLabel { text: "Risultati batch"; marginBottom: 3 }
            MetaText { width: parent.width; text: "Ogni risultato resta associato al file sorgente." }
        }
        Item { width: 1; height: 14 }
        NeuSurface {
            width: parent.width
            height: Math.max(190, Math.min(root.resultMaxHeight, resultsColumn.implicitHeight + 16))
            radius: Theme.radiusMD
            shadow: Theme.insetSmall
            Flickable {
                anchors.fill: parent
                anchors.topMargin: 8
                anchors.bottomMargin: 8
                clip: true
                contentHeight: resultsColumn.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                Basic.ScrollBar.vertical: NeuScrollBar {}
                Column {
                    id: resultsColumn
                    width: parent.width
                    CssText {
                        visible: backend.batchResults.length === 0
                        width: parent.width
                        marginTop: 18
                        marginBottom: 18
                        horizontalAlignment: Text.AlignHCenter
                        text: "Nessun risultato."
                        color: Theme.textMuted
                        font.pixelSize: 14
                    }
                    Repeater {
                        model: backend.batchResults
                        Column {
                            id: item
                            required property var modelData
                            required property int index
                            readonly property bool open: root.openResults[modelData.path] === true
                            width: resultsColumn.width
                            topPadding: 14
                            bottomPadding: 14
                            Rectangle { visible: item.index > 0; y: 0; width: parent.width; height: 1; color: Theme.hairline }
                            Item {
                                x: 16
                                width: parent.width - 32
                                height: summaryName.implicitHeight
                                readonly property color tint: item.modelData.ok || item.open ? Theme.accent : Theme.textSecondary
                                CssText { id: summaryName; text: item.modelData.name; color: parent.tint; font.pixelSize: 14; font.weight: Theme.semiBold; elide: Text.ElideRight; width: parent.width - status.width - 12 }
                                CssText { id: status; anchors.right: parent.right; text: item.modelData.ok ? "Completato" : "Errore"; color: parent.tint; font.pixelSize: 14; font.weight: Theme.semiBold }
                                TapHandler {
                                    cursorShape: Qt.PointingHandCursor
                                    onTapped: {
                                        const next = Object.assign({}, root.openResults)
                                        next[item.modelData.path] = !item.open
                                        root.openResults = next
                                    }
                                }
                            }
                            TextEdit {
                                visible: item.open
                                x: 16
                                width: parent.width - 32
                                topPadding: 12
                                readOnly: true
                                selectByMouse: true
                                textFormat: TextEdit.PlainText
                                wrapMode: TextEdit.Wrap
                                text: item.modelData.text
                                color: Theme.textPrimary
                                selectionColor: Theme.selection
                                font.family: Theme.monoFamily
                                font.pixelSize: 12
                            }
                        }
                    }
                }
            }
        }
    }
}
