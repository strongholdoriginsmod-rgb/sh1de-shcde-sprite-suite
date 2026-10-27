"""Stronghold 1 DE fuehrt eigene XAML-Woerterbuecher — hier sind sie.

BERICHTIGT AM 20.08.2026, und die Berichtigung ist der ganze Zweck dieser Datei.

`tools/ui_sh1_extract.py` und der Kopf von `tools/ui_atlas.py` halten seit dem
16.08. fest, Stronghold 1 liefere **keine** Rechteck-Woerterbuecher mit; Noesis
uebersetze sein XAML beim Bauen in die Anwendung, weshalb die Ausschnitte per
Zusammenhangsanalyse aus dem Bild gewonnen werden muessten. Daraus folgte die
ganze Zuordnung ueber Bildabstand — und deren magere Ausbeute: von 2172 Motiven
liessen sich 435 ueberhaupt paaren, 292 einsetzen, und die Bildprobe verwarf
davon noch einmal 14.

Das war falsch. Die Woerterbuecher liegen in Stronghold 1 DE genauso vor wie in
Crusader, nur nicht als `.xaml` auf der Platte und nicht als `TextAsset`,
sondern als **MonoBehaviour** in `globalgamemanagers.assets`:

    UI-MasterAtlas    152 648 B   1323 CroppedBitmap
    UI-ROL              6 316 B     55 CroppedBitmap
    UI-CandleAtlas      1 924 B     13 CroppedBitmap

Der XAML-Quelltext steht als reiner Text im Rumpf des Objekts; Noesis legt ihn
neben der uebersetzten Fassung ab. `<ResourceDictionary …>` bis
`</ResourceDictionary>` herausschneiden genuegt, danach liest ihn dieselbe
`read_atlas` wie Crusaders eigene Woerterbuecher.

Warum das die Umstellung veraendert: Crusader und Stronghold 1 vergeben
**dieselben Schluessel**. 1262 der 3886 Crusader-Slots haben in Stronghold 1
einen namensgleichen Eintrag, 861 davon sogar pixelgenau dieselbe Groesse. Das
ist keine Aehnlichkeit, die man messen muesste, sondern eine Zusage der beiden
Bauprozesse. Zur Kontrolle gegen Zufall gemessen: paart man Crusader-Slots mit
zufaelligen Stronghold-1-Ausschnitten, sind 1,3 % groessengleich; zieht man
zufaellig aus derselben Gruppe, 39,2 %. Namensgleichheit liefert 68,2 %.

    python tools/ui_sh1_dict.py --out work/ui-sh1-dict

Ausgabe: die drei `.xaml` im Original, je Blatt ein Ordner mit einer PNG-Datei
pro Schluessel und ein `index.json` im selben Format wie
`tools/ui_atlas.py export`. Damit ist der Stronghold-1-Auszug ohne Umbau
verwendbar, wo bisher `work/ui-sh1` stand.

Die Blaetter selbst werden nicht mitgeschrieben — sie liegen bereits als
`work/ui-sh1/*.png` und aendern sich nicht.
"""

from __future__ import annotations

from stronghold_europe_de.suite_paths import portable_path

import argparse
import json
from pathlib import Path
import struct
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from ui_atlas import Crop, UiAtlasError, read_atlas  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover - das venv hat es immer
    print("Pillow fehlt. Bitte im Projekt-venv arbeiten.", file=sys.stderr)
    raise


SH1DE_ASSET = Path(
    portable_path('source_data', 'globalgamemanagers.assets')
)
# Die drei Woerterbuecher heissen wie ihre Blaetter. `UI-MasterAtlas` traegt in
# beiden Spielen denselben Namen bei verschiedener Groesse (Crusader 8192x8192,
# Stronghold 1 8192x4096) — deshalb ist der Auszug streng getrennt zu halten.
DICTIONARIES = ("UI-MasterAtlas", "UI-ROL", "UI-CandleAtlas")
SCHEMA_VERSION = 1


class Sh1DictError(RuntimeError):
    """Die Stronghold-1-Woerterbuecher lassen sich nicht sicher gewinnen."""


def _project_output(value: str) -> Path:
    path = Path(value)
    path = path if path.is_absolute() else (PROJECT_ROOT / path)
    path = path.resolve()
    work = (PROJECT_ROOT / "work").resolve()
    if path == work or not path.is_relative_to(work):
        raise Sh1DictError(f"Ausgabe muss unter {work} liegen, nicht {path}")
    return path


def _monobehaviour_name(raw: bytes) -> str:
    """Den `m_Name` aus dem Rumpf eines MonoBehaviour lesen.

    Ohne Typenbaum kann UnityPy das Objekt nicht zerlegen (IL2CPP-Bau ohne
    Typeninformationen). Der Kopf ist aber fest: PPtr auf das GameObject
    (4 + 8 Byte), `m_Enabled` (4), PPtr auf das MonoScript (4 + 8), dann der
    laengenpraefixierte Name.
    """

    offset = 28
    if len(raw) < offset + 4:
        return ""
    (length,) = struct.unpack_from("<i", raw, offset)
    if not 0 < length < 200 or len(raw) < offset + 4 + length:
        return ""
    return raw[offset + 4 : offset + 4 + length].decode("utf-8", "replace")


def dump_dictionaries(destination: Path) -> dict[str, int]:
    """Die drei XAML-Woerterbuecher als Text herausschneiden."""

    try:
        import UnityPy
    except ImportError as error:  # pragma: no cover - Umgebungsfrage
        raise Sh1DictError(
            "UnityPy fehlt; Projekt mit dem Extra 'assets' installieren"
        ) from error
    if not SH1DE_ASSET.is_file():
        raise Sh1DictError(f"Nicht gefunden: {SH1DE_ASSET}")

    destination.mkdir(parents=True, exist_ok=True)
    environment = UnityPy.load(str(SH1DE_ASSET))
    sizes: dict[str, int] = {}
    for obj in environment.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        raw = bytes(obj.get_raw_data())
        name = _monobehaviour_name(raw)
        if name not in DICTIONARIES or name in sizes:
            continue
        start = raw.find(b"<ResourceDictionary")
        end = raw.rfind(b"</ResourceDictionary>")
        if start < 0 or end < 0:
            raise Sh1DictError(
                f"{name}: kein <ResourceDictionary>-Block im MonoBehaviour-Rumpf"
            )
        text = raw[start : end + len(b"</ResourceDictionary>")].decode("utf-8")
        (destination / f"{name}.xaml").write_text(text, encoding="utf-8")
        sizes[name] = len(text)
    missing = [name for name in DICTIONARIES if name not in sizes]
    if missing:
        raise Sh1DictError(f"Woerterbuch fehlt in {SH1DE_ASSET.name}: {missing}")
    return sizes


def load_sheets(wanted: set[str]) -> dict[str, "Image.Image"]:
    """Die Blaetter dekodieren — bevorzugt aus dem vorhandenen Auszug."""

    cached = PROJECT_ROOT / "work" / "ui-sh1"
    sheets: dict[str, Image.Image] = {}
    for name in sorted(wanted):
        path = cached / f"{name}.png"
        if path.is_file():
            sheets[name] = Image.open(path).convert("RGBA")
    if len(sheets) == len(wanted):
        return sheets

    import UnityPy

    environment = UnityPy.load(str(SH1DE_ASSET))
    for obj in environment.objects:
        if obj.type.name != "Texture2D":
            continue
        try:
            data = obj.read()
        except Exception:
            continue
        name = getattr(data, "m_Name", "") or ""
        if name not in wanted or name in sheets:
            continue
        sheets[name] = data.image.convert("RGBA")
        if len(sheets) == len(wanted):
            break
    missing = sorted(wanted - set(sheets))
    if missing:
        raise Sh1DictError(f"Blatt fehlt: {missing}")
    return sheets


def cut(destination: Path) -> tuple[dict[str, int], list[str]]:
    """Jeden benannten Ausschnitt als eigene PNG-Datei ablegen."""

    per_sheet: dict[str, list[Crop]] = {}
    for name in DICTIONARIES:
        xaml = destination / f"{name}.xaml"
        try:
            sheet_file, crops = read_atlas(xaml)
        except UiAtlasError as error:
            raise Sh1DictError(f"{name}: {error}") from error
        if not crops:
            raise Sh1DictError(f"{name}: keine Ausschnitte im Woerterbuch")
        # Das BitmapImage nennt `UI-MasterAtlas.png`; der Texturname ist der
        # Stamm davon. Ueber alle drei Woerterbuecher gegengeprueft.
        stem = Path(sheet_file).stem
        if stem != name:
            raise Sh1DictError(
                f"{name}: Woerterbuch verweist auf fremdes Blatt {sheet_file!r}"
            )
        per_sheet[name] = crops

    sheets = load_sheets(set(per_sheet))
    counts: dict[str, int] = {}
    entries: list[dict] = []
    warnings: list[str] = []
    for name, crops in per_sheet.items():
        sheet = sheets[name]
        folder = destination / name
        folder.mkdir(exist_ok=True)
        written = 0
        for crop in crops:
            if crop.x + crop.width > sheet.width or crop.y + crop.height > sheet.height:
                warnings.append(
                    f"{name}/{crop.key}: Rechteck {crop.box} liegt ausserhalb "
                    f"{sheet.width}x{sheet.height}"
                )
                continue
            sheet.crop(crop.box).save(folder / crop.filename)
            written += 1
            entries.append(
                {
                    "key": crop.key,
                    "sheet": name,
                    "file": f"{name}/{crop.filename}",
                    "x": crop.x,
                    "y": crop.y,
                    "width": crop.width,
                    "height": crop.height,
                }
            )
        counts[name] = written
    (destination / "index.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "source": str(SH1DE_ASSET),
                "note": (
                    "Rechtecke aus Stronghold 1 DEs eigenen Noesis-Woerterbuechern, "
                    "nicht aus dem Bild geraten."
                ),
                "crops": entries,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return counts, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui_sh1_dict",
        description="Stronghold 1 DEs eigene UI-Woerterbuecher gewinnen und ausschneiden.",
    )
    parser.add_argument("--out", default="work/ui-sh1-dict")
    parser.add_argument(
        "--nur-xaml",
        action="store_true",
        help="nur die drei Woerterbuecher schreiben, nichts ausschneiden",
    )
    args = parser.parse_args(argv)
    try:
        destination = _project_output(args.out)
        sizes = dump_dictionaries(destination)
        for name, size in sizes.items():
            print(f"{name:18} {size:8} Zeichen XAML")
        if args.nur_xaml:
            return 0
        counts, warnings = cut(destination)
        print()
        for name, count in counts.items():
            print(f"{name:18} {count:5} Ausschnitte")
        print(f"{'zusammen':18} {sum(counts.values()):5}")
        for line in warnings:
            print(f"  uebersprungen: {line}", file=sys.stderr)
    except (Sh1DictError, UiAtlasError) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
