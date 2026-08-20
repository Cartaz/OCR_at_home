import QtQuick
import QtQuick.Layouts

Item {
    id: root
    Theme { id: theme }
    property string statusText: ""
    property color statusColor: theme.statusIdle
    property string progressText: ""
    property string countText: ""
    implicitHeight: 34
    NeoInset { anchors.fill: parent; radius: theme.radiusSmall; surfaceColor: "#111111"; depth: 6 }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 9
        anchors.rightMargin: 9
        spacing: 12
        StatusDot { dotColor: root.statusColor; Layout.preferredWidth: 8; Layout.preferredHeight: 8 }
        Text { text: root.statusText; color: theme.textSecondary; font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true }
        Text { text: root.progressText; color: theme.textSecondary; font.pixelSize: 12; horizontalAlignment: Text.AlignRight; Layout.minimumWidth: root.progressText.length > 0 ? 82 : 0 }
        Text { visible: root.countText.length > 0; text: root.countText; color: theme.textSecondary; font.pixelSize: 12 }
    }
}
