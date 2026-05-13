from __future__ import annotations

from pathlib import Path
from typing import Iterable


def create_rect_mask(mask_path: Path, size: tuple[int, int], rect: tuple[int, int, int, int]) -> Path:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required to create mask images.") from exc

    width, height = size
    left, top, right, bottom = rect
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((left, top, right, bottom), fill=255)
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(mask_path)
    return mask_path


def pil_sizes(image_paths: Iterable[Path]) -> list[tuple[int, int]]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required to inspect image sizes.") from exc

    sizes: list[tuple[int, int]] = []
    for path in image_paths:
        with Image.open(path) as img:
            sizes.append(img.size)
    return sizes

