from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QApplication, QLabel, QStyle, QToolBar, QToolButton, QWidget, QWidgetAction


def _make_action(
    parent,
    object_name: str,
    text: str,
    *,
    checkable: bool = False,
    icon: QStyle.StandardPixmap | None = None,
    shortcut: str | None = None,
    tooltip: str | None = None,
) -> QAction:
    action = QAction(text, parent)
    action.setObjectName(object_name)
    action.setCheckable(checkable)
    if icon is not None:
        action.setIcon(QApplication.style().standardIcon(icon))
    if shortcut:
        action.setShortcut(QKeySequence(shortcut))
    if tooltip:
        action.setToolTip(tooltip)
        action.setStatusTip(tooltip)
    return action


def _add_section_label(toolbar: QToolBar, text: str) -> None:
    label = QLabel(text, toolbar)
    label.setProperty("role", "section")
    toolbar.addWidget(label)


def build_file_toolbar(parent) -> QToolBar:
    toolbar = QToolBar("Workflow", parent)
    toolbar.setObjectName("file_toolbar")
    toolbar.setMovable(False)
    toolbar.setFloatable(False)
    toolbar.setIconSize(QSize(18, 18))
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

    toolbar.setStyleSheet(
        """
        QToolBar#file_toolbar {
            background: #f8fafc;
            border: 0;
            border-bottom: 1px solid #d9e2ec;
            spacing: 8px;
            padding: 8px 10px;
        }
        QToolBar#file_toolbar QLabel[role="section"] {
            color: #52606d;
            font-size: 12px;
            font-weight: 600;
            padding: 0 2px 0 8px;
        }
        QToolBar#file_toolbar QToolButton {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            color: #1f2933;
            font-size: 13px;
            font-weight: 600;
            min-height: 30px;
            padding: 4px 10px;
        }
        QToolBar#file_toolbar QToolButton:hover {
            background: #eef6ff;
            border-color: #7aa7d9;
        }
        QToolBar#file_toolbar QToolButton:pressed {
            background: #dceeff;
            border-color: #3b82c4;
        }
        QToolBar#file_toolbar QToolButton:disabled {
            background: #f1f5f9;
            border-color: #d8dee7;
            color: #9aa5b1;
        }
        QToolBar#file_toolbar QComboBox {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            min-height: 30px;
            padding: 3px 28px 3px 10px;
        }
        """
    )

    _add_section_label(toolbar, "导入")
    toolbar.addAction(
        _make_action(
            parent,
            "open_action",
            "打开文件",
            icon=QStyle.StandardPixmap.SP_DialogOpenButton,
            shortcut="Ctrl+O",
            tooltip="打开 PPTX、PDF 或图片文件",
        )
    )
    toolbar.addAction(
        _make_action(
            parent,
            "folder_open_action",
            "打开文件夹",
            icon=QStyle.StandardPixmap.SP_DirIcon,
            shortcut="Ctrl+Shift+O",
            tooltip="选择包含图片的文件夹，按文件名顺序加载其中的所有图片",
        )
    )
    toolbar.addSeparator()
    _add_section_label(toolbar, "转换")
    toolbar.addAction(
        _make_action(
            parent,
            "folder_to_editable_pptx_action",
            "AI可编辑PPTX",
            icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
            shortcut="Ctrl+Shift+E",
            tooltip="调用 Evolink 将当前打开的页面生成分层可编辑 PPTX；未打开文件时可选择图片文件夹",
        )
    )
    toolbar.addSeparator()
    _add_section_label(toolbar, "输出")
    parent.addAction(
        _make_action(
            parent,
            "save_action",
            "保存",
            icon=QStyle.StandardPixmap.SP_DialogSaveButton,
            shortcut="Ctrl+S",
            tooltip="保存当前编辑结果",
        )
    )
    toolbar.addAction(
        _make_action(
            parent,
            "export_action",
            "导出",
            icon=QStyle.StandardPixmap.SP_DialogSaveButton,
            shortcut="Ctrl+E",
            tooltip="导出当前编辑结果",
        )
    )
    toolbar.addAction(
        _make_action(
            parent,
            "settings_action",
            "系统设置",
            icon=QStyle.StandardPixmap.SP_FileDialogInfoView,
            tooltip="配置 PPT/PDF 导入和 Evolink 参数",
        )
    )
    toolbar.addSeparator()
    _add_section_label(toolbar, "帮助")
    toolbar.addAction(
        _make_action(
            parent,
            "help_action",
            "使用帮助",
            icon=QStyle.StandardPixmap.SP_MessageBoxQuestion,
            shortcut="F1",
            tooltip="查看使用教程",
        )
    )
    return toolbar


def build_edit_toolbar(parent) -> QToolBar:
    toolbar = QToolBar("Edit", parent)
    toolbar.setObjectName("edit_toolbar")
    toolbar.setOrientation(Qt.Orientation.Horizontal)
    toolbar.setMovable(False)
    toolbar.setFloatable(False)
    toolbar.setIconSize(QSize(32, 32))
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    toolbar.setStyleSheet(
        """
        QToolBar {
            spacing: 10px;
            padding: 8px 12px;
        }
        QToolButton {
            min-width: 128px;
            min-height: 52px;
            padding: 7px 10px;
            font-size: 14px;
        }
        QToolButton:checked {
            background: #dbeafe;
            border: 1px solid #2563eb;
            border-radius: 4px;
        }
        QToolButton#nav_toggle_button {
            min-width: 52px;
            min-height: 52px;
            padding: 0;
        }
        """
    )

    def _nav_button(object_name: str, icon: QStyle.StandardPixmap, tooltip: str) -> QWidgetAction:
        shortcut_text = tooltip.split("(")[-1].rstrip(")").strip()
        button = QToolButton(toolbar)
        button.setObjectName("nav_toggle_button")
        button.setIcon(QApplication.style().standardIcon(icon))
        button.setIconSize(QSize(28, 28))
        button.setToolTip(tooltip)
        button.setStatusTip(tooltip)
        button.setAccessibleName(tooltip)
        widget_action = QWidgetAction(toolbar)
        widget_action.setObjectName(object_name)
        widget_action.setDefaultWidget(button)
        if shortcut_text:
            widget_action.setShortcut(QKeySequence(shortcut_text))
        button.clicked.connect(widget_action.trigger)
        return widget_action

    toolbar.addAction(_nav_button("prev_page_action", QStyle.StandardPixmap.SP_ArrowBack, "上一张 (Alt+Left)"))
    toolbar.addAction(_nav_button("next_page_action", QStyle.StandardPixmap.SP_ArrowForward, "下一张 (Alt+Right)"))

    left_spacer = QWidget(toolbar)
    left_spacer.setSizePolicy(left_spacer.sizePolicy().Policy.Expanding, left_spacer.sizePolicy().Policy.Preferred)
    left_action = QWidgetAction(toolbar)
    left_action.setDefaultWidget(left_spacer)
    toolbar.addAction(left_action)

    for object_name, text, checkable in (
        ("crop_action", "裁剪\nCtrl+3", False),
        ("select_action", "框选区域\nCtrl+1", True),
        ("move_select_action", "移动选区\nCtrl+2", True),
        ("erase_action", "擦除选区\nDelete", False),
        ("copy_action", "复制\nCtrl+C", False),
        ("paste_action", "粘贴\nCtrl+V", False),
        ("text_action", "插入文本", False),
        ("undo_action", "撤销\nCtrl+Z", False),
        ("transparent_action", "导出透明图", False),
    ):
        action = _make_action(parent, object_name, text, checkable=checkable)
        toolbar.addAction(action)

    for action in toolbar.actions():
        if action.objectName() == "select_action":
            action.setChecked(True)

    shortcuts = {
        "select_action": "Ctrl+1",
        "move_select_action": "Ctrl+2",
        "crop_action": "Ctrl+3",
        "erase_action": "Delete",
        "undo_action": "Ctrl+Z",
    }
    for action in toolbar.actions():
        shortcut = shortcuts.get(action.objectName())
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))

    right_spacer = QWidget(toolbar)
    right_spacer.setSizePolicy(right_spacer.sizePolicy().Policy.Expanding, right_spacer.sizePolicy().Policy.Preferred)
    right_action = QWidgetAction(toolbar)
    right_action.setDefaultWidget(right_spacer)
    toolbar.addAction(right_action)

    return toolbar


def make_chevron_icon(down: bool = False) -> QIcon:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#2563eb"), 2.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if down:
        points = (QPoint(3, 6), QPoint(8, 11), QPoint(13, 6))
    else:
        points = (QPoint(3, 10), QPoint(8, 5), QPoint(13, 10))
    painter.drawPolyline(points)
    painter.end()
    return QIcon(pixmap)
