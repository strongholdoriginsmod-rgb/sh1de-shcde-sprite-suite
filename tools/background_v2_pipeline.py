"""Deterministic geometry and overlay handling for European background V2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from scipy import ndimage as ndi


LANCZOS = Image.Resampling.LANCZOS
SKIRMISH_NAMES = (
    [f"SkirmishCoop{number}Map.png" for number in range(1, 4)]
    + [f"SkirmishSands{number}Map.png" for number in range(1, 8)]
    + ["SkirmishTrailMap.png", "SkirmishTrailMap2.png", "SkirmishTrailMap3.png"]
)


def _rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _disk(radius: int) -> np.ndarray:
    yy, xx = np.ogrid[-radius : radius + 1, -radius : radius + 1]
    return (xx * xx + yy * yy) <= radius * radius


def _terrain_mask(size: tuple[int, int], feather: int = 0) -> Image.Image:
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


def _route_seed(original: Image.Image) -> np.ndarray:
    rgb = np.asarray(original.convert("RGB"), dtype=np.int16)
    terrain = np.asarray(_terrain_mask(original.size), dtype=np.uint8) > 0
    boundary_distance = ndi.distance_transform_edt(terrain)
    detection_area = boundary_distance > 28
    near_black = (rgb.max(axis=2) < 43) & detection_area

    broad_dark = ndi.binary_opening(near_black, structure=_disk(7))
    candidate = near_black & ~broad_dark
    candidate = ndi.binary_closing(candidate, structure=np.ones((5, 5), bool))

    labels, _ = ndi.label(candidate, structure=np.ones((3, 3), bool))
    fallback: list[tuple[float, tuple[slice, slice], np.ndarray]] = []
    selected = np.zeros(candidate.shape, dtype=bool)
    image_width, image_height = original.size
    for label_id, slices in enumerate(ndi.find_objects(labels), start=1):
        if slices is None:
            continue
        ys, xs = slices
        component = labels[slices] == label_id
        area = int(component.sum())
        width = xs.stop - xs.start
        height = ys.stop - ys.start
        box_area = width * height
        fill = area / box_area if box_area else 1.0
        span = max(width, height)
        boundary_fraction = float(
            (boundary_distance[slices][component] < 60).mean()
        )
        colors = rgb[slices][component]
        mean_intensity = float(colors.mean())
        mean_chroma = float(
            (colors.max(axis=1) - colors.min(axis=1)).mean()
        )
        frame_like = (
            (width > image_width * 0.55 and height < image_height * 0.12)
            or (height > image_height * 0.55 and width < image_width * 0.12)
        )
        plausible_shape = (
            300 <= area <= 55_000
            and span >= 70
            and fill <= 0.23
            and boundary_fraction <= 0.70
            and not frame_like
        )
        if not plausible_shape:
            continue
        score = area * span * (1.0 - min(boundary_fraction, 0.95))
        fallback.append((score, slices, component))
        if mean_intensity < 10.5 and mean_chroma < 7.0:
            selected[slices] |= component

    if not selected.any():
        if not fallback:
            raise RuntimeError("No skirmish route seed detected")
        _, slices, component = max(fallback, key=lambda item: item[0])
        selected[slices] = component

    neighborhood = ndi.distance_transform_edt(~selected) <= 18
    selected |= candidate & neighborhood
    return selected


def skirmish_route_mask(original: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    seed = _route_seed(original)
    # The broad lock includes every anti-aliased route edge and complete mission
    # circles. Its small terrain halo is intentional: geometry wins over style.
    exact = ndi.distance_transform_edt(~seed) <= 16
    exact &= np.asarray(_terrain_mask(original.size), dtype=np.uint8) > 0
    return seed, exact


def _overlay_preview(
    original: Image.Image,
    mask: np.ndarray,
    output: Path,
    color: tuple[int, int, int] = (255, 0, 170),
) -> None:
    source = original.convert("RGB")
    overlay = Image.new("RGB", source.size, color)
    alpha = Image.fromarray((mask.astype(np.uint8) * 150), mode="L")
    preview = Image.composite(overlay, source, alpha)
    preview.thumbnail((1280, 1280), LANCZOS)
    output.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output, quality=90, optimize=True)


def audit_skirmish(source: Path, output: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for filename in SKIRMISH_NAMES:
        original = _rgba(source / filename)
        seed, exact = skirmish_route_mask(original)
        stem = Path(filename).stem
        output.mkdir(parents=True, exist_ok=True)
        Image.fromarray((exact.astype(np.uint8) * 255), mode="L").save(
            output / f"{stem}-route-lock.png"
        )
        _overlay_preview(original, exact, output / f"{stem}-route-overlay.jpg")
        records.append(
            {
                "file": filename,
                "seed_pixels": int(seed.sum()),
                "locked_pixels": int(exact.sum()),
            }
        )
    return records


def _mission_color_seed(image: np.ndarray) -> np.ndarray:
    rgb = image[..., :3].astype(np.int16)
    alpha = image[..., 3] > 12
    red = (
        (rgb[..., 0] > 105)
        & (rgb[..., 0] > rgb[..., 1] * 1.45 + 18)
        & (rgb[..., 0] > rgb[..., 2] * 1.35 + 15)
    )
    return red & alpha


def mission_overlay_mask(base: Image.Image, current: Image.Image, first: bool) -> np.ndarray:
    base_array = np.asarray(base, dtype=np.int16)
    current_array = np.asarray(current, dtype=np.int16)
    if base_array.shape != current_array.shape:
        raise RuntimeError("Mission family dimensions differ")

    difference = np.abs(current_array - base_array).max(axis=2) > 12
    difference = ndi.binary_dilation(difference, structure=_disk(3))
    color_seed = _mission_color_seed(base_array)
    # The first family image can already contain the starting flag. Include the
    # full flag/marker around its coloured heraldic seed.
    color_support = ndi.binary_dilation(color_seed, structure=_disk(18))
    mask = difference | color_support
    mask &= current_array[..., 3] > 0
    return ndi.binary_closing(mask, structure=_disk(2))


def audit_missions(source: Path, output: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    output.mkdir(parents=True, exist_ok=True)
    for family in range(1, 8):
        first_number = (family - 1) * 7 + 1
        base_name = f"HistoricalCampaign-Map-{first_number:02d}.png"
        base = _rgba(source / base_name)
        for offset in range(7):
            number = first_number + offset
            filename = f"HistoricalCampaign-Map-{number:02d}.png"
            current = _rgba(source / filename)
            mask = mission_overlay_mask(base, current, first=offset == 0)
            stem = Path(filename).stem
            Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(
                output / f"{stem}-overlay-lock.png"
            )
            _overlay_preview(
                current,
                mask,
                output / f"{stem}-overlay-preview.jpg",
                color=(0, 220, 255),
            )
            records.append(
                {
                    "file": filename,
                    "family": family,
                    "family_base": base_name,
                    "locked_pixels": int(mask.sum()),
                }
            )
    return records


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("audit-skirmish", "audit-missions"):
        child = subparsers.add_parser(command)
        child.add_argument("--source", type=Path, required=True)
        child.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "audit-skirmish":
        records = audit_skirmish(args.source, args.output)
    else:
        records = audit_missions(args.source, args.output)
    report = {"command": args.command, "count": len(records), "files": records}
    (args.output / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"command": args.command, "count": len(records)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
