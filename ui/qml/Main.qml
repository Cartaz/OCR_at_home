import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic as Basic
import "components"
import "views"

// Port of the former HTML/CSS interface: same layout, tokens and breakpoints
// (>900px sidebar, <=900px top bar, <=620px icon-only navigation).
Window {
    id: window
    color: Theme.surface
    title: "GLM OCR"
    visible: false

    Component.onCompleted: Theme.semiBold = backend.semiBoldWeight
    readonly property bool compact: width <= 900
    readonly property bool narrow: width <= 620
    readonly property real sidebarWidth: compact ? 0 : 220
    readonly property real topBarHeight: compact ? (narrow ? 68 : 72) : 0

    Sidebar {
        id: sidebar
        z: 10
        compact: window.compact
        narrow: window.narrow
        x: 0
        y: 0
        width: window.compact ? window.width : window.sidebarWidth
        height: window.compact ? window.topBarHeight : window.height
    }

    Flickable {
        id: workspace
        anchors.fill: parent
        anchors.leftMargin: window.sidebarWidth
        contentWidth: width
        contentHeight: page.height
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        Basic.ScrollBar.vertical: NeuScrollBar { parent: workspace.parent; anchors.top: workspace.top; anchors.right: workspace.right; anchors.bottom: workspace.bottom }

        Item {
            id: page
            readonly property real padTop: window.narrow ? 18 : window.compact ? 22 : 26
            readonly property real padRight: window.narrow ? 14 : window.compact ? 20 : 32
            readonly property real padBottom: window.narrow ? 28 : window.compact ? 34 : 40
            readonly property real padLeft: window.narrow ? 14 : window.compact ? 20 : 18
            // Chromium's page scrollbar takes layout width (10px) when the page overflows.
            readonly property real scrollbarWidth: content.y + content.implicitHeight + padBottom > workspace.height ? 10 : 0
            width: workspace.width
            height: Math.max(workspace.height, content.y + content.implicitHeight + padBottom)

            Column {
                id: content
                x: page.padLeft
                y: window.topBarHeight + page.padTop
                width: Math.min(page.width - page.scrollbarWidth - page.padLeft - page.padRight, 1280)

                // .topbar
                Item {
                    id: topbar
                    objectName: "topbar"
                    width: parent.width
                    readonly property real titleSize: Math.max(24, Math.min(34, window.width * 0.03))
                    height: Math.max(78, inner.height + 22)
                    Item {
                        id: inner
                        x: 4
                        y: 4
                        width: parent.width - 8
                        height: window.narrow ? heading.height + 14 + actions.height
                                              : Math.max(heading.height, actions.height)
                        Column {
                            id: heading
                            width: window.narrow ? parent.width : parent.width - actions.width - 24
                            CssText {
                                objectName: "eyebrow"
                                text: "GLM-OCR · LLAMA.CPP"
                                color: Theme.textMuted
                                font.pixelSize: 11
                                font.weight: Theme.semiBold
                                font.letterSpacing: 1.32
                                marginBottom: 4
                            }
                            CssText {
                                objectName: "viewTitle"
                                width: parent.width
                                text: backend.viewTitle
                                color: Theme.textPrimary
                                font.pixelSize: topbar.titleSize
                                font.weight: Font.Bold
                                font.letterSpacing: -0.025 * topbar.titleSize
                                cssLineHeight: topbar.titleSize * 1.1
                                elide: Text.ElideRight
                                Accessible.role: Accessible.Heading
                            }
                        }
                        Row {
                            id: actions
                            x: window.narrow ? 0 : parent.width - width
                            y: window.narrow ? heading.height + 14 : 0
                            spacing: 10
                            StatusPill {
                                objectName: "modelStatus"
                                height: window.narrow ? 34 : 38
                                text: backend.modelStatusText
                                active: backend.modelStatusActive
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            NeuButton {
                                visible: backend.globalCancelVisible
                                variant: "icon"
                                iconName: "stop"
                                tooltip: "Annulla operazione in corso"
                                onClicked: backend.cancelOperation()
                            }
                        }
                    }
                }

                Notice {
                    objectName: "notice"
                    width: parent.width
                    visible: backend.noticeVisible
                    height: visible ? implicitHeight : 0
                }
                Item { width: 1; height: backend.noticeVisible ? 24 : 0 }

                OcrView {
                    width: parent.width
                    visible: backend.view === "ocr"
                    narrow: window.narrow
                    viewportHeight: window.height
                }
                BatchView {
                    width: parent.width
                    visible: backend.view === "batch"
                    narrow: window.narrow
                    viewportHeight: window.height
                }
                LogsView {
                    width: parent.width
                    visible: backend.view === "logs"
                    active: visible && window.visible
                    narrow: window.narrow
                    viewportHeight: window.height
                }
                SettingsView {
                    width: parent.width
                    visible: backend.view === "settings"
                    compact: window.compact
                    narrow: window.narrow
                }
            }
        }
    }

    DropArea {
        anchors.fill: parent
        keys: ["text/uri-list"]
        onDropped: (drop) => {
            if (drop.hasUrls) {
                backend.acceptDroppedUrls(drop.urls)
                drop.acceptProposedAction()
            }
        }
    }

    Connections {
        target: backend
        function onViewChanged() { workspace.contentY = 0 }
    }

    Shortcut {
        sequence: "Ctrl+O"
        onActivated: {
            backend.setView("ocr")
            if (backend.canChooseSingle) backend.chooseSingleFile()
        }
    }
    Shortcut {
        sequences: ["Ctrl+Return", "Ctrl+Enter"]
        onActivated: {
            if (backend.view === "ocr" && backend.canStartSingle) backend.startSingleOcr()
            else if (backend.view === "batch" && backend.canStartBatch) backend.startBatch()
        }
    }
    Shortcut {
        sequence: "Ctrl+Shift+C"
        onActivated: if (backend.view === "ocr" && backend.canCopySingle) backend.copyText(backend.singleText)
    }
    Shortcut {
        // Text fields handle their own paste; elsewhere Ctrl+V stages a clipboard image.
        sequences: [StandardKey.Paste]
        enabled: !(window.activeFocusItem && window.activeFocusItem.hasOwnProperty("cursorPosition")
                   && !window.activeFocusItem.readOnly)
        onActivated: backend.pasteClipboardImage()
    }
}
