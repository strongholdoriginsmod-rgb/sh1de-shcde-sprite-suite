"""Die Stronghold-1-UI aus ihren TexturePacker-Blaettern herausschneiden.

Stronghold 1 DE FUEHRT eine UI - das ist am 16.08.2026 nachgemessen worden,
nachdem der Kopf von tools/ui_atlas.py jahrelang das Gegenteil behauptet hat.
In `globalgamemanagers.assets` liegen drei Blaetter:

    UI-MasterAtlas    8192 x 4096
    UI-ROL            4096 x 4096
    UI-CandleAtlas    2048 x 4096

Gleiche Namen und Groessen wie bei Crusader. Die Rechtecke liegen aber ANDERS:
Auf Crusaders Rechteck fuer das Kornspeicher-Symbol steht bei Stronghold 1 eine
Bilderrahmenecke, auf dem Pyramidensymbol ein aufgeschlagenes Buch. Crusaders
XAML-Woerterbuecher sind hier also wertlos.

WIDERRUFEN AM 20.08.2026. Hier stand, Stronghold 1 liefere keine eigenen
Woerterbuecher mit - es gebe keine .xaml auf der Platte, keinen TextAsset mit
Rechtecken, Noesis uebersetze sein XAML beim Bauen in die Anwendung hinein.
Das ist falsch, und es hat die ganze Zuordnung ueber Bildabstand verursacht.
Die Woerterbuecher liegen als MonoBehaviour in `globalgamemanagers.assets`, mit
dem XAML-Quelltext im Klartext im Objektrumpf: UI-MasterAtlas 1323
CroppedBitmap, UI-ROL 55, UI-CandleAtlas 13.

**Fuer die Umstellung ist dieses Werkzeug damit ueberholt.** Es gewinnt
Rechtecke aus dem Bild und vergibt Laufnummern; `tools/ui_sh1_dict.py` gewinnt
sie aus dem Woerterbuch und vergibt die echten Namen - und Crusader vergibt
dieselben. Siehe docs/UI_SH1_NAMENSGLEICH.md. Was hier bleibt, ist der Nutzen
als Gegenprobe: wo die Zusammenhangsanalyse und das Woerterbuch dasselbe
Rechteck finden, ist beides bestaetigt.

Bleibt, die Rechtecke aus dem Bild selbst zu gewinnen. TexturePacker legt in
Regalreihen ab und laesst zwischen den Ausschnitten eine durchsichtige Fuge;
darum genuegt eine Projektion: durchgehend leere Bildzeilen trennen die Regale,
innerhalb eines Regals trennen durchgehend leere Spalten die Ausschnitte. Das
ist keine Zusammenhangsanalyse und findet deshalb auch keine Motive, die sich
beruehren - dafuer laeuft es ueber 33 Millionen Pixel in Sekunden statt in
Minuten, und wo es zu grob war, sieht man es dem Kontaktbogen sofort an.

    python tools/ui_sh1_extract.py --out work/ui-sh1

Die Blaetter selbst werden dabei ebenfalls abgelegt, damit sie ohne Umweg ueber
UnityPy weiterverwendet werden koennen.
"""

from __future__ import annotations

from stronghold_europe_de.suite_paths import portable_path

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SH1DE_ASSET = Path(
    portable_path('source_data', 'globalgamemanagers.assets')
)
SHEETS = ("UI-MasterAtlas", "UI-ROL", "UI-CandleAtlas")

# Kleiner als das faellt als Fuge oder Staub durch. Gemessen: Crusaders
# kleinster benannter Ausschnitt ist 8x8.
MIN_SIDE = 6
# Ein Pixel gilt als belegt, wenn es nicht praktisch durchsichtig ist. Nicht
# strikt > 0: TexturePacker laesst an den Raendern einen Alpha-Saum stehen.
ALPHA_FLOOR = 8


class ExtractError(RuntimeError):
    """Die Blaetter lassen sich nicht sicher zerlegen."""


def _project_output(value: str) -> Path:
    path = Path(value)
    path = path if path.is_absolute() else (PROJECT_ROOT / path)
    path = path.resolve()
    work = (PROJECT_ROOT / "work").resolve()
    if path == work or not path.is_relative_to(work):
        raise ExtractError(f"Ausgabe muss unter {work} liegen, nicht {path}")
    return path


def cut_sheet(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Die Ausschnitte eines Blattes als (x, y, breite, hoehe).

    Zusammenhangsanalyse auf der Alphamaske, nicht Projektion auf die Achsen.
    Der erste Entwurf projizierte und fand auf dem MasterAtlas GENAU EINEN
    Ausschnitt: Das Blatt ist fugenlos gepackt, es gibt keine durchgehend leere
    Bildzeile. Zusammenhaengende Gebiete trennen dagegen sauber, solange sich
    zwei Motive nicht beruehren - und wo sie es tun, faellt es auf dem
    Kontaktbogen als Doppelbild auf.
    """

    from scipy import ndimage

    alpha = np.asarray(image.convert("RGBA"))[:, :, 3] >= ALPHA_FLOOR
    labels, count = ndimage.label(alpha)
    boxes: list[tuple[int, int, int, int]] = []
    for y_slice, x_slice in ndimage.find_objects(labels):
        width = x_slice.stop - x_slice.start
        height = y_slice.stop - y_slice.start
        if width < MIN_SIDE or height < MIN_SIDE:
            continue
        boxes.append((x_slice.start, y_slice.start, width, height))
    # Lesbare Reihenfolge: zeilenweise von oben nach unten.
    boxes.sort(key=lambda box: (box[1], box[0]))
    return boxes


def extract(destination: Path) -> dict[str, int]:
    try:
        import UnityPy
    except ImportError as error:  # pragma: no cover - Umgebungsfrage
        raise ExtractError("UnityPy fehlt; Projekt mit dem Extra 'assets' installieren") from error
    if not SH1DE_ASSET.is_file():
        raise ExtractError(f"Nicht gefunden: {SH1DE_ASSET}")

    destination.mkdir(parents=True, exist_ok=True)
    environment = UnityPy.load(str(SH1DE_ASSET))
    found: dict[str, Image.Image] = {}
    for obj in environment.objects:
        if obj.type.name != "Texture2D":
            continue
        data = obj.read()
        if data.m_Name in SHEETS:
            found[data.m_Name] = data.image
    missing = [name for name in SHEETS if name not in found]
    if missing:
        raise ExtractError(f"Blatt fehlt in {SH1DE_ASSET.name}: {missing}")

    counts: dict[str, int] = {}
    index: list[dict] = []
    for name, sheet in found.items():
        sheet.save(destination / f"{name}.png")
        folder = destination / name
        folder.mkdir(exist_ok=True)
        crops = cut_sheet(sheet)
        for number, (x, y, width, height) in enumerate(crops, start=1):
            file_name = f"{name} {number:04d}.png"
            sheet.crop((x, y, x + width, y + height)).save(folder / file_name)
            index.append(
                {
                    "sheet": name,
                    "file": f"{name}/{file_name}",
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                }
            )
        counts[name] = len(crops)
    (destination / "index.json").write_text(
        json.dumps(
            {
                "source": str(SH1DE_ASSET),
                "note": (
                    "Rechtecke aus dem Bild gewonnen, nicht aus einem "
                    "Woerterbuch - Stronghold 1 liefert keines mit."
                ),
                "crops": index,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui_sh1_extract",
        description="Die Stronghold-1-UI aus ihren Blaettern herausschneiden.",
    )
    parser.add_argument("--out", default="work/ui-sh1")
    args = parser.parse_args(argv)
    try:
        counts = extract(_project_output(args.out))
    except ExtractError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    for name, count in counts.items():
        print(f"{name:18} {count:5} Ausschnitte")
    print(f"{'zusammen':18} {sum(counts.values()):5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
