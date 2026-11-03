import tempfile
import unittest
from pathlib import Path

from app.core.settings import EvolinkSettings, mask_secret, read_evolink_settings, write_evolink_settings


class SettingsTests(unittest.TestCase):
    def test_write_and_read_evolink_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".key" / ".env_evolink_api_key"

            write_evolink_settings(
                EvolinkSettings(api_key="test-key", base_url="https://api.example/v1/"),
                env_file,
            )

            self.assertTrue(env_file.exists())
            content = env_file.read_text(encoding="utf-8")
            self.assertIn("EVOLINK_API_KEY=test-key", content)
            self.assertIn("EVOLINK_BASE_URL=https://api.example/v1/", content)
            self.assertIn("PPTX_ERASER_DOCUMENT_WIDTH=1920", content)
            self.assertIn("PPTX_ERASER_EDITABLE_PPTX_ENGINE=gorden-four-layer", content)
            self.assertIn("EVOLINK_VISION_MODEL=gpt-5.1", content)
            self.assertIn("EVOLINK_IMAGE_SIZE=16:9", content)
            self.assertIn("EVOLINK_RESOLUTION=2K", content)
            self.assertIn("EVOLINK_QUALITY=medium", content)

            settings = read_evolink_settings(env_file)
            self.assertEqual(settings.api_key, "test-key")
            self.assertEqual(settings.base_url, "https://api.example/v1/")
            self.assertEqual(settings.document_width, 1920)
            self.assertEqual(settings.editable_pptx_engine, "gorden-four-layer")
            self.assertEqual(settings.vision_model, "gpt-5.1")
            self.assertEqual(settings.image_size, "16:9")
            self.assertEqual(settings.resolution, "2K")
            self.assertEqual(settings.quality, "medium")

    def test_write_omits_empty_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"

            write_evolink_settings(EvolinkSettings(api_key="test-key", base_url=""), env_file)

            self.assertEqual(
                env_file.read_text(encoding="utf-8"),
                "EVOLINK_API_KEY=test-key\n"
                "PPTX_ERASER_DOCUMENT_WIDTH=1920\n"
                "PPTX_ERASER_EDITABLE_PPTX_ENGINE=gorden-four-layer\n"
                "EVOLINK_VISION_MODEL=gpt-5.1\n"
                "EVOLINK_IMAGE_SIZE=16:9\n"
                "EVOLINK_RESOLUTION=2K\n"
                "EVOLINK_QUALITY=medium\n",
            )

    def test_write_and_read_model_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"

            write_evolink_settings(
                EvolinkSettings(
                    api_key="test-key",
                    document_width=2560,
                    editable_pptx_engine="editppt-cli",
                    vision_model="vision-model",
                    image_size="4:3",
                    resolution="2K",
                    quality="highResolution",
                ),
                env_file,
            )

            settings = read_evolink_settings(env_file)
            self.assertEqual(settings.document_width, 2560)
            self.assertEqual(settings.editable_pptx_engine, "editppt-cli")
            self.assertEqual(settings.vision_model, "vision-model")
            self.assertEqual(settings.image_size, "4:3")
            self.assertEqual(settings.resolution, "2K")
            self.assertEqual(settings.quality, "highResolution")

    def test_read_missing_file_returns_empty_settings(self) -> None:
        settings = read_evolink_settings(Path("missing.env"))

        self.assertEqual(settings.api_key, "")
        self.assertEqual(settings.base_url, "")
        self.assertEqual(settings.document_width, 1920)
        self.assertEqual(settings.editable_pptx_engine, "gorden-four-layer")
        self.assertEqual(settings.vision_model, "gpt-5.1")
        self.assertEqual(settings.image_size, "16:9")
        self.assertEqual(settings.resolution, "2K")
        self.assertEqual(settings.quality, "medium")

    def test_mask_secret_preserves_only_edges(self) -> None:
        self.assertEqual(mask_secret("abcdef123456"), "abcd...3456")
        self.assertEqual(mask_secret("short"), "*****")
        self.assertEqual(mask_secret(""), "未配置")


if __name__ == "__main__":
    unittest.main()
