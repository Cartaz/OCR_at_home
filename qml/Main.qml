import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: window
    Theme { id: theme }

    visible: true
    minimumWidth: 680
    minimumHeight: 540
    width: Math.max(backend.initialWindowWidth, minimumWidth)
    height: Math.max(backend.initialWindowHeight, minimumHeight)

    title: "GLM OCR"
    color: theme.bgMain

    property int currentTab: 0

    onClosing: function(close) {
        backend.handleWindowClose()
        close.accepted = true
    }

    Shortcut { sequence: "Ctrl+Q"; onActivated: backend.forceQuit() }
    Shortcut { sequence: "Ctrl+M"; onActivated: backend.minimizeToTray() }

    Shortcut { sequence: "Ctrl+R"; enabled: window.currentTab === 0 && !backend.busy; onActivated: backend.startOcr() }
    Shortcut { sequence: "Ctrl+S"; enabled: window.currentTab === 0 && backend.ocrRunning; onActivated: backend.stopOcr() }
    Shortcut { sequence: "F5"; enabled: window.currentTab === 0 && !backend.busy; onActivated: backend.refreshDevices() }
    Shortcut { sequence: "Ctrl+L"; enabled: window.currentTab === 0 && !backend.busy; onActivated: backend.clearOcr() }
    Shortcut { sequence: "Ctrl+Shift+S"; enabled: window.currentTab === 0 && !backend.busy; onActivated: backend.saveOcr() }

    Shortcut { sequence: "Ctrl+B"; enabled: window.currentTab === 1 && !backend.busy; onActivated: backend.startBatch() }
    Shortcut { sequence: "Ctrl+S"; enabled: window.currentTab === 1 && backend.batchRunning; onActivated: backend.stopBatch() }
    Shortcut { sequence: "Ctrl+L"; enabled: window.currentTab === 1 && !backend.busy; onActivated: backend.clearBatch() }
    Shortcut { sequence: "Ctrl+Shift+S"; enabled: window.currentTab === 1 && !backend.busy; onActivated: backend.saveBatch() }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 12
        anchors.bottomMargin: 8
        spacing: 8

        Text {
            text: "GLM OCR"
            color: theme.accent
            font.pixelSize: 17
            font.weight: Font.Bold
            Layout.fillWidth: true
            Layout.topMargin: 2
        }

        Text {
            text: "Riconoscimento ottico con llama.cpp + SYCL"
            color: theme.textSecondary
            font.pixelSize: 12
            Layout.fillWidth: true
            Layout.bottomMargin: 5
        }

        Row {
            spacing: 3
            Layout.preferredHeight: 38

            NeoTabButton {
                text: "OCR"
                selected: window.currentTab === 0
                onClicked: window.currentTab = 0
            }

            NeoTabButton {
                text: "Batch"
                selected: window.currentTab === 1
                onClicked: window.currentTab = 1
            }
        }

        StackLayout {
            currentIndex: window.currentTab
            Layout.fillWidth: true
            Layout.fillHeight: true

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8

                    NeoCard {
                        title: "CONFIGURAZIONE OCR"
                        Layout.fillWidth: true

                        RowLayout {
                            spacing: 12
                            Layout.fillWidth: true
                            Layout.preferredHeight: theme.controlHeight

                            NeoComboBox {
                                id: languageCombo
                                model: ["Italiano + Inglese", "Inglese", "Italiano", "Francese", "Tedesco", "Spagnolo"]
                                currentIndex: backend.languageIndex
                                enabled: !backend.busy
                                Layout.fillWidth: true
                                onActivated: backend.setLanguageIndex(index)
                            }

                            NeoCheckBox {
                                text: "Pre-elaborazione"
                                checked: backend.preprocessingEnabled
                                enabled: !backend.busy
                                Layout.preferredWidth: 150
                                onToggled: backend.setPreprocessing(checked)
                            }
                        }

                        RowLayout {
                            spacing: 8
                            Layout.fillWidth: true
                            Layout.preferredHeight: theme.controlHeight

                            Text {
                                text: "Dispositivo:"
                                color: theme.textSecondary
                                font.pixelSize: 12
                            }

                            NeoComboBox {
                                id: deviceCombo
                                model: backend.devices
                                textRole: "label"
                                currentIndex: backend.deviceIndex
                                enabled: !backend.busy
                                Layout.fillWidth: true
                                onActivated: backend.setDeviceIndex(index)
                            }
                        }

                        RowLayout {
                            spacing: 8
                            Layout.fillWidth: true
                            Layout.preferredHeight: theme.controlHeight

                            Text {
                                text: backend.ocrFileName
                                color: backend.ocrFilePath.length > 0 ? theme.textPrimary : theme.textSecondary
                                font.pixelSize: 12
                                elide: Text.ElideMiddle
                                Layout.fillWidth: true
                                ToolTip.visible: fileHover.hovered && backend.ocrFilePath.length > 0
                                ToolTip.text: backend.ocrFilePath
                                HoverHandler { id: fileHover }
                            }

                            NeoButton {
                                text: "Sfoglia..."
                                enabled: !backend.busy
                                Layout.preferredWidth: 86
                                onClicked: backend.chooseOcrFile()
                            }
                        }
                    }

                    NeoCard {
                        title: "AZIONI"
                        Layout.fillWidth: true

                        GridLayout {
                            columns: 3
                            rowSpacing: 8
                            columnSpacing: 8
                            Layout.fillWidth: true

                            ActionUnit { label: "Avvia OCR"; shortcutText: "Ctrl+R"; primary: true; buttonEnabled: !backend.busy; Layout.fillWidth: true; onTriggered: backend.startOcr() }
                            ActionUnit { label: "Ferma"; shortcutText: "Ctrl+S"; danger: true; buttonEnabled: backend.ocrRunning; Layout.fillWidth: true; onTriggered: backend.stopOcr() }
                            ActionUnit { label: "Aggiorna"; shortcutText: "F5"; buttonEnabled: !backend.busy; Layout.fillWidth: true; onTriggered: backend.refreshDevices() }
                            ActionUnit { label: "Cancella"; shortcutText: "Ctrl+L"; buttonEnabled: !backend.busy; Layout.fillWidth: true; onTriggered: backend.clearOcr() }
                            ActionUnit { label: "Salva Testo"; shortcutText: "Ctrl+Shift+S"; buttonEnabled: !backend.busy && backend.ocrText.trim().length > 0; Layout.fillWidth: true; onTriggered: backend.saveOcr() }
                            Item { Layout.fillWidth: true; Layout.preferredHeight: theme.controlHeight }
                        }
                    }

                    OutputArea {
                        outputText: backend.ocrText
                        placeholderText: "Seleziona un'immagine o un PDF e clicca 'Avvia OCR'...\n\nSupporta PNG, JPG, BMP, TIFF, WEBP, PDF."
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 92
                    }

                    StatusBar {
                        statusText: backend.ocrStatusText
                        statusColor: backend.ocrStatusColor
                        progressText: backend.ocrPageProgress
                        Layout.fillWidth: true
                    }
                }
            }

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8

                    NeoCard {
                        title: "CONFIGURAZIONE BATCH"
                        Layout.fillWidth: true

                        Item {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 80

                            NeoInset { anchors.fill: parent; radius: theme.radiusMedium; surfaceColor: theme.inset }

                            Text {
                                anchors.centerIn: parent
                                text: backend.batchDropText
                                color: batchDrop.containsDrag ? theme.accent : theme.textSecondary
                                horizontalAlignment: Text.AlignHCenter
                                font.pixelSize: 12
                            }

                            DropArea {
                                id: batchDrop
                                anchors.fill: parent
                                enabled: !backend.busy
                                onDropped: function(drop) {
                                    backend.setBatchDroppedUrls(drop.urls)
                                    drop.acceptProposedAction()
                                }
                            }

                            TapHandler {
                                enabled: !backend.busy
                                onTapped: backend.chooseBatchFiles()
                            }
                        }
                    }

                    NeoCard {
                        title: "AZIONI"
                        Layout.fillWidth: true

                        GridLayout {
                            columns: 2
                            rowSpacing: 8
                            columnSpacing: 8
                            Layout.fillWidth: true

                            ActionUnit { label: "Avvia Batch"; shortcutText: "Ctrl+B"; primary: true; buttonEnabled: !backend.busy; Layout.fillWidth: true; onTriggered: backend.startBatch() }
                            ActionUnit { label: "Ferma"; shortcutText: "Ctrl+S"; danger: true; buttonEnabled: backend.batchRunning; Layout.fillWidth: true; onTriggered: backend.stopBatch() }
                            ActionUnit { label: "Cancella"; shortcutText: "Ctrl+L"; buttonEnabled: !backend.busy; Layout.fillWidth: true; onTriggered: backend.clearBatch() }
                            ActionUnit { label: "Salva Testo"; shortcutText: "Ctrl+Shift+S"; buttonEnabled: !backend.busy && backend.batchText.trim().length > 0; Layout.fillWidth: true; onTriggered: backend.saveBatch() }
                        }
                    }

                    OutputArea {
                        outputText: backend.batchText
                        placeholderText: "Trascina immagini o PDF qui sopra o clicca per sfogliare...\n\nIl testo estratto apparirà in quest'area."
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 92
                    }

                    StatusBar {
                        statusText: backend.batchStatusText
                        statusColor: backend.batchStatusColor
                        progressText: backend.batchProgressText
                        countText: backend.batchCountText
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }
}
