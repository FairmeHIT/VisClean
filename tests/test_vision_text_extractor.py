import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.core.vision_text_extractor import LLMTextExtractor


class _FakeVisionClient:
    def __init__(self) -> None:
        self.calls = []

    def create_vision_chat_completion(self, prompt, *, image_paths, model, max_tokens=8192):
        self.calls.append((prompt, image_paths, model))
        return {
            "choices": [
                {
                    "message": {
                        "content": """
                        ```json
                        {"texts":[{"text":"标题","source_bbox":[10,20,100,30],"size_px":24,"color":"112233","bold":true,"align":"center","font":"Microsoft YaHei"}]}
                        ```
                        """
                    }
                }
            ]
        }


class VisionTextExtractorTests(unittest.TestCase):
    def test_extract_texts_parses_json_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "slide.png"
            source.write_bytes(b"fake")
            client = _FakeVisionClient()

            texts = LLMTextExtractor(client=client, model="vision-model").extract_texts(source)

        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0].text, "标题")
        self.assertEqual(texts[0].source_bbox, (10, 20, 100, 30))
        self.assertEqual(texts[0].size_px, 24)
        self.assertEqual(texts[0].color, "#112233")
        self.assertTrue(texts[0].bold)
        self.assertEqual(texts[0].align, "center")
        self.assertEqual(client.calls[0][1], [source])
        self.assertEqual(client.calls[0][2], "vision-model")

    def test_extract_texts_scales_model_view_coordinates_to_source_pixels(self) -> None:
        class Client:
            def create_vision_chat_completion(self, prompt, *, image_paths, model, max_tokens=8192):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"ref_width":1280,"ref_height":720,'
                                    '"texts":[{"text":"标题","source_bbox":[10,20,100,30],'
                                    '"size_px":24,"color":"#000000"}]}'
                                )
                            }
                        }
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "slide.png"
            Image.new("RGB", (3840, 2160), "white").save(source)

            texts = LLMTextExtractor(client=Client(), model="vision-model").extract_texts(source)

        self.assertEqual(texts[0].source_bbox, (30, 60, 300, 90))
        self.assertEqual(texts[0].size_px, 72)

    def test_extract_texts_uses_bbox_height_when_model_size_is_too_small(self) -> None:
        class Client:
            def create_vision_chat_completion(self, prompt, *, image_paths, model, max_tokens=8192):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"texts":[{"text":"标题","source_bbox":[10,20,300,100],'
                                    '"size_px":18,"color":"#000000"}]}'
                                )
                            }
                        }
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "slide.png"
            Image.new("RGB", (1280, 720), "white").save(source)

            texts = LLMTextExtractor(client=Client(), model="vision-model").extract_texts(source)

        self.assertEqual(texts[0].size_px, 72)


if __name__ == "__main__":
    unittest.main()
