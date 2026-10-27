"""Gerahmte Symbole tauschen, ohne Rahmen und Grund anzufassen.

Ein Teil der Crusader-Oberflaeche besteht nicht aus freigestellten Sprites,
sondern aus **gerahmten Kacheln**: `Arabic Lord`, `Bedouin Lord` und ihre
`Over`-Fassungen sind quadratische Bilder mit einem farbigen Rand von drei bis
fuenf Punkten, dahinter ein flaechiger Grund und darauf erst das Motiv. Der Rand
traegt den Zustand - weiss heisst waehlbar, gelb heisst unter der Maus.

Wer so eine Kachel durch eine erzeugte Grafik ersetzt, darf deshalb nicht das
ganze Bild tauschen: Rand und Grund gehoeren zur Oberflaechenlogik, nur das
Motiv gehoert ausgewechselt. Dieses Werkzeug haelt beides auseinander.

## Was gemessen ist

**Der Rand ist schmal und einfarbig.** `Arabic Lord` 200x200 hat fuenf Punkte
Rand in rgb(255,255,255), die `Over`-Fassung dieselben fuenf in rgb(255,233,0);
`Bedouin Lord` 144x144 hat drei Punkte. Die Breite wird nicht geraten, sondern
von der Kante nach innen gezaehlt, solange die Farbe konstant bleibt.

**Der Grund ist teildurchsichtiges Schwarz, nicht deckend.** In den Innenecken
von `Arabic Lord` liegt rgba(0,0,0,215), Alpha zwischen 166 und 238. Wer statt
dessen deckendes Schwarz einsetzt, bekommt eine Kachel, die im Menue als
schwarzer Kasten steht. Der Grund wird darum aus den Innenecken des Originals
abgetastet und samt Alpha wiederhergestellt.

**Die Over-Fassung ist dasselbe Motiv.** Aus dem Crusader-Paar gemessen:
`y = 0,97*x + 5` je Kanal ueber 16085 Objektpunkte. Das ist kein anderer
Zustand des Motivs, sondern nur Rand und Grund. Ein erzeugtes Motiv bedient
deshalb beide Fassungen; es muss nicht zweimal erzeugt werden.

    python tools/ui_rahmen.py --objekt "work/ui-erzeugt/roh/Arabic Lord objekt.png" \\
        --ziel "Arabic Lord" "Arabic Lord Over" --baum work/ui-europa-geprueft
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RahmenError(RuntimeError):
    """Die Kachel laesst sich nicht tauschen."""


def randbreite(bild: Image.Image, toleranz: int = 40) -> int:
    """Wie viele Punkte der einfarbige Rand misst, von der Kante gezaehlt."""

    feld = np.asarray(bild.convert("RGB")).astype(int)
    zeile = feld[feld.shape[0] // 2]
    rand = zeile[0]
    breite = 0
    while breite < feld.shape[1] // 4 and np.abs(zeile[breite] - rand).max() < toleranz:
        breite += 1
    return breite


def grundfarbe(bild: Image.Image, rand: int, ecke: int = 10) -> tuple[int, int, int, int]:
    """Die Farbe des Grundes, aus den vier Innenecken abgetastet - mit Alpha."""

    feld = np.asarray(bild.convert("RGBA")).astype(int)
    h, w = feld.shape[:2]
    innen = feld[rand : h - rand, rand : w - rand]
    proben = np.concatenate(
        [
            innen[:ecke, :ecke].reshape(-1, 4),
            innen[:ecke, -ecke:].reshape(-1, 4),
            innen[-ecke:, :ecke].reshape(-1, 4),
            innen[-ecke:, -ecke:].reshape(-1, 4),
        ]
    )
    return tuple(int(v) for v in proben.mean(axis=0).round())


def tauschen(original: Image.Image, objekt: Image.Image, *, luft: float = 1.0) -> Image.Image:
    """Rand und Grund des Originals behalten, das Motiv ersetzen."""

    rand = randbreite(original)
    if rand < 1:
        raise RahmenError("kein einfarbiger Rand gefunden - keine gerahmte Kachel")
    breite, hoehe = original.size
    neu = original.copy()
    ImageDraw.Draw(neu).rectangle(
        [rand, rand, breite - rand - 1, hoehe - rand - 1],
        fill=grundfarbe(original, rand),
    )

    maske = np.asarray(objekt.convert("RGBA"))[:, :, 3] > 8
    if not maske.any():
        raise RahmenError("das erzeugte Objekt ist vollstaendig durchsichtig")
    ys, xs = np.where(maske)
    motiv = objekt.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))

    innen_w, innen_h = breite - 2 * rand, hoehe - 2 * rand
    faktor = min(innen_w / motiv.width, innen_h / motiv.height) * luft
    motiv = motiv.resize(
        (max(1, round(motiv.width * faktor)), max(1, round(motiv.height * faktor))),
        Image.LANCZOS,
    )
    neu.alpha_composite(
        motiv,
        (rand + (innen_w - motiv.width) // 2, rand + (innen_h - motiv.height) // 2),
    )
    return neu


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui_rahmen",
        description="Gerahmte Symbole tauschen, Rand und Grund behalten.",
    )
    parser.add_argument("--objekt", required=True, help="erzeugtes Motiv, freigestellt")
    parser.add_argument("--ziel", nargs="+", required=True, help="Schluessel im Auftrag")
    parser.add_argument("--baum", required=True)
    parser.add_argument("--auftrag", default="work/ui-vorlagen/auftrag.json")
    parser.add_argument(
        "--luft", type=float, default=1.0, help="Motiv kleiner einsetzen, z.B. 0.92"
    )
    parser.add_argument("--schreiben", action="store_true")
    args = parser.parse_args(argv)

    try:
        objekt_pfad = Path(args.objekt)
        if not objekt_pfad.is_absolute():
            objekt_pfad = PROJECT_ROOT / objekt_pfad
        baum = Path(args.baum)
        if not baum.is_absolute():
            baum = PROJECT_ROOT / baum
        auftrag_pfad = Path(args.auftrag)
        if not auftrag_pfad.is_absolute():
            auftrag_pfad = PROJECT_ROOT / auftrag_pfad
        if not (baum / "index.json").is_file():
            raise RahmenError(f"{baum} ist kein Exportbaum")
        auftrag = {
            p["schluessel"]: p
            for p in json.loads(auftrag_pfad.read_text(encoding="utf-8"))
        }
        with Image.open(objekt_pfad) as offen:
            objekt = offen.convert("RGBA")
            objekt.load()

        for schluessel in args.ziel:
            posten = auftrag.get(schluessel)
            if posten is None:
                raise RahmenError(f"{schluessel!r} steht nicht im Auftrag")
            slot = baum / posten["slot"]
            if not slot.is_file():
                raise RahmenError(f"Slot fehlt im Baum: {slot}")
            with Image.open(slot) as offen:
                original = offen.convert("RGBA")
                original.load()
            rand = randbreite(original)
            grund = grundfarbe(original, rand)
            neu = tauschen(original, objekt, luft=args.luft)
            print(
                f"  {schluessel:22} {original.width}x{original.height}"
                f"  Rand {rand} px  Grund rgba{grund}"
            )
            if args.schreiben:
                neu.save(slot)
            else:
                neu.save(slot.with_suffix(".vorschau.png"))
    except RahmenError as fehler:
        print(f"Abgelehnt: {fehler}", file=sys.stderr)
        return 1

    print(
        "\nGeschrieben." if args.schreiben else "\nNur Vorschau (*.vorschau.png). Mit --schreiben einsetzen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
