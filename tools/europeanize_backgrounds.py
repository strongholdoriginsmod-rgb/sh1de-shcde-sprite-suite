"""Prepare generated European menu backgrounds for direct game replacement.

The image model is used for artwork only. This tool enforces the mechanical
constraints that a generative model cannot guarantee:

* output dimensions and colour mode match the exported source;
* skirmish-map table, tray frame and props remain from the source;
* the source route and mission circles are copied back pixel-for-pixel;
* optional diagnostic masks and previews make the locked pixels auditable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage as ndi


LANCZOS = Image.Resampling.LANCZOS


def _open_rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _fit_exact(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize a same-aspect generator result to an exact output canvas."""
    target_width, target_height = size
    source_ratio = image.width / image.height
    target_ratio = target_width / target_height
    if source_ratio > target_ratio:
        crop_width = round(image.height * target_ratio)
        left = (image.width - crop_width) // 2
        image = image.crop((left, 0, left + crop_width, image.height))
    elif source_ratio < target_ratio:
        crop_height = round(image.width / target_ratio)
        top = (image.height - crop_height) // 2
        image = image.crop((0, top, image.width, top + crop_height))
    return image.resize(size, LANCZOS)


def _terrain_mask(size: tuple[int, int], feather: int = 24) -> Image.Image:
    """Return the inset, feathered quadrilateral inside the standard map tray."""
    width, height = size
    normalized = (
        (0.218, 0.207),
        (0.850, 0.015),
        (0.962, 0.655),
        (0.313, 0.941),
    )
    points = [(round(x * width), round(y * height)) for x, y in normalized]
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    return mask


def _route_core(original: Image.Image, terrain_mask: Image.Image) -> np.ndarray:
    """Detect the neutral-black, thin route components in a map plate."""
    rgb = np.asarray(original.convert("RGB"), dtype=np.int16)
    inside = np.asarray(terrain_mask, dtype=np.uint8) >= 245

    # Remove broad near-black shadows morphologically. The painted route has a
    # six-to-twelve-pixel core at 4K and therefore survives as a thin structure.
    yy, xx = np.ogrid[-8:9, -8:9]
    disk = (xx * xx + yy * yy) <= 64
    near_black = (rgb.max(axis=2) < 45) & inside
    broad_dark = ndi.binary_opening(near_black, structure=disk)
    candidate = near_black & ~broad_dark
    candidate = ndi.binary_closing(candidate, structure=np.ones((5, 5), bool))

    labels, _ = ndi.label(candidate, structure=np.ones((3, 3), bool))
    selected = np.zeros(candidate.shape, dtype=bool)
    for label_id, slices in enumerate(ndi.find_objects(labels), start=1):
        if slices is None:
            continue
        ys, xs = slices
        component = labels[slices] == label_id
        area = int(component.sum())
        component_width = xs.stop - xs.start
        component_height = ys.stop - ys.start
        box_area = component_width * component_height
        fill = area / box_area if box_area else 1.0
        span = max(component_width, component_height)
        if 350 <= area <= 40_000 and span >= 220 and fill <= 0.14:
            view = selected[slices]
            view |= component

    if not selected.any():
        raise RuntimeError("No route components detected; refusing an unlocked map")

    neighborhood = ndi.binary_dilation(selected, iterations=14)
    selected |= candidate & neighborhood
    return ndi.binary_dilation(selected, iterations=3)


def _save_mask(mask: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(path)


def _save_preview(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    preview = image.copy()
    preview.thumbnail((1280, 720), LANCZOS)
    preview.convert("RGB").save(path, quality=88, optimize=True)


def prepare_background(
    original_path: Path, generated_path: Path, output_path: Path
) -> dict:
    original = _open_rgba(original_path)
    generated = _fit_exact(_open_rgba(generated_path), original.size)
    if original.getchannel("A").getextrema() != (255, 255):
        generated.putalpha(original.getchannel("A"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generated.save(output_path, optimize=True)
    return {
        "kind": "background",
        "file": output_path.name,
        "width": original.width,
        "height": original.height,
        "route_locked_pixels": 0,
    }


def prepare_map(
    original_path: Path,
    generated_path: Path,
    output_path: Path,
    mask_path: Path | None = None,
    preview_path: Path | None = None,
) -> dict:
    original = _open_rgba(original_path)
    generated = _fit_exact(_open_rgba(generated_path), original.size)
    terrain_mask = _terrain_mask(original.size)

    composed = Image.composite(generated, original, terrain_mask)
    route_mask = _route_core(original, terrain_mask)
    route_support = Image.fromarray(route_mask.astype(np.uint8) * 255, mode="L")
    composed = Image.composite(original, composed, route_support)
    composed.putalpha(original.getchannel("A"))

    source_array = np.asarray(original)
    output_array = np.asarray(composed)
    locked_equal = bool(
        np.array_equal(source_array[route_mask], output_array[route_mask])
    )
    if not locked_equal:
        raise RuntimeError("Route lock verification failed")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    composed.save(output_path, optimize=True)
    if mask_path:
        _save_mask(route_mask, mask_path)
    if preview_path:
        _save_preview(composed, preview_path)

    return {
        "kind": "skirmish_map",
        "file": output_path.name,
        "width": original.width,
        "height": original.height,
        "route_locked_pixels": int(route_mask.sum()),
        "route_pixels_identical": locked_equal,
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("background", "map"):
        child = subparsers.add_parser(command)
        child.add_argument("--original", type=Path, required=True)
        child.add_argument("--generated", type=Path, required=True)
        child.add_argument("--output", type=Path, required=True)
        if command == "map":
            child.add_argument("--mask", type=Path)
            child.add_argument("--preview", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "background":
        report = prepare_background(args.original, args.generated, args.output)
    else:
        report = prepare_map(
            args.original,
            args.generated,
            args.output,
            args.mask,
            args.preview,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
