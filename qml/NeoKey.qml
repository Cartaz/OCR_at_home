import QtQuick

Item {
    id: root
    Theme { id: theme }
    property string text: ""
    implicitWidth: Math.max(56, label.implicitWidth + 20)
    implicitHeight: theme.controlHeight
    NeoInset { anchors.fill: parent; radius: theme.radiusSmall; surfaceColor: "#111111" }
    Text { id: label; anchors.centerIn: parent; text: root.text; color: theme.textSecondary; font.pixelSize: 11 }
}
