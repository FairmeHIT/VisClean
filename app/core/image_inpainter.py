from __future__ import annotations

from pathlib import Path


class InpaintError(RuntimeError):
    pass


def inpaint_file(
    image_path: Path,
    mask_path: Path,
    output_path: Path,
    radius: int | None = None,
    algorithm: str = "telea",
) -> Path:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise InpaintError("opencv-python and numpy are required for inpainting.") from exc

    image = _read_image(cv2, np, image_path, cv2.IMREAD_COLOR)
    mask = _read_image(cv2, np, mask_path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise InpaintError(f"failed to load image: {image_path}")
    if mask is None:
        raise InpaintError(f"failed to load mask: {mask_path}")

    if mask.max() <= 1:
        mask = mask * 255

    mask = _prepare_mask(cv2, mask)
    result = _inpaint_roi(cv2, image, mask, radius, algorithm)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not _write_image(cv2, output_path, result):
        raise InpaintError(f"failed to write image: {output_path}")
    return output_path


def _prepare_mask(cv2, mask):
    _, mask = cv2.threshold(mask, 1, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return mask
    x, y, width, height = cv2.boundingRect(max(contours, key=cv2.contourArea))
    grow = max(3, min(18, round(min(width, height) * 0.06)))
    kernel_size = grow * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    return cv2.dilate(mask, kernel, iterations=1)


def _inpaint_roi(cv2, image, mask, radius: int | None, algorithm: str):
    xs, ys = cv2.findNonZero(mask).reshape(-1, 2).T
    x1, x2 = int(xs.min()), int(xs.max())
    y1, y2 = int(ys.min()), int(ys.max())

    selection_width = x2 - x1 + 1
    selection_height = y2 - y1 + 1
    if radius is None:
        radius = max(3, min(16, round(min(selection_width, selection_height) * 0.05)))

    pad = max(radius * 2, 8)
    height, width = image.shape[:2]
    left = max(0, x1 - pad)
    top = max(0, y1 - pad)
    right = min(width, x2 + pad + 1)
    bottom = min(height, y2 + pad + 1)

    flag = cv2.INPAINT_TELEA
    if algorithm.lower() == "ns":
        flag = cv2.INPAINT_NS

    roi = image[top:bottom, left:right]
    roi_mask = mask[top:bottom, left:right]
    inpainted_roi = _fill_smooth_background(cv2, roi, roi_mask)
    if inpainted_roi is None:
        inpainted_roi = cv2.inpaint(roi, roi_mask, radius, flag)
    result = image.copy()
    result[top:bottom, left:right] = _blend_inpainted_roi(cv2, roi, inpainted_roi, roi_mask)
    return result


def _blend_inpainted_roi(cv2, original, inpainted, mask):
    blend_mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=2.0, sigmaY=2.0)
    blend_mask = blend_mask.astype("float32") / 255.0
    blend_mask = blend_mask[:, :, None]
    blended = inpainted.astype("float32") * blend_mask + original.astype("float32") * (1.0 - blend_mask)
    return blended.clip(0, 255).astype("uint8")


def _fill_smooth_background(cv2, roi, mask):
    ring = _mask_boundary_ring(cv2, mask)
    if cv2.countNonZero(ring) < 20:
        return None

    color = _dominant_boundary_color(roi, ring)
    if color is None:
        return None

    filled = roi.copy()
    filled[mask > 0] = color
    return filled


def _dominant_boundary_color(roi, ring, bucket_size: int = 16, min_share: float = 0.45):
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return None

    pixels = roi[ring > 0]
    if len(pixels) < 20:
        return None

    buckets = pixels // bucket_size
    bucket_keys, counts = np.unique(buckets, axis=0, return_counts=True)
    winner_index = int(counts.argmax())
    if counts[winner_index] / len(pixels) < min_share:
        return None

    winner = bucket_keys[winner_index]
    matching_pixels = pixels[np.all(buckets == winner, axis=1)]
    return np.median(matching_pixels, axis=0).astype("uint8")


def _mask_boundary_ring(cv2, mask):
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    outer = cv2.dilate(mask, kernel, iterations=1)
    return cv2.subtract(outer, mask)


def _read_image(cv2, np, path: Path, flags: int):
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def _write_image(cv2, path: Path, image) -> bool:
    suffix = path.suffix or ".png"
    success, encoded = cv2.imencode(suffix, image)
    if not success:
        return False
    try:
        encoded.tofile(str(path))
    except OSError:
        return False
    return True
