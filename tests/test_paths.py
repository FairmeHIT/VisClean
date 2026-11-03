import tempfile
import unittest
from pathlib import Path

from app.utils.paths import create_session_dir, default_editable_pptx_output_path, sanitize_stem


class PathTests(unittest.TestCase):
    def test_sanitize_stem(self) -> None:
        self.assertEqual(sanitize_stem(" a/b:c "), "a_b_c")
        self.assertEqual(sanitize_stem(""), "project")

    def test_create_session_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session_dir(root, "demo file")
            self.assertTrue(session_dir.exists())
            self.assertTrue((session_dir / "pages").exists())
            self.assertTrue((session_dir / "exports").exists())

    def test_default_editable_pptx_output_path_uses_folder_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_dir = Path(tmp) / "slides"
            image_dir.mkdir()

            output_path = default_editable_pptx_output_path(image_dir)

            self.assertEqual(output_path, image_dir / "slides_editable.pptx")

    def test_default_editable_pptx_output_path_avoids_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_dir = Path(tmp) / "slides"
            image_dir.mkdir()
            (image_dir / "slides_editable.pptx").write_bytes(b"existing")
            (image_dir / "slides_editable_2.pptx").write_bytes(b"existing")

            output_path = default_editable_pptx_output_path(image_dir)

            self.assertEqual(output_path, image_dir / "slides_editable_3.pptx")

    def test_default_editable_pptx_output_path_can_use_source_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            output_path = default_editable_pptx_output_path(output_dir, "demo deck")

            self.assertEqual(output_path, output_dir / "demo_deck_editable.pptx")


if __name__ == "__main__":
    unittest.main()
