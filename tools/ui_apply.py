"""Entschiedene UI-Paare in einen Exportbaum einsetzen.

Zwischen `ui_pair.py` (schlaegt Paare vor) und `ui_atlas.py import` (baut ein
Blatt zurueck) klaffte eine Luecke: Es gab keinen Weg von einem entschiedenen
Paar zu einer Datei, die der Import annimmt. Dieses Werkzeug schliesst sie.

    python tools/ui_atlas.py export --out work/ui-europa --replace
    python tools/ui_apply.py --baum work/ui-europa --gruppe UI-Buildings
    python tools/ui_apply.py --baum work/ui-europa --gruppe UI-Buildings --schreiben
    python tools/ui_atlas.py import --from work/ui-europa --out dist/ui-override

Ohne `--schreiben` wird nichts angefasst; der erste Lauf ist immer ein Bericht.

## Die drei Fallen, die das Werkzeug gekostet haben

**1. `identical` heisst NICHT „austauschbar", sondern „bereits europaeisch".**
`ui_pair.py` legt Paare mit Abstand unter 2,0 in diesen Topf, weil Crusader dort
schon dasselbe Motiv zeigt wie Stronghold 1. Sie einzusetzen ist bestenfalls
wirkungslos. Voreinstellung ist deshalb `candidates`, und `identical` muss
ausdruecklich verlangt werden.

**2. Die Paarung ist NICHT groessengleich, obwohl ihr Kopf das behauptet.**
`ui_pair.py` bildet zwar `by_size`, benutzt es aber nie; gepaart wird ueber das
Seitenverhaeltnis mit 18 % Toleranz. Gemessen ueber alle 1308 Kandidaten:
**23** Motive sind exakt gleich gross, **787** kleiner, **258** groesser und
**240** in einer Kante groesser. Nur was in das Slot-Rechteck passt, laesst sich
ohne Skalieren einsetzen — 1083 von 1308. Der Rest wird uebersprungen und
gezaehlt, nicht skaliert: `ui_atlas.py import` lehnt jede Groessenabweichung ab,
und ein skaliertes Symbol saesse fast richtig und waere spaeter kaum zu finden.

**3. Der Import verlangt einen VOLLSTAENDIGEN Exportbaum.** Er prueft jeden
Indexeintrag auf Vorhandensein, Groesse und `baseline_pixels_sha256` gegen die
heutigen Blattpixel. Ein duenner Baum aus nur den geaenderten Dateien wird
abgelehnt. Dieses Werkzeug schreibt darum **in einen bestehenden Exportbaum
hinein** und legt keinen an. (Der Baum in `work/ui` taugt dafuer momentan nicht:
sein `index.json` deckt nur `UI-Colour2Atlas` ab, die drei anderen Ordner
stammen aus frueheren Laeufen. Ein frischer Export ohne `--atlas` erfasst alle
vier.)

## Warum Mehrfachverwendung verweigert wird

Ein Stronghold-1-Ausschnitt darf voreingestellt nur EINEN Slot bedienen. Der
erste Probelauf ueber `UI-Buildings` wollte 42 Ausschnitte auf 228 Slots legen,
einen davon auf 16. Nachgemessen, warum das falsch waere:

- **Stronghold 1 hat keine Farbblaetter.** Sein Auszug besteht aus
  `UI-MasterAtlas`, `UI-CandleAtlas` und `UI-ROL`; ein Gegenstueck zu Crusaders
  `UI-Colour1Atlas`/`UI-Colour2Atlas` gibt es nicht.
- **Crusaders Farbfassungen sind echt verschieden.** Zwischen den acht Fassungen
  von `UI-Buildings O023` unterscheiden sich 2,6 % bis 54,3 % der Pixel. Dieselbe
  europaeische Grafik in alle acht zu legen, ebnet die Spielerfarben ein.
- **Aufeinanderfolgende Nummern sind verschiedene Gebaeude, keine Zustaende.**
  `O023` gegen `O024` unterscheidet sich in 56,9 % der Pixel. Ein Ausschnitt fuer
  beide ist ein Fehlpaar der Zuordnung, keine zulaessige Zusammenfassung.

Die Farbfassungen brauchen deshalb eine Umfaerbung aus einer europaeischen
Grundfassung, nicht eine Kopie — der Weg von `tools/stone_recolour.py`. Solange
es die nicht gibt, verweigert dieses Werkzeug den Griff.
`--mehrfach-erlauben` hebt die Sperre auf und ist fuer Gruppen gedacht, die
keine Farbfassungen fuehren.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ANKER = ("unten-mitte", "mitte", "links-oben")


class ApplyError(RuntimeError):
    """Die Paare lassen sich nicht einsetzen."""


def _unter_work(value: str, zweck: str) -> Path:
    path = Path(value)
    path = path if path.is_absolute() else (PROJECT_ROOT / path)
    path = path.resolve()
    work = (PROJECT_ROOT / "work").resolve()
    if path == work or not path.is_relative_to(work):
        raise ApplyError(f"{zweck} muss unter {work} liegen, nicht {path}")
    return path


def _gruppe(slot: str) -> str:
    """Der Gruppenname eines Slots, so wie ihn der Dateiname traegt."""

    name = Path(slot.replace("\\", "/")).name
    return name.split(" ")[0] if " " in name else name


def _motiv(path: Path) -> tuple[Image.Image, tuple[int, int], tuple[int, int, int, int] | None]:
    """Bild, volle Groesse und Rahmen des sichtbaren Inhalts."""

    with Image.open(path) as opened:
        rgba = opened.convert("RGBA")
        rgba.load()
    return rgba, rgba.size, rgba.getbbox()


def _ablage(
    slot_groesse: tuple[int, int],
    slot_rahmen: tuple[int, int, int, int] | None,
    motiv_groesse: tuple[int, int],
    anker: str,
) -> tuple[int, int]:
    """Wohin das europaeische Motiv im Slot-Rechteck gehoert.

    `unten-mitte` ist die Voreinstellung und der einzige Anker, der fuer
    Bausymbole richtig ist: Sie stehen auf einer Grundlinie. Waagerecht wird auf
    die Mitte des BISHERIGEN Motivs zentriert, nicht auf die Mitte des
    Rechtecks - viele Slots tragen ihren Inhalt aussermittig, und die Mitte des
    Rechtecks wuerde das Symbol sichtbar versetzen.
    """

    voll_w, voll_h = slot_groesse
    motiv_w, motiv_h = motiv_groesse
    if slot_rahmen is None:
        # Ein vollstaendig durchsichtiger Slot hat kein bisheriges Motiv, an dem
        # sich etwas ausrichten liesse. Dann bleibt nur das Rechteck selbst.
        links, oben, rechts, unten = 0, 0, voll_w, voll_h
    else:
        links, oben, rechts, unten = slot_rahmen

    if anker == "links-oben":
        return links, oben
    if anker == "mitte":
        return (
            links + ((rechts - links) - motiv_w) // 2,
            oben + ((unten - oben) - motiv_h) // 2,
        )
    # unten-mitte
    return (
        links + ((rechts - links) - motiv_w) // 2,
        unten - motiv_h,
    )


def _auswahl(
    zuordnung: dict[str, list[dict]],
    toepfe: list[str],
    gruppen: list[str] | None,
    liste: Path | None,
) -> list[dict]:
    erlaubt: set[str] | None = None
    if liste is not None:
        zeilen = [
            zeile.strip()
            for zeile in liste.read_text(encoding="utf-8").splitlines()
            if zeile.strip() and not zeile.lstrip().startswith("#")
        ]
        erlaubt = {zeile.replace("/", "\\") for zeile in zeilen}
        if not erlaubt:
            raise ApplyError(f"Die Auswahlliste {liste} enthaelt keinen Eintrag")

    gewaehlt: list[dict] = []
    for topf in toepfe:
        if topf not in zuordnung:
            raise ApplyError(f"Die Zuordnung kennt keinen Topf {topf!r}")
        for eintrag in zuordnung[topf]:
            if "sh1" not in eintrag:
                continue  # Waisen tragen kein Gegenstueck.
            if gruppen and _gruppe(eintrag["slot"]) not in gruppen:
                continue
            if erlaubt is not None and eintrag["slot"].replace("/", "\\") not in erlaubt:
                continue
            gewaehlt.append({**eintrag, "topf": topf})
    return gewaehlt


def anwenden(
    zuordnung: dict[str, list[dict]],
    sh1_dir: Path,
    baum: Path,
    *,
    toepfe: list[str],
    gruppen: list[str] | None,
    liste: Path | None,
    anker: str,
    schreiben: bool,
    mehrfach_erlauben: bool = False,
    einpassen: int = 0,
    mindestdeckung: float = 0.0,
) -> dict:
    if not (baum / "index.json").is_file():
        raise ApplyError(
            f"{baum} ist kein Exportbaum - index.json fehlt. Erst anlegen mit:\n"
            f"  python tools/ui_atlas.py export --out {baum.relative_to(PROJECT_ROOT)} --replace"
        )

    gewaehlt = _auswahl(zuordnung, toepfe, gruppen, liste)
    if not gewaehlt:
        raise ApplyError("Die Auswahl ist leer - nichts einzusetzen")

    zaehler: Counter[str] = Counter()
    eingesetzt: list[dict] = []
    abgelehnt: list[dict] = []
    sh1_nutzung: dict[str, list[str]] = defaultdict(list)
    # Erst alles rechnen, dann erst schreiben. Die Sperre gegen
    # Mehrfachverwendung laesst sich sonst nicht faellen: ob ein Ausschnitt
    # mehrere Slots bedient, steht erst fest, wenn alle geprueft sind.
    vorbereitet: list[tuple[dict, Path, "Image.Image"]] = []

    for eintrag in gewaehlt:
        slot_pfad = baum / eintrag["slot"]
        sh1_pfad = sh1_dir / eintrag["sh1"]
        if not slot_pfad.is_file():
            zaehler["slot fehlt im Baum"] += 1
            abgelehnt.append({**eintrag, "grund": "slot fehlt im Baum"})
            continue
        if not sh1_pfad.is_file():
            zaehler["SH1-Ausschnitt fehlt"] += 1
            abgelehnt.append({**eintrag, "grund": "SH1-Ausschnitt fehlt"})
            continue

        slot_bild, slot_groesse, slot_rahmen = _motiv(slot_pfad)
        sh1_bild, _sh1_voll, sh1_rahmen = _motiv(sh1_pfad)
        if sh1_rahmen is None:
            zaehler["SH1-Ausschnitt ist leer"] += 1
            abgelehnt.append({**eintrag, "grund": "SH1-Ausschnitt ist leer"})
            continue
        motiv = sh1_bild.crop(sh1_rahmen)

        ueberstand = max(
            motiv.width - slot_groesse[0], motiv.height - slot_groesse[1]
        )
        if 0 < ueberstand <= einpassen:
            # Gemessen am familienweisen Lauf vom 17.08.2026: von 111 zu grossen
            # Motiven ueberragen 72 ihr Rechteck um hoechstens ZWEI Punkte, der
            # Median liegt bei 2. Das ist kein anderes Motiv, sondern der
            # Rundungsrest der Zusammenhangsanalyse, aus der die
            # Stronghold-1-Ausschnitte stammen. Zwei Punkte auf 105 sind knapp
            # zwei Prozent und im Spiel nicht zu sehen; die Alternative waere,
            # ein richtiges Paar wegen eines Rundungsfehlers zu verwerfen.
            # Groessere Abweichungen bleiben abgewiesen - dort steht wirklich
            # ein anders geschnittenes Bild.
            passung = min(
                slot_groesse[0] / motiv.width, slot_groesse[1] / motiv.height
            )
            motiv = motiv.resize(
                (
                    max(1, min(slot_groesse[0], round(motiv.width * passung))),
                    max(1, min(slot_groesse[1], round(motiv.height * passung))),
                ),
                Image.LANCZOS,
            )
            zaehler["eingepasst"] += 1
        elif motiv.width > slot_groesse[0] or motiv.height > slot_groesse[1]:
            zaehler["passt nicht ins Rechteck"] += 1
            abgelehnt.append(
                {
                    **eintrag,
                    "grund": "passt nicht ins Rechteck",
                    "slot_rechteck": list(slot_groesse),
                    "sh1_motiv": [motiv.width, motiv.height],
                    "ueberstand": ueberstand,
                }
            )
            continue

        # Ins Rechteck passen heisst nicht, das Rechteck fuellen. Gemessen am
        # Lauf vom 17.08.2026: von 396 Einsetzungen deckten 93 weniger als ein
        # Viertel der Flaeche ab, die das bisherige Motiv einnahm - der aergste
        # Fall ersetzte ein 61035 Punkt grosses Kartenbild durch einen Fleck von
        # 48 Punkt. Im Spiel ist ein solcher Slot nicht europaeisch, sondern
        # leer. Verglichen wird Motivflaeche gegen Motivflaeche, nicht gegen das
        # Rechteck: viele Slots tragen ihren Inhalt ohnehin nur in einer Ecke.
        if slot_rahmen is not None and mindestdeckung > 0.0:
            alt_flaeche = (slot_rahmen[2] - slot_rahmen[0]) * (
                slot_rahmen[3] - slot_rahmen[1]
            )
            deckung = (motiv.width * motiv.height) / max(1, alt_flaeche)
            if deckung < mindestdeckung:
                zaehler["deckt das bisherige Motiv nicht"] += 1
                abgelehnt.append(
                    {
                        **eintrag,
                        "grund": "deckt das bisherige Motiv nicht",
                        "deckung": round(deckung, 4),
                        "alt_motiv": [
                            slot_rahmen[2] - slot_rahmen[0],
                            slot_rahmen[3] - slot_rahmen[1],
                        ],
                        "sh1_motiv": [motiv.width, motiv.height],
                    }
                )
                continue

        x, y = _ablage(slot_groesse, slot_rahmen, motiv.size, anker)
        # Nach dem Zentrieren kann der Anker knapp aus dem Rechteck laufen, wenn
        # das bisherige Motiv am Rand klebte. Hineinschieben statt beschneiden -
        # beschnitten waere das europaeische Symbol still verstuemmelt.
        x = max(0, min(x, slot_groesse[0] - motiv.width))
        y = max(0, min(y, slot_groesse[1] - motiv.height))

        leinwand = Image.new("RGBA", slot_groesse, (0, 0, 0, 0))
        leinwand.paste(motiv, (x, y))
        if leinwand.tobytes() == slot_bild.tobytes():
            zaehler["unveraendert"] += 1
            continue

        sh1_nutzung[eintrag["sh1"]].append(eintrag["slot"])
        vorbereitet.append(
            (
                {
                    "slot": eintrag["slot"],
                    "sh1": eintrag["sh1"],
                    "topf": eintrag["topf"],
                    "abstand": eintrag.get("abstand"),
                    "rechteck": list(slot_groesse),
                    "motiv": [motiv.width, motiv.height],
                    "ablage": [x, y],
                },
                slot_pfad,
                leinwand,
            )
        )

    mehrfach = {k: v for k, v in sh1_nutzung.items() if len(v) > 1}
    for satz, slot_pfad, leinwand in vorbereitet:
        if not mehrfach_erlauben and len(sh1_nutzung[satz["sh1"]]) > 1:
            zaehler["Mehrfachverwendung verweigert"] += 1
            abgelehnt.append(
                {
                    **satz,
                    "grund": "Mehrfachverwendung verweigert",
                    "bedient_slots": len(sh1_nutzung[satz["sh1"]]),
                }
            )
            continue
        eingesetzt.append(satz)
        zaehler["eingesetzt"] += 1
        if schreiben:
            leinwand.save(slot_pfad)

    return {
        "gewaehlt": len(gewaehlt),
        "zaehler": dict(zaehler),
        "eingesetzt": eingesetzt,
        "abgelehnt": abgelehnt,
        "mehrfach_verwendete_sh1": mehrfach,
        "mehrfach_erlaubt": mehrfach_erlauben,
        "anker": anker,
        "geschrieben": schreiben,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui_apply",
        description="Entschiedene UI-Paare in einen Exportbaum einsetzen.",
    )
    parser.add_argument("--paare", default="work/ui-paare/zuordnung.json")
    parser.add_argument("--sh1", default="work/ui-sh1")
    parser.add_argument(
        "--baum",
        required=True,
        help="bestehender Exportbaum, IN den geschrieben wird (unter work/)",
    )
    parser.add_argument(
        "--topf",
        nargs="*",
        default=["candidates"],
        help="candidates (Voreinstellung) und/oder identical",
    )
    parser.add_argument(
        "--gruppe",
        nargs="*",
        default=None,
        help="nur diese Gruppen, z.B. UI-Buildings UI-Buttons",
    )
    parser.add_argument(
        "--liste",
        default=None,
        help="Datei mit je einem gebilligten Slot-Pfad pro Zeile",
    )
    parser.add_argument("--anker", choices=ANKER, default="unten-mitte")
    parser.add_argument(
        "--mehrfach-erlauben",
        action="store_true",
        dest="mehrfach_erlauben",
        help=(
            "einen Stronghold-1-Ausschnitt mehrere Slots bedienen lassen; "
            "ebnet bei Farbfassungen die Spielerfarben ein"
        ),
    )
    parser.add_argument(
        "--einpassen",
        type=int,
        default=0,
        metavar="PUNKTE",
        help=(
            "Motive, die ihr Rechteck um hoechstens PUNKTE ueberragen, "
            "verkleinernd einpassen statt abweisen (empfohlen: 2)"
        ),
    )
    parser.add_argument(
        "--mindestdeckung",
        type=float,
        default=0.5,
        metavar="ANTEIL",
        help=(
            "das neue Motiv muss mindestens diesen Anteil der Flaeche des "
            "bisherigen Motivs einnehmen; 0 schaltet die Pruefung ab "
            "(Voreinstellung 0.5)"
        ),
    )
    parser.add_argument(
        "--bericht", default=None, help="Bericht als JSON hierhin schreiben (unter work/)"
    )
    parser.add_argument(
        "--schreiben",
        action="store_true",
        help="wirklich in den Baum schreiben; ohne dies nur berichten",
    )
    args = parser.parse_args(argv)

    try:
        paare_pfad = Path(args.paare)
        paare_pfad = (
            paare_pfad if paare_pfad.is_absolute() else PROJECT_ROOT / paare_pfad
        )
        sh1_dir = Path(args.sh1)
        sh1_dir = sh1_dir if sh1_dir.is_absolute() else PROJECT_ROOT / sh1_dir
        baum = _unter_work(args.baum, "Der Exportbaum")
        liste = None
        if args.liste:
            liste = Path(args.liste)
            liste = liste if liste.is_absolute() else PROJECT_ROOT / liste
            if not liste.is_file():
                raise ApplyError(f"Auswahlliste nicht gefunden: {liste}")
        if not paare_pfad.is_file():
            raise ApplyError(f"Zuordnung nicht gefunden: {paare_pfad}")
        if not sh1_dir.is_dir():
            raise ApplyError(f"Stronghold-1-Ausschnitte nicht gefunden: {sh1_dir}")
        zuordnung = json.loads(paare_pfad.read_text(encoding="utf-8"))

        bericht = anwenden(
            zuordnung,
            sh1_dir.resolve(),
            baum,
            toepfe=list(args.topf),
            gruppen=list(args.gruppe) if args.gruppe else None,
            liste=liste,
            anker=args.anker,
            schreiben=bool(args.schreiben),
            mehrfach_erlauben=bool(args.mehrfach_erlauben),
            einpassen=max(0, int(args.einpassen)),
            mindestdeckung=max(0.0, float(args.mindestdeckung)),
        )
    except ApplyError as fehler:
        print(f"Abgelehnt: {fehler}", file=sys.stderr)
        return 1

    print(f"Ausgewaehlt                {bericht['gewaehlt']:5}")
    for grund, anzahl in sorted(bericht["zaehler"].items(), key=lambda p: -p[1]):
        print(f"  {grund:28} {anzahl:5}")
    mehrfach = bericht["mehrfach_verwendete_sh1"]
    if mehrfach:
        betroffen = sum(len(v) for v in mehrfach.values())
        wort = "bedienen" if bericht["mehrfach_erlaubt"] else "wollten"
        print(
            f"\n{len(mehrfach)} Stronghold-1-Ausschnitte {wort} "
            f"{betroffen} Slots bedienen."
        )
        if bericht["mehrfach_erlaubt"]:
            print(
                "  --mehrfach-erlauben ist gesetzt. Bei Gruppen mit Farbfassungen "
                "ebnet das\n  die Spielerfarben ein - Crusader haelt sie getrennt, "
                "Stronghold 1 fuehrt keine."
            )
        else:
            print(
                "  Verweigert. Stronghold 1 fuehrt keine Farbblaetter, Crusaders "
                "acht Fassungen\n  unterscheiden sich aber in 2,6 bis 54,3 % der "
                "Pixel. Die Farbfassungen\n  brauchen eine Umfaerbung, keine Kopie. "
                "Mit --mehrfach-erlauben trotzdem."
            )
        for sh1, slots in list(sorted(mehrfach.items(), key=lambda p: -len(p[1])))[:3]:
            print(f"    {sh1} -> {len(slots)} Slots, z.B. {Path(slots[0]).name}")

    if args.bericht:
        try:
            ziel = _unter_work(args.bericht, "Der Bericht")
        except ApplyError as fehler:
            print(f"Abgelehnt: {fehler}", file=sys.stderr)
            return 1
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(
            json.dumps(bericht, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nBericht: {ziel}")

    if not bericht["geschrieben"]:
        print("\nNichts geschrieben. Mit --schreiben wirklich einsetzen.")
    else:
        print(
            f"\nGeschrieben in {baum}. Weiter mit:\n"
            f"  python tools/ui_atlas.py import --from "
            f"{baum.relative_to(PROJECT_ROOT)} --out dist/ui-override --replace"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
