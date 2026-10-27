"""Prepare exact pointed-window masks for iterative European replacements."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from background_v2_masked_edit import _crop_box, _rgba


def _luma(rgb: np.ndarray) -> np.ndarray:
    return (
        rgb[..., 0] * 0.2126
        + rgb[..., 1] * 0.7152
        + rgb[..., 2] * 0.0722
    )


def pointed_aperture(
    roi: Image.Image,
    search_box: tuple[int, int, int, int],
    threshold: float,
    center_override: float | None,
    center_end_override: float | None,
    inset: int,
    erosion: int,
) -> np.ndarray:
    rgb = np.asarray(roi.convert("RGB"), dtype=np.float32)
    height, width = rgb.shape[:2]
    x_min, y_min, x_max, y_max = search_box
    if not (0 <= x_min < x_max <= width and 0 <= y_min < y_max <= height):
        raise RuntimeError(f"Search box {search_box} is outside crop {roi.size}")

    bright = _luma(rgb) > threshold
    detection = np.zeros_like(bright)
    detection[y_min:y_max, x_min:x_max] = bright[
        y_min:y_max, x_min:x_max
    ]
    support = ndi.binary_dilation(
        detection, structure=np.ones((25, 3), dtype=bool)
    )

    left = np.full(height, np.nan)
    right = np.full(height, np.nan)
    for y in range(y_min, y_max):
        xs = np.flatnonzero(support[y])
        if xs.size >= 10:
            left[y] = np.quantile(xs, 0.006)
            right[y] = np.quantile(xs, 0.994)
    valid = np.flatnonzero(np.isfinite(left) & np.isfinite(right))
    if valid.size < 80:
        raise RuntimeError("Could not recover a pointed-window aperture")

    first, last = int(valid[0]), int(valid[-1])
    rows = np.arange(first, last + 1)
    left_data = np.interp(rows, valid, left[valid])
    right_data = np.interp(rows, valid, right[valid])
    left_curve = ndi.gaussian_filter1d(
        ndi.median_filter(left_data, size=45, mode="nearest"),
        sigma=5.0,
        mode="nearest",
    )
    right_curve = ndi.gaussian_filter1d(
        ndi.median_filter(right_data, size=45, mode="nearest"),
        sigma=5.0,
        mode="nearest",
    )
    if center_override is None:
        upper_count = max(20, round(rows.size * 0.55))
        center = float(
            np.median(
                (left_curve[:upper_count] + right_curve[:upper_count]) * 0.5
            )
        )
    else:
        center = center_override
    right_curve = np.maximum.accumulate(right_curve)
    right_curve = ndi.gaussian_filter1d(
        right_curve, sigma=3.0, mode="nearest"
    )
    center_end = center if center_end_override is None else center_end_override
    centers = np.linspace(center, center_end, rows.size)
    left_curve = 2.0 * centers - right_curve

    aperture = np.zeros((height, width), dtype=bool)
    for index, y in enumerate(rows):
        x0 = int(np.ceil(left_curve[index])) + inset
        x1 = int(np.floor(right_curve[index])) - inset
        if x1 > x0:
            aperture[y, x0 : x1 + 1] = True
    if erosion:
        aperture = ndi.binary_erosion(aperture, iterations=erosion)
    return aperture


def make_assets(
    source: Path,
    crop_box: tuple[int, int, int, int],
    search_box: tuple[int, int, int, int],
    output_dir: Path,
    prefix: str,
    threshold: float,
    center: float | None,
    center_end: float | None,
    inset: int,
    erosion: int,
) -> dict[str, object]:
    original = _rgba(source)
    roi = original.crop(crop_box)
    mask_array = pointed_aperture(
        roi, search_box, threshold, center, center_end, inset, erosion
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    crop_path = output_dir / f"{prefix}-roi.png"
    crop_jpg_path = output_dir / f"{prefix}-roi-imagegen.jpg"
    mask_path = output_dir / f"{prefix}-mask.png"
    guide_path = output_dir / f"{prefix}-mask-guide.png"
    preview_path = output_dir / f"{prefix}-mask-preview.png"

    roi.save(crop_path)
    roi.convert("RGB").save(
        crop_jpg_path, quality=96, subsampling=0, optimize=True
    )
    mask = Image.fromarray(mask_array.astype(np.uint8) * 255, mode="L")
    mask.save(mask_path)
    guide = Image.new("RGB", roi.size, "black")
    guide.paste("white", mask=mask)
    guide.save(guide_path)
    magenta = Image.new("RGB", roi.size, (255, 0, 170))
    alpha = mask.point(lambda value: round(value * 0.56))
    Image.composite(magenta, roi.convert("RGB"), alpha).save(preview_path)
    return {
        "source": str(source),
        "crop_box": list(crop_box),
        "search_box": list(search_box),
        "crop_size": list(roi.size),
        "editable_pixels": int(mask_array.sum()),
        "crop": str(crop_path),
        "crop_imagegen": str(crop_jpg_path),
        "mask": str(mask_path),
        "mask_guide": str(guide_path),
        "preview": str(preview_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--crop-box", type=_crop_box, required=True)
    parser.add_argument("--search-box", type=_crop_box, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--threshold", type=float, default=120.0)
    parser.add_argument("--center", type=float)
    parser.add_argument("--center-end", type=float)
    parser.add_argument("--inset", type=int, default=5)
    parser.add_argument("--erosion", type=int, default=2)
    args = parser.parse_args()
    report = make_assets(
        source=args.source,
        crop_box=args.crop_box,
        search_box=args.search_box,
        output_dir=args.output,
        prefix=args.prefix,
        threshold=args.threshold,
        center=args.center,
        center_end=args.center_end,
        inset=args.inset,
        erosion=args.erosion,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
