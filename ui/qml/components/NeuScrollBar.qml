import QtQuick
import QtQuick.Controls.Basic as Basic

// Thin 9px scrollbar: rgba(135,135,135,0.28) thumb inset by 2px.
Basic.ScrollBar {
    id: root
    implicitWidth: 9
    implicitHeight: 9
    padding: 2
    minimumSize: 0.08
    policy: Basic.ScrollBar.AsNeeded
    visible: size < 1.0
    contentItem: Rectangle {
        implicitWidth: 5
        implicitHeight: 5
        radius: 3
        color: root.hovered || root.pressed ? Theme.scrollThumbHover : Theme.scrollThumb
    }
    background: Rectangle { color: Theme.surface }
}
