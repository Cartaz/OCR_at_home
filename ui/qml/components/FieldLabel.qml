import QtQuick

// .field-label: an inline-block label inside a 14px line box. The line box
// is max(strut, label) above and below the baseline, which is why the label
// sits 2px below the top and the block is taller than label + margin.
Item {
    id: root
    property alias text: label.text
    property real marginBottom: 9
    property alias wrapMode: label.wrapMode
    readonly property real _strutAscent: 15
    readonly property real _strutDescent: 4
    implicitWidth: label.implicitWidth
    implicitHeight: _strutAscent + Math.max(_strutDescent, 4 + marginBottom)
                    + Math.max(0, label.lineCount - 1) * 17
    CssText {
        id: label
        y: root._strutAscent - 13
        width: root.width > 0 ? root.width : implicitWidth
        color: Theme.textSecondary
        font.pixelSize: 12
        font.weight: Font.Bold
        font.letterSpacing: 0.3
    }
}
