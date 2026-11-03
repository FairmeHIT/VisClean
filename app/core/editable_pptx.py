from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import re
from typing import Callable, Protocol
from uuid import uuid4

from app.core.evolink import DEFAULT_MODEL, EvolinkClient, EvolinkError
from app.core.settings import DEFAULT_IMAGE_SIZE, DEFAULT_QUALITY, DEFAULT_RESOLUTION


class EditablePptxError(RuntimeError):
    pass


@dataclass(frozen=True)
class EditablePptxTextBox:
    text: str
    source_bbox: tuple[int, int, int, int]
    size_px: int
    color: str = "#000000"
    bold: bool = False
    align: str = "left"
    font_face: str = "Microsoft YaHei"


@dataclass(frozen=True)
class EditablePptxIcon:
    file: Path
    source_bbox: tuple[int, int, int, int] | None = None
    sheet_bbox: tuple[int, int, int, int] | None = None
    cutout_content_bbox: tuple[int, int, int, int] | None = None
    label: str = ""
    confidence: float | None = None


@dataclass(frozen=True)
class ImageLayerSet:
    background: Path
    frame_raw: Path
    icons_raw: list[Path]


@dataclass(frozen=True)
class EditablePptxResult:
    pptx_path: Path
    run_root: Path
    page_dirs: list[Path]


class ImageLayerGenerator(Protocol):
    def generate_background(self, source_image: Path, page_dir: Path, key_color: str) -> Path:
        ...

    def generate_frame(self, source_image: Path, page_dir: Path, key_color: str) -> Path:
        ...

    def generate_icons(self, source_image: Path, page_dir: Path, key_color: str) -> list[Path]:
        ...


class TextExtractor(Protocol):
    def extract_texts(self, source_image: Path) -> list[EditablePptxTextBox]:
        ...


class IconLocator(Protocol):
    def locate_icons(
        self,
        source_image: Path,
        cutouts: list[EditablePptxIcon],
        contact_sheet: Path | None = None,
    ) -> list[EditablePptxIcon]:
        ...


class EmptyTextExtractor:
    def extract_texts(self, source_image: Path) -> list[EditablePptxTextBox]:
        return []


class EmptyIconLocator:
    def locate_icons(
        self,
        source_image: Path,
        cutouts: list[EditablePptxIcon],
        contact_sheet: Path | None = None,
    ) -> list[EditablePptxIcon]:
        return []


class SidecarTextExtractor:
    """Loads optional true text boxes from JSON instead of guessing OCR output."""

    def __init__(self, sidecar_path: Path | str) -> None:
        self.sidecar_path = Path(sidecar_path)

    def extract_texts(self, source_image: Path) -> list[EditablePptxTextBox]:
        if not self.sidecar_path.exists():
            return []
        payload = json.loads(self.sidecar_path.read_text(encoding="utf-8"))
        entries = _sidecar_entries_for_image(payload, Path(source_image).name)
        return [_text_box_from_json(entry) for entry in entries]


class EvolinkImageLayerGenerator:
    backend_name = "evolink-imagegen"

    def __init__(
        self,
        client: EvolinkClient | None = None,
        *,
        model: str = DEFAULT_MODEL,
        image_size: str = DEFAULT_IMAGE_SIZE,
        resolution: str = DEFAULT_RESOLUTION,
        quality: str = DEFAULT_QUALITY,
        poll_interval: float = 8,
        task_timeout: float = 600,
    ) -> None:
        self.client = client or EvolinkClient()
        self.model = model
        self.image_size = image_size
        self.resolution = resolution
        self.quality = quality
        self.poll_interval = poll_interval
        self.task_timeout = task_timeout

    def generate_background(self, source_image: Path, page_dir: Path, key_color: str) -> Path:
        prompts_dir = page_dir / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        background_prompt = prompts_dir / "background.txt"
        background_prompt.write_text(_background_prompt(), encoding="utf-8")
        return self._generate_one(source_image, background_prompt, page_dir / "background.png")

    def generate_frame(self, source_image: Path, page_dir: Path, key_color: str) -> Path:
        prompts_dir = page_dir / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        frame_prompt = prompts_dir / "frame.txt"
        frame_prompt.write_text(_frame_prompt(key_color), encoding="utf-8")
        return self._generate_one(source_image, frame_prompt, page_dir / "frame_raw.png")

    def generate_icons(self, source_image: Path, page_dir: Path, key_color: str) -> list[Path]:
        prompts_dir = page_dir / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        icons_prompt = prompts_dir / "icons.txt"
        icons_prompt.write_text(_icons_prompt(key_color), encoding="utf-8")
        return [self._generate_one(source_image, icons_prompt, page_dir / "icons_raw_1.png", size="1:1")]

    def _generate_one(self, source_image: Path, prompt_path: Path, output_path: Path, *, size: str | None = None) -> Path:
        prompt = prompt_path.read_text(encoding="utf-8")
        try:
            task = self.client.create_image_generation(
                prompt,
                image_paths=[source_image],
                size=size or self._source_size(source_image),
                resolution=self.resolution,
                quality=self.quality,
                n=1,
                model=self.model,
            )
            task_id = str(task.get("id") or task.get("task_id") or "").strip()
            if not task_id:
                raise EditablePptxError(f"Evolink response does not contain a task id: {task}")
            completed = self.client.wait_for_task(
                task_id,
                poll_interval=self.poll_interval,
                timeout=self.task_timeout,
            )
            return self.client.download_first_result(completed, output_path)
        except EvolinkError as exc:
            raise EditablePptxError(str(exc)) from exc

    def _source_size(self, source_image: Path) -> str:
        return _aspect_size(source_image) if self.image_size == "auto" else self.image_size


def convert_images_to_editable_pptx(
    image_paths: list[Path],
    output_path: Path,
    *,
    work_root: Path | None = None,
    layer_generator: ImageLayerGenerator | None = None,
    text_extractor: TextExtractor | None = None,
    icon_locator: IconLocator | None = None,
    background_mode: str = "generated",
    progress_callback: Callable[[str], None] | None = None,
) -> EditablePptxResult:
    if not image_paths:
        raise EditablePptxError("no source images were provided")

    generator = layer_generator or EvolinkImageLayerGenerator()
    extractor = text_extractor or EmptyTextExtractor()
    locator = icon_locator or EmptyIconLocator()
    normalized_background_mode = _normalize_background_mode(background_mode)
    run_root = _create_run_root(image_paths[0], work_root)
    page_dirs: list[Path] = []
    slide_specs: list[dict] = []
    page_count = len(image_paths)

    for index, image_path in enumerate(image_paths, start=1):
        _notify(progress_callback, f"第 {index}/{page_count} 页：正在准备源图片...")
        page_dir = run_root / "editable" / f"{index:02d}"
        page_dir.mkdir(parents=True, exist_ok=True)
        source_copy = page_dir / f"slide-{index:02d}.png"
        _copy_as_png(image_path, source_copy)
        key_color = probe_key_color(source_copy)
        _notify(
            progress_callback,
            f"第 {index}/{page_count} 页：正在生成背景层..."
            if normalized_background_mode == "generated"
            else f"第 {index}/{page_count} 页：正在创建空白背景层...",
        )
        background = (
            generator.generate_background(source_copy, page_dir, key_color)
            if normalized_background_mode == "generated"
            else _create_blank_background(source_copy, page_dir / "background.png")
        )
        _notify(progress_callback, f"第 {index}/{page_count} 页：正在生成框架层...")
        frame_raw = generator.generate_frame(source_copy, page_dir, key_color)
        _notify(progress_callback, f"第 {index}/{page_count} 页：正在生成图标和装饰层...")
        icons_raw = generator.generate_icons(source_copy, page_dir, key_color)
        layers = ImageLayerSet(
            background=background,
            frame_raw=frame_raw,
            icons_raw=icons_raw,
        )
        _notify(progress_callback, f"第 {index}/{page_count} 页：正在整理透明图层...")
        frame = remove_chroma_key(layers.frame_raw, page_dir / "frame.png", key_color)
        icon_layers = [
            remove_chroma_key(icon_raw, page_dir / f"icons_t_{icon_index}.png", key_color)
            for icon_index, icon_raw in enumerate(layers.icons_raw, start=1)
        ]
        _notify(progress_callback, f"第 {index}/{page_count} 页：正在切分图标和装饰元素...")
        icon_cutouts = _slice_icon_layers(icon_layers, page_dir)
        placed_icons: list[EditablePptxIcon] = []
        contact_sheet = page_dir / "icons" / "icons_contact_sheet.png"
        if icon_cutouts:
            _notify(progress_callback, f"第 {index}/{page_count} 页：正在定位图标和装饰元素...")
            placed_icons = [
                icon
                for icon in locator.locate_icons(
                    source_copy,
                    icon_cutouts,
                    contact_sheet if contact_sheet.exists() else None,
                )
                if icon.source_bbox is not None
            ]
        if placed_icons:
            _notify(progress_callback, f"第 {index}/{page_count} 页：已定位 {len(placed_icons)} 个图标/装饰元素。")
        elif icon_cutouts:
            _notify(progress_callback, f"第 {index}/{page_count} 页：未定位到图标位置，保留整页透明图标层作为回退。")
        fallback_icon_layers = [] if placed_icons else icon_layers
        _notify(progress_callback, f"第 {index}/{page_count} 页：正在写入文本和版式信息...")
        texts = extractor.extract_texts(source_copy)
        _write_manifest(page_dir, generator, key_color, layers, normalized_background_mode)
        _write_layout(page_dir, source_copy, layers.background, frame, fallback_icon_layers, placed_icons, texts)
        page_dirs.append(page_dir)
        slide_specs.append(
            {
                "source": source_copy,
                "background": layers.background,
                "frame": frame,
                "icon_layers": fallback_icon_layers,
                "icons": placed_icons,
                "texts": texts,
            }
        )

    _notify(progress_callback, "正在合成 PPTX 文件...")
    pptx_path = Path(output_path).with_suffix(".pptx")
    _compose_pptx(slide_specs, pptx_path)
    _notify(progress_callback, f"已写入 PPTX：{pptx_path}")
    return EditablePptxResult(pptx_path=pptx_path, run_root=run_root, page_dirs=page_dirs)


def _notify(callback: Callable[[str], None] | None, message: str) -> None:
    if callback is not None:
        callback(message)


def probe_key_color(image_path: Path) -> str:
    from PIL import Image

    with Image.open(image_path).convert("RGB") as image:
        width, height = image.size
        sample_step = max(1, math.floor(min(width, height) / 200))
        greenish = 0
        total = 0
        for y in range(0, height, sample_step):
            for x in range(0, width, sample_step):
                r, g, b = image.getpixel((x, y))
                total += 1
                if g > 120 and g > r * 1.3 and g > b * 1.3:
                    greenish += 1
    return "#ff00ff" if total and greenish / total > 0.02 else "#00ff00"


def remove_chroma_key(input_path: Path, output_path: Path, key_color: str = "#00ff00", tolerance: int = 36) -> Path:
    from PIL import Image

    key = _parse_hex_color(key_color)
    with Image.open(input_path).convert("RGBA") as image:
        pixels = []
        for r, g, b, a in image.getdata():
            distance = math.sqrt((r - key[0]) ** 2 + (g - key[1]) ** 2 + (b - key[2]) ** 2)
            pixels.append((r, g, b, 0 if distance <= tolerance else a))
        image.putdata(pixels)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
    return output_path


def _compose_pptx(slide_specs: list[dict], output_path: Path) -> Path:
    try:
        from PIL import Image
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Inches, Pt
    except ImportError as exc:  # pragma: no cover
        raise EditablePptxError("Pillow and python-pptx are required to create editable PPTX files.") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(slide_specs[0]["source"]) as first:
        first_width, first_height = first.size
    prs = Presentation()
    prs.slide_width = Inches(13.3333333333)
    prs.slide_height = Inches(13.3333333333 * first_height / first_width)
    blank = prs.slide_layouts[6]

    for spec in slide_specs:
        with Image.open(spec["source"]) as source:
            source_width, source_height = source.size
        slide = prs.slides.add_slide(blank)
        slide.shapes.add_picture(str(spec["background"]), 0, 0, width=prs.slide_width, height=prs.slide_height)
        slide.shapes.add_picture(str(spec["frame"]), 0, 0, width=prs.slide_width, height=prs.slide_height)
        for icon_layer in spec["icon_layers"]:
            slide.shapes.add_picture(str(icon_layer), 0, 0, width=prs.slide_width, height=prs.slide_height)
        for icon in spec.get("icons", []):
            if icon.source_bbox is None:
                continue
            x, y, width, height = _picture_bbox_for_icon(icon)
            slide.shapes.add_picture(
                str(icon.file),
                int(prs.slide_width * x / source_width),
                int(prs.slide_height * y / source_height),
                int(prs.slide_width * width / source_width),
                int(prs.slide_height * height / source_height),
            )
        for text_box in spec["texts"]:
            x, y, width, height = text_box.source_bbox
            box = slide.shapes.add_textbox(
                int(prs.slide_width * x / source_width),
                int(prs.slide_height * y / source_height),
                int(prs.slide_width * width / source_width),
                int(prs.slide_height * height / source_height),
            )
            frame = box.text_frame
            frame.clear()
            frame.margin_left = 0
            frame.margin_right = 0
            frame.margin_top = 0
            frame.margin_bottom = 0
            paragraph = frame.paragraphs[0]
            paragraph.alignment = {
                "center": PP_ALIGN.CENTER,
                "right": PP_ALIGN.RIGHT,
            }.get(text_box.align, PP_ALIGN.LEFT)
            run = paragraph.add_run()
            run.text = text_box.text
            run.font.name = text_box.font_face
            run.font.size = Pt(max(1, text_box.size_px * (prs.slide_height.inches * 72) / source_height))
            run.font.bold = text_box.bold
            r, g, b = _parse_hex_color(text_box.color)
            run.font.color.rgb = RGBColor(r, g, b)

    prs.save(output_path)
    return output_path


def _picture_bbox_for_icon(icon: EditablePptxIcon) -> tuple[float, float, float, float]:
    if icon.source_bbox is None:
        raise EditablePptxError("icon must include source_bbox before composition")
    x, y, width, height = icon.source_bbox
    if icon.cutout_content_bbox is None:
        return float(x), float(y), float(width), float(height)

    from PIL import Image

    cx, cy, cw, ch = icon.cutout_content_bbox
    if cw <= 0 or ch <= 0:
        return float(x), float(y), float(width), float(height)
    with Image.open(icon.file) as image:
        cutout_width, cutout_height = image.size
    scale_x = width / cw
    scale_y = height / ch
    return (
        x - cx * scale_x,
        y - cy * scale_y,
        cutout_width * scale_x,
        cutout_height * scale_y,
    )


def _create_run_root(source_image: Path, work_root: Path | None) -> Path:
    root = Path(work_root) if work_root is not None else Path.cwd() / "image2pptx_runs"
    root.mkdir(parents=True, exist_ok=True)
    slug = _slugify(Path(source_image).stem) or "image"
    run_root = root / f"editable_{slug}_{uuid4().hex[:8]}"
    run_root.mkdir(parents=False)
    (run_root / "out" / "preview").mkdir(parents=True, exist_ok=True)
    return run_root


def _copy_as_png(source: Path, target: Path) -> Path:
    from PIL import Image

    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.convert("RGB").save(target, format="PNG")
    return target


def _write_manifest(
    page_dir: Path,
    generator: ImageLayerGenerator,
    key_color: str,
    layers: ImageLayerSet,
    background_mode: str,
) -> None:
    backend = getattr(generator, "backend_name", "test-imagegen")
    prompts_dir = page_dir / "prompts"
    assets = [
        _manifest_entry(
            "background",
            layers.background,
            prompts_dir / "background.txt",
            backend if background_mode == "generated" else "blank",
            key_color,
            create_missing_prompt=background_mode == "generated",
        ),
        _manifest_entry("frame", layers.frame_raw, prompts_dir / "frame.txt", backend, key_color),
    ]
    assets.extend(
        _manifest_entry(f"icons_{index}", icon_raw, prompts_dir / "icons.txt", backend, key_color)
        for index, icon_raw in enumerate(layers.icons_raw, start=1)
    )
    (page_dir / "imagegen-assets-manifest.json").write_text(
        json.dumps({"background_mode": background_mode, "assets": assets}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _manifest_entry(
    layer: str,
    path: Path,
    prompt_path: Path,
    backend: str,
    key_color: str,
    *,
    create_missing_prompt: bool = True,
) -> dict:
    if create_missing_prompt and not prompt_path.exists():
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(f"test prompt for {layer}", encoding="utf-8")
    return {
        "layer": layer,
        "backend": backend,
        "generated_source": str(path.resolve()),
        "copied_to": str(path.resolve()),
        "prompt_file": str(prompt_path.resolve()) if prompt_path.exists() else None,
        "key_color": key_color,
    }


def _normalize_background_mode(background_mode: str) -> str:
    value = background_mode.strip().lower()
    if value not in {"generated", "blank"}:
        raise EditablePptxError("background_mode must be 'generated' or 'blank'.")
    return value


def _create_blank_background(source_image: Path, output_path: Path) -> Path:
    from PIL import Image

    with Image.open(source_image) as source:
        Image.new("RGBA", source.size, (255, 255, 255, 0)).save(output_path)
    return output_path


def _slice_icon_layers(icon_layers: list[Path], page_dir: Path) -> list[EditablePptxIcon]:
    icons_dir = page_dir / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    icons: list[EditablePptxIcon] = []
    manifests: list[dict] = []

    for layer_index, icon_layer in enumerate(icon_layers, start=1):
        sliced = slice_icon_sheet(
            icon_layer,
            icons_dir,
            prefix=f"icon_{layer_index}",
        )
        icons.extend(sliced)
        manifests.append(
            {
                "source": icon_layer.name,
                "count": len(sliced),
                "icons": [_icon_to_manifest_json(icons_dir, icon) for icon in sliced],
            }
        )

    (icons_dir / "icons_manifest.json").write_text(
        json.dumps({"layers": manifests}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_icon_contact_sheet(icons, icons_dir / "icons_contact_sheet.png")
    return icons


def slice_icon_sheet(
    icon_layer: Path,
    icons_dir: Path,
    *,
    prefix: str = "icon",
    min_alpha: int = 12,
    pad: int = 16,
    min_side_frac: float = 0.01,
) -> list[EditablePptxIcon]:
    from PIL import Image

    icons_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(icon_layer).convert("RGBA") as image:
        segments = _auto_icon_segments(image, min_alpha=min_alpha, pad=pad, min_side_frac=min_side_frac)
        icons: list[EditablePptxIcon] = []
        for index, segment in enumerate(segments, start=1):
            sheet_bbox, content_bbox = segment
            cutout = image.crop(sheet_bbox)
            file_path = icons_dir / f"{prefix}_{index:03d}.png"
            cutout.save(file_path)
            sx, sy, _sr, _sb = sheet_bbox
            cx, cy, cr, cb = content_bbox
            icons.append(
                EditablePptxIcon(
                    file=file_path,
                    sheet_bbox=sheet_bbox,
                    cutout_content_bbox=(cx - sx, cy - sy, cr - cx, cb - cy),
                )
            )
    return icons


def _auto_icon_segments(
    image,
    *,
    min_alpha: int,
    pad: int,
    min_side_frac: float,
) -> list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise EditablePptxError("numpy is required to slice generated icon sheets.") from exc

    width, height = image.size
    alpha = np.asarray(image.getchannel("A"))
    mask = alpha > min_alpha
    if not bool(mask.any()):
        return []

    row_min_pixels = max(1, int(0.003 * width))
    col_min_pixels = max(1, int(0.003 * height))
    row_gap = max(2, int(0.02 * height))
    col_gap = max(2, int(0.02 * width))
    min_width = max(2, int(min_side_frac * width))
    min_height = max(2, int(min_side_frac * height))

    row_has_content = (mask.sum(axis=1) > row_min_pixels).tolist()
    segments: list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]] = []
    for y0, y1 in _runs(row_has_content, row_gap):
        row_mask = mask[y0:y1]
        col_has_content = (row_mask.sum(axis=0) > col_min_pixels).tolist()
        for x0, x1 in _runs(col_has_content, col_gap):
            sub_mask = row_mask[:, x0:x1]
            ys, xs = np.where(sub_mask)
            if len(xs) == 0 or len(ys) == 0:
                continue
            content_left = x0 + int(xs.min())
            content_right = x0 + int(xs.max()) + 1
            content_top = y0 + int(ys.min())
            content_bottom = y0 + int(ys.max()) + 1
            if (content_right - content_left) < min_width or (content_bottom - content_top) < min_height:
                continue
            sheet_bbox = (
                max(0, content_left - pad),
                max(0, content_top - pad),
                min(width, content_right + pad),
                min(height, content_bottom + pad),
            )
            content_bbox = (content_left, content_top, content_right, content_bottom)
            segments.append((sheet_bbox, content_bbox))

    segments.sort(key=lambda item: (item[0][1], item[0][0]))
    return segments


def _runs(flags: list[bool], min_gap: int) -> list[tuple[int, int]]:
    runs: list[list[int]] = []
    start: int | None = None
    for index, value in enumerate(flags):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append([start, index])
            start = None
    if start is not None:
        runs.append([start, len(flags)])

    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] < min_gap:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [(start, end) for start, end in merged]


def _write_icon_contact_sheet(icons: list[EditablePptxIcon], output_path: Path) -> None:
    if not icons:
        return

    from PIL import Image, ImageDraw, ImageFont

    thumb_width = 220
    thumb_height = 180
    cols = min(4, max(1, len(icons)))
    rows = (len(icons) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_width, rows * thumb_height), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = _load_contact_sheet_font(ImageFont)

    for index, icon in enumerate(icons):
        x = (index % cols) * thumb_width
        y = (index // cols) * thumb_height
        draw.rectangle([x, y, x + thumb_width - 1, y + thumb_height - 1], outline=(180, 180, 180))
        with Image.open(icon.file).convert("RGBA") as image:
            preview = image.copy()
            preview.thumbnail((thumb_width - 24, thumb_height - 48))
            background = Image.new("RGBA", preview.size, (255, 255, 255, 255))
            background.alpha_composite(preview)
        sheet.paste(background.convert("RGB"), (x + (thumb_width - preview.width) // 2, y + 10))
        draw.text((x + 8, y + thumb_height - 30), icon.file.name, fill=(0, 0, 0), font=font)

    sheet.save(output_path)


def _load_contact_sheet_font(ImageFont):
    for candidate in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, 16)
        except Exception:
            pass
    return None


def _icon_to_manifest_json(icons_dir: Path, icon: EditablePptxIcon) -> dict:
    width, height = _image_size(icon.file)
    return {
        "file": icon.file.relative_to(icons_dir).as_posix(),
        "width": width,
        "height": height,
        "aspect": round(width / height, 4) if height else 1,
        "sheet_bbox": list(icon.sheet_bbox) if icon.sheet_bbox is not None else None,
        "cutout_content_bbox": (
            list(icon.cutout_content_bbox) if icon.cutout_content_bbox is not None else None
        ),
    }


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return image.size


def _write_layout(
    page_dir: Path,
    source: Path,
    background: Path,
    frame: Path,
    icon_layers: list[Path],
    icons: list[EditablePptxIcon],
    texts: list[EditablePptxTextBox],
) -> None:
    from PIL import Image

    with Image.open(source) as image:
        width, height = image.size
    layout = {
        "units": "px",
        "ref_width": width,
        "ref_height": height,
        "background": background.name,
        "frame": frame.name,
        "icon_layers": [path.name for path in icon_layers],
        "icon_placement_status": "placed" if icons else ("fallback_full_layer" if icon_layers else "empty"),
        "icons": [_icon_to_layout_json(page_dir, icon) for icon in icons],
        "texts": [
            {
                "text": text.text,
                "source_bbox": list(text.source_bbox),
                "size_px": text.size_px,
                "color": text.color,
                "bold": text.bold,
                "align": text.align,
                "font_face": text.font_face,
            }
            for text in texts
        ],
    }
    (page_dir / "layout.json").write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")


def _icon_to_layout_json(page_dir: Path, icon: EditablePptxIcon) -> dict:
    try:
        file_name = icon.file.relative_to(page_dir).as_posix()
    except ValueError:
        file_name = str(icon.file)
    return {
        "file": file_name,
        "source_bbox": list(icon.source_bbox) if icon.source_bbox is not None else None,
        "sheet_bbox": list(icon.sheet_bbox) if icon.sheet_bbox is not None else None,
        "cutout_content_bbox": (
            list(icon.cutout_content_bbox) if icon.cutout_content_bbox is not None else None
        ),
        "label": icon.label,
        "confidence": icon.confidence,
    }


def _text_box_from_json(entry: dict) -> EditablePptxTextBox:
    bbox = entry.get("source_bbox") or entry.get("bbox")
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        raise EditablePptxError("text sidecar entries must include source_bbox with four numbers")
    return EditablePptxTextBox(
        text=str(entry.get("text", "")),
        source_bbox=tuple(int(value) for value in bbox),
        size_px=int(entry.get("size_px", 18)),
        color=str(entry.get("color", "#000000")),
        bold=bool(entry.get("bold", False)),
        align=str(entry.get("align", "left")),
        font_face=str(entry.get("font_face", "Microsoft YaHei")),
    )


def _sidecar_entries_for_image(payload: dict, image_name: str) -> list[dict]:
    pages = payload.get("pages")
    if isinstance(pages, dict):
        page_payload = pages.get(image_name, [])
        return page_payload.get("texts", []) if isinstance(page_payload, dict) else page_payload
    if isinstance(pages, list):
        match = re.search(r"slide-(\d+)\.png$", image_name)
        if match:
            index = int(match.group(1)) - 1
            if 0 <= index < len(pages):
                page_payload = pages[index]
                return page_payload.get("texts", []) if isinstance(page_payload, dict) else page_payload
    page_payload = payload.get(image_name)
    if page_payload is not None:
        return page_payload.get("texts", []) if isinstance(page_payload, dict) else page_payload
    return payload.get("texts", [])


def _background_prompt() -> str:
    return (
        "Use the input image as the only edit target. Reconstruct a clean background layer for this PPT slide. "
        "Preserve the original canvas size, aspect ratio, base colors, gradients, lighting, shadows, textures, "
        "and large non-structural background decoration. Remove all text, icons, logos, art text, frames, cards, "
        "placeholder blocks, separators, charts, and foreground objects. The result must be a clean background only."
    )


def _frame_prompt(key_color: str) -> str:
    return (
        "Use the input image as the only edit target. Generate one full-slide framework/skeleton image on a "
        f"solid chroma-key background whose exact color is {key_color}. The framework layer means every visual "
        "element in the source except the clean background, ordinary editable text, icons, decorative symbols, "
        "logos, and art text. Include container/card outlines and fills, title bars, dividers, connector lines, "
        "arrows that belong to diagrams, all chart geometry, axes, grids, trend lines, ribbons, data graphics, "
        "and decorative lines or blocks. Preserve original shape, size, position, color, fill, border radius, "
        "and visual style 1:1. Do not include any ordinary text, icon, logo, or art text. Do not invent extra "
        "outline boxes, placeholders, labels, or decorative elements."
    )


def _icons_prompt(key_color: str) -> str:
    return (
        "Use the input image as the only edit target. Extract all standalone icons, decorative symbols, logos, "
        "and art-text elements from this PPT slide into a square icon sheet. "
        f"Use a solid chroma-key background whose exact color is {key_color}. Arrange the extracted elements in "
        "an evenly spaced grid with one element per cell, centered inside its cell, with generous empty padding "
        "around every element so it can be sliced cleanly. Do not draw visible grid lines. Do not include ordinary "
        "editable text, background strips, card fills, panel backgrounds, charts, or framework elements. Preserve "
        "the original colors, shapes, proportions, shadows, and styling of each extracted element."
    )


def _aspect_size(image_path: Path) -> str:
    from PIL import Image

    with Image.open(image_path) as image:
        width, height = image.size
    ratio = width / height
    supported_ratios = (
        ("1:1", 1 / 1),
        ("1:2", 1 / 2),
        ("2:1", 2 / 1),
        ("1:3", 1 / 3),
        ("3:1", 3 / 1),
        ("2:3", 2 / 3),
        ("3:2", 3 / 2),
        ("3:4", 3 / 4),
        ("4:3", 4 / 3),
        ("4:5", 4 / 5),
        ("5:4", 5 / 4),
        ("9:16", 9 / 16),
        ("16:9", 16 / 9),
        ("21:9", 21 / 9),
        ("9:21", 9 / 21),
    )
    nearest, nearest_ratio = min(supported_ratios, key=lambda item: abs(ratio - item[1]))
    if abs(ratio - nearest_ratio) / nearest_ratio <= 0.03:
        return nearest
    if ratio > 3:
        return "3:1"
    if ratio < 1 / 3:
        return "1:3"
    return _custom_pixel_size(width, height)


def _custom_pixel_size(width: int, height: int) -> str:
    min_area = 655_360
    max_area = 8_290_000
    max_edge = 3840
    area = width * height
    scale = 1.0

    if area < min_area:
        scale = math.sqrt(min_area / area)
        out_width = _ceil_multiple(width * scale, 16)
        out_height = _ceil_multiple(height * scale, 16)
    elif area > max_area:
        scale = math.sqrt(max_area / area)
        out_width = _floor_multiple(width * scale, 16)
        out_height = _floor_multiple(height * scale, 16)
    else:
        out_width = _round_multiple(width, 16)
        out_height = _round_multiple(height, 16)

    if max(out_width, out_height) > max_edge:
        scale = max_edge / max(out_width, out_height)
        out_width = _floor_multiple(out_width * scale, 16)
        out_height = _floor_multiple(out_height * scale, 16)

    while out_width * out_height < min_area:
        if out_width <= out_height:
            out_width += 16
        else:
            out_height += 16
    while out_width * out_height > max_area or max(out_width, out_height) > max_edge:
        if out_width >= out_height:
            out_width -= 16
        else:
            out_height -= 16

    return f"{max(16, out_width)}x{max(16, out_height)}"


def _ceil_multiple(value: float, multiple: int) -> int:
    return max(multiple, math.ceil(value / multiple) * multiple)


def _floor_multiple(value: float, multiple: int) -> int:
    return max(multiple, math.floor(value / multiple) * multiple)


def _round_multiple(value: float, multiple: int) -> int:
    return max(multiple, round(value / multiple) * multiple)


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    stripped = value.strip().lstrip("#")
    if len(stripped) != 6:
        raise EditablePptxError(f"invalid hex color: {value}")
    return int(stripped[0:2], 16), int(stripped[2:4], 16), int(stripped[4:6], 16)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return slug[:48]
