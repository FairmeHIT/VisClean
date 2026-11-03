from __future__ import annotations

from pathlib import Path
import json
import re
import shutil

from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtGui import QAction, QBrush, QColor, QCursor, QGuiApplication, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.exporter import (
    export_image_file,
    export_image_ppt,
    export_image_pptx,
    export_images_folder,
    export_pngs,
    export_transparent_image_file,
)
from app.core.session import (
    PastedObject,
    ProjectSession,
    compose_page,
    crop_page_to_rect,
    update_page_thumbnail,
)
from app.core.image_inpainter import inpaint_file
from app.core.settings import (
    DOCUMENT_WIDTH_OPTIONS,
    EDITABLE_PPTX_ENGINE_OPTIONS,
    IMAGE_SIZE_OPTIONS,
    QUALITY_OPTIONS,
    RESOLUTION_OPTIONS,
    EvolinkSettings,
    mask_secret,
    read_evolink_settings,
    write_evolink_settings,
)
from app.ui.canvas_view import CanvasView
from app.ui.thumbnail_panel import ThumbnailPanel
from app.ui.toolbar import build_edit_toolbar, build_file_toolbar, make_chevron_icon
from app.utils.image import (
    SUPPORTED_IMAGE_EXTENSIONS,
    create_rect_mask,
    create_rect_mask_from_rects,
    is_supported_image_path,
)
from app.utils.paths import create_session_dir, default_editable_pptx_output_path
from app.workers.connectivity_worker import EvolinkConnectivityWorker
from app.workers.convert_worker import ConvertWorker
from app.workers.editable_pptx_worker import EditablePptxWorker


IMAGE_IMPORT_FILTER = " ".join(f"*{extension}" for extension in sorted(SUPPORTED_IMAGE_EXTENSIONS))
IMPORT_FILE_FILTER = (
    f"Supported files (*.pptx *.pdf {IMAGE_IMPORT_FILTER});;"
    "PowerPoint (*.pptx);;"
    "PDF (*.pdf);;"
    f"Images ({IMAGE_IMPORT_FILTER})"
)
DOCUMENT_SOURCE_TYPES = {"pptx", "pdf"}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SlideClean")
        self.setMinimumSize(720, 480)
        self._fit_to_screen()
        self.session: ProjectSession | None = None
        self._dirty = False
        self._convert_worker: ConvertWorker | None = None
        self._editable_pptx_worker: EditablePptxWorker | None = None
        self._connectivity_worker: EvolinkConnectivityWorker | None = None
        self._editable_pptx_progress_dialog: QProgressDialog | None = None
        self._erase_worker = None
        self._toolbar_actions: dict[str, QAction] = {}
        self._ai_progress_label = QLabel("AI 可编辑 PPTX", self)
        self._ai_progress_label.setMinimumWidth(260)
        self._ai_progress_label.hide()
        self._ai_progress_bar = QProgressBar(self)
        self._ai_progress_bar.setRange(0, 0)
        self._ai_progress_bar.setFixedWidth(120)
        self._ai_progress_bar.hide()

        self.canvas = CanvasView(self)
        self.canvas.selectionMade.connect(self.on_selection_made)
        self.canvas.selectionCleared.connect(self.on_selection_cleared)
        self.canvas.moveMade.connect(self.on_move_made)
        self.canvas.copyRequested.connect(self.copy_selection)
        self.canvas.pasteRequested.connect(self.paste_clipboard)
        self.canvas.textRequested.connect(self.on_text_requested)
        self._clipboard: list[tuple] = []
        self._pending_text: str | None = None
        self.thumbnails = ThumbnailPanel(self)
        self.thumbnails.pageSelected.connect(self.set_page_index)
        self.settings_panel = self._build_settings_panel()
        self._load_system_settings_into_controls()
        self.edit_toolbar = build_edit_toolbar(self)

        splitter = QSplitter(self)
        splitter.addWidget(self.thumbnails)
        splitter.addWidget(self.canvas)
        splitter.addWidget(self.settings_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        self.settings_panel.hide()

        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        file_toolbar = build_file_toolbar(self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, file_toolbar)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, self.edit_toolbar)
        self.edit_toolbar.hide()
        self.statusBar().showMessage("Ready")
        self.statusBar().addPermanentWidget(self._ai_progress_label)
        self.statusBar().addPermanentWidget(self._ai_progress_bar)
        self._edit_toggle_button = QToolButton(self)
        self._edit_toggle_button.setObjectName("edit_toggle_button")
        self._edit_toggle_button.setIcon(make_chevron_icon(down=True))
        self._edit_toggle_button.setIconSize(QSize(18, 18))
        self._edit_toggle_button.setFixedSize(26, 26)
        self._edit_toggle_button.setToolTip("展开下方编辑工具 (Ctrl+Shift+T)")
        self._edit_toggle_button.setAccessibleName("展开或收起下方编辑工具")
        self._edit_toggle_button.setStyleSheet(
            "QToolButton { background: transparent; border: none; border-radius: 4px; }"
            "QToolButton:hover { background: #e2e8f0; }"
        )
        self._edit_toggle_button.clicked.connect(self._toggle_edit_tools)
        self.statusBar().addPermanentWidget(self._edit_toggle_button)
        toggle_shortcut_action = QAction(self)
        toggle_shortcut_action.setObjectName("edit_toggle_shortcut_action")
        toggle_shortcut_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
        toggle_shortcut_action.triggered.connect(self._toggle_edit_tools)
        self.addAction(toggle_shortcut_action)
        self._wire_toolbar_actions(file_toolbar, self.edit_toolbar)
        self._update_action_states()

    def _build_settings_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("settings_panel")
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(420)
        panel.setStyleSheet(
            """
            QWidget#settings_panel {
                background: #ffffff;
                border-left: 1px solid #d9e2ec;
            }
            QWidget#settings_panel QLabel[role="title"] {
                color: #1f2933;
                font-size: 18px;
                font-weight: 700;
            }
            QWidget#settings_panel QLabel[role="hint"] {
                color: #52606d;
                font-size: 12px;
            }
            QWidget#settings_panel QLabel[role="section"] {
                color: #1f2933;
                font-size: 13px;
                font-weight: 700;
                padding-top: 8px;
            }
            QWidget#settings_panel QLineEdit {
                min-height: 30px;
                padding: 4px 8px;
            }
            QWidget#settings_panel QPushButton {
                min-height: 30px;
                padding: 4px 12px;
            }
            """
        )

        title = QLabel("系统设置", panel)
        title.setProperty("role", "title")
        close_button = QPushButton("关闭", panel)
        close_button.clicked.connect(self.close_system_settings)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(close_button)

        self.current_key_label = QLabel(panel)
        self.current_key_label.setProperty("role", "hint")

        self.api_key_input = QLineEdit(panel)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("EVOLINK_API_KEY")

        self.base_url_input = QLineEdit(panel)
        self.base_url_input.setPlaceholderText("默认：https://api.evolink.ai")

        self.vision_model_input = QLineEdit(panel)
        self.vision_model_input.setPlaceholderText("默认：gpt-5.1")

        self.document_width_combo = QComboBox(panel)
        for width in DOCUMENT_WIDTH_OPTIONS:
            label = {
                1280: "低 1280px",
                1920: "标准 1920px",
                2560: "高清 2560px",
                3840: "超清 3840px",
            }.get(width, f"{width}px")
            self.document_width_combo.addItem(label, width)
        self.document_width_combo.setToolTip("仅用于打开 PPTX/PDF 时转换页面，不会缩放直接导入的图片")

        self.editable_pptx_engine_combo = QComboBox(panel)
        engine_labels = {
            "gorden-four-layer": "Gorden 四层重建（当前内置）",
            "editppt-cli": "Image-to-Editable-PPT CLI（实验）",
        }
        for value in EDITABLE_PPTX_ENGINE_OPTIONS:
            self.editable_pptx_engine_combo.addItem(engine_labels.get(value, value), value)
        self.editable_pptx_engine_combo.setToolTip(
            "Gorden 四层重建适合当前桌面流程；EditPPT CLI 是完整工作流适配器，后续用于更强的页面级重建。"
        )

        self.image_size_combo = QComboBox(panel)
        for value in IMAGE_SIZE_OPTIONS:
            label = "自动（按图片）" if value == "auto" else value
            self.image_size_combo.addItem(label, value)

        self.evolink_resolution_combo = QComboBox(panel)
        for value in RESOLUTION_OPTIONS:
            self.evolink_resolution_combo.addItem(value, value)

        self.quality_combo = QComboBox(panel)
        for value in QUALITY_OPTIONS:
            self.quality_combo.addItem(value, value)

        self.toggle_key_button = QPushButton(panel)
        self.toggle_key_button.setCheckable(True)
        self.toggle_key_button.setIcon(_visibility_icon(False))
        self.toggle_key_button.setIconSize(QSize(18, 18))
        self.toggle_key_button.setFixedWidth(40)
        self.toggle_key_button.setToolTip("显示 Key")
        self.toggle_key_button.setAccessibleName("显示或隐藏 Evolink Key")
        self.toggle_key_button.toggled.connect(self.toggle_api_key_visibility)

        key_row = QHBoxLayout()
        key_row.addWidget(self.api_key_input, 1)
        key_row.addWidget(self.toggle_key_button)

        document_section = QLabel("PPT/PDF 导入", panel)
        document_section.setProperty("role", "section")
        document_form = QFormLayout()
        document_form.addRow("截图宽度", self.document_width_combo)

        ai_section = QLabel("AI 可编辑 PPTX", panel)
        ai_section.setProperty("role", "section")
        ai_form = QFormLayout()
        ai_form.addRow("转换引擎", self.editable_pptx_engine_combo)
        ai_form.addRow("当前 Key", self.current_key_label)
        ai_form.addRow("Evolink Key", key_row)
        ai_form.addRow("Base URL", self.base_url_input)
        ai_form.addRow("视觉识别模型", self.vision_model_input)
        ai_form.addRow("图片尺寸 size", self.image_size_combo)
        ai_form.addRow("分辨率 resolution", self.evolink_resolution_combo)
        ai_form.addRow("质量 quality", self.quality_combo)

        self.settings_status_label = QLabel(panel)
        self.settings_status_label.setProperty("role", "hint")
        self.settings_status_label.setWordWrap(True)

        self.test_connection_button = QPushButton("测试连接", panel)
        self.test_connection_button.clicked.connect(self.test_system_settings_connection)

        save_button = QPushButton("保存", panel)
        save_button.clicked.connect(self.save_system_settings)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.test_connection_button)
        buttons.addWidget(save_button)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(document_section)
        layout.addLayout(document_form)
        layout.addWidget(ai_section)
        layout.addLayout(ai_form)
        layout.addWidget(self.settings_status_label)
        layout.addStretch(1)
        layout.addLayout(buttons)
        return panel

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
        actions.update({action.objectName(): action for action in self.actions()})
        self._toolbar_actions = actions
        actions["open_action"].triggered.connect(self.open_files)
        actions["folder_open_action"].triggered.connect(self.open_folder)
        actions["folder_to_editable_pptx_action"].triggered.connect(self.convert_image_folder_to_editable_pptx)
        actions["prev_page_action"].triggered.connect(self.goto_prev_page)
        actions["next_page_action"].triggered.connect(self.goto_next_page)
        actions["settings_action"].triggered.connect(self.open_system_settings)
        actions["help_action"].triggered.connect(self.show_help)
        actions["select_action"].triggered.connect(self.toggle_select_mode)
        actions["move_select_action"].triggered.connect(self.toggle_move_mode)
        actions["crop_action"].triggered.connect(self.crop_current_selection)
        actions["undo_action"].triggered.connect(self.undo_current_page)
        actions["erase_action"].triggered.connect(self.erase_current_selection)
        actions["copy_action"].triggered.connect(self.copy_selection)
        actions["paste_action"].triggered.connect(self.paste_clipboard)
        actions["text_action"].triggered.connect(self.insert_text)
        actions["transparent_action"].triggered.connect(self.export_current_page_transparent)
        actions["save_action"].triggered.connect(self.save_project)
        actions["export_action"].triggered.connect(self.export_project)
        self.canvas.set_select_mode()

    def _update_action_states(self) -> None:
        editable_pptx_running = self._editable_pptx_worker is not None and self._editable_pptx_worker.isRunning()
        editable_pptx_action = self._toolbar_actions.get("folder_to_editable_pptx_action")
        if editable_pptx_action is not None:
            editable_pptx_action.setEnabled(not editable_pptx_running)
        edit_toggle_button = getattr(self, "_edit_toggle_button", None)
        if edit_toggle_button is not None:
            edit_toggle_button.setEnabled(self.session is not None and self.session.current_page is not None)
        prev_page_action = self._toolbar_actions.get("prev_page_action")
        next_page_action = self._toolbar_actions.get("next_page_action")
        if prev_page_action is not None:
            prev_page_action.setEnabled(self.session is not None and self.session.current_page is not None)
        if next_page_action is not None:
            next_page_action.setEnabled(self.session is not None and self.session.current_page is not None)
        save_action = self._toolbar_actions.get("save_action")
        if save_action is not None:
            save_action.setEnabled(self.session is not None and bool(self.session.pages))
        export_action = self._toolbar_actions.get("export_action")
        if export_action is not None:
            export_action.setEnabled(self.session is not None and bool(self.session.pages))
        transparent_action = self._toolbar_actions.get("transparent_action")
        if transparent_action is not None:
            transparent_action.setEnabled(self.session is not None and self.session.current_page is not None)
        for action_name in ("copy_action", "paste_action", "text_action"):
            action = self._toolbar_actions.get(action_name)
            if action is not None:
                action.setEnabled(self.session is not None and self.session.current_page is not None)
        crop_action = self._toolbar_actions.get("crop_action")
        if crop_action is not None:
            crop_action.setEnabled(self.session is not None and self.session.current_page is not None)

    @Slot()
    def _toggle_edit_tools(self) -> None:
        self.set_edit_tools_visible(not self.edit_toolbar.isVisible())

    def set_edit_tools_visible(self, visible: bool) -> None:
        self.edit_toolbar.setVisible(visible)
        self._edit_toggle_button.setIcon(make_chevron_icon(down=not visible))
        self._edit_toggle_button.setToolTip(
            "收起下方编辑工具 (Ctrl+Shift+T)" if visible else "展开下方编辑工具 (Ctrl+Shift+T)"
        )
        self.statusBar().showMessage("编辑工具已显示" if visible else "编辑工具已收起")

    @Slot()
    def goto_prev_page(self) -> None:
        if self.session is None or self.session.current_page is None:
            return
        index = self.session.current_page_index - 1
        if 0 <= index < len(self.session.pages):
            self.thumbnails.setCurrentRow(index)

    @Slot()
    def goto_next_page(self) -> None:
        if self.session is None or self.session.current_page is None:
            return
        index = self.session.current_page_index + 1
        if 0 <= index < len(self.session.pages):
            self.thumbnails.setCurrentRow(index)

    @Slot(bool)
    def toggle_select_mode(self, checked: bool) -> None:
        move_action = self._toolbar_actions.get("move_select_action")
        if move_action is not None:
            move_action.setChecked(False)
        self.canvas.set_select_mode()
        if checked:
            self.statusBar().showMessage("框选模式：拖拽框选区域，按住 Shift 多选，左键点击取消选区，右键按住选框可移动选中内容")

    @Slot(bool)
    def toggle_move_mode(self, checked: bool) -> None:
        select_action = self._toolbar_actions.get("select_action")
        if checked:
            if select_action is not None:
                select_action.setChecked(False)
            self.canvas.set_move_mode()
            self.statusBar().showMessage("移动模式：在选框内按住鼠标拖拽移动，或用方向键步进移动（Shift+方向键大步长）")
        else:
            self.canvas.set_select_mode()
            if select_action is not None:
                select_action.setChecked(True)

    @Slot()
    def open_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open PPTX, PDF or images", "", IMPORT_FILE_FILTER)
        if not paths:
            return
        import_paths = [Path(path) for path in paths]
        if len(import_paths) == 1 and import_paths[0].suffix.lower() in {".pptx", ".pdf"}:
            self.load_project(import_paths[0])
            return
        if all(is_supported_image_path(path) for path in import_paths):
            self.load_images(import_paths)
            return
        QMessageBox.warning(self, "Unsupported files", "请选择一个 PPTX/PDF 文件，或选择一张/多张图片文件。")

    @Slot()
    def open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "打开图片文件夹")
        if not folder:
            return
        source_dir = Path(folder)
        try:
            image_paths = _collect_image_paths(source_dir)
        except Exception as exc:
            QMessageBox.critical(self, "Image scan failed", str(exc))
            return
        if not image_paths:
            QMessageBox.warning(self, "No images", "所选文件夹中没有支持的图片文件。")
            return
        self.load_images(image_paths)

    @Slot()
    def open_system_settings(self) -> None:
        self._load_system_settings_into_controls()
        self.settings_panel.show()
        self.api_key_input.setFocus()

    @Slot()
    def show_help(self) -> None:
        from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout

        dialog = QDialog(self)
        dialog.setWindowTitle("使用帮助")
        dialog.resize(680, 560)
        browser = QTextBrowser(dialog)
        browser.setOpenExternalLinks(False)
        browser.setHtml(_help_html())
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(browser)
        dialog.exec()

    def _load_system_settings_into_controls(self) -> None:
        current = read_evolink_settings()
        self.api_key_input.setText(current.api_key)
        self.base_url_input.setText(current.base_url)
        self.vision_model_input.setText(current.vision_model)
        _set_combo_value(self.document_width_combo, current.document_width)
        _set_combo_value(self.editable_pptx_engine_combo, current.editable_pptx_engine)
        _set_combo_value(self.image_size_combo, current.image_size)
        _set_combo_value(self.evolink_resolution_combo, current.resolution)
        _set_combo_value(self.quality_combo, current.quality)
        self.current_key_label.setText(mask_secret(current.api_key))
        self.settings_status_label.setText("")
        self.toggle_key_button.setChecked(False)

    def _settings_from_controls(self) -> EvolinkSettings:
        return EvolinkSettings(
            api_key=self.api_key_input.text().strip(),
            base_url=self.base_url_input.text().strip(),
            document_width=int(self.document_width_combo.currentData()),
            editable_pptx_engine=str(self.editable_pptx_engine_combo.currentData()),
            vision_model=self.vision_model_input.text().strip(),
            image_size=str(self.image_size_combo.currentData()),
            resolution=str(self.evolink_resolution_combo.currentData()),
            quality=str(self.quality_combo.currentData()),
        )

    @Slot()
    def close_system_settings(self) -> None:
        self.settings_panel.hide()

    @Slot()
    def save_system_settings(self) -> None:
        settings = self._settings_from_controls()
        path = write_evolink_settings(settings)
        self.current_key_label.setText(mask_secret(settings.api_key))
        self.settings_status_label.setText(f"已保存：{path}")
        self.statusBar().showMessage(f"系统设置已保存：{path}；Key：{mask_secret(settings.api_key)}")

    @Slot()
    def test_system_settings_connection(self) -> None:
        api_key = self.api_key_input.text().strip()
        if not api_key:
            self.settings_status_label.setText("请先填写 Evolink Key。")
            return
        if self._connectivity_worker and self._connectivity_worker.isRunning():
            return
        self.test_connection_button.setEnabled(False)
        self.settings_status_label.setText("正在测试连接...")
        self._connectivity_worker = EvolinkConnectivityWorker(api_key, self.base_url_input.text().strip(), parent=self)
        self._connectivity_worker.finished.connect(self.on_connection_test_finished)
        self._connectivity_worker.failed.connect(self.on_connection_test_failed)
        self._connectivity_worker.start()

    @Slot(str)
    def on_connection_test_finished(self, base_url: str) -> None:
        self.test_connection_button.setEnabled(True)
        self.settings_status_label.setText(f"连接成功：{base_url}")
        self.statusBar().showMessage("Evolink 连接测试成功")

    @Slot(str)
    def on_connection_test_failed(self, message: str) -> None:
        self.test_connection_button.setEnabled(True)
        self.settings_status_label.setText(f"连接失败：{message}")
        self.statusBar().showMessage("Evolink 连接测试失败")

    @Slot(bool)
    def toggle_api_key_visibility(self, checked: bool) -> None:
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
        self.toggle_key_button.setIcon(_visibility_icon(checked))
        self.toggle_key_button.setToolTip("隐藏 Key" if checked else "显示 Key")

    @Slot()
    def convert_image_folder_to_editable_pptx(self) -> None:
        if self._editable_pptx_worker and self._editable_pptx_worker.isRunning():
            QMessageBox.information(self, "AI editable PPTX", "AI 可编辑 PPTX 正在生成，请等待当前任务完成。")
            return
        prepared = self._prepare_editable_pptx_inputs()
        if prepared is None:
            return
        image_paths, output_path, sidecar = prepared
        settings = self._settings_from_controls()
        write_evolink_settings(settings)
        background_mode = "generated"
        if settings.editable_pptx_engine == "gorden-four-layer":
            background_label, accepted = QInputDialog.getItem(
                self,
                "Background mode",
                "背景模式",
                ("generated - Evolink 生成干净背景", "blank - 跳过背景生图，使用空白背景"),
                0,
                False,
            )
            if not accepted:
                return
            background_mode = "blank" if background_label.startswith("blank") else "generated"
        self._editable_pptx_worker = EditablePptxWorker(
            image_paths,
            output_path,
            text_sidecar=sidecar,
            background_mode=background_mode,
            parent=self,
        )
        self._editable_pptx_worker.progress.connect(self.on_editable_pptx_progress)
        self._editable_pptx_worker.finished.connect(self.on_editable_pptx_finished)
        self._editable_pptx_worker.failed.connect(self.on_editable_pptx_failed)
        self._show_editable_pptx_progress(f"准备生成 AI 可编辑 PPTX：{output_path}")
        self._editable_pptx_worker.start()
        self._update_action_states()
        if settings.editable_pptx_engine == "gorden-four-layer":
            self.statusBar().showMessage(
                f"正在生成 Gorden 四层可编辑 PPTX，背景模式：{background_mode}，输出：{output_path}"
            )
        else:
            self.statusBar().showMessage(f"正在使用 Image-to-Editable-PPT CLI 生成可编辑 PPTX，输出：{output_path}")

    def _prepare_editable_pptx_inputs(self) -> tuple[list[Path], Path, Path | None] | None:
        if self.session is not None and self.session.pages:
            source_path = self.session.source_pptx
            image_paths = [page.current_image_path for page in self.session.pages]
            output_path = default_editable_pptx_output_path(source_path.parent, source_path.stem)
            sidecar = source_path.parent / "editable_texts.json"
            return image_paths, output_path, sidecar if sidecar.exists() else None

        image_dir = QFileDialog.getExistingDirectory(self, "Select image folder")
        if not image_dir:
            return None
        source_dir = Path(image_dir)
        try:
            image_paths = _collect_image_paths(source_dir)
        except Exception as exc:
            QMessageBox.critical(self, "Image scan failed", str(exc))
            return None
        if not image_paths:
            QMessageBox.warning(self, "No images", "所选文件夹中没有支持的图片文件。")
            return None
        output_path = default_editable_pptx_output_path(source_dir)
        sidecar = source_dir / "editable_texts.json"
        return image_paths, output_path, sidecar if sidecar.exists() else None

    def _show_editable_pptx_progress(self, message: str) -> None:
        self._ai_progress_label.setText(message)
        self._ai_progress_label.show()
        self._ai_progress_bar.show()
        if self._editable_pptx_progress_dialog is not None:
            self._editable_pptx_progress_dialog.close()
        dialog = QProgressDialog(message, "", 0, 0, self)
        dialog.setWindowTitle("正在生成 AI 可编辑 PPTX")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        dialog.show()
        self._editable_pptx_progress_dialog = dialog

    def _close_editable_pptx_progress(self) -> None:
        self._ai_progress_label.hide()
        self._ai_progress_bar.hide()
        if self._editable_pptx_progress_dialog is not None:
            self._editable_pptx_progress_dialog.close()
            self._editable_pptx_progress_dialog = None

    @Slot(str)
    def on_editable_pptx_progress(self, message: str) -> None:
        self._ai_progress_label.setText(message)
        self._ai_progress_label.show()
        self._ai_progress_bar.show()
        if self._editable_pptx_progress_dialog is not None:
            self._editable_pptx_progress_dialog.setLabelText(message)
        self.statusBar().showMessage(message)

    @Slot(object)
    def on_editable_pptx_finished(self, result) -> None:
        self._close_editable_pptx_progress()
        editable_pptx_action = self._toolbar_actions.get("folder_to_editable_pptx_action")
        if editable_pptx_action is not None:
            editable_pptx_action.setEnabled(True)
        self.statusBar().showMessage(f"已生成可编辑 PPTX：{result.pptx_path}；运行目录：{result.run_root}")
        QMessageBox.information(
            self,
            "Editable PPTX complete",
            f"已生成：\n{result.pptx_path}\n\n中间文件：\n{result.run_root}",
        )

    @Slot(str)
    def on_editable_pptx_failed(self, message: str) -> None:
        self._close_editable_pptx_progress()
        editable_pptx_action = self._toolbar_actions.get("folder_to_editable_pptx_action")
        if editable_pptx_action is not None:
            editable_pptx_action.setEnabled(True)
        QMessageBox.critical(self, "Editable PPTX failed", message)
        self.statusBar().showMessage("可编辑 PPTX 生成失败")

    def load_project(self, source_path: Path) -> None:
        source_type = "pdf" if source_path.suffix.lower() == ".pdf" else "pptx"
        session_dir = create_session_dir(source_name=source_path.stem)
        self.session = ProjectSession(source_pptx=source_path, session_dir=session_dir, source_type=source_type)
        output_width = self._selected_output_width()
        unit = "pages" if source_type == "pdf" else "slides"
        self.statusBar().showMessage(f"Converting {unit} at {output_width}px wide...")
        self._convert_worker = ConvertWorker(source_path, session_dir / "pages", width=output_width, parent=self)
        self._convert_worker.finished.connect(self.on_conversion_finished)
        self._convert_worker.failed.connect(self.on_conversion_failed)
        self._convert_worker.start()
        self._update_action_states()

    def load_images(self, image_paths: list[Path]) -> None:
        source_name = image_paths[0].stem if len(image_paths) == 1 else "images"
        session_dir = create_session_dir(source_name=source_name)
        self.session = ProjectSession(source_pptx=image_paths[0], session_dir=session_dir, source_type="image")
        try:
            self.session.set_pages(image_paths)
        except Exception as exc:
            QMessageBox.critical(self, "Image import failed", str(exc))
            self.statusBar().showMessage("Image import failed")
            return
        self.thumbnails.set_pages([page.thumbnail_path for page in self.session.pages])
        if self.session.pages:
            self.thumbnails.setCurrentRow(0)
            self.canvas.set_image(str(self.session.pages[0].current_image_path))
            self._restore_page_selection()
        self._update_action_states()
        self.statusBar().showMessage(f"Loaded {len(self.session.pages)} image(s)")

    def _selected_output_width(self) -> int:
        return read_evolink_settings().document_width

    @Slot(list, dict)
    def on_conversion_finished(self, page_paths: list[Path], metadata: dict) -> None:
        if self.session is None:
            return
        self.session.set_pages([Path(p) for p in page_paths])
        self.thumbnails.set_pages([page.thumbnail_path for page in self.session.pages])
        if self.session.pages:
            self.thumbnails.setCurrentRow(0)
            self.canvas.set_image(str(self.session.pages[0].current_image_path))
            self._restore_page_selection()
        self._update_action_states()
        self.statusBar().showMessage(
            f"Loaded {metadata.get('slide_count', metadata.get('page_count', len(page_paths)))} pages at "
            f"{metadata.get('output_width')}x{metadata.get('output_height')}"
        )

    @Slot(str)
    def on_conversion_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Conversion failed", message)
        self.statusBar().showMessage("Conversion failed")
        self._update_action_states()

    @Slot(int)
    def set_page_index(self, index: int) -> None:
        if self.session is None:
            return
        if 0 <= index < len(self.session.pages):
            self.session.current_page_index = index
            self.canvas.set_image(str(self.session.pages[index].current_image_path))
            self._restore_page_selection()

    def _restore_page_selection(self) -> None:
        if self.session is None or self.session.current_page is None:
            self.canvas.clear_selection()
            return
        page = self.session.current_page
        if not page.selection_rects:
            self.canvas.clear_selection()
            return
        self.canvas.set_selection_rects([self._rect_to_qrectf(rect) for rect in page.selection_rects])

    @staticmethod
    def _rect_to_qrectf(rect: tuple[int, int, int, int]):
        from PySide6.QtCore import QRectF

        left, top, right, bottom = rect
        return QRectF(left, top, right - left + 1, bottom - top + 1)

    @Slot(object)
    def on_selection_made(self, rect) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        try:
            from PIL import Image
        except ImportError:
            QMessageBox.critical(self, "Missing dependency", "Pillow is required to create selection masks.")
            return
        with Image.open(page.current_image_path) as image:
            width, height = image.size
        qrect = rect.toRect()
        left = max(0, min(width - 1, qrect.left()))
        top = max(0, min(height - 1, qrect.top()))
        right = max(0, min(width - 1, qrect.right()))
        bottom = max(0, min(height - 1, qrect.bottom()))
        current_rect = (left, top, right, bottom)
        if current_rect not in page.selection_rects:
            page.selection_rects.append(current_rect)
        create_rect_mask_from_rects(page.mask_path, (width, height), page.selection_rects)
        self.statusBar().showMessage(f"Selected region {left},{top} - {right},{bottom}")

    @Slot()
    def on_selection_cleared(self) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        page.selection_rects.clear()
        page.mask_path.unlink(missing_ok=True)
        self.statusBar().showMessage("选区已取消")

    @Slot()
    def copy_selection(self) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        if not page.selection_rects:
            self.statusBar().showMessage("请先框选区域再复制")
            return
        try:
            from PIL import Image
        except ImportError:
            QMessageBox.critical(self, "Missing dependency", "Pillow is required to copy selection content.")
            return
        self._clipboard = []
        with Image.open(page.current_image_path) as image:
            for rect in page.selection_rects:
                left, top, right, bottom = rect
                region = image.crop((left, top, right + 1, bottom + 1))
                self._clipboard.append((region.copy(), rect))
        self.statusBar().showMessage(f"已复制 {len(self._clipboard)} 个选区")

    @Slot()
    def paste_clipboard(self) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        if not self._clipboard:
            self.statusBar().showMessage("剪贴板为空，请先复制选区")
            return
        try:
            from PIL import Image
        except ImportError:
            QMessageBox.critical(self, "Missing dependency", "Pillow is required to paste selection content.")
            return
        with Image.open(page.base_image_path) as image:
            width, height = image.size
        snapshot = (
            self.session.session_dir
            / "history"
            / f"page_{page.index:03d}_undo_{len(page.history.undo_stack):03d}.png"
        )
        self._snapshot_page_state(page, snapshot)
        page.history.push(snapshot)
        page.objects_dir.mkdir(parents=True, exist_ok=True)
        pasted_rects: list[tuple[int, int, int, int]] = []
        try:
            for region, source_rect in self._clipboard:
                offset = (24, 24) if not page.selection_rects else (0, 0)
                if page.selection_rects:
                    anchor = page.selection_rects[0]
                    offset = (anchor[0] - source_rect[0], anchor[1] - source_rect[1])
                target_left = source_rect[0] + offset[0]
                target_top = source_rect[1] + offset[1]
                target_right = target_left + (source_rect[2] - source_rect[0])
                target_bottom = target_top + (source_rect[3] - source_rect[1])
                paste_x0 = max(0, target_left)
                paste_y0 = max(0, target_top)
                paste_x1 = min(width, target_right + 1)
                paste_y1 = min(height, target_bottom + 1)
                if paste_x1 <= paste_x0 or paste_y1 <= paste_y0:
                    continue
                src_x0 = paste_x0 - target_left
                src_y0 = paste_y0 - target_top
                piece = region.crop(
                    (src_x0, src_y0, src_x0 + (paste_x1 - paste_x0), src_y0 + (paste_y1 - paste_y0))
                )
                object_id = page.next_object_id
                object_path = page.objects_dir / f"obj_{object_id:03d}.png"
                piece.save(object_path, format="PNG")
                page.objects.append(
                    PastedObject(image_path=object_path, bbox=(paste_x0, paste_y0, paste_x1 - 1, paste_y1 - 1))
                )
                pasted_rects.append((paste_x0, paste_y0, paste_x1 - 1, paste_y1 - 1))
            compose_page(page)
        except Exception as exc:
            QMessageBox.critical(self, "Paste failed", str(exc))
            return
        page.selection_rects = pasted_rects
        if pasted_rects:
            create_rect_mask_from_rects(page.mask_path, (width, height), page.selection_rects)
        self._dirty = True
        self.canvas.set_image(str(page.current_image_path), preserve_view=True)
        self._restore_page_selection()
        self.statusBar().showMessage(f"已粘贴 {len(pasted_rects)} 个选区")

    @Slot()
    def insert_text(self) -> None:
        if self.session is None or self.session.current_page is None:
            self.statusBar().showMessage("请先打开图片再插入文本")
            return
        text, accepted = QInputDialog.getText(self, "插入文本", "请输入文本内容:")
        if not accepted or not text.strip():
            return
        self._pending_text = text.strip()
        self.canvas.set_text_mode()
        self.statusBar().showMessage("请在图片上点击要插入文本的位置")

    @Slot(object)
    def on_text_requested(self, scene_pos) -> None:
        if self.session is None or self.session.current_page is None or not self._pending_text:
            return
        page = self.session.current_page
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            QMessageBox.critical(self, "Missing dependency", "Pillow is required to insert text.")
            return
        x = int(round(scene_pos.x()))
        y = int(round(scene_pos.y()))
        snapshot = (
            self.session.session_dir
            / "history"
            / f"page_{page.index:03d}_undo_{len(page.history.undo_stack):03d}.png"
        )
        self._snapshot_page_state(page, snapshot)
        page.history.push(snapshot)
        try:
            with Image.open(page.base_image_path) as image:
                draw = ImageDraw.Draw(image)
                font = _load_text_font(ImageFont, max(18, image.height // 18))
                draw.text((x, y), self._pending_text, fill=(0, 0, 0), font=font)
                image.save(page.base_image_path)
            compose_page(page)
        except Exception as exc:
            QMessageBox.critical(self, "Insert text failed", str(exc))
            return
        self._dirty = True
        self.canvas.set_image(str(page.current_image_path), preserve_view=True)
        self._restore_page_selection()
        self.statusBar().showMessage(f"已在 ({x}, {y}) 插入文本")
        self._pending_text = None

    @Slot(object, object)
    def on_move_made(self, source_rect, target_rect) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        try:
            from PIL import Image
        except ImportError:
            QMessageBox.critical(self, "Missing dependency", "Pillow is required to move selection content.")
            return
        with Image.open(page.base_image_path) as image:
            width, height = image.size
        source = self._scene_rect_to_pixel(source_rect, width, height)
        target = self._scene_rect_to_pixel(target_rect, width, height)
        offset = (target[0] - source[0], target[1] - source[1])
        if offset == (0, 0):
            return
        snapshot = (
            self.session.session_dir
            / "history"
            / f"page_{page.index:03d}_undo_{len(page.history.undo_stack):03d}.png"
        )
        self._snapshot_page_state(page, snapshot)
        page.history.push(snapshot)
        try:
            moved_objects = self._move_pasted_objects(page, source, offset, (width, height))
            if not moved_objects:
                self._move_image_content(page, source, offset, (width, height))
            else:
                compose_page(page)
        except Exception as exc:
            QMessageBox.critical(self, "Move failed", str(exc))
            return
        new_rect = (target[0], target[1], target[2], target[3])
        page.selection_rects.clear()
        if new_rect[2] > new_rect[0] and new_rect[3] > new_rect[1]:
            page.selection_rects.append(new_rect)
            create_rect_mask_from_rects(page.mask_path, (width, height), page.selection_rects)
        self._dirty = True
        self.canvas.set_image(str(page.current_image_path), preserve_view=True)
        self._restore_page_selection()
        self.statusBar().showMessage(f"已移动选区内容 ({offset[0]:+d}, {offset[1]:+d})")

    def _move_pasted_objects(
        self,
        page,
        source: tuple[int, int, int, int],
        offset: tuple[int, int],
        image_size: tuple[int, int],
    ) -> bool:
        left, top, right, bottom = source
        dx, dy = offset
        width, height = image_size
        matched = False
        for obj in page.objects:
            obj_left, obj_top, obj_right, obj_bottom = obj.bbox
            overlap_x = min(right, obj_right) - max(left, obj_left)
            overlap_y = min(bottom, obj_bottom) - max(top, obj_top)
            if overlap_x < 0 or overlap_y < 0:
                continue
            matched = True
            new_left = obj_left + dx
            new_top = obj_top + dy
            new_right = obj_right + dx
            new_bottom = obj_bottom + dy
            new_left_c = max(0, new_left)
            new_top_c = max(0, new_top)
            new_right_c = min(width - 1, new_right)
            new_bottom_c = min(height - 1, new_bottom)
            if new_right_c < new_left_c or new_bottom_c < new_top_c:
                page.objects.remove(obj)
                continue
            try:
                from PIL import Image
            except ImportError:  # pragma: no cover
                raise RuntimeError("Pillow is required to move pasted objects.")
            with Image.open(obj.image_path).convert("RGBA") as source_image:
                cut_left = new_left_c - new_left
                cut_top = new_top_c - new_top
                cut_right = cut_left + (new_right_c - new_left_c + 1)
                cut_bottom = cut_top + (new_bottom_c - new_top_c + 1)
                clipped = source_image.crop((cut_left, cut_top, cut_right, cut_bottom))
            object_id = page.next_object_id
            new_path = page.objects_dir / f"obj_{object_id:03d}.png"
            clipped.save(new_path, format="PNG")
            obj.image_path = new_path
            obj.bbox = (new_left_c, new_top_c, new_right_c, new_bottom_c)
        return matched

    @staticmethod
    def _scene_rect_to_pixel(rect, width: int, height: int) -> tuple[int, int, int, int]:
        from PySide6.QtCore import QRectF

        qrect = QRectF(rect).toRect()
        left = max(0, min(width - 1, qrect.left()))
        top = max(0, min(height - 1, qrect.top()))
        right = max(0, min(width - 1, qrect.right()))
        bottom = max(0, min(height - 1, qrect.bottom()))
        return (left, top, right, bottom)

    def _move_image_content(
        self,
        page,
        source: tuple[int, int, int, int],
        offset: tuple[int, int],
        image_size: tuple[int, int],
    ) -> None:
        from PIL import Image

        width, height = image_size
        left, top, right, bottom = source
        dx, dy = offset
        with Image.open(page.base_image_path) as image:
            content = image.crop((left, top, right + 1, bottom + 1))
        create_rect_mask(page.mask_path, (width, height), source)
        inpaint_file(page.base_image_path, page.mask_path, page.base_image_path)
        target_left = left + dx
        target_top = top + dy
        paste_x0 = max(0, target_left)
        paste_y0 = max(0, target_top)
        paste_x1 = min(width, target_left + (right - left + 1))
        paste_y1 = min(height, target_top + (bottom - top + 1))
        if paste_x1 > paste_x0 and paste_y1 > paste_y0:
            src_x0 = paste_x0 - target_left
            src_y0 = paste_y0 - target_top
            piece = content.crop(
                (
                    src_x0,
                    src_y0,
                    src_x0 + (paste_x1 - paste_x0),
                    src_y0 + (paste_y1 - paste_y0),
                )
            )
            with Image.open(page.base_image_path) as image:
                image.paste(piece, (paste_x0, paste_y0))
                image.save(page.base_image_path)
        compose_page(page)

    @Slot()
    def crop_current_selection(self) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        if len(page.selection_rects) != 1:
            QMessageBox.information(
                self,
                "No single selection",
                "Select exactly one region before cropping.",
            )
            return

        snapshot = (
            self.session.session_dir
            / "history"
            / f"page_{page.index:03d}_undo_{len(page.history.undo_stack):03d}.png"
        )
        self._snapshot_page_state(page, snapshot)
        try:
            crop_width, crop_height = crop_page_to_rect(page, page.selection_rects[0])
        except Exception as exc:
            QMessageBox.critical(self, "Crop failed", str(exc))
            return

        page.history.push(snapshot)
        self._dirty = True
        self.canvas.set_image(str(page.current_image_path))
        self.canvas.clear_selection()
        self.thumbnails.update_page(page.index - 1, page.thumbnail_path)
        self.statusBar().showMessage(f"Cropped page to {crop_width}x{crop_height}")

    @Slot()
    def erase_current_selection(self) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        if not page.selection_rects:
            QMessageBox.information(self, "No selection", "Select a region before erasing.")
            return
        try:
            from PIL import Image
        except ImportError:
            QMessageBox.critical(self, "Missing dependency", "Pillow is required to create selection masks.")
            return
        snapshot = (
            self.session.session_dir
            / "history"
            / f"page_{page.index:03d}_undo_{len(page.history.undo_stack):03d}.png"
        )
        self._snapshot_page_state(page, snapshot)
        page.history.push(snapshot)
        try:
            with Image.open(page.base_image_path) as image:
                image_size = image.size
            for rect in page.selection_rects:
                create_rect_mask(page.mask_path, image_size, rect)
                inpaint_file(page.base_image_path, page.mask_path, page.base_image_path)
            page.objects = [
                obj
                for obj in page.objects
                if not _rect_overlaps_any(obj.bbox, page.selection_rects)
            ]
            compose_page(page)
        except Exception as exc:
            QMessageBox.critical(self, "Erase failed", str(exc))
            return
        page.mask_path.unlink(missing_ok=True)
        page.selection_rects.clear()
        self._dirty = True
        self.canvas.set_image(str(page.current_image_path), preserve_view=True)
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
        self._snapshot_page_state(page, current_snapshot)
        previous = page.history.undo(current_snapshot)
        if previous is None:
            return
        self._restore_page_state(page, previous)
        self._dirty = True
        self.canvas.set_image(str(page.current_image_path), preserve_view=True)
        self._restore_page_selection()
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
        self._snapshot_page_state(page, current_snapshot)
        next_snapshot = page.history.redo(current_snapshot)
        if next_snapshot is None:
            return
        self._restore_page_state(page, next_snapshot)
        self._dirty = True
        self.canvas.set_image(str(page.current_image_path), preserve_view=True)
        self._restore_page_selection()
        self.statusBar().showMessage("Redo complete")

    @staticmethod
    def _snapshot_page_state(page, snapshot: Path) -> None:
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(page.base_image_path, snapshot)
        json_path = Path(str(snapshot)).with_suffix(".png.objects.json")
        payload = [
            {"image_path": str(obj.image_path), "bbox": list(obj.bbox)}
            for obj in page.objects
        ]
        json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _restore_page_state(page, snapshot: Path) -> None:
        shutil.copy2(snapshot, page.base_image_path)
        json_path = Path(str(snapshot)).with_suffix(".png.objects.json")
        page.objects = []
        if json_path.exists():
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            for entry in payload:
                page.objects.append(
                    PastedObject(
                        image_path=Path(entry["image_path"]),
                        bbox=tuple(int(value) for value in entry["bbox"]),
                    )
                )
        compose_page(page)
        update_page_thumbnail(page)

    @Slot()
    def save_project(self) -> None:
        if self.session is None or not self.session.pages:
            QMessageBox.information(self, "Nothing to save", "请先打开文件。")
            return
        page_images = [page.current_image_path for page in self.session.pages]
        try:
            exported = self._save_pages(page_images)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        if exported is not None:
            self._dirty = False
            self.statusBar().showMessage(f"已保存：{exported}")

    @Slot()
    def export_project(self) -> None:
        if self.session is None or not self.session.pages:
            return
        page_images = [page.current_image_path for page in self.session.pages]
        try:
            exported = self._export_pages(page_images)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        if exported is not None:
            self._dirty = False
            self.statusBar().showMessage(f"已导出：{exported}")

    def _begin_busy(self, message: str) -> QProgressDialog | None:
        dialog = QProgressDialog(message, "", 0, 0, self)
        dialog.setWindowTitle("请稍候")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        dialog.show()
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        return dialog

    def _end_busy(self, dialog: QProgressDialog | None) -> None:
        if dialog is not None:
            dialog.close()

    @Slot()
    def export_current_page_transparent(self) -> None:
        if self.session is None or self.session.current_page is None:
            return
        page = self.session.current_page
        default_name = f"{self.session.source_pptx.stem}_transparent.png"
        output_path, _ = QFileDialog.getSaveFileName(self, "Save transparent PNG", default_name, "PNG image (*.png)")
        if not output_path:
            return
        target = Path(output_path)
        if target.suffix.lower() != ".png":
            target = target.with_suffix(".png")
        try:
            exported = export_transparent_image_file(page.current_image_path, target)
        except Exception as exc:
            QMessageBox.critical(self, "Transparent export failed", str(exc))
            return
        self.statusBar().showMessage(f"已导出透明 PNG：{exported}")

    def _save_pages(self, page_images: list[Path]) -> Path | None:
        if self.session is not None and self.session.source_type == "image":
            busy = self._begin_busy("正在保存，请稍后...")
            try:
                return self._save_images_in_place()
            finally:
                self._end_busy(busy)
        if len(page_images) == 1:
            default_name = f"{self.session.source_pptx.stem}_edited.png"
            output_path, _ = QFileDialog.getSaveFileName(self, "保存编辑结果", default_name, "PNG image (*.png)")
            if not output_path:
                return None
            target = Path(output_path)
            if target.suffix.lower() != ".png":
                target = target.with_suffix(".png")
            busy = self._begin_busy("正在保存，请稍后...")
            try:
                return export_image_file(page_images[0], target)
            finally:
                self._end_busy(busy)

        output_dir = QFileDialog.getExistingDirectory(self, "保存编辑结果到文件夹")
        if not output_dir:
            return None
        busy = self._begin_busy("正在保存，请稍后...")
        try:
            return export_images_folder(page_images, Path(output_dir))
        finally:
            self._end_busy(busy)

    def _save_images_in_place(self) -> Path | None:
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover
            raise RuntimeError("Pillow is required to save image files.")

        saved: list[Path] = []
        for page in self.session.pages:
            original = Path(page.original_image_path)
            current = page.current_image_path
            if not original.exists() or original.resolve() == current.resolve():
                continue
            with Image.open(current) as image:
                image.save(original)
            saved.append(original)
        if not saved:
            return None
        return saved[0] if len(saved) == 1 else saved[0].parent

    def _export_pages(self, page_images: list[Path]) -> Path | None:
        if self.session is None:
            return None
        if self.session.source_type in DOCUMENT_SOURCE_TYPES:
            export_format, accepted = QInputDialog.getItem(
                self,
                "Export format",
                "导出格式",
                ("PPTX", "PPT", "图片"),
                0,
                False,
            )
            if not accepted:
                return None
            if export_format == "图片":
                output_dir = QFileDialog.getExistingDirectory(self, "Export images to folder")
                if not output_dir:
                    return None
                busy = self._begin_busy("正在导出，请稍后...")
                try:
                    return export_images_folder(page_images, Path(output_dir))
                finally:
                    self._end_busy(busy)

            default_name = f"{self.session.source_pptx.stem}_edited.{export_format.lower()}"
            file_filter = "PowerPoint PPTX (*.pptx)" if export_format == "PPTX" else "PowerPoint 97-2003 (*.ppt)"
            output_path, _ = QFileDialog.getSaveFileName(self, "Export", default_name, file_filter)
            if not output_path:
                return None
            target = Path(output_path)
            busy = self._begin_busy("正在导出，请稍后...")
            try:
                if export_format == "PPT":
                    return export_image_ppt(page_images, target.with_suffix(".ppt"))
                return export_image_pptx(page_images, target.with_suffix(".pptx"))
            finally:
                self._end_busy(busy)

        if len(page_images) == 1:
            default_name = f"{self.session.source_pptx.stem}_edited.png"
            output_path, _ = QFileDialog.getSaveFileName(self, "Save image", default_name, "PNG image (*.png)")
            if not output_path:
                return None
            target = Path(output_path)
            if target.suffix.lower() != ".png":
                target = target.with_suffix(".png")
            busy = self._begin_busy("正在导出，请稍后...")
            try:
                return export_image_file(page_images[0], target)
            finally:
                self._end_busy(busy)

        export_format, accepted = QInputDialog.getItem(
            self,
            "Export format",
            "导出格式",
            ("PPTX", "图片"),
            0,
            False,
        )
        if not accepted:
            return None
        if export_format == "PPTX":
            default_name = f"{self.session.source_pptx.stem}_edited.pptx"
            output_path, _ = QFileDialog.getSaveFileName(
                self, "Export", default_name, "PowerPoint PPTX (*.pptx)"
            )
            if not output_path:
                return None
            target = Path(output_path).with_suffix(".pptx")
            busy = self._begin_busy("正在导出，请稍后...")
            try:
                return export_image_pptx(page_images, target)
            finally:
                self._end_busy(busy)

        output_dir = QFileDialog.getExistingDirectory(self, "Export images to folder")
        if not output_dir:
            return None
        busy = self._begin_busy("正在导出，请稍后...")
        try:
            return Path(export_pngs(page_images, Path(output_dir))[-1]).parent
        finally:
            self._end_busy(busy)

    def closeEvent(self, event) -> None:
        if self._dirty and self.session is not None and self.session.pages:
            reply = QMessageBox.question(
                self,
                "未保存的修改",
                "当前有未保存的修改，确定退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._close_editable_pptx_progress()
        if self._convert_worker and self._convert_worker.isRunning():
            self._convert_worker.quit()
            self._convert_worker.wait(1000)
        if self._editable_pptx_worker and self._editable_pptx_worker.isRunning():
            self._editable_pptx_worker.quit()
            self._editable_pptx_worker.wait(1000)
        if self._connectivity_worker and self._connectivity_worker.isRunning():
            self._connectivity_worker.quit()
            self._connectivity_worker.wait(1000)
        super().closeEvent(event)


def _load_text_font(ImageFont, size: int):
    for candidate in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _help_html() -> str:
    return (
        "<h2>幻灯片清痕 · 使用帮助</h2>"
        "<h3>一、导入文件</h3>"
        "<ul>"
        "<li>点击顶部 <b>打开文件</b>，选择 PPTX/PDF 或一张/多张图片。</li>"
        "<li>点击 <b>打开文件夹</b>，一次性加载文件夹内所有图片。</li>"
        "<li>打开 PPTX/PDF 时会自动按页转换为图片；打开图片会直接进入编辑。</li>"
        "</ul>"
        "<h3>二、擦除内容</h3>"
        "<ol>"
        "<li>点击底部 <b>框选区域</b>，在页面上拖拽框选需要擦除的区域。</li>"
        "<li>按住 <b>Shift</b> 可框选多个区域；左键单击可取消所有选区。</li>"
        "<li>点击 <b>擦除选区</b> 执行擦除，原位置会被自动修复填充。</li>"
        "</ol>"
        "<h3>三、移动内容</h3>"
        "<ol>"
        "<li>点击 <b>移动选区</b>，在选框内按住鼠标拖拽可移动选中内容。</li>"
        "<li>也可以用键盘<b>方向键</b>步进移动（Shift+方向键每次 50px，否则 10px）。</li>"
        "<li>移动模式下，左键单击也会取消选区。</li>"
        "</ol>"
        "<h3>四、复制粘贴与文本</h3>"
        "<ul>"
        "<li>框选后按 <b>Ctrl+C</b> 复制选区，<b>Ctrl+V</b> 粘贴。</li>"
        "<li>点击 <b>插入文本</b>，输入文字后点击图片任意位置即可插入。</li>"
        "</ul>"
        "<h3>五、撤销与保存</h3>"
        "<ul>"
        "<li><b>Ctrl+Z</b> 撤销，<b>Ctrl+S</b> 保存（图片直接覆盖原图，保留原格式）。</li>"
        "<li>点击 <b>导出</b> 可导出为 PNG、PDF、图片版 PPTX/PPT。</li>"
        "<li>关闭窗口时若存在未保存的修改，程序会提示确认。</li>"
        "</ul>"
        "<h3>六、快捷键速查</h3>"
        "<table border='1' cellpadding='4' cellspacing='0'>"
        "<tr><th>快捷键</th><th>功能</th></tr>"
        "<tr><td>Ctrl+1</td><td>框选区域</td></tr>"
        "<tr><td>Ctrl+2</td><td>移动选区</td></tr>"
        "<tr><td>Ctrl+C / Ctrl+V</td><td>复制 / 粘贴选区</td></tr>"
        "<tr><td>Delete</td><td>擦除选区</td></tr>"
        "<tr><td>Ctrl+Z</td><td>撤销</td></tr>"
        "<tr><td>Ctrl+S</td><td>保存</td></tr>"
        "<tr><td>Ctrl+E</td><td>导出</td></tr>"
        "<tr><td>Alt+Left / Alt+Right</td><td>上一张 / 下一张</td></tr>"
        "<tr><td>Ctrl+Shift+T</td><td>展开/收起下方编辑工具</td></tr>"
        "<tr><td>F1</td><td>打开本帮助</td></tr>"
        "</table>"
        "<p>提示：按住 <b>Ctrl+滚轮</b> 缩放画布，按住 <b>鼠标右键</b> 拖动可平移画布，右键按住选框可快速移动选中内容。</p>"
    )


def _natural_sort_key(path: Path) -> tuple[object, ...]:
    parts = re.split(r"(\d+)", path.name.casefold())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _rect_overlaps_any(rect: tuple[int, int, int, int], rects: list) -> bool:
    left, top, right, bottom = rect
    for other in rects:
        o_left, o_top, o_right, o_bottom = other
        if min(right, o_right) >= max(left, o_left) and min(bottom, o_bottom) >= max(top, o_top):
            return True
    return False


def _collect_image_paths(image_dir: Path) -> list[Path]:
    if not image_dir.is_dir():
        raise ValueError(f"image folder does not exist: {image_dir}")
    return sorted(
        (path for path in image_dir.iterdir() if path.is_file() and is_supported_image_path(path)),
        key=_natural_sort_key,
    )


def _set_combo_value(combo: QComboBox, value: object) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


def _visibility_icon(visible: bool) -> QIcon:
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#52606d")
    painter.setPen(QPen(color, 1.8))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(3, 6, 14, 8)
    painter.setBrush(QBrush(color))
    painter.drawEllipse(8, 8, 4, 4)
    if visible:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(4, 16, 16, 4)
    painter.end()
    return QIcon(pixmap)
