from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.core.history import HistoryStack
from app.utils.image import save_image_as_png


ProjectSourceType = Literal["pptx", "pdf", "image"]


@dataclass
class PastedObject:
    image_path: Path
    bbox: tuple[int, int, int, int]


@dataclass
class SlidePage:
    index: int
    original_image_path: Path
    current_image_path: Path
    base_image_path: Path
    mask_path: Path
    thumbnail_path: Path
    objects_dir: Path
    history: HistoryStack = field(default_factory=HistoryStack)
    selection_rects: list[tuple[int, int, int, int]] = field(default_factory=list)
    objects: list[PastedObject] = field(default_factory=list)

    @property
    def next_object_id(self) -> int:
        existing = [int(p.stem.split("_")[-1]) for p in self.objects_dir.glob("obj_*.png")]
        return (max(existing) + 1) if existing else 1


@dataclass
class ProjectSession:
    source_pptx: Path
    session_dir: Path
    source_type: ProjectSourceType = "pptx"
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
        objects_dir = self.session_dir / "objects"
        for directory in (edits_dir, masks_dir, thumbs_dir, objects_dir):
            directory.mkdir(parents=True, exist_ok=True)

        new_pages: list[SlidePage] = []
        for index, image_path in enumerate(page_images, start=1):
            source_path = Path(image_path)
            page = SlidePage(
                index=index,
                original_image_path=source_path,
                current_image_path=edits_dir / f"page_{index:03d}_current.png",
                base_image_path=edits_dir / f"page_{index:03d}_base.png",
                mask_path=masks_dir / f"page_{index:03d}_mask.png",
                thumbnail_path=thumbs_dir / f"page_{index:03d}.png",
                objects_dir=objects_dir / f"page_{index:03d}",
            )
            save_image_as_png(source_path, page.current_image_path)
            save_image_as_png(source_path, page.base_image_path)
            update_page_thumbnail(page)
            new_pages.append(page)
        self.pages = new_pages
        self.current_page_index = 0


def update_page_thumbnail(page: SlidePage) -> None:
    try:
        from PIL import Image
    except ImportError:
        page.thumbnail_path.write_bytes(page.current_image_path.read_bytes())
        return

    with Image.open(page.current_image_path) as image:
        thumb = image.copy()
        thumb.thumbnail((240, 240))
        thumb.save(page.thumbnail_path)


def crop_page_to_rect(page: SlidePage, rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """Crop a page and keep pasted objects aligned with the new origin."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required to crop pages.") from exc

    with Image.open(page.base_image_path) as image:
        width, height = image.size

    left = max(0, min(width - 1, int(rect[0])))
    top = max(0, min(height - 1, int(rect[1])))
    right = max(0, min(width - 1, int(rect[2])))
    bottom = max(0, min(height - 1, int(rect[3])))
    if right < left or bottom < top:
        raise ValueError("Crop rectangle is empty.")

    crop_box = (left, top, right + 1, bottom + 1)
    with Image.open(page.base_image_path) as image:
        cropped_base = image.crop(crop_box)
    cropped_base.save(page.base_image_path, format="PNG")

    cropped_objects: list[PastedObject] = []
    page.objects_dir.mkdir(parents=True, exist_ok=True)
    for obj in page.objects:
        obj_left, obj_top, obj_right, obj_bottom = obj.bbox
        overlap_left = max(left, obj_left)
        overlap_top = max(top, obj_top)
        overlap_right = min(right, obj_right)
        overlap_bottom = min(bottom, obj_bottom)
        if overlap_right < overlap_left or overlap_bottom < overlap_top:
            continue

        with Image.open(obj.image_path) as overlay:
            overlay_box = (
                overlap_left - obj_left,
                overlap_top - obj_top,
                overlap_right - obj_left + 1,
                overlap_bottom - obj_top + 1,
            )
            cropped_overlay = overlay.crop(overlay_box)
        object_path = page.objects_dir / f"obj_{page.next_object_id:03d}.png"
        cropped_overlay.save(object_path, format="PNG")
        cropped_objects.append(
            PastedObject(
                image_path=object_path,
                bbox=(
                    overlap_left - left,
                    overlap_top - top,
                    overlap_right - left,
                    overlap_bottom - top,
                ),
            )
        )

    page.objects = cropped_objects
    page.selection_rects.clear()
    page.mask_path.unlink(missing_ok=True)
    compose_page(page)
    update_page_thumbnail(page)
    return right - left + 1, bottom - top + 1


def compose_page(page: SlidePage) -> Path:
    """Compose base image + pasted objects into the current display image."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required to compose page layers.") from exc

    with Image.open(page.base_image_path).convert("RGBA") as base:
        canvas = base.copy()
        for obj in page.objects:
            left, top, right, bottom = obj.bbox
            with Image.open(obj.image_path).convert("RGBA") as overlay:
                canvas.paste(overlay, (left, top))
        canvas.convert("RGB").save(page.current_image_path, format="PNG")
    return page.current_image_path
