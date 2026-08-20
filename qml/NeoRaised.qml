import QtQuick
import QtQuick.Effects

Item {
    id: root
    Theme { id: theme }
    property color surfaceColor: theme.surfaceRaised
    property real radius: theme.radiusMedium
    property real shadowOffset: theme.buttonShadowOffset
    property real shadowBlur: theme.buttonShadowBlur
    property int blurMax: theme.buttonShadowBlurMax
    property real lightOpacity: theme.buttonLightOpacity
    property real darkOpacity: theme.buttonDarkOpacity
    property real shadowPadding: theme.buttonShadowPadding
    property color lightShadowColor: theme.shadowLight
    property color darkShadowColor: theme.shadowDark
    property bool hovered: false
    clip: false

    Rectangle { id: shadowShape; anchors.fill: parent; radius: root.radius; color: root.surfaceColor; visible: false }

    MultiEffect {
        anchors.fill: shadowShape
        source: shadowShape
        autoPaddingEnabled: false
        paddingRect: Qt.rect(-root.shadowPadding, -root.shadowPadding, root.shadowPadding * 2, root.shadowPadding * 2)
        blurMax: root.blurMax
        shadowEnabled: true
        shadowBlur: root.shadowBlur
        shadowScale: 1.0
        shadowHorizontalOffset: -root.shadowOffset
        shadowVerticalOffset: -root.shadowOffset
        shadowColor: root.lightShadowColor
        shadowOpacity: root.lightOpacity
        z: -2
    }

    MultiEffect {
        anchors.fill: shadowShape
        source: shadowShape
        autoPaddingEnabled: false
        paddingRect: Qt.rect(-root.shadowPadding, -root.shadowPadding, root.shadowPadding * 2, root.shadowPadding * 2)
        blurMax: root.blurMax
        shadowEnabled: true
        shadowBlur: root.shadowBlur
        shadowScale: 1.0
        shadowHorizontalOffset: root.shadowOffset
        shadowVerticalOffset: root.shadowOffset
        shadowColor: root.darkShadowColor
        shadowOpacity: root.darkOpacity
        z: -1
    }

    Rectangle {
        anchors.fill: parent
        radius: root.radius
        gradient: Gradient {
            GradientStop { position: 0.0; color: root.hovered ? Qt.lighter(root.surfaceColor, 1.040) : Qt.lighter(root.surfaceColor, 1.018) }
            GradientStop { position: 1.0; color: root.hovered ? Qt.lighter(root.surfaceColor, 1.014) : root.surfaceColor }
        }
    }

    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.leftMargin: root.radius * 0.55; anchors.rightMargin: root.radius * 0.55; height: 1; color: "#222222"; opacity: 0.34 }
    Rectangle { anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.topMargin: root.radius * 0.55; anchors.bottomMargin: root.radius * 0.55; width: 1; color: "#222222"; opacity: 0.30 }
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.leftMargin: root.radius * 0.55; anchors.rightMargin: root.radius * 0.55; height: 1; color: "#0B0B0B"; opacity: 0.56 }
    Rectangle { anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right; anchors.topMargin: root.radius * 0.55; anchors.bottomMargin: root.radius * 0.55; width: 1; color: "#0B0B0B"; opacity: 0.48 }
}
