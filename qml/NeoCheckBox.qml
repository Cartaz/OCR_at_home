import QtQuick
import QtQuick.Controls

CheckBox {
    id: root
    Theme { id: theme }
    spacing: 8
    implicitHeight: theme.controlHeight
    hoverEnabled: true

    indicator: Item {
        implicitWidth: 18
        implicitHeight: 18
        x: 0
        y: (root.height - height) / 2
        NeoInset { anchors.fill: parent; visible: !root.checked; radius: 5; surfaceColor: theme.inset }
        NeoRaised {
            anchors.fill: parent
            visible: root.checked
            radius: 5
            surfaceColor: root.hovered ? theme.accentHover : theme.accent
            shadowOffset: 2
            shadowBlur: 0.26
            blurMax: 12
            lightOpacity: 0.18
            darkOpacity: 0.54
        }
    }

    contentItem: Text {
        text: root.text
        color: root.enabled ? theme.textPrimary : theme.textDisabled
        verticalAlignment: Text.AlignVCenter
        leftPadding: root.indicator.width + root.spacing
        font.pixelSize: 13
    }
}
