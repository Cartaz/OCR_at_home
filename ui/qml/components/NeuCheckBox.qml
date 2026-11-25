import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Shapes

// .check-control: native 16px checkbox with accent-color, label on the right.
Basic.CheckBox {
    id: root
    spacing: 9
    padding: 0
    hoverEnabled: true
    font.pixelSize: 14
    indicator: Rectangle {
        // Chromium's checkbox margin: 3px 3px 3px 4px.
        x: 4
        y: (root.height - height) / 2
        width: 16
        height: 16
        radius: 3
        color: root.checked ? Theme.accent : "#f2f2f2"
        border.width: root.checked ? 0 : 1
        border.color: "#767676"
        Shape {
            anchors.fill: parent
            visible: root.checked
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: "#141414"
                strokeWidth: 2
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                PathSvg { path: "M3.5 8.2l3 3 6-6.4" }
            }
        }
        Rectangle {
            visible: root.visualFocus
            anchors.fill: parent
            anchors.margins: -4
            radius: 6
            color: "transparent"
            border.width: 1
            border.color: Theme.accent
        }
    }
    contentItem: Text {
        leftPadding: 4 + root.indicator.width + 3 + root.spacing
        text: root.text
        color: Theme.textSecondary
        font: root.font
        verticalAlignment: Text.AlignVCenter
    }
}
