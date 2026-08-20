import QtQuick

Rectangle {
    id: root
    Theme { id: theme }
    property color dotColor: theme.statusIdle
    width: 8
    height: 8
    radius: 4
    color: dotColor
}
