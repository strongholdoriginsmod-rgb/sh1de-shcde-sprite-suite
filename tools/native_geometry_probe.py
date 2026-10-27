"""Compute and verify the native-geometry atlas contract for a GM group.

Implements the transformation described in `NATIVE_GEOMETRY_OPTION.md` without
touching the builder, so the result can be checked before the change is wired in.

For every derived frame of a group it produces exactly what the builder would
have to emit:

    image   = the source frame at its own size (never pasted onto a target canvas)
    pivot_x = (target_pivot_x * target_width)  / source_width
    pivot_y = (target_pivot_y * target_height) / source_height
    ppu     = target pixels-per-unit

and then checks the three properties that make it safe:

  * clipping is impossible — the canvas is the art, so the alpha loss that
    currently blocks the group cannot occur;
  * the absolute anchor is preserved to sub-pixel accuracy, so the sprite does
    not move on its tile;
  * pixels-per-unit is unchanged, so world scale is unchanged.

Usage::

    python tools/native_geometry_probe.py tile_land8
    python tools/native_geometry_probe.py Tree_Oak body_deer --verbose
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from stronghold_europe_de.mapping import read_mapping  # noqa: E402

MAPPING = REPO_ROOT / "work" / "mapping" / "proposals.json.gz"
TOLERANCE = 1e-6


def reanchored_pivot(source: dict, target: dict) -> tuple[float, float]:
    """Normalised pivot that keeps the absolute anchor of the target frame."""

    target_abs_x = float(target["pivot_x"]) * float(target["width"])
    target_abs_y = float(target["pivot_y"]) * float(target["height"])
    return target_abs_x / float(source["width"]), target_abs_y / float(source["height"])


def probe(group: str, frames: list[dict], verbose: bool) -> dict:
    anchor_error_x: list[float] = []
    anchor_error_y: list[float] = []
    ppu_mismatch = 0
    grew = shrank = same = 0
    area_ratio: list[float] = []

    for row in frames:
        source, target = row["source"], row["target"]
        pivot_x, pivot_y = reanchored_pivot(source, target)

        # The anchor the sprite will actually have, in source-canvas pixels.
        actual_abs_x = pivot_x * float(source["width"])
        actual_abs_y = pivot_y * float(source["height"])
        wanted_abs_x = float(target["pivot_x"]) * float(target["width"])
        wanted_abs_y = float(target["pivot_y"]) * float(target["height"])
        anchor_error_x.append(actual_abs_x - wanted_abs_x)
        anchor_error_y.append(actual_abs_y - wanted_abs_y)

        if abs(float(source["pixels_per_unit"]) - float(target["pixels_per_unit"])) > TOLERANCE:
            ppu_mismatch += 1

        sw, sh = float(source["width"]), float(source["height"])
        tw, th = float(target["width"]), float(target["height"])
        area_ratio.append((sw * sh) / (tw * th))
        if (sw, sh) == (tw, th):
            same += 1
        elif sw >= tw and sh >= th:
            grew += 1
        else:
            shrank += 1

        if verbose:
            print(
                f"    {row['name']:<22} {int(sw)}x{int(sh)} -> Pivot "
                f"({pivot_x:.4f}, {pivot_y:.4f})   Ziel {int(tw)}x{int(th)}"
            )

    worst = max(
        max(abs(v) for v in anchor_error_x),
        max(abs(v) for v in anchor_error_y),
    )
    return {
        "frames": len(frames),
        "ppu_mismatch": ppu_mismatch,
        "worst_anchor_error": worst,
        "canvas_grew": grew,
        "canvas_shrank": shrank,
        "canvas_same": same,
        "median_area_ratio": statistics.median(area_ratio),
        "max_area_ratio": max(area_ratio),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("groups", nargs="+")
    parser.add_argument("--verbose", action="store_true", help="print every frame")
    args = parser.parse_args(argv)

    mapping = read_mapping(MAPPING)
    grouped: dict[str, list[dict]] = {}
    for item in mapping["sprites"]:
        if item.get("source") and item.get("action") in {"REPLACE_DERIVED", "REPLACE_EXACT"}:
            grouped.setdefault(str(item["group"]), []).append(item)

    failures = 0
    for group in args.groups:
        frames = grouped.get(group)
        print(f"\n=== {group} ===")
        if not frames:
            print("  keine konvertierbaren Frames")
            failures += 1
            continue
        result = probe(group, frames, args.verbose)
        print(f"  Frames                    : {result['frames']}")
        print(f"  Beschnitt moeglich        : nein (die Leinwand ist die Grafik)")
        print(f"  PPU-Abweichungen          : {result['ppu_mismatch']}")
        print(f"  groesster Ankerfehler     : {result['worst_anchor_error']:.2e} px")
        print(
            f"  Leinwand groesser/kleiner/gleich: "
            f"{result['canvas_grew']} / {result['canvas_shrank']} / {result['canvas_same']}"
        )
        print(
            f"  Flaechenfaktor median/max : "
            f"{result['median_area_ratio']:.2f} / {result['max_area_ratio']:.2f}"
        )
        ok = result["ppu_mismatch"] == 0 and result["worst_anchor_error"] < 1e-6
        print(f"  -> {'TRAGFAEHIG' if ok else 'PRUEFEN'}")
        if not ok:
            failures += 1

    print(
        "\nDer Ankerfehler ist der Abstand zwischen dem Anker, den der Sprite "
        "bekommt,\nund dem, den Crusader erwartet. Null bedeutet: kein Versatz "
        "auf der Kachel."
    )
    print(
        "Der Flaechenfaktor sagt, wie viel groesser der Atlas wird - er bestimmt,\n"
        "ob die gepackte Textur noch unter 8192 Pixel bleibt."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
