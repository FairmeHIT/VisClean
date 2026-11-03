from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import tempfile


def sanitize_stem(name: str) -> str:
    stem = re.sub(r"[^\w.-]+", "_", name.strip(), flags=re.UNICODE)
    stem = stem.strip("._")
    return stem or "project"


def create_session_dir(base_dir: Path | None = None, source_name: str = "project") -> Path:
    base = Path(base_dir) if base_dir is not None else Path(tempfile.gettempdir()) / "pptx_eraser"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_name = f"{timestamp}_{sanitize_stem(source_name)}"
    session_dir = base / "sessions" / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    for child in ("pages", "edits", "masks", "thumbnails", "history", "exports"):
        (session_dir / child).mkdir(exist_ok=True)
    return session_dir


def default_editable_pptx_output_path(output_dir: Path, source_stem: str | None = None) -> Path:
    stem_source = source_stem if source_stem is not None else output_dir.name or "images"
    stem = f"{sanitize_stem(stem_source)}_editable"
    candidate = output_dir / f"{stem}.pptx"
    suffix = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}_{suffix}.pptx"
        suffix += 1
    return candidate
