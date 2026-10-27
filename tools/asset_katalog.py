"""Asset-Katalog: jede Grafikgruppe thematisch einsehen, ersetzen, ergaenzen, zuruecksetzen.

Der Katalog ist die Werkbank hinter dem gleichnamigen Reiter der Universal-Suite.
Er erfindet keinen eigenen Lieferweg, sondern bedient die vorhandenen:

* Einzelbilder gehen ueber ``tools/sprites.py import`` in eine Lieferablage
  ``assets/sprites/derived/benutzer-<gruppe>`` und ueber ``profile-add`` in ein
  Profil. Die Ablage liefert ``Override/Sprites/<name>.png`` und ueberlagert den
  Atlas (``allow_atlas_shadow``) - genau der Weg der Zinnen-Leerbilder.
* Ganze Objekte aus einem anderen Spender gehen ueber
  ``config/frame-overrides.local.json`` in die Konvertierung (Huetten-Fall);
  danach muessen die Nachweise neu vermessen werden (``pin_digests.py``).

Der Lieferweg verlangt die Crusader-Leinwand je Platz. Statt ein Bild mit
anderer Groesse abzuweisen, passt der Katalog es ein: Fusspunkt auf Fusspunkt
(Standard), an einer Ecke ausgerichtet (Eckanker wie bei den Zinnen), oder
skaliert. Was dabei abgeschnitten wird, meldet er.

    python tools/asset_katalog.py kategorien
    python tools/asset_katalog.py vorbereiten tile_buildings2 --seiten crusader,stronghold1,geliefert
    python tools/asset_katalog.py ersetzen tile_buildings2 "tile_buildings2 1198" --bild haus.png
    python tools/asset_katalog.py uebernehmen body_archer body_archer-17 --quelle frame:body_archer-1 --spiegeln
    python tools/asset_katalog.py block body_archer --von 0 --nach 16 --anzahl 16 --spiegeln
    python tools/asset_katalog.py anwenden tile_buildings2
    python tools/asset_katalog.py umlenken tile_buildings2 --ziel 1192-1207 --spender 10-25
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

WORK = PROJECT_ROOT / "work" / "katalog"
SIDES = ("crusader", "stronghold1", "geliefert")
KATEGORIEN = PROJECT_ROOT / "config" / "asset-kategorien.json"
ROLLEN = PROJECT_ROOT / "config" / "asset-rollen.json"
REGISTRY = PROJECT_ROOT / "config" / "benutzer-ablagen.json"
OVERRIDES = PROJECT_ROOT / "config" / "frame-overrides.local.json"
ERWEITERUNGEN = PROJECT_ROOT / "assets" / "erweiterungen"
DEFAULT_PROFILE = "profiles/benutzer.json"
DEFAULT_BASE_PROFILE = "profiles/europe-production-bc7-v2.json"
ANCHORS = ("fusspunkt", "exakt", "oben-links", "oben-rechts", "unten-links",
           "unten-rechts", "mitte", "skalieren")

_mapping_cache: dict | None = None


# ------------------------------------------------------------------ helpers

def say(text: str = "") -> None:
    print(text, flush=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def store_for(group: str, origin: str = "derived") -> str:
    return f"assets/sprites/{origin}/benutzer-{slug(group)}"


def mapping() -> dict:
    global _mapping_cache
    if _mapping_cache is None:
        path = PROJECT_ROOT / "work" / "mapping" / "proposals.json.gz"
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                _mapping_cache = json.load(stream)
        except OSError:
            say(f"Hinweis: kein Mapping unter {path} - zuerst 'Spiele einlesen'.")
            _mapping_cache = {"sprites": []}
    return _mapping_cache


def group_rows(group: str) -> list[dict]:
    rows = [row for row in mapping().get("sprites", []) if row.get("group") == group]
    rows.sort(key=lambda row: frame_sort_key(str(row.get("name"))))
    return rows


def frame_number(name: str) -> tuple[int, bool]:
    """Index und Alt-Kennung aus einem nativen Namen ('g 012', 'g-7', 'g-7x')."""
    match = re.search(r"[- ](\d+)(x?)$", name)
    if not match:
        return -1, False
    return int(match.group(1)), bool(match.group(2))


def frame_sort_key(name: str):
    index, alt = frame_number(name)
    return (alt, index, name)


def name_style(group: str) -> tuple[str, int]:
    """('dash', 0) oder ('space', Stellen) - aus den echten Namen der Gruppe."""
    for row in mapping().get("sprites", []):
        if row.get("group") != group:
            continue
        name = str(row.get("name"))
        if name.startswith(group + "-"):
            return "dash", 0
        tail = name[len(group) + 1:]
        if tail.isdigit() and tail.startswith("0"):
            return "space", len(tail)
    return "space", 3


def native_name(group: str, index: int, alt: bool = False) -> str:
    style, width = name_style(group)
    if style == "dash":
        return f"{group}-{index}{'x' if alt else ''}"
    return f"{group} {index:0{max(width, 3)}d}" if index < 10 ** max(width, 3) else f"{group} {index}"


def parse_range(text: str) -> list[int]:
    out: list[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def run_tool(args: list[str]) -> int:
    say("$ " + " ".join(str(a) for a in args))
    result = subprocess.run([sys.executable, *map(str, args)], cwd=PROJECT_ROOT)
    return result.returncode


def target_game_dir() -> Path | None:
    try:
        config = tomllib.loads((PROJECT_ROOT / "config" / "installations.local.toml").read_text(encoding="utf-8"))
        return Path(config["target"]["game_dir"])
    except (OSError, ValueError, KeyError):
        return None


def default_mod_dir() -> Path | None:
    game = target_game_dir()
    candidates = []
    if game is not None:
        candidates.append(game / "BepInEx" / "plugins" / "StrongholdEuropeDE")
    dist = PROJECT_ROOT / "dist"
    if dist.is_dir():
        candidates.extend(sorted((p / "StrongholdEuropeDE" for p in dist.iterdir() if p.is_dir()),
                                 key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True))
    candidates.append(PROJECT_ROOT.parent / "daten" / "mod-neuester-stand" / "StrongholdEuropeDE")
    for candidate in candidates:
        if (candidate / "Runtime" / "AssetBundles" / "index.json").is_file():
            return candidate
    return None


# ------------------------------------------------------------------ categories

def known_groups() -> list[str]:
    groups = {str(row.get("group")) for row in mapping().get("sprites", [])}
    return sorted(g for g in groups if g and not g.endswith("Sprites_m") and not g.startswith("UI"))


def category_tree() -> dict:
    config = load_json(KATEGORIEN, {"kategorien": [], "erweiterungen": []})
    counts: dict[str, dict] = {}
    for row in mapping().get("sprites", []):
        entry = counts.setdefault(str(row.get("group")), {"frames": 0, "aktionen": {}})
        entry["frames"] += 1
        action = str(row.get("action"))
        entry["aktionen"][action] = entry["aktionen"].get(action, 0) + 1
    registry = load_json(REGISTRY, {"ablagen": {}}).get("ablagen", {})
    user_groups = {spec.get("gruppe") for spec in registry.values()}
    overrides = load_json(OVERRIDES, {"gruppen": {}}).get("gruppen", {})
    seen: set[str] = set()

    def decorate(group: str) -> dict:
        seen.add(group)
        info = counts.get(group, {"frames": 0, "aktionen": {}})
        return {"gruppe": group, **info, "benutzerablage": group in user_groups,
                "umlenkungen": len(overrides.get(group, []))}

    tree = []
    for cat in config.get("kategorien", []):
        node = {"name": cat.get("name"), "unterkategorien": []}
        for sub in cat.get("unterkategorien", []):
            node["unterkategorien"].append({
                "name": sub.get("name"),
                "gruppen": [decorate(g) for g in sub.get("gruppen", [])],
            })
        if cat.get("gruppen"):
            node["unterkategorien"].append({"name": "(direkt)", "gruppen": [decorate(g) for g in cat["gruppen"]]})
        tree.append(node)
    rest = [g for g in known_groups() if g not in seen]
    if rest:
        tree.append({"name": "Sonstiges", "unterkategorien": [{"name": "nicht zugeordnet", "gruppen": [decorate(g) for g in rest]}]})
    ext = []
    for manifest in sorted(ERWEITERUNGEN.glob("*/*/erweiterung.json")):
        data = load_json(manifest, {})
        ext.append({"name": data.get("name"), "kategorie": data.get("kategorie"),
                    "bilder": len(data.get("bilder", [])), "bindung": data.get("bindung"),
                    "ordner": manifest.parent.relative_to(PROJECT_ROOT).as_posix()})
    if ext:
        tree.append({"name": "Erweiterungen", "erweiterungen": ext, "unterkategorien": []})
    return {"kategorien": tree}


def cmd_kategorien(args) -> int:
    tree = category_tree()
    if args.json:
        print(json.dumps(tree, ensure_ascii=False))
        return 0
    for cat in tree["kategorien"]:
        say(cat["name"])
        for sub in cat["unterkategorien"]:
            say(f"  {sub['name']}")
            for g in sub["gruppen"]:
                flags = (" [Benutzerablage]" if g["benutzerablage"] else "") + (
                    f" [{g['umlenkungen']} Umlenkungen]" if g["umlenkungen"] else "")
                say(f"    {g['gruppe']:<28} {g['frames']:>6} Frames{flags}")
        for e in cat.get("erweiterungen", []):
            say(f"  * {e['name']} ({e['bilder']} Bilder) -> {e['bindung'] or 'ungebunden'}")
    return 0


def cmd_kategorie(args) -> int:
    config = load_json(KATEGORIEN, {"schema": "stronghold-europe.asset-kategorien.v1", "kategorien": [], "erweiterungen": []})
    cats = config.setdefault("kategorien", [])

    def find(name, create=False):
        for cat in cats:
            if cat.get("name") == name:
                return cat
        if create:
            cat = {"name": name, "unterkategorien": []}
            cats.append(cat)
            return cat
        return None

    if args.aktion == "neu":
        cat = find(args.name, create=True)
        if args.unter:
            subs = cat.setdefault("unterkategorien", [])
            if not any(s.get("name") == args.unter for s in subs):
                subs.append({"name": args.unter, "gruppen": []})
        say(f"Kategorie angelegt: {args.name}{' / ' + args.unter if args.unter else ''}")
    elif args.aktion == "zuordnen":
        for cat in cats:
            for sub in cat.get("unterkategorien", []):
                if args.gruppe in sub.get("gruppen", []):
                    sub["gruppen"].remove(args.gruppe)
        cat = find(args.name, create=True)
        subs = cat.setdefault("unterkategorien", [])
        target = next((s for s in subs if s.get("name") == (args.unter or "(direkt)")), None)
        if target is None:
            target = {"name": args.unter or "(direkt)", "gruppen": []}
            subs.append(target)
        target["gruppen"].append(args.gruppe)
        say(f"{args.gruppe} -> {args.name}{' / ' + args.unter if args.unter else ''}")
    elif args.aktion == "entfernen":
        config["kategorien"] = [c for c in cats if c.get("name") != args.name]
        say(f"Kategorie entfernt: {args.name} (ihre Gruppen erscheinen unter 'Sonstiges')")
    save_json(KATEGORIEN, config)
    return 0


# ------------------------------------------------------------------ exports

def side_dir(side: str, group: str) -> Path:
    return WORK / side / group


def work_dir(group: str) -> Path:
    return WORK / "arbeit" / group


def export_delivered(group: str, mod_dir: Path | None) -> int:
    import numpy as np
    import UnityPy
    from PIL import Image

    mod_dir = mod_dir or default_mod_dir()
    if mod_dir is None:
        say("Kein ausgelieferter Stand gefunden (weder im Zielspiel noch unter dist/). Seite 'geliefert' uebersprungen.")
        return 0
    index_path = mod_dir / "Runtime" / "AssetBundles" / "index.json"
    index = load_json(index_path, {"groups": []})
    entry = next((g for g in index.get("groups", []) if str(g.get("group", "")).casefold() == group.casefold()), None)
    if entry is None:
        say(f"{group} ist in {mod_dir} nicht als Atlas ausgeliefert (dort liefert das Spiel das Original).")
        return 0
    bundle = mod_dir / entry["bundle_path"]
    env = UnityPy.load(str(bundle))
    atlas = None
    textures: dict[str, np.ndarray] = {}
    for obj in env.objects:
        if obj.type.name == "TextAsset":
            script = obj.read().m_Script
            if isinstance(script, (bytes, bytearray)):
                script = bytes(script).decode("utf-8")
            try:
                atlas = json.loads(script)
            except ValueError:
                pass
        elif obj.type.name == "Texture2D":
            data = obj.read()
            textures[str(data.m_Name)] = np.asarray(data.image.convert("RGBA"))
    if atlas is None or not textures:
        say(f"Bundle {bundle.name} ist nicht lesbar - uebersprungen.")
        return 1

    def page_texture(page: dict, kind: str):
        spec = page.get(kind)
        if not spec:
            return None
        wanted = Path(spec.get("asset_path", "")).stem
        for name, pixels in textures.items():
            if name == wanted or name.endswith(wanted):
                return pixels
        return next(iter(textures.values())) if kind == "main" and len(textures) == 1 else None

    pages = {page["id"]: page for page in atlas.get("pages", [])}
    out = side_dir("geliefert", group)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    frames_out = []
    for frame in atlas.get("frames", []):
        page = pages.get(frame.get("page", 0), {})
        rect = frame["rect"]
        name = str(frame.get("name") or native_name(group, int(frame["index"]), bool(frame.get("alt"))))
        record = {"name": name, "file": name + ".png", "width": rect["width"], "height": rect["height"],
                  "pivot_x": frame["pivot"]["x"], "pivot_y": frame["pivot"]["y"],
                  "pixels_per_unit": frame.get("pixels_per_unit", 64.0)}
        for kind, suffix in (("main", ".png"), ("mask", "_m.png")):
            pixels = page_texture(page, kind)
            if pixels is None:
                continue
            height = pixels.shape[0]
            top = height - (rect["y"] + rect["height"])
            crop = pixels[top:height - rect["y"], rect["x"]:rect["x"] + rect["width"]]
            Image.fromarray(crop).save(out / (name + suffix))
            if kind == "mask":
                record["mask_file"] = name + "_m.png"
        frames_out.append(record)
    save_json(out / "index.json", {"schema_version": 1, "group": group, "game": "geliefert",
                                   "quelle": str(mod_dir), "bundle_sha256": entry.get("bundle_sha256"),
                                   "frames": frames_out})
    say(f"geliefert: {len(frames_out)} Frames aus {bundle.name} nach {out}")
    return 0


def ensure_side(group: str, side: str, refresh: bool = False, mod_dir: Path | None = None) -> int:
    target = side_dir(side, group)
    if target.is_dir() and (target / "index.json").is_file() and not refresh:
        return 0
    if side == "geliefert":
        return export_delivered(group, mod_dir)
    args = ["tools/sprites.py", "export", group, "--game", side, "--out", str(WORK / side)]
    if target.exists():
        args.append("--replace")
    return run_tool(args)


def ensure_work(group: str) -> Path:
    work = work_dir(group)
    if (work / "index.json").is_file():
        return work
    if ensure_side(group, "crusader") != 0 or not (side_dir("crusader", group) / "index.json").is_file():
        raise SystemExit(f"Crusader-Export fuer {group} fehlt - Spielpfade unter 'Einrichten' pruefen.")
    work.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(side_dir("crusader", group), work)
    return work


def cmd_vorbereiten(args) -> int:
    sides = [s.strip() for s in args.seiten.split(",") if s.strip()]
    code = 0
    for side in sides:
        if side == "arbeit":
            ensure_work(args.gruppe)
            continue
        if side not in SIDES:
            say(f"Unbekannte Seite {side} - erlaubt: {', '.join(SIDES)}, arbeit")
            continue
        code |= ensure_side(args.gruppe, side, refresh=args.neu, mod_dir=Path(args.mod) if args.mod else None)
    if args.arbeit or "arbeit" in sides:
        ensure_work(args.gruppe)
    say("fertig")
    return 0 if code == 0 else 1


# ------------------------------------------------------------------ geometry

def index_of(directory: Path) -> dict:
    return load_json(directory / "index.json", {"frames": []})


def frame_entry(directory: Path, name: str) -> dict | None:
    for frame in index_of(directory).get("frames", []):
        if str(frame.get("name")) == name:
            return frame
    return None


def pivot_of(entry: dict, side: str) -> tuple[float, float, float, float]:
    """(Breite, Hoehe, pivot_x, pivot_y) des Frames aus Sicht einer Seite."""
    if side in ("crusader", "stronghold1") and isinstance(entry.get(side), dict):
        geo = entry[side]
        return float(geo["width"]), float(geo["height"]), float(geo["pivot_x"]), float(geo["pivot_y"])
    if "pivot_x" in entry:
        return float(entry["width"]), float(entry["height"]), float(entry["pivot_x"]), float(entry["pivot_y"])
    eff = entry.get("effective") or {}
    return float(entry["width"]), float(entry["height"]), float(eff.get("pivot_x", 0.5)), float(eff.get("pivot_y", 0.0))


def foot_px(width: float, height: float, pivot_x: float, pivot_y: float) -> tuple[float, float]:
    """Fusspunkt in Bildkoordinaten (von oben links); Unity zaehlt pivot_y von unten."""
    return pivot_x * width, (1.0 - pivot_y) * height


def fit_image(src, src_foot, canvas, canvas_foot, mode="fusspunkt", dx=0, dy=0, flip=False, resample="nearest"):
    """Bild auf die Ziel-Leinwand einpassen; liefert (Bild, verlorene Pixel)."""
    from PIL import Image

    src = src.convert("RGBA")
    sx, sy = src_foot
    if flip:
        src = src.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        sx = src.width - sx
    cw, ch = canvas
    fx, fy = canvas_foot
    if mode == "skalieren":
        scale = min(cw / src.width, ch / src.height)
        filt = Image.Resampling.NEAREST if resample == "nearest" else Image.Resampling.LANCZOS
        size = (max(1, round(src.width * scale)), max(1, round(src.height * scale)))
        src = src.resize(size, filt)
        sx, sy = sx * scale, sy * scale
        mode = "fusspunkt"
    if mode == "exakt" and src.size == (cw, ch):
        ox, oy = 0, 0
    elif mode in ("fusspunkt", "exakt"):
        ox, oy = round(fx - sx), round(fy - sy)
    elif mode == "oben-links":
        ox, oy = 0, 0
    elif mode == "oben-rechts":
        ox, oy = cw - src.width, 0
    elif mode == "unten-links":
        ox, oy = 0, ch - src.height
    elif mode == "unten-rechts":
        ox, oy = cw - src.width, ch - src.height
    elif mode == "mitte":
        ox, oy = (cw - src.width) // 2, (ch - src.height) // 2
    else:
        raise SystemExit(f"Unbekannter Modus {mode}")
    ox, oy = ox + int(dx), oy + int(dy)
    out = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    out.alpha_composite(src, (max(ox, 0), max(oy, 0)), (max(-ox, 0), max(-oy, 0)))
    total = src.width * src.height - src.getchannel("A").histogram()[0]
    kept = cw * ch - out.getchannel("A").histogram()[0]
    return out, max(0, total - kept)


# ------------------------------------------------------------------ editing

def log_change(group: str, record: dict) -> None:
    path = work_dir(group) / "aenderungen.json"
    data = load_json(path, {"aenderungen": []})
    record["zeit"] = datetime.now().isoformat(timespec="seconds")
    data["aenderungen"].append(record)
    save_json(path, data)


def place(group: str, name: str, image, mask, how: str, mask_mode: str) -> None:
    from PIL import Image

    work = ensure_work(group)
    entry = frame_entry(work, name)
    if entry is None:
        raise SystemExit(f"{name} ist kein Platz der Gruppe {group} (Frames: siehe 'gruppe {group}').")
    image.save(work / entry["file"])
    if entry.get("mask_file"):
        mask_path = work / entry["mask_file"]
        if mask is not None:
            mask.save(mask_path)
        elif mask_mode == "leer":
            Image.new("RGBA", image.size, (0, 0, 0, 0)).save(mask_path)
        elif mask_mode == "crusader":
            shutil.copy2(side_dir("crusader", group) / entry["mask_file"], mask_path)
        # "behalten": unveraendert lassen
    log_change(group, {"frame": name, "wie": how})


def target_geometry(group: str, name: str):
    work = ensure_work(group)
    entry = frame_entry(work, name)
    if entry is None:
        raise SystemExit(f"{name} ist kein Platz der Gruppe {group}.")
    w, h, px, py = pivot_of(entry, "crusader")
    return (int(w), int(h)), foot_px(w, h, px, py), entry


def parse_anchor(text: str | None, size):
    if not text:
        return None
    x, y = (float(v) for v in text.replace(";", ",").split(","))
    if 0 <= x <= 1 and 0 <= y <= 1 and "." in text:
        return foot_px(size[0], size[1], x, y)  # normiert, Unity-Richtung
    return x, y


def cmd_ersetzen(args) -> int:
    from PIL import Image

    canvas, cfoot, entry = target_geometry(args.gruppe, args.frame)
    src = Image.open(args.bild).convert("RGBA")
    anchor = parse_anchor(args.anker, src.size)
    if anchor is None:
        w, h, px, py = pivot_of(entry, "crusader")
        anchor = foot_px(src.width, src.height, px, py)
    mode = args.modus
    if mode == "exakt" and src.size != canvas:
        say(f"Hinweis: {src.width}x{src.height} statt {canvas[0]}x{canvas[1]} - wird am Fusspunkt eingepasst.")
        mode = "fusspunkt"
    image, lost = fit_image(src, anchor, canvas, cfoot, mode, args.dx, args.dy, args.spiegeln, args.filter)
    mask = None
    if args.maske:
        mimg = Image.open(args.maske).convert("RGBA")
        mask, _ = fit_image(mimg, anchor, canvas, cfoot, mode, args.dx, args.dy, args.spiegeln, "nearest")
    place(args.gruppe, args.frame, image, mask, f"ersetzt aus {Path(args.bild).name} ({mode})", args.maske_modus)
    say(f"{args.frame}: eingesetzt ({mode}, Leinwand {canvas[0]}x{canvas[1]})" + (f", {lost} Pixel ragten ueber den Rand" if lost else ""))
    return 0


def source_image(group: str, quelle: str, name: str):
    """(Bild, Maske|None, Fusspunkt) aus einer Seite oder einem anderen Frame."""
    from PIL import Image

    other_group, other_name, side = group, name, quelle
    if quelle.startswith("frame:"):
        other_name, side = quelle[6:], "arbeit"
    elif quelle.startswith("gruppe:"):
        _, other_group, other_name = quelle.split(":", 2)
        side = "arbeit" if work_dir(other_group).is_dir() else "crusader"
    elif ":" in quelle:
        side, other_name = quelle.split(":", 1)
    if side not in (*SIDES, "arbeit"):
        raise SystemExit(f"Unbekannte Quelle {quelle!r} - erlaubt: crusader|stronghold1|geliefert|arbeit[:<frame>], "
                         "frame:<frame>, gruppe:<gruppe>:<frame>")
    if side == "arbeit":
        directory = ensure_work(other_group)
        geometry_side = "crusader"
    else:
        ensure_side(other_group, side)
        directory = side_dir(side, other_group)
        geometry_side = side
    entry = frame_entry(directory, other_name)
    if entry is None:
        hint = ""
        if side == "stronghold1":
            hint = (" Stronghold 1 hat an diesem Platz keinen gleichnamigen Spender. Einen anderen SH1-Frame "
                    "waehlen ('stronghold1:<name>') oder die Seite 'geliefert' nehmen.")
        raise SystemExit(f"{other_name} liegt auf der Seite {side} nicht vor.{hint}")
    image = Image.open(directory / entry["file"]).convert("RGBA")
    mask = None
    if entry.get("mask_file") and (directory / entry["mask_file"]).is_file():
        mask = Image.open(directory / entry["mask_file"]).convert("RGBA")
    w, h, px, py = pivot_of(entry, geometry_side)
    if (int(w), int(h)) != image.size:  # Export zeigt die eigene Leinwand
        w, h = image.size
    return image, mask, foot_px(w, h, px, py)


def cmd_uebernehmen(args) -> int:
    canvas, cfoot, _entry = target_geometry(args.gruppe, args.frame)
    image, mask, anchor = source_image(args.gruppe, args.quelle, args.frame)
    fitted, lost = fit_image(image, anchor, canvas, cfoot, args.modus, args.dx, args.dy, args.spiegeln, args.filter)
    fmask = None
    if mask is not None:
        fmask, _ = fit_image(mask, anchor, canvas, cfoot, args.modus, args.dx, args.dy, args.spiegeln, "nearest")
    place(args.gruppe, args.frame, fitted, fmask, f"uebernommen aus {args.quelle}{' gespiegelt' if args.spiegeln else ''}", args.maske_modus)
    say(f"{args.frame} <- {args.quelle}{' (gespiegelt)' if args.spiegeln else ''}" + (f", {lost} Pixel abgeschnitten" if lost else ""))
    return 0


def cmd_block(args) -> int:
    """Einen Frameblock kopieren - z.B. eine fehlende Blickrichtung aus der gespiegelten Nachbarrichtung."""
    work = ensure_work(args.gruppe)
    names = {frame_number(str(f["name"])): str(f["name"]) for f in index_of(work).get("frames", [])}
    done = 0
    for i in range(args.anzahl):
        src = names.get((args.von + i * args.schritt, False))
        dst = names.get((args.nach + i * args.schritt, False))
        if src is None or dst is None:
            say(f"  Platz {args.von + i * args.schritt} -> {args.nach + i * args.schritt}: nicht vorhanden, uebersprungen")
            continue
        quelle = args.quelle + ":" + src if args.quelle == "gruppe" else ("frame:" + src if args.quelle == "arbeit" else args.quelle)
        if args.quelle not in ("arbeit",) and not args.quelle.startswith("gruppe"):
            # andere Seite, gleicher Quellplatz
            image, mask, anchor = source_image(args.gruppe, args.quelle, src)
        else:
            image, mask, anchor = source_image(args.gruppe, quelle, src)
        canvas, cfoot, _ = target_geometry(args.gruppe, dst)
        fitted, _ = fit_image(image, anchor, canvas, cfoot, args.modus, 0, 0, args.spiegeln)
        fmask = fit_image(mask, anchor, canvas, cfoot, args.modus, 0, 0, args.spiegeln)[0] if mask is not None else None
        place(args.gruppe, dst, fitted, fmask, f"Block aus {src}{' gespiegelt' if args.spiegeln else ''}", "behalten")
        done += 1
    say(f"{done} Frames gesetzt")
    return 0


def changed_frames(group: str) -> list[str]:
    work, base = work_dir(group), side_dir("crusader", group)
    if not (work / "index.json").is_file():
        return []
    out = []
    for frame in index_of(work).get("frames", []):
        files = [frame["file"]] + ([frame["mask_file"]] if frame.get("mask_file") else [])
        for filename in files:
            a, b = work / filename, base / filename
            if not b.is_file() or not a.is_file() or hashlib.sha256(a.read_bytes()).digest() != hashlib.sha256(b.read_bytes()).digest():
                out.append(str(frame["name"]))
                break
    return out


def cmd_zuruecksetzen(args) -> int:
    work, base = work_dir(args.gruppe), side_dir("crusader", args.gruppe)
    if not work.is_dir():
        say("Keine Arbeitskopie - nichts zurueckzusetzen.")
        return 0
    names = set(args.frames or [])
    count = 0
    for frame in index_of(work).get("frames", []):
        if not args.alle and str(frame["name"]) not in names:
            continue
        for filename in [frame["file"]] + ([frame["mask_file"]] if frame.get("mask_file") else []):
            if (base / filename).is_file():
                shutil.copy2(base / filename, work / filename)
        count += 1
    log_change(args.gruppe, {"frame": "alle" if args.alle else sorted(names), "wie": "zurueckgesetzt"})
    say(f"{count} Frames auf das Crusader-Original zurueckgesetzt. 'anwenden' traegt das ins Profil.")
    return 0


# ------------------------------------------------------------------ delivery

def ensure_profile(profile: str, base: str) -> Path:
    path = PROJECT_ROOT / profile
    if path.is_file():
        return path
    source = PROJECT_ROOT / base
    data = load_json(source, None)
    if data is None:
        raise SystemExit(f"Basisprofil {base} fehlt.")
    data["id"] = path.stem
    data["description"] = f"Benutzerprofil der Universal-Suite auf Basis von {Path(base).stem}"
    save_json(path, data)
    say(f"Benutzerprofil angelegt: {profile} (Basis {base})")
    return path


def register_store(group: str, origin: str) -> str:
    store = store_for(group, origin)
    data = load_json(REGISTRY, {"schema": "stronghold-europe.benutzer-ablagen.v1", "ablagen": {}})
    data.setdefault("ablagen", {})[store] = {"gruppe": group, "herkunft": origin}
    save_json(REGISTRY, data)
    return store


def remove_profile_entry(profile_path: Path, store: str) -> None:
    data = load_json(profile_path, None)
    if not isinstance(data, dict):
        return
    before = len(data.get("authored_sprites", []))
    data["authored_sprites"] = [e for e in data.get("authored_sprites", []) if e.get("source_dir") != store]
    if len(data["authored_sprites"]) != before:
        save_json(profile_path, data)
        say(f"Profileintrag {store} entfernt.")


def cmd_anwenden(args) -> int:
    group = args.gruppe
    origin = args.herkunft
    store = register_store(group, origin)
    store_dir = PROJECT_ROOT / store
    changed = set(changed_frames(group))
    profile_path = ensure_profile(args.profil, args.basis)
    # Frames, die in der Arbeitskopie wieder dem Original entsprechen, aus der Ablage nehmen.
    if store_dir.is_dir():
        work = work_dir(group)
        for frame in index_of(work).get("frames", []):
            if str(frame["name"]) in changed:
                continue
            for filename in [frame["file"]] + ([frame.get("mask_file")] if frame.get("mask_file") else []):
                stale = store_dir / filename
                if stale.is_file():
                    stale.unlink()
    if not changed:
        if store_dir.is_dir():
            shutil.rmtree(store_dir)
        remove_profile_entry(profile_path, store)
        say("Keine Aenderungen gegenueber dem Original - Ablage und Profileintrag entfernt.")
        return 0
    code = run_tool(["tools/sprites.py", "import", str(work_dir(group)), "--set", store.rsplit("/", 1)[-1], "--origin", origin])
    if code != 0:
        say("Import meldete Probleme (siehe oben). Tipp: betroffene Frames mit 'ersetzen --modus fusspunkt' neu einpassen.")
        return code
    add = ["tools/sprites.py", "profile-add", store.rsplit("/", 1)[-1], "--profile",
           str(profile_path.relative_to(PROJECT_ROOT)), "--origin", origin, "--write"]
    code = run_tool(add + ["--allow-atlas-shadow"])
    if code != 0:
        code = run_tool(add)
    if code == 0:
        say(f"{len(changed)} Frames von {group} liegen in {store} und im Profil {profile_path.name}. Weiter: Paket bauen.")
    else:
        say("Das Profil nimmt diese Ablage nicht an. Liefert das Profil die Gruppe ueber ein sparse/shared-Backend, "
            "fuehrt nur 'umlenken' (Konvertierung) zum Ziel.")
    return code


def cmd_status(args) -> int:
    registry = load_json(REGISTRY, {"ablagen": {}}).get("ablagen", {})
    overrides = load_json(OVERRIDES, {"gruppen": {}}).get("gruppen", {})
    report = {"ablagen": [], "arbeitskopien": [], "umlenkungen": {g: len(v) for g, v in overrides.items()}}
    for store, spec in sorted(registry.items()):
        directory = PROJECT_ROOT / store
        report["ablagen"].append({"ablage": store, "gruppe": spec.get("gruppe"),
                                  "dateien": len(list(directory.glob("*.png"))) if directory.is_dir() else 0})
    if (WORK / "arbeit").is_dir():
        for work in sorted((WORK / "arbeit").iterdir()):
            if work.is_dir():
                report["arbeitskopien"].append({"gruppe": work.name, "geaendert": len(changed_frames(work.name))})
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
        return 0
    say("Lieferablagen:")
    for row in report["ablagen"] or [{"ablage": "(keine)", "gruppe": "", "dateien": 0}]:
        say(f"  {row['ablage']:<60} {row['gruppe']:<24} {row['dateien']} PNG")
    say("Arbeitskopien:")
    for row in report["arbeitskopien"] or [{"gruppe": "(keine)", "geaendert": 0}]:
        say(f"  {row['gruppe']:<28} {row['geaendert']} geaenderte Frames")
    say("Eigene Umlenkungen:")
    for group, count in report["umlenkungen"].items() or [("(keine)", 0)]:
        say(f"  {group:<28} {count}")
    return 0


# ------------------------------------------------------------------ overrides

def cmd_umlenken(args) -> int:
    group = args.gruppe
    targets = parse_range(args.ziel)
    donors = parse_range(args.spender) if args.spender else [None] * len(targets)
    if len(donors) != len(targets):
        raise SystemExit(f"{len(targets)} Zielplaetze, aber {len(donors)} Spender - die Bereiche muessen gleich lang sein.")
    source_names = {str(row.get("name")) for row in group_rows(group)}
    data = load_json(OVERRIDES, {"schema": "stronghold-europe.frame-overrides.v1", "gruppen": {}})
    rows = data.setdefault("gruppen", {}).setdefault(group, [])
    by_target = {row["ziel"]: row for row in rows}
    style, width = name_style(group)
    for target, donor in zip(targets, donors):
        tname = native_name(group, target)
        if tname not in source_names:
            say(f"  Hinweis: {tname} steht nicht im Mapping dieser Gruppe - trotzdem eingetragen.")
        dname = None
        if donor is not None:
            dname = f"{group}-{donor}" if style == "dash" else f"{group} {donor:03d}"
        by_target[tname] = {"ziel": tname, "spender": dname, "grund": args.grund}
    data["gruppen"][group] = sorted(by_target.values(), key=lambda r: frame_sort_key(r["ziel"]))
    save_json(OVERRIDES, data)
    say(f"{len(targets)} Umlenkungen fuer {group} in {OVERRIDES.relative_to(PROJECT_ROOT)}.")
    say("Wichtig: Die Nachweise dieser Gruppe stimmen jetzt nicht mehr. Unter 'Paket bauen' zuerst "
        "'Nachweise vermessen' (tools/pin_digests.py) laufen lassen, dann bauen.")
    if len(targets) not in (1, 4, 9, 16, 25, 36, 49, 64, 81, 100, 121) and group.startswith("tile_"):
        say("Achtung Huetten-Regel: Ein Kachelobjekt hat 4/9/16/25/.../121 Teile. Wird nur ein Teil umgelenkt, "
            "bleibt der alte Sockel stehen. Ganzes Objekt umlenken!")
    return 0


def cmd_umlenkung_entfernen(args) -> int:
    data = load_json(OVERRIDES, {"gruppen": {}})
    rows = data.get("gruppen", {}).get(args.gruppe, [])
    drop = {native_name(args.gruppe, i) for i in parse_range(args.ziel)} if args.ziel else None
    kept = [r for r in rows if drop is not None and r["ziel"] not in drop]
    data.setdefault("gruppen", {})[args.gruppe] = kept
    if not kept:
        data["gruppen"].pop(args.gruppe, None)
    save_json(OVERRIDES, data)
    say(f"{len(rows) - len(kept)} Umlenkungen entfernt. Nachweise neu vermessen, dann bauen.")
    return 0


# ------------------------------------------------------------------ group info

def cmd_gruppe(args) -> int:
    group = args.gruppe
    rows = group_rows(group)
    work = work_dir(group)
    changed = set(changed_frames(group)) if work.is_dir() else set()
    store_dir = PROJECT_ROOT / store_for(group)
    in_store = {p.stem for p in store_dir.glob("*.png")} if store_dir.is_dir() else set()
    from stronghold_europe_de.gm_atlas import frame_overrides_for

    overrides = {o.target_name: o.donor_name for o in frame_overrides_for(group)}
    roles = load_json(ROLLEN, {"gruppen": {}}).get("gruppen", {}).get(group, {})
    frames = []
    for row in rows:
        name = str(row.get("name"))
        target = row.get("target") or {}
        source = row.get("source") or {}
        index, alt = frame_number(name)
        frames.append({
            "name": name, "index": index, "alt": alt, "aktion": row.get("action"),
            "crusader": [target.get("width"), target.get("height"), target.get("pivot_x"), target.get("pivot_y")],
            "stronghold1": [source.get("width"), source.get("height"), source.get("pivot_x"), source.get("pivot_y")] if source else None,
            "umlenkung": overrides.get(name, "-") if name in overrides else None,
            "geaendert": name in changed, "in_ablage": name in in_store,
        })
    info = {"gruppe": group, "frames": frames, "rollen": roles,
            "seiten": {side: side_dir(side, group).is_dir() for side in SIDES},
            "arbeit": work.is_dir(), "ablage": store_for(group), "katalog": str(WORK)}
    if args.json:
        print(json.dumps(info, ensure_ascii=False))
        return 0
    actions: dict[str, int] = {}
    for f in frames:
        actions[f["aktion"]] = actions.get(f["aktion"], 0) + 1
    say(f"{group}: {len(frames)} Plaetze  {actions}")
    say(f"  Umlenkungen: {len(overrides)}  geaendert in Arbeitskopie: {len(changed)}  in Ablage: {len(in_store)}")
    for f in frames[: args.zeilen]:
        say(f"  {f['name']:<28} {f['aktion']:<16} crusader={f['crusader'][:2]} sh1={(f['stronghold1'] or [None, None])[:2]}"
            + (f" -> {f['umlenkung']}" if f["umlenkung"] else "") + (" *" if f["geaendert"] else ""))
    return 0


def cmd_rollen(args) -> int:
    data = load_json(ROLLEN, {"schema": "stronghold-europe.asset-rollen.v1", "gruppen": {}})
    entry = data.setdefault("gruppen", {}).setdefault(args.gruppe, {})
    if args.spalten:
        entry["spalten"] = args.spalten
    for block in args.block or []:
        name, span = block.split("=", 1)
        lo, hi = span.split("-")
        entry.setdefault("bloecke", [])
        entry["bloecke"] = [b for b in entry["bloecke"] if b.get("name") != name]
        entry["bloecke"].append({"name": name, "von": int(lo), "bis": int(hi)})
    save_json(ROLLEN, data)
    say(f"Rollen fuer {args.gruppe}: {entry}")
    return 0


# ------------------------------------------------------------------ extensions

def cmd_erweiterung(args) -> int:
    from PIL import Image

    if args.aktion == "neu":
        folder = ERWEITERUNGEN / slug(args.kategorie) / slug(args.name)
        folder.mkdir(parents=True, exist_ok=True)
        pictures = []
        sources = []
        for item in args.bilder:
            path = Path(item)
            sources.extend(sorted(path.glob("*.png")) if path.is_dir() else [path])
        for number, path in enumerate(sources):
            if path.name.endswith("_m.png"):
                continue
            image = Image.open(path).convert("RGBA")
            name = f"{number:03d}.png"
            image.save(folder / name)
            record = {"datei": name, "quelle": path.name, "breite": image.width, "hoehe": image.height}
            mask = path.with_name(path.stem + "_m.png")
            if mask.is_file():
                Image.open(mask).convert("RGBA").save(folder / f"{number:03d}_m.png")
                record["maske"] = f"{number:03d}_m.png"
            pictures.append(record)
        manifest = {"schema": "stronghold-europe.erweiterung.v1", "name": args.name, "kategorie": args.kategorie,
                    "beschreibung": args.beschreibung or "", "bilder": pictures, "bindung": None}
        save_json(folder / "erweiterung.json", manifest)
        say(f"Erweiterung '{args.name}' mit {len(pictures)} Bildern unter {folder.relative_to(PROJECT_ROOT)} angelegt.")
        say("Binden an Spielplaetze: 'erweiterung binden --name ... --gruppe ... --ab <Index>'.")
        return 0
    manifest_path = next((p for p in ERWEITERUNGEN.glob("*/*/erweiterung.json")
                          if load_json(p, {}).get("name") == args.name), None)
    if manifest_path is None:
        raise SystemExit(f"Erweiterung {args.name} nicht gefunden.")
    manifest = load_json(manifest_path, {})
    folder = manifest_path.parent
    if args.aktion == "binden":
        for offset, picture in enumerate(manifest.get("bilder", [])):
            name = native_name(args.gruppe, args.ab + offset)
            canvas, cfoot, entry = target_geometry(args.gruppe, name)
            image = Image.open(folder / picture["datei"]).convert("RGBA")
            w, h, px, py = pivot_of(entry, "crusader")
            anchor = foot_px(image.width, image.height, px, py)
            fitted, lost = fit_image(image, anchor, canvas, cfoot, args.modus)
            mask = None
            if picture.get("maske"):
                mask = fit_image(Image.open(folder / picture["maske"]), anchor, canvas, cfoot, args.modus)[0]
            place(args.gruppe, name, fitted, mask, f"Erweiterung {args.name}", "leer")
            say(f"  {picture['datei']} -> {name}" + (f" ({lost} Pixel abgeschnitten)" if lost else ""))
        manifest["bindung"] = {"gruppe": args.gruppe, "ab": args.ab, "modus": args.modus}
        save_json(manifest_path, manifest)
        say("Gebunden. Mit 'anwenden' ins Profil uebernehmen.")
    return 0


# ------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("kategorien", help="thematischer Baum aller Grafikgruppen")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_kategorien)

    p = sub.add_parser("kategorie", help="Kategorien anlegen, Gruppen zuordnen, Kategorien entfernen")
    p.add_argument("aktion", choices=("neu", "zuordnen", "entfernen"))
    p.add_argument("--name", required=True)
    p.add_argument("--unter")
    p.add_argument("--gruppe")
    p.set_defaults(func=cmd_kategorie)

    p = sub.add_parser("gruppe", help="Plaetze, Aktionen, Umlenkungen und Aenderungen einer Gruppe")
    p.add_argument("gruppe")
    p.add_argument("--json", action="store_true")
    p.add_argument("--zeilen", type=int, default=40)
    p.set_defaults(func=cmd_gruppe)

    p = sub.add_parser("vorbereiten", help="Ansichten einer Gruppe exportieren (crusader, stronghold1, geliefert, arbeit)")
    p.add_argument("gruppe")
    p.add_argument("--seiten", default="crusader,stronghold1,geliefert")
    p.add_argument("--mod", help="Modordner fuer 'geliefert' (Standard: Zielspiel, sonst neuester Bau)")
    p.add_argument("--neu", action="store_true", help="vorhandene Exporte ersetzen")
    p.add_argument("--arbeit", action="store_true", help="auch die Arbeitskopie anlegen")
    p.set_defaults(func=cmd_vorbereiten)

    def fit_options(p):
        p.add_argument("--modus", choices=ANCHORS, default="fusspunkt")
        p.add_argument("--dx", type=int, default=0)
        p.add_argument("--dy", type=int, default=0)
        p.add_argument("--spiegeln", action="store_true")
        p.add_argument("--filter", choices=("nearest", "lanczos"), default="nearest")
        p.add_argument("--maske-modus", choices=("leer", "behalten", "crusader"), default="leer",
                       help="Teamfarbenmaske ohne eigene Vorlage: leer (keine Teamfarbe), behalten, crusader")

    p = sub.add_parser("ersetzen", help="einen Platz durch ein eigenes Bild ersetzen (wird eingepasst)")
    p.add_argument("gruppe")
    p.add_argument("frame")
    p.add_argument("--bild", required=True)
    p.add_argument("--maske")
    p.add_argument("--anker", help="Fusspunkt im Bild: 'x,y' in Pixeln von oben links oder normiert '0.5,0.1' (Unity)")
    fit_options(p)
    p.set_defaults(func=cmd_ersetzen)

    p = sub.add_parser("uebernehmen", help="einen Platz aus einer anderen Seite oder einem anderen Frame fuellen")
    p.add_argument("gruppe")
    p.add_argument("frame")
    p.add_argument("--quelle", required=True,
                   help="crusader | stronghold1 | geliefert | frame:<name> | gruppe:<gruppe>:<name>")
    fit_options(p)
    p.set_defaults(func=cmd_uebernehmen)

    p = sub.add_parser("block", help="Frameblock kopieren (Richtungen, Schadensstufen, Animationsphasen)")
    p.add_argument("gruppe")
    p.add_argument("--von", type=int, required=True, help="erster Quellindex")
    p.add_argument("--nach", type=int, required=True, help="erster Zielindex")
    p.add_argument("--anzahl", type=int, required=True)
    p.add_argument("--schritt", type=int, default=1, help="Abstand zwischen den Frames (z.B. Richtungsanzahl)")
    p.add_argument("--quelle", default="arbeit", help="arbeit | crusader | stronghold1 | geliefert")
    p.add_argument("--modus", choices=ANCHORS, default="fusspunkt")
    p.add_argument("--spiegeln", action="store_true")
    p.set_defaults(func=cmd_block)

    p = sub.add_parser("zuruecksetzen", help="Plaetze der Arbeitskopie auf das Crusader-Original setzen")
    p.add_argument("gruppe")
    p.add_argument("frames", nargs="*")
    p.add_argument("--alle", action="store_true")
    p.set_defaults(func=cmd_zuruecksetzen)

    p = sub.add_parser("anwenden", help="Aenderungen einer Gruppe in Ablage und Profil uebernehmen")
    p.add_argument("gruppe")
    p.add_argument("--profil", default=DEFAULT_PROFILE)
    p.add_argument("--basis", default=DEFAULT_BASE_PROFILE, help="Vorlage, falls das Benutzerprofil noch fehlt")
    p.add_argument("--herkunft", choices=("derived", "authored"), default="derived")
    p.set_defaults(func=cmd_anwenden)

    p = sub.add_parser("status", help="alle eigenen Ablagen, Arbeitskopien und Umlenkungen")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("umlenken", help="Plaetze aus einem anderen SH1-Spender konvertieren (ganze Objekte!)")
    p.add_argument("gruppe")
    p.add_argument("--ziel", required=True, help="Zielindizes, z.B. 1192-1207")
    p.add_argument("--spender", help="SH1-Indizes gleicher Anzahl; weglassen = Crusader-Bild behalten")
    p.add_argument("--grund", default="Benutzerumlenkung (Universal-Suite)")
    p.set_defaults(func=cmd_umlenken)

    p = sub.add_parser("umlenkung-entfernen", help="eigene Umlenkungen wieder entfernen")
    p.add_argument("gruppe")
    p.add_argument("--ziel", help="nur diese Zielindizes; ohne Angabe alle der Gruppe")
    p.set_defaults(func=cmd_umlenkung_entfernen)

    p = sub.add_parser("rollen", help="Rasteransicht und Rollen (Richtungen, Schadensstufen) einer Gruppe festlegen")
    p.add_argument("gruppe")
    p.add_argument("--spalten", type=int, help="Frames je Zeile, z.B. Anzahl der Blickrichtungen")
    p.add_argument("--block", action="append", help="Name=von-bis, z.B. 'Schaden 1=40-47'")
    p.set_defaults(func=cmd_rollen)

    p = sub.add_parser("erweiterung", help="neue eigene Assets anlegen und an Spielplaetze binden")
    p.add_argument("aktion", choices=("neu", "binden"))
    p.add_argument("--name", required=True)
    p.add_argument("--kategorie", default="Eigene Assets")
    p.add_argument("--bilder", nargs="*", default=[])
    p.add_argument("--beschreibung")
    p.add_argument("--gruppe")
    p.add_argument("--ab", type=int, default=0)
    p.add_argument("--modus", choices=ANCHORS, default="fusspunkt")
    p.set_defaults(func=cmd_erweiterung)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
