import QtQuick
import QtQuick.Shapes

// Stroke icon drawn from the same 24x24 SVG path data the web UI used
// (stroke-width 1.7, round caps and joins, no fill).
Item {
    id: root
    property string name: ""
    property color color: Theme.textSecondary
    property real size: 20
    implicitWidth: size
    implicitHeight: size
    width: size
    height: size

    readonly property var _paths: ({
        "brand": ["M5 3h10l4 4v14H5z", "M15 3v5h5M8 12h8M8 16h8"],
        "ocr": ["M4 7V4h3M17 4h3v3M20 17v3h-3M7 20H4v-3M8 8h8v8H8z"],
        "batch": ["M7 3h10v4H7zM5 8h14v5H5zM3 14h18v7H3z"],
        "logs": ["M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"],
        "settings": ["M15 12a3 3 0 1 1-6 0a3 3 0 1 1 6 0",
                     "M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.7-1L14.5 3h-5l-.4 3.1a7 7 0 0 0-1.7 1L5 6.1 3 9.5 5 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.7 1l.4 3.1h5l.4-3.1a7 7 0 0 0 1.7-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1z"],
        "quit": ["M10 5H5v14h5M14 8l4 4-4 4M18 12H9"],
        "stop": ["M7 7h10v10H7z"],
        "close": ["M6 6l12 12M18 6L6 18"],
        "file": ["M5 3h10l4 4v14H5zM15 3v5h5"],
        "folder": ["M4 6h6l2 2h8v11H4z"],
        "folderPlus": ["M4 6h6l2 2h8v11H4zM12 11v6M9 14h6"],
        "play": ["M8 5l11 7-11 7z"],
        "copy": ["M8 8h11v12H8zM5 4h10v4M5 4v12h3"],
        "refresh": ["M19 8a7 7 0 1 0 1 7M19 4v4h-4"]
    })

    readonly property var _icon: _paths[name] || []

    Shape {
        width: 24
        height: 24
        scale: root.size / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root._icon.length > 0 ? root.color : "transparent"
            strokeWidth: 1.7
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: root._icon.length > 0 ? root._icon[0] : "M0 0" }
        }
        ShapePath {
            strokeColor: root._icon.length > 1 ? root.color : "transparent"
            strokeWidth: 1.7
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: root._icon.length > 1 ? root._icon[1] : "M0 0" }
        }
    }
}
