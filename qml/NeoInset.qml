import QtQuick

Item {
    id: root
    Theme { id: theme }
    property color surfaceColor: theme.inset
    property real radius: theme.radiusMedium
    property real depth: 9
    property bool focused: false

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            ctx.clearRect(0, 0, width, height);
            var w = width;
            var h = height;
            var r = Math.max(1, Math.min(root.radius, Math.min(w, h) / 2));
            var d = Math.max(2, Math.min(root.depth, Math.min(w, h) / 3));
            function roundedRectPath(x, y, w, h, r) {
                ctx.beginPath();
                ctx.moveTo(x + r, y);
                ctx.lineTo(x + w - r, y);
                ctx.quadraticCurveTo(x + w, y, x + w, y + r);
                ctx.lineTo(x + w, y + h - r);
                ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
                ctx.lineTo(x + r, y + h);
                ctx.quadraticCurveTo(x, y + h, x, y + h - r);
                ctx.lineTo(x, y + r);
                ctx.quadraticCurveTo(x, y, x + r, y);
                ctx.closePath();
            }
            roundedRectPath(0.5, 0.5, w - 1, h - 1, r);
            ctx.fillStyle = root.surfaceColor;
            ctx.fill();
            if (root.focused) { ctx.strokeStyle = theme.accent; ctx.lineWidth = 1; ctx.stroke(); }
            ctx.save();
            roundedRectPath(0.5, 0.5, w - 1, h - 1, r);
            ctx.clip();
            var topGrad = ctx.createLinearGradient(0, 0, 0, d);
            topGrad.addColorStop(0.0, "rgba(0,0,0,0.72)"); topGrad.addColorStop(1.0, "rgba(0,0,0,0.0)");
            ctx.fillStyle = topGrad; ctx.fillRect(0, 0, w, d);
            var leftGrad = ctx.createLinearGradient(0, 0, d, 0);
            leftGrad.addColorStop(0.0, "rgba(0,0,0,0.64)"); leftGrad.addColorStop(1.0, "rgba(0,0,0,0.0)");
            ctx.fillStyle = leftGrad; ctx.fillRect(0, 0, d, h);
            var bottomGrad = ctx.createLinearGradient(0, h, 0, h - d);
            bottomGrad.addColorStop(0.0, "rgba(36,36,36,0.42)"); bottomGrad.addColorStop(1.0, "rgba(36,36,36,0.0)");
            ctx.fillStyle = bottomGrad; ctx.fillRect(0, h - d, w, d);
            var rightGrad = ctx.createLinearGradient(w, 0, w - d, 0);
            rightGrad.addColorStop(0.0, "rgba(36,36,36,0.38)"); rightGrad.addColorStop(1.0, "rgba(36,36,36,0.0)");
            ctx.fillStyle = rightGrad; ctx.fillRect(w - d, 0, d, h);
            ctx.restore();
        }
        Connections {
            target: root
            function onWidthChanged() { canvas.requestPaint(); }
            function onHeightChanged() { canvas.requestPaint(); }
            function onSurfaceColorChanged() { canvas.requestPaint(); }
            function onRadiusChanged() { canvas.requestPaint(); }
            function onDepthChanged() { canvas.requestPaint(); }
            function onFocusedChanged() { canvas.requestPaint(); }
        }
    }
}
