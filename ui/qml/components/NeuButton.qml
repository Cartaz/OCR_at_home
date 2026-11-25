import QtQuick
import QtQuick.Controls.Basic as Basic

// .button / .icon-button / .icon-button.compact / .nav-item from the web UI.
Basic.AbstractButton {
    id: root
    property string iconName: ""
    property bool primary: false
    // "button" | "icon" | "compact" | "nav"
    property string variant: "button"
    property bool current: false
    property string tooltip: ""

    readonly property bool _icon: variant === "icon" || variant === "compact"
    readonly property bool _hover: hovered && enabled
    readonly property bool _down: pressed && enabled
    readonly property real _radius: variant === "icon" ? 14 : variant === "compact" ? 11 : Theme.radiusMD

    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    padding: 0
    leftPadding: _icon ? 0 : variant === "nav" ? 14 : 16
    rightPadding: leftPadding
    implicitWidth: variant === "icon" ? 42 : variant === "compact" ? 34
        : Math.max(44, leftPadding + rightPadding + contentRow.implicitWidth)
    implicitHeight: variant === "icon" ? 42 : variant === "compact" ? 34 : variant === "nav" ? 48 : 44
    opacity: enabled ? 1 : Theme.disabledOpacity
    scale: _down ? 0.98 : 1
    Behavior on scale { NumberAnimation { duration: Theme.fastMs; easing.type: Easing.InOutQuad } }
    Behavior on opacity { NumberAnimation { duration: Theme.fastMs } }

    Accessible.name: text.length ? text : tooltip
    Accessible.description: tooltip

    readonly property color _textColor: {
        if (!enabled) return Theme.textSecondary
        if (variant === "button" && primary) return Theme.accent
        if (_down) return Theme.textPrimary
        if (_hover) return Theme.textPrimary
        if (variant === "nav" && current) return Theme.accent
        return Theme.textSecondary
    }

    background: Item {
        // CSS :focus-visible outline: 1px accent, 3px outside the box.
        Rectangle {
            visible: root.visualFocus
            anchors.fill: parent
            anchors.margins: -4
            radius: root._radius + 4
            color: "transparent"
            border.width: 1
            border.color: Theme.accent
        }
        NeuSurface {
            anchors.fill: parent
            radius: root._radius
            shadow: {
                if (root._down) return Theme.insetSmall
                if (root._hover) return Theme.raisedHover
                if (root.visualFocus) return root.primary ? Theme.primaryFocus : Theme.focusRing
                if (root.variant === "nav" && root.current) return Theme.activeInsetGlow
                return Theme.raisedSoft
            }
        }
    }

    contentItem: Item {
        implicitWidth: contentRow.implicitWidth
        implicitHeight: contentRow.implicitHeight
        Row {
            id: contentRow
            spacing: root.variant === "nav" ? 12 : 9
            anchors.verticalCenter: parent.verticalCenter
            x: root.variant === "nav" ? 0 : (parent.width - width) / 2
            Icon {
                visible: root.iconName.length > 0
                name: root.iconName
                size: root.variant === "compact" ? 17 : 20
                color: root._textColor
                anchors.verticalCenter: parent.verticalCenter
            }
            CssText {
                visible: root.text.length > 0
                text: root.text
                color: root._textColor
                font.pixelSize: root.variant === "compact" ? 14 : 14
                font.weight: root.variant === "button" ? Theme.semiBold : Font.Normal
                anchors.verticalCenter: parent.verticalCenter
                Behavior on color { ColorAnimation { duration: Theme.fastMs } }
            }
        }
    }

    Basic.ToolTip.visible: tooltip.length > 0 && hovered
    Basic.ToolTip.text: tooltip
    Basic.ToolTip.delay: 600
}
