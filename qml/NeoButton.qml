import QtQuick
import QtQuick.Controls

Button {
    id: root
    Theme { id: theme }

    property bool primary: false
    property bool danger: false
    property color neutralSurface: theme.surfaceRaised

    implicitHeight: theme.controlHeight
    hoverEnabled: true

    contentItem: Text {
        text: root.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: !root.enabled ? theme.textDisabled : root.primary ? theme.textOnAccent : theme.textPrimary
        font.pixelSize: 13
        font.weight: Font.DemiBold
        elide: Text.ElideRight
    }

    background: Item {
        NeoRaised {
            anchors.fill: parent
            visible: !root.down
            radius: theme.radiusMedium
            surfaceColor: !root.enabled ? "#161616" : root.primary ? (root.hovered ? theme.accentHover : theme.accent) : root.danger ? (root.hovered ? theme.danger : theme.dangerDark) : root.neutralSurface
            hovered: root.hovered && root.enabled
            lightShadowColor: root.primary ? "#261C17" : theme.shadowLight
            darkShadowColor: root.primary ? "#080808" : theme.shadowDark
            lightOpacity: root.primary ? 0.10 : theme.buttonLightOpacity
            darkOpacity: root.primary ? 0.46 : (root.enabled ? theme.buttonDarkOpacity : 0.28)
        }

        NeoInset {
            anchors.fill: parent
            visible: root.down
            radius: theme.radiusMedium
            surfaceColor: root.primary ? theme.accentDark : root.danger ? theme.dangerDark : theme.inset
            focused: false
        }
    }
}
