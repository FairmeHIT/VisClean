from __future__ import annotations

from pathlib import Path
import shutil

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QWidget,
)

from app.core.exporter import export_image_pptx, export_pdf, export_pngs
from app.core.session import ProjectSession
from app.core.image_inpainter import inpaint_file
from app.ui.canvas_view import CanvasView
from app.ui.thumbnail_panel import ThumbnailPanel
from app.ui.toolbar import build_edit_toolbar, build_file_toolbar
from app.utils.image import create_rect_mask
from app.utils.paths import create_session_dir
from app.workers.convert_worker import ConvertWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SlideClean")
        self.setMinimumSize(720, 480)
        self._fit_to_screen()
        self.session: ProjectSession | None = None
        self._convert_worker: ConvertWorker | None = None
        self._erase_worker = None
        self._current_rect: tuple[int, int, int, int] | None = None

        self.canvas = CanvasView(self)
        self.canvas.selectionMade.connect(self.on_selection_made)
        self.thumbnails = ThumbnailPanel(self)
        self.thumbnails.pageSelected.connect(self.set_page_index)
        self.edit_toolbar = build_edit_toolbar(self)
        self.resolution_combo: QComboBox | None = None

        splitter = QSplitter(self)
        splitter.addWidget(self.thumbnails)
        splitter.addWidget(self.canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        file_toolbar = build_file_toolbar(self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, file_toolbar)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, self.edit_toolbar)
        self.resolution_combo = file_toolbar.findChild(QComboBox, "resolution_combo")
        self.statusBar().showMessage("Ready")
        self._wire_toolbar_actions(file_toolbar, self.edit_toolbar)

    def _fit_to_screen(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1200, 800)
            return

        available = screen.availableGeometry()
        width = min(1400, int(available.width() * 0.9))
        height = min(900, int(available.height() * 0.9))
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )

    def _wire_toolbar_actions(self, *toolbars) -> None:
        actions: dict[str, QAction] = {}
        for toolbar in toolbars:
            actions.update({action.objectName(): action for action in toolbar.actions()})
        actions["open_action"].triggered.connect(self.open_pptx)
        actions["select_action"].triggered.connect(self.canvas.set_select_mode)
        actions["undo_action"].triggered.connect(self.undo_current_page)
        actions["erase_action"].triggered.connect(self.erase_current_selection)
        actions["export_action"].triggered.connect(self.export_project)
        self.canvas.set_select_mode()

    @Slot()
    def open_pptx(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open PPTX", "", "PowerPoint (*.pptx)")
        if not path:
            return
        self.load_project(Path(path))

    def load_project(self, pptx_path: Path) -> None:
        session_dir = create_session_dir(source_name=pptx_path.stem)
        self.session = ProjectSession(source_pptx=pptx_path, session_dir=session_dir)
        output_width = self._selected_output_width()
        self.statusBar().showMessage(f"Converting slides at {output_width}px wide...")
        self._convert_worker = ConvertWorker(pptx_path, session_dir / "pages", width=output_width, parent=self)
        self._convert_worker.finished.connect(self.on_conversion_finished)
        self._convert_worker.failed.connect(self.on_conversion_failed)
        self._convert_worker.start()

    def _selected_output_width(self) -> int:
        if self.resolution_combo is None:
            return 1920
        value = self.resolution_combo.currentData()
        return int(value) if value else 1920

    @Slot(list, dict)
    def on_conversion_finished(self, page_paths: list[Path], metadata: dict) -> None:
        if self.session is None:
            return
        self.session.set_pages([Path(p) for p in page_paths])
        self.thumbnails.set_pages([page.thumbnail_path for page in self.session.pages])
        if self.session.pages:
            self.thumbnails.setCurrentRow(0)
            self.canvas.set_image(str(self.session.pages[0].current_image_path))
            self.canvas.clear_selection()
        self.statusBar().showMessage(
            f"Loaded {metadata.get('slide_count', len(page_paths))} slides at "
            f"{metadata.get('output_width')}x{metadata.get('output_height')}"
        )

    @Slot(str)
    def on_conversion_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Conversion failed", message)
        self.statusBar().showMessage("Conversion failed")

    @Slot(int)
    def set_page_index(self, index: int) -> None:
        if self.session is None:
            return
        if 0 <= index < len(self.session.pages):
            self.session.current_page_index = index
            self.canvas.set_image(str(self.session.pages[index].current_image_path))
            self.canvas.clear_selection()

    @Slot(object)
    def on_selection_made(self, rect) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        rect = rect.toRect()
        try:
            from PIL import Image
        except ImportError:
            QMessageBox.critical(self, "Missing dependency", "Pillow is required to create selection masks.")
            return
        with Image.open(page.current_image_path) as image:
            width, height = image.size
        left = max(0, min(width - 1, rect.left()))
        top = max(0, min(height - 1, rect.top()))
        right = max(0, min(width - 1, rect.right()))
        bottom = max(0, min(height - 1, rect.bottom()))
        self._current_rect = (left, top, right, bottom)
        create_rect_mask(page.mask_path, (width, height), self._current_rect)
        self.statusBar().showMessage(f"Selected region {left},{top} - {right},{bottom}")

    @Slot()
    def erase_current_selection(self) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        if not page.mask_path.exists():
            QMessageBox.information(self, "No selection", "Select a region before erasing.")
            return
        snapshot = (
            self.session.session_dir
            / "history"
            / f"page_{page.index:03d}_undo_{len(page.history.undo_stack):03d}.png"
        )
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(page.current_image_path, snapshot)
        page.history.push(snapshot)
        try:
            inpaint_file(page.current_image_path, page.mask_path, page.current_image_path)
        except Exception as exc:
            QMessageBox.critical(self, "Erase failed", str(exc))
            return
        page.mask_path.unlink(missing_ok=True)
        self.canvas.set_image(str(page.current_image_path))
        self.canvas.clear_selection()
        self.statusBar().showMessage("Selection erased")

    @Slot()
    def undo_current_page(self) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        if not page.history.can_undo():
            return
        current_snapshot = (
            self.session.session_dir
            / "history"
            / f"page_{page.index:03d}_redo_{len(page.history.redo_stack):03d}.png"
        )
        shutil.copy2(page.current_image_path, current_snapshot)
        previous = page.history.undo(current_snapshot)
        if previous is None:
            return
        shutil.copy2(previous, page.current_image_path)
        self.canvas.set_image(str(page.current_image_path))
        self.canvas.clear_selection()
        self.statusBar().showMessage("Undo complete")

    @Slot()
    def redo_current_page(self) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        if not page.history.can_redo():
            return
        current_snapshot = (
            self.session.session_dir
            / "history"
            / f"page_{page.index:03d}_undo_{len(page.history.undo_stack):03d}.png"
        )
        shutil.copy2(page.current_image_path, current_snapshot)
        next_snapshot = page.history.redo(current_snapshot)
        if next_snapshot is None:
            return
        shutil.copy2(next_snapshot, page.current_image_path)
        self.canvas.set_image(str(page.current_image_path))
        self.canvas.clear_selection()
        self.statusBar().showMessage("Redo complete")

    @Slot()
    def export_project(self) -> None:
        if self.session is None or not self.session.pages:
            return
        output_dir = QFileDialog.getExistingDirectory(self, "Export to folder")
        if not output_dir:
            return
        output_root = Path(output_dir)
        page_images = [page.current_image_path for page in self.session.pages]
        try:
            export_pngs(page_images, output_root / "png")
            export_pdf(page_images, output_root / "export.pdf")
            export_image_pptx(page_images, output_root / "export.pptx")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(f"Exported to {output_root}")

    def closeEvent(self, event) -> None:
        if self._convert_worker and self._convert_worker.isRunning():
            self._convert_worker.quit()
            self._convert_worker.wait(1000)
        super().closeEvent(event)
