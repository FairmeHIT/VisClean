from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np


SUPPORTED_IMAGE_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".jfif",
        ".gif",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
    }
)


def is_supported_image_path(path: Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def save_image_as_png(source_path: Path, target_path: Path) -> Path:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required to import image files.") from exc

    try:
        with Image.open(source_path) as image:
            normalized = ImageOps.exif_transpose(image)
            if normalized.mode not in ("RGB", "RGBA"):
                normalized = normalized.convert("RGBA" if "A" in normalized.getbands() else "RGB")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            normalized.save(target_path, format="PNG")
    except UnidentifiedImageError as exc:
        raise ValueError(f"Unsupported or invalid image file: {source_path}") from exc
    return target_path


def remove_white_background(image, threshold: int = 250):
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required to process image files.") from exc

    normalized = ImageOps.exif_transpose(image).convert("RGBA")
    data = np.array(normalized)
    white_mask = np.all(data[:, :, :3] >= threshold, axis=2)
    if white_mask.any():
        data[white_mask, 3] = 0
    return Image.fromarray(data, "RGBA")


def create_rect_mask_from_rects(
    mask_path: Path,
    size: tuple[int, int],
    rects: Iterable[tuple[int, int, int, int]],
) -> Path:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required to create mask images.") from exc

    width, height = size
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for left, top, right, bottom in rects:
        draw.rectangle((left, top, right, bottom), fill=255)
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(mask_path)
    return mask_path


def create_rect_mask(mask_path: Path, size: tuple[int, int], rect: tuple[int, int, int, int]) -> Path:
    return create_rect_mask_from_rects(mask_path, size, (rect,))


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
