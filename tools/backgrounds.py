"""Die Vollbilder der Oberflaeche aus- und wieder einbauen.

Anders als Einheiten, Kacheln und Knoepfe liegen die grossen Bilder des Spiels
NICHT in einem Sprite-Blatt, sondern jedes als eigene Textur. Das Menue-XAML
verweist sie mit ihrem Pfad::

    <ImageBrush ImageSource="../Images/MenusBackground.png"/>

Der Script-Extender loest genau diesen Pfad ueber sein Dateiverzeichnis auf
(``GameAssetManagerAPI.TryLoadTexture``). Eine Datei unter::

    BepInEx/plugins/StrongholdEuropeDE/Override/Assets/GUI/Images/<Name>.png

ersetzt das Bild also vollstaendig - dieselbe Mechanik, mit der der Mod schon
die vier UI-Blaetter unter ``Override/Assets/GUI/Sprites/`` austauscht.

    python tools/backgrounds.py list
    python tools/backgrounds.py export --out work/hintergruende
    ... die PNGs in work/hintergruende/crusader/ uebermalen ...
    python tools/backgrounds.py check work/hintergruende/crusader
    python tools/backgrounds.py install work/hintergruende/crusader

**Groesse.** Der Extender laedt das PNG als eigene Textur; das XAML skaliert sie
auf sein Element. Ein abweichend grosses Bild wuerde also angezeigt, aber
verzerrt, sobald das Seitenverhaeltnis nicht stimmt. ``check`` verlangt deshalb
die Originalgroesse und nennt sie, wenn sie fehlt; ``--erlaube-groesse`` laesst
bewusst abweichende Masse durch.

**Qualitaet.** Ausgegeben wird verlustfrei: RGBA-PNG in voller Aufloesung, ohne
Nachbearbeitung. Die Vorlagen liegen im Spiel als BC7 bzw. RGB24 - das
Ausgabebild ist die dekodierte Fassung, mehr Bildinformation gibt es nicht.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stronghold_europe_de.config import load_config  # noqa: E402
from stronghold_europe_de.unity_inventory import (  # noqa: E402
    _import_unitypy,
    load_unity_asset,
)

# Die Blaetter der Oberflaeche stehen woanders und haben ein eigenes Werkzeug
# (tools/ui_atlas.py); hier geht es um die Vollbilder.
IMAGE_ASSET_FILE = "sharedassets1.assets"
GAME_PATH_PREFIX = "Assets/GUI/Images/"
OVERRIDE_PREFIX = "Override/Assets/GUI/Images/"
INDEX_NAME = "index.json"
SCHEMA_VERSION = 1

# Gruppen nur zur Anzeige - sie sagen, wofuer ein Bild im Spiel steht, damit man
# nicht 166 Namen einzeln nachschlagen muss.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Vollbild-Hintergruende",
        (
            "MenusBackground",
            "loading background",
            "BriefingBackground",
            "MapEditor",
            "SkirmishTrail-Background",
            "SkirmishTrail-Sands-Background",
            "HistoricalCampaign-Background",
            "HistoricalCampaignMenu-Background",
            "SandsofTimeScoreBackground",
            "victory_military_small",
        ),
    ),
    (
        "Kampagnen- und Trail-Karten",
        (
            "SkirmishTrailMap",
            "SkirmishTrailMap2",
            "SkirmishTrailMap3",
            "SkirmishSands1Map",
            "SkirmishSands2Map",
            "SkirmishSands3Map",
            "SkirmishSands4Map",
            "SkirmishSands5Map",
            "SkirmishSands6Map",
            "SkirmishSands7Map",
            "SkirmishCoop1Map",
            "SkirmishCoop2Map",
            "SkirmishCoop3Map",
            "SkirmishMasters",
            "Roadmap",
        ),
    ),
    (
        "Marken und Logos",
        ("logo1", "Partner_Logos", "ScribeUnlock"),
    ),
)
GROUP_PREFIXES: tuple[tuple[str, str], ...] = (
    ("HistoricalCampaign-Campaign", "Historische Kampagne: Kapitelbilder"),
    ("HistoricalCampaign-Map-", "Historische Kampagne: Missionskarten"),
    ("HistoricalCampaign-Drawing-", "Historische Kampagne: Zeichnungen"),
    # Am Bild nachgesehen (21.08.2026): keine Buchseiten, sondern Stoffkeile in
    # den vier Spielerfarben - rot, gelb, blau, gruen, dieselbe Falte je Farbe.
    # Da ist nichts zu europaeisieren, das ist Spielerfarbe, keine Kultur.
    ("tslice", "Stoffbahnen in Spielerfarben"),
    ("HistoricalCampaign-", "Historische Kampagne: uebriges"),
)


class BackgroundError(RuntimeError):
    """Raised when an export or an edited image cannot be trusted."""


def _group_of(name: str) -> str:
    for label, names in GROUPS:
        if name in names:
            return label
    for prefix, label in GROUP_PREFIXES:
        if name.startswith(prefix):
            return label
    return "Weitere Oberflaechenbilder"


def _data_dir(side: str) -> Path:
    config = load_config(PROJECT_ROOT / "config" / "installations.local.toml")
    if side == "crusader":
        return config.target.data_dir
    if side == "stronghold1":
        directory = config.source.data_dir
        if directory is None:
            raise BackgroundError("Stronghold 1 DE is not configured")
        return directory
    raise BackgroundError(f"Unknown game side: {side}")


def _textures(side: str) -> Iterable[tuple[Any, Any]]:
    """Yield (object, read data) for every Texture2D of the GUI image file."""

    path = (_data_dir(side) / IMAGE_ASSET_FILE).resolve()
    if not path.is_file():
        raise BackgroundError(f"Missing game asset file: {path}")
    environment = load_unity_asset(path, unitypy=_import_unitypy())
    for obj in environment.objects:
        if obj.type.name != "Texture2D":
            continue
        yield obj, obj.read()


def _entries(side: str) -> list[dict[str, Any]]:
    rows = []
    for obj, data in _textures(side):
        rows.append(
            {
                "name": str(data.m_Name),
                "width": int(data.m_Width),
                "height": int(data.m_Height),
                "texture_format": int(data.m_TextureFormat),
                "path_id": int(obj.path_id),
            }
        )
    rows.sort(key=lambda row: (-(row["width"] * row["height"]), row["name"]))
    gc.collect()
    return rows


def _safe_file_name(name: str) -> str:
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise BackgroundError(f"Unsafe texture name: {name!r}")
    return f"{name}.png"


def command_list(args: argparse.Namespace) -> int:
    rows = _entries(args.game)
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_group_of(row["name"]), []).append(row)
    for label in sorted(groups, key=lambda key: (-len(groups[key]), key)):
        print(f"\n{label}  ({len(groups[label])})")
        for row in groups[label]:
            print(f"  {row['name']:46s} {row['width']:5d} x {row['height']:<5d}")
    print(f"\n{len(rows)} Bilder in {args.game}/{IMAGE_ASSET_FILE}")
    return 0


def command_export(args: argparse.Namespace) -> int:
    out_root = Path(args.out)
    target = out_root / args.game
    if target.exists() and not args.replace:
        raise BackgroundError(
            f"{target} exists; pass --replace to overwrite it deliberately"
        )
    staging = out_root / f".{args.game}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    frames: list[dict[str, Any]] = []
    written = 0
    for obj, data in _textures(args.game):
        name = str(data.m_Name)
        if args.only and not any(part.lower() in name.lower() for part in args.only):
            continue
        image = data.image.convert("RGBA")
        file_name = _safe_file_name(name)
        image.save(staging / file_name, format="PNG", compress_level=6)
        payload = (staging / file_name).read_bytes()
        frames.append(
            {
                "name": name,
                "file": file_name,
                "width": int(image.width),
                "height": int(image.height),
                "source_texture_format": int(data.m_TextureFormat),
                "path_id": int(obj.path_id),
                "group": _group_of(name),
                "game_path": f"{GAME_PATH_PREFIX}{file_name}",
                "override_path": f"{OVERRIDE_PREFIX}{file_name}",
                "exported_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        written += 1
        print(f"  {name:46s} {image.width:5d} x {image.height:<5d}", flush=True)
        del image
        gc.collect()

    frames.sort(key=lambda row: (-(row["width"] * row["height"]), row["name"]))
    index = {
        "schema_version": SCHEMA_VERSION,
        "game": args.game,
        "asset_file": IMAGE_ASSET_FILE,
        "game_path_prefix": GAME_PATH_PREFIX,
        "override_prefix": OVERRIDE_PREFIX,
        "frames": frames,
    }
    (staging / INDEX_NAME).write_text(
        json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    print(f"\n{written} Bilder nach {target}")
    print(f"Pruefen:  python tools/backgrounds.py check {target}")
    return 0


def _load_index(directory: Path) -> dict[str, Any]:
    index_path = directory / INDEX_NAME
    if not index_path.is_file():
        raise BackgroundError(f"No {INDEX_NAME} in {directory}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("schema_version") != SCHEMA_VERSION:
        raise BackgroundError("Unsupported index schema")
    return index


def _checked_files(
    directory: Path, allow_size: bool
) -> tuple[list[tuple[dict[str, Any], Path]], list[str]]:
    from PIL import Image

    index = _load_index(directory)
    ready: list[tuple[dict[str, Any], Path]] = []
    problems: list[str] = []
    for frame in index["frames"]:
        path = directory / str(frame["file"])
        if not path.is_file():
            problems.append(f"fehlt: {frame['file']}")
            continue
        try:
            with Image.open(path) as opened:
                opened.load()
                size = opened.size
                opened.convert("RGBA")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"unlesbar: {frame['file']} ({exc})")
            continue
        expected = (int(frame["width"]), int(frame["height"]))
        if size != expected and not allow_size:
            problems.append(
                f"Groesse: {frame['file']} ist {size[0]}x{size[1]}, "
                f"gebraucht wird {expected[0]}x{expected[1]}"
            )
            continue
        ready.append((frame, path))
    return ready, problems


def command_check(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    ready, problems = _checked_files(directory, args.erlaube_groesse)
    index = _load_index(directory)
    changed = [
        frame["file"]
        for frame, path in ready
        if hashlib.sha256(path.read_bytes()).hexdigest() != frame["exported_sha256"]
    ]
    print(f"{len(ready)} von {len(index['frames'])} Bildern in Ordnung")
    print(f"{len(changed)} davon gegenueber dem Export veraendert (das sind deine)")
    for problem in problems:
        print(f"  FEHLER {problem}")
    return 1 if problems else 0


def command_install(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    ready, problems = _checked_files(directory, args.erlaube_groesse)
    if problems:
        for problem in problems:
            print(f"  FEHLER {problem}")
        raise BackgroundError("Nicht installiert - erst die Fehler oben beheben")
    index = _load_index(directory)
    config = load_config(PROJECT_ROOT / "config" / "installations.local.toml")
    if config.target.game_dir is None:
        raise BackgroundError("Target game directory is not configured")
    mod_root = (
        config.target.game_dir
        / "BepInEx"
        / "plugins"
        / config.output.mod_folder_name
    ).resolve()
    if not mod_root.is_dir():
        raise BackgroundError(f"Mod is not installed at {mod_root}")
    destination = (mod_root / Path(OVERRIDE_PREFIX)).resolve()
    if mod_root not in destination.parents and destination != mod_root:
        raise BackgroundError("Install destination escaped the mod folder")

    installed = 0
    for frame, path in ready:
        if args.nur_geaenderte and (
            hashlib.sha256(path.read_bytes()).hexdigest() == frame["exported_sha256"]
        ):
            continue
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination / str(frame["file"]))
        installed += 1
        print(f"  {frame['file']}")
    print(f"\n{installed} Bilder nach {destination}")
    print(f"({len(index['frames']) - installed} unveraendert uebersprungen)"
          if args.nur_geaenderte else "")
    print("Das Spiel liest sie beim naechsten Start.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backgrounds", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="alle Vollbilder mit Groesse auflisten")
    listing.add_argument("--game", choices=("crusader", "stronghold1"), default="crusader")
    listing.set_defaults(func=command_list)

    export = sub.add_parser("export", help="alle Vollbilder als PNG schreiben")
    export.add_argument("--game", choices=("crusader", "stronghold1"), default="crusader")
    export.add_argument("--out", default="work/hintergruende")
    export.add_argument("--only", nargs="*", default=None, help="Namensteile filtern")
    export.add_argument("--replace", action="store_true")
    export.set_defaults(func=command_export)

    check = sub.add_parser("check", help="bearbeitete PNGs pruefen")
    check.add_argument("directory")
    check.add_argument("--erlaube-groesse", action="store_true")
    check.set_defaults(func=command_check)

    install = sub.add_parser("install", help="gepruefte PNGs in die Installation legen")
    install.add_argument("directory")
    install.add_argument("--erlaube-groesse", action="store_true")
    install.add_argument("--nur-geaenderte", action="store_true", default=True)
    install.add_argument(
        "--alle", dest="nur_geaenderte", action="store_false",
        help="auch unveraenderte Bilder kopieren",
    )
    install.set_defaults(func=command_install)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return int(args.func(args))
    except BackgroundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
