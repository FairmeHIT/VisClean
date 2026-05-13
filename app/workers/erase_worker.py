from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, QThread

from app.core.image_inpainter import inpaint_file


class EraseWorker(QThread):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        image_path: Path,
        mask_path: Path,
        output_path: Path,
        radius: int = 5,
        algorithm: str = "telea",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.image_path = Path(image_path)
        self.mask_path = Path(mask_path)
        self.output_path = Path(output_path)
        self.radius = radius
        self.algorithm = algorithm

    def run(self) -> None:  # pragma: no cover
        try:
            result = inpaint_file(self.image_path, self.mask_path, self.output_path, self.radius, self.algorithm)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
