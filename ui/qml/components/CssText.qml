import QtQuick

// Text laid out with CSS line-box rules as Chromium applies them:
//  * line-height "normal" = round(ascent) + round(descent);
//  * an explicit line height splits the extra space evenly (half-leading);
//  * marginTop/marginBottom behave like block margins.
// Qt alone makes each line ~1px taller and does not apply half-leading.
Text {
    id: root
    property real cssLineHeight: 0
    property real marginTop: 0
    property real marginBottom: 0

    readonly property real _ascent: Math.round(metrics.ascent)
    readonly property real _normal: _ascent + Math.round(metrics.descent)
    readonly property real _line: cssLineHeight > 0 ? cssLineHeight : _normal

    lineHeightMode: Text.FixedHeight
    lineHeight: _line
    // Chromium snaps the baseline to a whole pixel (half-leading floored).
    topPadding: marginTop + Math.floor((_line - _normal) / 2) + (_ascent - metrics.ascent)
    height: marginTop + Math.max(1, lineCount) * _line + marginBottom

    FontMetrics { id: metrics; font: root.font }
}
