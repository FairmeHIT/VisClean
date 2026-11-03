import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.core.session import PastedObject, ProjectSession, compose_page, crop_page_to_rect


class SessionTests(unittest.TestCase):
    def test_current_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = ProjectSession(Path("source.pptx"), Path(tmp))
            self.assertIsNone(session.current_page)

    def test_set_pages_converts_imported_images_to_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jpg"
            Image.new("RGB", (32, 24), "red").save(source)

            session = ProjectSession(source, root / "session")
            session.set_pages([source])

            page = session.pages[0]
            self.assertEqual(page.current_image_path.suffix, ".png")
            with Image.open(page.current_image_path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (32, 24))

    def test_set_pages_keeps_all_imported_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.png"
            second = root / "second.png"
            Image.new("RGB", (32, 24), "red").save(first)
            Image.new("RGB", (48, 36), "blue").save(second)

            session = ProjectSession(first, root / "session")
            session.set_pages([first, second])

            self.assertEqual(len(session.pages), 2)
            self.assertEqual([page.index for page in session.pages], [1, 2])

    def test_set_pages_rejects_non_image_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "notes.txt"
            source.write_text("not an image", encoding="utf-8")

            session = ProjectSession(source, root / "session")

            with self.assertRaises(ValueError):
                session.set_pages([source])

    def test_crop_page_updates_dimensions_and_pasted_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            Image.new("RGB", (100, 80), "white").save(source)

            session = ProjectSession(source, root / "session")
            session.set_pages([source])
            page = session.pages[0]
            object_path = page.objects_dir / "obj_001.png"
            object_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (20, 20), "red").save(object_path)
            page.objects.append(PastedObject(object_path, (30, 20, 49, 39)))
            compose_page(page)

            size = crop_page_to_rect(page, (20, 10, 60, 50))

            self.assertEqual(size, (41, 41))
            with Image.open(page.current_image_path) as image:
                self.assertEqual(image.size, (41, 41))
                self.assertEqual(image.getpixel((10, 10))[:3], (255, 0, 0))
            self.assertEqual(page.objects[0].bbox, (10, 10, 29, 29))
            with Image.open(page.objects[0].image_path) as image:
                self.assertEqual(image.size, (20, 20))
            with Image.open(page.thumbnail_path) as image:
                self.assertLessEqual(max(image.size), 240)


if __name__ == "__main__":
    unittest.main()
