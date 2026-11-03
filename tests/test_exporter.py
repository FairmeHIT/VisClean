import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.core.exporter import (
    ExportError,
    export_image_file,
    export_image_folder_pptx,
    export_images_folder,
    export_pngs,
    export_transparent_image_file,
)


class ExporterTests(unittest.TestCase):
    def test_export_pngs_copies_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "page.png"
            source.write_bytes(b"fake-png")
            exported = export_pngs([source], root / "out")
            self.assertTrue(exported[0].exists())
            self.assertEqual(exported[0].read_bytes(), b"fake-png")

    def test_export_image_file_writes_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "page.png"
            target = root / "edited.png"
            Image.new("RGB", (20, 10), "blue").save(source)

            exported = export_image_file(source, target)

            self.assertEqual(exported, target)
            with Image.open(target) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.size, (20, 10))

    def test_export_image_file_keeps_white_background_opaque(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "page.png"
            target = root / "normal.png"

            Image.new("RGB", (12, 12), "white").save(source)

            export_image_file(source, target)

            with Image.open(target) as result:
                self.assertEqual(result.mode, "RGB")
                self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))

    def test_export_transparent_image_file_removes_white_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "page.png"
            target = root / "transparent.png"

            image = Image.new("RGB", (12, 12), "white")
            for x in range(3, 9):
                for y in range(4, 8):
                    image.putpixel((x, y), (0, 128, 255))
            image.save(source)

            export_transparent_image_file(source, target)

            with Image.open(target) as result:
                self.assertEqual(result.mode, "RGBA")
                self.assertEqual(result.getpixel((0, 0))[3], 0)
                self.assertEqual(result.getpixel((5, 5))[3], 255)

    def test_export_images_folder_writes_to_images_subfolder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_one = root / "source_one.png"
            source_two = root / "source_two.png"
            source_one.write_bytes(b"page-one")
            source_two.write_bytes(b"page-two")

            image_dir = export_images_folder([source_one, source_two], root / "export")

            self.assertEqual(image_dir, root / "export" / "images")
            self.assertEqual((image_dir / "page_001.png").read_bytes(), b"page-one")
            self.assertEqual((image_dir / "page_002.png").read_bytes(), b"page-two")

    def test_export_image_folder_pptx_uses_supported_images_in_name_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "images"
            source_dir.mkdir()
            Image.new("RGB", (30, 20), "red").save(source_dir / "page_10.jpg")
            Image.new("RGB", (30, 20), "green").save(source_dir / "page_2.png")
            (source_dir / "notes.txt").write_text("ignore me", encoding="utf-8")
            target = root / "deck.pptx"

            exported = export_image_folder_pptx(source_dir, target)

            self.assertEqual(exported, target)
            self.assertTrue(target.exists())
            from pptx import Presentation

            presentation = Presentation(target)
            self.assertEqual(len(presentation.slides), 2)

    def test_export_image_folder_pptx_rejects_empty_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(ExportError):
                export_image_folder_pptx(root, root / "deck.pptx")


if __name__ == "__main__":
    unittest.main()
