import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.core.editable_pptx import (
    EditablePptxIcon,
    EditablePptxTextBox,
    EvolinkImageLayerGenerator,
    ImageLayerSet,
    _aspect_size,
    convert_images_to_editable_pptx,
    remove_chroma_key,
    slice_icon_sheet,
)


class _FakeLayerGenerator:
    def __init__(self) -> None:
        self.background_calls: list[tuple[str, Path, Path]] = []
        self.frame_calls: list[tuple[str, Path, Path]] = []
        self.icon_calls: list[tuple[str, Path, Path]] = []

    def generate_background(self, source_image: Path, page_dir: Path, key_color: str) -> Path:
        self.background_calls.append((key_color, source_image, page_dir))
        background = page_dir / "background.png"
        Image.new("RGB", (320, 180), "white").save(background)
        return background

    def generate_frame(self, source_image: Path, page_dir: Path, key_color: str) -> Path:
        self.frame_calls.append((key_color, source_image, page_dir))
        frame_raw = page_dir / "frame_raw.png"

        frame = Image.new("RGB", (320, 180), key_color)
        for x in range(20, 300):
            for y in range(30, 34):
                frame.putpixel((x, y), (255, 0, 0))
        frame.save(frame_raw)
        return frame_raw

    def generate_icons(self, source_image: Path, page_dir: Path, key_color: str) -> list[Path]:
        self.icon_calls.append((key_color, source_image, page_dir))
        icons_raw = page_dir / "icons_raw_1.png"
        icons = Image.new("RGB", (128, 128), key_color)
        for x in range(40, 88):
            for y in range(40, 88):
                icons.putpixel((x, y), (0, 0, 255))
        icons.save(icons_raw)
        return [icons_raw]


class _FakeTextExtractor:
    def extract_texts(self, source_image: Path) -> list[EditablePptxTextBox]:
        return [
            EditablePptxTextBox(
                text="Editable title",
                source_bbox=(32, 40, 160, 24),
                size_px=22,
                color="#112233",
                bold=True,
            )
        ]


class _FakeIconLocator:
    def locate_icons(
        self,
        source_image: Path,
        cutouts: list[EditablePptxIcon],
        contact_sheet: Path | None = None,
    ) -> list[EditablePptxIcon]:
        if not cutouts:
            return []
        icon = cutouts[0]
        return [
            EditablePptxIcon(
                file=icon.file,
                source_bbox=(40, 50, 48, 48),
                sheet_bbox=icon.sheet_bbox,
                cutout_content_bbox=icon.cutout_content_bbox,
                label="blue square",
                confidence=0.95,
            )
        ]


class EditablePptxTests(unittest.TestCase):
    def test_remove_chroma_key_preserves_non_key_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            target = root / "target.png"
            image = Image.new("RGB", (4, 4), "#00ff00")
            image.putpixel((1, 1), (255, 0, 0))
            image.save(source)

            remove_chroma_key(source, target, "#00ff00")

            with Image.open(target) as result:
                self.assertEqual(result.mode, "RGBA")
                self.assertEqual(result.getpixel((0, 0))[3], 0)
                self.assertEqual(result.getpixel((1, 1)), (255, 0, 0, 255))

    def test_convert_images_to_editable_pptx_creates_isolated_run_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "slide.png"
            Image.new("RGB", (320, 180), "white").save(source)
            output = root / "deck.pptx"
            generator = _FakeLayerGenerator()
            progress_messages: list[str] = []

            result = convert_images_to_editable_pptx(
                [source],
                output,
                work_root=root / "runs",
                layer_generator=generator,
                text_extractor=_FakeTextExtractor(),
                progress_callback=progress_messages.append,
            )

            self.assertEqual(result.pptx_path, output)
            self.assertTrue(output.exists())
            self.assertTrue(result.run_root.is_dir())
            self.assertEqual(len(generator.background_calls), 1)
            self.assertEqual(generator.background_calls[0][1], result.run_root / "editable" / "01" / "slide-01.png")

            page_dir = result.run_root / "editable" / "01"
            manifest = json.loads((page_dir / "imagegen-assets-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["assets"][0]["backend"], "test-imagegen")
            self.assertTrue((page_dir / "frame.png").exists())
            self.assertTrue((page_dir / "icons_t_1.png").exists())

            from pptx import Presentation

            presentation = Presentation(output)
            self.assertEqual(len(presentation.slides), 1)
            slide_text = "\n".join(shape.text for shape in presentation.slides[0].shapes if hasattr(shape, "text"))
            self.assertIn("Editable title", slide_text)
            self.assertTrue(any("正在生成背景层" in message for message in progress_messages))
            self.assertTrue(any("正在合成 PPTX 文件" in message for message in progress_messages))

    def test_slice_icon_sheet_extracts_alpha_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "icons_t_1.png"
            image = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
            for x in range(20, 50):
                for y in range(20, 60):
                    image.putpixel((x, y), (255, 0, 0, 255))
            for x in range(130, 170):
                for y in range(25, 65):
                    image.putpixel((x, y), (0, 0, 255, 255))
            image.save(sheet)

            icons = slice_icon_sheet(sheet, root / "icons", pad=4)

            self.assertEqual(len(icons), 2)
            self.assertTrue(all(icon.file.exists() for icon in icons))
            self.assertEqual(icons[0].sheet_bbox, (16, 16, 54, 64))
            self.assertEqual(icons[0].cutout_content_bbox, (4, 4, 30, 40))

    def test_located_icon_cutouts_are_composed_as_independent_pictures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "slide.png"
            Image.new("RGB", (320, 180), "white").save(source)
            output = root / "deck.pptx"

            result = convert_images_to_editable_pptx(
                [source],
                output,
                work_root=root / "runs",
                layer_generator=_FakeLayerGenerator(),
                text_extractor=_FakeTextExtractor(),
                icon_locator=_FakeIconLocator(),
            )

            page_dir = result.run_root / "editable" / "01"
            layout = json.loads((page_dir / "layout.json").read_text(encoding="utf-8"))
            self.assertEqual(layout["icon_placement_status"], "placed")
            self.assertEqual(layout["icon_layers"], [])
            self.assertEqual(len(layout["icons"]), 1)
            self.assertEqual(layout["icons"][0]["source_bbox"], [40, 50, 48, 48])
            self.assertTrue((page_dir / "icons" / "icons_contact_sheet.png").exists())

            from pptx import Presentation
            from pptx.enum.shapes import MSO_SHAPE_TYPE

            presentation = Presentation(output)
            picture_shapes = [
                shape for shape in presentation.slides[0].shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
            ]
            self.assertEqual(len(picture_shapes), 3)
            icon_shape = picture_shapes[-1]
            self.assertLess(icon_shape.width, presentation.slide_width)
            self.assertLess(icon_shape.height, presentation.slide_height)

    def test_blank_background_mode_skips_background_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "slide.png"
            Image.new("RGB", (320, 180), "#f0f0f0").save(source)
            generator = _FakeLayerGenerator()

            result = convert_images_to_editable_pptx(
                [source],
                root / "blank.pptx",
                work_root=root / "runs",
                layer_generator=generator,
                text_extractor=_FakeTextExtractor(),
                background_mode="blank",
            )

            self.assertEqual(generator.background_calls, [])
            self.assertEqual(len(generator.frame_calls), 1)
            self.assertEqual(len(generator.icon_calls), 1)
            page_dir = result.run_root / "editable" / "01"
            manifest = json.loads((page_dir / "imagegen-assets-manifest.json").read_text(encoding="utf-8"))
            background = next(asset for asset in manifest["assets"] if asset["layer"] == "background")
            self.assertEqual(background["backend"], "blank")
            self.assertEqual(manifest["background_mode"], "blank")

            with Image.open(page_dir / "background.png") as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.size, (320, 180))
                self.assertEqual(image.getpixel((0, 0)), (255, 255, 255, 0))

    def test_nonstandard_aspect_size_uses_valid_pixel_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "wide.png"
            Image.new("RGB", (987, 441), "white").save(source)

            size = _aspect_size(source)

            self.assertEqual(size, "1216x544")
            width, height = (int(part) for part in size.split("x"))
            self.assertEqual(width % 16, 0)
            self.assertEqual(height % 16, 0)
            self.assertGreaterEqual(width * height, 655_360)

    def test_extreme_aspect_size_uses_supported_enum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "extreme.png"
            Image.new("RGB", (2000, 500), "white").save(source)

            self.assertEqual(_aspect_size(source), "3:1")

    def test_configured_image_size_overrides_auto_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "slide.png"
            Image.new("RGB", (987, 441), "white").save(source)
            generator = EvolinkImageLayerGenerator(client=object(), image_size="4:3")

            self.assertEqual(generator._source_size(source), "4:3")


if __name__ == "__main__":
    unittest.main()
