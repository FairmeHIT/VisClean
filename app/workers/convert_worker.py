from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, QThread

from app.core.pptx_converter import export_pptx_to_png


class ConvertWorker(QThread):
    finished = Signal(list, dict)
    failed = Signal(str)

    def __init__(self, pptx_path: Path, output_dir: Path, width: int = 1920, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pptx_path = Path(pptx_path)
        self.output_dir = Path(output_dir)
        self.width = width

    def run(self) -> None:  # pragma: no cover
        try:
            page_paths, metadata = export_pptx_to_png(self.pptx_path, self.output_dir, self.width)
            self.finished.emit(page_paths, metadata)
        except Exception as exc:
            self.failed.emit(str(exc))
