from __future__ import annotations

import argparse
from pathlib import Path

from app.core.pptx_converter import export_pptx_to_png


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Windows PowerPoint COM PPTX to PNG export.")
    parser.add_argument("pptx", type=Path, help="Path to a .pptx file")
    parser.add_argument("--out", type=Path, default=Path("validation_output"), help="Output directory")
    parser.add_argument("--width", type=int, default=1920, help="Export image width")
    args = parser.parse_args()

    pages, metadata = export_pptx_to_png(args.pptx, args.out, args.width)
    print(f"exported {len(pages)} pages")
    print(metadata)
    for page in pages:
        print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

