from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QComboBox, QLabel, QToolBar, QWidget, QWidgetAction


def _make_action(parent, object_name: str, text: str, *, checkable: bool = False) -> QAction:
    action = QAction(text, parent)
    action.setObjectName(object_name)
    action.setCheckable(checkable)
    return action


def build_file_toolbar(parent) -> QToolBar:
    toolbar = QToolBar("File", parent)
    toolbar.setObjectName("file_toolbar")
    toolbar.setMovable(False)
    toolbar.setIconSize(QSize(24, 24))
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    for object_name, text in (
        ("open_action", "打开"),
        ("export_action", "导出"),
    ):
        toolbar.addAction(_make_action(parent, object_name, text))
    toolbar.addSeparator()
    resolution_label = QLabel("图片分辨率", toolbar)
    resolution_label.setObjectName("resolution_label")
    toolbar.addWidget(resolution_label)
    resolution_combo = QComboBox(toolbar)
    resolution_combo.setObjectName("resolution_combo")
    for text, width in (
        ("低 1280px", 1280),
        ("标准 1920px", 1920),
        ("高清 2560px", 2560),
        ("超清 3840px", 3840),
    ):
        resolution_combo.addItem(text, width)
    resolution_combo.setCurrentIndex(1)
    resolution_combo.setMinimumWidth(120)
    toolbar.addWidget(resolution_combo)
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
            min-width: 108px;
            min-height: 44px;
            padding: 8px 12px;
            font-size: 15px;
        }
        QToolButton:checked {
            background: #dbeafe;
            border: 1px solid #2563eb;
            border-radius: 4px;
        }
        """
    )

    left_spacer = QWidget(toolbar)
    left_spacer.setSizePolicy(left_spacer.sizePolicy().Policy.Expanding, left_spacer.sizePolicy().Policy.Preferred)
    left_action = QWidgetAction(toolbar)
    left_action.setDefaultWidget(left_spacer)
    toolbar.addAction(left_action)

    for object_name, text, checkable in (
        ("select_action", "选框", True),
        ("erase_action", "擦除", False),
        ("undo_action", "撤销", False),
    ):
        action = _make_action(parent, object_name, text, checkable=checkable)
        toolbar.addAction(action)

    for action in toolbar.actions():
        if action.objectName() == "select_action":
            action.setChecked(True)

    right_spacer = QWidget(toolbar)
    right_spacer.setSizePolicy(right_spacer.sizePolicy().Policy.Expanding, right_spacer.sizePolicy().Policy.Preferred)
    right_action = QWidgetAction(toolbar)
    right_action.setDefaultWidget(right_spacer)
    toolbar.addAction(right_action)

    return toolbar
