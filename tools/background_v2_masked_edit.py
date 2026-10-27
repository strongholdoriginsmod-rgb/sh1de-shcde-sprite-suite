"""Mask-first image edits with deterministic, pixel-exact preservation.

The image generator is allowed to propose pixels only for a small region of
interest.  This module normalizes that proposal and composites it into the
source while preserving every pixel outside the supplied mask and preserving
the complete source alpha channel.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage as ndi


LANCZOS = Image.Resampling.LANCZOS
BRIEFING_WINDOW_BOX = (2300, 50, 3350, 1200)


def _rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _luma(rgb: np.ndarray) -> np.ndarray:
    return (
        rgb[..., 0] * 0.2126
        + rgb[..., 1] * 0.7152
        + rgb[..., 2] * 0.0722
    )


def _briefing_window_aperture(roi: Image.Image) -> np.ndarray:
    """Recover the pointed-window aperture while excluding its stone frame."""

    rgb = np.asarray(roi.convert("RGB"), dtype=np.float32)
    height, width = rgb.shape[:2]
    bright = _luma(rgb) > 120

    # The sky visible through the open lower door is deliberately excluded.
    y_min = round(height * 0.185)
    y_max = round(height * 0.642)
    x_min = round(width * 0.16)
    x_max = round(width * 0.94)
    detection = np.zeros_like(bright)
    detection[y_min:y_max, x_min:x_max] = bright[
        y_min:y_max, x_min:x_max
    ]

    # Vertical support bridges the dark horizontal lattice bands.  Robust row
    # quantiles trace the bright aperture without following tiny stone glints.
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
    if valid.size < 100:
        raise RuntimeError("Could not recover the briefing window aperture")
    first, last = int(valid[0]), int(valid[-1])
    rows = np.arange(first, last + 1)
    left[first : last + 1] = np.interp(rows, valid, left[valid])
    right[first : last + 1] = np.interp(rows, valid, right[valid])
    left_curve = ndi.median_filter(
        left[first : last + 1], size=45, mode="nearest"
    )
    right_curve = ndi.median_filter(
        right[first : last + 1], size=45, mode="nearest"
    )
    left_curve = ndi.gaussian_filter1d(
        left_curve, sigma=5.0, mode="nearest"
    )
    right_curve = ndi.gaussian_filter1d(
        right_curve, sigma=5.0, mode="nearest"
    )

    # The right glass edge is unobstructed; the left edge contains bright
    # stone glints.  Recover the latter from the aperture's measured centre
    # symmetry, then enforce a smooth monotonic Gothic arch on both sides.
    upper_count = max(20, round(rows.size * 0.55))
    center = float(np.median((left_curve[:upper_count] + right_curve[:upper_count]) * 0.5))
    right_curve = np.maximum.accumulate(right_curve)
    right_curve = ndi.gaussian_filter1d(right_curve, sigma=3.0, mode="nearest")
    right[first : last + 1] = right_curve
    left[first : last + 1] = 2.0 * center - right_curve

    aperture = np.zeros((height, width), dtype=bool)
    inset = 5
    for y in rows:
        x0 = int(np.ceil(left[y])) + inset
        x1 = int(np.floor(right[y])) - inset
        if x1 > x0:
            aperture[y, x0 : x1 + 1] = True

    # A final erosion leaves a narrow seam of the original aperture at the
    # frame.  This guarantees that no generated stone can enter the result.
    aperture = ndi.binary_erosion(aperture, iterations=2)
    return aperture


def make_briefing_assets(
    source: Path, output_dir: Path
) -> dict[str, object]:
    original = _rgba(source)
    roi = original.crop(BRIEFING_WINDOW_BOX)
    mask = _briefing_window_aperture(roi)
    output_dir.mkdir(parents=True, exist_ok=True)

    crop_path = output_dir / "BriefingBackground-window-roi.png"
    mask_path = output_dir / "BriefingBackground-window-mask.png"
    guide_path = output_dir / "BriefingBackground-window-mask-guide.png"
    preview_path = output_dir / "BriefingBackground-window-mask-preview.png"
    roi.save(crop_path)
    mask_image = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
    mask_image.save(mask_path)

    guide = Image.new("RGB", roi.size, "black")
    guide.paste("white", mask=mask_image)
    guide.save(guide_path)

    preview = roi.convert("RGB")
    magenta = Image.new("RGB", roi.size, (255, 0, 170))
    alpha = mask_image.point(lambda value: round(value * 0.55))
    preview = Image.composite(magenta, preview, alpha)
    preview.save(preview_path)
    return {
        "source": str(source),
        "crop_box": list(BRIEFING_WINDOW_BOX),
        "crop_size": list(roi.size),
        "editable_pixels": int(mask.sum()),
        "crop": str(crop_path),
        "mask": str(mask_path),
        "mask_guide": str(guide_path),
        "preview": str(preview_path),
    }


def _cover_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_width, target_height = size
    scale = max(target_width / image.width, target_height / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)), LANCZOS
    )
    left = (resized.width - target_width) // 2
    top = (resized.height - target_height) // 2
    return resized.crop(
        (left, top, left + target_width, top + target_height)
    )


def compose_masked(
    original_path: Path,
    generated_path: Path,
    mask_path: Path,
    output_path: Path,
    crop_box: tuple[int, int, int, int] | None = None,
    feather: float = 0.0,
) -> dict[str, object]:
    original = _rgba(original_path)
    generated = _rgba(generated_path)
    with Image.open(mask_path) as loaded_mask:
        mask = loaded_mask.convert("L")

    if crop_box is None:
        target_box = (0, 0, original.width, original.height)
    else:
        target_box = crop_box
    target_size = (target_box[2] - target_box[0], target_box[3] - target_box[1])
    if mask.size != target_size:
        raise RuntimeError(
            f"Mask size {mask.size} does not match target region {target_size}"
        )
    generated = _cover_resize(generated, target_size)

    hard_mask = np.asarray(mask, dtype=np.uint8) > 0
    blend_mask = mask
    if feather > 0:
        blend_mask = mask.filter(ImageFilter.GaussianBlur(feather))

    source_region = original.crop(target_box)
    # Generated alpha is never trusted.  The source alpha is restored below.
    generated.putalpha(source_region.getchannel("A"))
    composed_region = Image.composite(generated, source_region, blend_mask)
    result = original.copy()
    result.paste(composed_region, target_box[:2])
    result.putalpha(original.getchannel("A"))

    source_array = np.asarray(original)
    result_array = np.asarray(result)
    full_mask = np.zeros(source_array.shape[:2], dtype=bool)
    full_mask[
        target_box[1] : target_box[3], target_box[0] : target_box[2]
    ] = hard_mask
    unchanged = np.array_equal(source_array[~full_mask], result_array[~full_mask])
    alpha_equal = np.array_equal(source_array[..., 3], result_array[..., 3])
    if not unchanged:
        raise RuntimeError("Pixel-exact preservation outside mask failed")
    if not alpha_equal:
        raise RuntimeError("Source alpha preservation failed")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path)
    changed = np.any(source_array != result_array, axis=2)
    outside_changed = changed & ~full_mask
    return {
        "output": str(output_path),
        "size": list(result.size),
        "mode": result.mode,
        "mask_pixels": int(full_mask.sum()),
        "changed_pixels": int(changed.sum()),
        "outside_mask_changed_pixels": int(outside_changed.sum()),
        "outside_mask_bit_exact": unchanged,
        "alpha_bit_exact": alpha_equal,
    }


def _crop_box(value: str) -> tuple[int, int, int, int]:
    items = tuple(int(item.strip()) for item in value.split(","))
    if len(items) != 4:
        raise argparse.ArgumentTypeError("crop box must be left,top,right,bottom")
    return items


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    briefing = subparsers.add_parser("make-briefing-assets")
    briefing.add_argument("--source", type=Path, required=True)
    briefing.add_argument("--output", type=Path, required=True)

    compose = subparsers.add_parser("compose")
    compose.add_argument("--original", type=Path, required=True)
    compose.add_argument("--generated", type=Path, required=True)
    compose.add_argument("--mask", type=Path, required=True)
    compose.add_argument("--output", type=Path, required=True)
    compose.add_argument("--crop-box", type=_crop_box)
    compose.add_argument("--feather", type=float, default=0.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "make-briefing-assets":
        report = make_briefing_assets(args.source, args.output)
    else:
        report = compose_masked(
            original_path=args.original,
            generated_path=args.generated,
            mask_path=args.mask,
            output_path=args.output,
            crop_box=args.crop_box,
            feather=args.feather,
        )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
