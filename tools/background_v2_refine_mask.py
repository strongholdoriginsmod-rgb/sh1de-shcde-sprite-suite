"""Build narrow refinement masks for iterative image-generation passes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from background_v2_masked_edit import _crop_box, _rgba


def _disk(radius: int) -> np.ndarray:
    yy, xx = np.ogrid[-radius : radius + 1, -radius : radius + 1]
    return (xx * xx + yy * yy) <= radius * radius


def make_refinement_assets(
    source: Path,
    base_mask_path: Path,
    crop_box: tuple[int, int, int, int],
    output_dir: Path,
    prefix: str,
    outer_radius: int,
    inner_width: int,
) -> dict[str, object]:
    original = _rgba(source)
    roi = original.crop(crop_box)
    with Image.open(base_mask_path) as image:
        base = np.asarray(image.convert("L"), dtype=np.uint8) > 0
    if base.shape != (roi.height, roi.width):
        raise RuntimeError(
            f"Base mask {base.shape[::-1]} does not match crop {roi.size}"
        )

    outer = ndi.binary_dilation(base, structure=_disk(outer_radius))
    inner = ndi.binary_erosion(base, structure=_disk(inner_width))
    ring = outer & ~inner
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

    mask = Image.fromarray(ring.astype(np.uint8) * 255, mode="L")
    mask.save(mask_path)
    guide = Image.new("RGB", roi.size, "black")
    guide.paste("white", mask=mask)
    guide.save(guide_path)

    magenta = Image.new("RGB", roi.size, (255, 0, 170))
    alpha = mask.point(lambda value: round(value * 0.58))
    preview = Image.composite(magenta, roi.convert("RGB"), alpha)
    preview.save(preview_path)
    return {
        "source": str(source),
        "crop_box": list(crop_box),
        "crop_size": list(roi.size),
        "outer_radius": outer_radius,
        "inner_width": inner_width,
        "editable_pixels": int(ring.sum()),
        "crop": str(crop_path),
        "crop_imagegen": str(crop_jpg_path),
        "mask": str(mask_path),
        "mask_guide": str(guide_path),
        "preview": str(preview_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--base-mask", type=Path, required=True)
    parser.add_argument("--crop-box", type=_crop_box, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--outer-radius", type=int, default=5)
    parser.add_argument("--inner-width", type=int, default=16)
    args = parser.parse_args()
    report = make_refinement_assets(
        source=args.source,
        base_mask_path=args.base_mask,
        crop_box=args.crop_box,
        output_dir=args.output,
        prefix=args.prefix,
        outer_radius=args.outer_radius,
        inner_width=args.inner_width,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
