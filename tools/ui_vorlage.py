"""Fuer Slots ohne Stronghold-1-Gegenstueck die Crusader-Vorlage herausgeben.

`ui_pair.py --familien` teilt Crusaders Oberflaeche in drei Toepfe. Zwei davon
sind erledigt: `identical` zeigt bereits dasselbe wie Stronghold 1, `candidates`
bekommt seinen europaeischen Ausschnitt von `ui_apply.py`. Der dritte, `orphans`,
hat kein Gegenstueck - dort muss gezeichnet werden. Dieses Werkzeug legt dafuer
die Mappe an: je Motiv die Crusader-Vorlage in bestmoeglicher Qualitaet, die
verlangte Zielgroesse und den Nachweis, wo das Bild im Spiel auftaucht.

## Was "bestmoegliche Qualitaet" hier heisst - gemessen, nicht behauptet

Die Oberflaeche liegt in vier Blaettern in `globalgamemanagers.assets`, BC7
komprimiert, 8192x8192 beziehungsweise 4096x4096. `ui_atlas.py export` dekodiert
die Mipstufe 0 und schneidet mit den Rechtecken aus dem XAML-Woerterbuch;
Gegenprobe an `btn_shield_bar_01`: 1440x346, genau die im Woerterbuch deklarierte
Groesse. Die ausgegebene PNG ist damit **verlustfrei gegenueber dem, was das
Spiel zeichnet**. Etwas Hoeheraufgeloestes gibt es in dieser Installation nicht -
die BC7-Kompression ist bereits im Auslieferungsstand verbacken und nicht
umkehrbar.

Je Motiv entstehen deshalb zwei Dateien mit verschiedenem Zweck:

- `<Schluessel>.png` - Originalgroesse, verlustfrei, mit Alphakanal. **Das ist
  der Vertrag.** Genau diese Pixelgroesse muss die Neuzeichnung wieder haben,
  sonst weist `ui_atlas.py import` sie ab (jede Groessenabweichung wird
  abgelehnt, nicht skaliert).
- `<Schluessel>@vorlage.png` - dieselben Pixel, mit Lanczos auf 1024 Punkt
  Langkante gebracht, Alphakanal erhalten. Nur als **Eingabe fuer die
  Bilderzeugung** gedacht: ein 91x170-Bild ist zu klein, als dass ein
  Bildmodell das Motiv sicher erkennt. Es traegt keine zusaetzliche Information.

## Die Reihenfolge ist nach Sichtbarkeit sortiert, nicht alphabetisch

Von 3890 Schluesseln in den vier Woerterbuechern werden **1385 in den 96
Oberflaechendateien des Extenders ueberhaupt referenziert**; 2505 kommen dort
nicht vor. Wer alphabetisch abarbeitet, zeichnet zuerst Dinge, die niemand
sieht. Sortiert wird darum nach Zahl der Verweise, dann nach Flaeche.

**Vorsicht bei der Umkehrung:** "kommt im XAML nicht vor" heisst *nicht*
"wird nicht gebraucht". Sprites lassen sich auch aus dem Spielcode heraus
adressieren, und das ist hier nicht nachgesehen. Die Zahl taugt als
Reihenfolge, nicht als Streichliste.

## Gebrauch

    python tools/ui_atlas.py export --out work/ui-cru-voll --replace
    python tools/ui_pair.py --crusader work/ui-cru-voll --sh1 work/ui-sh1 \
        --out work/ui-paare-fam --familien
    python tools/ui_vorlage.py --out work/ui-vorlagen --grenze 60

`--grenze` schneidet nach den ersten N Motiven ab, damit die Mappe in Portionen
abzuarbeiten ist statt in einem Schwung von 1430.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Der Extender liefert die gesamte Oberflaeche als Text aus; das Spiel selbst
# fuehrt keine XAML-Dateien, Noesis kompiliert sie hinein. Was hier steht, ist
# also die Fassung, die zur Laufzeit gilt.
GUI_VORGABE = (
    PROJECT_ROOT.parent
    / "BepInEx"
    / "plugins"
    / "000shcdese"
    / "Override"
    / "Assets"
    / "GUI"
)

VORLAGE_LANGKANTE = 1024


class VorlageError(RuntimeError):
    """Die Mappe laesst sich nicht anlegen."""


def gruppe(schluessel: str, blatt: str) -> str:
    """Der Ordner, in den ein Motiv gehoert.

    Crusader benennt seine Schluessel auf zwei Arten: die Atlasreihen tragen
    Gruppe und Nummer getrennt durch ein Leerzeichen (`UI-Buttons L019`), die
    Einzelstuecke nur einen Namen (`btn_Hide`, `Panel_Divider`). Wer nur am
    Leerzeichen trennt, legt fuer jedes Einzelstueck einen eigenen Ordner an -
    beim ersten Lauf waren das ueber zweihundert Ordner mit je einer Datei.
    Deshalb faellt die Benennung ohne Leerzeichen auf den ersten
    Unterstrich-Abschnitt zurueck und zuletzt auf das Blatt.
    """

    if " " in schluessel:
        return schluessel.split(" ")[0]
    if "_" in schluessel:
        kopf = schluessel.split("_")[0]
        if len(kopf) >= 3:
            return kopf
    return blatt


def _unter_work(value: str) -> Path:
    path = Path(value)
    path = path if path.is_absolute() else (PROJECT_ROOT / path)
    path = path.resolve()
    work = (PROJECT_ROOT / "work").resolve()
    if path == work or not path.is_relative_to(work):
        raise VorlageError(f"Ausgabe muss unter {work} liegen, nicht {path}")
    return path


def verwendung(gui: Path) -> dict[str, dict]:
    """Je Atlas-Schluessel: wie oft und in welchen Dateien er referenziert wird."""

    if not gui.is_dir():
        raise VorlageError(f"Kein GUI-Baum unter {gui}")
    woerterbuecher = sorted((gui / "Sprites").glob("*.xaml"))
    if not woerterbuecher:
        raise VorlageError(f"Keine Sprite-Woerterbuecher unter {gui / 'Sprites'}")

    schluessel: set[str] = set()
    for pfad in woerterbuecher:
        text = pfad.read_text(encoding="utf-8", errors="replace")
        schluessel |= set(re.findall(r'x:Key="([^"]+)"', text))

    namen = {pfad.stem for pfad in woerterbuecher}
    zahl: Counter[str] = Counter()
    dateien: dict[str, set[str]] = defaultdict(set)
    for pfad in sorted(gui.rglob("*.xaml")):
        if pfad.stem in namen:
            continue  # Ein Woerterbuch verweist nicht, es definiert.
        text = pfad.read_text(encoding="utf-8", errors="replace")
        for treffer in re.findall(r"\{StaticResource\s+([^}]+?)\s*\}", text):
            treffer = treffer.strip()
            if treffer in schluessel:
                zahl[treffer] += 1
                dateien[treffer].add(pfad.name)

    return {
        k: {"verweise": zahl.get(k, 0), "dateien": sorted(dateien.get(k, ()))}
        for k in schluessel
    }


def _vorlage(bild: Image.Image) -> Image.Image:
    """Dieselben Pixel, gross genug fuer ein Bildmodell. Nie verkleinern."""

    lang = max(bild.size)
    if lang >= VORLAGE_LANGKANTE:
        return bild.copy()
    faktor = VORLAGE_LANGKANTE / lang
    return bild.resize(
        (max(1, round(bild.width * faktor)), max(1, round(bild.height * faktor))),
        Image.LANCZOS,
    )


ZELLE = 192


def _kontaktbogen(
    zeilen: list[tuple[str, Path]], ziel: Path, titel: str, spalten: int = 8
) -> None:
    """Ein Bogen mit fester Zellengroesse.

    Die erste Fassung nahm als Zellenbreite das groesste Bild des Stapels. Ein
    einziger 1070x30-Trenner unter lauter 42x42-Symbolen blies damit den ganzen
    Bogen auf 8128 Punkt Breite auf, und die Symbole standen als Staubkoerner
    darin. Hier wird jedes Bild in eine feste Zelle eingepasst - nur zum Ansehen,
    die ausgegebenen Dateien bleiben unangetastet.
    """

    if not zeilen:
        return
    reihen = (len(zeilen) + spalten - 1) // spalten
    leinwand = Image.new(
        "RGBA", (spalten * ZELLE, reihen * (ZELLE + 16) + 24), (26, 26, 30, 255)
    )
    stift = ImageDraw.Draw(leinwand)
    stift.text((6, 6), titel, fill=(228, 228, 228, 255))
    for nummer, (beschriftung, pfad) in enumerate(zeilen):
        with Image.open(pfad) as offen:
            bild = offen.convert("RGBA")
        passung = min((ZELLE - 12) / bild.width, (ZELLE - 12) / bild.height, 1.0)
        if passung < 1.0:
            bild = bild.resize(
                (max(1, round(bild.width * passung)), max(1, round(bild.height * passung))),
                Image.LANCZOS,
            )
        spalte, reihe = nummer % spalten, nummer // spalten
        x = spalte * ZELLE + (ZELLE - bild.width) // 2
        y = 24 + reihe * (ZELLE + 16) + (ZELLE - bild.height) // 2
        leinwand.paste(bild, (x, y), bild)
        stift.text(
            (spalte * ZELLE + 4, 24 + reihe * (ZELLE + 16) + ZELLE + 2),
            beschriftung[:26],
            fill=(180, 180, 180, 255),
        )
    leinwand.save(ziel)


def mappe(
    zuordnung: dict,
    crusader: Path,
    gui: Path,
    ziel: Path,
    *,
    grenze: int | None,
    nur_verwendet: bool,
) -> dict:
    waisen = zuordnung.get("orphans")
    if not waisen:
        raise VorlageError("Die Zuordnung fuehrt keinen Topf 'orphans'")

    genutzt = verwendung(gui)
    posten: list[dict] = []
    for eintrag in waisen:
        slot = eintrag["slot"]
        quelle = crusader / slot
        if not quelle.is_file():
            continue
        schluessel = Path(slot.replace("\\", "/")).stem
        info = genutzt.get(schluessel, {"verweise": 0, "dateien": []})
        with Image.open(quelle) as offen:
            breite, hoehe = offen.size
        blatt = slot.replace("\\", "/").split("/")[0]
        posten.append(
            {
                "schluessel": schluessel,
                "gruppe": gruppe(schluessel, blatt),
                "slot": slot,
                "blatt": blatt,
                "zielgroesse": [breite, hoehe],
                "flaeche": breite * hoehe,
                "verweise": info["verweise"],
                "dateien": info["dateien"],
                "fassungen": eintrag.get("fassungen", []),
                "slots_gesamt": len(eintrag.get("slots", [slot])),
                "naechster_abstand": eintrag.get("abstand"),
            }
        )

    if nur_verwendet:
        posten = [p for p in posten if p["verweise"] > 0]
    posten.sort(key=lambda p: (-p["verweise"], -p["flaeche"], p["schluessel"]))
    gesamt = len(posten)
    if grenze is not None:
        posten = posten[:grenze]

    ziel.mkdir(parents=True, exist_ok=True)
    for posten_eintrag in posten:
        ordner_name = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in posten_eintrag["gruppe"]
        )
        ordner = ziel / ordner_name
        ordner.mkdir(parents=True, exist_ok=True)
        quelle = crusader / posten_eintrag["slot"]
        with Image.open(quelle) as offen:
            bild = offen.convert("RGBA")
        name = posten_eintrag["schluessel"]
        bild.save(ordner / f"{name}.png")
        _vorlage(bild).save(ordner / f"{name}@vorlage.png")
        posten_eintrag["datei"] = f"{ordner_name}/{name}.png"
        posten_eintrag["vorlage"] = f"{ordner_name}/{name}@vorlage.png"

    nach_gruppe: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for posten_eintrag in posten:
        nach_gruppe[posten_eintrag["gruppe"]].append(
            (posten_eintrag["schluessel"], ziel / posten_eintrag["datei"])
        )
    boegen = 0
    for name, zeilen in sorted(nach_gruppe.items()):
        sicher = "".join(c if c.isalnum() or c in "-_" else "_" for c in name).lower()
        for nummer in range(0, len(zeilen), 32):
            _kontaktbogen(
                zeilen[nummer : nummer + 32],
                ziel / f"kontakt-{sicher}-{nummer // 32 + 1:02d}.png",
                f"{name} - Crusader-Ist, zu ersetzen",
            )
            boegen += 1

    return {"posten": posten, "gesamt": gesamt, "ausgegeben": len(posten), "boegen": boegen}


def _auftrag_md(ergebnis: dict, ziel: Path) -> None:
    posten = ergebnis["posten"]
    zeilen = [
        "# Zeichenauftrag - Crusader-Slots ohne Stronghold-1-Gegenstueck",
        "",
        f"{ergebnis['ausgegeben']} von {ergebnis['gesamt']} Motiven, sortiert nach",
        "Sichtbarkeit (Zahl der XAML-Verweise), dann nach Flaeche.",
        "",
        "## Die Regel, an der eine Rueckgabe scheitert",
        "",
        "**Die Zielgroesse ist bindend.** `ui_atlas.py import` prueft jede Datei auf",
        "exakte Pixelgroesse und lehnt jede Abweichung ab, statt zu skalieren - der",
        "Platz im Blatt ist fest vergeben. Ein erzeugtes 1024x1024-Bild muss also vor",
        "der Rueckgabe auf die Zielgroesse gebracht werden, und zwar mit erhaltenem",
        "**Alphakanal**: die Slots sind freigestellt, kein Bild hat einen Hintergrund.",
        "",
        "Je Motiv liegen zwei Dateien bei:",
        "",
        "- `<Schluessel>.png` - Originalgroesse, verlustfrei. Das ist der Vertrag.",
        "- `<Schluessel>@vorlage.png` - auf 1024 Punkt hochgezogen, nur als Eingabe",
        "  fuer die Bilderzeugung. Traegt keine zusaetzliche Information.",
        "",
        "## Die Liste",
        "",
        "| # | Schluessel | Zielgroesse | Slots | Verweise | taucht auf in |",
        "|---:|---|---|---:|---:|---|",
    ]
    for nummer, p in enumerate(posten, 1):
        breite, hoehe = p["zielgroesse"]
        wo = ", ".join(d.replace(".xaml", "") for d in p["dateien"][:3])
        if len(p["dateien"]) > 3:
            wo += f" (+{len(p['dateien']) - 3})"
        zeilen.append(
            f"| {nummer} | `{p['schluessel']}` | {breite}x{hoehe} | "
            f"{p['slots_gesamt']} | {p['verweise']} | {wo or '-'} |"
        )
    zeilen += [
        "",
        "## Spalte „Slots\"",
        "",
        "Wo dort 8 steht, fuehrt Crusader acht Fassungen desselben Bildes - eine je",
        "Spielerfarbe. Gezeichnet wird trotzdem **eines**: die Grundfassung ist die",
        "rote, und die sieben anderen entstehen daraus, indem genau das Rot durch die",
        "Spielerfarbe ersetzt wird. Gemessen an `UI-Buildings O023`: unter der",
        "Aenderungsmaske liegt rgb(134,48,45), und `Green` macht daraus rgb(84,119,69),",
        "`Blue` rgb(46,86,115), `Purple` rgb(94,67,117). Die Maske ist klein - 228 bis",
        "1000 Pixel von rund 23000.",
        "",
    ]
    (ziel / "AUFTRAG.md").write_text("\n".join(zeilen), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui_vorlage",
        description="Crusader-Vorlagen fuer Slots ohne Stronghold-1-Gegenstueck.",
    )
    parser.add_argument("--zuordnung", default="work/ui-paare-fam/zuordnung.json")
    parser.add_argument("--crusader", default="work/ui-cru-voll")
    parser.add_argument("--gui", default=str(GUI_VORGABE))
    parser.add_argument("--out", default="work/ui-vorlagen")
    parser.add_argument(
        "--grenze", type=int, default=None, help="nur die ersten N Motive ausgeben"
    )
    parser.add_argument(
        "--nur-verwendet",
        action="store_true",
        help="nur Motive, die im XAML wirklich referenziert werden",
    )
    args = parser.parse_args(argv)

    try:
        zuordnung_pfad = Path(args.zuordnung)
        if not zuordnung_pfad.is_absolute():
            zuordnung_pfad = PROJECT_ROOT / zuordnung_pfad
        if not zuordnung_pfad.is_file():
            raise VorlageError(f"Keine Zuordnung unter {zuordnung_pfad}")
        crusader = Path(args.crusader)
        if not crusader.is_absolute():
            crusader = PROJECT_ROOT / crusader
        ziel = _unter_work(args.out)
        ergebnis = mappe(
            json.loads(zuordnung_pfad.read_text(encoding="utf-8")),
            crusader.resolve(),
            Path(args.gui).resolve(),
            ziel,
            grenze=args.grenze,
            nur_verwendet=args.nur_verwendet,
        )
    except VorlageError as fehler:
        print(f"Fehler: {fehler}", file=sys.stderr)
        return 1

    _auftrag_md(ergebnis, ziel)
    (ziel / "auftrag.json").write_text(
        json.dumps(ergebnis["posten"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    mit_verweis = sum(1 for p in ergebnis["posten"] if p["verweise"])
    print(f"Motive ohne Gegenstueck   {ergebnis['gesamt']:5}")
    print(f"  ausgegeben              {ergebnis['ausgegeben']:5}")
    print(f"  davon im XAML benutzt   {mit_verweis:5}")
    print(f"  Kontaktboegen           {ergebnis['boegen']:5}")
    print(f"\n{ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
