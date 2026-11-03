import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.image_inpainter import inpaint_file


class ImageInpainterTests(unittest.TestCase):
    def test_inpaint_file_supports_non_ascii_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="擦除测试_") as tmp:
            root = Path(tmp)
            image_path = root / "页面_001_current.png"
            mask_path = root / "页面_001_mask.png"
            output_path = root / "页面_001_output.png"

            image = np.full((32, 32, 3), 255, dtype=np.uint8)
            image[10:20, 10:20] = 0
            mask = np.zeros((32, 32), dtype=np.uint8)
            mask[10:20, 10:20] = 255

            Image.fromarray(image).save(image_path)
            Image.fromarray(mask).save(mask_path)

            result = inpaint_file(image_path, mask_path, output_path)

            self.assertTrue(result.exists())
            self.assertGreater(result.stat().st_size, 0)

    def test_inpaint_file_cleans_flat_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "page.png"
            mask_path = root / "mask.png"
            output_path = root / "output.png"

            background = np.full((64, 96, 3), 240, dtype=np.uint8)
            background[24:40, 32:64] = 20
            mask = np.zeros((64, 96), dtype=np.uint8)
            mask[22:42, 30:66] = 255

            Image.fromarray(background).save(image_path)
            Image.fromarray(mask).save(mask_path)

            inpaint_file(image_path, mask_path, output_path)
            result = np.array(Image.open(output_path))

            erased_region = result[26:38, 36:60]
            self.assertGreater(erased_region.mean(), 220)

    def test_inpaint_file_prefers_immediate_boundary_color(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "page.png"
            mask_path = root / "mask.png"
            output_path = root / "output.png"

            image = np.full((48, 48, 3), 30, dtype=np.uint8)
            image[14:34, 14:34] = 236
            image[20:28, 20:28] = 20
            mask = np.zeros((48, 48), dtype=np.uint8)
            mask[20:28, 20:28] = 255

            Image.fromarray(image).save(image_path)
            Image.fromarray(mask).save(mask_path)

            inpaint_file(image_path, mask_path, output_path)
            result = np.array(Image.open(output_path))

            erased_region = result[22:26, 22:26]
            self.assertGreater(erased_region.mean(), 220)

    def test_inpaint_file_uses_dominant_boundary_color_when_text_crosses_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "page.png"
            mask_path = root / "mask.png"
            output_path = root / "output.png"

            image = np.full((48, 48, 3), 255, dtype=np.uint8)
            image[20:28, 20:28] = 20
            image[19:29, 27:31] = 0
            mask = np.zeros((48, 48), dtype=np.uint8)
            mask[20:28, 20:28] = 255

            Image.fromarray(image).save(image_path)
            Image.fromarray(mask).save(mask_path)

            inpaint_file(image_path, mask_path, output_path)
            result = np.array(Image.open(output_path))

            erased_region = result[22:26, 22:26]
            self.assertGreater(erased_region.mean(), 245)


if __name__ == "__main__":
    unittest.main()
