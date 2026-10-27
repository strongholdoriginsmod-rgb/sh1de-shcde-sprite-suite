"""Composite generated material with a feather that stays inside the hard mask."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from background_v2_masked_edit import _cover_resize, _crop_box, _rgba


def compose(
    original_path: Path,
    generated_path: Path,
    mask_path: Path,
    output_path: Path,
    crop_box: tuple[int, int, int, int],
    inner_feather: float,
) -> dict[str, object]:
    original = _rgba(original_path)
    generated = _rgba(generated_path)
    with Image.open(mask_path) as image:
        hard = np.asarray(image.convert("L"), dtype=np.uint8) > 0
    size = (crop_box[2] - crop_box[0], crop_box[3] - crop_box[1])
    if hard.shape != (size[1], size[0]):
        raise RuntimeError(f"Mask {hard.shape[::-1]} does not match crop {size}")
    generated = _cover_resize(generated, size)
    source_region = original.crop(crop_box)
    generated.putalpha(source_region.getchannel("A"))

    distance = ndi.distance_transform_edt(hard)
    weights = np.clip(distance / max(inner_feather, 1.0), 0.0, 1.0)
    weights *= hard
    blend = Image.fromarray(np.round(weights * 255).astype(np.uint8), mode="L")
    region = Image.composite(generated, source_region, blend)
    result = original.copy()
    result.paste(region, crop_box[:2])
    result.putalpha(original.getchannel("A"))

    source_array = np.asarray(original)
    result_array = np.asarray(result)
    full_mask = np.zeros(source_array.shape[:2], dtype=bool)
    full_mask[crop_box[1] : crop_box[3], crop_box[0] : crop_box[2]] = hard
    unchanged = np.array_equal(source_array[~full_mask], result_array[~full_mask])
    alpha_equal = np.array_equal(source_array[..., 3], result_array[..., 3])
    if not unchanged or not alpha_equal:
        raise RuntimeError("Hard-mask or alpha preservation failed")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path)
    changed = np.any(source_array != result_array, axis=2)
    return {
        "output": str(output_path),
        "size": list(result.size),
        "hard_mask_pixels": int(full_mask.sum()),
        "changed_pixels": int(changed.sum()),
        "outside_mask_changed_pixels": int((changed & ~full_mask).sum()),
        "outside_mask_bit_exact": unchanged,
        "alpha_bit_exact": alpha_equal,
        "inner_feather": inner_feather,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--mask", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--crop-box", type=_crop_box, required=True)
    parser.add_argument("--inner-feather", type=float, default=48.0)
    args = parser.parse_args()
    report = compose(
        args.original,
        args.generated,
        args.mask,
        args.output,
        args.crop_box,
        args.inner_feather,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
