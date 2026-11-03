import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.core.editable_pptx import EditablePptxIcon
from app.core.vision_icon_locator import LLMIconLocator


class _FakeIconVisionClient:
    def __init__(self) -> None:
        self.calls = []

    def create_vision_chat_completion(self, prompt, *, image_paths, model, max_tokens=4096):
        self.calls.append((prompt, image_paths, model, max_tokens))
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"ref_width":1280,"ref_height":720,'
                            '"icons":[{"file":"icon_001.png","source_bbox":[10,20,30,40],'
                            '"label":"demo","confidence":0.9}]}'
                        )
                    }
                }
            ]
        }


class VisionIconLocatorTests(unittest.TestCase):
    def test_locate_icons_scales_model_view_coordinates_to_source_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "slide.png"
            contact_sheet = root / "contact.png"
            icon_file = root / "icon_001.png"
            Image.new("RGB", (3840, 2160), "white").save(source)
            Image.new("RGB", (220, 180), "white").save(contact_sheet)
            Image.new("RGBA", (32, 32), (0, 0, 255, 255)).save(icon_file)
            client = _FakeIconVisionClient()

            icons = LLMIconLocator(client=client, model="vision-model").locate_icons(
                source,
                [EditablePptxIcon(file=icon_file)],
                contact_sheet,
            )

        self.assertEqual(len(icons), 1)
        self.assertEqual(icons[0].source_bbox, (30, 60, 90, 120))
        self.assertEqual(icons[0].label, "demo")
        self.assertEqual(client.calls[0][1], [source, contact_sheet])


if __name__ == "__main__":
    unittest.main()
