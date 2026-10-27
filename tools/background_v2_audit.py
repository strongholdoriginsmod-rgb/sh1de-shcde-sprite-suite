"""Audit every exported GUI image before the European V2 replacement pass."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


LANCZOS = Image.Resampling.LANCZOS
UNCHANGED_NAMES = {"logo1.png", "Partner_Logos.png"}
DIRECT_NAMES = {"MapEditor.png", "victory_military_small.png"}
NEUTRAL_NAMES = {
    "HistoricalCampaign-Background.png",
    "Roadmap.png",
    "SandsofTimeScoreBackground.png",
    "SkirmishMasters.png",
    "SkirmishTrail-Background.png",
    "SkirmishTrail-Sands-Background.png",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    filename = "arialbd.ttf" if bold else "arial.ttf"
    path = Path(os.environ.get('WINDIR', '')) / 'Fonts' / filename
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _classification(filename: str) -> str:
    if (
        filename.startswith("tslice")
        or filename in UNCHANGED_NAMES
        or filename in NEUTRAL_NAMES
    ):
        return "unchanged"
    if filename in DIRECT_NAMES:
        return "direct_stronghold1"
    return "generated_edit"


def _invariants(group: str, filename: str) -> list[str]:
    common = ["exact_dimensions", "source_alpha"]
    if group == "Vollbild-Hintergruende":
        return common + ["camera", "composition", "ui_negative_space"]
    if group == "Kampagnen- und Trail-Karten":
        if filename.startswith("Skirmish") and "Map" in filename:
            return common + ["table_and_tray", "route", "mission_markers"]
        return common + ["camera", "composition", "overlay_safe_zones"]
    if group == "Historische Kampagne: Kapitelbilder":
        return common + ["book_position", "cover_silhouette", "ui_negative_space"]
    if group == "Historische Kampagne: Missionskarten":
        return common + ["card_position", "route_arrows", "flags_and_markers"]
    if group == "Historische Kampagne: Zeichnungen":
        return common + ["figure_count", "poses", "scene_layout", "ink_style"]
    if filename == "ScribeUnlock.png":
        return common + ["four_to_one_crop", "panel_positions", "scribe_pose"]
    if filename == "table.png":
        return common + ["silhouette", "camera", "shadow_footprint"]
    return common + ["composition"]


def _checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    width, height = size
    yy, xx = np.indices((height, width))
    board = ((xx // cell + yy // cell) % 2).astype(np.uint8)
    values = np.where(board[..., None] == 0, 55, 78).astype(np.uint8)
    rgb = np.repeat(values, 3, axis=2)
    return Image.fromarray(rgb, mode="RGB")


def _flatten(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    background = _checkerboard(rgba.size)
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


def _contact_sheet(
    root: Path,
    frames: list[dict[str, object]],
    output: Path,
    title: str,
    columns: int,
) -> None:
    card_width, card_height = 340, 255
    title_height = 72
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new(
        "RGB",
        (columns * card_width, title_height + rows * card_height),
        (21, 22, 24),
    )
    draw = ImageDraw.Draw(sheet)
    draw.text((22, 20), title, font=_font(28, bold=True), fill=(242, 237, 222))

    for index, frame in enumerate(frames):
        column = index % columns
        row = index // columns
        x = column * card_width
        y = title_height + row * card_height
        draw.rounded_rectangle(
            (x + 6, y + 6, x + card_width - 6, y + card_height - 6),
            radius=8,
            fill=(35, 37, 40),
            outline=(83, 85, 88),
        )
        path = root / str(frame["file"])
        with Image.open(path) as source:
            dimensions = f"{source.width} x {source.height}"
            preview = ImageOps.contain(_flatten(source), (316, 178), method=LANCZOS)
        image_x = x + (card_width - preview.width) // 2
        image_y = y + 15 + (178 - preview.height) // 2
        sheet.paste(preview, (image_x, image_y))
        draw.text((x + 14, y + 202), path.stem, font=_font(14, bold=True), fill="white")
        draw.text((x + 14, y + 222), dimensions, font=_font(12), fill=(184, 188, 192))

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92, optimize=True, progressive=True)


def _inspect_image(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
        return {
            "width": rgba.width,
            "height": rgba.height,
            "mode": image.mode,
            "alpha_min": int(alpha.min()),
            "alpha_max": int(alpha.max()),
            "alpha_nonzero_fraction": round(float((alpha > 0).mean()), 8),
            "alpha_opaque_fraction": round(float((alpha == 255).mean()), 8),
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    index = json.loads((args.source / "index.json").read_text(encoding="utf-8"))
    frames = index["frames"]
    records: list[dict[str, object]] = []
    for frame in frames:
        filename = str(frame["file"])
        record = dict(frame)
        record.update(_inspect_image(args.source / filename))
        record.update(
            {
                "classification": _classification(filename),
                "invariants": _invariants(str(frame["group"]), filename),
                "sha256": _sha256(args.source / filename),
            }
        )
        if filename.startswith("HistoricalCampaign-Map-"):
            number = int(Path(filename).stem.rsplit("-", 1)[1])
            record["mission_map_family"] = (number - 1) // 7 + 1
            record["mission_in_family"] = (number - 1) % 7 + 1
        records.append(record)

    args.output.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "total": len(records),
        "classification_counts": dict(Counter(item["classification"] for item in records)),
        "group_counts": dict(Counter(str(item["group"]) for item in records)),
        "files": records,
    }
    (args.output / "inventory.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    grouped: dict[str, list[dict[str, object]]] = {}
    for record in records:
        grouped.setdefault(str(record["group"]), []).append(record)
    for group, group_frames in grouped.items():
        safe_name = "".join(character if character.isalnum() else "_" for character in group)
        columns = 5 if len(group_frames) >= 32 else 4
        _contact_sheet(
            args.source,
            group_frames,
            args.output / f"originale-{safe_name}.jpg",
            f"Originale: {group}",
            columns,
        )

    print(json.dumps(payload["classification_counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
