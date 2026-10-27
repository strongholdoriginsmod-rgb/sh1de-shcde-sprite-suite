"""Create review sheets and a deterministic validation report for backgrounds."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


LANCZOS = Image.Resampling.LANCZOS


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ("arialbd.ttf", "arial.ttf") if bold else ("arial.ttf",)
    for name in names:
        path = Path(os.environ.get('WINDIR', '')) / 'Fonts' / name
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _contact_sheet(paths: list[Path], output: Path, title: str) -> None:
    columns = 4
    card_width, card_height = 500, 340
    title_height = 72
    rows = math.ceil(len(paths) / columns)
    sheet = Image.new(
        "RGB",
        (columns * card_width, title_height + rows * card_height),
        (24, 25, 27),
    )
    draw = ImageDraw.Draw(sheet)
    draw.text((24, 20), title, font=_font(30, bold=True), fill=(238, 232, 217))

    for index, path in enumerate(paths):
        column = index % columns
        row = index // columns
        x = column * card_width
        y = title_height + row * card_height
        draw.rounded_rectangle(
            (x + 8, y + 8, x + card_width - 8, y + card_height - 8),
            radius=10,
            fill=(37, 39, 42),
            outline=(92, 91, 84),
            width=1,
        )
        with Image.open(path) as source:
            source = source.convert("RGB")
            dimensions = f"{source.width} x {source.height}"
            preview = ImageOps.contain(source, (468, 263), method=LANCZOS)
        image_x = x + (card_width - preview.width) // 2
        image_y = y + 18 + (263 - preview.height) // 2
        sheet.paste(preview, (image_x, image_y))
        draw.text((x + 18, y + 290), path.stem, font=_font(17, bold=True), fill="white")
        draw.text((x + 18, y + 314), dimensions, font=_font(14), fill=(182, 186, 190))

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92, optimize=True, progressive=True)


def _validate_changed(
    original_dir: Path, finished_dir: Path, mask_dir: Path
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for output_path in sorted(finished_dir.glob("*.png"), key=lambda item: item.name.lower()):
        original_path = original_dir / output_path.name
        if not original_path.is_file():
            raise FileNotFoundError(f"Original fehlt: {original_path}")
        with Image.open(original_path) as original_image, Image.open(output_path) as output_image:
            if original_image.size != output_image.size:
                raise RuntimeError(
                    f"Aufloesung stimmt nicht: {output_path.name}: "
                    f"{output_image.size} != {original_image.size}"
                )
            record: dict[str, object] = {
                "file": output_path.name,
                "width": output_image.width,
                "height": output_image.height,
                "original_sha256": _sha256(original_path),
                "replacement_sha256": _sha256(output_path),
            }

            mask_path = mask_dir / f"{output_path.stem}-route-mask.png"
            if mask_path.is_file():
                original = np.asarray(original_image.convert("RGBA"))
                replacement = np.asarray(output_image.convert("RGBA"))
                with Image.open(mask_path) as mask_image:
                    mask = np.asarray(mask_image.convert("L")) > 0
                if mask.shape != original.shape[:2]:
                    raise RuntimeError(f"Maskengroesse stimmt nicht: {mask_path.name}")
                route_equal = bool(np.array_equal(original[mask], replacement[mask]))
                if not route_equal:
                    raise RuntimeError(f"Pfadsperre verletzt: {output_path.name}")
                record.update(
                    {
                        "kind": "skirmish_map",
                        "route_locked_pixels": int(mask.sum()),
                        "route_pixels_identical": True,
                    }
                )
            else:
                record.update({"kind": "background", "route_locked_pixels": 0})
        records.append(record)
    return records


def _validate_package(original_dir: Path, package_dir: Path) -> dict[str, int]:
    originals = sorted(original_dir.glob("*.png"), key=lambda item: item.name.lower())
    packaged = sorted(package_dir.glob("*.png"), key=lambda item: item.name.lower())
    if [item.name for item in originals] != [item.name for item in packaged]:
        raise RuntimeError("Das Austauschpaket entspricht nicht dem 166-Dateien-Export")

    changed = 0
    for original_path, packaged_path in zip(originals, packaged, strict=True):
        with Image.open(original_path) as original, Image.open(packaged_path) as packaged_image:
            if original.size != packaged_image.size:
                raise RuntimeError(f"Paketaufloesung stimmt nicht: {packaged_path.name}")
        changed += _sha256(original_path) != _sha256(packaged_path)
    return {"file_count": len(packaged), "changed_count": changed}


def _write_report(
    output: Path, records: list[dict[str, object]], package: dict[str, int]
) -> None:
    maps = [record for record in records if record["kind"] == "skirmish_map"]
    lines = [
        "# Prüfbericht: europäisierte Crusader-Hintergründe",
        "",
        f"- Ersatzgrafiken: {len(records)}",
        f"- Vollständiges Austauschpaket: {package['file_count']} Dateien",
        f"- Gegenüber dem Original geändert: {package['changed_count']} Dateien",
        f"- Scharmützelkarten mit pixelgesperrtem Pfad: {len(maps)}",
        "- Auflösungen: für jede Datei identisch zum jeweiligen Original",
        "",
        "## Pixelgesperrte Scharmützelkarten",
        "",
        "| Datei | Auflösung | gesperrte Pixel | Gleichheit |",
        "|---|---:|---:|---:|",
    ]
    for record in maps:
        lines.append(
            f"| {record['file']} | {record['width']} × {record['height']} | "
            f"{record['route_locked_pixels']} | ja |"
        )
    lines.extend(
        [
            "",
            "Die Pfade wurden nicht vom Bildgenerator rekonstruiert. Gelände und Atmosphäre "
            "wurden generiert; anschließend wurden die erkannten Original-Pfadpixel "
            "deterministisch zurückkopiert und binär gegen das Original verglichen.",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-dir", type=Path, required=True)
    parser.add_argument("--finished-dir", type=Path, required=True)
    parser.add_argument("--mask-dir", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    records = _validate_changed(args.original_dir, args.finished_dir, args.mask_dir)
    package = _validate_package(args.original_dir, args.package_dir)
    maps = [args.finished_dir / record["file"] for record in records if record["kind"] == "skirmish_map"]
    others = [args.finished_dir / record["file"] for record in records if record["kind"] != "skirmish_map"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _contact_sheet(maps, args.output_dir / "Scharmuetzelkarten-Kontaktbogen.jpg", "Europäisierte Scharmützelkarten")
    _contact_sheet(others, args.output_dir / "Weitere-Hintergruende-Kontaktbogen.jpg", "Weitere europäisierte Hintergründe")

    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "package": package,
        "replacements": records,
    }
    (args.output_dir / "pruefbericht.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_report(args.output_dir / "PRUEFBERICHT.md", records, package)
    print(json.dumps({"replacements": len(records), "maps": len(maps), **package}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
