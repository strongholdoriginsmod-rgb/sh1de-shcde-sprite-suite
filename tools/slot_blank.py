"""Eine Sprite-Gruppe unsichtbar machen, ohne ihren Platz aufzugeben.

Fuer Crusader-Gruppen, die inhaltlich nicht nach Europa gehoeren, fuer die es in
Stronghold 1 keinen Spender gibt und die niemand zeichnen will. Statt sie
stehenzulassen, wird jeder Frame durch ein vollstaendig transparentes Bild
**derselben Leinwand** ersetzt. Der Ladeplatz bleibt damit erhalten und
regelkonform besetzt - er zeichnet nur nichts mehr.

Der Anlass ist ``body_camel`` (GM 94, 944 Frames); siehe docs/KAMELE.md.

Warum die Leinwand erhalten bleiben muss: Der Lader zwingt jedem gelieferten
Bild den anteiligen Fusspunkt seines Crusader-Platzes auf
(``authored_sprite_foot_point``), und ``mod_builder`` lehnt jede abweichende
Groesse ab. Eine 1x1-Pixel-Attrappe waere kleiner, wuerde aber verweigert.

Der Weg ist der normale Rueckweg der Grafikwerkstatt::

    python tools/sprites.py export body_camel --game crusader --out work/art_gen
    python tools/slot_blank.py work/art_gen/body_camel --out work/art_gen/body_camel-leer
    python tools/sprites.py check work/art_gen/body_camel-leer
    python tools/sprites.py import work/art_gen/body_camel-leer --set camel-slot-blank --origin derived --check-only
    python tools/sprites.py import work/art_gen/body_camel-leer --set camel-slot-blank --origin derived
    python tools/sprites.py profile-add camel-slot-blank --origin derived --write

**Die Neubelegung bleibt offen.** Dieses Werkzeug nimmt dem Platz nur den
Inhalt, nicht die Zukunft: ``_PROJECT_AUTHORED_SPRITE_SETS`` erlaubt mehrere
Ablagen je Gruppe, solange ein Profil genau eine davon waehlt. Eine spaetere
Ablage - etwa der Stronghold-1-Baer auf demselben GM-Platz 94 - tritt neben
diese und wird im Profil getauscht, nicht darueber geschrieben.

Die ``index.json`` wird **unveraendert** uebernommen. Das ist Absicht: Sie
traegt die ``pixels_sha256`` des Exports, und ``sprites.py import`` verlangt
genau daran den Nachweis, dass sich ein Frame seit dem Export geaendert hat.

Deterministisch: gleiche Eingabe, gleiche Bytes. Ein transparentes RGBA-PNG
haengt nur an Groesse und Pillow-Version (in pyproject.toml gepinnt); es wird
kein Zeitstempel und keine Textbeigabe geschrieben.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

UEBERSICHT_PRAEFIX = "UEBERSICHT-"


def _pfad(wert: str) -> Path:
    pfad = Path(wert)
    return pfad if pfad.is_absolute() else PROJECT_ROOT / pfad


def _lies_index(quelle: Path) -> dict[str, Any]:
    index_pfad = quelle / "index.json"
    if not index_pfad.is_file():
        raise SystemExit(f"Kein Export: {index_pfad} fehlt")
    index = json.loads(index_pfad.read_text(encoding="utf-8"))
    if not isinstance(index, dict) or "frames" not in index:
        raise SystemExit(f"index.json ohne Frameliste: {index_pfad}")
    return index


def _leeres_png(breite: int, hoehe: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    puffer = BytesIO()
    Image.new("RGBA", (breite, hoehe), (0, 0, 0, 0)).save(puffer, format="PNG")
    return puffer.getvalue()


def leeren(quelle: Path, ziel: Path, *, ersetzen: bool) -> int:
    """Schreibt zu jedem Frame des Exports ein transparentes Bild gleicher Groesse."""

    index = _lies_index(quelle)
    frames = index["frames"]
    gruppe = index.get("group", "?")

    if ziel.exists():
        fremd = [p for p in ziel.iterdir() if p.name != "index.json"]
        if fremd and not ersetzen:
            raise SystemExit(
                f"{ziel} ist nicht leer. --replace ersetzt den Ordner ausdruecklich."
            )
        if ersetzen:
            shutil.rmtree(ziel)
    ziel.mkdir(parents=True, exist_ok=True)

    # Gleich grosse Frames teilen sich dieselben Bytes - einmal erzeugen genuegt.
    zwischenspeicher: dict[tuple[int, int], bytes] = {}
    geschrieben = 0
    masken = 0

    for frame in frames:
        breite = int(frame["width"])
        hoehe = int(frame["height"])
        schluessel = (breite, hoehe)
        if schluessel not in zwischenspeicher:
            zwischenspeicher[schluessel] = _leeres_png(breite, hoehe)
        rohdaten = zwischenspeicher[schluessel]

        (ziel / str(frame["file"])).write_bytes(rohdaten)
        geschrieben += 1

        maske = frame.get("mask_file")
        if maske:
            (ziel / str(maske)).write_bytes(rohdaten)
            masken += 1

    shutil.copyfile(quelle / "index.json", ziel / "index.json")

    bericht = {
        "werkzeug": "slot_blank",
        "gruppe": gruppe,
        "frames": geschrieben,
        "masken": masken,
        "leinwandgroessen": len(zwischenspeicher),
        "bytes_je_groesse": {
            f"{b}x{h}": len(daten) for (b, h), daten in sorted(zwischenspeicher.items())
        },
        "payload_sha256": hashlib.sha256(
            b"".join(zwischenspeicher[(int(f["width"]), int(f["height"]))] for f in frames)
        ).hexdigest(),
    }
    (ziel / "bericht.json").write_text(
        json.dumps(bericht, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"Gruppe {gruppe}: {geschrieben} Frames und {masken} Masken transparent")
    print(f"  verschiedene Leinwaende : {len(zwischenspeicher)}")
    print(f"  Ausgabe                 : {ziel}")
    print(f"  Nutzlast-Digest         : {bericht['payload_sha256']}")
    print()
    print("Pruefen:")
    print(f"  python tools/sprites.py check {ziel.relative_to(PROJECT_ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Jeden Frame eines Sprite-Exports durch ein transparentes "
        "Bild derselben Leinwand ersetzen.",
    )
    parser.add_argument(
        "export",
        help="Exportordner mit index.json, erzeugt von 'sprites.py export'",
    )
    parser.add_argument("--out", required=True, help="Zielordner fuer die leeren Frames")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="einen vorhandenen Zielordner ausdruecklich ersetzen",
    )
    args = parser.parse_args(argv)

    quelle = _pfad(args.export)
    ziel = _pfad(args.out)
    if quelle == ziel:
        raise SystemExit("Quelle und Ziel duerfen nicht derselbe Ordner sein")
    return leeren(quelle, ziel, ersetzen=args.replace)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
