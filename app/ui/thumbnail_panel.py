from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QListWidget, QListWidgetItem


class ThumbnailPanel(QListWidget):
    pageSelected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setIconSize(QSize(120, 80))
        self.currentRowChanged.connect(self.pageSelected.emit)
        self.setStyleSheet(
            """
            QListWidget {
                background: #ffffff;
                border-right: 1px solid #d9e2ec;
            }
            QListWidget::item {
                padding: 8px 6px;
                color: #1f2933;
            }
            QListWidget::item:hover {
                background: #eef2f7;
            }
            QListWidget::item:selected {
                background: #2563eb;
                color: #ffffff;
                border-left: 3px solid #1e40af;
            }
            """
        )

    def set_pages(self, thumbnail_paths: list[Path]) -> None:
        self.clear()
        for index, thumbnail_path in enumerate(thumbnail_paths, start=1):
            item = QListWidgetItem(QIcon(str(thumbnail_path)), f"Page {index}")
            self.addItem(item)

    def update_page(self, index: int, thumbnail_path: Path) -> None:
        if 0 <= index < self.count():
            self.item(index).setIcon(QIcon(str(thumbnail_path)))
