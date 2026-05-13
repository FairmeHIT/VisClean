from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any


class PowerPointConversionError(RuntimeError):
    pass


def export_pptx_to_png(pptx_path: Path, output_dir: Path, width: int = 1920) -> tuple[list[Path], dict[str, Any]]:
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:  # pragma: no cover
        raise PowerPointConversionError("pywin32 is required on Windows to convert PPTX files.") from exc

    pptx_path = Path(pptx_path).expanduser().resolve()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    app = None
    presentation = None
    export_paths: list[Path] = []
    metadata: dict[str, Any] = {}
    try:
        app = win32com.client.DispatchEx("PowerPoint.Application")
        with suppress(Exception):
            app.Visible = 1
        presentation = app.Presentations.Open(str(pptx_path), ReadOnly=1, Untitled=0, WithWindow=False)

        slide_width = float(presentation.PageSetup.SlideWidth)
        slide_height = float(presentation.PageSetup.SlideHeight)
        height = max(1, round(width * slide_height / slide_width))
        metadata = {
            "slide_width": slide_width,
            "slide_height": slide_height,
            "output_width": width,
            "output_height": height,
            "slide_count": int(presentation.Slides.Count),
        }

        for index in range(1, presentation.Slides.Count + 1):
            out_path = output_dir / f"page_{index:03d}.png"
            presentation.Slides(index).Export(str(out_path), "PNG", width, height)
            export_paths.append(out_path)

        return export_paths, metadata
    except Exception as exc:  # pragma: no cover
        raise PowerPointConversionError(f"failed to export {pptx_path.name}: {exc}") from exc
    finally:
        if presentation is not None:
            with suppress(Exception):
                presentation.Close()
        if app is not None:
            with suppress(Exception):
                app.Quit()
        pythoncom.CoUninitialize()

