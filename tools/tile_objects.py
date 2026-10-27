"""Compose and split editable Stronghold objects made from tile sprites.

The game stores a large building as one sprite per occupied map tile.  A flat
PNG is useful as a preview but cannot be split losslessly after editing because
tall neighbouring sprites overlap.  This tool therefore creates an OpenRaster
document (``.ora``) with one pinned layer per game tile.

Typical route::

    python tools/tile_objects.py compose work/art/tile_castle \
        --from 1193 --to 1313 --columns 11 --rows 11 \
        --out work/objects/keep-1193
    # edit work/objects/keep-1193/keep-1193.ora
    python tools/tile_objects.py check work/objects/keep-1193
    python tools/tile_objects.py split work/objects/keep-1193 \
        --out work/art-return/keep-1193
    python tools/sprites.py import work/art-return/keep-1193 \
        --set tile-castle-europe

Only plain-shader, independently loadable ``tile_*`` groups are admitted.
Output and replacement are restricted to the project's generated ``work``
tree; the game installations remain read-only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stronghold_europe_de.loader_groups import LOADER_GROUP_TABLE  # noqa: E402
from stronghold_europe_de.tile_roundtrip import (  # noqa: E402
    LAYOUTS,
    TileRoundtripError,
    compose_object,
    inspect_object,
    split_object,
    write_current_preview,
)
from stronghold_europe_de.tile_presets import (  # noqa: E402
    TilePresetError,
    load_tile_presets,
)
from stronghold_europe_de.workspace_lock import WorkspaceLockError  # noqa: E402

PRESETS = PROJECT_ROOT / "config" / "tile-object-presets.json"


def _resolve(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _generated_destination(value: str) -> Path:
    path = _resolve(value)
    work = (PROJECT_ROOT / "work").resolve()
    if path == work or not path.is_relative_to(work):
        raise TileRoundtripError(
            f"Ausgabe muss ein Unterordner von {work} sein, nicht {path}"
        )
    return path


def _group_from_export(directory: Path) -> str:
    try:
        spec = importlib.util.spec_from_file_location(
            "stronghold_europe_sprite_contract", PROJECT_ROOT / "tools" / "sprites.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("sprites.py nicht ladbar")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        index = module._load_export_index(directory, verify_mapping=True)
        module._verify_mapping_builds(module.read_mapping_document())
    except Exception as exc:
        raise TileRoundtripError(f"Sprite-Exportvertrag ist ungültig: {exc}") from exc
    group = str(index.get("group", ""))
    _validate_group(group)
    return group


def _preset_map():
    try:
        presets = load_tile_presets(PRESETS)
    except TilePresetError as exc:
        raise TileRoundtripError(str(exc)) from exc
    return {preset.id: preset for preset in presets}


def _validate_package_preset(inspected: dict) -> None:
    manifest = inspected["manifest"]
    semantic = manifest["semantic"]
    if semantic["status"] != "verified-preset":
        return
    preset = _preset_map().get(semantic["preset_id"])
    if preset is None or preset.contract_sha256 != semantic["contract_sha256"]:
        raise TileRoundtripError("Presetvertrag fehlt oder wurde seit dem Zusammensetzen geändert")
    grid = manifest["grid"]
    frame_range = manifest["frame_range"]
    actual = (
        manifest["group"], int(frame_range["from"]), int(frame_range["to"]),
        int(grid["columns"]), int(grid["rows"]), str(grid["layout"]),
    )
    expected = (
        preset.group, preset.start, preset.end, preset.columns, preset.rows, preset.layout,
    )
    if actual != expected:
        raise TileRoundtripError("Objektgeometrie widerspricht ihrem verifizierten Preset")


def cmd_presets(args: argparse.Namespace) -> int:
    presets = [preset.public_dict() for preset in _preset_map().values()]
    if args.json:
        print(json.dumps({"presets": presets}, ensure_ascii=False))
    else:
        for preset in presets:
            print(
                f"{preset['id']}: {preset['label']} — {preset['group']} "
                f"{preset['from']}..{preset['to']}, {preset['columns']}x{preset['rows']}, "
                f"{preset['layout']}"
            )
    return 0


def _validate_group(group: str) -> None:
    loader = LOADER_GROUP_TABLE.get(group)
    if not group.startswith("tile_") or loader is None:
        raise TileRoundtripError(
            f"{group!r} ist keine bekannte optische Tile-Gruppe"
        )
    if not loader.plain_shader:
        raise TileRoundtripError(
            f"{group} hat eine separate Teamfarbenmaske; der Objektweg ist "
            "dafuer noch nicht freigegeben"
        )
    if not loader.owns_its_gm_arrays:
        raise TileRoundtripError(
            f"{group} teilt seine GM-Felder mit einer anderen Gruppe und kann "
            "ueber den aktuellen Einzel-PNG-Lader nicht sicher geliefert werden"
        )


def cmd_compose(args: argparse.Namespace) -> int:
    from stronghold_europe_de.workspace_lock import exclusive_workspace_lock

    destination = _generated_destination(args.out)
    with exclusive_workspace_lock(
        PROJECT_ROOT / "work",
        f"tile-compose:{destination}",
        f"Tile-Paket {destination.name}",
    ):
        return _cmd_compose_locked(args, destination)


def _cmd_compose_locked(args: argparse.Namespace, destination: Path) -> int:
    source = _resolve(args.directory)
    group = _group_from_export(source)
    name = args.name or destination.name
    semantic_contract = None
    if args.preset:
        preset = _preset_map().get(args.preset)
        if preset is None:
            raise TileRoundtripError(f"Unbekanntes Tile-Preset: {args.preset}")
        if group != preset.group:
            raise TileRoundtripError(
                f"Preset {preset.id} verlangt {preset.group}, Export ist {group}"
            )
        values = (
            preset.start, preset.end, preset.columns, preset.rows, preset.layout
        )
        supplied = (
            args.range_from, args.range_to, args.columns, args.rows, args.layout
        )
        for given, expected, label in zip(
            supplied, values, ("--from", "--to", "--columns", "--rows", "--layout")
        ):
            if given is not None and given != expected:
                raise TileRoundtripError(
                    f"{label}={given} widerspricht Preset {preset.id} ({expected})"
                )
        start, end, columns, rows, layout = values
        semantic_contract = {
            "preset_id": preset.id,
            "contract_sha256": preset.contract_sha256,
        }
    else:
        missing = [
            label for label, value in (
                ("--from", args.range_from), ("--to", args.range_to),
                ("--columns", args.columns), ("--rows", args.rows),
            ) if value is None
        ]
        if missing:
            raise TileRoundtripError(
                "Ohne --preset fehlen Pflichtangaben: " + ", ".join(missing)
            )
        start, end, columns, rows = (
            args.range_from, args.range_to, args.columns, args.rows
        )
        layout = args.layout or "row-major"
    manifest = compose_object(
        source,
        destination,
        start=start,
        end=end,
        columns=columns,
        rows=rows,
        layout=layout,
        object_name=name,
        replace=args.replace,
        semantic_contract=semantic_contract,
    )
    print(f"Objekt {manifest['name']}: {len(manifest['layers'])} Tiles aus {group}")
    print(
        f"  Raster: {manifest['grid']['columns']}x{manifest['grid']['rows']} "
        f"({manifest['grid']['layout']})"
    )
    print(
        f"  Leinwand: {manifest['canvas']['width']}x{manifest['canvas']['height']} px"
    )
    print(f"  Bearbeiten: {destination / str(manifest['ora'])}")
    print(f"  Vorschau:   {destination / str(manifest['preview'])}")
    print()
    print(
        "Jedes benannte Tile bleibt eine eigene Ebene. Neue Malerei vor dem "
        "Rueckweg in die passende Tile-Ebene einarbeiten; zusaetzliche Ebenen "
        "werden absichtlich abgelehnt."
    )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    package = _resolve(args.package)
    inspected = inspect_object(package)
    _validate_package_preset(inspected)
    summary = inspected["summary"]
    _validate_group(str(summary["group"]))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(
            f"Objekt {summary['name']}: {summary['frame_count']} Tiles, "
            f"{summary['changed_count']} geaendert, {summary['moved_count']} verschoben"
        )
        print(
            f"  Leinwand: {summary['canvas']['width']}x{summary['canvas']['height']} px"
        )
        if summary["changed"]:
            print("  Geaendert: " + ", ".join(summary["changed"][:20]))
            if len(summary["changed"]) > 20:
                print(f"  ... und {len(summary['changed']) - 20} weitere")
        print("  Rueckweg ist verlustfrei teilbar.")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    from stronghold_europe_de.workspace_lock import exclusive_workspace_lock

    package = _resolve(args.package)
    with exclusive_workspace_lock(
        PROJECT_ROOT / "work",
        f"tile-preview:{package}",
        f"Tile-Vorschau {package.name}",
    ):
        _validate_package_preset(inspect_object(package))
        path, summary = write_current_preview(package)
    _validate_group(str(summary["group"]))
    print(
        f"Aktuelle ORA-Vorschau: {summary['frame_count']} geprüfte Tiles, "
        f"{summary['changed_count']} geändert, {summary['moved_count']} verschoben"
    )
    print(f"  {path}")
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    from stronghold_europe_de.workspace_lock import exclusive_workspace_lock

    destination = _generated_destination(args.out)
    with exclusive_workspace_lock(
        PROJECT_ROOT / "work",
        f"tile-split:{destination}",
        f"Tile-Rückweg {destination.name}",
    ):
        return _cmd_split_locked(args, destination)


def _cmd_split_locked(args: argparse.Namespace, destination: Path) -> int:
    package = _resolve(args.package)
    inspected = inspect_object(package)
    _validate_package_preset(inspected)
    _validate_group(str(inspected["summary"]["group"]))
    summary = split_object(
        package,
        destination,
        replace=args.replace,
        confirm_custom_layout=args.confirm_custom_layout,
    )
    print(
        f"{summary['frame_count']} Tile-PNGs nach {destination}; "
        f"{summary['changed_count']} davon weichen vom Paket-Ausgang ab."
    )
    print(f"Naechster Test: python tools/sprites.py check {destination}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tile_objects",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    presets = sub.add_parser("presets", help="verifizierte Objekt-Raster auflisten")
    presets.add_argument("--json", action="store_true")
    presets.set_defaults(func=cmd_presets)

    compose = sub.add_parser(
        "compose", help="einen zusammenhaengenden Frameblock als ORA zusammensetzen"
    )
    compose.add_argument("directory", help="sprites.py-Export mit index.json")
    compose.add_argument("--preset", help="verifiziertes Raster aus 'presets'")
    compose.add_argument("--from", dest="range_from", type=int)
    compose.add_argument("--to", dest="range_to", type=int)
    compose.add_argument("--columns", type=int)
    compose.add_argument("--rows", type=int)
    compose.add_argument("--layout", choices=LAYOUTS, default=None)
    compose.add_argument("--name", help="Objekt- und ORA-Name; Standard ist der Ausgabeordner")
    compose.add_argument("--out", required=True, help="neuer Paketordner unter work/")
    compose.add_argument(
        "--replace",
        action="store_true",
        help="vorhandenen Paketordner atomar ersetzen",
    )
    compose.set_defaults(func=cmd_compose)

    check = sub.add_parser("check", help="ORA-Ebenen und verlustfreien Rueckweg pruefen")
    check.add_argument("package", help="Paketordner mit object.json")
    check.add_argument("--json", action="store_true", help="Kurzbericht als JSON")
    check.set_defaults(func=cmd_check)

    preview = sub.add_parser(
        "preview", help="aktuelle geprüfte ORA-Ebenen als PNG zusammensetzen"
    )
    preview.add_argument("package", help="Paketordner mit object.json")
    preview.set_defaults(func=cmd_preview)

    split = sub.add_parser("split", help="ORA in die nativen Tile-PNGs zerlegen")
    split.add_argument("package", help="Paketordner mit object.json")
    split.add_argument("--out", required=True, help="neuer sprites.py-Arbeitsordner unter work/")
    split.add_argument(
        "--replace",
        action="store_true",
        help="vorhandenen Ausgabeordner atomar ersetzen",
    )
    split.add_argument(
        "--confirm-custom-layout",
        action="store_true",
        help="nach visueller Prüfung ein benutzerdefiniertes Raster ausdrücklich freigeben",
    )
    split.set_defaults(func=cmd_split)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (TileRoundtripError, WorkspaceLockError) as exc:
        print(f"Abgelehnt: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
