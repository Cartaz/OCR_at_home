import QtQuick

// A rounded surface with CSS-equivalent outer/inset box-shadows (see
// shaders/neumorphic.frag). Content goes on top of the surface.
Item {
    id: root
    property var shadow: Theme.flat
    property real radius: Theme.radiusMD
    property color color: Theme.surface
    property bool animated: true
    default property alias content: contentItem.data

    readonly property var _outer: shadow.outer || []
    readonly property var _inset: shadow.inset || []
    readonly property real _pad: {
        let pad = 1
        for (let i = 0; i < _outer.length; ++i) {
            const s = _outer[i]
            pad = Math.max(pad, Math.max(Math.abs(s[0]), Math.abs(s[1])) + 1.5 * s[2] + Math.max(0, s[3]) + 2)
        }
        return Math.ceil(pad)
    }

    function _slot(list, index) {
        const s = list[index]
        return s ? Qt.vector4d(s[0], s[1], s[2], s[3]) : Qt.vector4d(0, 0, 0, 0)
    }
    function _color(list, index) {
        const s = list[index]
        return s ? s[4] : Qt.rgba(0, 0, 0, 0)
    }

    ShaderEffect {
        id: effect
        x: -root._pad
        y: -root._pad
        width: root.width + 2 * root._pad
        height: root.height + 2 * root._pad
        visible: root.width > 0 && root.height > 0

        property size itemSize: Qt.size(width, height)
        property vector4d bodyRect: Qt.vector4d(root._pad, root._pad, root.width, root.height)
        property real radius: Math.min(root.radius, root.width / 2, root.height / 2)
        property color surfaceColor: root.color

        property vector4d outer1: root._slot(root._outer, 0)
        property color outer1Color: root._color(root._outer, 0)
        property vector4d outer2: root._slot(root._outer, 1)
        property color outer2Color: root._color(root._outer, 1)
        property vector4d outer3: root._slot(root._outer, 2)
        property color outer3Color: root._color(root._outer, 2)
        property vector4d outer4: root._slot(root._outer, 3)
        property color outer4Color: root._color(root._outer, 3)
        property vector4d inset1: root._slot(root._inset, 0)
        property color inset1Color: root._color(root._inset, 0)
        property vector4d inset2: root._slot(root._inset, 1)
        property color inset2Color: root._color(root._inset, 1)

        Behavior on outer1Color { enabled: root.animated; ColorAnimation { duration: Theme.shadowMs } }
        Behavior on outer2Color { enabled: root.animated; ColorAnimation { duration: Theme.shadowMs } }
        Behavior on outer3Color { enabled: root.animated; ColorAnimation { duration: Theme.shadowMs } }
        Behavior on outer4Color { enabled: root.animated; ColorAnimation { duration: Theme.shadowMs } }
        Behavior on inset1Color { enabled: root.animated; ColorAnimation { duration: Theme.shadowMs } }
        Behavior on inset2Color { enabled: root.animated; ColorAnimation { duration: Theme.shadowMs } }

        fragmentShader: Qt.resolvedUrl("../shaders/neumorphic.frag.qsb")
    }

    Item {
        id: contentItem
        anchors.fill: parent
    }
}
