"""Export UI artwork as ordinary PNGs and return verified edits to the build.

The interface is not made of loose images.  Every button, icon and panel is a
rectangle cut out of one big TexturePacker sheet, and a XAML resource dictionary
names each rectangle:

    <CroppedBitmap x:Key="UI-Buildings E007"
                   Source="{StaticResource UI-MasterAtlas}"
                   SourceRect="8044,2,146,157"/>

This tool is the way in and out of Crusader's own sheets.

BERICHTIGT AM 16.08.2026.  Hier stand, Stronghold 1 DE habe kein vergleichbares
Blatt, diese Bilder seien deshalb als einzige der ganzen Umsetzung nicht zu
konvertieren, sondern zu zeichnen.  Das war falsch, und es hat Arbeit gekostet.
Stronghold 1 DE fuehrt in seinem eigenen `globalgamemanagers.assets` drei
Blaetter mit denselben Namen und Groessen wie Crusader - UI-MasterAtlas
8192x4096, UI-ROL 4096x4096, UI-CandleAtlas 2048x4096 - und darauf liegt die
vollstaendige europaeische Oberflaeche: Fachwerkhaeuser, Holzpalisaden,
Steinturm, Weizenfarm, Brauerei, Kirche mit Kreuz, gotisches Masswerk.

Woher der Irrtum kam, ist der Merksatz: Die Woerterbuecher unten kommen vom
Script-Extender, nicht aus dem Spiel (siehe DEFAULT_SPRITES).  Wer nur dort
sucht, findet fuer Stronghold 1 nichts - es hat keinen Extender.  Die Blaetter
lagen die ganze Zeit im Spiel selbst.

Die Rechtecke sind allerdings ANDERS gepackt als bei Crusader, Crusaders XAML
ist auf Stronghold 1 also nicht anwendbar.  Und Stronghold 1 liefert keine
eigenen Woerterbuecher mit; Noesis uebersetzt sein XAML beim Bauen in die
Anwendung.  Zum Herausschneiden dient deshalb tools/ui_sh1_extract.py, das die
Rechtecke aus dem Bild selbst gewinnt.

    python tools/ui_atlas.py export --out work/ui
    ... edit the PNGs in work/ui/UI-MasterAtlas/ with any image editor ...
    python tools/ui_atlas.py check --from work/ui
    python tools/ui_atlas.py import --from work/ui --store europa-ui
    python tools/ui_atlas.py profile-add europa-ui --write

Beim bewussten Wechsel von einer Vorgaengerablage, die dieselben Blaetter
beansprucht, kommt ``--verdraengen`` hinzu. Ohne diesen ausdruecklichen Schalter
bleibt die Kollisionspruefung fehl-geschlossen.

Export writes one PNG per rectangle plus an index.json.  Import checks every
edited file against its declared rectangle, refuses anything that does not fit,
and pastes the survivors back at exactly the coordinates they came from.

The final two commands create a digest-pinned derived store and select it in
the production profile; the normal build/install path then delivers it. A loose
``--out`` import remains available only as a review artifact.

Nothing here guesses.  A file whose size does not match its rectangle is
rejected by name and size rather than scaled - a scaled icon would land in the
sheet looking almost right and be very hard to trace later.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

try:
    from PIL import Image
except ImportError:  # pragma: no cover - the venv always has it
    print("Pillow fehlt. Bitte im Projekt-venv arbeiten.", file=sys.stderr)
    raise

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
XAML_NS = "{http://schemas.microsoft.com/winfx/2006/xaml}"
PRESENTATION_NS = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"

# The extender ships the XAML dictionaries that describe the sheets, but not the
# sheets themselves: `UriSource="UI-MasterAtlas.png"` names a file that does not
# exist on disk.  The pixels live inside the game as Unity textures, and they are
# not in resources.assets where the sprite work happens - they are in
# globalgamemanagers.assets, which is why an earlier search for them came up
# empty.
CONFIG = "config/installations.local.toml"
INDEX_SCHEMA_VERSION = 1
UI_SHEET_DIMENSIONS = {
    "UI-MasterAtlas.png": (8192, 8192),
    "UI-TrailAtlas.png": (8192, 8192),
    "UI-Colour1Atlas.png": (4096, 4096),
    "UI-Colour2Atlas.png": (4096, 4096),
}
# Where an override has to land for the extender to serve it instead.
OVERRIDE_RELATIVE = Path("Override/Assets/GUI/Sprites")


class UiAtlasError(RuntimeError):
    """The UI artwork cannot be proven safe to export or rebuild."""


def _configured_sources() -> tuple[Path, Path, str]:
    """Resolve UI sources from the same approved installation as the builder."""

    from stronghold_europe_de.builds import verify_supported_builds
    from stronghold_europe_de.config import load_config

    config = load_config(PROJECT_ROOT / CONFIG)
    if config.target.game_dir is None:
        raise UiAtlasError("Kein Crusader-Spielordner konfiguriert")
    match = verify_supported_builds(
        config, PROJECT_ROOT / "config" / "supported-builds.json"
    )
    sprites = (
        config.target.game_dir
        / "BepInEx" / "plugins" / "000shcdese"
        / "Override" / "Assets" / "GUI" / "Sprites"
    ).resolve()
    textures = (config.target.data_dir / "globalgamemanagers.assets").resolve()
    if not sprites.is_dir():
        raise UiAtlasError(f"Extender-XAML-Ordner fehlt: {sprites}")
    if not textures.is_file():
        raise UiAtlasError(f"Unity-UI-Asset fehlt: {textures}")
    return sprites, textures, match.target_id


def _resolve_sources(args: argparse.Namespace) -> tuple[Path, Path, str]:
    configured_sprites, configured_textures, build_id = _configured_sources()
    sprites = Path(args.sprites).resolve() if args.sprites else configured_sprites
    textures = Path(args.textures).resolve() if args.textures else configured_textures
    if sprites != configured_sprites or textures != configured_textures:
        raise UiAtlasError(
            "UI-Quellen müssen exakt aus der konfigurierten und fingerprint-geprüften "
            "SHCDE-Installation stammen"
        )
    return sprites, textures, build_id


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pixel_digest(image: Image.Image) -> str:
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    return hashlib.sha256(rgba.tobytes()).hexdigest()


def _project_output(value: str, root_name: str) -> Path:
    path = Path(value)
    path = path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    root = (PROJECT_ROOT / root_name).resolve()
    if path == root or not path.is_relative_to(root):
        raise UiAtlasError(
            f"Ausgabe muss ein Unterordner von {root} sein, nicht {path}"
        )
    return path


def _flat_name(value: object, label: str) -> str:
    text = str(value)
    if not text or Path(text).name != text or text in {".", ".."}:
        raise UiAtlasError(f"Unsicherer {label}: {text!r}")
    return text


def _prepare_directory(destination: Path, replace: bool) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_dir():
            raise UiAtlasError(f"Ausgabe ist kein Ordner: {destination}")
        if any(destination.iterdir()) and not replace:
            raise UiAtlasError(
                f"Ausgabeordner ist nicht leer: {destination}. "
                "Bearbeitete Bilder sichern oder --replace ausdrücklich verwenden."
            )
    return Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.ui-atlas-", dir=destination.parent)
    )


def _commit_directory(staging: Path, destination: Path, replace: bool) -> None:
    backup: Path | None = None
    try:
        if destination.exists():
            if not replace and any(destination.iterdir()):
                raise UiAtlasError(f"Ausgabeordner änderte sich während des Schreibens: {destination}")
            backup = destination.with_name(destination.name + ".ui-atlas-backup")
            if backup.exists():
                raise UiAtlasError(f"Alte UI-Atlas-Sicherung blockiert den Lauf: {backup}")
            os.replace(destination, backup)
        os.replace(staging, destination)
        if backup is not None:
            shutil.rmtree(backup)
    except Exception:
        if destination.exists() and backup is not None and backup.exists():
            shutil.rmtree(destination)
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise


def load_sheets(asset_path: Path, wanted: set[str]) -> dict[str, "Image.Image"]:
    """Decode the named atlas textures out of a Unity assets file.

    These are 8192x8192 RGBA sheets - a quarter of a gigabyte each in memory -
    so only the ones actually asked for get decoded.
    """

    import UnityPy

    environment = UnityPy.load(str(asset_path))
    sheets: dict[str, Image.Image] = {}
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
    return sheets

# Windows forbids these in file names, and several resource keys contain them.
UNSAFE = re.compile(r'[<>:"/\\|?*]')


@dataclass(frozen=True)
class Crop:
    """One named rectangle inside one sheet."""

    key: str
    sheet: str
    x: int
    y: int
    width: int
    height: int

    @property
    def filename(self) -> str:
        return UNSAFE.sub("_", self.key) + ".png"

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)


def read_atlas(xaml_path: Path) -> tuple[str, list[Crop]]:
    """Read a TexturePacker resource dictionary: its sheet and every rectangle."""

    try:
        tree = ElementTree.parse(xaml_path)
    except (OSError, ElementTree.ParseError) as exc:
        raise UiAtlasError(f"XAML ist nicht lesbar: {xaml_path} ({exc})") from exc
    root = tree.getroot()
    sheet_name: str | None = None
    sheet_key: str | None = None
    for element in root:
        if element.tag == PRESENTATION_NS + "BitmapImage":
            sheet_key = element.get(XAML_NS + "Key")
            sheet_name = element.get("UriSource")
            break
    crop_elements = [
        element for element in root if element.tag == PRESENTATION_NS + "CroppedBitmap"
    ]
    if not sheet_name or not sheet_key:
        if crop_elements:
            raise UiAtlasError(
                f"{xaml_path.name} enthält CroppedBitmap ohne eindeutiges BitmapImage"
            )
        return "", []

    crops: list[Crop] = []
    keys: set[str] = set()
    filenames: set[str] = set()
    for element in crop_elements:
        key = element.get(XAML_NS + "Key")
        rect = element.get("SourceRect")
        if not key or not rect:
            raise UiAtlasError(f"{xaml_path.name}: CroppedBitmap ohne Key/SourceRect")
        parts = [part.strip() for part in rect.replace(";", ",").split(",")]
        if len(parts) != 4:
            raise UiAtlasError(f"{xaml_path.name}/{key}: SourceRect hat nicht vier Werte")
        try:
            x, y, width, height = (int(part) for part in parts)
        except ValueError as exc:
            raise UiAtlasError(f"{xaml_path.name}/{key}: SourceRect ist nicht ganzzahlig") from exc
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise UiAtlasError(f"{xaml_path.name}/{key}: SourceRect ist nicht positiv")
        crop = Crop(key, sheet_name, x, y, width, height)
        if key in keys:
            raise UiAtlasError(f"{xaml_path.name}: doppelter Ressourcenschlüssel {key}")
        if crop.filename in filenames:
            raise UiAtlasError(
                f"{xaml_path.name}: Dateinamen kollidieren nach Windows-Bereinigung: {crop.filename}"
            )
        keys.add(key)
        filenames.add(crop.filename)
        crops.append(crop)
    return sheet_name, crops


def discover(sprites_dir: Path) -> list[tuple[Path, str, list[Crop]]]:
    """Every atlas dictionary in a sprites folder, with its sheet and crops."""

    found: list[tuple[Path, str, list[Crop]]] = []
    global_keys: set[str] = set()
    for xaml_path in sorted(sprites_dir.glob("*.xaml")):
        sheet, crops = read_atlas(xaml_path)
        if crops:
            duplicate = global_keys & {crop.key for crop in crops}
            if duplicate:
                raise UiAtlasError(
                    f"Ressourcenschlüssel kommen in mehreren Dictionaries vor: {sorted(duplicate)[:8]}"
                )
            global_keys.update(crop.key for crop in crops)
            found.append((xaml_path, sheet, crops))
    return found


def _reject_overlaps(crops: list[Crop], label: str) -> None:
    """No two editable rectangles may mutate the same atlas pixel."""

    ordered = sorted(crops, key=lambda crop: (crop.x, crop.y, crop.key))
    active: list[Crop] = []
    for crop in ordered:
        active = [other for other in active if other.x + other.width > crop.x]
        for other in active:
            if crop.y < other.y + other.height and other.y < crop.y + crop.height:
                raise UiAtlasError(
                    f"{label}: Ausschnitte überlappen ({other.key!r}, {crop.key!r})"
                )
        active.append(crop)


def cmd_list(args: argparse.Namespace) -> int:
    sprites, textures, _build_id = _resolve_sources(args)
    atlases = discover(sprites)
    if not atlases:
        print(f"Keine Atlas-Dictionaries in {sprites}")
        return 1
    total = 0
    print(f"{'Dictionary':<28} {'Blatt':<28} {'Ausschnitte':>11}")
    for xaml_path, sheet, crops in atlases:
        print(f"{xaml_path.name:<28} {sheet:<28} {len(crops):>11}")
        total += len(crops)
    print(f"\n{total} Ausschnitte in {len(atlases)} Blaettern")
    print()
    print("Die Blaetter selbst liegen nicht als Datei vor, sondern als Unity-")
    print(f"Texturen in {textures.name}.")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from stronghold_europe_de.workspace_lock import (
        WorkspaceLockError,
        exclusive_workspace_lock,
    )

    try:
        with exclusive_workspace_lock(
            PROJECT_ROOT / "work", f"ui-export:{args.out}", "UI-Export"
        ):
            return _cmd_export_locked(args)
    except WorkspaceLockError as exc:
        raise UiAtlasError(str(exc)) from exc


def _cmd_export_locked(args: argparse.Namespace) -> int:
    sprites, texture_asset, target_build_id = _resolve_sources(args)
    out_root = _project_output(args.out, "work")
    atlases = discover(sprites)
    if not atlases:
        print(f"Keine Atlas-Dictionaries in {sprites}")
        return 1
    wanted = set(args.atlas) if args.atlas else None

    selected = [
        (xaml_path, sheet, crops)
        for xaml_path, sheet, crops in atlases
        if wanted is None or xaml_path.stem in wanted
    ]
    if not selected:
        print("Keines der gewaehlten Dictionaries gefunden.")
        return 1
    texture_names = {Path(sheet).stem for _x, sheet, _c in selected}
    print(f"Lade {len(texture_names)} Blatt/Blaetter aus dem Spiel ...")
    sheets = load_sheets(texture_asset, texture_names)
    missing_sheets = sorted(texture_names - set(sheets))
    if missing_sheets:
        raise UiAtlasError(
            "Atlastexturen nicht im Spiel gefunden: " + ", ".join(missing_sheets)
        )

    staging = _prepare_directory(out_root, args.replace)

    index: dict[str, object] = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "target_build_id": target_build_id,
        "texture_asset_name": texture_asset.name,
        "texture_asset_sha256": _sha256_file(texture_asset),
        "atlases": [],
    }
    written = 0
    try:
        for xaml_path, sheet, crops in selected:
            _reject_overlaps(crops, xaml_path.name)
            stem = _flat_name(xaml_path.stem, "Atlasordner")
            source = sheets[Path(sheet).stem]
            target_dir = staging / stem
            target_dir.mkdir(parents=True, exist_ok=True)
            entries: list[dict[str, object]] = []
            for crop in crops:
                if (
                    crop.x < 0
                    or crop.y < 0
                    or crop.x + crop.width > source.width
                    or crop.y + crop.height > source.height
                ):
                    raise UiAtlasError(f"Ausschnitt liegt außerhalb des Blattes: {crop.key}")
                source.crop(crop.box).save(target_dir / crop.filename)
                entries.append(
                    {
                        "key": crop.key,
                        "file": crop.filename,
                        "x": crop.x,
                        "y": crop.y,
                        "width": crop.width,
                        "height": crop.height,
                        "baseline_pixels_sha256": _pixel_digest(source.crop(crop.box)),
                    }
                )
                written += 1
            index["atlases"].append(
                {
                    "dictionary": xaml_path.name,
                    "dictionary_sha256": _sha256_file(xaml_path),
                    "sheet": sheet,
                    "sheet_width": source.width,
                    "sheet_height": source.height,
                    "directory": stem,
                    "crops": entries,
                }
            )
            print(f"  {stem}: {len(entries)} PNGs")

        (staging / "index.json").write_text(
            json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        _commit_directory(staging, out_root, args.replace)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    print(f"\n{written} Bilder nach {out_root}")
    print()
    print("Die Dateinamen tragen den Ressourcenschluessel, etwa")
    print("  'UI-Buildings A017.png'  ->  <CroppedBitmap x:Key=\"UI-Buildings A017\">")
    print("Bearbeite sie mit einem beliebigen Bildprogramm. Die Bildgroesse muss")
    print("exakt bleiben - der Platz im Blatt ist fest vergeben.")
    print()
    print(f"Zurueckbauen:  python tools/ui_atlas.py import --from {args.out}")
    return 0


def _inspect_edits(
    source_root: Path,
    *,
    sprites_dir: Path,
    texture_asset: Path,
    target_build_id: str,
    atlas_selector: list[str] | None = None,
) -> tuple[list[tuple[str, Image.Image, int]], list[str]]:
    source_root = source_root.resolve() if source_root.is_absolute() else (PROJECT_ROOT / source_root).resolve()
    index_path = source_root / "index.json"
    if not index_path.is_file():
        raise UiAtlasError(f"Kein index.json in {source_root} - erst exportieren.")
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UiAtlasError(f"index.json ist nicht lesbar: {exc}") from exc
    allowed_top = {
        "schema_version", "target_build_id", "texture_asset_name",
        "texture_asset_sha256", "atlases",
    }
    if (
        not isinstance(index, dict)
        or index.get("schema_version") != INDEX_SCHEMA_VERSION
        or set(index) != allowed_top
        or not isinstance(index.get("atlases"), list)
        or not index["atlases"]
    ):
        raise UiAtlasError("index.json hat nicht den vollständigen unterstützten UI-Vertrag")
    if index["target_build_id"] != target_build_id:
        raise UiAtlasError("UI-Export gehört nicht zum aktuellen SHCDE-Build")
    if index["texture_asset_name"] != texture_asset.name:
        raise UiAtlasError("UI-Export nennt eine andere Unity-Assetdatei")
    if index["texture_asset_sha256"] != _sha256_file(texture_asset):
        raise UiAtlasError("Unity-UI-Asset wurde seit dem Export verändert")

    discovered = {path.name: (path, sheet, crops) for path, sheet, crops in discover(sprites_dir)}
    wanted: set[str] | None = None
    if atlas_selector is not None:
        if not atlas_selector:
            raise UiAtlasError("--atlas braucht mindestens einen Dictionary-Namen")
        wanted = set()
        for raw_name in atlas_selector:
            name = _flat_name(raw_name, "Atlas-Auswahl")
            if Path(name).suffix or Path(name).stem != name:
                raise UiAtlasError(
                    f"Atlas-Auswahl muss ein Dictionary-Stamm ohne Endung sein: {name!r}"
                )
            if name in wanted:
                raise UiAtlasError(f"Atlas-Auswahl ist doppelt: {name}")
            wanted.add(name)
    needed: set[str] = set()
    atlas_names: set[str] = set()
    atlas_stems: set[str] = set()
    sheet_names: set[str] = set()
    directory_names: set[str] = set()
    for position, atlas in enumerate(index["atlases"]):
        if not isinstance(atlas, dict) or set(atlas) != {
            "dictionary", "dictionary_sha256", "sheet", "sheet_width",
            "sheet_height", "directory", "crops",
        }:
            raise UiAtlasError(f"Atlasindex[{position}] ist unvollständig oder erweitert")
        dictionary = _flat_name(atlas["dictionary"], "Dictionary")
        sheet_name = _flat_name(atlas["sheet"], "Blattname")
        directory_name = _flat_name(atlas["directory"], "Atlasordner")
        atlas_stem = Path(dictionary).stem
        if dictionary in atlas_names or sheet_name in sheet_names or directory_name in directory_names:
            raise UiAtlasError("Atlasindex enthält doppelte Dictionaries, Blätter oder Ordner")
        atlas_names.add(dictionary)
        if atlas_stem in atlas_stems:
            raise UiAtlasError("Atlasindex enthaelt doppelte Dictionary-Staemme")
        atlas_stems.add(atlas_stem)
        sheet_names.add(sheet_name)
        directory_names.add(directory_name)
        if dictionary not in discovered:
            raise UiAtlasError(f"XAML-Dictionary fehlt inzwischen: {dictionary}")
        xaml_path, current_sheet, current_crops = discovered[dictionary]
        if atlas["dictionary_sha256"] != _sha256_file(xaml_path):
            raise UiAtlasError(f"XAML-Dictionary wurde seit dem Export verändert: {dictionary}")
        if current_sheet != sheet_name:
            raise UiAtlasError(f"{dictionary}: Blattzuordnung wurde verändert")
        _reject_overlaps(current_crops, dictionary)
        if wanted is None or atlas_stem in wanted:
            needed.add(Path(sheet_name).stem)
    if wanted is not None:
        unknown = sorted(wanted - atlas_stems)
        if unknown:
            raise UiAtlasError(
                "Unbekannte Atlas-Auswahl: " + ", ".join(unknown)
                + "; vorhanden: " + ", ".join(sorted(atlas_stems))
            )
    print(f"Lade {len(needed)} Blatt/Blaetter aus dem Spiel ...")
    sheets = load_sheets(texture_asset, needed)

    problems: list[str] = []
    prepared: list[tuple[str, Image.Image, int]] = []
    for atlas in index["atlases"]:
        if wanted is not None and Path(str(atlas["dictionary"])).stem not in wanted:
            continue
        sheet_name = _flat_name(atlas["sheet"], "Blattname")
        sheet = sheets.get(Path(sheet_name).stem)
        if sheet is None:
            problems.append(f"Blatt nicht im Spiel gefunden: {sheet_name}")
            continue
        directory_name = _flat_name(atlas["directory"], "Atlasordner")
        directory = source_root / directory_name
        if not directory.is_dir():
            problems.append(f"Atlasordner fehlt: {directory_name}")
            continue
        try:
            expected_sheet_size = (int(atlas["sheet_width"]), int(atlas["sheet_height"]))
        except (TypeError, ValueError) as exc:
            raise UiAtlasError(f"{directory_name}: Blattgröße ist ungültig") from exc
        if sheet.size != expected_sheet_size:
            problems.append(
                f"{directory_name}: aktuelles Blatt {sheet.width}x{sheet.height} "
                f"statt {expected_sheet_size[0]}x{expected_sheet_size[1]}"
            )
            continue
        updated = sheet.copy()
        changed = 0
        crops = atlas.get("crops")
        if not isinstance(crops, list):
            problems.append(f"{directory_name}: Ausschnittsliste fehlt")
            continue
        dictionary = str(atlas["dictionary"])
        current_crops = {crop.key: crop for crop in discovered[dictionary][2]}
        indexed_files: set[str] = set()
        indexed_keys: set[str] = set()
        for entry in crops:
            if not isinstance(entry, dict) or set(entry) != {
                "key", "file", "x", "y", "width", "height",
                "baseline_pixels_sha256",
            }:
                problems.append(f"{directory_name}: ungültiger Ausschnittseintrag")
                continue
            key = str(entry.get("key", ""))
            if key in indexed_keys or key not in current_crops:
                problems.append(f"{directory_name}: fremder oder doppelter Schlüssel {key!r}")
                continue
            indexed_keys.add(key)
            filename = _flat_name(entry.get("file", ""), "Ausschnittsdatei")
            current = current_crops[key]
            expected_geometry = (current.x, current.y, current.width, current.height)
            try:
                indexed_geometry = tuple(
                    int(entry[field]) for field in ("x", "y", "width", "height")
                )
            except (TypeError, ValueError) as exc:
                raise UiAtlasError(f"{directory_name}/{key}: Geometrie ist ungültig") from exc
            if indexed_geometry != expected_geometry or filename != current.filename:
                problems.append(f"{directory_name}/{key}: XAML-Geometrie/Dateiname verändert")
                continue
            if filename in indexed_files:
                problems.append(f"{directory_name}: doppelter Dateiname {filename}")
                continue
            indexed_files.add(filename)
            candidate = directory / filename
            if not candidate.is_file():
                problems.append(f"{directory_name}/{filename}: fehlt")
                continue
            try:
                with Image.open(candidate) as opened:
                    edited = opened.convert("RGBA")
            except Exception as exc:
                problems.append(f"{directory_name}/{filename}: nicht lesbar ({exc})")
                continue
            width, height = int(entry["width"]), int(entry["height"])
            x, y = int(entry["x"]), int(entry["y"])
            if edited.size != (width, height):
                problems.append(
                    f"{directory_name}/{filename}: "
                    f"{edited.width}x{edited.height} statt {width}x{height}"
                )
                continue
            if x < 0 or y < 0 or x + width > sheet.width or y + height > sheet.height:
                problems.append(f"{directory_name}/{filename}: Rechteck liegt außerhalb des Blattes")
                continue
            original = sheet.crop((x, y, x + width, y + height))
            if entry["baseline_pixels_sha256"] != _pixel_digest(original):
                problems.append(
                    f"{directory_name}/{filename}: Quellpixel wurden seit dem Export verändert"
                )
                continue
            if original.tobytes() == edited.tobytes():
                continue
            updated.paste(edited, (x, y))
            changed += 1
        missing_keys = sorted(set(current_crops) - indexed_keys)
        if missing_keys:
            problems.append(
                f"{directory_name}: Index lässt aktuelle XAML-Ausschnitte aus: {missing_keys[:8]}"
            )
        unindexed_files = sorted(
            path.name for path in directory.glob("*.png") if path.name not in indexed_files
        )
        if unindexed_files:
            problems.append(
                f"{directory_name}: nicht indizierte PNGs: {unindexed_files[:8]}"
            )
        prepared.append((sheet_name, updated, changed))
    return prepared, problems


def cmd_check(args: argparse.Namespace) -> int:
    source_root = Path(getattr(args, "from"))
    sprites, textures, build_id = _resolve_sources(args)
    prepared, problems = _inspect_edits(
        source_root,
        sprites_dir=sprites,
        texture_asset=textures,
        target_build_id=build_id,
        atlas_selector=args.atlas,
    )
    changed_total = sum(changed for _name, _image, changed in prepared)
    if problems:
        print("Abgelehnt:")
        for line in problems:
            print("  " + line)
        print("\nKein Rückbau darf beginnen, solange der Export unvollständig ist.")
        return 1
    print(
        f"UI-Export vollständig: {len(prepared)} Blätter, "
        f"{changed_total} geänderte Ausschnitte; Größen und Rechtecke stimmen."
    )
    return 0


def _verified_partial_store_hashes(
    store: Path,
    *,
    set_name: str,
    source_index: Path,
) -> dict[str, str]:
    """Validate every preserved byte before a selected-atlas store update."""

    if not store.is_dir() or store.is_symlink():
        raise UiAtlasError(
            "Partieller UI-Import braucht eine vorhandene regulaere UI-Ablage"
        )
    manifest_path = store / "store-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise UiAtlasError("Partielle UI-Ablage hat kein regulaeres store-manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise UiAtlasError("Partielles UI-Ablagenmanifest ist nicht lesbar") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version", "set", "origin", "source_export_index_sha256", "sheets"
    }:
        raise UiAtlasError("Partielles UI-Ablagenmanifest ist unvollstaendig oder erweitert")
    if (
        manifest["schema_version"] != 1
        or manifest["set"] != set_name
        or manifest["origin"] != "derived"
        or not isinstance(manifest["sheets"], list)
        or not manifest["sheets"]
    ):
        raise UiAtlasError("Partielle UI-Ablage hat einen falschen Identitaetsvertrag")
    if manifest["source_export_index_sha256"] != _sha256_file(source_index):
        raise UiAtlasError(
            "Partielle UI-Ablage stammt nicht aus dem aktuellen Exportindex"
        )

    hashes: dict[str, str] = {}
    for entry in manifest["sheets"]:
        if not isinstance(entry, dict) or set(entry) != {
            "file", "width", "height", "sha256"
        }:
            raise UiAtlasError("Partielles UI-Ablagenblatt ist unvollstaendig oder erweitert")
        filename = _flat_name(entry["file"], "UI-Blatt")
        if filename in hashes or filename not in UI_SHEET_DIMENSIONS:
            raise UiAtlasError(
                f"Partielles UI-Blatt ist doppelt oder nicht freigegeben: {filename}"
            )
        expected_hash = entry["sha256"]
        if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            raise UiAtlasError(f"Partielles UI-Blatt hat keinen gueltigen SHA-256: {filename}")
        path = store / filename
        if not path.is_file() or path.is_symlink() or _sha256_file(path) != expected_hash:
            raise UiAtlasError(
                f"Partielles UI-Blatt fehlt oder weicht vom Manifest ab: {filename}"
            )
        try:
            width, height = int(entry["width"]), int(entry["height"])
            with Image.open(path) as opened:
                opened.load()
                actual_size = opened.size
        except Exception as exc:
            raise UiAtlasError(f"Partielles UI-Blatt ist nicht lesbar: {filename}") from exc
        if (width, height) != UI_SHEET_DIMENSIONS[filename] or actual_size != (width, height):
            raise UiAtlasError(f"Partielle UI-Blattgroesse ist falsch: {filename}")
        hashes[filename] = expected_hash

    actual_entries = {path.name for path in store.iterdir()}
    expected_entries = set(hashes) | {"store-manifest.json"}
    if actual_entries != expected_entries:
        raise UiAtlasError(
            "Partielle UI-Ablage enthaelt einen anderen Dateisatz: "
            f"fehlend={sorted(expected_entries-actual_entries)}, "
            f"zusaetzlich={sorted(actual_entries-expected_entries)}"
        )
    return hashes


def cmd_import(args: argparse.Namespace) -> int:
    from stronghold_europe_de.workspace_lock import (
        WorkspaceLockError,
        exclusive_workspace_lock,
    )

    try:
        resource = f"ui-store:{args.store}" if args.store else f"ui-import:{args.out}"
        with exclusive_workspace_lock(
            PROJECT_ROOT / "work", resource, "UI-Rückbau"
        ):
            return _cmd_import_locked(args)
    except WorkspaceLockError as exc:
        raise UiAtlasError(str(exc)) from exc


def _cmd_import_locked(args: argparse.Namespace) -> int:
    source_root = Path(getattr(args, "from"))
    source_root = (
        source_root.resolve()
        if source_root.is_absolute()
        else (PROJECT_ROOT / source_root).resolve()
    )
    sprites, textures, build_id = _resolve_sources(args)
    prepared, problems = _inspect_edits(
        source_root,
        sprites_dir=sprites,
        texture_asset=textures,
        target_build_id=build_id,
        atlas_selector=args.atlas,
    )
    changed_total = sum(changed for _name, _image, changed in prepared)

    if problems:
        print("\nAbgelehnt:")
        for line in problems:
            print("  " + line)
        print(
            "\nDie Bildgroesse muss exakt der Rechteckgroesse entsprechen. Ein "
            "skaliertes Bild wuerde im Blatt fast richtig aussehen und waere "
            "spaeter kaum aufzufinden - deshalb wird es hier abgelehnt statt "
            "angepasst."
        )
        print("\nNichts geschrieben; der Rückbau ist transaktional.")
        return 1

    if not changed_total and not args.store:
        print("Nichts geaendert - kein Override geschrieben.")
        return 0
    if args.store:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.store) is None:
            raise UiAtlasError("UI-Ablagename ist kein sicherer einzelner Bezeichner")
        out_root = (
            PROJECT_ROOT / "assets" / "ui" / "derived" / args.store
        ).resolve()
        expected_parent = (PROJECT_ROOT / "assets" / "ui" / "derived").resolve()
        if out_root.parent != expected_parent:
            raise UiAtlasError("UI-Ablage verlässt assets/ui/derived")
    else:
        out_root = _project_output(args.out, "dist")
    partial_store_hashes: dict[str, str] = {}
    if args.store and args.atlas is not None:
        partial_store_hashes = _verified_partial_store_hashes(
            out_root,
            set_name=args.store,
            source_index=source_root / "index.json",
        )
    staging = _prepare_directory(out_root, args.replace)
    try:
        override_dir = staging if args.store else staging / OVERRIDE_RELATIVE
        override_dir.mkdir(parents=True, exist_ok=True)
        if args.store and out_root.is_dir():
            foreign = [
                path.name
                for path in out_root.iterdir()
                if not path.is_file()
                or (path.suffix.lower() != ".png" and path.name != "store-manifest.json")
            ]
            if foreign:
                raise UiAtlasError(f"Fremde Einträge in UI-Ablage: {foreign[:8]}")
            for existing in out_root.glob("*.png"):
                shutil.copy2(existing, override_dir / existing.name)
        for sheet_name, sheet, changed in prepared:
            destination = override_dir / sheet_name
            if args.store and destination.exists():
                destination.unlink()
            if changed:
                sheet.save(destination)
                # Decode the just-written file and compare pixel-for-pixel to
                # the in-memory result before the directory can be promoted.
                with Image.open(destination) as reopened:
                    reopened.load()
                    delivered = reopened.convert("RGBA")
                if delivered.size != sheet.size or delivered.tobytes() != sheet.tobytes():
                    raise UiAtlasError(f"PNG-Nachprüfung widerspricht Rückbau: {sheet_name}")
                print(f"  {sheet_name}: {changed} Ausschnitte ersetzt")
            elif args.store:
                print(f"  {sheet_name}: auf Original zurückgesetzt, aus Ablage entfernt")
        if partial_store_hashes:
            selected_sheets = {sheet_name for sheet_name, _sheet, _changed in prepared}
            for filename, expected_hash in partial_store_hashes.items():
                if filename in selected_sheets:
                    continue
                preserved = override_dir / filename
                if not preserved.is_file() or _sha256_file(preserved) != expected_hash:
                    raise UiAtlasError(
                        f"Ungewaehltes UI-Blatt wurde beim Staging veraendert: {filename}"
                    )
        if args.store:
            sheets_manifest = []
            for path in sorted(override_dir.glob("*.png")):
                if path.name not in UI_SHEET_DIMENSIONS:
                    raise UiAtlasError(f"Nicht freigegebenes UI-Blatt in Ablage: {path.name}")
                with Image.open(path) as opened:
                    opened.load()
                    width, height = opened.size
                if (width, height) != UI_SHEET_DIMENSIONS[path.name]:
                    raise UiAtlasError(
                        f"UI-Blatt {path.name} hat {width}x{height} statt "
                        f"{UI_SHEET_DIMENSIONS[path.name][0]}x{UI_SHEET_DIMENSIONS[path.name][1]}"
                    )
                sheets_manifest.append(
                    {
                        "file": path.name,
                        "width": width,
                        "height": height,
                        "sha256": _sha256_file(path),
                    }
                )
            (staging / "store-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "set": args.store,
                        "origin": "derived",
                        "source_export_index_sha256": _sha256_file(
                            source_root.resolve() / "index.json"
                        ),
                        "sheets": sheets_manifest,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        _commit_directory(staging, out_root, args.replace)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    print(f"\n{changed_total} Ausschnitte ersetzt, Ausgabe unter {out_root}")
    if args.store:
        print(
            "Produktionsprofil aktualisieren: python tools/ui_atlas.py "
            f"profile-add {args.store} --write"
        )
        return 0
    print()
    print("Einbauen: den Inhalt nach")
    print("  <Spielordner>/BepInEx/plugins/StrongholdEuropeDE/")
    print("kopieren. Der Extender bedient Assets/GUI/Sprites aus dem Override.")
    return 0


def _ui_store_sections(set_name: str) -> list[dict[str, object]]:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", set_name) is None:
        raise UiAtlasError("UI-Ablagename ist kein sicherer einzelner Bezeichner")
    store = (PROJECT_ROOT / "assets" / "ui" / "derived" / set_name).resolve()
    manifest_path = store / "store-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise UiAtlasError(f"UI-Ablagenmanifest ist nicht lesbar: {manifest_path}") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version", "set", "origin", "source_export_index_sha256", "sheets"
    }:
        raise UiAtlasError("UI-Ablagenmanifest ist unvollständig oder erweitert")
    if (
        manifest["schema_version"] != 1
        or manifest["set"] != set_name
        or manifest["origin"] != "derived"
        or not isinstance(manifest["sheets"], list)
    ):
        raise UiAtlasError("UI-Ablagenmanifest hat einen falschen Identitätsvertrag")
    sections: list[dict[str, object]] = []
    names: set[str] = set()
    for entry in manifest["sheets"]:
        if not isinstance(entry, dict) or set(entry) != {"file", "width", "height", "sha256"}:
            raise UiAtlasError("UI-Ablagenblatt ist unvollständig oder erweitert")
        filename = _flat_name(entry["file"], "UI-Blatt")
        if filename in names or filename not in UI_SHEET_DIMENSIONS:
            raise UiAtlasError(f"UI-Blatt ist doppelt oder nicht freigegeben: {filename}")
        names.add(filename)
        path = store / filename
        if not path.is_file() or _sha256_file(path) != entry["sha256"]:
            raise UiAtlasError(f"UI-Blatt fehlt oder weicht vom Manifest ab: {filename}")
        try:
            width, height = int(entry["width"]), int(entry["height"])
            with Image.open(path) as opened:
                opened.load()
                actual_size = opened.size
        except Exception as exc:
            raise UiAtlasError(f"UI-Blatt ist nicht lesbar: {filename}") from exc
        if (width, height) != UI_SHEET_DIMENSIONS[filename] or actual_size != (width, height):
            raise UiAtlasError(f"UI-Blattgröße ist falsch: {filename} {actual_size}")
        source = f"assets/ui/derived/{set_name}/{filename}"
        sections.append(
            {
                "source": source,
                "output": f"Override/Assets/GUI/Sprites/{filename}",
                "category": "authored_ui_atlas",
                "origin": "derived",
                "width": width,
                "height": height,
                "expected_sha256": str(entry["sha256"]),
            }
        )
    actual_files = {path.name for path in store.iterdir() if path.is_file()}
    expected_files = names | {"store-manifest.json"}
    if actual_files != expected_files:
        raise UiAtlasError(
            f"UI-Ablage enthält einen anderen Dateisatz: "
            f"fehlend={sorted(expected_files-actual_files)}, zusätzlich={sorted(actual_files-expected_files)}"
        )
    return sections


def cmd_profile_add(args: argparse.Namespace) -> int:
    from stronghold_europe_de.workspace_lock import (
        WorkspaceLockError,
        exclusive_workspace_lock,
    )

    profile_path = Path(args.profile)
    if not profile_path.is_absolute():
        profile_path = PROJECT_ROOT / profile_path
    try:
        with exclusive_workspace_lock(
            PROJECT_ROOT / "work",
            f"profile:{profile_path.resolve()}",
            f"Profil {profile_path.name}",
        ):
            sections = _ui_store_sections(args.set)
            try:
                original = profile_path.read_text(encoding="utf-8")
                profile = json.loads(original)
            except (OSError, UnicodeError, ValueError) as exc:
                raise UiAtlasError(f"Profil ist nicht lesbar: {profile_path}") from exc
            if not isinstance(profile, dict):
                raise UiAtlasError("Profil ist kein JSON-Objekt")
            current = profile.get("authored_ui_atlases", [])
            if not isinstance(current, list) or any(not isinstance(item, dict) for item in current):
                raise UiAtlasError("authored_ui_atlases ist keine Objektliste")
            prefix = f"assets/ui/derived/{args.set}/"
            retained = [item for item in current if not str(item.get("source", "")).startswith(prefix)]
            claimed_outputs = {
                str(item["output"]).casefold() for item in sections
            }
            displaced = [
                item
                for item in retained
                if str(item.get("output", "")).casefold() in claimed_outputs
            ]
            if displaced and not args.verdraengen:
                collision = sorted(str(item.get("output", "")) for item in displaced)
                raise UiAtlasError(f"Andere UI-Ablage beansprucht dieselben Blätter: {collision}")
            if displaced:
                retained = [
                    item
                    for item in retained
                    if str(item.get("output", "")).casefold() not in claimed_outputs
                ]
            profile["authored_ui_atlases"] = sorted(
                [*retained, *sections], key=lambda item: str(item.get("output", ""))
            )
            updated = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"
            print(json.dumps(sections, indent=2, ensure_ascii=False))
            if displaced:
                print(
                    "Verdraengt: "
                    + ", ".join(
                        sorted(
                            str(item.get("source", "<ohne Quelle>"))
                            for item in displaced
                        )
                    )
                )
            if not args.write:
                print("Ohne --write nur gezeigt; Profil blieb unverändert.")
                return 0
            if updated == original:
                print("Profil bereits identisch; nichts geschrieben.")
                return 0
            temporary = profile_path.with_name(profile_path.name + ".tmp")
            temporary.write_text(updated, encoding="utf-8")
            os.replace(temporary, profile_path)
            print(f"UI-Ablage {args.set} atomar in {profile_path.name} eingetragen.")
            return 0
    except WorkspaceLockError as exc:
        raise UiAtlasError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui_atlas",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sprites",
        default=None,
        help=(
            "Ordner mit den XAML-Dictionaries; Standard wird aus der "
            "fingerprint-geprüften lokalen Installation gelesen"
        ),
    )
    # Fehlte, obwohl cmd_export und cmd_import es lesen: der Export brach mit
    # AttributeError ab, bevor er das erste Blatt geschrieben hatte. Die
    # Voreinstellung ist dieselbe Datei, die der Kommentar oben beschreibt -
    # die Blaetter liegen in globalgamemanagers.assets, nicht in resources.
    parser.add_argument(
        "--textures",
        default=None,
        help=(
            "Unity-Assetdatei mit den Atlas-Blättern; Standard wird aus der "
            "fingerprint-geprüften lokalen Installation gelesen"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="Welche Blaetter gibt es, wie gross")
    listing.set_defaults(func=cmd_list)

    export = sub.add_parser("export", help="Jeden Ausschnitt als PNG herausschreiben")
    export.add_argument("--out", default="work/ui")
    export.add_argument(
        "--atlas",
        nargs="*",
        default=None,
        help="nur diese Dictionaries, ohne Endung (z.B. UI-MasterAtlas)",
    )
    export.add_argument(
        "--replace", action="store_true", help="vorhandenen Export atomar ersetzen"
    )
    export.set_defaults(func=cmd_export)

    check = sub.add_parser("check", help="Export vollständig und ohne Größenfehler prüfen")
    check.add_argument("--from", dest="from", default="work/ui")
    check.add_argument(
        "--atlas",
        nargs="+",
        default=None,
        help="nur diese Dictionaries, ohne Endung (z.B. UI-MasterAtlas)",
    )
    check.set_defaults(func=cmd_check)

    importer = sub.add_parser("import", help="Bearbeitete PNGs zurueckbauen")
    importer.add_argument("--from", dest="from", default="work/ui")
    importer.add_argument(
        "--atlas",
        nargs="+",
        default=None,
        help="nur diese Dictionaries, ohne Endung (z.B. UI-MasterAtlas)",
    )
    importer.add_argument("--out", default="dist/ui-override")
    importer.add_argument(
        "--store",
        help=(
            "statt einer losen dist-Ausgabe eine lokale, abgeleitete "
            "Produktionsablage unter assets/ui/derived/<Name> aktualisieren"
        ),
    )
    importer.add_argument(
        "--replace", action="store_true", help="vorhandene Ausgabe atomar ersetzen"
    )
    importer.set_defaults(func=cmd_import)

    profile_add = sub.add_parser(
        "profile-add", help="eine UI-Ablage digest-gepinnt ins Produktionsprofil eintragen"
    )
    profile_add.add_argument("set", help="Ablagename unter assets/ui/derived")
    profile_add.add_argument(
        "--profile", default="profiles/europe-production.json"
    )
    profile_add.add_argument(
        "--write", action="store_true", help="wirklich atomar schreiben; sonst nur zeigen"
    )
    profile_add.add_argument(
        "--verdraengen",
        action="store_true",
        help=(
            "bestehende authored_ui_atlases-Eintraege mit denselben "
            "Ausgabeblaettern ausdruecklich ersetzen"
        ),
    )
    profile_add.set_defaults(func=cmd_profile_add)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except UiAtlasError as exc:
        print(f"Abgelehnt: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
