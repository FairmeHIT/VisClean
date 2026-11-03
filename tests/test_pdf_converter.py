import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.pdf_converter import export_pdf_to_png


class _FakePixmap:
    def __init__(self, page_index: int) -> None:
        self.page_index = page_index

    def save(self, path: str) -> None:
        Path(path).write_bytes(f"page-{self.page_index}".encode("utf-8"))


class _FakePage:
    def __init__(self, index: int) -> None:
        self.index = index
        self.rect = types.SimpleNamespace(width=200, height=100)

    def get_pixmap(self, matrix, alpha: bool):
        return _FakePixmap(self.index)


class _FakeDocument:
    def __init__(self) -> None:
        self.pages = [_FakePage(1), _FakePage(2)]

    def __len__(self) -> int:
        return len(self.pages)

    def __iter__(self):
        return iter(self.pages)

    def __getitem__(self, index: int):
        return self.pages[index]

    def close(self) -> None:
        pass


class PdfConverterTests(unittest.TestCase):
    def test_export_pdf_to_png_renders_each_page(self) -> None:
        fake_fitz = types.SimpleNamespace(
            Matrix=lambda x_scale, y_scale: (x_scale, y_scale),
            open=lambda path: _FakeDocument(),
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"fitz": fake_fitz}):
            root = Path(tmp)

            pages, metadata = export_pdf_to_png(root / "source.pdf", root / "pages", width=400)

            self.assertEqual(len(pages), 2)
            self.assertEqual(pages[0].read_bytes(), b"page-1")
            self.assertEqual(pages[1].read_bytes(), b"page-2")
            self.assertEqual(metadata["source_type"], "pdf")
            self.assertEqual(metadata["page_count"], 2)
            self.assertEqual(metadata["output_width"], 400)
            self.assertEqual(metadata["output_height"], 200)


if __name__ == "__main__":
    unittest.main()
