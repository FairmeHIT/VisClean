from __future__ import annotations

from pathlib import Path
from typing import Any


class PdfConversionError(RuntimeError):
    pass


def export_pdf_to_png(pdf_path: Path, output_dir: Path, width: int = 1920) -> tuple[list[Path], dict[str, Any]]:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover
        raise PdfConversionError("PyMuPDF is required to convert PDF files.") from exc

    pdf_path = Path(pdf_path).expanduser().resolve()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    document = None
    export_paths: list[Path] = []
    try:
        document = fitz.open(pdf_path)
        if len(document) == 0:
            raise PdfConversionError("PDF contains no pages.")

        first_page = document[0]
        page_width = float(first_page.rect.width)
        page_height = float(first_page.rect.height)
        if page_width <= 0 or page_height <= 0:
            raise PdfConversionError("PDF page size is invalid.")

        zoom = width / page_width
        height = max(1, round(page_height * zoom))
        matrix = fitz.Matrix(zoom, zoom)

        for index, page in enumerate(document, start=1):
            out_path = output_dir / f"page_{index:03d}.png"
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pixmap.save(str(out_path))
            export_paths.append(out_path)

        metadata: dict[str, Any] = {
            "source_type": "pdf",
            "page_width": page_width,
            "page_height": page_height,
            "output_width": width,
            "output_height": height,
            "page_count": len(document),
        }
        return export_paths, metadata
    except PdfConversionError:
        raise
    except Exception as exc:  # pragma: no cover
        raise PdfConversionError(f"failed to export {pdf_path.name}: {exc}") from exc
    finally:
        if document is not None:
            document.close()
