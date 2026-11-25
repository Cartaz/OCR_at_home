import QtQuick

// .panel.raised with the standard 22px padding.
NeuSurface {
    id: root
    property real padding: 22
    default property alias body: column.data
    property alias spacing: column.spacing
    readonly property real bodyHeight: column.implicitHeight
    radius: Theme.radiusLG
    shadow: Theme.raised
    implicitHeight: column.implicitHeight + 2 * padding
    Column {
        id: column
        x: root.padding
        y: root.padding
        width: root.width - 2 * root.padding
    }
}
