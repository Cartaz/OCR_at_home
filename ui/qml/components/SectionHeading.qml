import QtQuick

// .section-heading: h2 + description, optional operation chip on the right.
Item {
    id: root
    property string title: ""
    property string description: ""
    property string chipText: ""
    property bool chipActive: false
    property bool narrow: false

    implicitHeight: narrow ? textColumn.implicitHeight + (chip.visible ? chip.height + 10 : 0)
                           : Math.max(textColumn.implicitHeight, chip.visible ? chip.height : 0)

    Column {
        id: textColumn
        width: root.narrow || !chip.visible ? parent.width : parent.width - chip.width - 20
        CssText {
            objectName: "sectionTitle"
            width: parent.width
            text: root.title
            color: Theme.textPrimary
            font.pixelSize: 18
            font.weight: Font.Bold
            marginBottom: 7
            wrapMode: Text.Wrap
        }
        CssText {
            width: parent.width
            text: root.description
            color: Theme.textSecondary
            font.pixelSize: 14
            wrapMode: Text.Wrap
            cssLineHeight: 21.7
        }
    }
    Chip {
        id: chip
        objectName: "operationLabel"
        visible: root.chipText.length > 0
        text: root.chipText
        active: root.chipActive
        x: root.narrow ? 0 : parent.width - width
        y: root.narrow ? textColumn.implicitHeight + 10 : 0
    }
}
