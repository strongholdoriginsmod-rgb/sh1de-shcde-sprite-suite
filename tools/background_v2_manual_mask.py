"""Create registered polygon masks and generator references for V2 edits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

from background_v2_masked_edit import _crop_box, _rgba


def _polygon(value: str) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for pair in value.split(";"):
        x, y = pair.split(",", 1)
        points.append((int(x.strip()), int(y.strip())))
    if len(points) < 3:
        raise argparse.ArgumentTypeError("polygon needs at least three points")
    return points


def make_assets(
    source: Path,
    crop_box: tuple[int, int, int, int],
    polygons: list[list[tuple[int, int]]],
    subtract_masks: list[Path],
    output_dir: Path,
    prefix: str,
    erode: int,
    dilate: int,
) -> dict[str, object]:
    original = _rgba(source)
    roi = original.crop(crop_box)
    mask_image = Image.new("L", roi.size, 0)
    draw = ImageDraw.Draw(mask_image)
    for polygon in polygons:
        draw.polygon(polygon, fill=255)
    mask = np.asarray(mask_image, dtype=np.uint8) > 0
    if dilate:
        mask = ndi.binary_dilation(mask, iterations=dilate)
    if erode:
        mask = ndi.binary_erosion(mask, iterations=erode)
    for path in subtract_masks:
        with Image.open(path) as loaded:
            locked = np.asarray(loaded.convert("L"), dtype=np.uint8) > 0
        if locked.shape != mask.shape:
            raise RuntimeError(
                f"Subtract mask {path} size {locked.shape[::-1]} != {roi.size}"
            )
        mask &= ~locked
    mask &= np.asarray(roi.getchannel("A"), dtype=np.uint8) > 0

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
    mask_image = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
    mask_image.save(mask_path)
    guide = Image.new("RGB", roi.size, "black")
    guide.paste("white", mask=mask_image)
    guide.save(guide_path)
    magenta = Image.new("RGB", roi.size, (255, 0, 170))
    alpha = mask_image.point(lambda value: round(value * 0.56))
    Image.composite(magenta, roi.convert("RGB"), alpha).save(preview_path)
    return {
        "source": str(source),
        "crop_box": list(crop_box),
        "crop_size": list(roi.size),
        "polygon_count": len(polygons),
        "subtract_masks": [str(path) for path in subtract_masks],
        "editable_pixels": int(mask.sum()),
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
    parser.add_argument("--polygon", type=_polygon, action="append", required=True)
    parser.add_argument("--subtract-mask", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--erode", type=int, default=0)
    parser.add_argument("--dilate", type=int, default=0)
    args = parser.parse_args()
    report = make_assets(
        source=args.source,
        crop_box=args.crop_box,
        polygons=args.polygon,
        subtract_masks=args.subtract_mask,
        output_dir=args.output,
        prefix=args.prefix,
        erode=args.erode,
        dilate=args.dilate,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
