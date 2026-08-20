import QtQuick
import QtQuick.Controls

Button {
    id: root
    Theme { id: theme }
    property bool selected: false
    implicitWidth: 128
    implicitHeight: 38
    hoverEnabled: true
    contentItem: Text { text: root.text; color: root.selected ? theme.accent : theme.textSecondary; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 13; font.weight: root.selected ? Font.DemiBold : Font.Normal }
    background: Item {
        NeoRaised { anchors.fill: parent; visible: !root.selected && !root.down; radius: 8; surfaceColor: theme.surfaceRaised; shadowOffset: 1.8; shadowBlur: 0.22; blurMax: 10; shadowPadding: 7; lightOpacity: 0.14; darkOpacity: 0.46 }
        NeoInset { anchors.fill: parent; visible: root.selected || root.down; radius: 8; surfaceColor: theme.inset }
        Rectangle { visible: root.selected; height: 2; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; color: theme.accent }
    }
}
