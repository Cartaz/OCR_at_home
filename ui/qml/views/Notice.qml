import QtQuick
import "../components"

// .notice: inset card with accent ring, title + message, optional details.
NeuSurface {
    id: root
    property bool detailsOpen: false
    radius: Theme.radiusMD
    shadow: Theme.noticeShadow
    implicitHeight: column.implicitHeight + 28
    Accessible.role: backend.noticeUrgent ? Accessible.AlertMessage : Accessible.StaticText
    Accessible.name: backend.noticeTitle + ". " + backend.noticeMessage

    // Like the web UI, an urgent notice takes keyboard focus (screen readers
    // announce it) and shows the focus outline until focus moves on.
    activeFocusOnTab: true
    Connections {
        target: backend
        function onNoticeChanged() {
            root.detailsOpen = false
            if (backend.noticeVisible && backend.noticeUrgent)
                root.forceActiveFocus()
        }
    }
    Rectangle {
        visible: root.activeFocus
        anchors.fill: parent
        anchors.margins: -4
        radius: root.radius + 4
        color: "transparent"
        border.width: 1
        border.color: Theme.accent
    }
    Keys.onEscapePressed: backend.dismissNotice()

    Column {
        id: column
        x: 16
        y: 14
        width: parent.width - 32 - close.width - 16
        spacing: 10
        Flow {
            width: parent.width
            spacing: 10
            CssText { text: backend.noticeTitle; color: Theme.accent; font.pixelSize: 14; font.bold: true }
            CssText { text: backend.noticeMessage; color: Theme.textSecondary; font.pixelSize: 14; wrapMode: Text.Wrap; width: Math.min(implicitWidth, parent.width) }
        }
        Column {
            visible: backend.noticeDetails.length > 0
            width: parent.width
            spacing: 6
            CssText {
                text: (root.detailsOpen ? "▼ " : "▶ ") + "Dettagli tecnici"
                color: Theme.textSecondary
                font.pixelSize: 14
                TapHandler { cursorShape: Qt.PointingHandCursor; onTapped: root.detailsOpen = !root.detailsOpen }
            }
            CssText {
                visible: root.detailsOpen
                width: parent.width
                text: backend.noticeDetails
                color: Theme.textSecondary
                font.family: Theme.monoFamily
                font.pixelSize: 12
                wrapMode: Text.WrapAnywhere
                cssLineHeight: 18
                maximumLineCount: 10
                elide: Text.ElideRight
            }
        }
    }
    NeuButton {
        id: close
        anchors.right: parent.right
        anchors.rightMargin: 16
        y: 14
        variant: "compact"
        iconName: "close"
        tooltip: "Chiudi messaggio"
        onClicked: backend.dismissNotice()
    }
}
