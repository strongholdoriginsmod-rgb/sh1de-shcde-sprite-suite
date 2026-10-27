"""Erzeugte Grafiken in den UI-Exportbaum einpflegen.

Gegenstueck zu `ui_vorlage.py`: Das gibt die Crusader-Vorlage heraus, dieses
Werkzeug nimmt die fertige Neuzeichnung wieder an. Dazwischen liegt die
Bilderzeugung, die ihr Ergebnis in einer beliebigen Groesse und mit beliebigem
Rand liefert - `ui_atlas.py import` verlangt aber die Slotgroesse auf den Punkt
genau und lehnt jede Abweichung ab, statt zu skalieren.

Erwartet wird ein Ordner mit Dateien, die nach ihrem Atlas-Schluessel heissen:

    work/ui-erzeugt/roh/Panel_CelticKnot.png
    work/ui-erzeugt/roh/Face 05.png

Was damit geschieht, und warum:

**Beschnitten wird auf den sichtbaren Inhalt, nicht auf die Leinwand.** Ein
Bildmodell setzt sein Motiv gern mit Luft ringsum; wer die Leinwand skaliert,
verkleinert das Motiv im Slot. Die Schwelle liegt bei Alpha > 8, damit ein
weich auslaufender Rand nicht als Inhalt zaehlt.

**Skaliert wird seitenverhaeltnistreu und nur verkleinernd.** Ein Motiv
groesser zu rechnen, als es erzeugt wurde, bringt keine Schaerfe hinzu. Weicht
das Seitenverhaeltnis vom Slot ab, bleibt Rand statt Verzerrung - ein
gestauchtes Wappen faellt sofort auf, ein Millimeter Rand nicht.

**Der Alphakanal ist Pflicht.** Ein voellig undurchsichtiges Bild ist fast
immer eines mit weissem Hintergrund, und das saehe im Spiel als weisser Kasten
aus. Solche Dateien werden abgewiesen statt eingesetzt; `--ohne-alpha-erlauben`
hebt das auf, wenn der Slot wirklich flaechendeckend ist.

    python tools/ui_einpflegen.py --roh work/ui-erzeugt/roh \\
        --baum work/ui-europa-geprueft
    python tools/ui_einpflegen.py --roh work/ui-erzeugt/roh \\
        --baum work/ui-europa-geprueft --schreiben

Ohne `--schreiben` wird nichts angefasst; der erste Lauf ist immer ein Bericht.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ANKER = ("mitte", "unten-mitte", "links-oben")


class EinpflegeError(RuntimeError):
    """Die erzeugte Grafik laesst sich nicht einpflegen."""


def _unter_work(value: str, zweck: str) -> Path:
    path = Path(value)
    path = path if path.is_absolute() else (PROJECT_ROOT / path)
    path = path.resolve()
    work = (PROJECT_ROOT / "work").resolve()
    if path == work or not path.is_relative_to(work):
        raise EinpflegeError(f"{zweck} muss unter {work} liegen, nicht {path}")
    return path


def motivrahmen(bild: Image.Image, schwelle: int = 8) -> tuple[int, int, int, int] | None:
    """Der Rahmen des sichtbaren Inhalts, weiche Raender ausgenommen."""

    alpha = bild.getchannel("A")
    maske = alpha.point(lambda wert: 255 if wert > schwelle else 0)
    return maske.getbbox()


def einpassen(
    bild: Image.Image, ziel: tuple[int, int], anker: str, schwelle: int
) -> tuple[Image.Image, dict]:
    """Ein erzeugtes Bild auf die Slotgroesse bringen."""

    rahmen = motivrahmen(bild, schwelle)
    if rahmen is None:
        raise EinpflegeError("Das Bild ist vollstaendig durchsichtig")
    motiv = bild.crop(rahmen)
    breite, hoehe = ziel
    faktor = min(breite / motiv.width, hoehe / motiv.height)
    neu = (
        max(1, min(breite, round(motiv.width * faktor))),
        max(1, min(hoehe, round(motiv.height * faktor))),
    )
    if neu != motiv.size:
        motiv = motiv.resize(neu, Image.LANCZOS)

    leinwand = Image.new("RGBA", ziel, (0, 0, 0, 0))
    if anker == "links-oben":
        x, y = 0, 0
    elif anker == "unten-mitte":
        x, y = (breite - motiv.width) // 2, hoehe - motiv.height
    else:
        x, y = (breite - motiv.width) // 2, (hoehe - motiv.height) // 2
    leinwand.paste(motiv, (x, y))
    return leinwand, {
        "roh": list(bild.size),
        "motiv": list(rahmen),
        "skaliert": list(neu),
        "ablage": [x, y],
        "faktor": round(faktor, 4),
    }


def einpflegen(
    roh: Path,
    baum: Path,
    auftrag: list[dict],
    *,
    anker: str,
    schwelle: int,
    schreiben: bool,
    ohne_alpha_erlauben: bool,
) -> dict:
    if not (baum / "index.json").is_file():
        raise EinpflegeError(f"{baum} ist kein Exportbaum - index.json fehlt")

    nach_schluessel = {p["schluessel"]: p for p in auftrag}
    zaehler: Counter[str] = Counter()
    eingepflegt: list[dict] = []
    abgelehnt: list[dict] = []

    for pfad in sorted(roh.glob("*.png")):
        schluessel = pfad.stem
        posten = nach_schluessel.get(schluessel)
        if posten is None:
            zaehler["Schluessel nicht im Auftrag"] += 1
            abgelehnt.append({"schluessel": schluessel, "grund": "nicht im Auftrag"})
            continue
        slot = baum / posten["slot"]
        if not slot.is_file():
            zaehler["Slot fehlt im Baum"] += 1
            abgelehnt.append({"schluessel": schluessel, "grund": "Slot fehlt im Baum"})
            continue

        with Image.open(pfad) as offen:
            bild = offen.convert("RGBA")
            bild.load()

        durchsichtig = bild.getchannel("A").getextrema()[0]
        if durchsichtig == 255 and not ohne_alpha_erlauben:
            zaehler["kein Alphakanal"] += 1
            abgelehnt.append(
                {
                    "schluessel": schluessel,
                    "grund": "kein Alphakanal - vermutlich weisser Hintergrund",
                }
            )
            continue

        ziel = tuple(posten["zielgroesse"])
        try:
            fertig, spur = einpassen(bild, ziel, anker, schwelle)
        except EinpflegeError as fehler:
            zaehler[str(fehler)] += 1
            abgelehnt.append({"schluessel": schluessel, "grund": str(fehler)})
            continue

        # Bleibt nach dem Einpassen viel Rand, stimmt das Seitenverhaeltnis
        # nicht. Das ist kein Fehler, aber es gehoert gemeldet - im Spiel sitzt
        # das Symbol dann kleiner in seinem Feld als das Original.
        deckung = (spur["skaliert"][0] * spur["skaliert"][1]) / max(
            1, ziel[0] * ziel[1]
        )
        spur["deckung"] = round(deckung, 3)
        if deckung < 0.75:
            zaehler["Seitenverhaeltnis weicht ab"] += 1

        zaehler["eingepflegt"] += 1
        eingepflegt.append({"schluessel": schluessel, "slot": posten["slot"], **spur})
        if schreiben:
            fertig.save(slot)

    return {
        "zaehler": dict(zaehler),
        "eingepflegt": eingepflegt,
        "abgelehnt": abgelehnt,
        "anker": anker,
        "geschrieben": schreiben,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui_einpflegen",
        description="Erzeugte Grafiken auf Slotgroesse bringen und einsetzen.",
    )
    parser.add_argument("--roh", default="work/ui-erzeugt/roh")
    parser.add_argument("--baum", required=True)
    parser.add_argument("--auftrag", default="work/ui-vorlagen/auftrag.json")
    parser.add_argument("--anker", choices=ANKER, default="mitte")
    parser.add_argument(
        "--schwelle", type=int, default=8, help="ab welchem Alpha ein Pixel Inhalt ist"
    )
    parser.add_argument(
        "--ohne-alpha-erlauben",
        action="store_true",
        dest="ohne_alpha_erlauben",
        help="auch vollstaendig undurchsichtige Bilder annehmen",
    )
    parser.add_argument("--bericht", default=None)
    parser.add_argument(
        "--schreiben", action="store_true", help="wirklich in den Baum schreiben"
    )
    args = parser.parse_args(argv)

    try:
        roh = _unter_work(args.roh, "Rohordner")
        baum = _unter_work(args.baum, "Exportbaum")
        auftrag_pfad = Path(args.auftrag)
        if not auftrag_pfad.is_absolute():
            auftrag_pfad = PROJECT_ROOT / auftrag_pfad
        if not roh.is_dir():
            raise EinpflegeError(f"Kein Rohordner unter {roh}")
        auftrag = json.loads(auftrag_pfad.read_text(encoding="utf-8"))
        bericht = einpflegen(
            roh,
            baum,
            auftrag,
            anker=args.anker,
            schwelle=max(0, int(args.schwelle)),
            schreiben=bool(args.schreiben),
            ohne_alpha_erlauben=bool(args.ohne_alpha_erlauben),
        )
    except EinpflegeError as fehler:
        print(f"Abgelehnt: {fehler}", file=sys.stderr)
        return 1

    for grund, anzahl in sorted(bericht["zaehler"].items(), key=lambda p: -p[1]):
        print(f"  {grund:34} {anzahl:5}")
    for eintrag in bericht["eingepflegt"]:
        print(
            f"    {eintrag['schluessel'][:30]:32} {eintrag['roh'][0]}x{eintrag['roh'][1]}"
            f" -> {eintrag['skaliert'][0]}x{eintrag['skaliert'][1]}"
            f"  Deckung {eintrag['deckung']*100:.0f} %"
        )
    if args.bericht:
        ziel = _unter_work(args.bericht, "Bericht")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(
            json.dumps(bericht, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nBericht: {ziel}")
    if not bericht["geschrieben"]:
        print("\nNichts geschrieben. Mit --schreiben wirklich einsetzen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
