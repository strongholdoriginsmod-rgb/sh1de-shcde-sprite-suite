"""Vorschau-Sandkasten: Aenderungen sofort auf einer kleinen Karte sehen, ohne das Spiel.

Gezeichnet wird nach denselben Regeln, nach denen SHC:DE seine Welt zeichnet und
die wir im Spiel nachgemessen haben:

* Pixel: die ausgelieferten BC7-Atlanten werden dekodiert - das sind die Pixel,
  die auch die Grafikkarte bekommt. Eigene, noch nicht gebaute Aenderungen
  koennen durch dieselbe BC7-Kompression geschickt werden (Simulation).
* Platz: Kachelraster 64x32, Anker ((x-y)*32, (x+y)*16); jedes Sprite sitzt mit
  seinem Unity-Pivot (von unten gezaehlt) auf dem Anker. Kachelteile haben den
  Pivot 16,5 px ueber der Unterkante.
* Massstab 1:1, Punktfilter, Zeichenfolge Reihe fuer Reihe (x+y, dann x).
* Mehrteilige Gebaeude: ein Sprite je belegter Kachel, im Raster des Objekts.

Genaehert sind nur Shader-Effekte: Teamfarbe (aus der _m-Maske), Wind der
Baeume (hier: die Bildfolge des Spiels), Licht und Nebel fehlen. Mit
``abgleich`` laesst sich die Uebereinstimmung an einem echten Spielbild messen.

    python tools/sandkasten.py render sandbox/szenen/beispieldorf.json --out work/sandkasten/bild.png
    python tools/sandkasten.py abgleich sandbox/szenen/beispieldorf.json --bild <Spielbild.png>
    python tools/sandkasten.py hud --bilder a.png b.png c.png
    python tools/sandkasten.py fenster
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import asset_katalog as katalog  # noqa: E402

SANDBOX = PROJECT_ROOT / "sandbox"
SCENES = SANDBOX / "szenen"
HUD_DIR = SANDBOX / "hud"
HALF_W, HALF_H, TILE_PIVOT_Y = 32, 16, 16.5
MODES = {
    "crusader": "Crusader-Original",
    "geliefert": "Ausgeliefert (installiert/gebaut)",
    "arbeit": "Ausgeliefert + meine Aenderungen",
}
TEAM_COLOURS = {
    "keine": None, "rot": (200, 30, 30), "blau": (40, 70, 210), "gelb": (230, 200, 40),
    "gruen": (40, 160, 50), "orange": (230, 120, 20), "lila": (140, 50, 170), "tuerkis": (40, 180, 180),
    "grau": (130, 130, 130),
}


def say(text=""):
    print(text, flush=True)


# ------------------------------------------------------------------ sprites

@dataclass
class Frame:
    image: object          # PIL RGBA
    mask: object | None    # PIL RGBA oder None
    foot: tuple[float, float]  # Pivot in Bildkoordinaten (von oben links)
    side: str


class FrameSource:
    """Liefert Frames nach Modus; Arbeitskopie > geliefert > Crusader."""

    def __init__(self, mode: str = "arbeit", mod_dir: Path | None = None, bc7: bool = False, log=say):
        self.mode = mode
        self.mod_dir = mod_dir
        self.bc7 = bc7
        self.log = log
        self._cache: dict[tuple, Frame | None] = {}
        self._indices: dict[tuple[str, str], dict] = {}
        self._changed: dict[str, set[str]] = {}

    def _index(self, side: str, group: str) -> dict:
        key = (side, group)
        if key not in self._indices:
            if side == "arbeit":
                directory = katalog.work_dir(group)
                if not (directory / "index.json").is_file():
                    self._indices[key] = {}
                    return self._indices[key]
            else:
                try:
                    katalog.ensure_side(group, side, mod_dir=self.mod_dir)
                except SystemExit as exc:
                    self.log(f"  {group}/{side}: {exc}")
                directory = katalog.side_dir(side, group)
            frames = katalog.index_of(directory).get("frames", [])
            self._indices[key] = {"dir": directory, "frames": {str(f["name"]): f for f in frames}}
        return self._indices[key]

    def changed(self, group: str) -> set[str]:
        if group not in self._changed:
            self._changed[group] = set(katalog.changed_frames(group)) if katalog.work_dir(group).is_dir() else set()
        return self._changed[group]

    def frame(self, group: str, name: str) -> Frame | None:
        key = (group, name)
        if key in self._cache:
            return self._cache[key]
        result = None
        order = {"crusader": ["crusader"], "geliefert": ["geliefert", "crusader"],
                 "arbeit": ["arbeit", "geliefert", "crusader"]}[self.mode]
        for side in order:
            if side == "arbeit" and name not in self.changed(group):
                continue
            index = self._index(side, group)
            entry = index.get("frames", {}).get(name) if index else None
            if entry is None:
                continue
            result = self._load(index["dir"], entry, side)
            if result is not None:
                break
        self._cache[key] = result
        return result

    def _load(self, directory: Path, entry: dict, side: str) -> Frame | None:
        from PIL import Image

        path = directory / entry["file"]
        if not path.is_file():
            return None
        image = Image.open(path).convert("RGBA")
        mask = None
        if entry.get("mask_file") and (directory / entry["mask_file"]).is_file():
            mask = Image.open(directory / entry["mask_file"]).convert("RGBA")
        geometry = "crusader" if side in ("arbeit", "crusader") else side
        w, h, px, py = katalog.pivot_of(entry, geometry)
        if (int(round(w)), int(round(h))) != image.size:
            w, h = image.size
        if side == "arbeit" and self.bc7:
            image = bc7_roundtrip(image)
        return Frame(image, mask, katalog.foot_px(w, h, px, py), side)


def bc7_roundtrip(image):
    """Dieselbe verlustbehaftete Stufe wie im Bau: BC7 kodieren und wieder dekodieren."""
    from PIL import Image

    try:
        import etcpak
        import texture2ddecoder
    except ImportError:
        return image
    w, h = image.size
    pw, ph = (w + 3) // 4 * 4, (h + 3) // 4 * 4
    padded = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    padded.paste(image, (0, 0))
    try:
        data = etcpak.compress_bc7(padded.tobytes(), pw, ph)
        raw = texture2ddecoder.decode_bc7(data, pw, ph)
    except Exception:
        return image
    decoded = Image.frombytes("RGBA", (pw, ph), raw, "raw", "BGRA")
    return decoded.crop((0, 0, w, h))


def tint(image, mask, colour):
    """Teamfarbe (Naeherung): Maskenanteil wird in der Teamfarbe eingefaerbt."""
    if mask is None or colour is None:
        return image
    import numpy as np
    from PIL import Image

    rgba = np.asarray(image).astype(np.float32)
    m = np.asarray(mask.resize(image.size) if mask.size != image.size else mask).astype(np.float32)
    # Rot-Kanal der _m-Maske = Teamfarbenanteil (gemessen an body_archer; Gruen und
    # Alpha tragen andere Materialdaten). Nur sichtbare Farbpixel werden gefaerbt.
    weight = (m[..., 0] / 255.0 * (rgba[..., 3] > 0))[..., None]
    lum = rgba[..., :3].mean(axis=2, keepdims=True) / 255.0
    team = np.array(colour, dtype=np.float32)[None, None, :] * (0.35 + 0.9 * lum)
    rgb = rgba[..., :3] * (1 - weight) + np.clip(team, 0, 255) * weight
    out = np.concatenate([rgb, rgba[..., 3:4]], axis=2).clip(0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


# ------------------------------------------------------------------ scenes

def default_scene() -> dict:
    return {
        "schema": "stronghold-europe.sandkasten.v1",
        "name": "Beispieldorf",
        "karte": [26, 26],
        "boden": {"gruppe": "tile_land8", "frames": list(range(1, 57)), "saat": 7},
        "objekte": [
            {"art": "kachelobjekt", "gruppe": "tile_buildings2", "von": 1192, "spalten": 4, "zeilen": 4,
             "layout": "gm1", "x": 4, "y": 12, "titel": "Huette 1"},
            {"art": "kachelobjekt", "gruppe": "tile_buildings2", "von": 1208, "spalten": 4, "zeilen": 4,
             "layout": "gm1", "x": 9, "y": 16, "titel": "Huette 2"},
            {"art": "kachelobjekt", "gruppe": "tile_buildings2", "von": 1224, "spalten": 4, "zeilen": 4,
             "layout": "gm1", "x": 14, "y": 19, "titel": "Huette 3"},
            {"art": "kachelobjekt", "gruppe": "tile_castle", "von": 1193, "spalten": 11, "zeilen": 11,
             "layout": "gm1", "x": 12, "y": 2, "titel": "Bergfriedsockel"},
            {"art": "sprite", "gruppe": "Tree_Oak", "frame": 0, "x": 4, "y": 4,
             "animation": {"von": 0, "bis": 24, "fps": 10}, "titel": "Eiche"},
            {"art": "sprite", "gruppe": "Tree_Oak", "frame": 5, "x": 7, "y": 2,
             "animation": {"von": 0, "bis": 24, "fps": 10}, "titel": "Eiche"},
            {"art": "sprite", "gruppe": "body_archer", "frame": 0, "x": 10, "y": 12, "team": "rot",
             "titel": "Bogenschuetze"},
            {"art": "sprite", "gruppe": "body_archer", "frame": 4, "x": 11, "y": 13, "team": "blau",
             "titel": "Bogenschuetze"},
        ],
        "hud": {"sichtbar": True},
    }


def load_scene(path: Path | None) -> dict:
    if path is None:
        path = SCENES / "beispieldorf.json"
    if not path.is_file():
        scene = default_scene()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(scene, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return scene
    return json.loads(path.read_text(encoding="utf-8-sig"))


_GM1_LAYOUTS: dict | None = None


def gm1_layout(count: int) -> list | None:
    """Teilfolge der Original-GM1 (config/kachelobjekt-raster.json): diagonal von vorne nach hinten."""
    global _GM1_LAYOUTS
    if _GM1_LAYOUTS is None:
        _GM1_LAYOUTS = katalog.load_json(PROJECT_ROOT / "config" / "kachelobjekt-raster.json", {})
    return _GM1_LAYOUTS.get(str(count))


def layout_xy(position: int, columns: int, rows: int, layout: str) -> tuple[int, int]:
    if layout == "gm1":
        table = gm1_layout(columns * rows)
        if table:
            x, y = table[position]
            return int(x), int(y)
        layout = "row-major"
    if layout.startswith("column-major"):
        x, y = divmod(position, rows)
    else:
        y, x = divmod(position, columns)
    if layout.endswith("flip-x") or layout.endswith("rotate-180"):
        x = columns - 1 - x
    if layout.endswith("flip-y") or layout.endswith("rotate-180"):
        y = rows - 1 - y
    return x, y


@dataclass
class Item:
    group: str
    name: str
    x: int
    y: int
    layer: int
    team: str | None = None
    title: str = ""
    order: int = 0
    box: tuple[int, int, int, int] | None = field(default=None)


def scene_items(scene: dict, tick: float) -> list[Item]:
    width, height = scene.get("karte", [24, 24])
    items: list[Item] = []
    # Unter Gebaeudeteilen gibt es im Spiel keinen Boden - die Kachel traegt das Gebaeude.
    occupied = set()
    for obj in scene.get("objekte", []):
        if obj.get("art") == "kachelobjekt":
            for dx in range(int(obj["spalten"])):
                for dy in range(int(obj["zeilen"])):
                    occupied.add((obj["x"] + dx, obj["y"] + dy))
    ground = scene.get("boden")
    if ground:
        rng = random.Random(ground.get("saat", 1))
        frames = ground.get("frames") or [0]
        for y in range(height):
            for x in range(width):
                index = rng.choice(frames)
                if (x, y) in occupied:
                    continue
                items.append(Item(ground["gruppe"], katalog.native_name(ground["gruppe"], index), x, y, 0))
    for number, obj in enumerate(scene.get("objekte", [])):
        group = obj["gruppe"]
        if obj.get("art") == "kachelobjekt":
            columns, rows = int(obj["spalten"]), int(obj["zeilen"])
            for position in range(columns * rows):
                tx, ty = layout_xy(position, columns, rows, obj.get("layout", "gm1"))
                items.append(Item(group, katalog.native_name(group, int(obj["von"]) + position),
                                  obj["x"] + tx, obj["y"] + ty, 1, obj.get("team"), obj.get("titel", ""), number))
        else:
            index = int(obj.get("frame", 0))
            animation = obj.get("animation")
            if animation:
                lo, hi, fps = int(animation["von"]), int(animation["bis"]), float(animation.get("fps", 10))
                index = lo + (int(tick * fps) + (index - lo)) % (hi - lo + 1)
            items.append(Item(group, katalog.native_name(group, index, bool(obj.get("alt"))), obj["x"], obj["y"], 1,
                              obj.get("team"), obj.get("titel", ""), number))
    return items


def raster_edge(value: float) -> int:
    """Erste Pixelzeile/-spalte einer Sprite-Kante wie auf der Grafikkarte.

    Gemessen am Testerfoto vom 04.09.2026 (Huette 1192-1207): Kanten werden mit
    1/256 px Genauigkeit gerastert, und eine Kante genau auf der Pixelmitte
    zaehlt mit (Top-Left-Regel). Pivots von 16,49996 / 16,5 / 16,50006 px landen
    damit in derselben Zeile - einfaches Runden lag bei exakt ,5 um 1 px daneben.
    """
    return math.ceil(round(value * 256) / 256 - 0.5)


def render(scene: dict, source: FrameSource, tick: float = 0.0, grid=False, pivots=False, team_default="rot"):
    """Szene zeichnen; liefert (Bild, Items mit Bildschirmrechteck)."""
    from PIL import Image, ImageDraw

    width, height = scene.get("karte", [24, 24])
    margin_top = 420
    canvas_w = (width + height) * HALF_W + 2 * HALF_W
    canvas_h = (width + height) * HALF_H + margin_top + 80
    origin_x, origin_y = height * HALF_W + HALF_W, margin_top
    out = Image.new("RGBA", (canvas_w, canvas_h), (24, 26, 22, 255))
    items = scene_items(scene, tick)
    # Reihe fuer Reihe wie im Spiel - Boden eingeschlossen: die Grashalme vorderer
    # Bodenkacheln ueberdecken Gebaeudesockel (am Testerfoto 04.09.2026 gemessen).
    items.sort(key=lambda it: (it.x + it.y, it.x, it.layer, it.order))
    missing = set()
    for item in items:
        frame = source.frame(item.group, item.name)
        if frame is None:
            missing.add(item.group)
            continue
        image = frame.image
        team_capable = item.group.startswith("body_") or "flag" in item.group
        colour = TEAM_COLOURS.get(item.team or team_default) if team_capable else None
        if frame.mask is not None and colour is not None:
            image = tint(image, frame.mask, colour)
        ax = origin_x + (item.x - item.y) * HALF_W
        ay = origin_y + (item.x + item.y) * HALF_H
        left = raster_edge(ax - frame.foot[0])
        top = raster_edge(ay - frame.foot[1])
        dst = (max(left, 0), max(top, 0))
        src = (max(-left, 0), max(-top, 0))
        if src[0] < image.width and src[1] < image.height and dst[0] < canvas_w and dst[1] < canvas_h:
            out.alpha_composite(image, dst, src)
        item.box = (left, top, left + image.width, top + image.height)
        if pivots and item.layer:
            draw = ImageDraw.Draw(out)
            draw.line([(ax - 4, ay), (ax + 4, ay)], fill=(255, 40, 40, 255))
            draw.line([(ax, ay - 4), (ax, ay + 4)], fill=(255, 40, 40, 255))
    if grid:
        draw = ImageDraw.Draw(out)
        for y in range(height + 1):
            a = (origin_x - y * HALF_W, origin_y + y * HALF_H - HALF_H)
            b = (origin_x + (width - y) * HALF_W, origin_y + (width + y) * HALF_H - HALF_H)
            draw.line([a, b], fill=(255, 255, 255, 60))
        for x in range(width + 1):
            a = (origin_x + x * HALF_W, origin_y + x * HALF_H - HALF_H)
            b = (origin_x + (x - height) * HALF_W, origin_y + (x + height) * HALF_H - HALF_H)
            draw.line([a, b], fill=(255, 255, 255, 60))
    return out, items, sorted(missing)


def _delivered_ui_sheet(sheet_name: str):
    """Ausgelieferte UI-Bogen (authored_ui_atlases des Profils) als Bild."""
    from PIL import Image

    for profile_name in ("benutzer.json", "europe-production-bc7-v2.json", "europe-production.json"):
        profile = katalog.load_json(PROJECT_ROOT / "profiles" / profile_name, None)
        if not isinstance(profile, dict):
            continue
        for entry in profile.get("authored_ui_atlases", []):
            if Path(entry.get("output", "")).name == sheet_name:
                path = PROJECT_ROOT / entry["source"]
                if path.is_file():
                    return Image.open(path).convert("RGBA")
    return None


def ui_changes() -> list[dict]:
    """Bearbeitete UI-Ausschnitte aus allen ui_atlas-Exporten unter work/ (Hash != Ausgangsstand)."""
    import hashlib

    from PIL import Image

    changes = []
    for index_path in sorted((PROJECT_ROOT / "work").glob("*/index.json")):
        index = katalog.load_json(index_path, {})
        for atlas in index.get("atlases", []) if isinstance(index, dict) else []:
            directory = index_path.parent / atlas.get("directory", "")
            for crop in atlas.get("crops", []):
                path = directory / crop["file"]
                if not path.is_file() or not crop.get("baseline_pixels_sha256"):
                    continue
                image = Image.open(path).convert("RGBA")
                if hashlib.sha256(image.tobytes()).hexdigest() == crop["baseline_pixels_sha256"]:
                    continue
                changes.append({"sheet": atlas["sheet"], "key": crop["key"], "rect": (crop["x"], crop["y"],
                                crop["width"], crop["height"]), "neu": image})
    return changes


def _locate(hud, template, scales):
    import numpy as np
    from PIL import Image
    from scipy.signal import fftconvolve

    base = np.asarray(hud.convert("RGB"), dtype=np.float64) @ np.array([0.299, 0.587, 0.114])
    s2 = base * base
    best = None
    for scale in scales:
        w, h = max(2, round(template.width * scale)), max(2, round(template.height * scale))
        if w >= base.shape[1] or h >= base.shape[0]:
            continue
        small = template.resize((w, h), Image.Resampling.BILINEAR)
        rgba = np.asarray(small, dtype=np.float64)
        mask = (rgba[..., 3] > 200).astype(np.float64)
        n = mask.sum()
        if n < 30:
            continue
        g = rgba[..., :3] @ np.array([0.299, 0.587, 0.114])
        tc = (g - (g * mask).sum() / n) * mask
        den = math.sqrt((tc * tc).sum())
        if den < 1e-6:
            continue
        flip = mask[::-1, ::-1]
        num = fftconvolve(base, tc[::-1, ::-1], mode="valid")
        ss = fftconvolve(base, flip, mode="valid")
        ss2 = fftconvolve(s2, flip, mode="valid")
        ncc = num / (np.sqrt(np.maximum(ss2 - ss * ss / n, 1e-9)) * den)
        k = int(np.argmax(ncc))
        y, x = np.unravel_index(k, ncc.shape)
        if best is None or ncc[y, x] > best[0]:
            best = (float(ncc[y, x]), int(x), int(y), scale, (w, h))
    return best


def apply_ui_changes(hud, log=say):
    """Bearbeitete UI-Ausschnitte in die Referenzleiste einsetzen (Lage und Massstab gemessen)."""
    from PIL import Image

    changes = ui_changes()
    if not changes:
        return hud
    cache_path = HUD_DIR / "ui-treffer.json"
    cache = katalog.load_json(cache_path, {})
    sheets: dict = {}
    out = hud.copy()
    placed = 0
    for change in changes:
        key = f"{change['sheet']}|{change['key']}"
        hit = cache.get(key)
        if hit is None:
            if change["sheet"] not in sheets:
                sheets[change["sheet"]] = _delivered_ui_sheet(change["sheet"])
            sheet = sheets[change["sheet"]]
            if sheet is None:
                continue
            x, y, w, h = change["rect"]
            original = sheet.crop((x, y, x + w, y + h))
            scales = [round(0.30 + 0.05 * i, 2) for i in range(27)]
            best = _locate(out, original, scales)
            hit = {"ncc": best[0], "x": best[1], "y": best[2], "groesse": list(best[4])} if best else {"ncc": 0}
            cache[key] = hit
        if hit.get("ncc", 0) < 0.9:
            continue
        new = change["neu"].resize(tuple(hit["groesse"]), Image.Resampling.BILINEAR)
        region = out.crop((hit["x"], hit["y"], hit["x"] + new.width, hit["y"] + new.height))
        region.paste(new, (0, 0), new)
        out.paste(region, (hit["x"], hit["y"]))
        placed += 1
    katalog.save_json(cache_path, cache)
    if placed:
        log(f"{placed} bearbeitete UI-Ausschnitte in die Leiste eingesetzt")
    return out


def compose_hud(world, scale: float = 1.0):
    """Oberflaeche aus einem echten Spielbild (sandbox/hud) unten rechts einblenden."""
    from PIL import Image

    hud_path = HUD_DIR / "hud.png"
    if not hud_path.is_file():
        return world
    hud = Image.open(hud_path).convert("RGBA")
    try:
        hud = apply_ui_changes(hud)
    except Exception as exc:  # Nachsicht: die Leiste bleibt dann unveraendert
        say(f"WARNUNG: UI-Ersetzung uebersprungen ({exc})")
    if scale != 1.0:
        hud = hud.resize((round(hud.width * scale), round(hud.height * scale)), Image.Resampling.NEAREST)
    view = world.copy()
    view.alpha_composite(hud, (max(view.width - hud.width, 0), max(view.height - hud.height, 0)))
    return view


# ------------------------------------------------------------------ CLI

def cmd_render(args) -> int:
    scene = load_scene(Path(args.szene) if args.szene else None)
    source = FrameSource(args.modus, Path(args.mod) if args.mod else None, args.bc7)
    start = time.perf_counter()
    image, items, missing = render(scene, source, args.zeit, args.raster, args.pivots)
    if args.hud:
        image = compose_hud(image)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    say(f"{len(items)} Sprites gezeichnet in {time.perf_counter() - start:.2f} s -> {out}")
    if missing:
        say(f"WARNUNG: ohne Bild (Gruppe nicht exportierbar/geliefert): {missing}")
    return 0


def cmd_abgleich(args) -> int:
    """Jedes Sprite der Szene im echten Spielbild suchen (maskierte NCC, 1:1)."""
    import numpy as np
    from PIL import Image
    from scipy.signal import fftconvolve

    scene = load_scene(Path(args.szene) if args.szene else None)
    source = FrameSource(args.modus, Path(args.mod) if args.mod else None, False)
    shot = np.asarray(Image.open(args.bild).convert("RGB"), dtype=np.float64)
    if args.bereich:
        x0, y0, x1, y1 = args.bereich
        shot = shot[y0:y1, x0:x1]
    gray = shot @ np.array([0.299, 0.587, 0.114])
    s2 = gray * gray
    seen, scores = set(), []
    for item in scene_items(scene, 0.0):
        if item.layer == 0 or (item.group, item.name) in seen:
            continue
        seen.add((item.group, item.name))
        frame = source.frame(item.group, item.name)
        if frame is None:
            continue
        rgba = np.asarray(frame.image, dtype=np.float64)
        h, w = rgba.shape[:2]
        mask = (rgba[..., 3] > 200).astype(np.float64)
        n = mask.sum()
        if n < args.min_pixel or h > gray.shape[0] or w > gray.shape[1]:
            continue
        t = rgba[..., :3] @ np.array([0.299, 0.587, 0.114])
        tc = (t - (t * mask).sum() / n) * mask
        denom = math.sqrt((tc * tc).sum())
        if denom < 1e-6:
            continue
        flip = mask[::-1, ::-1]
        num = fftconvolve(gray, tc[::-1, ::-1], mode="valid")
        ssum = fftconvolve(gray, flip, mode="valid")
        ssum2 = fftconvolve(s2, flip, mode="valid")
        var = np.maximum(ssum2 - ssum * ssum / n, 1e-9)
        ncc = num / (np.sqrt(var) * denom)
        k = int(np.argmax(ncc))
        yy, xx = np.unravel_index(k, ncc.shape)
        scores.append((float(ncc[yy, xx]), item.name, int(xx), int(yy)))
    scores.sort(reverse=True)
    good = [s for s in scores if s[0] >= args.schwelle]
    for score, name, x, y in scores[: args.anzahl]:
        say(f"NCC={score:.4f}  {name:<28} Lage=({x},{y})")
    say(f"{len(good)} von {len(scores)} Sprites der Szene im Spielbild wiedergefunden (NCC >= {args.schwelle}).")
    return 0


# Form der Spielleiste bei 2560x1440 (vermessen am Spielbild 2026-09-05_194636):
# Pergamentleiste mit Schriftrollen-Saeule, Schluesselleiste, Minikarte, Berater.
# Rechtecke in Bildschirmpixeln (x0, y0, x1, y1); "gleich" = nur Pixel behalten,
# die in allen Bildern uebereinstimmen (Berater-Silhouette vor wechselnder Welt).
HUD_FORM_2560 = {
    "fest": [(1060, 1195, 2105, 1440), (1060, 1170, 1096, 1440), (2100, 1168, 2382, 1440),
             (2230, 1152, 2268, 1195), (2360, 1195, 2560, 1440)],
    "gleich": [(2380, 1055, 2560, 1200), (1990, 1150, 2110, 1200)],
}


def cmd_hud(args) -> int:
    """HUD-Referenz aus Spielbildern ausschneiden (Form 2560x1440, auf andere 16:9 skaliert)."""
    import numpy as np
    from PIL import Image

    shots = [np.asarray(Image.open(p).convert("RGB"), dtype=np.int16) for p in args.bilder]
    h, w = shots[0].shape[:2]
    if any(s.shape != shots[0].shape for s in shots):
        raise SystemExit("Alle Spielbilder muessen dieselbe Aufloesung haben.")
    factor = w / 2560.0
    if abs(h / w - 1440 / 2560) > 0.01:
        say("WARNUNG: kein 16:9-Bild - die Leistenform wird trotzdem proportional uebernommen.")
    mask = np.zeros((h, w), dtype=bool)

    def box(rect):
        x0, y0, x1, y1 = (round(v * factor) for v in rect)
        return slice(max(y0, 0), min(y1, h)), slice(max(x0, 0), min(x1, w))

    for rect in HUD_FORM_2560["fest"]:
        mask[box(rect)] = True
    for rect in HUD_FORM_2560["gleich"]:
        sl = box(rect)
        same = np.ones(mask[sl].shape, dtype=bool)
        for other in shots[1:]:
            same &= np.abs(shots[0][sl] - other[sl]).max(axis=2) <= args.toleranz
        if len(shots) > 1:
            mask[sl] |= same
    x0 = int(np.flatnonzero(mask.any(axis=0)).min())
    y0 = int(np.flatnonzero(mask.any(axis=1)).min())
    reference = shots[args.referenz].astype(np.uint8)
    rgba = np.dstack([reference, (mask * 255).astype(np.uint8)])[y0:, x0:]
    HUD_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(HUD_DIR / "hud.png")
    katalog.save_json(HUD_DIR / "hud.json", {"bildschirm": [w, h], "x": x0, "y": y0,
                                             "quellen": [str(p) for p in args.bilder]})
    say(f"HUD-Referenz {w - x0}x{h - y0} px aus {len(shots)} Spielbild(ern) -> {HUD_DIR / 'hud.png'}")
    return 0


def cmd_fenster(args) -> int:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    window = SandboxWindow(root, Path(args.szene) if args.szene else None)
    window.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return 0


# ------------------------------------------------------------------ window

class SandboxWindow:
    """Tk-Fenster; wird auch aus der Universal-Suite geoeffnet."""

    def __new__(cls, master, scene_path=None, on_select=None):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        from PIL import ImageTk

        win = tk.Toplevel(master)
        win.title("Vorschau-Sandkasten - Stronghold Europe")
        win.geometry("1500x940")
        win.configure(bg="#1e1f22")
        state = {
            "scene_path": scene_path or SCENES / "beispieldorf.json",
            "tick": 0.0, "running": True, "photo": None, "items": [], "image": None,
        }
        state["scene"] = load_scene(state["scene_path"])
        mode = tk.StringVar(value="arbeit")
        zoom = tk.IntVar(value=1)
        grid = tk.BooleanVar(value=False)
        pivots = tk.BooleanVar(value=False)
        hud = tk.BooleanVar(value=True)
        bc7 = tk.BooleanVar(value=True)
        animate = tk.BooleanVar(value=True)
        team = tk.StringVar(value="rot")
        status = tk.StringVar(value="Szene wird vorbereitet ...")

        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=8, pady=6)
        ttk.Label(bar, text="Quelle:").pack(side="left")
        ttk.Combobox(bar, textvariable=mode, values=list(MODES), state="readonly", width=11).pack(side="left", padx=4)
        ttk.Label(bar, text="Zoom:").pack(side="left", padx=(10, 0))
        ttk.Combobox(bar, textvariable=zoom, values=[1, 2, 3], state="readonly", width=3).pack(side="left", padx=4)
        ttk.Label(bar, text="Teamfarbe:").pack(side="left", padx=(10, 0))
        ttk.Combobox(bar, textvariable=team, values=[k for k in TEAM_COLOURS if k != "keine"], state="readonly",
                     width=8).pack(side="left", padx=4)
        for text, var in (("Animation", animate), ("Raster", grid), ("Pivots", pivots), ("Oberflaeche", hud),
                          ("BC7-Simulation", bc7)):
            ttk.Checkbutton(bar, text=text, variable=var, command=lambda: rebuild(True)).pack(side="left", padx=4)
        ttk.Button(bar, text="Neu laden", command=lambda: rebuild(False)).pack(side="right", padx=3)
        ttk.Button(bar, text="Szene speichern", command=lambda: save_scene()).pack(side="right", padx=3)
        ttk.Button(bar, text="Szene oeffnen", command=lambda: open_scene()).pack(side="right", padx=3)
        ttk.Button(bar, text="Als PNG", command=lambda: export_png()).pack(side="right", padx=3)

        place_bar = ttk.Frame(win)
        place_bar.pack(fill="x", padx=8)
        ttk.Label(place_bar, text="Platzieren:").pack(side="left")
        place_group = tk.StringVar(value="")
        place_frame = tk.StringVar(value="0")
        place_kind = tk.StringVar(value="sprite")
        ttk.Combobox(place_bar, textvariable=place_kind, values=["sprite", "kachelobjekt"], state="readonly",
                     width=12).pack(side="left", padx=4)
        ttk.Label(place_bar, text="Gruppe").pack(side="left")
        ttk.Combobox(place_bar, textvariable=place_group, values=katalog.known_groups(), width=24).pack(side="left", padx=4)
        ttk.Label(place_bar, text="Frame / erster Index").pack(side="left")
        ttk.Entry(place_bar, textvariable=place_frame, width=8).pack(side="left", padx=4)
        ttk.Label(place_bar, text="Raster (bei Kachelobjekt)").pack(side="left")
        place_grid = tk.StringVar(value="4x4")
        ttk.Entry(place_bar, textvariable=place_grid, width=6).pack(side="left", padx=4)
        ttk.Label(place_bar, text="Animation von-bis (leer = keine)").pack(side="left")
        place_anim = tk.StringVar(value="")
        ttk.Entry(place_bar, textvariable=place_anim, width=9).pack(side="left", padx=4)
        ttk.Label(place_bar, text="-> dann Linksklick auf eine Kachel; Rechtsklick entfernt", foreground="#9a9a9a").pack(side="left", padx=8)

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        canvas = tk.Canvas(body, bg="#18191b", highlightthickness=0)
        xs = ttk.Scrollbar(body, orient="horizontal", command=canvas.xview)
        ys = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=lambda *a: (xs.set(*a), place_hud()),
                         yscrollcommand=lambda *a: (ys.set(*a), place_hud()))
        canvas.bind("<Configure>", lambda _e: place_hud())
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        canvas.pack(fill="both", expand=True)
        ttk.Label(win, textvariable=status).pack(fill="x", padx=8, pady=(0, 6))

        def make_source():
            state["source"] = FrameSource(mode.get(), None, bc7.get(), log=lambda t: status.set(t))

        def draw():
            try:
                image, items, missing = render(state["scene"], state["source"], state["tick"] if animate.get() else 0.0,
                                               grid.get(), pivots.get(), team.get())
            except Exception as exc:  # Nachsicht: Fehler anzeigen, Fenster bleibt
                status.set(f"Zeichnen fehlgeschlagen: {exc}")
                return
            state["items"] = items
            state["image"] = compose_hud(image) if hud.get() else image
            factor = zoom.get()
            shown = image if factor == 1 else image.resize((image.width * factor, image.height * factor), 0)
            state["photo"] = ImageTk.PhotoImage(shown)
            canvas.delete("welt")
            canvas.create_image(0, 0, image=state["photo"], anchor="nw", tags=("welt",))
            canvas.tag_lower("welt")
            canvas.configure(scrollregion=(0, 0, shown.width, shown.height))
            if not state.get("centred"):
                state["centred"] = True
                canvas.update_idletasks()
                canvas.xview_moveto(max(0.0, 0.5 - canvas.winfo_width() / max(shown.width, 1) / 2))
                canvas.yview_moveto(max(0.0, 0.62 - canvas.winfo_height() / max(shown.height, 1) / 2))
            place_hud()
            text = f"{MODES[mode.get()]} | {len([i for i in items if i.layer])} Objekt-Sprites"
            if missing:
                text += f" | ohne Bild: {', '.join(missing)}"
            status.set(text + " | 1:1, Punktfilter; Teamfarbe/Wind/Licht genaehert")

        def load_hud():
            from PIL import Image as _Image

            state["hud_photo"] = None
            path = HUD_DIR / "hud.png"
            if path.is_file():
                image = _Image.open(path).convert("RGBA")
                try:
                    image = apply_ui_changes(image, log=lambda t: status.set(t))
                except Exception as exc:
                    status.set(f"UI-Ersetzung uebersprungen: {exc}")
                state["hud_photo"] = ImageTk.PhotoImage(image)
                state["hud_size"] = image.size

        def place_hud(*_args):
            # Wie im Spiel: die Leiste steht fest am Fensterrand, die Welt scrollt darunter.
            canvas.delete("hud")
            if not hud.get():
                return
            if state.get("hud_photo") is None:
                load_hud()
            if state.get("hud_photo") is None:
                return
            w, h = state["hud_size"]
            x = canvas.canvasx(canvas.winfo_width()) - w
            y = canvas.canvasy(canvas.winfo_height()) - h
            canvas.create_image(x, y, image=state["hud_photo"], anchor="nw", tags=("hud",))
            canvas.tag_raise("hud")

        def rebuild(keep_source):
            if not keep_source or state.get("source") is None or state["source"].mode != mode.get() \
                    or state["source"].bc7 != bc7.get():
                make_source()
            draw()

        def loop():
            if not win.winfo_exists():
                return
            if animate.get():
                state["tick"] += 0.1
                draw()
            win.after(100, loop)

        def tile_at(event):
            factor = zoom.get()
            x = canvas.canvasx(event.x) / factor
            y = canvas.canvasy(event.y) / factor
            width, height = state["scene"].get("karte", [24, 24])
            ox, oy = height * HALF_W + HALF_W, 420
            u = (x - ox) / HALF_W
            v = (y - oy) / HALF_H
            return int(math.floor((u + v) / 2 + 0.5)), int(math.floor((v - u) / 2 + 0.5)), x, y

        def on_click(event):
            tx, ty, x, y = tile_at(event)
            if place_group.get():
                obj = {"art": place_kind.get(), "gruppe": place_group.get(), "x": tx, "y": ty}
                try:
                    if place_kind.get() == "kachelobjekt":
                        cols, rows = (int(v) for v in place_grid.get().lower().split("x"))
                        obj.update({"von": int(place_frame.get()), "spalten": cols, "zeilen": rows, "layout": "gm1"})
                    else:
                        obj["frame"] = int(place_frame.get())
                        if place_anim.get().strip():
                            lo, hi = (int(v) for v in place_anim.get().split("-"))
                            obj["animation"] = {"von": lo, "bis": hi, "fps": 10}
                except ValueError:
                    messagebox.showinfo("Platzieren", "Frame, Raster (z.B. 4x4) und Animation (z.B. 0-24) pruefen.", parent=win)
                    return
                state["scene"].setdefault("objekte", []).append(obj)
                draw()
                return
            hit = None
            for item in reversed(state["items"]):
                if item.layer and item.box and item.box[0] <= x < item.box[2] and item.box[1] <= y < item.box[3]:
                    frame = state["source"].frame(item.group, item.name)
                    if frame is not None:
                        px, py = int(x - item.box[0]), int(y - item.box[1])
                        if frame.image.getpixel((px, py))[3] > 0:
                            hit = (item, frame)
                            break
            if hit:
                item, frame = hit
                status.set(f"{item.name}  ({item.title or item.group})  Kachel {item.x},{item.y}  Quelle: {frame.side}"
                           f"  {frame.image.width}x{frame.image.height}")
                if on_select:
                    on_select(item.group, item.name)
            else:
                status.set(f"Kachel {tx},{ty}")

        def on_right(event):
            tx, ty, _x, _y = tile_at(event)
            objects = state["scene"].get("objekte", [])
            for i in range(len(objects) - 1, -1, -1):
                o = objects[i]
                w, h = (o.get("spalten", 1), o.get("zeilen", 1))
                if o["x"] <= tx < o["x"] + w and o["y"] <= ty < o["y"] + h:
                    del objects[i]
                    draw()
                    return

        def save_scene():
            path = filedialog.asksaveasfilename(parent=win, initialdir=str(SCENES), defaultextension=".json",
                                                filetypes=[("Szene", "*.json")])
            if path:
                Path(path).write_text(json.dumps(state["scene"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                state["scene_path"] = Path(path)

        def open_scene():
            path = filedialog.askopenfilename(parent=win, initialdir=str(SCENES), filetypes=[("Szene", "*.json")])
            if path:
                state["scene_path"] = Path(path)
                state["scene"] = load_scene(Path(path))
                draw()

        def export_png():
            if state["image"] is None:
                return
            path = filedialog.asksaveasfilename(parent=win, defaultextension=".png", filetypes=[("PNG", "*.png")])
            if path:
                state["image"].save(path)

        canvas.bind("<Button-1>", on_click)
        canvas.bind("<Button-3>", on_right)
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        canvas.bind("<Shift-MouseWheel>", lambda e: canvas.xview_scroll(-1 if e.delta > 0 else 1, "units"))

        def start():
            status.set("Exporte der Szenengruppen werden vorbereitet (einmalig, danach im Katalog-Cache) ...")
            win.update_idletasks()
            make_source()
            draw()
            loop()

        win.after(50, start)
        win.reload = lambda: rebuild(False)
        return win


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("render", help="Szene als PNG zeichnen")
    p.add_argument("szene", nargs="?")
    p.add_argument("--out", default="work/sandkasten/szene.png")
    p.add_argument("--modus", choices=list(MODES), default="arbeit")
    p.add_argument("--mod")
    p.add_argument("--zeit", type=float, default=0.0)
    p.add_argument("--raster", action="store_true")
    p.add_argument("--pivots", action="store_true")
    p.add_argument("--hud", action="store_true")
    p.add_argument("--bc7", action="store_true")
    p.set_defaults(func=cmd_render)
    p = sub.add_parser("abgleich", help="Szenen-Sprites in einem echten Spielbild wiederfinden")
    p.add_argument("szene", nargs="?")
    p.add_argument("--bild", required=True)
    p.add_argument("--bereich", type=int, nargs=4)
    p.add_argument("--modus", choices=list(MODES), default="geliefert")
    p.add_argument("--mod")
    p.add_argument("--schwelle", type=float, default=0.99)
    p.add_argument("--min-pixel", type=int, default=300)
    p.add_argument("--anzahl", type=int, default=20)
    p.set_defaults(func=cmd_abgleich)
    p = sub.add_parser("hud", help="Oberflaechen-Referenz aus echten Spielbildern ausschneiden")
    p.add_argument("--bilder", nargs="+", required=True)
    p.add_argument("--toleranz", type=int, default=6)
    p.add_argument("--referenz", type=int, default=0, help="welches Bild die Pixel liefert (Index)")
    p.set_defaults(func=cmd_hud)
    p = sub.add_parser("fenster", help="Sandkasten-Fenster oeffnen")
    p.add_argument("szene", nargs="?")
    p.set_defaults(func=cmd_fenster)
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
