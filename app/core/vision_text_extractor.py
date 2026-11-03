from __future__ import annotations

from pathlib import Path
import json
import re

from app.core.editable_pptx import EditablePptxError, EditablePptxTextBox
from app.core.evolink import DEFAULT_VISION_MODEL, EvolinkClient, EvolinkError
from app.core.vision_geometry import image_size_or_none, infer_reference_size, normalize_bbox, reference_size_from_payload


class LLMTextExtractor:
    def __init__(
        self,
        client: EvolinkClient | None = None,
        *,
        model: str = DEFAULT_VISION_MODEL,
        max_tokens: int = 8192,
    ) -> None:
        self.client = client or EvolinkClient()
        self.model = model.strip() or DEFAULT_VISION_MODEL
        self.max_tokens = max_tokens

    def extract_texts(self, source_image: Path) -> list[EditablePptxTextBox]:
        try:
            response = self.client.create_vision_chat_completion(
                _text_extraction_prompt(),
                image_paths=[Path(source_image)],
                model=self.model,
                max_tokens=self.max_tokens,
            )
        except EvolinkError as exc:
            raise EditablePptxError(str(exc)) from exc
        payload = _parse_json_response(_message_content(response))
        entries = payload.get("texts", payload if isinstance(payload, list) else [])
        if not isinstance(entries, list):
            raise EditablePptxError("vision text extractor response must contain a texts array")
        actual_size = image_size_or_none(Path(source_image))
        text_entries = [entry for entry in entries if _has_text(entry)]
        ref_size = reference_size_from_payload(payload) or _infer_ref_size(text_entries, actual_size)
        return [
            _text_box_from_vision_json(entry, actual_size=actual_size, ref_size=ref_size)
            for entry in text_entries
        ]


def _message_content(response: dict) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise EditablePptxError(f"vision text extractor response does not contain choices: {response}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "\n".join(str(part) for part in parts if part)
    raise EditablePptxError(f"vision text extractor response does not contain text content: {response}")


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
        raise EditablePptxError(f"vision text extractor returned invalid JSON: {content[:500]}") from exc


def _trim_to_json_payload(text: str) -> str:
    object_start = text.find("{")
    array_start = text.find("[")
    starts = [index for index in (object_start, array_start) if index >= 0]
    if not starts:
        return text
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return text[start : end + 1] if end >= start else text[start:]


def _text_box_from_vision_json(
    entry: dict,
    *,
    actual_size: tuple[int, int] | None = None,
    ref_size: tuple[int, int] | None = None,
) -> EditablePptxTextBox:
    if not isinstance(entry, dict):
        raise EditablePptxError("vision text entries must be JSON objects")
    normalized_bbox = normalize_bbox(entry, actual_size, payload_ref_size=ref_size)
    if normalized_bbox is None:
        raise EditablePptxError("vision text entries must include source_bbox with four numbers")
    x, y, width, height = normalized_bbox
    size_scale_y = _size_scale_y(actual_size, ref_size, entry)
    return EditablePptxTextBox(
        text=str(entry.get("text", "")),
        source_bbox=(x, y, max(1, width), max(1, height)),
        size_px=_size_px(entry, height, size_scale_y=size_scale_y),
        color=_normalize_color(str(entry.get("color", "#000000"))),
        bold=bool(entry.get("bold", False)),
        align=str(entry.get("align", "left")).lower(),
        font_face=str(entry.get("font_face") or entry.get("font") or "Microsoft YaHei"),
    )


def _size_px(entry: dict, fallback_height: int, *, size_scale_y: float = 1.0) -> int:
    for key in ("size_px", "font_size_px", "glyph_height_px"):
        value = entry.get(key)
        if value is not None:
            explicit_size = max(1, int(round(float(value) * size_scale_y)))
            inferred_size = max(1, int(round(fallback_height * 0.72)))
            if explicit_size < fallback_height * 0.45:
                return inferred_size
            return explicit_size
    size_ratio = entry.get("size_ratio")
    ref_height = entry.get("ref_height")
    if size_ratio is not None and ref_height is not None:
        return max(1, int(round(float(size_ratio) * float(ref_height))))
    return max(1, int(round(fallback_height * 0.72)))


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


def _size_scale_y(
    actual_size: tuple[int, int] | None,
    ref_size: tuple[int, int] | None,
    entry: dict,
) -> float:
    if actual_size is None or ref_size is None or any(
        key in entry for key in ("bbox_frac", "bbox_ratio", "fraction_bbox")
    ):
        return 1.0
    return actual_size[1] / ref_size[1] if ref_size[1] else 1.0


def _normalize_color(value: str) -> str:
    stripped = value.strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", stripped):
        return stripped if stripped.startswith("#") else f"#{stripped}"
    return "#000000"


def _has_text(entry) -> bool:
    return isinstance(entry, dict) and bool(str(entry.get("text", "")).strip())


def _text_extraction_prompt() -> str:
    return (
        "Use your vision capability to read all ordinary editable text in this PPT slide image. "
        "Return strict JSON only. Do not return Markdown, comments, or explanations. "
        "JSON schema: "
        '{"ref_width": coordinate_system_width, "ref_height": coordinate_system_height, '
        '"texts": [{"text": "verbatim visible text", "source_bbox": [x, y, w, h], '
        '"bbox_frac": [x, y, w, h], "size_px": text_height_pixels, "color": "#RRGGBB", '
        '"bold": false, "align": "left|center|right", "font_face": "Microsoft YaHei"}]}. '
        "Rules: 1. Transcribe visible text verbatim, including Chinese text; do not rewrite, translate, "
        "summarize, normalize punctuation, or invent missing characters. "
        "2. Prefer bbox_frac using normalized 0-1 coordinates, and also report ref_width/ref_height for "
        "the coordinate system you used. "
        "3. If source_bbox is provided in pixels, it must use the same coordinate system as ref_width/ref_height "
        "and must be [left_x, top_y, width, height]. "
        "4. size_px is the visible text height in the ref_height coordinate system; do not mix thumbnail and "
        "source-image coordinate systems. "
        "5. Each bbox must tightly cover one line or one natural short text block only; do not include whole cards, "
        "blank space, nearby icons, adjacent columns, or container edges. "
        "6. Split multi-line titles and multi-line body text into multiple text entries; do not merge them into one "
        "tall or very wide bbox. "
        "7. The bbox width should end near the visible end of that text; do not extend it to the right page edge "
        "or the container edge for convenience. "
        "8. Extract ordinary font text only. Do not include art text, logo lettering, gradient outlined text, "
        "or decorative typography in texts. "
        "9. Preserve reading order. If a character is unclear, keep only the confirmed visible part or skip it."
    )
