import QtQuick
import QtQuick.Layouts

Item {
    id: root
    Theme { id: theme }
    property string title: ""
    default property alias contentData: contentColumn.data
    implicitHeight: contentColumn.implicitHeight + 48

    NeoRaised {
        anchors.fill: parent
        radius: theme.radiusLarge
        surfaceColor: theme.surfaceRaised
        shadowOffset: theme.cardShadowOffset
        shadowBlur: theme.cardShadowBlur
        blurMax: theme.cardShadowBlurMax
        lightOpacity: theme.cardLightOpacity
        darkOpacity: theme.cardDarkOpacity
        shadowPadding: theme.cardShadowPadding
    }

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: 24
        spacing: 8
        Text {
            text: root.title
            color: theme.textSecondary
            font.pixelSize: 13
            font.weight: Font.Medium
            font.capitalization: Font.AllUppercase
            Layout.fillWidth: true
        }
    }
}
