"""Eine UI-Ablage aus dem Produktionsprofil loesen — der fehlende Gegengriff.

`ui_atlas.py profile-add <neu> --write` traegt eine Ablage ein und entfernt dabei
**nur** Eintraege derselben Ablage. Eine Vorgaengerablage bleibt stehen, und weil
beide dasselbe Blatt beanspruchen, bricht der Eintrag fehl-geschlossen ab:

    Abgelehnt: Andere UI-Ablage beansprucht dieselben Blätter:
    ['Override/Assets/GUI/Sprites/UI-MasterAtlas.png', ...]

Das ist richtig so — zwei Ablagen auf demselben Blatt waeren ein stiller
Konflikt. Es fehlte nur der Gegengriff. Am 20.08.2026 musste die Vorgaengerablage
`ui-europa-geprueft` deshalb von Hand aus einer 160 kB grossen Profildatei
geschnitten werden; genau das soll niemand noch einmal tun muessen.

    python tools/ui_ablage_loesen.py ui-europa-geprueft            # nur zeigen
    python tools/ui_ablage_loesen.py ui-europa-geprueft --write
    python tools/ui_atlas.py profile-add sh1-umstellung --write

Was das Werkzeug NICHT tut: es raeumt keine Dateien weg. `assets/ui/derived/<Name>`
bleibt liegen, damit ein Rueckweg offen ist. Und es fasst ausschliesslich
`authored_ui_atlases` an — jeder andere Abschnitt des Profils geht unveraendert
durch, Schluesselreihenfolge eingeschlossen.

Warum eine eigene Datei und kein Schalter an `ui_atlas.py`: Der Git-Stand dieses
Repositoriums deckt sich **nicht** mit dem Arbeitsbaum (`HEAD:tools/ui_atlas.py`
kennt `profile-add` gar nicht). Ein misslungener Eingriff dort waere nicht
zurueckzurollen.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STANDARD_PROFIL = "profiles/europe-production.json"
ABSCHNITT = "authored_ui_atlases"


class LoesenError(RuntimeError):
    """Der Eingriff ins Profil ist nicht sicher."""


def _profilpfad(wert: str) -> Path:
    pfad = Path(wert)
    pfad = pfad if pfad.is_absolute() else (PROJECT_ROOT / pfad)
    pfad = pfad.resolve()
    profile = (PROJECT_ROOT / "profiles").resolve()
    if not pfad.is_relative_to(profile):
        raise LoesenError(f"Profil muss unter {profile} liegen, nicht {pfad}")
    if not pfad.is_file():
        raise LoesenError(f"Profil nicht gefunden: {pfad}")
    return pfad


def loesen(profil: Path, ablage: str, *, schreiben: bool, heute: str) -> dict:
    try:
        roh = profil.read_text(encoding="utf-8")
        daten = json.loads(roh)
    except (OSError, UnicodeError, ValueError) as fehler:
        raise LoesenError(f"Profil ist nicht lesbar: {profil} ({fehler})") from fehler
    if not isinstance(daten, dict):
        raise LoesenError("Profil ist kein JSON-Objekt")

    vorher = daten.get(ABSCHNITT, [])
    if not isinstance(vorher, list) or any(not isinstance(e, dict) for e in vorher):
        raise LoesenError(f"{ABSCHNITT} ist keine Objektliste")

    praefix = f"assets/ui/derived/{ablage}/"
    entfernt = [e for e in vorher if str(e.get("source", "")).startswith(praefix)]
    bleibt = [e for e in vorher if e not in entfernt]
    if not entfernt:
        raise LoesenError(
            f"Das Profil fuehrt keinen Eintrag der Ablage {ablage!r}. "
            f"Vorhanden: {sorted({str(e.get('source','')).split('/')[3] for e in vorher if str(e.get('source','')).count('/') > 3}) or 'keine'}"
        )

    if not schreiben:
        return {"entfernt": entfernt, "bleibt": bleibt, "geschrieben": False}

    sicherung = profil.with_name(f"{profil.name}.bak-{heute}-ablage-{ablage}")
    if sicherung.exists():
        raise LoesenError(f"Sicherung liegt schon: {sicherung.name} — erst pruefen")
    shutil.copy2(profil, sicherung)

    daten[ABSCHNITT] = bleibt
    neu = json.dumps(daten, indent=2, ensure_ascii=False) + "\n"
    zwischen = profil.with_name(profil.name + ".tmp")
    try:
        zwischen.write_text(neu, encoding="utf-8")
        os.replace(zwischen, profil)
    except OSError:
        zwischen.unlink(missing_ok=True)
        raise
    return {
        "entfernt": entfernt,
        "bleibt": bleibt,
        "geschrieben": True,
        "sicherung": str(sicherung),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui_ablage_loesen",
        description="Eine UI-Ablage aus authored_ui_atlases entfernen.",
    )
    parser.add_argument("ablage", help="Ablagename unter assets/ui/derived")
    parser.add_argument("--profile", default=STANDARD_PROFIL)
    parser.add_argument("--write", action="store_true",
                        help="wirklich schreiben; sonst nur zeigen")
    parser.add_argument("--datum", default=None,
                        help="Datum fuer den Sicherungsnamen (Vorgabe: heute)")
    args = parser.parse_args(argv)
    if args.datum:
        heute = args.datum
    else:
        from datetime import date

        heute = date.today().isoformat()
    try:
        ergebnis = loesen(_profilpfad(args.profile), args.ablage,
                          schreiben=args.write, heute=heute)
    except LoesenError as fehler:
        print(f"Abgelehnt: {fehler}", file=sys.stderr)
        return 1
    for eintrag in ergebnis["entfernt"]:
        print(f"  entfernt  {eintrag.get('source')}")
    print(f"  {ABSCHNITT}: {len(ergebnis['entfernt']) + len(ergebnis['bleibt'])} "
          f"-> {len(ergebnis['bleibt'])}")
    if ergebnis["geschrieben"]:
        print(f"  Sicherung {Path(ergebnis['sicherung']).name}")
    else:
        print("Ohne --write nur gezeigt; Profil blieb unveraendert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
