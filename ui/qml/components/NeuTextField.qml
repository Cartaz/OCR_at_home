import QtQuick
import QtQuick.Controls.Basic as Basic

// .inset-field.text-field with a borderless 44px input.
NeuSurface {
    id: root
    property alias text: input.text
    property alias input: input
    property string accessibleName: ""
    implicitHeight: 46
    radius: Theme.radiusMD
    shadow: Theme.insetSmall
    Basic.TextField {
        id: input
        anchors.fill: parent
        anchors.leftMargin: 13
        anchors.rightMargin: 13
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.textPrimary
        selectionColor: Theme.selection
        selectedTextColor: Theme.textPrimary
        placeholderTextColor: Theme.textMuted
        font.pixelSize: 14
        padding: 0
        leftPadding: 0
        rightPadding: 0
        background: null
        Accessible.name: root.accessibleName
    }
    Rectangle {
        visible: input.activeFocus
        anchors.fill: parent
        anchors.margins: -4
        radius: root.radius + 4
        color: "transparent"
        border.width: 1
        border.color: Theme.accent
    }
}
