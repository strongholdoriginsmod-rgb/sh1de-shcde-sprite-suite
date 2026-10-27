"""Bruecke zum HTML-Sprite-Editor (Stronghold Sprite Editor 1.0) - hin und zurueck.

Hin (``export``): eine Gruppe oder ein Frameblock aus dem Asset-Katalog wird so
verpackt, wie der Editor ihn importiert:

  <name>.zip            Farb-PNGs + _m-Masken + source-meta.json (Pivots, PPU)
                        -> Editor: Importieren > PNG-Serie / ZIP
  <name>-ziel.zip       Crusader-Referenzen + target-meta.json
                        -> Editor: Importieren > SHCDE-Zielreferenzen
  <name>-zuordnung.csv  Zielzuordnung (Quelle -> Ziel, Pivot, PPU)
                        -> Editor: Importieren > Zielzuordnung (CSV)

Der Editor verlangt Zielnamen im Muster ``gruppe-index``. Gruppen mit
Leerzeichen-Namen (``tile_buildings2 1198``) und Alt-Frames (``body_x-7x``)
werden dafuer umbenannt; Alt-Frames erhalten Index+900000. Die Zuordnung liegt
in work/editor/bruecke.json und macht den Rueckweg eindeutig.

Zurueck (``import``): Modpaket-ZIP/SEMOD (Override/Sprites/...), Tiles-ZIP,
.shsprite-Projekt oder ein Ordner mit PNGs. Jedes Bild wird auf seinen
Crusader-Platz eingepasst (gleiche Leinwand exakt, sonst am Fusspunkt aus den
Editor-Pivots) und landet in der Arbeitskopie des Katalogs. Danach im Katalog
'anwenden'.

    python tools/editor_bruecke.py export tile_buildings2 --von 1192 --bis 1239 --seite geliefert
    python tools/editor_bruecke.py import Downloads/MeinMod.zip
    python tools/editor_bruecke.py oeffnen
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import webbrowser
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import asset_katalog as katalog  # noqa: E402

EDITOR_HTML = PROJECT_ROOT / "extras" / "sprite-editor" / "Stronghold_Sprite_Editor.html"
OUT = PROJECT_ROOT / "work" / "editor"
BRIDGE = OUT / "bruecke.json"
ALT_OFFSET = 900000


def say(text=""):
    print(text, flush=True)


def editor_name(native: str, group: str) -> str:
    index, alt = katalog.frame_number(native)
    safe_group = re.sub(r"[^A-Za-z0-9_]", "_", group)
    if not safe_group[:1].isalpha():
        safe_group = "g" + safe_group
    return f"{safe_group}-{index + (ALT_OFFSET if alt else 0)}"


def load_bridge() -> dict:
    return katalog.load_json(BRIDGE, {"namen": {}})


def remember(names: dict[str, tuple]) -> None:
    data = load_bridge()
    for ename, (group, native, size, pivot) in names.items():
        data["namen"][ename] = {"gruppe": group, "name": native, "groesse": size, "pivot": pivot}
    katalog.save_json(BRIDGE, data)


def side_directory(group: str, side: str) -> tuple[Path, str]:
    if side == "arbeit":
        return katalog.ensure_work(group), "crusader"
    katalog.ensure_side(group, side)
    return katalog.side_dir(side, group), side


def cmd_export(args) -> int:
    group = args.gruppe
    directory, geometry = side_directory(group, args.seite)
    frames = katalog.index_of(directory).get("frames", [])
    if args.von is not None or args.bis is not None:
        lo = args.von if args.von is not None else -1
        hi = args.bis if args.bis is not None else 10 ** 9
        frames = [f for f in frames if lo <= katalog.frame_number(str(f["name"]))[0] <= hi]
    if not frames:
        say("Keine Frames im gewaehlten Bereich.")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    stem = args.name or f"{katalog.slug(group)}-{args.seite}" + (
        f"-{args.von}-{args.bis}" if args.von is not None or args.bis is not None else "")
    source_zip, target_zip, csv_path = OUT / f"{stem}.zip", OUT / f"{stem}-ziel.zip", OUT / f"{stem}-zuordnung.csv"
    names: dict[str, tuple] = {}
    meta, target_meta, rows = [], [], []
    katalog.ensure_side(group, "crusader")
    crusader = katalog.side_dir("crusader", group)
    with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_STORED) as src, \
            zipfile.ZipFile(target_zip, "w", zipfile.ZIP_STORED) as ref:
        for frame in frames:
            native = str(frame["name"])
            ename = editor_name(native, group)
            w, h, px, py = katalog.pivot_of(frame, geometry)
            from PIL import Image as _Image
            with _Image.open(directory / frame["file"]) as _probe:
                size = list(_probe.size)
            names[ename] = (group, native, size, {"x": px, "y": py})
            src.write(directory / frame["file"], f"{ename}.png")
            if frame.get("mask_file") and (directory / frame["mask_file"]).is_file():
                src.write(directory / frame["mask_file"], f"{ename}_m.png")
            meta.append({"name": ename, "pivot": {"x": px, "y": py}})
            centry = katalog.frame_entry(crusader, native)
            if centry is not None:
                cw, ch, cpx, cpy = katalog.pivot_of(centry, "crusader")
                ref.write(crusader / centry["file"], f"{ename}.png")
                target_meta.append({"name": ename, "pivot": {"x": cpx, "y": cpy}})
                rows.append([f"{ename}.png", ename, cpx, cpy, 64, 0, 0])
        src.writestr("source-meta.json", json.dumps({"pixelsPerUnit": 64, "frames": meta}))
        ref.writestr("target-meta.json", json.dumps({"pixelsPerUnit": 64, "frames": target_meta}))
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["source", "target", "pivot_x", "pivot_y", "ppu", "offset_x", "offset_y"])
        writer.writerows(rows)
    remember(names)
    say(f"{len(frames)} Frames fuer den Editor verpackt:")
    say(f"  {source_zip}   (Importieren > PNG-Serie / ZIP)")
    say(f"  {target_zip}   (Importieren > SHCDE-Zielreferenzen)")
    say(f"  {csv_path}   (Importieren > Zielzuordnung)")
    say("Im Editor danach: Modpaket als ZIP ausgeben - und hier mit 'import' zurueckholen.")
    return 0


def resolve_native(name: str) -> tuple[str, str] | None:
    stem = PurePosixPath(name).name
    stem = re.sub(r"\.png$", "", stem, flags=re.IGNORECASE)
    known = load_bridge().get("namen", {})
    if stem in known:
        return known[stem]["gruppe"], known[stem]["name"]
    match = re.fullmatch(r"(.+?)[- ](\d+)(x?)", stem)
    if not match:
        return None
    group, index, alt = match.group(1), int(match.group(2)), bool(match.group(3))
    if index >= ALT_OFFSET:
        index, alt = index - ALT_OFFSET, True
    groups = {g.casefold(): g for g in katalog.known_groups()}
    real = groups.get(group.casefold()) or groups.get(group.replace("_", " ").casefold())
    if real is None:
        return None
    return real, katalog.native_name(real, index, alt)


def collect_images(path: Path) -> list[dict]:
    """[{name, bild(bytes), maske(bytes|None), pivot(dict|None)}] aus jedem Editorformat."""
    items: dict[str, dict] = {}

    def add(name: str, data: bytes, pivot=None):
        stem = PurePosixPath(name).name
        is_mask = stem.lower().endswith("_m.png")
        key = stem[:-6] if is_mask else stem[:-4]
        entry = items.setdefault(key, {"name": key, "bild": None, "maske": None, "pivot": None})
        entry["maske" if is_mask else "bild"] = data
        if pivot is not None:
            entry["pivot"] = pivot

    if path.is_dir():
        for png in sorted(path.rglob("*.png")):
            add(png.name, png.read_bytes())
    elif path.suffix.lower() == ".png":
        add(path.name, path.read_bytes())
    else:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "project.json" in names:  # .shsprite
                project = json.loads(archive.read("project.json"))
                assets = {a["id"]: a["path"] for a in project.get("assets", [])}
                for frame in project.get("frames", []):
                    if not frame.get("visible", True):
                        continue
                    target = frame.get("targetName") or frame.get("name", "")
                    target = re.sub(r"\.png$", "", str(target))
                    add(target + ".png", archive.read(assets[frame["imageId"]]), frame.get("pivot"))
                    if frame.get("maskId") in assets:
                        add(target + "_m.png", archive.read(assets[frame["maskId"]]))
            else:
                meta = {}
                for candidate in names:
                    if candidate.endswith("source-meta.json") or candidate.endswith("target-meta.json"):
                        for row in json.loads(archive.read(candidate)).get("frames", []):
                            meta[str(row.get("name"))] = row.get("pivot")
                for name in names:
                    if name.lower().endswith(".png") and "/Atlas/" not in name:
                        stem = PurePosixPath(name).name[:-4]
                        add(name, archive.read(name), meta.get(stem.removesuffix("_m")))
    return [item for item in items.values() if item["bild"] is not None]


def cmd_import(args) -> int:
    from PIL import Image

    path = Path(args.datei)
    items = collect_images(path)
    if not items:
        say("Keine Bilder gefunden (erwartet: Modpaket-ZIP, Tiles-ZIP, .shsprite, Ordner oder PNG).")
        return 1
    done, skipped = 0, []
    touched: set[str] = set()
    for item in items:
        resolved = resolve_native(item["name"])
        if resolved is None:
            skipped.append(item["name"])
            continue
        group, native = resolved
        try:
            canvas, cfoot, entry = katalog.target_geometry(group, native)
        except SystemExit as exc:
            skipped.append(f"{item['name']} ({exc})")
            continue
        image = Image.open(io.BytesIO(item["bild"])).convert("RGBA")
        if image.size == canvas:
            mode, anchor = "exakt", cfoot
        else:
            mode = "fusspunkt"
            pivot = item.get("pivot")
            remembered = load_bridge().get("namen", {}).get(re.sub(r"\.png$", "", item["name"]), {})
            if not pivot and remembered.get("pivot") and list(image.size) == remembered.get("groesse"):
                pivot = remembered["pivot"]
            if pivot:
                anchor = katalog.foot_px(image.width, image.height, float(pivot["x"]), float(pivot["y"]))
            else:
                w, h, px, py = katalog.pivot_of(entry, "crusader")
                anchor = katalog.foot_px(image.width, image.height, px, py)
        fitted, lost = katalog.fit_image(image, anchor, canvas, cfoot, mode)
        mask = None
        if item.get("maske"):
            mask = katalog.fit_image(Image.open(io.BytesIO(item["maske"])).convert("RGBA"), anchor, canvas, cfoot, mode)[0]
        katalog.place(group, native, fitted, mask, f"Editor-Import {path.name}", "behalten")
        touched.add(group)
        done += 1
        if lost:
            say(f"  {native}: {lost} Pixel ragten ueber die Crusader-Leinwand")
    say(f"{done} Bilder in die Arbeitskopie uebernommen ({', '.join(sorted(touched))}).")
    if skipped:
        say(f"WARNUNG: {len(skipped)} Bilder ohne erkennbaren Zielplatz uebersprungen: {skipped[:10]}")
    if touched:
        say("Weiter im Asset-Katalog: Vorschau pruefen, dann 'anwenden'.")
    log = OUT / "import-protokoll.jsonl"
    OUT.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"zeit": datetime.now().isoformat(timespec="seconds"), "datei": str(path),
                                 "uebernommen": done, "uebersprungen": skipped}, ensure_ascii=False) + "\n")
    return 0


def cmd_oeffnen(args) -> int:
    import os

    english = EDITOR_HTML.with_name("Stronghold_Sprite_Editor_EN.html")
    # Die zweisprachige Fassung (Umschalter oben rechts) wird bevorzugt; sie startet
    # auf Englisch und merkt sich die Wahl im Browser.
    target = english if english.is_file() and (args.sprache == "en" or os.environ.get("SEDE_SPRACHE") == "en") else EDITOR_HTML
    if not target.is_file():
        say(f"Editor fehlt: {target}")
        return 1
    webbrowser.open(target.as_uri())
    say(f"Editor geoeffnet: {target}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("export", help="Gruppe/Frameblock fuer den Editor verpacken")
    p.add_argument("gruppe")
    p.add_argument("--seite", choices=("arbeit", "geliefert", "crusader", "stronghold1"), default="arbeit")
    p.add_argument("--von", type=int)
    p.add_argument("--bis", type=int)
    p.add_argument("--name")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("import", help="Editor-Ergebnis in die Arbeitskopie zurueckholen")
    p.add_argument("datei")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("oeffnen", help="HTML-Editor im Browser oeffnen")
    p.add_argument("--sprache", choices=("de", "en"))
    p.set_defaults(func=cmd_oeffnen)
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
