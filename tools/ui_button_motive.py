"""Motivkatalog der Knopfgrafiken, von Hand am Bild geprueft.

Die Zustandsgruppen sind nicht geraten: Fuer die A-Reihe traegt jede vierte
Nummer eine entsaettigte Fassung (gemessen ueber die mittlere Saettigung der
undurchsichtigen Pixel), fuer S048..S099 wechselt die Ringfarbe im Dreitakt
Silber - Gold hell - Gold dunkel. Zwei Ausnahmen sind belegt und stehen unten
ausdruecklich drin: A053..A055 und A056..A058 fuehren nur drei Zustaende.

Ausgabe: work/ui-europa-buttons/motive.json
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "work" / "ui" / "UI-MasterAtlas"
OUT = ROOT / "work" / "ui-europa-buttons"

# (Motivschluessel, erster Ausschnitt, Anzahl Zustaende, Rahmenart, Zeichen, Bezeichnung)
GRUPPEN = [
    ("wachturm",            "A001", 4, "wappenschild", "wachturm",        "Wachturm mit Zinnen"),
    ("bauhammer",           "A005", 4, "wappenschild", "hammer",          "Bauhammer"),
    ("apfel",               "A009", 4, "wappenschild", "apfel",           "Apfel"),
    ("wohnhaus",            "A013", 4, "wappenschild", "haus",            "Wohnhaus"),
    ("schild_leer",         "A017", 4, "wappenschild", "-",               "leerer Wappenschild"),
    ("sichel",              "A021", 4, "wappenschild", "sichel",          "Sichel"),
    ("torhaus",             "A025", 4, "wappenschild", "torhaus",         "Torhaus mit zwei Tuermen"),
    ("schwert_wappen",      "A029", 4, "wappenschild", "schwert",         "Schwert"),
    ("schluessel",          "A033", 4, "frei",         "schluessel",      "Schluessel"),
    ("zeichen_i",           "A037", 4, "frei",         "zeichen_i",       "Auskunftszeichen i"),
    ("zeichen_x",           "A041", 4, "frei",         "zeichen_x",       "Abbruchzeichen X"),
    ("rueckpfeil",          "A045", 4, "frei",         "rueckpfeil",      "Pfeil zurueck"),
    ("krummsaebel",         "A049", 4, "wappenschild", "ritterschwert",   "Krummsaebel -> Ritterschwert"),
    ("signalhorn",          "A053", 3, "wappenschild", "horn",            "Signalhorn"),
    ("mauerkrone",          "A056", 3, "wappenschild", "mauerkrone",      "Mauerkrone"),
    ("krummdolch",          "A059", 4, "wappenschild", "dolch",           "Krummdolch -> Dolch"),
    ("blide",               "A063", 4, "wappenschild", "blide",           "Blide"),

    ("marke_leer",          "S001", 1, "scheibe",      "-",               "leere Marke"),
    ("marke_achtung",       "S002", 1, "scheibe",      "ausrufezeichen",  "Achtung"),
    ("marke_holz",          "S003", 1, "scheibe",      "holzbalken",      "Holz"),
    ("marke_hopfen",        "S004", 1, "scheibe",      "hopfenkorb",      "Hopfen"),
    ("marke_stein",         "S005", 1, "scheibe",      "steinblock",      "Stein"),
    ("marke_eisen",         "S006", 1, "scheibe",      "eisenbarren",     "Eisen"),
    ("marke_pech",          "S007", 1, "scheibe",      "pechkrug",        "Pech"),
    ("marke_weizen",        "S008", 1, "scheibe",      "weizenaehre",     "Weizen"),
    ("marke_brot",          "S009", 1, "scheibe",      "brotlaib",        "Brot"),
    ("marke_kaese",         "S010", 1, "scheibe",      "kaeselaib",       "Kaese"),
    ("marke_fleisch",       "S011", 1, "scheibe",      "fleischkeule",    "Fleisch"),
    ("marke_obst",          "S012", 1, "scheibe",      "apfelkorb",       "Obst"),
    ("marke_bier",          "S013", 1, "scheibe",      "bierfass",        "Bier"),
    ("marke_gold",          "S014", 1, "scheibe",      "goldmuenzen",     "Gold"),
    ("marke_mehl",          "S015", 1, "scheibe",      "mehlsack",        "Mehl"),
    ("marke_bogen",         "S016", 1, "scheibe",      "bogen",           "Bogen"),
    ("marke_armbrust",      "S017", 1, "scheibe",      "armbrust",        "Armbrust"),
    ("marke_speer",         "S018", 1, "scheibe",      "speer",           "Speer"),
    ("marke_streitaxt",     "S019", 1, "scheibe",      "streitaxt",       "Streitaxt"),
    ("marke_morgenstern",   "S020", 1, "scheibe",      "morgenstern",     "Morgenstern"),
    ("marke_schwert",       "S021", 1, "scheibe",      "schwert",         "Schwert"),
    ("marke_lederzeug",     "S022", 1, "scheibe",      "gambeson",        "Lederzeug"),
    ("marke_harnisch",      "S023", 1, "scheibe",      "harnisch",        "Harnisch"),

    ("rolle_krieg",         "S024", 2, "schriftrolle", "gekreuzte_schwerter", "Krieg erklaeren"),
    ("handel_hin",          "S026", 3, "warenstapel",  "warenstapel",     "Handel hin"),
    ("handel_zurueck",      "S029", 2, "warenstapel",  "warenstapel",     "Handel zurueck"),
    ("rolle_friede",        "S031", 2, "schriftrolle", "zeichen_x",       "Krieg beenden"),
    ("wappen_kreuz",        "S033", 2, "wappen_gross", "-",               "Wappenschild mit Kreuz"),
    ("rundschild",          "S035", 2, "frei",         "ritterschild",    "Rundschild -> Normannenschild"),
    ("handschuh_nein",      "S037", 2, "ring_grund",   "daumen_runter",   "Ablehnen"),
    ("handschuh_ja",        "S039", 2, "ring_grund",   "daumen_hoch",     "Annehmen"),
    ("schwerter_gekreuzt",  "S041", 1, "frei",         "gekreuzte_schwerter", "gekreuzte Schwerter"),
    ("wappen_klein",        "S042", 1, "frei",         "-",               "kleines Wappenschild"),
    ("rahmen_abbruch",      "S043", 2, "steinrahmen",  "zeichen_x",       "Abbrechen"),
    ("koenigskrone",        "S045", 3, "frei",         "koenigskrone",    "Koenigskrone"),
    ("ring_gold",           "S048", 3, "ring",         "geldsack",        "Gold"),
    ("ring_harnisch",       "S051", 3, "ring",         "harnisch",        "Ruestung"),
    ("schaedel",            "S054", 1, "frei",         "schaedel",        "Schaedel"),
    ("ring_fussvolk",       "S055", 3, "ring",         "fusssoldat",      "Fussvolk"),
    ("ring_reiterei",       "S058", 3, "ring",         "berittener",      "Reiterei"),
    ("ring_nahrung",        "S061", 3, "ring",         "nahrung",         "Nahrung"),
    ("ring_holz",           "S064", 3, "ring",         "holzbalken",      "Holz"),
    ("ring_stein",          "S067", 3, "ring",         "steinblock",      "Stein"),
    ("ring_eisen",          "S070", 3, "ring",         "eisenbarren",     "Eisen"),
    ("ring_pech",           "S073", 3, "ring",         "pechkrug",        "Pech"),
    ("ring_waffen",         "S076", 3, "ring",         "waffenbuendel",   "Waffen"),
    ("ring_bauer",          "S079", 3, "ring",         "bauer",           "Bauern"),
    ("ring_beliebtheit",    "S082", 3, "ring",         "blume_galgen",    "Beliebtheit"),
    ("ring_feuer",          "S085", 3, "ring",         "feuer",           "Feuer"),
    ("ring_mauerbau",       "S088", 3, "ring",         "mauerbau",        "Mauerbau"),
    ("ring_fahne",          "S091", 3, "ring",         "fahnentraeger",   "Fahnentraeger"),
    ("ring_handel_links",   "S094", 3, "ring",         "warenstapel",     "Handel links"),
    ("ring_handel_rechts",  "S097", 3, "ring",         "warenstapel",     "Handel rechts"),
    ("rahmen_bestaetigen",  "S100", 2, "steinrahmen",  "haken",           "Bestaetigen"),
]

ZUSTAENDE = {
    ("wappenschild", 4): ["ruhend", "ueberfahren", "gedrueckt", "aus"],
    ("wappenschild", 3): ["ruhend", "ueberfahren", "gedrueckt"],
    ("frei", 4): ["ruhend", "ueberfahren", "gedrueckt", "aus"],
    ("frei", 3): ["ruhend", "ueberfahren", "gedrueckt"],
    ("frei", 2): ["ruhend", "ueberfahren"],
    ("frei", 1): ["ruhend"],
    ("ring", 3): ["ruhend", "ueberfahren", "gedrueckt"],
    ("scheibe", 1): ["ruhend"],
    ("schriftrolle", 2): ["ruhend", "ueberfahren"],
    ("warenstapel", 3): ["ruhend", "ueberfahren", "aus"],
    ("warenstapel", 2): ["ruhend", "ueberfahren"],
    ("wappen_gross", 2): ["ruhend", "ueberfahren"],
    ("ring_grund", 2): ["ruhend", "ueberfahren"],
    ("steinrahmen", 2): ["ruhend", "ueberfahren"],
}


def main() -> int:
    motive, alle = [], []
    for schluessel, erster, anzahl, rahmen, zeichen, name in GRUPPEN:
        reihe, nr = erster[0], int(erster[1:])
        keys = [f"{reihe}{nr + i:03d}" for i in range(anzahl)]
        dateien = [f"UI-Buttons {k}.png" for k in keys]
        for datei in dateien:
            if not (ATLAS / datei).exists():
                raise SystemExit(f"fehlt: {datei}")
        groesse = list(Image.open(ATLAS / dateien[0]).size)
        rollen = ZUSTAENDE.get((rahmen, anzahl))
        if rollen is None:
            raise SystemExit(f"kein Zustandsmodell fuer {rahmen}/{anzahl} ({schluessel})")
        motive.append({
            "motiv": schluessel,
            "bezeichnung": name,
            "rahmen": rahmen,
            "zeichen": zeichen,
            "groesse": groesse,
            "ausschnitte": keys,
            "zustaende": rollen,
            "dateien": dateien,
        })
        alle.extend(keys)

    doppelt = [k for k in set(alle) if alle.count(k) > 1]
    if doppelt:
        raise SystemExit(f"doppelt vergeben: {sorted(doppelt)}")
    bestand = sorted(
        p.stem.split(" ")[-1] for p in ATLAS.glob("UI-Buttons *.png")
        if len(p.stem.split(" ")[-1]) == 4 and p.stem.split(" ")[-1][0] in "SA"
        and p.stem.split(" ")[-1][1:].isdigit()
    )
    fehlend = sorted(set(bestand) - set(alle))
    if fehlend:
        raise SystemExit(f"nicht zugeordnet: {fehlend}")

    zeichen = sorted({m["zeichen"] for m in motive} - {"-"})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "motive.json").write_text(
        json.dumps({"motive": motive, "zeichen": zeichen}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Motive {len(motive)}  Ausschnitte {len(alle)}  eigene Zeichen {len(zeichen)}")
    print("Zeichen:", ", ".join(zeichen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
