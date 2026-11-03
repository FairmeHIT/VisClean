import tempfile
import unittest
from pathlib import Path

from app.core.editppt_cli_adapter import _prepared_run_dir


class EditPptCliAdapterTests(unittest.TestCase):
    def test_prepared_run_dir_uses_reported_deck_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            run.mkdir()
            deck = run / "deck_manifest.json"
            deck.write_text("{}", encoding="utf-8")

            self.assertEqual(_prepared_run_dir(str(deck), root), run)

    def test_prepared_run_dir_falls_back_to_latest_run_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()

            self.assertEqual(_prepared_run_dir("", root), second)


if __name__ == "__main__":
    unittest.main()
