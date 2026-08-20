import QtQuick
import QtQuick.Layouts

Item {
    id: root
    Theme { id: theme }

    property string label: ""
    property string shortcutText: ""
    property bool primary: false
    property bool danger: false
    property bool buttonEnabled: true

    signal triggered()

    implicitHeight: theme.controlHeight
    implicitWidth: row.implicitWidth

    RowLayout {
        id: row
        anchors.fill: parent
        spacing: 5

        StatusDot { Layout.preferredWidth: 8; Layout.preferredHeight: 8; dotColor: theme.statusIdle }

        NeoButton {
            text: root.label
            primary: root.primary
            danger: root.danger
            enabled: root.buttonEnabled
            Layout.fillWidth: true
            Layout.minimumWidth: 106
            onClicked: root.triggered()
        }

        NeoKey {
            text: root.shortcutText
            Layout.preferredWidth: Math.max(56, implicitWidth)
            Layout.preferredHeight: theme.controlHeight
        }
    }
}
