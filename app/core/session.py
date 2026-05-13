from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.core.history import HistoryStack


@dataclass
class SlidePage:
    index: int
    original_image_path: Path
    current_image_path: Path
    mask_path: Path
    thumbnail_path: Path
    history: HistoryStack = field(default_factory=HistoryStack)


@dataclass
class ProjectSession:
    source_pptx: Path
    session_dir: Path
    pages: list[SlidePage] = field(default_factory=list)
    current_page_index: int = 0

    @property
    def current_page(self) -> SlidePage | None:
        if not self.pages:
            return None
        if self.current_page_index < 0 or self.current_page_index >= len(self.pages):
            return None
        return self.pages[self.current_page_index]

    def set_pages(self, page_images: list[Path]) -> None:
        self.pages = []
        edits_dir = self.session_dir / "edits"
        masks_dir = self.session_dir / "masks"
        thumbs_dir = self.session_dir / "thumbnails"
        for directory in (edits_dir, masks_dir, thumbs_dir):
            directory.mkdir(parents=True, exist_ok=True)

        for index, image_path in enumerate(page_images, start=1):
            source_path = Path(image_path)
            page = SlidePage(
                index=index,
                original_image_path=source_path,
                current_image_path=edits_dir / f"page_{index:03d}_current.png",
                mask_path=masks_dir / f"page_{index:03d}_mask.png",
                thumbnail_path=thumbs_dir / f"page_{index:03d}.png",
            )
            page.current_image_path.write_bytes(source_path.read_bytes())
            try:
                from PIL import Image
            except ImportError:
                page.thumbnail_path.write_bytes(source_path.read_bytes())
            else:
                with Image.open(source_path) as image:
                    thumb = image.copy()
                    thumb.thumbnail((240, 240))
                    thumb.save(page.thumbnail_path)
            self.pages.append(page)
        self.current_page_index = 0
