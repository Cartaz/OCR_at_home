import QtQuick

// .top-status: inset capsule with status dot and text.
NeuSurface {
    id: root
    property string text: ""
    property bool active: false
    implicitWidth: row.implicitWidth + 28
    implicitHeight: 38
    width: implicitWidth
    height: implicitHeight
    radius: height / 2
    shadow: Theme.insetSmall
    Row {
        id: row
        anchors.centerIn: parent
        spacing: 8
        StatusDot { active: root.active; anchors.verticalCenter: parent.verticalCenter }
        CssText {
            text: root.text
            color: Theme.textSecondary
            font.pixelSize: 12
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
