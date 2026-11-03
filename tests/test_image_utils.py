import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.utils.image import create_rect_mask_from_rects


class ImageUtilsTests(unittest.TestCase):
    def test_create_rect_mask_from_rects_merges_multiple_regions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mask_path = root / "mask.png"

            create_rect_mask_from_rects(mask_path, (20, 20), ((2, 2, 6, 6), (12, 12, 16, 16)))

            with Image.open(mask_path) as mask:
                self.assertEqual(mask.getpixel((4, 4)), 255)
                self.assertEqual(mask.getpixel((14, 14)), 255)
                self.assertEqual(mask.getpixel((9, 9)), 0)


if __name__ == "__main__":
    unittest.main()
