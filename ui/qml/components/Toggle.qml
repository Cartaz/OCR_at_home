import QtQuick
import QtQuick.Controls.Basic as Basic

// .toggle: 54x30 inset track, 20px raised knob that slides 24px when checked.
Basic.AbstractButton {
    id: root
    checkable: true
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    implicitWidth: 54
    implicitHeight: 30
    padding: 0
    opacity: enabled ? 1 : Theme.disabledOpacity
    Accessible.role: Accessible.CheckBox
    Accessible.checked: checked

    background: Item {
        Rectangle {
            visible: root.visualFocus
            anchors.fill: parent
            anchors.margins: -4
            radius: height / 2
            color: "transparent"
            border.width: 1
            border.color: Theme.accent
        }
        NeuSurface {
            anchors.fill: parent
            radius: height / 2
            shadow: root.checked ? Theme.activeInsetGlow : Theme.insetSmall
        }
    }
    contentItem: Item {
        NeuSurface {
            width: 20
            height: 20
            radius: 10
            x: root.checked ? 29 : 5
            y: 5
            color: root.checked ? Theme.accent : Theme.textSecondary
            shadow: root.checked ? Theme.knobChecked : Theme.raisedSoft
            Behavior on x { NumberAnimation { duration: Theme.fastMs; easing.type: Easing.InOutQuad } }
            Behavior on color { ColorAnimation { duration: Theme.fastMs } }
        }
    }
}
