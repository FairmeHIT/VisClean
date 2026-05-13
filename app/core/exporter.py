from __future__ import annotations

from pathlib import Path
import shutil


class ExportError(RuntimeError):
    pass


def export_pngs(page_images: list[Path], output_dir: Path) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []
    for index, image_path in enumerate(page_images, start=1):
        target = output_dir / f"page_{index:03d}.png"
        shutil.copy2(image_path, target)
        exported.append(target)
    return exported


def export_pdf(page_images: list[Path], output_path: Path) -> Path:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ExportError("Pillow is required to export PDF files.") from exc

    if not page_images:
        raise ExportError("no pages available for PDF export")

    opened: list[Image.Image] = []
    try:
        for image_path in page_images:
            img = Image.open(image_path).convert("RGB")
            opened.append(img)
        first, rest = opened[0], opened[1:]
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        first.save(output_path, "PDF", save_all=True, append_images=rest)
        return output_path
    finally:
        for img in opened:
            img.close()


def export_image_pptx(page_images: list[Path], output_path: Path, slide_size: tuple[int, int] | None = None) -> Path:
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover
        raise ExportError("python-pptx is required to export PPTX files.") from exc

    if not page_images:
        raise ExportError("no pages available for PPTX export")

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ExportError("Pillow is required to inspect page sizes.") from exc

    from pptx.util import Inches

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(page_images[0]) as first_image:
        width_px, height_px = first_image.size

    if slide_size is None:
        slide_size = (width_px, height_px)

    prs = Presentation()
    aspect = slide_size[1] / slide_size[0]
    prs.slide_width = Inches(13.3333333333)
    prs.slide_height = Inches(13.3333333333 * aspect)
    blank_layout = prs.slide_layouts[6]

    for image_path in page_images:
        slide = prs.slides.add_slide(blank_layout)
        slide.shapes.add_picture(str(image_path), 0, 0, width=prs.slide_width, height=prs.slide_height)

    prs.save(output_path)
    return output_path
