from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, QThread

from app.core.editppt_cli_adapter import convert_images_with_editppt_cli
from app.core.editable_pptx import EvolinkImageLayerGenerator, SidecarTextExtractor, convert_images_to_editable_pptx
from app.core.settings import read_evolink_settings
from app.core.vision_icon_locator import LLMIconLocator
from app.core.vision_text_extractor import LLMTextExtractor


class EditablePptxWorker(QThread):
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        image_paths: list[Path],
        output_path: Path,
        text_sidecar: Path | None = None,
        background_mode: str = "generated",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.image_paths = [Path(path) for path in image_paths]
        self.output_path = Path(output_path)
        self.text_sidecar = Path(text_sidecar) if text_sidecar is not None else None
        self.background_mode = background_mode

    def run(self) -> None:  # pragma: no cover
        try:
            self.progress.emit("正在读取 AI 可编辑 PPTX 设置...")
            settings = read_evolink_settings()
            if settings.editable_pptx_engine == "editppt-cli":
                result = convert_images_with_editppt_cli(
                    self.image_paths,
                    self.output_path,
                    progress_callback=self.progress.emit,
                )
                self.finished.emit(result)
                return

            extractor = (
                SidecarTextExtractor(self.text_sidecar)
                if self.text_sidecar is not None
                else LLMTextExtractor(model=settings.vision_model)
            )
            icon_locator = LLMIconLocator(model=settings.vision_model)
            generator = EvolinkImageLayerGenerator(
                image_size=settings.image_size,
                resolution=settings.resolution,
                quality=settings.quality,
            )
            self.progress.emit("正在准备 AI 分层任务...")
            result = convert_images_to_editable_pptx(
                self.image_paths,
                self.output_path,
                layer_generator=generator,
                text_extractor=extractor,
                icon_locator=icon_locator,
                background_mode=self.background_mode,
                progress_callback=self.progress.emit,
            )
            self.progress.emit("AI 可编辑 PPTX 已生成，正在收尾...")
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
