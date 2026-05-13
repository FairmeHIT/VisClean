import tempfile
import unittest
from pathlib import Path

from app.core.exporter import export_pngs


class ExporterTests(unittest.TestCase):
    def test_export_pngs_copies_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "page.png"
            source.write_bytes(b"fake-png")
            exported = export_pngs([source], root / "out")
            self.assertTrue(exported[0].exists())
            self.assertEqual(exported[0].read_bytes(), b"fake-png")


if __name__ == "__main__":
    unittest.main()

