"""Teilfolge der Kachelobjekte aus den Original-GM1-Dateien ableiten (config/kachelobjekt-raster.json).

SHC:DE speichert ein Gebaeude als eine 64-px-Kachel je belegtem Feld; die
Reihenfolge der Teile steht nur im klassischen GM1 (part_id/part_count und die
Bildversaetze). Fuer jede Objektgroesse N*N ist die Folge in allen tile_*.gm1
dieselbe: Teil 0 ist die vorderste Kachel, danach diagonal nach hinten.

    python tools/kachelraster_gm1.py --gm1 "<Stronghold Crusader HD>/gm"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stronghold_europe_de.gm1_classic import GM1  # noqa: E402

GROUPS = ("tile_buildings1", "tile_buildings2", "tile_castle", "tile_churches", "tile_workshops",
          "tile_goods", "tile_ruins", "tile_walls")


def layouts_from(directory: Path) -> tuple[dict[int, list], dict[int, int]]:
    layouts: dict[int, list] = {}
    conflicts: dict[int, int] = {}
    for name in GROUPS:
        path = directory / f"{name}.gm1"
        if not path.is_file():
            continue
        images = GM1(str(path)).images
        i = 0
        while i < len(images):
            head = images[i]
            count = head.part_count
            parts = images[i:i + count]
            if count > 1 and head.part_id == 0 and len(parts) == count and all(
                    p.part_id == k and p.part_count == count for k, p in enumerate(parts)):
                cx0 = parts[0].offset_x + parts[0].width / 2
                cy0 = parts[0].offset_y + parts[0].height - 8
                cells = []
                for p in parts:
                    u = (p.offset_x + p.width / 2 - cx0) * 2 / 32
                    v = (p.offset_y + p.height - 8 - cy0) * 2 / 16
                    cells.append((round((u + v) / 2), round((v - u) / 2)))
                mx, my = min(x for x, _ in cells), min(y for _, y in cells)
                cells = [[x - mx, y - my] for x, y in cells]
                if count in layouts and layouts[count] != cells:
                    conflicts[count] = conflicts.get(count, 0) + 1
                layouts.setdefault(count, cells)
                i += count
                continue
            i += 1
    return layouts, conflicts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--gm1", required=True, help="Ordner mit den tile_*.gm1 (Stronghold Crusader HD/gm)")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "config" / "kachelobjekt-raster.json"))
    args = parser.parse_args(argv)
    layouts, conflicts = layouts_from(Path(args.gm1))
    if not layouts:
        print("Keine Kachelobjekte gefunden - Pfad pruefen.")
        return 1
    Path(args.out).write_text(json.dumps({str(k): v for k, v in sorted(layouts.items())}, indent=0), encoding="utf-8")
    print(f"{len(layouts)} Objektgroessen ({', '.join(str(k) for k in sorted(layouts))}) -> {args.out}")
    if conflicts:
        print(f"WARNUNG: abweichende Folgen gefunden: {conflicts} - die erste wurde verwendet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
