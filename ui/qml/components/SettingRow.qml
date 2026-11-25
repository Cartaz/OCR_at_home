import QtQuick

// .setting-row: label + help on the left, toggle on the right, hairline below.
Item {
    id: root
    property string label: ""
    property string help: ""
    property alias checked: toggle.checked
    property alias toggleEnabled: toggle.enabled
    signal toggled()
    implicitHeight: Math.max(copy.implicitHeight, toggle.height) + 18 + 1

    Column {
        id: copy
        width: parent.width - toggle.width - 20
        anchors.verticalCenter: toggle.verticalCenter
        FieldLabel { text: root.label; width: parent.width; wrapMode: Text.Wrap; marginBottom: 4 }
        CssText {
            width: parent.width
            text: root.help
            color: Theme.textSecondary
            font.pixelSize: 14
            wrapMode: Text.Wrap
            cssLineHeight: 21.7
        }
    }
    Toggle {
        id: toggle
        anchors.right: parent.right
        y: Math.max(0, (Math.max(copy.implicitHeight, height) - height) / 2)
        Accessible.name: root.label
        onToggled: root.toggled()
    }
    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.hairline
    }
}
