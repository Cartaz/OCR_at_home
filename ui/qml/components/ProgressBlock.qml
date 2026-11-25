import QtQuick

// .progress-block: label/value row and an inset 12px track with glowing fill.
Column {
    id: root
    property string label: ""
    property string valueText: ""
    property real value: 0
    spacing: 9
    Item {
        width: parent.width
        height: Math.max(labelText.implicitHeight, valueLabel.implicitHeight)
        CssText { id: labelText; text: root.label; color: Theme.textSecondary; font.pixelSize: 12 }
        CssText { id: valueLabel; anchors.right: parent.right; text: root.valueText; color: Theme.textSecondary; font.pixelSize: 12 }
    }
    NeuSurface {
        width: parent.width
        height: 12
        radius: 6
        shadow: Theme.insetSmall
        Accessible.role: Accessible.ProgressBar
        Accessible.name: root.label
        NeuSurface {
            width: parent.width * Math.max(0, Math.min(1, root.value))
            height: parent.height
            radius: 6
            visible: width > 0.5
            color: Theme.accent
            shadow: Theme.progressGlow
            Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.InOutQuad } }
        }
    }
}
