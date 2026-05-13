import unittest
from pathlib import Path

from app.core.history import HistoryStack


class HistoryTests(unittest.TestCase):
    def test_push_and_undo(self) -> None:
        history = HistoryStack(limit=2)
        history.push(Path("a.png"))
        history.push(Path("b.png"))
        self.assertTrue(history.can_undo())
        self.assertEqual(history.undo(), Path("b.png"))


if __name__ == "__main__":
    unittest.main()

