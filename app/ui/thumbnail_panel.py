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

    def set_pages(self, thumbnail_paths: list[Path]) -> None:
        self.clear()
        for index, thumbnail_path in enumerate(thumbnail_paths, start=1):
            item = QListWidgetItem(QIcon(str(thumbnail_path)), f"Page {index}")
            self.addItem(item)
