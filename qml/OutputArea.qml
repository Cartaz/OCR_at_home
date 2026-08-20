import QtQuick
import QtQuick.Controls

Item {
    id: root
    Theme { id: theme }
    property string outputText: ""
    property string placeholderText: ""
    ScrollView {
        anchors.fill: parent
        clip: true
        background: NeoInset { radius: theme.radiusMedium; surfaceColor: theme.inset }
        TextArea {
            text: root.outputText
            placeholderText: root.placeholderText
            placeholderTextColor: "#747A80"
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.Wrap
            color: theme.textPrimary
            font.pixelSize: 14
            padding: 14
            background: null
            onTextChanged: cursorPosition = length
        }
    }
}
