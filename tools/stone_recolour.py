"""Crusader-Sandstein auf die gemessene europaeische Steinfarbe ziehen.

Fuer Bauwerke, die Crusader selbst erfunden hat. Der Rundturm `tile_castle`
1570-1596 ist der Anlass: Stronghold 1 kennt ihn nicht - seine Gruppe endet bei
Index 1569, Crusader hat 27 Frames angehaengt. Es gibt also keinen europaeischen
Spender, weder gleichindiziert noch anderswo (der hoechste Stronghold-1-Bau
misst 643 px, dieser Turm 677 px, und alle hohen Stronghold-1-Bauten sind an
ihren eigenen Indizes bereits in Gebrauch). Bleibt: so lassen, ein fremdes
Bauwerk doppelt verwenden - oder das Material angleichen.

## Die Zielwerte sind gemessen, nicht gewaehlt

Gemessen an denselben Gruppen, die das Spiel bereits ausliefert, ueber alle
Pixel mit Alpha >= 200 und Helligkeit >= 0,12:

    Stein, Stronghold 1 (tile_castle 1147-1192)   Farbton 40,8  Saett. 0,24  R-B +29
    Stein, Crusader-Rundturm (1573-1578)          Farbton 33,8  Saett. 0,51  R-B +69
    Holz,  Stronghold-1-Palisade (1551-1567)      Farbton 38,0  Saett. 0,44  R-B +46
    Holz,  Crusader-Rundturm, oberes acht­el      Farbton 32,0  Saett. 0,40  R-B +49

Zwei Dinge stehen darin, die man sehen muss.

**Der Unterschied ist Saettigung, nicht Grau gegen Gold.** Beide Steinsorten
liegen im selben warmen Farbton; Crusader ist doppelt so gesaettigt. Wer nach
Grau umfaerbt, trifft daneben - das ist an dieser Stelle schon einmal falsch
behauptet worden.

**Das Holz des Turms ist bereits richtig.** Es misst praktisch dasselbe wie die
europaeische Palisade derselben Gruppe. Es darf deshalb nicht mitkorrigiert
werden, und genau das ist die Schwierigkeit: Ueber Farbton (33,8 gegen 32,0)
und Helligkeit (0,53 gegen 0,48) sind Stein und Holz nicht zu trennen. Im
Blauanteil sind sie es - B/R betraegt beim Sandstein 0,52, beim Holz 0,61.

Die Helligkeit bleibt unangetastet. Sie traegt die gesamte Steinstruktur; wer
sie anfasst, plaettet das Mauerwerk.

## Gebrauch

    python tools/sprites.py export tile_castle --game crusader --out work/turm
    python tools/stone_recolour.py work/turm/tile_castle work/turm-europa 1570 1596
    python tools/sprites.py check work/turm-europa
    python tools/sprites.py import work/turm-europa --set tile-castle-tower-europe --origin derived

`--origin derived` ist Pflicht: Das Ergebnis ist uebermaltes Firefly-Bildmaterial
und gehoert nicht ins Repository, sondern unter die .gitignore-Regel fuer
`assets/sprites/derived/`.
"""

from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from PIL import Image


class RecolourError(RuntimeError):
    """Etwas an den Eingaben stimmt nicht."""


# Gemessen, siehe Kopf der Datei.
SOURCE_HUE_DEGREES = 33.8
SOURCE_SATURATION = 0.51
TARGET_HUE_DEGREES = 40.8
TARGET_SATURATION = 0.24

# Der warme Bereich, in dem Sandstein ueberhaupt liegt. Schatten, Himmel und
# die dunklen Bruchstellen der Ruinenstufen fallen darunter heraus.
WARM_HUE_LOW = 0.02
WARM_HUE_HIGH = 0.14
DARK_CUTOFF = 0.12

# Blauanteil B/R: darueber ist es Holz und bleibt, darunter Stein und wird
# korrigiert. Dazwischen laeuft die Korrektur weich aus - eine harte Schwelle
# mitten durch zwei ueberlappende Verteilungen erzeugt sichtbare Kanten.
WOOD_BLUE_RATIO = 0.61
STONE_BLUE_RATIO = 0.52

HUE_SHIFT = (TARGET_HUE_DEGREES - SOURCE_HUE_DEGREES) / 360.0
SATURATION_SCALE = TARGET_SATURATION / SOURCE_SATURATION


def recolour_image(image: Image.Image) -> Image.Image:
    """Ein Bild umfaerben. Alpha und Helligkeit bleiben, wie sie sind."""

    out = image.convert("RGBA").copy()
    pixels = out.load()
    for y in range(out.height):
        for x in range(out.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0 or red == 0:
                continue
            hue, saturation, value = colorsys.rgb_to_hsv(
                red / 255, green / 255, blue / 255
            )
            if value < DARK_CUTOFF:
                continue
            if not WARM_HUE_LOW <= hue <= WARM_HUE_HIGH:
                continue
            weight = (WOOD_BLUE_RATIO - blue / red) / (
                WOOD_BLUE_RATIO - STONE_BLUE_RATIO
            )
            weight = max(0.0, min(1.0, weight))
            if weight <= 0.0:
                continue
            hue = (hue + HUE_SHIFT * weight) % 1.0
            saturation = min(
                1.0, saturation * (1.0 + weight * (SATURATION_SCALE - 1.0))
            )
            new_red, new_green, new_blue = colorsys.hsv_to_rgb(
                hue, saturation, value
            )
            pixels[x, y] = (
                round(new_red * 255),
                round(new_green * 255),
                round(new_blue * 255),
                alpha,
            )
    return out


def _frame_index(name: str) -> int | None:
    match = re.search(r"(\d+)$", name.strip())
    return int(match.group(1)) if match else None


def recolour_range(
    source: Path, destination: Path, low: int, high: int
) -> int:
    """Den Indexbereich umfaerben und als eigenen Exportordner ablegen.

    Der Index wird mitgeschrieben und auf die tatsaechlich enthaltenen Frames
    gekuerzt, damit `sprites.py check` und `import` den Ordner ohne weiteres
    Zutun annehmen. Die Pruefsummen werden neu gebildet - sie beschreiben ja
    jetzt andere Pixel.
    """

    index_path = source / "index.json"
    if not index_path.is_file():
        raise RecolourError(f"Kein index.json in {source}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    frames = index.get("frames")
    if not isinstance(frames, list):
        raise RecolourError(f"index.json in {source} fuehrt keine Frames")
    if low > high:
        raise RecolourError(f"Leerer Bereich: {low} bis {high}")

    destination.mkdir(parents=True, exist_ok=True)
    kept: list[dict] = []
    for frame in frames:
        index_number = _frame_index(str(frame.get("name", "")))
        if index_number is None or not low <= index_number <= high:
            continue
        file_name = str(frame["file"])
        origin = source / file_name
        if not origin.is_file():
            raise RecolourError(f"Fehlende Datei: {origin}")
        target = destination / file_name
        recolour_image(Image.open(origin)).save(target)
        entry = dict(frame)
        entry["pixels_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        kept.append(entry)
        # Masken unveraendert mitnehmen: Sie sagen, welche Pixel die
        # Spielerfarbe tragen, und das aendert eine Umfaerbung nicht.
        mask_name = file_name[:-4] + "_m.png"
        if (source / mask_name).is_file():
            shutil.copy2(source / mask_name, destination / mask_name)

    if not kept:
        raise RecolourError(f"Kein Frame zwischen {low} und {high}")
    index["frames"] = kept
    index["game"] = "derived"
    (destination / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return len(kept)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stone_recolour",
        description=(
            "Crusader-Sandstein auf die gemessene europaeische Steinfarbe "
            "ziehen. Holz bleibt Holz."
        ),
    )
    parser.add_argument("source", type=Path, help="Exportordner von sprites.py")
    parser.add_argument("destination", type=Path, help="Zielordner")
    parser.add_argument("low", type=int, help="erster Frameindex")
    parser.add_argument("high", type=int, help="letzter Frameindex")
    args = parser.parse_args(argv)
    try:
        count = recolour_range(
            args.source, args.destination, args.low, args.high
        )
    except RecolourError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    print(f"{count} Frames umgefaerbt nach {args.destination}")
    print(f"Pruefen:  python tools/sprites.py check {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
