import QtQuick
import QtQuick.Controls.Basic as Basic

// .result-view / .log-view: inset, internally scrolling, selectable monospace text.
NeuSurface {
    id: root
    property string text: ""
    property int pixelSize: 13
    property real lineHeightFactor: 1.65
    property color textColor: Theme.textPrimary
    property alias flickable: flick
    radius: Theme.radiusMD
    shadow: Theme.insetSmall

    function scrollToEnd() {
        flick.contentY = Math.max(0, flick.contentHeight - flick.height)
    }

    Flickable {
        id: flick
        anchors.fill: parent
        anchors.rightMargin: 2
        clip: true
        contentWidth: width
        contentHeight: edit.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        Basic.ScrollBar.vertical: NeuScrollBar {}
        TextEdit {
            id: edit
            width: flick.width
            padding: 18
            // Qt's rich-text MinimumHeight lines add the extra leading below the
            // glyphs; CSS splits it. Shift up by the CSS half-leading delta.
            topPadding: 18 - Math.round((root.pixelSize * root.lineHeightFactor - root.pixelSize * 1.3) / 2)
            bottomPadding: 36 - topPadding
            readOnly: true
            selectByMouse: true
            selectByKeyboard: true
            activeFocusOnPress: true
            // Rich text only to reproduce the CSS line-height (TextEdit has no
            // lineHeight); the content is HTML-escaped plain text.
            textFormat: TextEdit.RichText
            wrapMode: TextEdit.Wrap
            text: "<div style=\"white-space:pre-wrap;line-height:" + (root.pixelSize * root.lineHeightFactor).toFixed(2) + "px\">"
                  + root.text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") + "</div>"
            color: root.textColor
            selectionColor: Theme.selection
            selectedTextColor: Theme.textPrimary
            font.family: Theme.monoFamily
            font.pixelSize: root.pixelSize
            Accessible.role: Accessible.StaticText
            Accessible.name: root.text
        }
    }
}
