"""Die Dachlinie geradeziehen — und dieselbe Zahl der Engine geben.

## Der Befund, aus dem dieses Werkzeug entsteht

`geometry_policy: native_source_reanchored_v1` laesst das Stronghold-1-Bild in
**seiner eigenen Groesse** stehen und rechnet den Pivot so um, dass der
**Ankerpunkt** exakt dort landet, wo Crusader ihn erwartet
(`docs/NATIVE_GEOMETRY_OPTION.md`). Das ist sauber gerechnet — der Ankerfehler
ist Fliesskommarauschen.

Die Formel garantiert aber **einen Punkt je Frame**. Die Unterkante stimmt. Ueber
die Oberkante sagt sie nichts, und genau daran haengen zwei Dinge:

1. **Die Fugen.** Ein Bauwerk wird aus 64 Punkt breiten Kachelspalten
   zusammengesetzt. Wachsen benachbarte Spalten **unterschiedlich** stark, bricht
   jede waagerechte Linie an jeder Fuge — Dachkante, Sturz, Zinnenband.
2. **Die Standhoehe.** Die Engine hebt Einheiten um Crusaders eigenen Wert
   (`GameMap.cs:1056`, Feld 5 des 21er-Satzes, geteilt durch 32 — siehe
   `docs/BERGFRIED_STANDHOEHE.md`). Waechst das Dach, bleibt die Hebung stehen,
   und der Soldat steht im Dach statt darauf.

Gemessen an `tile_castle` des ausgelieferten Baus: 418 aufragende Frames in 110
Blocken, **37 Blocke uneinheitlich** (Spanne ueber 16 Punkt), 178 Frames
betroffen. Der Bergfriedblock 1186–1192 waechst um +135…+167 — sechs Spalten im
Buendel bei +135…+143, eine einzelne bei **+167**. Das sind rund 25 Punkt
Versatz an genau einer Fuge, und das ist der gemeldete Bruch am Eingang.

## Die eine Zahl, zweimal benutzt

Je Block ergibt der **Median des Zuwachses** die Hoehe, auf die sich das Bauwerk
geeinigt hat. Daraus folgt beides:

* **Angleichen (B).** Ein Frame, dessen Zuwachs vom Blockmedian abweicht, wird
  ueber seinen **Pivot** verschoben — kein Pixel wird angefasst, nichts wird
  beschnitten, nichts neu abgetastet. Die Rechnung:

      a       = pivot_y * hoehe                     (Anker ueber der Unterkante)
      a_neu   = a + (zuwachs_frame - zuwachs_block)
      pivot_y = a_neu / hoehe

  Gegenprobe: die Oberkante liegt danach `(zielhoehe - zielanker) +
  zuwachs_block` ueber dem Anker — fuer jeden Frame des Blocks dieselbe Formel,
  also eine geschlossene Dachlinie.

* **Hoehentabelle (C).** Derselbe Blockmedian ist der Betrag, um den die Engine
  eine Einheit auf diesem Bauwerk zusaetzlich heben muss:
  `heightAboveGround += zuwachs_block / 32`. Der Massstab 32 Punkt = 1
  Welteinheit ist in `BERGFRIED_STANDHOEHE.md` zweifach unabhaengig belegt.

**Damit muss nichts geschaetzt und nichts am Bild gepfuscht werden.** Die Zahl
steht je Frame im Bau-Nachweis (`build-manifest.json`,
`native_source_geometry_policy.frame_proofs`), weil der Bau sie zum Umrechnen des
Pivots ohnehin gebraucht hat.

## Was das Werkzeug NICHT entscheidet

Ein „Block" ist hier ein Lauf aufeinanderfolgender aufragender Frame-Nummern mit
hoechstens zwei Nummern Luecke. Das ist eine **Heuristik fuer ein Bauwerk**, kein
gelesener Grundriss. Sie trifft den Bergfried (1186–1192) richtig; wo ein Block
zwei Bauwerke zusammenfasst oder eines zerreisst, ist der Median falsch. Bloecke
mit sehr grosser Spanne sind darum gemeldet und **nicht** stillschweigend
angeglichen: eine Spanne von 378 Punkten in einem Zweierblock ist kein
Formunterschied, sondern ein Hinweis, dass Nummer N in beiden Spielen nicht
dasselbe Bauteil ist.

    python tools/silhouette.py pruefen
    python tools/silhouette.py pruefen --gruppe tile_castle --alle
    python tools/silhouette.py angleichen --gruppe tile_castle --baum <atlasordner>
    python tools/silhouette.py hoehentabelle --out work/silhouette/hoehen.json
"""

from __future__ import annotations

from stronghold_europe_de.suite_paths import portable_path

import argparse
import json
from pathlib import Path
import re
import statistics
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Ein Block bricht ab, wenn mehr als so viele Nummern fehlen. Zwei, weil zwischen
# aufragenden Spalten regelmaessig ein bis zwei flache 64x32-Bodenkacheln liegen.
BLOCK_LUECKE = 2
# Unter dieser Spanne gilt ein Block als geschlossen; darueber wird angeglichen.
SPANNE_GRENZE = 16
# Darueber wird gemeldet statt angeglichen — der Median traegt dann nicht mehr.
SPANNE_VERDACHT = 60
# Flache Bodenkacheln tragen keine Silhouette.
FLACH_HOEHE = 32
# GameMap rechnet 32 Punkt = 1 Welteinheit (BERGFRIED_STANDHOEHE.md).
WELTMASSSTAB = 32.0

STANDARD_NACHWEIS = (
    Path(portable_path('target_game', ''))
    / "BepInEx" / "plugins" / "StrongholdEuropeDE" / "build-manifest.json"
)


class SilhouetteError(RuntimeError):
    """Die Silhouette laesst sich nicht sicher rechnen."""


# Je Gruppe: wie viele Frame-Nachweise keine Zielgeometrie fuehren und darum
# nicht bewertet werden koennen.
OHNE_ZIELGEOMETRIE: dict[str, int] = {}


def _nummer(name: str) -> int:
    treffer = re.findall(r"(\d+)", name)
    return int(treffer[-1]) if treffer else -1


def lies_nachweis(pfad: Path) -> dict[str, list[dict]]:
    """Je GM-Gruppe die Frame-Nachweise der nativen Geometriepolitik."""

    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as fehler:
        raise SilhouetteError(f"Bau-Nachweis nicht lesbar: {pfad} ({fehler})") from fehler
    gruppen: dict[str, list[dict]] = {}
    for satz in daten.get("outputs", []):
        weg = str(satz.get("relative_path", ""))
        if not weg.startswith("Override/Atlas/") or not weg.endswith("/atlas.json"):
            continue
        meta = satz.get("metadata") or {}
        politik = meta.get("native_source_geometry_policy") or {}
        beweise = politik.get("frame_proofs") or []
        # Zwei Nachweisformen liegen vor: die meisten Frames fuehren nur die
        # Quellgeometrie, nur ein Teil auch die Zielgeometrie. Ohne
        # `target_height` ist der Zuwachs nicht bestimmbar — solche Frames
        # bleiben aussen vor und werden gezaehlt, nicht verschwiegen.
        mit_ziel = [b for b in beweise if "target_height" in b]
        if mit_ziel:
            name = str(meta.get("gm_file_name") or weg.split("/")[2])
            gruppen[name] = mit_ziel
            OHNE_ZIELGEOMETRIE[name] = len(beweise) - len(mit_ziel)
    if not gruppen:
        raise SilhouetteError(
            "Kein Frame-Nachweis im Bau gefunden — laeuft die Gruppe unter einer "
            "anderen geometry_policy?"
        )
    return gruppen


def bloecke(beweise: list[dict]) -> list[list[dict]]:
    """Aufragende Frames in Laeufe zerlegen; flache Bodenkacheln trennen nicht."""

    hoch = sorted(
        (b for b in beweise if int(b["target_height"]) > FLACH_HOEHE),
        key=lambda b: _nummer(b["name"]),
    )
    if not hoch:
        return []
    gruppen: list[list[dict]] = []
    aktuell = [hoch[0]]
    for beweis in hoch[1:]:
        if _nummer(beweis["name"]) - _nummer(aktuell[-1]["name"]) <= BLOCK_LUECKE:
            aktuell.append(beweis)
        else:
            gruppen.append(aktuell)
            aktuell = [beweis]
    gruppen.append(aktuell)
    return gruppen


def zuwachs(beweis: dict) -> int:
    return int(beweis["source_height"]) - int(beweis["target_height"])


def bewerte(block: list[dict]) -> dict:
    werte = [zuwachs(b) for b in block]
    spanne = max(werte) - min(werte)
    median = int(statistics.median(werte))
    if spanne > SPANNE_VERDACHT:
        urteil = "verdaechtig"
    elif spanne > SPANNE_GRENZE:
        urteil = "anzugleichen"
    else:
        urteil = "geschlossen"
    return {
        "von": _nummer(block[0]["name"]),
        "bis": _nummer(block[-1]["name"]),
        "frames": len(block),
        "zuwachs_min": min(werte),
        "zuwachs_max": max(werte),
        "zuwachs_median": median,
        "spanne": spanne,
        "urteil": urteil,
        "namen": [b["name"] for b in block],
    }


def neuer_pivot(beweis: dict, ziel_zuwachs: int) -> tuple[float, int]:
    """Pivot, der den Frame auf den Blockzuwachs herunterzieht. Kein Pixel bewegt.

    Rueckgabe: (neuer normierter pivot_y, Verschiebung in Punkten).
    """

    hoehe = int(beweis["source_height"])
    if hoehe <= 0:
        raise SilhouetteError(f"{beweis['name']}: Quellhoehe ist nicht positiv")
    anker = float(beweis["output_pivot_y"]) * hoehe
    versatz = zuwachs(beweis) - ziel_zuwachs
    return (anker + versatz) / hoehe, versatz


# ------------------------------------------------------------------- Befehle


def cmd_pruefen(args: argparse.Namespace) -> int:
    gruppen = lies_nachweis(Path(args.nachweis))
    namen = [args.gruppe] if args.gruppe else sorted(gruppen)
    gesamt = {"geschlossen": 0, "anzugleichen": 0, "verdaechtig": 0}
    frames = dict(gesamt)
    for name in namen:
        if name not in gruppen:
            raise SilhouetteError(f"Gruppe nicht im Bau-Nachweis: {name}")
        bewertet = [bewerte(b) for b in bloecke(gruppen[name])]
        if not bewertet:
            continue
        zaehler = {"geschlossen": 0, "anzugleichen": 0, "verdaechtig": 0}
        for eintrag in bewertet:
            zaehler[eintrag["urteil"]] += 1
            gesamt[eintrag["urteil"]] += 1
            frames[eintrag["urteil"]] += eintrag["frames"]
        print(
            f"{name:22} {len(bewertet):4} Blocke  "
            f"geschlossen {zaehler['geschlossen']:3}  "
            f"anzugleichen {zaehler['anzugleichen']:3}  "
            f"verdaechtig {zaehler['verdaechtig']:3}"
        )
        for eintrag in bewertet:
            if eintrag["urteil"] == "geschlossen" and not args.alle:
                continue
            marke = {"anzugleichen": "  >", "verdaechtig": "  !", "geschlossen": "   "}
            print(
                f"{marke[eintrag['urteil']]} {eintrag['von']:5}-{eintrag['bis']:<5}"
                f" n={eintrag['frames']:<3} Zuwachs {eintrag['zuwachs_min']:+5}..."
                f"{eintrag['zuwachs_max']:+5}  Median {eintrag['zuwachs_median']:+5}"
                f"  Spanne {eintrag['spanne']:4}"
            )
    print()
    print(f"{'zusammen':22} geschlossen {gesamt['geschlossen']:4} Blocke / {frames['geschlossen']:4} Frames")
    print(f"{'':22} anzugleichen {gesamt['anzugleichen']:3} Blocke / {frames['anzugleichen']:4} Frames")
    print(f"{'':22} verdaechtig {gesamt['verdaechtig']:4} Blocke / {frames['verdaechtig']:4} Frames"
          f"   (Spanne ueber {SPANNE_VERDACHT} - nicht angleichen, nachsehen)")
    stumm = {k: v for k, v in OHNE_ZIELGEOMETRIE.items() if v}
    if stumm:
        print()
        print("Ohne Zielgeometrie im Nachweis und darum nicht bewertbar:")
        for name, zahl in sorted(stumm.items(), key=lambda kv: -kv[1])[:8]:
            print(f"   {name:22} {zahl:6} Frames")
    return 0


def cmd_hoehentabelle(args: argparse.Namespace) -> int:
    """Je Block den Betrag, um den die Engine Einheiten darauf heben muss."""

    gruppen = lies_nachweis(Path(args.nachweis))
    tabelle: dict[str, list[dict]] = {}
    for name in sorted(gruppen):
        eintraege = []
        for block in bloecke(gruppen[name]):
            bewertung = bewerte(block)
            if bewertung["zuwachs_median"] == 0:
                continue
            eintraege.append(
                {
                    "von": bewertung["von"],
                    "bis": bewertung["bis"],
                    "frames": bewertung["frames"],
                    "zuwachs_punkte": bewertung["zuwachs_median"],
                    "hebung_welteinheiten": round(
                        bewertung["zuwachs_median"] / WELTMASSSTAB, 6
                    ),
                    "spanne": bewertung["spanne"],
                    "urteil": bewertung["urteil"],
                }
            )
        if eintraege:
            tabelle[name] = eintraege
    ausgabe = {
        "schema_version": 1,
        "quelle": "build-manifest.json / native_source_geometry_policy.frame_proofs",
        "weltmassstab_punkte_je_einheit": WELTMASSSTAB,
        "hinweis": (
            "zuwachs_punkte ist source_height - target_height im Median des Blocks. "
            "Die Engine hebt Einheiten um Crusaders eigenen Wert; um diesen Betrag "
            "liegt das gezeichnete Dach darueber."
        ),
        "gruppen": tabelle,
    }
    ziel = Path(args.out)
    ziel = ziel if ziel.is_absolute() else (PROJECT_ROOT / ziel)
    work = (PROJECT_ROOT / "work").resolve()
    if not ziel.resolve().is_relative_to(work):
        raise SilhouetteError(f"Ausgabe muss unter {work} liegen")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(ausgabe, indent=1, ensure_ascii=False), encoding="utf-8")
    betroffen = sum(len(v) for v in tabelle.values())
    print(f"{betroffen} Blocke mit Zuwachs in {len(tabelle)} Gruppen -> {ziel}")
    for name, eintraege in tabelle.items():
        stark = [e for e in eintraege if abs(e["zuwachs_punkte"]) >= 32]
        if stark:
            print(f"  {name}: {len(stark)} Blocke ab einer ganzen Welteinheit")
            for e in stark[:6]:
                print(f"     {e['von']:5}-{e['bis']:<5} {e['zuwachs_punkte']:+5} Punkte"
                      f" = {e['hebung_welteinheiten']:+.4f} Einheiten  [{e['urteil']}]")
    return 0


def cmd_angleichen(args: argparse.Namespace) -> int:
    """Die Pivots eines gebauten atlas.json auf den Blockmedian ziehen."""

    gruppen = lies_nachweis(Path(args.nachweis))
    if args.gruppe not in gruppen:
        raise SilhouetteError(f"Gruppe nicht im Bau-Nachweis: {args.gruppe}")
    baum = Path(args.baum)
    baum = baum if baum.is_absolute() else (PROJECT_ROOT / baum)
    json_pfad = baum / "atlas.json"
    if not json_pfad.is_file():
        raise SilhouetteError(f"Kein atlas.json unter {baum}")

    beweis_je_name = {b["name"]: b for b in gruppen[args.gruppe]}
    daten = json.loads(json_pfad.read_text(encoding="utf-8"))
    frames = daten["frames"] if isinstance(daten, dict) and "frames" in daten else daten

    plan: list[tuple[str, float, float, int]] = []
    uebersprungen = 0
    for block in bloecke(gruppen[args.gruppe]):
        bewertung = bewerte(block)
        if bewertung["urteil"] == "geschlossen":
            continue
        if bewertung["urteil"] == "verdaechtig" and not args.auch_verdaechtige:
            uebersprungen += bewertung["frames"]
            continue
        for beweis in block:
            neu, versatz = neuer_pivot(beweis, bewertung["zuwachs_median"])
            if versatz == 0:
                continue
            plan.append((beweis["name"], float(beweis["output_pivot_y"]), neu, versatz))

    nach_name = {}
    for frame in frames:
        nach_name[frame.get("name")] = frame
    fehlend = [n for n, _, _, _ in plan if n not in nach_name]
    if fehlend:
        raise SilhouetteError(f"{len(fehlend)} geplante Frames fehlen im atlas.json, z. B. {fehlend[:3]}")

    print(f"Gruppe {args.gruppe}: {len(plan)} Frames zu verschieben"
          f"{f', {uebersprungen} in verdaechtigen Blocken uebersprungen' if uebersprungen else ''}")
    for name, alt, neu, versatz in plan[:20]:
        print(f"   {name:22} pivot_y {alt:.6f} -> {neu:.6f}   {versatz:+4} Punkte")
    if len(plan) > 20:
        print(f"   ... und {len(plan)-20} weitere")
    if not args.schreiben:
        print("\nProbelauf — nichts geschrieben. Mit --schreiben ausfuehren.")
        return 0

    for name, _alt, neu, _versatz in plan:
        nach_name[name]["pivot"]["y"] = neu
    # Die Sicherung darf NICHT neben das atlas.json — liegt der Baum im
    # Installationsplatz, waere sie dort eine ueberzaehlige Datei und wuerde
    # `install --replace` mit „Existing installed file set changed" verkeilen.
    # Genau das ist am 21.08. passiert. Sie geht deshalb nach work/.
    sicherungsordner = PROJECT_ROOT / "work" / "silhouette" / "sicherung"
    sicherungsordner.mkdir(parents=True, exist_ok=True)
    sicherung = sicherungsordner / f"{args.gruppe}-atlas.json.vor-silhouette"
    if not sicherung.exists():
        sicherung.write_text(json_pfad.read_text(encoding="utf-8"), encoding="utf-8")
    json_pfad.write_text(json.dumps(daten, indent=1), encoding="utf-8")
    print(f"\ngeschrieben. Sicherung: {sicherung.name}")
    print("Achtung: der Installationsnachweis kennt den alten Digest — ein regulaerer "
          "Bau ist der saubere Weg, dieses Werkzeug ist die Messung davor.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="silhouette",
        description="Dachlinie je Bauwerksblock pruefen, angleichen und die Hebung ableiten.",
    )
    unter = parser.add_subparsers(dest="befehl", required=True)
    for name in ("pruefen", "angleichen", "hoehentabelle"):
        p = unter.add_parser(name)
        p.add_argument("--nachweis", default=str(STANDARD_NACHWEIS))
        if name == "pruefen":
            p.add_argument("--gruppe")
            p.add_argument("--alle", action="store_true", help="auch geschlossene Blocke zeigen")
        if name == "angleichen":
            p.add_argument("--gruppe", required=True)
            p.add_argument("--baum", required=True, help="Ordner mit atlas.json")
            p.add_argument("--schreiben", action="store_true")
            p.add_argument("--auch-verdaechtige", action="store_true",
                           help="auch Blocke mit sehr grosser Spanne angleichen")
        if name == "hoehentabelle":
            p.add_argument("--out", default="work/silhouette/hoehen.json")
    args = parser.parse_args(argv)
    befehle = {
        "pruefen": cmd_pruefen,
        "angleichen": cmd_angleichen,
        "hoehentabelle": cmd_hoehentabelle,
    }
    try:
        return befehle[args.befehl](args)
    except SilhouetteError as fehler:
        print(f"Fehler: {fehler}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
