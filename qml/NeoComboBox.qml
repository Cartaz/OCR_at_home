import QtQuick
import QtQuick.Controls

ComboBox {
    id: root
    Theme { id: theme }
    implicitHeight: theme.controlHeight
    hoverEnabled: true
    leftPadding: 12
    rightPadding: 32

    contentItem: Text {
        text: root.displayText
        color: root.enabled ? theme.textPrimary : theme.textDisabled
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        font.pixelSize: 13
    }

    indicator: Text {
        x: root.width - width - 12
        y: (root.height - height) / 2 - 1
        text: "⌄"
        color: theme.textSecondary
        font.pixelSize: 16
    }

    background: NeoInset { radius: theme.radiusMedium; surfaceColor: theme.inset; focused: root.activeFocus }

    delegate: ItemDelegate {
        width: root.width
        height: 32
        text: root.textAt(index)
        highlighted: root.highlightedIndex === index
        contentItem: Text {
            text: parent.text
            color: parent.highlighted ? theme.textOnAccent : theme.textPrimary
            verticalAlignment: Text.AlignVCenter
            leftPadding: 8
            elide: Text.ElideRight
            font.pixelSize: 13
        }
        background: Rectangle { radius: 5; color: parent.highlighted ? theme.accent : "transparent" }
    }

    popup: Popup {
        y: root.height + 6
        width: root.width
        padding: 6
        contentItem: ListView {
            clip: true
            implicitHeight: Math.min(contentHeight, 220)
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }
        background: NeoRaised {
            radius: theme.radiusMedium
            surfaceColor: "#1B1B1B"
            shadowOffset: 2.0
            shadowBlur: 0.24
            blurMax: 10
            shadowPadding: 7
            lightOpacity: 0.14
            darkOpacity: 0.46
        }
    }
}
