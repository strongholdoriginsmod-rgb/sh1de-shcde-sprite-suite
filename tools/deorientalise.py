"""Kuppelblau auf Bleigrau ziehen.

ACHTUNG, Stand 16.08.2026: Dieses Werkzeug faerbt die Kuppeln um. Den HALBMOND
entfernt es NICHT - vier Anlaeufe sind daran gescheitert, und die Gruende stehen
weiter unten, damit der naechste sie nicht wiederholt.

Fuer Bauwerke, die Crusader selbst erfunden hat und fuer die Stronghold 1
keinen Spender fuehrt. Die Moschee in `tile_churches` ist der Anlass: Ihre
Frames stehen samt und sonders als KEEP_CRUSADER im Mapping, weil es kein
gleichnamiges Stronghold-1-Sprite gibt. Sie auszunehmen aendert also nichts -
ausgenommen sind sie bereits. Wer sie loswerden will, muss das Bild anfassen.

## Was hier geschieht

**Kuppelblau wird Bleigrau.** Die Kuppeln sind ein kraeftiges Blau
   (190-230 Grad). Europaeische Kirchendaecher sind Blei oder Schiefer: gleiche
   Helligkeit, fast keine Saettigung. Die Helligkeit bleibt deshalb
   unangetastet - sie traegt die Woelbung.

**Die Kuppelform bleibt.** Eine Kuppel ist nicht orientalisch; Florenz und Aachen
haben welche.

## Warum der Halbmond bleibt - vier gescheiterte Anlaeufe

Farbschwelle und Formpruefung ziehen hier gegeneinander, und das ist keine
Frage besserer Werte, sondern der Bauart:

1. **Enge Goldschwelle** (Saettigung 0,55): Nur der helle Kern des Halbmonds
   faellt darunter, seine beschatteten Raender bleiben. Uebrig ist eine goldene
   Umrisslinie - ein HOHLER Halbmond, auffaelliger als ein voller.
2. **Weite Schwelle plus Weitung um zwei Pixel** (0,38): Die Halbmonde gehen -
   aber warme Steinlichter im Mauerwerk gelten jetzt ebenfalls als Gold, und das
   Loeschen schlaegt Loecher in die Waende. Gemessen 32404 entfernte Pixel, fast
   alle davon Wand.
3. **Weite Schwelle plus Pruefung auf freistehend** (Rand muss zu 45 Prozent an
   Durchsichtiges grenzen): Unter der weiten Schwelle waechst das Goldgebiet
   ueber die Steinlichter mit der Wand zusammen, gilt damit nicht mehr als
   freistehend und wird abgewiesen. 89 von 32404 Pixeln blieben uebrig.
4. **Enge Schwelle plus Weitung plus freistehend**: Der helle Kern ist von
   dunklerem Gold umgeben, das unter der engen Schwelle als undurchsichtiger
   Nachbar zaehlt. Der Kern sieht damit eingebettet aus und wird ebenfalls
   abgewiesen.

Ein fuenfter Weg waere, den Halbmond ueber seine FORM zu finden statt ueber die
Farbe - er sitzt immer als oberster zusammenhaengender Gegenstand ueber einer
Kugel. Das ist machbar, aber es ist Formerkennung und kein Farbfilter, und es
gehoert dann sauber gebaut statt an eine Umfaerbung angehaengt.

## Gebrauch

    python tools/sprites.py export tile_churches --game crusader --out work/kirchen
    python tools/deorientalise.py work/kirchen/tile_churches work/kirchen-europa 582 741
    python tools/sprites.py check work/kirchen-europa
    python tools/sprites.py import work/kirchen-europa --set tile-churches-europe --origin derived

`--origin derived` ist Pflicht: uebermaltes Firefly-Material gehoert nicht ins
Repository.
"""

from __future__ import annotations

import argparse
import colorsys
from collections import deque
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DeorientaliseError(RuntimeError):
    """Die Eingaben lassen sich nicht sicher verarbeiten."""


# Gold: Halbmond und Minarettspitze. Eng gefasst, damit Sandstein und
# Messingbeschlaege an Tueren nicht mitgehen.
GOLD_HUE_LOW = 40.0 / 360.0
GOLD_HUE_HIGH = 58.0 / 360.0
# Eng gefasst, und das mit Absicht - zwei Anlaeufe haben das gelehrt.
#
# Mit dieser Schwelle allein blieb vom Halbmond eine goldene Umrisslinie
# stehen, weil seine beschatteten Raender nicht mehr als Gold galten. Die
# Antwort darauf ist die WEITUNG weiter unten, nicht eine weichere Schwelle:
# Bei 0,38 gilt auch ein warmes Steinlicht als Gold, das Goldgebiet waechst
# ueber die Wand hinweg mit dem Mauerwerk zusammen, und dann greift weder die
# Groessengrenze noch die Freistehend-Pruefung - gemessen fielen so von 32404
# entfernten Pixeln fast alle auf Loecher in der Wand.
GOLD_SATURATION_MIN = 0.55
GOLD_VALUE_MIN = 0.50

# Ein Aufsatzstueck ist klein. Groessere zusammenhaengende Goldflaechen sind
# etwas anderes - ein Dach, ein Bodenmosaik - und bleiben unberuehrt.
GOLD_BLOB_MAX_PIXELS = 1400

# Anteil des Randes, der an Durchsichtiges grenzen muss, damit ein Goldgebiet
# als freistehender Aufsatz gilt. Gemessen an den Bildern: Halbmonde und
# Spitzen liegen weit ueber der Haelfte, Steinlichter praktisch bei null.
FREE_STANDING_MIN = 0.45

# Kuppelblau.
DOME_HUE_LOW = 190.0 / 360.0
DOME_HUE_HIGH = 230.0 / 360.0
DOME_SATURATION_MIN = 0.15
DOME_VALUE_MIN = 0.25

# Blei und Schiefer: gemessen an europaeischen Daechern derselben Spiele liegt
# die Saettigung bei rund einem Zehntel, der Farbton leicht ins Blaugraue.
LEAD_SATURATION = 0.10
LEAD_HUE = 215.0 / 360.0


def _is_gold(hue: float, saturation: float, value: float) -> bool:
    return (
        GOLD_HUE_LOW <= hue <= GOLD_HUE_HIGH
        and saturation >= GOLD_SATURATION_MIN
        and value >= GOLD_VALUE_MIN
    )


def _is_dome(hue: float, saturation: float, value: float) -> bool:
    return (
        DOME_HUE_LOW <= hue <= DOME_HUE_HIGH
        and saturation >= DOME_SATURATION_MIN
        and value >= DOME_VALUE_MIN
    )


def deorientalise_image(image: Image.Image) -> tuple[Image.Image, int, int]:
    """Ein Bild entorientalisieren; liefert (Bild, Goldpixel, Kuppelpixel)."""

    out = image.convert("RGBA").copy()
    pixels = out.load()
    width, height = out.size

    gold_mask = [[False] * width for _ in range(height)]
    dome_total = 0
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                continue
            hue, saturation, value = colorsys.rgb_to_hsv(
                red / 255, green / 255, blue / 255
            )
            if _is_gold(hue, saturation, value):
                gold_mask[y][x] = True
            elif _is_dome(hue, saturation, value):
                # Helligkeit unangetastet: Sie traegt die Woelbung.
                new_red, new_green, new_blue = colorsys.hsv_to_rgb(
                    LEAD_HUE, LEAD_SATURATION, value
                )
                pixels[x, y] = (
                    round(new_red * 255),
                    round(new_green * 255),
                    round(new_blue * 255),
                    alpha,
                )
                dome_total += 1

    # Zusammenhaengende Goldgebiete sammeln und nur die kleinen loeschen.
    gold_removed = 0
    seen = [[False] * width for _ in range(height)]
    for start_y in range(height):
        for start_x in range(width):
            if not gold_mask[start_y][start_x] or seen[start_y][start_x]:
                continue
            blob: list[tuple[int, int]] = []
            queue = deque([(start_x, start_y)])
            seen[start_y][start_x] = True
            while queue:
                x, y = queue.popleft()
                blob.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    if seen[ny][nx] or not gold_mask[ny][nx]:
                        continue
                    seen[ny][nx] = True
                    queue.append((nx, ny))
            if len(blob) > GOLD_BLOB_MAX_PIXELS:
                continue
            # Steht das Gebiet frei gegen den Himmel, oder liegt es in der Wand?
            #
            # Das ist der Unterschied, an dem der zweite Anlauf gescheitert ist.
            # Mit der weiteren Schwelle gilt auch ein warmes Steinlicht als
            # Gold - und wo es mitten im Mauerwerk sitzt, schlug das Loeschen
            # Loecher in die Wand. Ein Halbmond oder eine Minarettspitze grenzt
            # fast rundum an Durchsichtiges, ein Steinlicht fast nirgends.
            transparent_edge = opaque_edge = 0
            for x, y in blob:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < width and 0 <= ny < height):
                        transparent_edge += 1
                        continue
                    if gold_mask[ny][nx]:
                        continue
                    if pixels[nx, ny][3] == 0:
                        transparent_edge += 1
                    else:
                        opaque_edge += 1
            edge = transparent_edge + opaque_edge
            if edge == 0 or transparent_edge / edge < FREE_STANDING_MIN:
                continue
            # Um zwei Pixel weiten. Der Uebergang vom Gold zum Himmel ist
            # weichgezeichnet; ohne Weitung bleibt ein blasser Saum stehen, der
            # die Form des Halbmonds weiter erkennen laesst.
            widened = set(blob)
            for _step in range(2):
                edge = set()
                for x, y in widened:
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if not (0 <= nx < width and 0 <= ny < height):
                            continue
                        if (nx, ny) in widened:
                            continue
                        if pixels[nx, ny][3] == 0:
                            continue
                        edge.add((nx, ny))
                widened |= edge
            for x, y in widened:
                red, green, blue, _alpha = pixels[x, y]
                pixels[x, y] = (red, green, blue, 0)
            gold_removed += len(widened)

    return out, gold_removed, dome_total


def _frame_index(name: str) -> int | None:
    match = re.search(r"(\d+)$", name.strip())
    return int(match.group(1)) if match else None


def process_range(
    source: Path, destination: Path, low: int, high: int
) -> tuple[int, int, int]:
    index_path = source / "index.json"
    if not index_path.is_file():
        raise DeorientaliseError(f"Kein index.json in {source}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    frames = index.get("frames")
    if not isinstance(frames, list):
        raise DeorientaliseError(f"index.json in {source} fuehrt keine Frames")
    if low > high:
        raise DeorientaliseError(f"Leerer Bereich: {low} bis {high}")

    destination.mkdir(parents=True, exist_ok=True)
    kept: list[dict] = []
    gold_total = dome_total = 0
    for frame in frames:
        number = _frame_index(str(frame.get("name", "")))
        if number is None or not low <= number <= high:
            continue
        file_name = str(frame["file"])
        origin = source / file_name
        if not origin.is_file():
            raise DeorientaliseError(f"Fehlende Datei: {origin}")
        image, gold, dome = deorientalise_image(Image.open(origin))
        target = destination / file_name
        image.save(target)
        gold_total += gold
        dome_total += dome
        entry = dict(frame)
        entry["pixels_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        kept.append(entry)
        mask_name = file_name[:-4] + "_m.png"
        if (source / mask_name).is_file():
            shutil.copy2(source / mask_name, destination / mask_name)

    if not kept:
        raise DeorientaliseError(f"Kein Frame zwischen {low} und {high}")
    index["frames"] = kept
    index["game"] = "derived"
    (destination / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return len(kept), gold_total, dome_total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deorientalise",
        description="Halbmond und Goldspitze entfernen, Kuppelblau auf Bleigrau ziehen.",
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("low", type=int)
    parser.add_argument("high", type=int)
    args = parser.parse_args(argv)
    try:
        count, gold, dome = process_range(
            args.source, args.destination, args.low, args.high
        )
    except DeorientaliseError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    print(f"{count} Frames bearbeitet nach {args.destination}")
    print(f"  Gold entfernt : {gold} Pixel")
    print(f"  Kuppel gefaerbt: {dome} Pixel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
