"""Europaeische Vegetation fuer Crusader-Plaetze erzeugen, die keinen Spender haben.

Der Kakteensatz (``tree_cactii``, 17 Frames, alle KEEP_CRUSADER) und der
Birkensatz (``tree_birch``, 148 Frames, davon 75 Palmen ohne Spender) bekommen
in Stronghold 1 keinen gleichnamigen Frame. Dieses Skript malt sie aus
Stronghold-1-Pixeln, die schon im Spiel sind - Straeucher aus ``tree_shrub1`` /
``tree_shrub2``, Birken und Eichen aus ``tree_birch`` / ``Tree_Oak`` - auf die
exakte Crusader-Leinwand jedes Zielframes und legt sie unter ``work/art_gen/``
ab. Von dort geht es den normalen Rueckweg::

    python tools/vegetation_gen.py cactii
    ... UEBERSICHT-tree_cactii-01.png ansehen ...
    python tools/sprites.py import work/art_gen/tree_cactii --set tree-cactii-europe --origin derived --check-only

Drei Regeln, die das Ergebnis tragen:

**Exakte Leinwand.** Der Lader zwingt jedem gelieferten Bild den anteiligen
Fusspunkt des Crusader-Platzes auf (``authored_sprite_foot_point``); nur auf
derselben Leinwand ist die Abweichung null. Deshalb wird nie beschnitten,
sondern verweigert, wenn ein skalierter Spender nicht in die Leinwand passt.

**Nie hochskalieren.** Jeder Skalenfaktor ist <= 1.0. Ein hochskalierter
Strauch wuerde weich und faellt neben den scharfen Nachbarn auf.

**Gerades Alpha, kein Halo.** Die Quelltexturen tragen unter Alpha 0 teils
Schwarz (gemessen an den SH1-Strauchframes: 560-1340 schwarze A0-Pixel je
Frame). Ein Resize ueber gerades RGBA zieht dieses Schwarz in die Kanten.
Deshalb wird ausdruecklich premultipliziert skaliert (Pillow-Modus ``RGBa``)
und danach zurueckgerechnet - der Lader premultipliziert beim Laden selbst
noch einmal (SHCDESE_139_LIMITS.md, "LoadTexture premultiplies alpha"),
geliefert werden muss also gerades Alpha.

Alles ist deterministisch: feste Tabellen, ganzzahlige Offsets, kein Zufall,
kein Zeitstempel, Pillow gepinnt (pyproject.toml). Ein zweiter Lauf liefert
dieselben ``pixels_sha256``; der Bericht druckt sie je Frame.

Der Birkensatz ist nur ein Entwurf hinter ``--entwurf``: er hat keinen
Allowlist-Eintrag und keinen Profilabschnitt, solange die Foliage-Frage offen
ist (docs/TREE_BIRCH_DEFEKT.md, Abschnitt "Ersatz ueber Einzelsprites").
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DEFAULT_OUT = "work/art_gen"

# Ab hier gilt ein Pixel als "opak", wenn die Grundlinie eines Crusader-Frames
# gemessen wird. Gemessen, nicht angenommen: die drei 360er-Leinwaende von
# tree_cactii (Frames 0-2) tragen ueber die GANZE Flaeche Alpha 1..7 (rund
# 8000 Pixel je Frame), die eigentliche Kakteengruppe ist 60-90 px breit.
# Ohne Schwelle waere die Bounding-Box die Leinwand selbst und die Grundlinie
# der Leinwandrand statt des Fusses.
OPAQUE_ALPHA = 128


class VegetationError(RuntimeError):
    """Ein Verstoss gegen eine Erzeugerregel; es wird nichts geschrieben."""


# --- Kompositionstabelle Kakteen ---------------------------------------------
#
# Je Crusader-Slot eine Liste von Platzierungen (Spendername, Skala, dx, dy).
# Spender sind SH1-Frames von tree_shrub1 (Laubstrauch, 117-123 x 84-88 px)
# und tree_shrub2 (Grasbueschel, 83-87 x 71-74 px) - genau die Pixel, die die
# Mod fuer diese beiden Gruppen ohnehin ausliefert, damit Ersatz und Nachbar
# im Spiel aus einer Hand sind.
#
# Anker je Slot: horizontal die Mitte der opaken Bounding-Box des
# Crusader-Frames, senkrecht deren Unterkante (Grundlinie). dx verschiebt
# nach rechts, dy nach vorn (bildschirmabwaerts). Bei mehreren Straeuchern in
# einem Slot sind sie isometrisch gestaffelt: zwischen zwei Platzierungen
# gilt 2*ddy == ddx, d.h. sie stehen auf einer Isometrie-Reihe. Der vorderste
# steht auf der Grundlinie (dy=0), die anderen dahinter (dy<0).
#
# Warum welcher Spender: Frames 0-2 zeigen kleine Kakteengruppen (2-3 Stueck),
# 3-5 breite Agaven, 6-8 Feigenkakteen, 9-11 niedrige Saeulengruppen, 12-16
# hohe Saeulenkakteen. Fuer schmale Slots das Grasbueschel (passt ohne
# Skalierung), fuer breite der Laubstrauch, fuer die drei Gruppen ein
# gestaffeltes Paar bzw. Trio.
CACTII_COMPOSITION: dict[int, tuple[tuple[str, float, int, int], ...]] = {
    0: (("tree_shrub2-0", 0.75, -20, -10), ("tree_shrub2-12", 0.75, 0, 0)),
    1: (
        ("tree_shrub1-5", 0.5, -34, -17),
        ("tree_shrub2-3", 0.7, -8, -4),
        ("tree_shrub2-16", 0.7, 0, 0),
    ),
    2: (("tree_shrub2-8", 0.7, -24, -12), ("tree_shrub2-20", 0.7, 0, 0)),
    3: (("tree_shrub1-2", 1.0, -30, -15), ("tree_shrub1-9", 1.0, 0, 0)),
    4: (("tree_shrub1-14", 1.0, 0, 0),),
    5: (("tree_shrub1-21", 1.0, 0, 0),),
    6: (("tree_shrub1-7", 0.92, 0, 0),),
    7: (("tree_shrub1-18", 0.94, 0, 0),),
    8: (("tree_shrub2-5", 1.0, 0, 0),),
    9: (("tree_shrub2-10", 1.0, 0, 0),),
    10: (("tree_shrub2-14", 1.0, 0, 0),),
    11: (("tree_shrub2-19", 1.0, 0, 0),),
    12: (("tree_shrub1-11", 0.8, 0, 0),),
    13: (("tree_shrub1-16", 0.8, 0, 0),),
    14: (("tree_shrub1-0", 1.0, 0, 0),),
    # 15 und 16 sind die schmalsten Leinwaende (85 und 63 px): dort ein 83 px
    # breites Bueschel bzw. eines auf 62 px, um einen Pixel nach rechts, weil
    # die Boxmitte bei 30 liegt und 62//2 = 31 sonst links heraussteht.
    15: (("tree_shrub2-21", 1.0, 0, 0),),
    16: (("tree_shrub2-24", 0.75, 1, 0),),
}
CACTII_GROUP = "tree_cactii"
CACTII_DONOR_GROUPS = ("tree_shrub1", "tree_shrub2")

# --- Birken: Faell-Ersatztabelle -----------------------------------------------
#
# Crusader fuehrt in tree_birch 55-72 eine stehende Schwingschleife, Stronghold
# 1 an denselben Indizes eine Faellsequenz (docs/TREE_BIRCH_DEFEKT.md, gemessen
# an den Massen 217x150 .. 58x31). Die 13 liegenden Spender werden durch die
# jeweils naechstliegende stehende Birke ersetzt. Bewusst dokumentierte
# Einschraenkung: mehrere Animationsphasen zeigen dann dasselbe Standbild.
BIRCH_FELL_SUBSTITUTES: dict[int, int] = {
    55: 54, 56: 54, 57: 54,
    58: 61, 59: 61, 60: 61,
    65: 64, 66: 64, 67: 64,
    68: 71, 69: 71, 70: 71,
    72: 71,
}
BIRCH_GROUP = "tree_birch"
BIRCH_OAK_GROUP = "Tree_Oak"
BIRCH_SH1_FRAMES = 73  # 0..72 haben SH1-Spender, 73..147 sind Palmen


# --- reine Rechenregeln (ohne Spieldaten testbar) -----------------------------


def frame_index(name: str) -> int:
    match = re.search(r"(\d+)\s*$", name)
    if match is None:
        raise VegetationError(f"Kein Frameindex im Namen: {name!r}")
    return int(match.group(1))


def opaque_bbox(image: Any, threshold: int = OPAQUE_ALPHA) -> tuple[int, int, int, int]:
    """Bounding-Box aller Pixel mit Alpha >= threshold (Pillow-Koordinaten)."""

    mask = image.getchannel("A").point(lambda v: 255 if v >= threshold else 0)
    bbox = mask.getbbox()
    if bbox is None:
        raise VegetationError("Frame hat keinen opaken Pixel - keine Grundlinie messbar")
    return bbox


def baseline_anchor(bbox: tuple[int, int, int, int], canvas_height: int) -> tuple[int, int]:
    """(Mitte der Box, Unterkante der Box von UNTEN gezaehlt).

    Von unten, weil der Lader so zaehlt (Unity) und die Fusspunkte im
    Profilabschnitt ebenfalls von unten stehen; so vergleicht der Bericht
    Gleiches mit Gleichem.
    """

    left, _top, right, bottom = bbox
    return ((left + right) // 2, canvas_height - bottom)


def scaled_size(width: int, height: int, scale: float) -> tuple[int, int]:
    if not 0.0 < scale <= 1.0:
        raise VegetationError(f"Skala muss in (0, 1] liegen, nie hochskalieren: {scale}")
    return (max(1, round(width * scale)), max(1, round(height * scale)))


def resize_straight_alpha(image: Any, size: tuple[int, int]) -> Any:
    """LANCZOS-Resize ohne dunkle Raender, Ergebnis in geradem Alpha.

    Ausdruecklich ueber Pillows premultiplizierten Modus ``RGBa``. Pillow
    12.3.0 tut das fuer RGBA in ``Image.resize`` intern selbst (Image.py:2406,
    gemessen: eine weisse Kante ueber schwarzem A0-Grund bleibt (255,255,255,14)
    statt grau) - hier steht es trotzdem ausgeschrieben, damit die Regel nicht
    an einer internen Verzweigung haengt und ein Test sie halten kann. Und
    NICHT von Hand vor-premultiplizieren und dann RGBA skalieren: das waere
    doppelt und zoege die Kanten wieder dunkel.
    """

    from PIL import Image

    if image.mode != "RGBA":
        raise VegetationError(f"Spender muss RGBA sein, nicht {image.mode}")
    if tuple(image.size) == tuple(size):
        # Bei Skala 1.0 bleiben die SH1-Pixel bitgleich - kein Umweg ueber RGBa,
        # der an halbtransparenten Pixeln rundet.
        return image.copy()
    return image.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")


def paste_position(
    canvas_size: tuple[int, int],
    donor_size: tuple[int, int],
    anchor: tuple[int, int],
    dx: int,
    dy: int,
) -> tuple[int, int]:
    """Linke obere Ecke (Pillow) fuer einen Spender am Grundlinien-Anker.

    Der Spender steht mit seiner Unterkante auf der Grundlinie und mit seiner
    Mitte auf der Ankermitte, verschoben um (dx nach rechts, dy nach vorn).
    """

    for label, value in (("dx", dx), ("dy", dy)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise VegetationError(f"{label} muss ganzzahlig sein: {value!r}")
    _canvas_width, canvas_height = canvas_size
    width, height = donor_size
    cx, base = anchor
    left = cx - width // 2 + dx
    bottom_from_below = base - dy
    top = canvas_height - bottom_from_below - height
    return left, top


def fits(canvas_size: tuple[int, int], donor_size: tuple[int, int], left: int, top: int) -> bool:
    return (
        left >= 0
        and top >= 0
        and left + donor_size[0] <= canvas_size[0]
        and top + donor_size[1] <= canvas_size[1]
    )


def pivot_position(
    canvas_size: tuple[int, int],
    donor_size: tuple[int, int],
    scale: float,
    source_pivot_px: tuple[float, float],
    target_pivot_px: tuple[float, float],
) -> tuple[int, int, int, int]:
    """Fuss auf Fuss, in die Leinwand geklemmt: (left, top, klemm_dx, klemm_dy).

    Der skalierte SH1-Fusspunkt kommt auf den Crusader-Fusspunkt. Passt der
    Spender dann nicht ganz in die Leinwand, wird er hineingeschoben statt
    beschnitten, und die Klemmweite steht im Bericht - kein stilles Abschneiden.
    Setzt voraus, dass der Spender ueberhaupt in die Leinwand passt (min-fit).
    """

    canvas_width, canvas_height = canvas_size
    width, height = donor_size
    if width > canvas_width or height > canvas_height:
        raise VegetationError(
            f"Spender {width}x{height} passt nicht in {canvas_width}x{canvas_height}"
        )
    left = round(target_pivot_px[0] - scale * source_pivot_px[0])
    bottom = round(target_pivot_px[1] - scale * source_pivot_px[1])
    clamped_left = min(max(left, 0), canvas_width - width)
    clamped_bottom = min(max(bottom, 0), canvas_height - height)
    top = canvas_height - clamped_bottom - height
    return clamped_left, top, clamped_left - left, clamped_bottom - bottom


def min_fit_scale(source_size: tuple[int, int], canvas_size: tuple[int, int]) -> float:
    return min(1.0, canvas_size[0] / source_size[0], canvas_size[1] / source_size[1])


# NamedTuple statt dataclass: dataclasses loesen unter ``from __future__ import
# annotations`` ihre Annotationen ueber sys.modules[__module__] auf, und dieses
# Werkzeug wird von Tests und von der Suite per importlib geladen, wo es dort
# nicht zwingend registriert ist (Python 3.14, dataclasses.py:762).
class Placement(NamedTuple):
    donor: str
    scale: float
    dx: int
    dy: int


class PlacedDonor(NamedTuple):
    donor: str
    scale: float
    size: tuple[int, int]
    left: int
    top: int
    foot_from_below: tuple[float, float]


def compose_on_canvas(
    canvas_size: tuple[int, int],
    anchor: tuple[int, int],
    placements: list[tuple[Placement, Any, tuple[float, float]]],
) -> tuple[Any, list[PlacedDonor]]:
    """Alle Spender eines Slots auf eine transparente Leinwand malen.

    ``placements``: (Platzierung, Spenderbild RGBA, SH1-Fusspunkt in px von
    links/unten). Malreihenfolge von hinten nach vorn (dy aufsteigend), damit
    der vordere Strauch den hinteren ueberdeckt. Passt ein Spender nicht ganz,
    wird verweigert - nichts wird beschnitten.
    """

    from PIL import Image

    canvas_width, canvas_height = canvas_size
    canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
    placed: list[PlacedDonor] = []
    ordered = sorted(placements, key=lambda item: (item[0].dy, item[0].dx, item[0].donor))
    for placement, donor_image, source_pivot in ordered:
        size = scaled_size(donor_image.width, donor_image.height, placement.scale)
        left, top = paste_position(canvas_size, size, anchor, placement.dx, placement.dy)
        if not fits(canvas_size, size, left, top):
            raise VegetationError(
                f"{placement.donor} bei Skala {placement.scale} ({size[0]}x{size[1]}) "
                f"liegt mit ({left},{top}) ausserhalb der Leinwand "
                f"{canvas_width}x{canvas_height} - Tabelle anpassen, nicht beschneiden"
            )
        scaled = resize_straight_alpha(donor_image, size)
        canvas.alpha_composite(scaled, (left, top))
        bottom_from_below = canvas_height - top - size[1]
        placed.append(
            PlacedDonor(
                donor=placement.donor,
                scale=placement.scale,
                size=size,
                left=left,
                top=top,
                foot_from_below=(
                    left + placement.scale * source_pivot[0],
                    bottom_from_below + placement.scale * source_pivot[1],
                ),
            )
        )
    return canvas, placed


def cactii_table_check(
    table: dict[int, tuple[tuple[str, float, int, int], ...]] = CACTII_COMPOSITION,
) -> list[str]:
    """Die Tabellenregeln als Liste von Verstoessen (leer = in Ordnung)."""

    problems: list[str] = []
    if sorted(table) != list(range(17)):
        problems.append(f"Tabelle deckt nicht genau die Slots 0..16: {sorted(table)}")
    for slot, entries in table.items():
        if not entries:
            problems.append(f"Slot {slot}: keine Platzierung")
            continue
        for donor, scale, dx, dy in entries:
            if not any(donor.startswith(group + "-") for group in CACTII_DONOR_GROUPS):
                problems.append(f"Slot {slot}: {donor} ist kein Strauchspender")
            if not 0.0 < scale <= 1.0:
                problems.append(f"Slot {slot}: {donor} Skala {scale} nicht in (0, 1]")
            if any(isinstance(v, bool) or not isinstance(v, int) for v in (dx, dy)):
                problems.append(f"Slot {slot}: {donor} Offsets nicht ganzzahlig")
        if max(dy for _d, _s, _dx, dy in entries) != 0:
            problems.append(f"Slot {slot}: der vorderste Strauch steht nicht auf der Grundlinie")
        ordered = sorted(entries, key=lambda e: (e[3], e[2]))
        for (_d1, _s1, dx1, dy1), (_d2, _s2, dx2, dy2) in zip(ordered, ordered[1:]):
            if 2 * (dy2 - dy1) != (dx2 - dx1):
                problems.append(
                    f"Slot {slot}: Staffelung nicht isometrisch (ddx={dx2 - dx1}, ddy={dy2 - dy1})"
                )
    return problems


def birch_donor_name(index: int) -> str:
    """Welcher SH1-Frame den Crusader-Slot ``tree_birch-<index>`` fuellt."""

    if not 0 <= index < 148:
        raise VegetationError(f"tree_birch kennt keinen Slot {index}")
    if index >= BIRCH_SH1_FRAMES:
        return f"{BIRCH_OAK_GROUP}-{index}"
    return f"{BIRCH_GROUP}-{BIRCH_FELL_SUBSTITUTES.get(index, index)}"


# --- Spieldaten lesen (nur lesend) --------------------------------------------


def _sprites_tool() -> Any:
    spec = importlib.util.spec_from_file_location(
        "sprites_tool", Path(__file__).resolve().with_name("sprites.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_sprites(
    asset: Path, wanted: dict[int, str], *, with_trees: bool = False
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """Sprites nach path_id aus einer resources.assets lesen.

    Gibt (name -> RGBA-Bild, name -> Sprite-Typetree, environment) zurueck. Das
    environment bleibt am Leben, weil die Maskentextur spaeter aus demselben
    Ladevorgang geschnitten wird.
    """

    from stronghold_europe_de.unity_inventory import _import_unitypy, load_unity_asset

    if not asset.is_file():
        raise VegetationError(f"Spieldaten fehlen: {asset}")
    environment = load_unity_asset(asset, unitypy=_import_unitypy())
    images: dict[str, Any] = {}
    trees: dict[str, Any] = {}
    for obj in environment.objects:
        if obj.type.name != "Sprite" or obj.path_id not in wanted:
            continue
        name = wanted[obj.path_id]
        data = obj.read()
        if str(data.m_Name) != name:
            raise VegetationError(f"path_id {obj.path_id}: {data.m_Name} statt {name}")
        images[name] = data.image.convert("RGBA")
        if with_trees:
            trees[name] = obj.read_typetree()
    missing = sorted(set(wanted.values()) - set(images))
    if missing:
        raise VegetationError(f"Nicht in {asset.name} gefunden: {missing[:5]}")
    return images, trees, environment


def _pivot_px(meta: dict[str, Any]) -> tuple[float, float]:
    return (
        float(meta["pivot_x"]) * float(meta["width"]),
        float(meta["pivot_y"]) * float(meta["height"]),
    )


def _write_set(
    out_dir: Path,
    group: str,
    frames: list[dict[str, Any]],
    images: dict[str, Any],
    masks: dict[str, Any],
    report: dict[str, Any],
) -> None:
    """PNGs, index.json (fuer sprites.py sheet/check) und bericht.json schreiben.

    index.json traegt absichtlich KEIN pixels_sha256 je Frame: ``sprites.py
    import`` liest dieses Feld als "so sah der unbearbeitete Export aus" und
    liefert gleiche Bilder nicht - hier ist aber jedes Bild die Lieferung.
    Die Digests stehen im Bericht.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    # Nur die eigenen Erzeugnisse eines frueheren Laufs raeumen (Frames, Masken,
    # Blatt) - ein fremdes PNG, das jemand dort abgelegt hat, bleibt liegen.
    for stale in list(out_dir.glob(f"{group}-*.png")) + list(out_dir.glob(f"UEBERSICHT-{group}*.png")):
        stale.unlink()
    for name, image in sorted(images.items()):
        image.save(out_dir / f"{name}.png", format="PNG", optimize=False, compress_level=9)
    for name, image in sorted(masks.items()):
        image.save(out_dir / f"{name}_m.png", format="PNG", optimize=False, compress_level=9)
    (out_dir / "index.json").write_text(
        json.dumps({"group": group, "game": "erzeugt", "frames": frames}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "bericht.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _sheet(out_dir: Path, frame_count: int, cell: int, columns: int) -> None:
    """Uebersichtsblatt im Stil von ``sprites.py sheet`` - dieselbe Routine."""

    tool = _sprites_tool()
    rows = max(1, min(20, -(-frame_count // columns)))
    tool.cmd_sheet(
        argparse.Namespace(
            directory=str(out_dir), cell=cell, columns=columns, rows=rows,
            range_from=None, range_to=None,
        )
    )


def _digest(image: Any) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


# --- Kakteen ---------------------------------------------------------------------


def cmd_cactii(args: argparse.Namespace) -> int:
    tool = _sprites_tool()
    problems = cactii_table_check()
    if problems:
        print("Kompositionstabelle verletzt ihre Regeln:")
        for line in problems:
            print("  " + line)
        return 1

    rows = tool.read_mapping()
    targets = {
        str(r["name"]): r for r in rows if r.get("group") == CACTII_GROUP and r.get("target")
    }
    if len(targets) != 17:
        raise VegetationError(f"tree_cactii hat im Mapping {len(targets)} Frames statt 17")
    donors_meta = {
        str(r["name"]): r
        for r in rows
        if r.get("group") in CACTII_DONOR_GROUPS and r.get("source")
    }
    needed = sorted({p[0] for entries in CACTII_COMPOSITION.values() for p in entries})
    unknown = [d for d in needed if d not in donors_meta]
    if unknown:
        raise VegetationError(f"Spender ohne SH1-Quelle im Mapping: {unknown}")

    # Crusader-Originale, nur zum Messen der Grundlinie (Zielspiel bleibt lesend).
    target_images, _t, _env_t = _load_sprites(
        tool.game_assets("crusader"),
        {int(meta["target"]["path_id"]): name for name, meta in targets.items()},
    )
    donor_images, _d, _env_d = _load_sprites(
        tool.game_assets("stronghold1"),
        {int(donors_meta[name]["source"]["path_id"]): name for name in needed},
    )

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    out_dir = out_dir / CACTII_GROUP

    images: dict[str, Any] = {}
    frames: list[dict[str, Any]] = []
    report_frames: list[dict[str, Any]] = []
    print(f"{'Frame':<16} {'Leinwand':<9} {'Anker':<10} Spender (Skala, Groesse, Position, Fussabweichung)")
    for name in sorted(targets, key=frame_index):
        slot = frame_index(name)
        target = targets[name]["target"]
        canvas = (int(round(float(target["width"]))), int(round(float(target["height"]))))
        original = target_images[name]
        if original.size != canvas:
            raise VegetationError(f"{name}: Crusader-Bild {original.size} != Mapping {canvas}")
        anchor = baseline_anchor(opaque_bbox(original), canvas[1])
        placements = [
            (
                Placement(donor, scale, dx, dy),
                donor_images[donor],
                _pivot_px(donors_meta[donor]["source"]),
            )
            for donor, scale, dx, dy in CACTII_COMPOSITION[slot]
        ]
        image, placed = compose_on_canvas(canvas, anchor, placements)
        target_foot = _pivot_px(target)
        images[name] = image
        digest = _digest(image)
        frames.append(
            {
                "name": name,
                "file": f"{name}.png",
                "width": canvas[0],
                "height": canvas[1],
                "shown_from": "erzeugt",
                "crusader": {
                    "width": canvas[0],
                    "height": canvas[1],
                    "pivot_x": float(target["pivot_x"]),
                    "pivot_y": float(target["pivot_y"]),
                    "pixels_per_unit": float(target["pixels_per_unit"]),
                    "texture": str(target["texture_name"]),
                },
            }
        )
        detail = []
        for p in placed:
            dev = (p.foot_from_below[0] - target_foot[0], p.foot_from_below[1] - target_foot[1])
            detail.append(
                f"{p.donor} x{p.scale:g} {p.size[0]}x{p.size[1]} @({p.left},{p.top}) "
                f"Fuss {dev[0]:+.1f}/{dev[1]:+.1f}"
            )
        report_frames.append(
            {
                "name": name,
                "canvas": list(canvas),
                "anchor_center_x": anchor[0],
                "anchor_baseline_from_below": anchor[1],
                "target_foot_px": [round(target_foot[0], 3), round(target_foot[1], 3)],
                "placements": [
                    {
                        "donor": p.donor,
                        "scale": p.scale,
                        "size": list(p.size),
                        "left": p.left,
                        "top": p.top,
                        "foot_from_below": [round(v, 3) for v in p.foot_from_below],
                    }
                    for p in placed
                ],
                "pixels_sha256": digest,
            }
        )
        print(f"{name:<16} {canvas[0]}x{canvas[1]:<5} ({anchor[0]},{anchor[1]:<3})  " + "; ".join(detail))
        print(f"{'':<16} pixels_sha256 {digest}")

    report = {
        "group": CACTII_GROUP,
        "opaque_alpha": OPAQUE_ALPHA,
        "rule": "Grundlinie = Unterkante der opaken Crusader-Box, Mitte = Boxmitte; "
                "Spender aus SH1 tree_shrub1/tree_shrub2, Skala <= 1, RGBa-Resize",
        "frames": report_frames,
    }
    _write_set(out_dir, CACTII_GROUP, frames, images, {}, report)
    _sheet(out_dir, len(images), cell=200, columns=6)
    print()
    print(f"{len(images)} PNGs nach {out_dir}")
    print("Keine Masken: tree_cactii ist plain_shader, der Bauer wiese eine Maske ab.")
    print()
    print("Weiter, NACH der Sichtpruefung des Uebersichtsblatts:")
    print(
        f"  python tools/sprites.py import {out_dir.relative_to(PROJECT_ROOT).as_posix()} "
        "--set tree-cactii-europe --origin derived --check-only"
    )
    return 0


# --- Birken (Entwurf) -------------------------------------------------------------


def cmd_birch(args: argparse.Namespace) -> int:
    if not args.entwurf:
        print("Der Birkensatz ist ein Entwurf ohne Allowlist-Eintrag und ohne")
        print("Profilabschnitt (Foliage-Frage offen, docs/TREE_BIRCH_DEFEKT.md).")
        print("Erzeugen nur mit --entwurf; importieren laesst er sich heute nicht.")
        return 1
    from stronghold_europe_de.mod_builder import _crop_mask_for_sprite, _texture_objects

    tool = _sprites_tool()
    rows = tool.read_mapping()
    targets = {
        str(r["name"]): r for r in rows if r.get("group") == BIRCH_GROUP and r.get("target")
    }
    if len(targets) != 148:
        raise VegetationError(f"tree_birch hat im Mapping {len(targets)} Frames statt 148")
    sources = {
        str(r["name"]): r
        for r in rows
        if r.get("group") in (BIRCH_GROUP, BIRCH_OAK_GROUP) and r.get("source")
    }
    plan = {name: birch_donor_name(frame_index(name)) for name in targets}
    unknown = sorted({d for d in plan.values() if d not in sources})
    if unknown:
        raise VegetationError(f"Spender ohne SH1-Quelle im Mapping: {unknown[:5]}")
    donor_names = sorted(set(plan.values()))
    donor_images, donor_trees, environment = _load_sprites(
        tool.game_assets("stronghold1"),
        {int(sources[d]["source"]["path_id"]): d for d in donor_names},
        with_trees=True,
    )
    textures = {str(sources[d]["source"]["texture_name"]) for d in donor_names}
    if len(textures) != 1:
        raise VegetationError(f"Spender liegen auf mehreren Texturen: {sorted(textures)}")
    texture_name = textures.pop()
    _by_id, texture_by_name, texture_trees = _texture_objects(environment)
    mask_obj = texture_by_name.get(texture_name + "_m")
    if mask_obj is None:
        raise VegetationError(f"SH1-Maskentextur fehlt: {texture_name}_m")
    mask_sheet = mask_obj.read().image.convert("RGBA")

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    out_dir = out_dir / BIRCH_GROUP

    from PIL import Image

    images: dict[str, Any] = {}
    masks: dict[str, Any] = {}
    frames: list[dict[str, Any]] = []
    report_frames: list[dict[str, Any]] = []
    clamped_frames = 0
    print(f"{'Frame':<16} {'Leinwand':<9} {'Spender':<16} {'Skala':<6} {'Groesse':<9} {'Klemmung':<9} pixels_sha256")
    for name in sorted(targets, key=frame_index):
        target = targets[name]["target"]
        canvas = (int(round(float(target["width"]))), int(round(float(target["height"]))))
        donor = plan[name]
        source_meta = sources[donor]["source"]
        donor_image = donor_images[donor]
        source_size = (int(round(float(source_meta["width"]))), int(round(float(source_meta["height"]))))
        if donor_image.size != source_size:
            raise VegetationError(f"{donor}: Bild {donor_image.size} != Mapping {source_size}")
        scale = min_fit_scale(source_size, canvas)
        size = scaled_size(source_size[0], source_size[1], scale)
        left, top, clamp_dx, clamp_dy = pivot_position(
            canvas, size, scale, _pivot_px(source_meta), _pivot_px(target)
        )
        if clamp_dx or clamp_dy:
            clamped_frames += 1
        colour = Image.new("RGBA", canvas, (0, 0, 0, 0))
        colour.alpha_composite(resize_straight_alpha(donor_image, size), (left, top))
        # Maske: derselbe Rect, dieselbe Transformation, aber NEAREST - eine
        # Tint-Maske mit Halbtonkanten faerbte Randpixel halb.
        source_mask = _crop_mask_for_sprite(
            mask_sheet, texture_trees[texture_name], donor_trees[donor], source_size
        )
        if source_mask.size != size:
            source_mask = source_mask.resize(size, Image.Resampling.NEAREST)
        mask = Image.new("RGBA", canvas, (0, 0, 0, 0))
        mask.paste(source_mask, (left, top))
        images[name] = colour
        masks[name] = mask
        digest = _digest(colour)
        frames.append(
            {
                "name": name,
                "file": f"{name}.png",
                "width": canvas[0],
                "height": canvas[1],
                "shown_from": "erzeugt",
                "crusader": {
                    "width": canvas[0],
                    "height": canvas[1],
                    "pivot_x": float(target["pivot_x"]),
                    "pivot_y": float(target["pivot_y"]),
                    "pixels_per_unit": float(target["pixels_per_unit"]),
                    "texture": str(target["texture_name"]),
                },
            }
        )
        report_frames.append(
            {
                "name": name,
                "canvas": list(canvas),
                "donor": donor,
                "scale": round(scale, 6),
                "size": list(size),
                "left": left,
                "top": top,
                "clamp_dx": clamp_dx,
                "clamp_dy": clamp_dy,
                "pixels_sha256": digest,
                "mask_sha256": _digest(mask),
            }
        )
        print(
            f"{name:<16} {canvas[0]}x{canvas[1]:<5} {donor:<16} {scale:<6.3f} "
            f"{size[0]}x{size[1]:<5} {clamp_dx:+d}/{clamp_dy:<+5d} {digest}"
        )

    report = {
        "group": BIRCH_GROUP,
        "status": "ENTWURF - nicht lieferbar, kein Allowlist-Eintrag, kein Profilabschnitt",
        "rule": "0-72 SH1 tree_birch mit Faell-Ersatz, 73-147 SH1 Tree_Oak; min-fit s<=1; "
                "SH1-Fuss auf Crusader-Fuss, in die Leinwand geklemmt; Maske NEAREST",
        "fell_substitutes": {str(k): v for k, v in sorted(BIRCH_FELL_SUBSTITUTES.items())},
        "clamped_frames": clamped_frames,
        "frames": report_frames,
    }
    _write_set(out_dir, BIRCH_GROUP, frames, images, masks, report)
    _sheet(out_dir, len(images), cell=144, columns=16)
    print()
    print(f"{len(images)} Farbbilder + {len(masks)} Masken nach {out_dir}")
    print(f"Geklemmte Frames: {clamped_frames} (Klemmweiten je Frame im Bericht)")
    print()
    print("ENTWURF: kein Allowlist-Eintrag, kein Profilabschnitt. Der Einzelsprite-Weg")
    print("rendert Baeume mit Unlit/TeamColour statt Unlit/Foliage - Bedingung fuer die")
    print("Auslieferung steht in docs/TREE_BIRCH_DEFEKT.md.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vegetation_gen",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    cactii = sub.add_parser("cactii", help="17 Kakteenplaetze aus SH1-Straeuchern malen")
    cactii.add_argument("--out", default=DEFAULT_OUT, help="Ablage (Standard: work/art_gen)")
    cactii.set_defaults(func=cmd_cactii)

    birch = sub.add_parser("birch", help="148 Birkenplaetze aus SH1-Birken/Eichen malen (Entwurf)")
    birch.add_argument("--out", default=DEFAULT_OUT, help="Ablage (Standard: work/art_gen)")
    birch.add_argument(
        "--entwurf",
        action="store_true",
        help="ausdruecklich als Entwurf erzeugen; ohne Flag wird nur erklaert, warum nicht",
    )
    birch.set_defaults(func=cmd_birch)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except VegetationError as exc:
        print(f"Verweigert: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
