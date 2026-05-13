import tempfile
import unittest
from pathlib import Path

from app.core.session import ProjectSession


class SessionTests(unittest.TestCase):
    def test_current_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = ProjectSession(Path("source.pptx"), Path(tmp))
            self.assertIsNone(session.current_page)


if __name__ == "__main__":
    unittest.main()

