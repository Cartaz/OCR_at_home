import QtQuick
import "../components"

// Wide (>900px) vertical sidebar and compact (<=900px) sticky top bar.
Item {
    id: root
    property bool compact: false
    property bool narrow: false
    readonly property var navItems: [
        { view: "ocr", label: "OCR", icon: "ocr", tip: "OCR singolo" },
        { view: "batch", label: "Batch", icon: "batch", tip: "Elaborazione batch" },
        { view: "logs", label: "Log", icon: "logs", tip: "Log applicazione" },
        { view: "settings", label: "Impostazioni", icon: "settings", tip: "Impostazioni" }
    ]

    // ---- wide layout -------------------------------------------------------
    Item {
        visible: !root.compact
        anchors.fill: parent
        Column {
            x: 18
            y: 24
            width: parent.width - 36
            spacing: 28
            Item {
                objectName: "brand"
                width: parent.width
                height: 50
                NeuSurface {
                    objectName: "brandMark"
                    x: 8; y: 4
                    width: 42; height: 42; radius: 14
                    shadow: Theme.raisedSoft
                    Icon { name: "brand"; size: 22; color: Theme.accent; anchors.centerIn: parent }
                }
                Column {
                    x: 64
                    y: 4 + (42 - height) / 2
                    spacing: 2
                    CssText { objectName: "brandTitle"; text: "GLM OCR"; color: Theme.textPrimary; font.pixelSize: 15; font.bold: true; font.letterSpacing: 0.3 }
                    CssText { text: "LOCAL · SYCL"; color: Theme.textMuted; font.pixelSize: 11; font.letterSpacing: 0.88 }
                }
            }
            Column {
                width: parent.width
                spacing: 10
                Repeater {
                    model: root.navItems
                    NeuButton {
                        required property var modelData
                        objectName: "nav_" + modelData.view
                        width: parent.width
                        variant: "nav"
                        text: modelData.label
                        iconName: modelData.icon
                        tooltip: modelData.tip
                        current: backend.view === modelData.view
                        onClicked: backend.setView(modelData.view)
                    }
                }
            }
        }
        Item {
            x: 26
            width: parent.width - 52
            height: 42
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 32
            Row {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                width: parent.width - quit.width - 10
                StatusDot { active: backend.sidebarStatusActive; anchors.verticalCenter: parent.verticalCenter }
                CssText {
                    width: parent.width - 16
                    text: backend.sidebarStatusText
                    color: Theme.textSecondary
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            NeuButton {
                id: quit
                objectName: "quitButton"
                anchors.right: parent.right
                variant: "icon"
                iconName: "quit"
                tooltip: "Esci da GLM OCR"
                onClicked: backend.quit()
            }
        }
    }

    // ---- compact top bar ---------------------------------------------------
    NeuSurface {
        visible: root.compact
        anchors.fill: parent
        radius: 0
        shadow: Theme.topBarShadow
        animated: false
        NeuSurface {
            id: compactBrand
            x: root.narrow ? 10 : 14
            anchors.verticalCenter: parent.verticalCenter
            width: 38; height: 38; radius: 12
            shadow: Theme.raisedSoft
            Icon { name: "brand"; size: 22; color: Theme.accent; anchors.centerIn: parent }
        }
        Row {
            anchors.centerIn: parent
            spacing: 8
            Repeater {
                model: root.navItems
                NeuButton {
                    required property var modelData
                    variant: "nav"
                    height: 40
                    leftPadding: root.narrow ? 0 : 11
                    rightPadding: leftPadding
                    width: root.narrow ? 40 : implicitWidth
                    text: root.narrow ? "" : modelData.label
                    iconName: modelData.icon
                    tooltip: modelData.tip
                    current: backend.view === modelData.view
                    onClicked: backend.setView(modelData.view)
                }
            }
        }
        NeuButton {
            anchors.right: parent.right
            anchors.rightMargin: root.narrow ? 10 : 14
            anchors.verticalCenter: parent.verticalCenter
            variant: "icon"
            iconName: "quit"
            tooltip: "Esci da GLM OCR"
            onClicked: backend.quit()
        }
    }
}
