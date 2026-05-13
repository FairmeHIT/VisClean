import tempfile
import unittest
from pathlib import Path

from app.utils.paths import create_session_dir, sanitize_stem


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


if __name__ == "__main__":
    unittest.main()

