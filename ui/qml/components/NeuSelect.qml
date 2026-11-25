pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic

// .inset-field.language-select-field: inset 46px select with an accent chevron.
Basic.ComboBox {
    id: root
    property string accessibleName: ""
    textRole: "text"
    valueRole: "value"
    implicitHeight: 46
    hoverEnabled: true
    leftPadding: 13
    rightPadding: 38
    font.pixelSize: 14
    opacity: enabled ? 1 : Theme.disabledOpacity
    Accessible.name: accessibleName

    // A stored value missing from the options is added rather than silently
    // replaced by the first option (it would be saved back on "Salva").
    function selectValue(value, label) {
        let index = indexOfValue(value)
        if (index < 0) {
            model = model.concat([{ text: label !== undefined ? label : String(value), value: value }])
            index = indexOfValue(value)
        }
        currentIndex = index
    }

    background: Item {
        Rectangle {
            visible: root.visualFocus
            anchors.fill: parent
            anchors.margins: -4
            radius: Theme.radiusMD + 4
            color: "transparent"
            border.width: 1
            border.color: Theme.accent
        }
        NeuSurface { anchors.fill: parent; radius: Theme.radiusMD; shadow: Theme.insetSmall }
    }
    contentItem: Text {
        text: root.displayText
        color: Theme.selectText
        font: root.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Text {
        x: root.width - 12 - width
        y: (root.height - height) / 2 - 1
        text: "⌄"
        color: Theme.accent
        font.pixelSize: 18
    }
    delegate: Basic.ItemDelegate {
        id: option
        required property var model
        required property int index
        width: root.popup.width - 12
        height: 34
        highlighted: root.highlightedIndex === index
        contentItem: Text {
            text: option.model[root.textRole]
            color: option.highlighted ? Theme.accent : Theme.selectText
            font: root.font
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: Theme.radiusSM - 2
            color: option.highlighted ? Qt.rgba(1, 1, 1, 0.04) : "transparent"
        }
    }
    popup: Basic.Popup {
        y: root.height + 6
        width: root.width
        padding: 6
        implicitHeight: Math.min(listView.contentHeight + 12, 320)
        background: NeuSurface { radius: Theme.radiusSM; shadow: Theme.raisedSoft }
        contentItem: ListView {
            id: listView
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
        }
    }
}
