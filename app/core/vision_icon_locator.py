from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import re

from app.core.editable_pptx import EditablePptxError, EditablePptxIcon
from app.core.evolink import DEFAULT_VISION_MODEL, EvolinkClient, EvolinkError
from app.core.vision_geometry import image_size_or_none, infer_reference_size, normalize_bbox, reference_size_from_payload


class LLMIconLocator:
    def __init__(self, client: EvolinkClient | None = None, *, model: str = DEFAULT_VISION_MODEL) -> None:
        self.client = client or EvolinkClient()
        self.model = model.strip() or DEFAULT_VISION_MODEL

    def locate_icons(
        self,
        source_image: Path,
        cutouts: list[EditablePptxIcon],
        contact_sheet: Path | None = None,
    ) -> list[EditablePptxIcon]:
        if not cutouts or contact_sheet is None or not contact_sheet.exists():
            return []
        try:
            response = self.client.create_vision_chat_completion(
                _icon_location_prompt(cutouts),
                image_paths=[Path(source_image), contact_sheet],
                model=self.model,
                max_tokens=4096,
            )
        except EvolinkError as exc:
            raise EditablePptxError(str(exc)) from exc

        payload = _parse_json_response(_message_content(response))
        entries = payload.get("icons", payload if isinstance(payload, list) else [])
        if not isinstance(entries, list):
            raise EditablePptxError("vision icon locator response must contain an icons array")

        by_name = {icon.file.name: icon for icon in cutouts}
        icon_entries = [entry for entry in entries if isinstance(entry, dict)]
        actual_size = image_size_or_none(Path(source_image))
        ref_size = reference_size_from_payload(payload) or _infer_ref_size(icon_entries, actual_size)
        placed: list[EditablePptxIcon] = []
        for entry in icon_entries:
            icon = _located_icon_from_json(entry, by_name, actual_size=actual_size, ref_size=ref_size)
            if icon is not None:
                placed.append(icon)
        return placed


def _message_content(response: dict) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise EditablePptxError(f"vision icon locator response does not contain choices: {response}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "\n".join(str(part) for part in parts if part)
    raise EditablePptxError(f"vision icon locator response does not contain text content: {response}")


def _parse_json_response(content: str):
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    elif text.lower().startswith("```json"):
        text = text[7:].strip()
    elif text.startswith("```"):
        text = text[3:].strip()
    text = _trim_to_json_payload(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise EditablePptxError(f"vision icon locator returned invalid JSON: {content[:500]}") from exc


def _trim_to_json_payload(text: str) -> str:
    object_start = text.find("{")
    array_start = text.find("[")
    starts = [index for index in (object_start, array_start) if index >= 0]
    if not starts:
        return text
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return text[start : end + 1] if end >= start else text[start:]


def _located_icon_from_json(
    entry: object,
    by_name: dict[str, EditablePptxIcon],
    *,
    actual_size: tuple[int, int] | None = None,
    ref_size: tuple[int, int] | None = None,
) -> EditablePptxIcon | None:
    if not isinstance(entry, dict):
        return None
    file_name = Path(str(entry.get("file") or entry.get("name") or "")).name
    source_icon = by_name.get(file_name)
    if source_icon is None:
        return None
    normalized_bbox = normalize_bbox(entry, actual_size, payload_ref_size=ref_size)
    if normalized_bbox is None:
        return None
    x, y, width, height = normalized_bbox
    confidence = entry.get("confidence")
    try:
        confidence_value = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence_value = None
    return replace(
        source_icon,
        source_bbox=(x, y, width, height),
        label=str(entry.get("label", "")),
        confidence=confidence_value,
    )


def _infer_ref_size(entries: list[dict], actual_size: tuple[int, int] | None) -> tuple[int, int] | None:
    if actual_size is None:
        return None
    bboxes = []
    for entry in entries:
        bbox = entry.get("source_bbox") or entry.get("bbox") or entry.get("box_px")
        if isinstance(bbox, list | tuple) and len(bbox) == 4:
            try:
                x, y, width, height = (int(round(float(value))) for value in bbox)
            except (TypeError, ValueError):
                continue
            if width > 0 and height > 0:
                bboxes.append((x, y, width, height))
    return infer_reference_size(bboxes, actual_size)


def _icon_location_prompt(cutouts: list[EditablePptxIcon]) -> str:
    names = ", ".join(icon.file.name for icon in cutouts)
    return (
        "You will see two images. The first image is the original PPT slide screenshot. The second image is a "
        "contact sheet of sliced icon/decorative-element PNG files. For each file in the contact sheet, locate "
        "where that same visible element appears in the first image. Return strict JSON only. Do not return "
        "Markdown, comments, or explanations. JSON schema: "
        '{"ref_width": coordinate_system_width, "ref_height": coordinate_system_height, '
        '"icons": [{"file": "icon_1_001.png", "source_bbox": [x, y, w, h], '
        '"bbox_frac": [x, y, w, h], "label": "short label", "confidence": 0.0}]}. '
        "Rules: 1. file must be one of these exact filenames: " + names + ". "
        "2. Prefer bbox_frac using normalized 0-1 coordinates in the first image, and also report ref_width/ref_height "
        "for the coordinate system you used. "
        "3. If source_bbox is provided in pixels, it must use the same coordinate system as ref_width/ref_height "
        "and must be [left_x, top_y, visible_width, visible_height]. "
        "4. The bbox must tightly cover the visible icon/decorative element itself. Do not include nearby ordinary "
        "text, whole cards, panel backgrounds, or empty space. "
        "5. Omit elements you cannot find confidently, rather than placing them at a guessed position. "
        "6. Do not duplicate the same source element. Treat art text, logos, and decorative symbols as image elements."
    )
