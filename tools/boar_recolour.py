"""Aus Crusaders Hyaene ein europaeisches Wildschwein faerben.

Weder Crusader (135.352 Sprites) noch Stronghold 1 (83.200) fuehren ein
Wildschwein - `body_boar` und `body_pig` gibt es in keinem der beiden Spiele.
Die Hyaene ist trotzdem kein Notbehelf, sondern der passende Koerper: hohe
Schultern, abfallende Kruppe, gesenkter Kopf, kurzer Schwanz, gedrungener Rumpf.
Das ist die Silhouette eines Keilers, und mit 17-97 x 20-92 px ist sie deutlich
kleiner als Loewe und Wolf.

Umgefaerbt wird auf **derselben Leinwand**: gleiche Groesse, gleicher Fusspunkt,
kein Geometrieproblem. Der Weg ist der normale Rueckweg der Grafikwerkstatt::

    python tools/sprites.py export body_hyena --game crusader --out work/wildtiere
    python tools/boar_recolour.py work/wildtiere/body_hyena --out work/art_gen/body_hyena-keiler
    python tools/sprites.py sheet work/art_gen/body_hyena-keiler --from 0 --to 47
    ... das Blatt ansehen ...
    python tools/sprites.py check work/art_gen/body_hyena-keiler
    python tools/sprites.py import work/art_gen/body_hyena-keiler --set boar-europe --origin derived
    python tools/sprites.py profile-add boar-europe --origin derived --write

## Die Zielwerte sind gemessen, nicht gewaehlt

Ueber die ersten 60 Frames je Gruppe, Alpha >= 200, ohne Schattenpixel
(``max(r,g,b) < SCHATTEN_GRENZE``), Median in HSV:

    body_hyena          Farbton 34.3 deg   Saettigung 0.379   Helligkeit 0.325
    body_ox             Farbton 24.0 deg   Saettigung 0.414   Helligkeit 0.353
    anim_dancing_bear   Farbton  0.0 deg   Saettigung 0.000   Helligkeit 0.204
    body_wolf           Farbton 37.5 deg   Saettigung 0.298   Helligkeit 0.412

Zwei Dinge stehen darin, die man sehen muss. Crusaders Tanzbaer ist
**vollstaendig entsaettigt** - sein dunkles Fell ist reines Grau, kein Braun.
Und der Ochse, das braune europaeische Nutztier desselben Spiels, liegt bei
24 Grad, also zehn Grad roter als die gelb-ockerfarbene Hyaene.

Ein Keiler liegt zwischen beiden: rotbraun wie der Ochse, aber matt und dunkel
wie der Baer. Daraus die drei Regeln:

* **Farbton** wird auf den gemessenen Ochsenwert gezogen, nicht verschoben.
  Eine feste Drehung um -10.3 Grad wuerde die dunklen Flecken der Hyaene, die
  einen anderen Farbton tragen, in eine andere Richtung ziehen als das Grundfell.
* **Saettigung** und **Helligkeit** gehen den halben Weg zum Baeren:
  0.379 -> 0.21 und 0.325 -> 0.235. Halb, weil ganz ein grauer Baer waere und
  gar nicht eine gelbe Hyaene bliebe.

## Was dieses Werkzeug nicht kann

Stossszaehne und Borstenkamm. Beides braeuchte gezeichnete Pixel je Frame und
Richtung; hier wird ausschliesslich Farbe geaendert. Die Silhouette bleibt die
der Hyaene.

## Was unangetastet bleibt

**Schatten.** Pixel unter ``SCHATTEN_GRENZE`` tragen keine Fellfarbe, sondern
den Bodenschatten des Sprites. Wer sie mitfaerbt, hebt den Schatten ins Braune.

**Alpha.** Es wird nur der Farbanteil ersetzt, der Alphakanal Pixel fuer Pixel
uebernommen. Skaliert wird nichts, deshalb ist hier auch keine
premultiplizierte Rechnung noetig.

**Die Teammasken.** Sie werden unveraendert mitkopiert. Die Gruppe laeuft mit
``plainShader: false`` und ``animalColours``; ohne Maske ersaetzt der Lader eine
transparente 4x4 und das Tier verlaere seine Spielerfarbe.

Deterministisch: feste Zielwerte, ganzzahlige Rundung, kein Zufall, kein
Zeitstempel. Ein zweiter Lauf liefert dieselben Bytes.
"""

from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Ab hier gilt ein Pixel als Bodenschatten und wird nicht angefasst. Gemessen:
# die Fellmessung ohne diese Grenze zieht den Median um mehrere Grad, weil die
# Schattenflaeche jedes Frames groesser ist als der Kopf des Tieres.
SCHATTEN_GRENZE = 40

# Ab hier gilt ein Pixel als sichtbar. Darunter traegt er ohnehin keine Farbe,
# die jemand sieht, und die Kanten bleiben unberuehrt.
ALPHA_GRENZE = 8

ZIEL_FARBTON_GRAD = 24.0      # gemessen an body_ox
ZIEL_SAETTIGUNG = 0.21        # halber Weg von 0.379 (Hyaene) zu 0.000 (Baer)
ZIEL_HELLIGKEIT = 0.235       # halber Weg von 0.325 (Hyaene) zu 0.204 (Baer)

# Gemessene Ausgangswerte der Hyaene, gegen die skaliert wird.
QUELL_SAETTIGUNG = 0.379
QUELL_HELLIGKEIT = 0.325


def _pfad(wert: str) -> Path:
    pfad = Path(wert)
    return pfad if pfad.is_absolute() else PROJECT_ROOT / pfad


def faerbe_pixel(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Ein Fellpixel nach Keilerart umrechnen."""

    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)

    # Farbton auf den Zielwert ziehen statt drehen: die dunklen Flecken der
    # Hyaene tragen einen anderen Farbton als ihr Grundfell, und eine feste
    # Drehung zoege sie auseinander.
    h_neu = ZIEL_FARBTON_GRAD / 360.0

    # Saettigung und Helligkeit verhaeltnisgleich, damit die Zeichnung im Fell
    # (Flecken, Muskelschatten, Glanzlichter) erhalten bleibt.
    s_neu = min(1.0, s * (ZIEL_SAETTIGUNG / QUELL_SAETTIGUNG))
    v_neu = min(1.0, v * (ZIEL_HELLIGKEIT / QUELL_HELLIGKEIT))

    r2, g2, b2 = colorsys.hsv_to_rgb(h_neu, s_neu, v_neu)
    return int(round(r2 * 255)), int(round(g2 * 255)), int(round(b2 * 255))


def faerbe_bild(pfad_ein: Path):
    from PIL import Image

    with Image.open(pfad_ein) as geoeffnet:
        geoeffnet.load()
        bild = geoeffnet.convert("RGBA")

    pixel = list(bild.getdata())
    neu = []
    gefaerbt = 0
    for r, g, b, a in pixel:
        if a < ALPHA_GRENZE or max(r, g, b) < SCHATTEN_GRENZE:
            neu.append((r, g, b, a))
            continue
        r2, g2, b2 = faerbe_pixel(r, g, b)
        neu.append((r2, g2, b2, a))
        gefaerbt += 1
    bild.putdata(neu)
    return bild, gefaerbt


def umfaerben(quelle: Path, ziel: Path, *, ersetzen: bool) -> int:
    from io import BytesIO

    index_pfad = quelle / "index.json"
    if not index_pfad.is_file():
        raise SystemExit(f"Kein Export: {index_pfad} fehlt")
    index = json.loads(index_pfad.read_text(encoding="utf-8"))
    frames = index["frames"]
    gruppe = index.get("group", "?")

    if ziel.exists():
        if not ersetzen:
            raise SystemExit(f"{ziel} existiert. --replace ersetzt den Ordner ausdruecklich.")
        shutil.rmtree(ziel)
    ziel.mkdir(parents=True, exist_ok=True)

    geschrieben = masken = 0
    gefaerbt_gesamt = 0
    digest = hashlib.sha256()

    for frame in frames:
        bild, gefaerbt = faerbe_bild(quelle / str(frame["file"]))
        puffer = BytesIO()
        bild.save(puffer, format="PNG")
        rohdaten = puffer.getvalue()
        (ziel / str(frame["file"])).write_bytes(rohdaten)
        digest.update(rohdaten)
        geschrieben += 1
        gefaerbt_gesamt += gefaerbt

        maske = frame.get("mask_file")
        if maske:
            # Unveraendert: die Teamfarbe des Tieres soll bleiben, wie sie ist.
            shutil.copyfile(quelle / str(maske), ziel / str(maske))
            masken += 1

    shutil.copyfile(index_pfad, ziel / "index.json")

    bericht = {
        "werkzeug": "boar_recolour",
        "gruppe": gruppe,
        "frames": geschrieben,
        "masken_unveraendert": masken,
        "gefaerbte_pixel": gefaerbt_gesamt,
        "ziel_farbton_grad": ZIEL_FARBTON_GRAD,
        "ziel_saettigung": ZIEL_SAETTIGUNG,
        "ziel_helligkeit": ZIEL_HELLIGKEIT,
        "schatten_grenze": SCHATTEN_GRENZE,
        "payload_sha256": digest.hexdigest(),
    }
    (ziel / "bericht.json").write_text(
        json.dumps(bericht, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"Gruppe {gruppe}: {geschrieben} Frames gefaerbt, {masken} Masken unveraendert")
    print(f"  gefaerbte Pixel : {gefaerbt_gesamt}")
    print(f"  Ziel            : Farbton {ZIEL_FARBTON_GRAD} deg, "
          f"Saettigung {ZIEL_SAETTIGUNG}, Helligkeit {ZIEL_HELLIGKEIT}")
    print(f"  Ausgabe         : {ziel}")
    print(f"  Nutzlast-Digest : {bericht['payload_sha256']}")
    print()
    print("Erst ansehen, dann pruefen:")
    print(f"  python tools/sprites.py sheet {ziel.relative_to(PROJECT_ROOT)} --from 0 --to 47")
    print(f"  python tools/sprites.py check {ziel.relative_to(PROJECT_ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Crusaders Hyaene zu einem europaeischen Wildschwein umfaerben.",
    )
    parser.add_argument("export", help="Exportordner body_hyena mit index.json")
    parser.add_argument("--out", required=True, help="Zielordner")
    parser.add_argument("--replace", action="store_true",
                        help="einen vorhandenen Zielordner ausdruecklich ersetzen")
    args = parser.parse_args(argv)

    quelle = _pfad(args.export)
    ziel = _pfad(args.out)
    if quelle == ziel:
        raise SystemExit("Quelle und Ziel duerfen nicht derselbe Ordner sein")
    return umfaerben(quelle, ziel, ersetzen=args.replace)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
