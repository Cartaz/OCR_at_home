import QtQuick
import "../components"

// Log view (#view-logs): polled while visible, optional auto-scroll.
Column {
    id: root
    property bool narrow: false
    property real viewportHeight: 800
    property bool active: false
    property string logText: "Log non ancora caricato."

    function refresh() {
        logText = backend.readLogs(600)
        if (autoScroll.checked)
            Qt.callLater(logView.scrollToEnd)
    }
    onActiveChanged: if (active) refresh()

    Timer { interval: 1800; repeat: true; running: root.active; onTriggered: root.refresh() }

    SectionHeading {
        x: 4
        width: root.width - 8
        narrow: root.narrow
        title: "Log"
        description: "Ultime righe del log applicativo, senza alterare il livello di logging."
    }
    Item { width: 1; height: 22 }

    Panel {
        width: root.width
        padding: root.narrow ? 17 : 22
        implicitHeight: Math.max(Math.min(root.viewportHeight * 0.68, 700), bodyHeight + 2 * padding)
        Item {
            width: parent.width
            height: 44
            Row {
                spacing: 14
                anchors.verticalCenter: parent.verticalCenter
                NeuButton { text: "Aggiorna"; iconName: "refresh"; onClicked: root.refresh() }
                NeuCheckBox { id: autoScroll; text: "Auto-scroll"; checked: true; anchors.verticalCenter: parent.verticalCenter }
            }
            NeuButton {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                variant: "icon"
                iconName: "copy"
                tooltip: "Copia log"
                onClicked: backend.copyText(root.logText)
            }
        }
        Item { width: 1; height: 14 }
        InsetTextView {
            id: logView
            width: parent.width
            height: Math.min(root.viewportHeight * 0.62, 620)
            text: root.logText
            pixelSize: 12
            textColor: Theme.textSecondary
            lineHeightFactor: 1.55
        }
    }
}
