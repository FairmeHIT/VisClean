from __future__ import annotations

from pathlib import Path
from typing import Iterable


def image_size_or_none(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def reference_size_from_payload(payload: object) -> tuple[int, int] | None:
    if not isinstance(payload, dict):
        return None
    direct = _reference_size_from_mapping(payload)
    if direct is not None:
        return direct
    notes = payload.get("notes")
    if isinstance(notes, dict):
        return _reference_size_from_mapping(notes)
    return None


def normalize_bbox(
    entry: dict,
    actual_size: tuple[int, int] | None,
    *,
    payload_ref_size: tuple[int, int] | None = None,
) -> tuple[int, int, int, int] | None:
    if actual_size is None:
        bbox = entry.get("source_bbox") or entry.get("bbox") or entry.get("box_px")
        return _coerce_bbox(bbox)

    frac_bbox = entry.get("bbox_frac") or entry.get("bbox_ratio") or entry.get("fraction_bbox")
    if isinstance(frac_bbox, list | tuple) and len(frac_bbox) == 4:
        return _scale_bbox([float(value) for value in frac_bbox], actual_size[0], actual_size[1])

    bbox = entry.get("source_bbox") or entry.get("bbox") or entry.get("box_px")
    coerced = _coerce_bbox(bbox)
    if coerced is None:
        return None

    ref_size = _reference_size_from_mapping(entry) or payload_ref_size
    if ref_size is None:
        ref_size = infer_reference_size([coerced], actual_size)
    return scale_bbox_between_sizes(coerced, ref_size, actual_size) if ref_size else coerced


def normalize_bboxes(
    entries: Iterable[dict],
    actual_size: tuple[int, int] | None,
    *,
    payload_ref_size: tuple[int, int] | None = None,
) -> list[tuple[dict, tuple[int, int, int, int]]]:
    items = [(entry, _coerce_bbox(entry.get("source_bbox") or entry.get("bbox") or entry.get("box_px"))) for entry in entries]
    if actual_size is None:
        return [(entry, bbox) for entry, bbox in items if bbox is not None]

    ref_size = payload_ref_size or _infer_reference_size_for_entries([bbox for _entry, bbox in items if bbox], actual_size)
    normalized = []
    for entry, bbox in items:
        if bbox is None:
            bbox = normalize_bbox(entry, actual_size, payload_ref_size=payload_ref_size)
        elif ref_size is not None and not _has_fraction_bbox(entry):
            bbox = scale_bbox_between_sizes(bbox, ref_size, actual_size)
        else:
            bbox = normalize_bbox(entry, actual_size, payload_ref_size=payload_ref_size)
        if bbox is not None:
            normalized.append((entry, bbox))
    return normalized


def infer_reference_size(
    bboxes: list[tuple[int, int, int, int]],
    actual_size: tuple[int, int],
) -> tuple[int, int] | None:
    return _infer_reference_size_for_entries(bboxes, actual_size)


def scale_bbox_between_sizes(
    bbox: tuple[int, int, int, int],
    ref_size: tuple[int, int],
    actual_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    ref_width, ref_height = ref_size
    actual_width, actual_height = actual_size
    if ref_width <= 0 or ref_height <= 0 or (ref_width, ref_height) == actual_size:
        return bbox
    sx = actual_width / ref_width
    sy = actual_height / ref_height
    x, y, width, height = bbox
    return (
        max(0, int(round(x * sx))),
        max(0, int(round(y * sy))),
        max(1, int(round(width * sx))),
        max(1, int(round(height * sy))),
    )


def _infer_reference_size_for_entries(
    bboxes: list[tuple[int, int, int, int]],
    actual_size: tuple[int, int],
) -> tuple[int, int] | None:
    if not bboxes:
        return None
    actual_width, actual_height = actual_size
    if actual_width < 1800 or actual_height < 1000:
        return None
    max_right = max(x + width for x, _y, width, _height in bboxes)
    max_bottom = max(y + height for _x, y, _width, height in bboxes)
    if max_right > actual_width * 0.72 or max_bottom > actual_height * 0.72:
        return actual_size

    aspect = actual_width / actual_height
    candidates = [
        (1280, 720),
        (1024, 576),
        (1366, 768),
        (1600, 900),
        (1920, 1080),
        (2048, 1152),
        (2560, 1440),
    ]
    viable = [
        (width, height)
        for width, height in candidates
        if width < actual_width
        and height < actual_height
        and max_right <= width * 1.03
        and max_bottom <= height * 1.03
        and abs((width / height) - aspect) / aspect <= 0.03
    ]
    return viable[0] if viable else None


def _reference_size_from_mapping(mapping: dict) -> tuple[int, int] | None:
    width = mapping.get("ref_width") or mapping.get("image_width") or mapping.get("width")
    height = mapping.get("ref_height") or mapping.get("image_height") or mapping.get("height")
    try:
        width_int = int(round(float(width)))
        height_int = int(round(float(height)))
    except (TypeError, ValueError):
        return None
    return (width_int, height_int) if width_int > 0 and height_int > 0 else None


def _coerce_bbox(value: object) -> tuple[int, int, int, int] | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    try:
        x, y, width, height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _scale_bbox(values: list[float], actual_width: int, actual_height: int) -> tuple[int, int, int, int]:
    x, y, width, height = values
    return (
        max(0, int(round(x * actual_width))),
        max(0, int(round(y * actual_height))),
        max(1, int(round(width * actual_width))),
        max(1, int(round(height * actual_height))),
    )


def _has_fraction_bbox(entry: dict) -> bool:
    return any(key in entry for key in ("bbox_frac", "bbox_ratio", "fraction_bbox"))
