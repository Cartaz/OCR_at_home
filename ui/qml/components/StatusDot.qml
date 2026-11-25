import QtQuick

// .status-dot: 8px, inset when idle, accent with glow when active.
NeuSurface {
    property bool active: false
    width: 8
    height: 8
    radius: 4
    color: active ? Theme.accent : Theme.textMuted
    shadow: active ? Theme.dotActive : Theme.insetSmall
}
