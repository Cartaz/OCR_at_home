import QtQuick

// .operation-label / .status-chip: inset pill, accent glow when active.
NeuSurface {
    id: root
    property string text: ""
    property bool active: false
    implicitWidth: label.implicitWidth + 22
    implicitHeight: 30
    width: implicitWidth
    height: implicitHeight
    radius: height / 2
    shadow: active ? Theme.activeInsetGlow : Theme.insetSmall
    CssText {
        id: label
        anchors.centerIn: parent
        text: root.text
        color: root.active ? Theme.accent : Theme.textSecondary
        font.pixelSize: 11
        font.weight: Theme.semiBold
    }
}
