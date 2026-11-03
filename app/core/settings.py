from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.evolink import DEFAULT_ENV_FILE, DEFAULT_IMAGE_SIZE, DEFAULT_QUALITY, DEFAULT_RESOLUTION, DEFAULT_VISION_MODEL


IMAGE_SIZE_OPTIONS = (
    "auto",
    "1:1",
    "1:2",
    "2:1",
    "1:3",
    "3:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
    "9:21",
)
RESOLUTION_OPTIONS = ("1K", "2K", "4K")
QUALITY_OPTIONS = ("low", "medium", "highResolution")
DOCUMENT_WIDTH_OPTIONS = (1280, 1920, 2560, 3840)
DEFAULT_DOCUMENT_WIDTH = 1920
EDITABLE_PPTX_ENGINE_OPTIONS = ("gorden-four-layer", "editppt-cli")
DEFAULT_EDITABLE_PPTX_ENGINE = "gorden-four-layer"


@dataclass(frozen=True)
class EvolinkSettings:
    api_key: str = ""
    base_url: str = ""
    document_width: int = DEFAULT_DOCUMENT_WIDTH
    editable_pptx_engine: str = DEFAULT_EDITABLE_PPTX_ENGINE
    vision_model: str = DEFAULT_VISION_MODEL
    image_size: str = DEFAULT_IMAGE_SIZE
    resolution: str = DEFAULT_RESOLUTION
    quality: str = DEFAULT_QUALITY


def read_evolink_settings(env_file: Path | str = DEFAULT_ENV_FILE) -> EvolinkSettings:
    path = Path(env_file)
    if not path.exists():
        return EvolinkSettings()

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.replace("export ", "", 1).strip()] = value.strip().strip('"').strip("'")
    return EvolinkSettings(
        api_key=values.get("EVOLINK_API_KEY", ""),
        base_url=values.get("EVOLINK_BASE_URL", ""),
        document_width=_int_setting_or_default(
            values.get("PPTX_ERASER_DOCUMENT_WIDTH"),
            DOCUMENT_WIDTH_OPTIONS,
            DEFAULT_DOCUMENT_WIDTH,
        ),
        editable_pptx_engine=_setting_or_default(
            values.get("PPTX_ERASER_EDITABLE_PPTX_ENGINE"),
            EDITABLE_PPTX_ENGINE_OPTIONS,
            DEFAULT_EDITABLE_PPTX_ENGINE,
        ),
        vision_model=(values.get("EVOLINK_VISION_MODEL") or DEFAULT_VISION_MODEL).strip() or DEFAULT_VISION_MODEL,
        image_size=_setting_or_default(values.get("EVOLINK_IMAGE_SIZE"), IMAGE_SIZE_OPTIONS, DEFAULT_IMAGE_SIZE),
        resolution=_setting_or_default(values.get("EVOLINK_RESOLUTION"), RESOLUTION_OPTIONS, DEFAULT_RESOLUTION),
        quality=_setting_or_default(values.get("EVOLINK_QUALITY"), QUALITY_OPTIONS, DEFAULT_QUALITY),
    )


def write_evolink_settings(settings: EvolinkSettings, env_file: Path | str = DEFAULT_ENV_FILE) -> Path:
    path = Path(env_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"EVOLINK_API_KEY={settings.api_key.strip()}"]
    base_url = settings.base_url.strip()
    if base_url:
        lines.append(f"EVOLINK_BASE_URL={base_url}")
    lines.extend(
        [
            f"PPTX_ERASER_DOCUMENT_WIDTH={_int_setting_or_default(settings.document_width, DOCUMENT_WIDTH_OPTIONS, DEFAULT_DOCUMENT_WIDTH)}",
            f"PPTX_ERASER_EDITABLE_PPTX_ENGINE={_setting_or_default(settings.editable_pptx_engine, EDITABLE_PPTX_ENGINE_OPTIONS, DEFAULT_EDITABLE_PPTX_ENGINE)}",
            f"EVOLINK_VISION_MODEL={settings.vision_model.strip() or DEFAULT_VISION_MODEL}",
            f"EVOLINK_IMAGE_SIZE={_setting_or_default(settings.image_size, IMAGE_SIZE_OPTIONS, DEFAULT_IMAGE_SIZE)}",
            f"EVOLINK_RESOLUTION={_setting_or_default(settings.resolution, RESOLUTION_OPTIONS, DEFAULT_RESOLUTION)}",
            f"EVOLINK_QUALITY={_setting_or_default(settings.quality, QUALITY_OPTIONS, DEFAULT_QUALITY)}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def mask_secret(value: str) -> str:
    secret = value.strip()
    if not secret:
        return "未配置"
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"


def _setting_or_default(value: str | None, options: tuple[str, ...], default: str) -> str:
    normalized = (value or "").strip()
    return normalized if normalized in options else default


def _int_setting_or_default(value: int | str | None, options: tuple[int, ...], default: int) -> int:
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return normalized if normalized in options else default
