from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import tempfile

from app.utils.image import is_supported_image_path, remove_white_background, save_image_as_png


class ExportError(RuntimeError):
    pass


def _natural_sort_key(path: Path) -> tuple[object, ...]:
    parts = re.split(r"(\d+)", path.name.casefold())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def export_pngs(page_images: list[Path], output_dir: Path) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []
    for index, image_path in enumerate(page_images, start=1):
        target = output_dir / f"page_{index:03d}.png"
        shutil.copy2(image_path, target)
        exported.append(target)
    return exported


def export_images_folder(page_images: list[Path], output_root: Path) -> Path:
    exported = export_pngs(page_images, Path(output_root) / "images")
    if not exported:
        raise ExportError("no pages available for image export")
    return exported[0].parent


def export_image_file(image_path: Path, output_path: Path) -> Path:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ExportError("Pillow is required to export image files.") from exc

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as image:
        image.save(output_path, format="PNG")
    return output_path


def export_transparent_image_file(image_path: Path, output_path: Path) -> Path:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ExportError("Pillow is required to export image files.") from exc

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as image:
        transparent = remove_white_background(image)
        transparent.save(output_path, format="PNG")
    return output_path


def export_image_folder_pptx(image_dir: Path, output_path: Path) -> Path:
    image_dir = Path(image_dir)
    if not image_dir.is_dir():
        raise ExportError(f"image folder does not exist: {image_dir}")

    image_paths = sorted(
        (path for path in image_dir.iterdir() if path.is_file() and is_supported_image_path(path)),
        key=_natural_sort_key,
    )
    if not image_paths:
        raise ExportError("no supported images found in the selected folder")

    with tempfile.TemporaryDirectory(prefix="slideclean_images_") as tmp:
        normalized_dir = Path(tmp)
        normalized_paths: list[Path] = []
        for index, image_path in enumerate(image_paths, start=1):
            normalized_path = normalized_dir / f"page_{index:03d}.png"
            normalized_paths.append(save_image_as_png(image_path, normalized_path))
        return export_image_pptx(normalized_paths, output_path)


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


def export_image_ppt(page_images: list[Path], output_path: Path, slide_size: tuple[int, int] | None = None) -> Path:
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:  # pragma: no cover
        raise ExportError("pywin32 is required on Windows to export PPT files.") from exc

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_pptx = tempfile.mkstemp(prefix=f"{output_path.stem}_", suffix=".pptx", dir=output_path.parent)
    os.close(fd)
    pptx_path = Path(temp_pptx)
    export_image_pptx(page_images, pptx_path, slide_size=slide_size)

    pythoncom.CoInitialize()
    app = None
    presentation = None
    try:
        app = win32com.client.DispatchEx("PowerPoint.Application")
        presentation = app.Presentations.Open(str(pptx_path.resolve()), ReadOnly=0, Untitled=0, WithWindow=False)
        presentation.SaveAs(str(output_path.resolve()), 1)
        return output_path
    except Exception as exc:  # pragma: no cover
        raise ExportError(f"failed to export PPT: {exc}") from exc
    finally:
        if presentation is not None:
            try:
                presentation.Close()
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()
        pptx_path.unlink(missing_ok=True)
