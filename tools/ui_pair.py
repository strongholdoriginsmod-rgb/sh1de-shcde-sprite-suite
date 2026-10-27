"""Crusader-UI-Slots und Stronghold-1-Ausschnitte einander zuordnen.

Crusader hat seine Oberflaeche nicht neu erfunden, sondern die von Stronghold 1
weitergefuehrt und stellenweise uebermalt. Das laesst sich ausnutzen, statt 1519
Ausschnitte von Hand zu sortieren:

1. **Deckungsgleich.** Ist ein Crusader-Slot Pixel fuer Pixel derselbe wie ein
   Stronghold-1-Ausschnitt, ist er bereits europaeisch. Dort ist nichts zu tun -
   und das ist der grosse Teil des Rahmenwerks.
2. **Groessengleich.** Ein Slot ohne deckungsgleiches Gegenstueck, zu dem es
   Stronghold-1-Ausschnitte derselben Groesse gibt, ist ein Austauschkandidat:
   gleiches Rechteck heisst, das Bild passt ohne Skalieren an dieselbe Stelle.
3. **Ohne Kandidat.** Alles uebrige. Das ist die ehrliche Restmenge, die
   wirklich gezeichnet werden muss.

Die Groessengleichheit ist ein Vorschlag, kein Beweis - zwei Symbole gleicher
Kantenlaenge muessen nicht dasselbe zeigen. Deshalb schreibt dieses Werkzeug
Kontaktboegen mit, auf denen die Paare nebeneinander stehen; entschieden wird am
Bild, nicht an der Zahl.

    python tools/ui_pair.py --crusader work/ui --sh1 work/ui-sh1 --out work/ui-paare
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Crusaders Spielerfarben, wie sie im Dateinamen hinter dem Schluessel stehen.
# Gemessen am vollstaendigen Export vom 17.08.2026: 245 Basisnamen fuehren je
# sieben benannte Fassungen plus eine unbenannte. Die unbenannte ist ROT - unter
# der Aenderungsmaske liegt in ihr rgb(127,7,7), rgb(134,48,45), rgb(135,90,70),
# und jede benannte Fassung ersetzt genau dieses Rot durch ihre Spielerfarbe.
SPIELERFARBEN = (
    "Light Blue",  # vor "Blue" pruefen, sonst schluckt "Blue" die Haelfte
    "Green",
    "Orange",
    "Yellow",
    "Purple",
    "Black",
    "Blue",
    "Red",
)


class PairError(RuntimeError):
    """Die Zuordnung laesst sich nicht bilden."""


def familie(slot: str) -> tuple[str, str | None]:
    """Ein Slotname zerlegt in (Basisname, Spielerfarbe).

    `UI-Buildings O023 Green` -> `(UI-Buildings O023, Green)`
    `UI-Buildings O023`       -> `(UI-Buildings O023, None)`

    Die Zerlegung ist der Kern der familienweisen Zuordnung: Crusader haelt
    dieselbe Grafik achtmal, einmal je Spielerfarbe, und diese acht liegen ueber
    drei Blaetter verstreut (Grund und `Blue` im MasterAtlas, `Green`,
    `Light Blue`, `Orange` im Colour1Atlas, `Black`, `Purple`, `Yellow` im
    Colour2Atlas). Wer je Slot zuordnet, verlangt achtmal dasselbe europaeische
    Bild und laeuft in die Mehrfachsperre von `ui_apply.py`; wer je Familie
    zuordnet, braucht ein Bild und leitet die sieben Fassungen daraus ab.
    """

    stem = Path(slot.replace("\\", "/")).stem
    for farbe in SPIELERFARBEN:
        if stem.endswith(" " + farbe):
            return stem[: -(len(farbe) + 1)], farbe
    return stem, None


def _project_output(value: str) -> Path:
    path = Path(value)
    path = path if path.is_absolute() else (PROJECT_ROOT / path)
    path = path.resolve()
    work = (PROJECT_ROOT / "work").resolve()
    if path == work or not path.is_relative_to(work):
        raise PairError(f"Ausgabe muss unter {work} liegen, nicht {path}")
    return path


def _pixels(path: Path) -> tuple[str, tuple[int, int]]:
    """Pruefsumme und Groesse des SICHTBAREN Inhalts.

    Beschnitten wird auf beiden Seiten, und das ist nicht kosmetisch: Die
    Stronghold-1-Ausschnitte entstehen aus einer Zusammenhangsanalyse und sind
    darum schon auf ihr Motiv beschnitten, Crusaders Slots dagegen sind die im
    XAML deklarierten Rechtecke samt durchsichtigem Rand. Ohne Beschnitt
    vergleicht man Rahmen mit Inhalt - der erste Lauf fand so null
    deckungsgleiche Paare, was nichts ueber die Spiele aussagte, sondern nur
    ueber den Vergleich.
    """

    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        box = rgba.getbbox()
        if box is not None:
            rgba = rgba.crop(box)
        return hashlib.sha256(rgba.tobytes()).hexdigest(), rgba.size


def _collect(directory: Path) -> dict[str, tuple[str, tuple[int, int], Path]]:
    """Jede PNG eines Ordnerbaums als (Pruefsumme, Groesse, Pfad)."""

    found: dict[str, tuple[str, tuple[int, int], Path]] = {}
    for path in sorted(directory.rglob("*.png")):
        if path.name.startswith(("UEBERSICHT", "kontakt", "vorschau", "vergleich")):
            continue
        # Die vollen Blaetter selbst sind keine Ausschnitte.
        if path.parent == directory and path.stem.startswith("UI-"):
            continue
        digest, size = _pixels(path)
        found[str(path.relative_to(directory))] = (digest, size, path)
    return found


def pair(crusader_dir: Path, sh1_dir: Path) -> dict[str, list]:
    crusader = _collect(crusader_dir)
    sh1 = _collect(sh1_dir)
    if not crusader:
        raise PairError(f"Keine Crusader-Ausschnitte in {crusader_dir}")
    if not sh1:
        raise PairError(f"Keine Stronghold-1-Ausschnitte in {sh1_dir}")

    by_digest: dict[str, list[str]] = defaultdict(list)
    by_size: dict[tuple[int, int], list[str]] = defaultdict(list)
    for key, (digest, size, _path) in sh1.items():
        by_digest[digest].append(key)
        by_size[size].append(key)

    # Exakte Gleichheit taugt hier nicht, und das ist gemessen: null Treffer
    # ueber 3886 Slots. Beide Atlanten sind blockkomprimiert und werden je
    # Spiel neu kodiert, dasselbe Motiv kommt also nie bitgleich heraus.
    # Verglichen wird deshalb auf einem 16x16-Miniaturbild.
    import numpy as np

    def thumbs(items):
        keys = list(items)
        data = np.zeros((len(keys), 16 * 16 * 4), dtype=np.float32)
        shapes = []
        for row, key in enumerate(keys):
            with Image.open(items[key][2]) as image:
                rgba = image.convert("RGBA")
                box = rgba.getbbox()
                if box is not None:
                    rgba = rgba.crop(box)
                shapes.append(rgba.size)
                small = rgba.resize((16, 16), Image.BILINEAR)
                data[row] = np.asarray(small, dtype=np.float32).reshape(-1) / 255.0
        return keys, data, shapes

    sh1_keys, sh1_data, sh1_shapes = thumbs(sh1)
    cru_keys, cru_data, cru_shapes = thumbs(crusader)
    sh1_ratio = np.array([w / max(1, h) for w, h in sh1_shapes], dtype=np.float32)

    # Quadratischer Abstand ueber ||a-b||^2 = |a|^2 + |b|^2 - 2ab, damit die
    # 5,9 Millionen Paare in einem Matrizenprodukt statt in Schleifen fallen.
    sh1_sq = (sh1_data**2).sum(axis=1)
    identical: list[dict] = []
    candidates: list[dict] = []
    orphans: list[dict] = []
    for row, key in enumerate(cru_keys):
        vector = cru_data[row]
        width, height = cru_shapes[row]
        ratio = width / max(1, height)
        # Nur Ausschnitte aehnlichen Zuschnitts: ein breites Band und ein
        # quadratisches Symbol koennen nie dasselbe zeigen.
        allowed = np.abs(sh1_ratio - ratio) <= 0.18 * max(ratio, 1.0)
        if not allowed.any():
            orphans.append({"slot": key, "size": [width, height]})
            continue
        distance = sh1_sq - 2.0 * (sh1_data @ vector)
        distance = np.where(allowed, distance, np.inf)
        best = int(np.argmin(distance))
        score = float(np.sqrt(max(0.0, distance[best] + float((vector**2).sum()))))
        entry = {
            "slot": key,
            "size": [width, height],
            "sh1": sh1_keys[best],
            "abstand": round(score, 3),
        }
        # Die Schwellen sind an den Kontaktboegen abgelesen, nicht gesetzt:
        # unter 2,0 zeigen beide Seiten dasselbe Motiv, ueber 4,5 nie.
        if score < 2.0:
            identical.append(entry)
        elif score < 4.5:
            candidates.append(entry)
        else:
            orphans.append({"slot": key, "size": [width, height], "abstand": round(score, 3)})
    return {"identical": identical, "candidates": candidates, "orphans": orphans}


def _miniaturen(items: dict[str, tuple[str, tuple[int, int], Path]]):
    """16x16-Miniatur je Ausschnitt, beschnitten auf das Motiv."""

    import numpy as np

    keys = list(items)
    data = np.zeros((len(keys), 16 * 16 * 4), dtype=np.float32)
    shapes: list[tuple[int, int]] = []
    for row, key in enumerate(keys):
        with Image.open(items[key][2]) as image:
            rgba = image.convert("RGBA")
            box = rgba.getbbox()
            if box is not None:
                rgba = rgba.crop(box)
            shapes.append(rgba.size)
            small = rgba.resize((16, 16), Image.BILINEAR)
            data[row] = np.asarray(small, dtype=np.float32).reshape(-1) / 255.0
    return keys, data, shapes


def pair_familien(
    crusader_dir: Path, sh1_dir: Path, *, schwelle: float = 4.5
) -> dict[str, list]:
    """Je Farbfamilie genau ein Stronghold-1-Ausschnitt, global eindeutig.

    Zwei Aenderungen gegenueber `pair()`, beide gemessen begruendet:

    **Zugeordnet wird je Familie, nicht je Slot.** Von 3886 Crusader-Slots sind
    1959 blosse Farbfassungen von 245 Grundbildern; es bleiben 2172 wirklich
    verschiedene Motive. Die alte Zuordnung verlangte fuer alle acht Fassungen
    denselben Ausschnitt und wurde dafuer von `ui_apply.py` abgewiesen - 929 der
    1308 Kandidaten fielen genau daran.

    **Vergeben wird global eindeutig statt je Slot am naechsten.** Das alte
    `argmin` je Slot durfte denselben Ausschnitt beliebig oft ausgeben; 122
    Ausschnitte wollten 929 Slots bedienen, einer davon 63. Hier faellt die
    Entscheidung als Zuordnungsproblem ueber die ganze Abstandsmatrix
    (`scipy.optimize.linear_sum_assignment`), und jeder Ausschnitt wird hoechstens
    einmal vergeben.
    """

    import numpy as np
    from scipy.optimize import linear_sum_assignment

    crusader = _collect(crusader_dir)
    sh1 = _collect(sh1_dir)
    if not crusader:
        raise PairError(f"Keine Crusader-Ausschnitte in {crusader_dir}")
    if not sh1:
        raise PairError(f"Keine Stronghold-1-Ausschnitte in {sh1_dir}")

    # Familien bilden. Vertreter ist die unbenannte Fassung (Rot); fehlt sie,
    # die alphabetisch erste - dann traegt die Familie eben eine Spielerfarbe,
    # was fuer die Motiverkennung unerheblich ist.
    mitglieder: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for slot in crusader:
        basis, farbe = familie(slot)
        mitglieder[basis].append((slot, farbe))
    vertreter: dict[str, str] = {}
    for basis, liste in mitglieder.items():
        ohne_farbe = [slot for slot, farbe in liste if farbe is None]
        vertreter[basis] = sorted(ohne_farbe or [slot for slot, _ in liste])[0]

    vertreter_items = {basis: crusader[slot] for basis, slot in vertreter.items()}
    fam_keys, fam_data, fam_shapes = _miniaturen(vertreter_items)
    sh1_keys, sh1_data, sh1_shapes = _miniaturen(sh1)

    fam_ratio = np.array([w / max(1, h) for w, h in fam_shapes], dtype=np.float32)
    sh1_ratio = np.array([w / max(1, h) for w, h in sh1_shapes], dtype=np.float32)

    # ||a-b||^2 = |a|^2 + |b|^2 - 2ab, damit 3,3 Millionen Paare in einem
    # Matrizenprodukt fallen statt in Schleifen.
    kosten = (
        (fam_data**2).sum(axis=1)[:, None]
        + (sh1_data**2).sum(axis=1)[None, :]
        - 2.0 * (fam_data @ sh1_data.T)
    )
    kosten = np.sqrt(np.maximum(0.0, kosten))

    # Ausschnitte voellig anderen Zuschnitts koennen nie dasselbe zeigen. Statt
    # sie auf `inf` zu setzen - womit das Zuordnungsproblem unloesbar werden
    # kann - bekommen sie einen Preis weit ueber der Annahmeschwelle.
    unpassend = np.abs(sh1_ratio[None, :] - fam_ratio[:, None]) > 0.18 * np.maximum(
        fam_ratio[:, None], 1.0
    )
    strafe = float(kosten.max()) + 1000.0
    kosten_gestraft = np.where(unpassend, strafe, kosten)

    zeilen, spalten = linear_sum_assignment(kosten_gestraft)

    identical: list[dict] = []
    candidates: list[dict] = []
    orphans: list[dict] = []
    zugeordnet: set[int] = set()
    for zeile, spalte in zip(zeilen, spalten):
        if unpassend[zeile, spalte]:
            continue
        abstand = float(kosten[zeile, spalte])
        if abstand >= schwelle:
            continue
        zugeordnet.add(int(zeile))
        basis = fam_keys[zeile]
        eintrag = {
            "slot": vertreter[basis],
            "basis": basis,
            "size": list(fam_shapes[zeile]),
            "sh1": sh1_keys[spalte],
            "abstand": round(abstand, 3),
            "fassungen": sorted(
                farbe for _slot, farbe in mitglieder[basis] if farbe is not None
            ),
        }
        # Die Schwellen sind dieselben wie in `pair()` und an den Kontaktboegen
        # abgelesen: unter 2,0 zeigt Crusader bereits dasselbe Motiv.
        (identical if abstand < 2.0 else candidates).append(eintrag)

    for zeile, basis in enumerate(fam_keys):
        if zeile in zugeordnet:
            continue
        bester = int(np.argmin(kosten_gestraft[zeile]))
        orphans.append(
            {
                "slot": vertreter[basis],
                "basis": basis,
                "size": list(fam_shapes[zeile]),
                "abstand": round(float(kosten[zeile, bester]), 3),
                "fassungen": sorted(
                    farbe for _slot, farbe in mitglieder[basis] if farbe is not None
                ),
                "slots": sorted(slot for slot, _ in mitglieder[basis]),
            }
        )

    fam_index = {name: zeile for zeile, name in enumerate(fam_keys)}
    sh1_index = {name: spalte for spalte, name in enumerate(sh1_keys)}
    geordnet = _folgen_ordnen(
        identical + candidates, fam_index, sh1_index, fam_data, sh1_data
    )
    if geordnet:
        print(f"  Bildfolgen wieder in Reihenfolge gebracht: {geordnet} Paare")

    return {"identical": identical, "candidates": candidates, "orphans": orphans}


def _nummer(schluessel: str) -> tuple[str, int]:
    """Ein Schluessel zerlegt in Stamm und Laufnummer.

    `UI-Scribe B012` -> `(UI-Scribe B, 12)`;  `UI-ROL 0008` -> `(UI-ROL , 8)`.
    Ohne Nummer am Ende bleibt die Nummer -1.
    """

    treffer = re.search(r"(\d+)\s*$", schluessel)
    if not treffer:
        return schluessel, -1
    return schluessel[: treffer.start()], int(treffer.group(1))


def _folgen_ordnen(
    paare: list[dict],
    fam_index: dict[str, int],
    sh1_index: dict[str, int],
    fam_data,
    sh1_data,
    *,
    schwelle: float = 2.0,
) -> int:
    """Bildfolgen wieder in ihre Reihenfolge bringen.

    Die global eindeutige Vergabe loest die Mehrfachverwendung, handelt sich
    dabei aber einen neuen Fehler ein, und der ist am Bild aufgefallen: Die 74
    Bilder des Schreibers (`UI-Scribe B001`...) sind Einzelbilder EINER
    Bewegung. Sie unterscheiden sich kaum, also ist der rechnerische Abstand
    zwischen fast allen Kombinationen fast gleich, und die Zuordnung verteilt
    sie in beliebiger Folge: `B003` bekam `UI-ROL 0013`, `B006` dagegen `0039`,
    `B007` wieder `0017`. Eingesetzt ergaebe das einen zuckenden Schreiber.

    Erkannt wird eine Folge nicht am Namen, sondern **gemessen**: nur wenn die
    aufeinanderfolgenden Crusader-Bilder eines Stamms untereinander im Mittel
    weniger als `schwelle` auseinanderliegen - dieselbe Schranke, unter der
    `pair()` zwei Bilder „dasselbe Motiv" nennt -, ist es eine Bewegung. Bei
    `UI-Buildings` ist dieser Abstand gross (`O023` gegen `O024`: 56,9 % andere
    Pixel), dort greift die Umsortierung deshalb nicht - und das ist richtig,
    denn Gebaeude Nummer 5 in Crusader ist nicht Gebaeude Nummer 5 in
    Stronghold 1.

    Umsortiert wird innerhalb der bereits vergebenen Menge: beide Seiten nach
    Laufnummer sortiert und der Reihe nach neu verbunden. Die Eindeutigkeit
    bleibt damit erhalten, es ist nur eine Permutation.
    """

    import numpy as np

    eimer: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for eintrag in paare:
        cru_stamm, cru_nr = _nummer(Path(eintrag["basis"]).stem)
        sh1_stamm, sh1_nr = _nummer(Path(eintrag["sh1"].replace("\\", "/")).stem)
        if cru_nr < 0 or sh1_nr < 0:
            continue
        eimer[(cru_stamm, sh1_stamm)].append(eintrag)

    geordnet = 0
    for (cru_stamm, _sh1_stamm), gruppe in eimer.items():
        if len(gruppe) < 4:
            continue
        gruppe.sort(key=lambda e: _nummer(Path(e["basis"]).stem)[1])
        reihen = [fam_index[e["basis"]] for e in gruppe]
        folge = fam_data[reihen]
        # Mittlerer Abstand zwischen aufeinanderfolgenden Crusader-Bildern.
        schritte = np.sqrt(((folge[1:] - folge[:-1]) ** 2).sum(axis=1))
        if float(schritte.mean()) >= schwelle:
            continue  # Keine Bewegung, sondern verschiedene Dinge.
        ausschnitte = sorted(
            (e["sh1"] for e in gruppe),
            key=lambda s: _nummer(Path(s.replace("\\", "/")).stem)[1],
        )
        for eintrag, ausschnitt in zip(gruppe, ausschnitte):
            if eintrag["sh1"] != ausschnitt:
                geordnet += 1
            eintrag["sh1"] = ausschnitt
            eintrag["folge"] = cru_stamm.strip()
            zeile = fam_index[eintrag["basis"]]
            spalte = sh1_index[ausschnitt]
            eintrag["abstand"] = round(
                float(np.linalg.norm(fam_data[zeile] - sh1_data[spalte])), 3
            )
    return geordnet


def _contact_sheet(
    rows: list[tuple[str, Path, Path]], destination: Path, title: str
) -> None:
    if not rows:
        return
    cell_w = max(max(Image.open(a).width, Image.open(b).width) for _, a, b in rows) + 14
    cell_h = max(max(Image.open(a).height, Image.open(b).height) for _, a, b in rows) + 16
    columns = max(1, min(10, len(rows)))
    lines = (len(rows) + columns - 1) // columns
    canvas = Image.new(
        "RGBA", (columns * cell_w, lines * cell_h * 2 + 22), (26, 26, 30, 255)
    )
    from PIL import ImageDraw

    draw = ImageDraw.Draw(canvas)
    draw.text((4, 4), title, fill=(225, 225, 225, 255))
    for index, (label, left, right) in enumerate(rows):
        column = index % columns
        line = index // columns
        x = column * cell_w
        y = 22 + line * cell_h * 2
        with Image.open(left) as image:
            crusader = image.convert("RGBA")
            canvas.paste(crusader, (x + 7, y), crusader)
        draw.text((x + 7, y + cell_h - 13), label[:26], fill=(185, 185, 185, 255))
        with Image.open(right) as image:
            european = image.convert("RGBA")
            canvas.paste(european, (x + 7, y + cell_h), european)
    canvas.save(destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui_pair",
        description="Crusader-UI-Slots und Stronghold-1-Ausschnitte zuordnen.",
    )
    parser.add_argument("--crusader", default="work/ui")
    parser.add_argument("--sh1", default="work/ui-sh1")
    parser.add_argument("--out", default="work/ui-paare")
    parser.add_argument(
        "--sheets", type=int, default=60, help="Paare je Kontaktbogen"
    )
    parser.add_argument(
        "--familien",
        action="store_true",
        help=(
            "je Farbfamilie statt je Slot zuordnen und global eindeutig vergeben "
            "(siehe pair_familien)"
        ),
    )
    parser.add_argument(
        "--alle-boegen",
        action="store_true",
        help="Kontaktboegen fuer ALLE Gruppen schreiben, nicht nur UI-Buildings",
    )
    args = parser.parse_args(argv)
    try:
        crusader_dir = Path(args.crusader)
        crusader_dir = (
            crusader_dir if crusader_dir.is_absolute() else PROJECT_ROOT / crusader_dir
        )
        sh1_dir = Path(args.sh1)
        sh1_dir = sh1_dir if sh1_dir.is_absolute() else PROJECT_ROOT / sh1_dir
        destination = _project_output(args.out)
        if args.familien:
            result = pair_familien(crusader_dir.resolve(), sh1_dir.resolve())
        else:
            result = pair(crusader_dir.resolve(), sh1_dir.resolve())
    except PairError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1

    destination.mkdir(parents=True, exist_ok=True)
    (destination / "zuordnung.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    total = sum(len(v) for v in result.values())
    einheit = "Farbfamilien" if args.familien else "Crusader-Ausschnitte"
    print(f"{einheit:26}{total:5}")
    print(f"  deckungsgleich          {len(result['identical']):5}  bereits europaeisch")
    print(f"  Kandidat                {len(result['candidates']):5}  am Bild zu pruefen")
    print(f"  ohne Kandidat           {len(result['orphans']):5}  muss gezeichnet werden")
    if args.familien:
        gedeckt = sum(
            1 + len(e.get("fassungen", []))
            for e in result["identical"] + result["candidates"]
        )
        print(f"  davon Slots gedeckt     {gedeckt:5}  Familien mal Fassungen")

    # Kontaktboegen. Bis zum 17.08.2026 entstanden sie nur fuer `UI-Buildings`,
    # womit 1015 der 1308 Kandidaten keine Sichtpruefmoeglichkeit hatten - wer
    # entscheiden sollte, konnte es nicht. `--alle-boegen` schliesst die Luecke
    # und legt je Gruppe einen eigenen Satz Boegen an.
    nach_gruppe: dict[str, list[tuple[str, Path, Path]]] = defaultdict(list)
    for entry in result["candidates"]:
        name = Path(entry["slot"]).name
        gruppe = name.split(" ")[0] if " " in name else Path(name).stem
        if not args.alle_boegen and not name.startswith("UI-Buildings"):
            continue
        left = crusader_dir / entry["slot"]
        right = sh1_dir / entry["sh1"]
        if left.is_file() and right.is_file():
            nach_gruppe[gruppe].append((Path(entry["slot"]).stem, left, right))

    boegen = 0
    for gruppe, rows in sorted(nach_gruppe.items()):
        sicher = "".join(c if c.isalnum() or c in "-_" else "_" for c in gruppe).lower()
        for number in range(0, len(rows), args.sheets):
            chunk = rows[number : number + args.sheets]
            _contact_sheet(
                chunk,
                destination / f"kandidaten-{sicher}-{number // args.sheets + 1:02d}.png",
                "oben: Crusader-Slot     unten: zugeordneter Stronghold-1-Ausschnitt",
            )
            boegen += 1
    print(f"  Kontaktboegen           {boegen:5}  ueber {len(nach_gruppe)} Gruppen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
