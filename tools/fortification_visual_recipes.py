"""Erzeugt den Sichtrezept-Katalog der Festungs-Mauerarten (fortification-sprites v3).

Kein Bild wird veraendert. Gemessen 2026-09-02 (SHCDE 2.80, Editor): eine
Mauer ist eine angehobene Wehrgangkachel (GM 12, Bild 97..104, Hoehe +2,813)
mit tile_walls-Chevrons als Flaechen; bildschirm-waagerechte Mauern setzen
zusaetzlich einen anim_castle-Streifen (49..62) auf die vordere Lueckenkachel
und eine Kappe (47) auf die hintere, bildschirm-senkrechte die Randstuecke
46/48. Ein Rezept setzt darum je Kachel vorhandene Frames zusammen:

* ``body``  -- der Engine-Sprite der Kachel bekommt einen anderen vorhandenen
  Frame (z. B. ein ganzes SH1-Holzwandstueck statt der Wehrgangkachel) und/oder
  einen Pixelversatz (die Kachel wird auf den Boden gesenkt);
* ``layer`` -- bis zu vier zusaetzliche Sprites je Kachel ueber die Fill-in-API
  des Spiels (z. B. der Plankenwehrgang auf der Rundholzwand);
* ``hide``  -- der Engine-Sprite wird aus dem Bild geschoben (Streifen, Kappe,
  Randstuecke, die die Variante nicht mehr braucht).

``shape`` waehlt das Stueck nach der Mauerrichtung an der Kachel: ``se``
(Nachbar in +/-x), ``sw`` (+/-y), ``h`` (+x/-y, bildschirm-waagerecht), ``v``
(+x/+y, bildschirm-senkrecht), ``any`` als Rueckfall.

Quelle ist ``config/fortification-visual-frames-v1.json`` (Abschnitt
``recipes``); Bildbereiche wie ``49-62`` und ``*`` werden hier in explizite
Zeilen aufgeloest.

Aufruf:
    python tools/fortification_visual_recipes.py [--output <dir>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "fortification-visual-frames-v1.json"
VARIANTS_PATH = PROJECT_ROOT / "config" / "fortification-variants-v1.json"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "sprites" / "derived" / "fortification-recipes-v1"
TSV_NAME = "fortification-sprites-v1.tsv"
CONFIG_SCHEMA = "stronghold-europe-de.fortification-visual-frames.v3"
SCHEMA = "stronghold-europe-de.fortification-sprites.v3"
COLUMNS = "variant_id\top\tshape\tgm\timage\ttarget_gm\ttarget_image\tdx\tdy\torder\tnote"
OPS = ("body", "layer", "hide")
# "any"/se/sw/h/v = Mauerrichtung; <achse><sinn><stufe> = Treppenstufe entlang
# der Achse (se = +/-x, sw = +/-y), Sinn = Aufstiegsrichtung, Stufe 0..3.
STAIR_SHAPES = tuple(
    f"{axis}{sense}{step}"
    for axis in ("se", "sw")
    for sense in ("+", "-")
    for step in range(4)
)
SHAPES = ("any", "se", "sw", "h", "v") + STAIR_SHAPES
MAX_FRAME = 0xFFFF
WILDCARD_IMAGE = 0xFFFF  # "*": every engine image of that GM file
MAX_OFFSET = 512
MAX_ORDER = 8
MAX_LAYERS = 4

Row = tuple[str, str, str, int, int, int, int, int, int, int, str]


def wall_variant_ids() -> set[str]:
    raw = json.loads(VARIANTS_PATH.read_text(encoding="utf-8"))
    return {
        variant["id"]
        for variant in raw["variants"]
        if variant["kind"] in {"linear_wall", "composite_wall"}
    }


def expand_images(spec: object) -> list[int]:
    """``47`` | ``"49-62"`` | ``"47,49-51"`` | ``"*"`` -> sorted unique frame indices."""
    if isinstance(spec, int):
        return [spec]
    if str(spec).strip() == "*":
        return [WILDCARD_IMAGE]
    result: set[int] = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            low, high = (int(value) for value in part.split("-", 1))
            if low > high:
                raise SystemExit(f"image range reversed: {part}")
            result.update(range(low, high + 1))
        else:
            result.add(int(part))
    if not result:
        raise SystemExit(f"empty image spec: {spec!r}")
    return sorted(result)


def parse_target(spec: object) -> tuple[int, int]:
    """``"52/355"`` -> (52, 355); ``None``/``""`` -> (0, 0) keeps the engine frame."""
    if spec in (None, "", 0):
        return (0, 0)
    gm_text, image_text = str(spec).split("/", 1)
    gm, image = int(gm_text), int(image_text)
    if not (1 <= gm <= 255 and 1 <= image <= MAX_FRAME):
        raise SystemExit(f"target out of range: {spec}")
    return (gm, image)


def build_rows(config: dict) -> list[Row]:
    if config["schema"] != CONFIG_SCHEMA:
        raise SystemExit("unexpected frame map schema")
    engine_gm = int(config["engine"]["wall_gm"])
    known = wall_variant_ids()
    rows: list[Row] = []
    bodies: set[tuple[str, str, int, int]] = set()
    layers: dict[tuple[str, str, int, int], int] = {}
    for variant_id, rules in sorted(config["recipes"].items()):
        if variant_id not in known:
            raise SystemExit(f"recipe names a non-wall variant: {variant_id}")
        for rule in rules:
            op = rule["op"]
            if op not in OPS:
                raise SystemExit(f"unknown op {op!r} in {variant_id}")
            shape = str(rule.get("shape", "any"))
            if shape not in SHAPES:
                raise SystemExit(f"unknown shape {shape!r} in {variant_id}")
            gm = int(rule.get("gm", engine_gm))
            images = expand_images(rule["image"])
            targets = rule.get("target")
            if isinstance(targets, list):
                target_cycle = [parse_target(item) for item in targets]
            else:
                target_cycle = [parse_target(targets)]
            dx = int(rule.get("dx", 0))
            dy = int(rule.get("dy", 0))
            order = int(rule.get("order", 0))
            note = str(rule.get("note", "")).replace("\t", " ").replace("\n", " ")
            if not (1 <= gm <= 255) or abs(dx) > MAX_OFFSET or abs(dy) > MAX_OFFSET or abs(order) > MAX_ORDER:
                raise SystemExit(f"rule out of range: {variant_id} {rule}")
            if op != "layer" and order != 0:
                raise SystemExit(f"only layers carry an order: {variant_id} {rule}")
            if op == "hide" and (target_cycle != [(0, 0)] or dx or dy):
                raise SystemExit(f"hide takes no target or offset: {variant_id} {rule}")
            for position, image in enumerate(images):
                if not (0 <= image <= MAX_FRAME):
                    raise SystemExit(f"image out of range: {variant_id} {image}")
                target_gm, target_image = target_cycle[position % len(target_cycle)]
                key = (variant_id, shape, gm, image)
                if op in ("body", "hide"):
                    if op == "body" and target_gm == 0 and dx == 0 and dy == 0:
                        raise SystemExit(f"body rule changes nothing: {variant_id} {image}")
                    if target_gm == gm and target_image == image:
                        raise SystemExit(f"body rule maps a frame onto itself: {variant_id} {image}")
                    if key in bodies:
                        raise SystemExit(f"duplicate body/hide rule: {key}")
                    bodies.add(key)
                else:
                    layers[key] = layers.get(key, 0) + 1
                    if layers[key] > MAX_LAYERS:
                        raise SystemExit(f"too many layers: {key}")
                rows.append((variant_id, op, shape, gm, image, target_gm, target_image, dx, dy, order, note))
    # Deterministic: body/hide before layers, layers keep their config order (slot).
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda item: (
        item[1][0], item[1][3], item[1][4], SHAPES.index(item[1][2]),
        0 if item[1][1] != "layer" else 1, item[0]))
    return [row for _, row in indexed]


def render(config: dict, rows: list[Row]) -> str:
    lines = [f"# {SCHEMA}", f"# engine\twall_gm\t{config['engine']['wall_gm']}", COLUMNS]
    for row in rows:
        lines.append("\t".join(str(value) for value in row))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    rows = build_rows(config)
    args.output.mkdir(parents=True, exist_ok=True)
    for stale in args.output.glob("*"):
        stale.unlink()
    (args.output / TSV_NAME).write_text(render(config, rows), encoding="utf-8", newline="\n")
    print(f"rules={len(rows)} output={args.output / TSV_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
