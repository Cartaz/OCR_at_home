pragma Singleton
import QtQuick

// Design tokens mirrored 1:1 from the former ui/web/styles.css custom properties.
QtObject {
    readonly property color surface: Qt.rgba(20 / 255, 20 / 255, 20 / 255, 1)
    readonly property color accent: Qt.rgba(1, 102 / 255, 0, 1)
    readonly property color textPrimary: Qt.rgba(225 / 255, 225 / 255, 225 / 255, 1)
    readonly property color textSecondary: Qt.rgba(135 / 255, 135 / 255, 135 / 255, 1)
    readonly property color textMuted: Qt.rgba(90 / 255, 90 / 255, 90 / 255, 1)
    readonly property color accentBorder: Qt.rgba(1, 102 / 255, 0, 0.88)
    readonly property color accentGlow: Qt.rgba(1, 102 / 255, 0, 0.36)
    readonly property color accentGlowSoft: Qt.rgba(1, 102 / 255, 0, 0.16)
    readonly property color hairline: Qt.rgba(1, 1, 1, 0.04)
    readonly property color selection: Qt.rgba(1, 102 / 255, 0, 0.28)
    readonly property color selectText: Qt.rgba(218 / 255, 218 / 255, 218 / 255, 1)
    readonly property color scrollThumb: Qt.rgba(135 / 255, 135 / 255, 135 / 255, 0.28)
    readonly property color scrollThumbHover: Qt.rgba(135 / 255, 135 / 255, 135 / 255, 0.42)

    readonly property int radiusXL: 28
    readonly property int radiusLG: 22
    readonly property int radiusMD: 16
    readonly property int radiusSM: 12

    readonly property int fastMs: 180
    readonly property int shadowMs: 220
    readonly property real disabledOpacity: 0.34

    // Proportional text uses the application font (Inter, else system sans).
    readonly property string monoFamily: "monospace"
    // CSS font-weight 600 resolves to the heavier face when the family has no
    // SemiBold (Chromium rule); Main.qml sets this from backend.semiBoldWeight.
    property int semiBold: 600

    // --- box-shadow presets: [offsetX, offsetY, blur, spread, color] -----------
    readonly property color _dark78: Qt.rgba(0, 0, 0, 0.78)
    readonly property color _dark72: Qt.rgba(0, 0, 0, 0.72)
    readonly property color _dark70: Qt.rgba(0, 0, 0, 0.70)
    readonly property color _dark65: Qt.rgba(0, 0, 0, 0.65)
    readonly property color _light16: Qt.rgba(75 / 255, 75 / 255, 75 / 255, 0.16)
    readonly property color _light15: Qt.rgba(75 / 255, 75 / 255, 75 / 255, 0.15)
    readonly property color _light13: Qt.rgba(75 / 255, 75 / 255, 75 / 255, 0.13)
    readonly property color _light12: Qt.rgba(75 / 255, 75 / 255, 75 / 255, 0.12)
    readonly property color _light11: Qt.rgba(75 / 255, 75 / 255, 75 / 255, 0.11)

    readonly property var raised: ({
        outer: [[10, 10, 24, 0, _dark78], [-8, -8, 20, 0, _light16]], inset: [] })
    readonly property var raisedSoft: ({
        outer: [[6, 6, 14, 0, _dark65], [-5, -5, 12, 0, _light13]], inset: [] })
    readonly property var raisedHover: ({
        outer: [[8, 8, 17, 0, _dark70], [-6, -6, 14, 0, _light15]], inset: [] })
    readonly property var insetSmall: ({
        outer: [], inset: [[3, 3, 7, 0, _dark72], [-3, -3, 6, 0, _light11]] })
    readonly property var inset: ({
        outer: [], inset: [[6, 6, 12, 0, _dark72], [-5, -5, 10, 0, _light12]] })
    readonly property var activeInsetGlow: ({
        outer: [[0, 0, 0, 1, accentBorder], [0, 0, 8, 0, accentGlow], [0, 0, 18, 0, accentGlowSoft]],
        inset: [[3, 3, 7, 0, _dark72], [-3, -3, 6, 0, _light11]] })
    readonly property var noticeShadow: ({
        outer: [[0, 0, 0, 1, accentBorder], [0, 0, 12, 0, accentGlowSoft]],
        inset: [[3, 3, 7, 0, _dark72], [-3, -3, 6, 0, _light11]] })
    readonly property var primaryFocus: ({
        outer: [[0, 0, 0, 1, accentBorder], [0, 0, 12, 0, accentGlowSoft],
                [6, 6, 14, 0, _dark65], [-5, -5, 12, 0, _light13]], inset: [] })
    readonly property var focusRing: ({
        outer: [[0, 0, 0, 1, accentBorder], [0, 0, 10, 0, accentGlowSoft]], inset: [] })
    readonly property var knobChecked: ({
        outer: [[0, 0, 8, 0, accentGlow], [6, 6, 14, 0, _dark65], [-5, -5, 12, 0, _light13]], inset: [] })
    readonly property var dotActive: ({
        outer: [[0, 0, 8, 0, accentGlow], [0, 0, 16, 0, accentGlowSoft]], inset: [] })
    readonly property var progressGlow: ({
        outer: [[0, 0, 8, 0, Qt.rgba(1, 102 / 255, 0, 0.25)]], inset: [] })
    readonly property var topBarShadow: ({
        outer: [[0, 10, 24, 0, Qt.rgba(0, 0, 0, 0.45)]], inset: [] })
    readonly property var flat: ({ outer: [], inset: [] })
}
