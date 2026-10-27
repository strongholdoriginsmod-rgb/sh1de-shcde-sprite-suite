"""Export game sprites as ordinary PNGs, and bring hand-drawn ones back.

Every visible object in the game is a frame in a sprite group. This exports any
group as one PNG per frame plus a machine-readable index, so the art can be
edited in any image program, and imports edited frames back into a shape the
builder can ship.

    python tools/sprites.py list
    python tools/sprites.py export body_gate --out work/art
    ... edit work/art/body_gate/*.png ...
    python tools/sprites.py check work/art/body_gate
    python tools/sprites.py import work/art/body_gate --set body-gate-europe

Three things about the format are worth knowing before drawing anything.

**Size is not free.** Each frame occupies a slot whose geometry the game reads
from the atlas we ship. The current delivery route therefore accepts exactly
the exported Crusader canvas. The index records the original pivot for every
frame; `check` verifies geometry and pixels against that contract.

**The team mask is a second image.** Groups whose mask policy is `required`
carry a parallel mask that tells the engine which pixels take the player's
colour. Those export as `<name>_m.png`. Editing the colour image without the
mask leaves banners and shields tinted along the old outline.

**The foot point is not free on the delivery route.** Measured in the extender's
own code, not assumed: `GameSpriteManagerAPI.CreateReplacementSprite` divides
the Crusader sprite's pivot by the Crusader rect and hands that *normalised*
fraction to `Sprite.Create` over the full new texture. Any image size is
accepted, but the frame always ends up sitting at

    (pivot_x * own width, pivot_y * own height)

counted from the left and from **below** - Unity's order, the opposite of
Pillow's row order. A frame drawn on a different canvas therefore keeps its old
*relative* anchor and slides on its tile while looking almost right. `import`
consequently accepts only the Crusader canvas and names the size that would fit.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stronghold_europe_de.gm_atlas import (  # noqa: E402
    LOADER_139_GROUPS,
    parse_loader_frame_name,
)
from stronghold_europe_de.hashing import sha256_file  # noqa: E402
from stronghold_europe_de.loader_groups import LOADER_GROUP_TABLE  # noqa: E402

MAPPING = PROJECT_ROOT / "work" / "mapping" / "proposals.json.gz"
UNSAFE = re.compile(r'[<>:"/\\|?*]')

CONFIG = "config/installations.local.toml"
EXPORT_INDEX_SCHEMA = 1
_HEX_256 = re.compile(r"^[0-9a-f]{64}$")


def game_assets(game: str) -> Path:
    """Return the resources.assets of one game, as configured.

    The paths used to stand here as literals. That was wrong twice over: it
    broke the moment an installation moved, and it bypassed the one file that
    decides which directories this project is allowed to read at all.
    """
    from stronghold_europe_de.config import load_config

    config = load_config(PROJECT_ROOT / CONFIG)
    data_dir = config.source.data_dir if game == "stronghold1" else config.target.data_dir
    return data_dir / "resources.assets"


def read_mapping_document() -> dict[str, Any]:
    """Read the pinned mapping and reject ambiguous frame identities."""

    try:
        with gzip.open(MAPPING, "rt", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Mapping ist nicht lesbar: {MAPPING}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 2:
        raise ValueError("Mapping hat nicht das unterstützte Schema 2")
    if not isinstance(document.get("source_build_id"), str) or not isinstance(
        document.get("target_build_id"), str
    ):
        raise ValueError("Mapping trägt keine eindeutigen Build-IDs")
    rows = document.get("sprites")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Mapping enthält keine gültige Sprite-Liste")
    identities: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        group = row.get("group")
        name = row.get("name")
        if not isinstance(group, str) or not group or not isinstance(name, str) or not name:
            raise ValueError(f"Mapping-Frame {index} hat keine eindeutige Gruppe/Name")
        identity = (group, name)
        if identity in identities:
            raise ValueError(f"Doppelter Mapping-Frame: {group}/{name}")
        identities.add(identity)
        for side in ("source", "target"):
            meta = row.get(side)
            if meta is None:
                continue
            if not isinstance(meta, dict):
                raise ValueError(f"{group}/{name}: {side} ist kein Objekt")
            required = {
                "path_id", "texture_name", "width", "height",
                "pivot_x", "pivot_y", "pixels_per_unit",
            }
            if not required <= set(meta):
                raise ValueError(
                    f"{group}/{name}: {side} unvollständig: {sorted(required - set(meta))}"
                )
    return document


def read_mapping() -> list[dict]:
    return read_mapping_document()["sprites"]


def _load_config():
    from stronghold_europe_de.config import load_config

    return load_config(PROJECT_ROOT / CONFIG)


def _verify_mapping_builds(document: Mapping[str, Any]):
    """Prove that mapping metadata describes the two configured installs."""

    from stronghold_europe_de.builds import verify_supported_builds

    config = _load_config()
    match = verify_supported_builds(
        config, PROJECT_ROOT / "config" / "supported-builds.json"
    )
    if document.get("source_build_id") != match.source_id:
        raise ValueError("Mapping gehört nicht zum konfigurierten SH1DE-Build")
    if document.get("target_build_id") != match.target_id:
        raise ValueError("Mapping gehört nicht zum konfigurierten SHCDE-Build")
    return config, match


def _safe_flat_png(value: object, label: str) -> str:
    text = str(value)
    path = Path(text)
    if (
        not text
        or path.name != text
        or path.suffix.lower() != ".png"
        or text in {".", ".."}
    ):
        raise ValueError(f"{label} ist kein sicherer flacher PNG-Name: {value!r}")
    return text


def _sha256_text(value: object, label: str) -> str:
    text = str(value).lower()
    if _HEX_256.fullmatch(text) is None:
        raise ValueError(f"{label} ist kein SHA-256")
    return text


def _load_export_index(directory: Path, *, verify_mapping: bool) -> dict[str, Any]:
    """Load the round-trip contract without trusting paths from JSON."""

    index_path = directory / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"index.json ist nicht lesbar: {index_path}") from exc
    if not isinstance(index, dict) or index.get("schema_version") != EXPORT_INDEX_SCHEMA:
        raise ValueError(f"index.json benötigt Schema {EXPORT_INDEX_SCHEMA}")
    allowed_top = {
        "schema_version", "group", "game", "frame_range", "frames",
        "source_build_id", "target_build_id", "mapping_sha256",
        "installed_profile_id", "installed_build_manifest_sha256",
    }
    required_top = {
        "schema_version", "group", "game", "frame_range", "frames",
        "source_build_id", "target_build_id", "mapping_sha256",
    }
    if not required_top <= set(index):
        raise ValueError(
            f"index.json ist unvollständig: {sorted(required_top - set(index))}"
        )
    if set(index) - allowed_top:
        raise ValueError(f"index.json enthält unbekannte Felder: {sorted(set(index) - allowed_top)}")
    group = index.get("group")
    if not isinstance(group, str) or group not in LOADER_GROUP_TABLE:
        raise ValueError(f"Unbekannte oder nicht ladbare Gruppe im Index: {group!r}")
    game = index.get("game")
    if game not in {"delivered", "crusader", "stronghold1"}:
        raise ValueError("index.json enthält keine gültige Exportquelle")
    frame_range = index.get("frame_range")
    if not isinstance(frame_range, dict) or set(frame_range) != {"from", "to"}:
        raise ValueError("index.json.frame_range muss exakt from/to enthalten")
    for key in ("from", "to"):
        value = frame_range[key]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ValueError(f"index.json.frame_range.{key} ist ungültig")
    if (
        frame_range["from"] is not None
        and frame_range["to"] is not None
        and frame_range["from"] > frame_range["to"]
    ):
        raise ValueError("index.json.frame_range ist umgekehrt")
    if game == "delivered":
        if not isinstance(index.get("installed_profile_id"), str) or not index[
            "installed_profile_id"
        ]:
            raise ValueError("Installierter Export trägt keine Profil-ID")
        _sha256_text(
            index.get("installed_build_manifest_sha256"),
            "installed_build_manifest_sha256",
        )
    elif (
        "installed_profile_id" in index
        or "installed_build_manifest_sha256" in index
    ):
        raise ValueError("Rohspiel-Export darf keinen Installationsbezug tragen")
    _sha256_text(index.get("mapping_sha256"), "mapping_sha256")
    if not isinstance(index.get("source_build_id"), str) or not isinstance(
        index.get("target_build_id"), str
    ):
        raise ValueError("index.json trägt keine Build-IDs")
    frames = index.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("index.json enthält keine Frames")
    loader = LOADER_GROUP_TABLE[group]
    names: set[str] = set()
    files: set[str] = set()
    masks: set[str] = set()
    for position, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise ValueError(f"frames[{position}] ist kein Objekt")
        required = {
            "name", "file", "width", "height", "pixels_sha256",
            "shown_from", "effective", "crusader",
        }
        if not required <= set(frame):
            raise ValueError(f"frames[{position}] ist unvollständig: {sorted(required - set(frame))}")
        allowed_frame = required | {
            "mask_file", "mask_pixels_sha256", "stronghold1",
        }
        if set(frame) - allowed_frame:
            raise ValueError(
                f"frames[{position}] enthält unbekannte Felder: "
                f"{sorted(set(frame) - allowed_frame)}"
            )
        name = frame.get("name")
        slot = (
            parse_loader_frame_name(name, group, loader.dash_format)
            if isinstance(name, str)
            else None
        )
        if slot is None or name in names:
            raise ValueError(f"Leerer, fremder oder doppelter Framename: {name!r}")
        if (
            frame_range["from"] is not None
            and slot.index < frame_range["from"]
        ) or (
            frame_range["to"] is not None
            and slot.index > frame_range["to"]
        ):
            raise ValueError(f"{name}: liegt außerhalb von frame_range")
        names.add(name)
        filename = _safe_flat_png(frame.get("file"), f"{name}.file")
        if filename != UNSAFE.sub("_", name) + ".png" or filename in files:
            raise ValueError(f"Nicht-kanonischer oder doppelter Dateiname: {filename}")
        files.add(filename)
        width, height = frame.get("width"), frame.get("height")
        if isinstance(width, bool) or isinstance(height, bool) or not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            raise ValueError(f"Ungültige Bildgröße für {name}")
        _sha256_text(frame.get("pixels_sha256"), f"{name}.pixels_sha256")
        if frame.get("shown_from") not in {
            "crusader", "stronghold1", "installed-atlas", "installed-sprite"
        }:
            raise ValueError(f"{name}: unbekannte wirksame Quelle")
        effective = frame.get("effective")
        if not isinstance(effective, dict) or set(effective) != {
            "pivot_x", "pivot_y", "pixels_per_unit"
        }:
            raise ValueError(f"{name}.effective ist unvollständig oder erweitert")
        for key, value in effective.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{name}.effective.{key} ist keine endliche Zahl")
        mask_name = frame.get("mask_file")
        mask_digest = frame.get("mask_pixels_sha256")
        if loader.plain_shader:
            if mask_name is not None or mask_digest is not None:
                raise ValueError(f"{name}: Plain-Shader darf keine Maske tragen")
        else:
            expected_mask = Path(filename).with_suffix("").name + "_m.png"
            actual_mask = _safe_flat_png(mask_name, f"{name}.mask_file")
            if actual_mask != expected_mask or actual_mask in masks:
                raise ValueError(f"Nicht-kanonische oder doppelte Maske: {actual_mask}")
            masks.add(actual_mask)
            _sha256_text(mask_digest, f"{name}.mask_pixels_sha256")
        for meta_name in ("crusader", "stronghold1"):
            meta = frame.get(meta_name)
            if meta is None:
                continue
            if not isinstance(meta, dict):
                raise ValueError(f"{name}.{meta_name} ist kein Objekt")
            for key in ("width", "height", "pivot_x", "pivot_y", "pixels_per_unit", "texture"):
                if key not in meta:
                    raise ValueError(f"{name}.{meta_name}.{key} fehlt")
            if set(meta) != {"width", "height", "pivot_x", "pivot_y", "pixels_per_unit", "texture"}:
                raise ValueError(f"{name}.{meta_name} enthält unbekannte Felder")
            if not isinstance(meta["texture"], str) or not meta["texture"]:
                raise ValueError(f"{name}.{meta_name}.texture ist leer")
            for key in ("width", "height", "pivot_x", "pivot_y", "pixels_per_unit"):
                value = meta[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError(f"{name}.{meta_name}.{key} ist keine endliche Zahl")
    if verify_mapping:
        mapping = read_mapping_document()
        if sha256_file(MAPPING) != index["mapping_sha256"]:
            raise ValueError("Export und aktuelle Mapping-Datei unterscheiden sich")
        if index["source_build_id"] != mapping["source_build_id"] or index["target_build_id"] != mapping["target_build_id"]:
            raise ValueError("Export und aktuelle Mapping-Build-IDs unterscheiden sich")
        rows_by_name = {
            str(row["name"]): row
            for row in mapping["sprites"]
            if row.get("group") == group
        }
        known = set(rows_by_name)
        if not names <= known:
            raise ValueError(f"Index enthält Frames außerhalb der aktuellen Mapping: {sorted(names - known)[:8]}")
        for frame in frames:
            row = rows_by_name[str(frame["name"])]
            for side, label in (("target", "crusader"), ("source", "stronghold1")):
                mapped = row.get(side)
                indexed = frame.get(label)
                if mapped is None:
                    if indexed is not None:
                        raise ValueError(f"{frame['name']}: erfundene {label}-Metadaten")
                    continue
                expected_meta = {
                    "width": int(float(mapped["width"])),
                    "height": int(float(mapped["height"])),
                    "pivot_x": float(mapped["pivot_x"]),
                    "pivot_y": float(mapped["pivot_y"]),
                    "pixels_per_unit": float(mapped["pixels_per_unit"]),
                    "texture": str(mapped["texture_name"]),
                }
                if indexed != expected_meta:
                    raise ValueError(
                        f"{frame['name']}: {label}-Geometrie wurde gegenüber der Mapping verändert"
                    )
    return index


def _frame_number(name: object) -> int | None:
    """Return the trailing Stronghold frame number, if the name carries one."""

    match = re.search(r"(\d+)\s*$", str(name))
    return int(match.group(1)) if match else None


def _select_export_range(
    rows: list[dict], range_from: int | None, range_to: int | None
) -> list[dict]:
    """Select an inclusive numeric frame interval without changing its metadata."""

    if range_from is not None and range_to is not None and range_from > range_to:
        raise ValueError(f"ungueltiger Framebereich: {range_from} bis {range_to}")
    if range_from is None and range_to is None:
        return rows
    selected: list[dict] = []
    for row in rows:
        number = _frame_number(row.get("name"))
        if number is None:
            continue
        if range_from is not None and number < range_from:
            continue
        if range_to is not None and number > range_to:
            continue
        selected.append(row)
    return selected


def cmd_list(args: argparse.Namespace) -> int:
    rows = read_mapping()
    counts: dict[str, int] = {}
    for row in rows:
        group = str(row.get("group"))
        counts[group] = counts.get(group, 0) + 1
    wanted = sorted(counts) if args.all else sorted(set(LOADER_139_GROUPS) & set(counts))
    if args.json:
        # Fuer die Suite: sie soll nur anzeigen, was dieses Werkzeug berechnet,
        # statt die Texttabelle zu zerlegen oder selbst zu rechnen. Die
        # Freigaben stehen mit dabei, weil die Ablage-Auswahl der Oberflaeche
        # sonst eine zweite Kopie der Erlaubnisliste braeuchte.
        from stronghold_europe_de.mod_builder import _PROJECT_AUTHORED_SPRITE_SETS

        groups = []
        for name in wanted:
            entry = LOADER_GROUP_TABLE.get(name)
            groups.append(
                {
                    "group": name,
                    "frames": counts[name],
                    "mask_required": None if entry is None else not entry.plain_shader,
                    "loadable": (
                        "nein"
                        if entry is None
                        else ("ja" if entry.owns_its_gm_arrays else "geteilt")
                    ),
                }
            )
        stores = [
            {
                "store": store,
                "set": store.rsplit("/", 1)[-1],
                "origin": origin,
                "group": group,
            }
            for store, (group, origin) in sorted(
                _PROJECT_AUTHORED_SPRITE_SETS.items()
            )
        ]
        print(json.dumps({"groups": groups, "stores": stores}, ensure_ascii=False))
        return 0
    print(f"{'Gruppe':<30} {'Frames':>7}  {'Maske':<10} Ladbar")
    for name in wanted:
        entry = LOADER_GROUP_TABLE.get(name)
        mask = "-"
        loadable = "nein"
        if entry is not None:
            mask = "nein" if entry.plain_shader else "ja"
            loadable = "ja" if entry.owns_its_gm_arrays else "geteilt"
        print(f"{name:<30} {counts[name]:>7}  {mask:<10} {loadable}")
    print(f"\n{len(wanted)} Gruppen")
    return 0


def _extract_raw_frames(
    rows: Sequence[dict[str, Any]],
    *,
    side: str,
    game: str,
    mask_required: bool,
):
    """Extract exactly the requested side from its verified Unity archive."""

    import UnityPy
    from stronghold_europe_de.installed_art import InstalledFrame
    from stronghold_europe_de.mod_builder import _crop_mask_for_sprite, _texture_objects

    asset = game_assets(game)
    if not asset.is_file():
        raise ValueError(f"Spieldaten fehlen: {asset}")
    wanted: dict[int, dict[str, Any]] = {}
    for row in rows:
        meta = row.get(side)
        if meta is None:
            continue
        path_id = int(meta["path_id"])
        if path_id in wanted:
            raise ValueError(f"Doppelte Sprite-PathID auf {side}: {path_id}")
        wanted[path_id] = row
    if not wanted:
        return {}
    print(f"{len(wanted)} Frames aus {game} ({asset.name}) ...")
    environment = UnityPy.load(str(asset))
    by_id, textures, texture_trees = _texture_objects(environment)
    decoded_masks: dict[str, object] = {}
    result = {}
    for path_id, row in wanted.items():
        name = str(row["name"])
        obj = by_id.get(path_id)
        if obj is None or obj.type.name != "Sprite":
            raise ValueError(f"Sprite PathID fehlt: {path_id} ({name})")
        sprite = obj.read()
        image = sprite.image.convert("RGBA")
        frame_mask = None
        if mask_required:
            atlas_name = str(row[side]["texture_name"])
            mask_name = atlas_name + "_m"
            mask_obj = textures.get(mask_name)
            if mask_obj is None:
                raise ValueError(f"Teamfarbenatlas fehlt: {mask_name}")
            if atlas_name not in texture_trees:
                raise ValueError(f"Hauptatlas-Metadaten fehlen: {atlas_name}")
            if mask_name not in decoded_masks:
                decoded_masks[mask_name] = mask_obj.read().image.convert("RGBA")
            frame_mask = _crop_mask_for_sprite(
                decoded_masks[mask_name],
                texture_trees[atlas_name],
                obj.read_typetree(),
                image.size,
                require_native_size=True,
            )
        meta = row[side]
        result[name] = InstalledFrame(
            name=name,
            image=image,
            mask=frame_mask,
            pivot_x=float(meta["pivot_x"]),
            pivot_y=float(meta["pivot_y"]),
            pixels_per_unit=float(meta["pixels_per_unit"]),
            origin=game,
        )
    return result


def _export_entry(
    working_dir: Path,
    row: Mapping[str, Any],
    frame,
    *,
    mask_required: bool,
) -> dict[str, Any]:
    """Write one proven frame and return its strict index record."""

    name = str(row["name"])
    filename = UNSAFE.sub("_", name) + ".png"
    image = frame.image.convert("RGBA")
    image.save(working_dir / filename)
    entry: dict[str, Any] = {
        "name": name,
        "file": filename,
        "width": image.width,
        "height": image.height,
        "pixels_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "shown_from": frame.origin,
        "effective": {
            "pivot_x": float(frame.pivot_x),
            "pivot_y": float(frame.pivot_y),
            "pixels_per_unit": float(frame.pixels_per_unit),
        },
    }
    if mask_required:
        if frame.mask is None:
            raise ValueError(f"Installierter/roher Frame hat keine Pflichtmaske: {name}")
        mask = frame.mask.convert("RGBA")
        if mask.size != image.size:
            raise ValueError(f"Teammaske hat für {name} eine andere Größe")
        mask_filename = Path(filename).with_suffix("").name + "_m.png"
        mask.save(working_dir / mask_filename)
        entry["mask_file"] = mask_filename
        entry["mask_pixels_sha256"] = hashlib.sha256(mask.tobytes()).hexdigest()
    for meta_side, meta_game in (("target", "crusader"), ("source", "stronghold1")):
        meta = row.get(meta_side)
        if meta is None:
            continue
        entry[meta_game] = {
            "width": int(float(meta["width"])),
            "height": int(float(meta["height"])),
            "pivot_x": float(meta["pivot_x"]),
            "pivot_y": float(meta["pivot_y"]),
            "pixels_per_unit": float(meta["pixels_per_unit"]),
            "texture": str(meta["texture_name"]),
        }
    return entry


def cmd_export(args: argparse.Namespace) -> int:
    from stronghold_europe_de.workspace_lock import (
        WorkspaceLockError,
        exclusive_workspace_lock,
    )

    out = Path(args.out)
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    resource = f"sprite-export:{(out / args.group).resolve()}"
    try:
        with exclusive_workspace_lock(
            PROJECT_ROOT / "work", resource, f"Sprite-Export {args.group}"
        ):
            return _cmd_export_locked(args)
    except WorkspaceLockError as exc:
        print(f"Export abgelehnt: {exc}")
        return 1


def _cmd_export_locked(args: argparse.Namespace) -> int:
    from stronghold_europe_de.installed_art import (
        InstalledArtError,
        InstalledFrame,
        installed_group_frames,
        reject_other_override_plugins,
        verify_installed_mod,
    )

    group = args.group
    try:
        mapping = read_mapping_document()
    except ValueError as exc:
        print(f"Abgelehnt: {exc}")
        return 1
    group_rows = [row for row in mapping["sprites"] if row.get("group") == group]
    if not group_rows:
        print(f"Keine Frames fuer {group}. 'list' zeigt die verfuegbaren Gruppen.")
        return 1
    try:
        rows = _select_export_range(group_rows, args.range_from, args.range_to)
    except ValueError as exc:
        print(f"Abgelehnt: {exc}")
        return 1
    if not rows:
        print(
            f"Keine Frames fuer {group} im Bereich "
            f"{args.range_from if args.range_from is not None else 'Anfang'} bis "
            f"{args.range_to if args.range_to is not None else 'Ende'}."
        )
        return 1

    out = Path(args.out)
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    target_dir = out / group
    out.mkdir(parents=True, exist_ok=True)
    if target_dir.exists() and any(target_dir.iterdir()) and not args.replace:
        print(f"Exportordner ist nicht leer: {target_dir}")
        print(
            "Nichts ueberschrieben. Bearbeitete PNGs erst zurueckfuehren oder "
            "den Export mit --replace ausdruecklich atomar ersetzen."
        )
        return 1
    backup = target_dir.with_name(target_dir.name + ".sprites-export-backup")
    if backup.exists():
        print(f"Eine alte Export-Sicherung blockiert den Lauf: {backup}")
        return 1

    try:
        config, _match = _verify_mapping_builds(mapping)
    except Exception as exc:
        print(f"Abgelehnt: Build-/Mapping-Prüfung fehlgeschlagen: {exc}")
        return 1

    working_dir = Path(
        tempfile.mkdtemp(prefix=f".{group}.sprites-export-", dir=out)
    )

    loader = LOADER_GROUP_TABLE.get(group)
    if loader is None:
        print(f"{group} ist keine unterstützte Ladergruppe.")
        shutil.rmtree(working_dir)
        return 1
    mask_required = loader is not None and not loader.plain_shader
    entries: dict[str, dict[str, Any]] = {}
    installed_manifest_digest = None
    installed_profile_id = None
    try:
        if args.game == "delivered":
            # This is intentionally not reconstructed from mapping decisions.
            # It reads the fully hashed managed install, applies the loader's
            # atlas-then-direct-sprite precedence, and uses raw Crusader only
            # where that install has no override.
            mod = verify_installed_mod(config)
            reject_other_override_plugins(
                config, group, [str(row["name"]) for row in rows]
            )
            expected_names = [
                str(row["name"]) for row in group_rows if row.get("target") is not None
            ]
            overrides = installed_group_frames(mod, group, expected_names) or {}
            fallback_rows = [row for row in rows if str(row["name"]) not in overrides]
            frames = _extract_raw_frames(
                fallback_rows, side="target", game="crusader", mask_required=mask_required
            )
            frames.update(overrides)
            installed_manifest_digest = sha256_file(mod.root / "build-manifest.json")
            installed_profile_id = str(mod.build_manifest.get("profile_id", ""))
            for row in rows:
                name = str(row["name"])
                frame = frames.get(name)
                if frame is None:
                    raise ValueError(f"Kein wirksamer installierter Frame: {name}")
                if frame.origin == "installed-sprite":
                    target = row.get("target")
                    if not isinstance(target, dict):
                        raise ValueError(f"Einzeloverride ohne Zielgeometrie: {name}")
                    frame = InstalledFrame(
                        name=frame.name,
                        image=frame.image,
                        mask=frame.mask,
                        pivot_x=frame.pivot_x,
                        pivot_y=frame.pivot_y,
                        pixels_per_unit=float(target["pixels_per_unit"]),
                        origin=frame.origin,
                    )
                entries[name] = _export_entry(
                    working_dir, row, frame, mask_required=mask_required
                )
        else:
            side = "source" if args.game == "stronghold1" else "target"
            expected_rows = [row for row in rows if row.get(side) is not None]
            frames = _extract_raw_frames(
                expected_rows, side=side, game=args.game, mask_required=mask_required
            )
            for row in expected_rows:
                name = str(row["name"])
                entries[name] = _export_entry(
                    working_dir, row, frames[name], mask_required=mask_required
                )
    except (InstalledArtError, OSError, RuntimeError, ValueError) as exc:
        print(f"Export abgelehnt: {exc}")
        shutil.rmtree(working_dir)
        return 1

    expected = {
        str(row["name"])
        for row in rows
        if row.get("source" if args.game == "stronghold1" else "target") is not None
    }
    missing_names = sorted(expected - set(entries))
    if missing_names:
        print(f"Export unvollständig; fehlend: {missing_names[:20]}")
        shutil.rmtree(working_dir)
        return 1

    written = len(entries)
    ordered = [entries[name] for name in sorted(entries)]
    index: dict[str, Any] = {
        "schema_version": EXPORT_INDEX_SCHEMA,
        "group": group,
        "game": args.game,
        "frame_range": {"from": args.range_from, "to": args.range_to},
        "source_build_id": mapping["source_build_id"],
        "target_build_id": mapping["target_build_id"],
        "mapping_sha256": sha256_file(MAPPING),
        "frames": ordered,
    }
    if installed_manifest_digest is not None:
        index["installed_profile_id"] = installed_profile_id
        index["installed_build_manifest_sha256"] = installed_manifest_digest
    (working_dir / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    try:
        if target_dir.exists():
            os.replace(target_dir, backup)
        os.replace(working_dir, target_dir)
    except Exception:
        if target_dir.exists() and backup.exists():
            shutil.rmtree(target_dir)
        if backup.exists() and not target_dir.exists():
            os.replace(backup, target_dir)
        if working_dir.exists():
            shutil.rmtree(working_dir)
        raise
    if backup.exists():
        shutil.rmtree(backup)
    mask_count = sum("mask_file" in entry for entry in entries.values())
    print(
        f"{written} Farbbilder"
        + (f" und {mask_count} Teamfarbenmasken" if mask_count else "")
        + f" nach {target_dir}"
    )
    if mask_required:
        print()
        print("Diese Gruppe trägt eine Teammaske. Zu jedem Farbbild wurde die")
        print("passende native _m.png als sichtbare Bearbeitungsvorlage exportiert.")
    print()
    print(f"Pruefen:  python tools/sprites.py check {out}/{group}")
    return 0


def _frame_order(entry: dict) -> tuple:
    """Sort by the trailing number, not by the string.

    Frame names are ``<group> <n>`` with three-digit padding, so a group with
    more than 999 frames sorts '1000' before '999' as text. That would silently
    scramble every overview sheet of the larger groups.
    """
    match = re.search(r"(\d+)\s*$", entry["name"])
    return (0, int(match.group(1))) if match else (1, entry["name"])


def cmd_sheet(args: argparse.Namespace) -> int:
    from PIL import Image, ImageDraw, ImageFont

    directory = Path(args.directory)
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    try:
        index = _load_export_index(directory, verify_mapping=True)
    except ValueError as exc:
        print(f"Exportvertrag abgelehnt: {exc}")
        return 1
    frames = sorted(index["frames"], key=_frame_order)
    if args.range_from is not None or args.range_to is not None:
        low = args.range_from if args.range_from is not None else -(1 << 62)
        high = args.range_to if args.range_to is not None else (1 << 62)
        # Nur Frames mit Zahlindex kommen in Frage. Gruppen wie body_lord
        # fuehren gespiegelte Frames, deren Name nicht auf eine Zahl endet;
        # _frame_order gibt dort den Namen zurueck, und ein Vergleich gegen
        # eine Zeichenkette bricht ab.
        frames = [
            f for f in frames
            if _frame_order(f)[0] == 0 and low <= _frame_order(f)[1] <= high
        ]
        if not frames:
            print(f"Kein Frame zwischen {low} und {high}.")
            return 1

    cell, label, pad = args.cell, 18, 6
    columns, rows = args.columns, args.rows
    per_page = columns * rows
    header = 46
    try:
        font = ImageFont.truetype("arial.ttf", 12)
        head_font = ImageFont.truetype("arial.ttf", 20)
    except OSError:  # pragma: no cover - font availability is platform detail
        font = head_font = ImageFont.load_default()

    # Colour says where the picture came from, so a glance at a sheet answers
    # "what is still Crusader in this group" without opening a single file.
    tint = {
        "stronghold1": (86, 150, 74),
        "crusader": (196, 122, 52),
        "installed-atlas": (76, 132, 205),
        "installed-sprite": (149, 93, 214),
    }
    pages = [frames[i : i + per_page] for i in range(0, len(frames), per_page)] or [[]]
    written = []
    for page_number, page in enumerate(pages, start=1):
        width = columns * (cell + pad) + pad
        height = header + rows * (cell + label + pad) + pad
        sheet = Image.new("RGBA", (width, height), (30, 31, 34, 255))
        draw = ImageDraw.Draw(sheet)
        draw.text(
            (pad, 8),
            f"{index['group']} - Blatt {page_number}/{len(pages)}   "
            "gruen = SH1   orange = Crusader   blau/violett = installierte Mod",
            fill=(232, 230, 227),
            font=head_font,
        )
        for position, entry in enumerate(page):
            column, row = position % columns, position // columns
            x = pad + column * (cell + pad)
            y = header + row * (cell + label + pad)
            colour = tint.get(entry.get("shown_from", ""), (110, 110, 110))
            draw.rectangle([x, y, x + cell, y + cell], outline=colour, width=1)
            path = directory / entry["file"]
            if path.is_file():
                with Image.open(path) as picture:
                    picture = picture.convert("RGBA")
                    picture.thumbnail((cell - 4, cell - 4), Image.LANCZOS)
                    # Bottom-aligned: a building stands on the ground, and a
                    # centred thumbnail makes tall and short frames look
                    # unrelated when they are the same structure.
                    sheet.alpha_composite(
                        picture,
                        (x + (cell - picture.width) // 2, y + cell - 2 - picture.height),
                    )
            draw.text(
                (x + 2, y + cell + 3),
                re.sub(r"^.*?(\d+)\s*$", r"\1", entry["name"]),
                fill=(154, 154, 154),
                font=font,
            )
        # The range must appear in the name. Without it a range sheet silently
        # overwrites the full sheet of the same page number.
        span = ""
        if args.range_from is not None or args.range_to is not None:
            low = _frame_order(frames[0])[1]
            high = _frame_order(frames[-1])[1]
            span = f"-{low}bis{high}"
        out = directory / f"UEBERSICHT-{index['group']}{span}-{page_number:02d}.png"
        sheet.convert("RGB").save(out)
        written.append(out)
    print(f"{len(frames)} Frames auf {len(written)} Blatt")
    for path in written:
        print(f"  {path}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from PIL import Image

    directory = Path(args.directory)
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    try:
        index = _load_export_index(directory, verify_mapping=True)
    except ValueError as exc:
        print(f"Exportvertrag abgelehnt: {exc}")
        return 1

    group = str(index.get("group", ""))
    loader = LOADER_GROUP_TABLE.get(group)
    mask_required = loader is not None and not loader.plain_shader
    missing, resized, ok = [], [], 0
    missing_masks, resized_masks = [], []
    for frame in index["frames"]:
        path = directory / str(frame["file"])
        if not path.is_file():
            missing.append(frame["file"])
            continue
        try:
            with Image.open(path) as opened:
                opened.load()
                image = opened.convert("RGBA")
        except Exception as exc:
            resized.append(f"{frame['file']}: kein lesbares Bild ({exc})")
            continue
        if (image.width, image.height) != (frame["width"], frame["height"]):
            resized.append(
                f"{frame['file']}: {image.width}x{image.height} "
                f"statt {frame['width']}x{frame['height']}"
            )
            continue
        ok += 1
        mask_name = str(
            frame.get("mask_file")
            or (Path(str(frame["file"])).with_suffix("").name + "_m.png")
        )
        mask_path = directory / mask_name
        if mask_required:
            if not mask_path.is_file():
                missing_masks.append(mask_name)
            else:
                try:
                    with Image.open(mask_path) as opened:
                        opened.load()
                        mask = opened.convert("RGBA")
                except Exception as exc:
                    resized_masks.append(f"{mask_name}: kein lesbares Bild ({exc})")
                else:
                    if mask.size != (frame["width"], frame["height"]):
                        resized_masks.append(
                            f"{mask_name}: {mask.width}x{mask.height} "
                            f"statt {frame['width']}x{frame['height']}"
                        )

    forbidden_masks = []
    if loader is not None and loader.plain_shader:
        forbidden_masks = sorted(path.name for path in directory.glob("*_m.png"))
    indexed_pngs = {str(frame["file"]) for frame in index["frames"]}
    indexed_pngs.update(
        str(frame["mask_file"])
        for frame in index["frames"]
        if frame.get("mask_file") is not None
    )
    unindexed = sorted(
        path.name
        for path in directory.glob("*.png")
        if path.name not in indexed_pngs and not path.name.startswith("UEBERSICHT-")
    )

    print(f"Gruppe {index['group']}: {len(index['frames'])} Frames erwartet")
    print(f"  unveraendert gross : {ok}")
    print(f"  fehlend            : {len(missing)}")
    print(f"  andere Groesse     : {len(resized)}")
    print(f"  fehlende Masken    : {len(missing_masks)}")
    print(f"  falsche Maskengroesse: {len(resized_masks)}")
    print(f"  unerlaubte Masken  : {len(forbidden_masks)}")
    print(f"  nicht indizierte PNGs: {len(unindexed)}")
    for line in resized[:10]:
        print(f"    {line}")
    if len(resized) > 10:
        print(f"    ... und {len(resized) - 10} weitere")
    for line in resized_masks[:10]:
        print(f"    {line}")
    if missing_masks:
        for line in missing_masks[:10]:
            print(f"    fehlt: {line}")
    if forbidden_masks:
        for line in forbidden_masks[:10]:
            print(f"    nicht erlaubt: {line}")
    if unindexed:
        for line in unindexed[:10]:
            print(f"    nicht indiziert: {line}")
    if resized:
        print()
        print("Eine andere Bildgroesse ist fuer diesen Lieferweg nicht freigegeben.")
        print("Der Extender uebernimmt nur den normierten Fusspunkt des")
        print("Crusader-Slots; ein anderes Format wuerde das Objekt verschieben.")
        print("Bitte auf die in index.json angegebene Breite und Hoehe bringen.")
    return 1 if (
        missing or resized or missing_masks or resized_masks or forbidden_masks or unindexed
    ) else 0


def authored_foot_check(
    name: str, width: int, height: int, target: dict
) -> tuple[bool, str]:
    """Decide whether a drawn canvas may ship, and say exactly why not.

    The one place this rule lives. `cmd_import` calls it and the builder holds
    the same rule in `_prepare_authored_sprites`; both read the foot point from
    `gm_atlas.authored_sprite_foot_point`, so there is no second formula that
    could drift.

    Accepted only at the Crusader canvas. A different canvas would land at a
    computable but different place, and that place has never been verified in a
    running game - so the message names both foot points and the size that fits.
    """
    from stronghold_europe_de.gm_atlas import authored_sprite_foot_point

    target_width = int(round(float(target["width"])))
    target_height = int(round(float(target["height"])))
    slot = authored_sprite_foot_point(target_width, target_height, target)
    if (width, height) == (target_width, target_height):
        return True, f"Fusspunkt ({slot[0]:.2f}, {slot[1]:.2f}) px, Abweichung 0"
    drawn = authored_sprite_foot_point(width, height, target)
    return False, (
        f"{name}: {width}x{height} statt {target_width}x{target_height}. Der "
        f"Lader behaelt den anteiligen Fusspunkt des Crusader-Platzes, das Bild "
        f"saesse bei ({drawn[0]:.2f}, {drawn[1]:.2f}) px statt bei "
        f"({slot[0]:.2f}, {slot[1]:.2f}) px - gemessen von links und von UNTEN."
    )


def collect_store_section(
    store: str,
    extra_payloads: dict[str, bytes] | None = None,
    *,
    complete_payloads: dict[str, bytes] | None = None,
) -> tuple[dict | None, list[str]]:
    """Berechnet den Profilabschnitt einer Lieferablage aus dem, was dort liegt.

    Eine Formel fuer beide Befehle: ``import`` druckt den Abschnitt,
    ``profile-add`` traegt ihn ein, und der Bauer rechnet beide Digests beim
    Build unabhaengig nach (``_prepare_authored_sprites``). Die Pruefungen hier
    sind dieselben, die auch die Uebernahme faehrt - Leinwand, Kantenlaenge,
    Bytegrenze, Maskenregel - damit ``profile-add`` keinen Abschnitt eintragen
    kann, den der Bauer spaeter grundlos abweist. Das prueft auch Dateien, die
    jemand von Hand in die Ablage kopiert hat: frueher waere so eine Datei erst
    beim Build aufgefallen.

    ``extra_payloads`` erlaubt ``import --check-only``, die noch nicht
    geschriebenen Kandidaten mitzurechnen.
    """

    from PIL import Image

    from stronghold_europe_de.gm_atlas import (
        authored_sprite_foot_point,
        authored_sprite_names_digest,
        authored_sprite_payload_digest,
    )
    from stronghold_europe_de.mod_builder import (
        MAX_AUTHORED_SPRITE_BYTES,
        MAX_AUTHORED_SPRITE_EDGE,
        _PROJECT_AUTHORED_SPRITE_SETS,
    )

    if extra_payloads is not None and complete_payloads is not None:
        return None, ["Interner Fehler: Overlay und vollständiger Kandidat zugleich"]
    if store not in _PROJECT_AUTHORED_SPRITE_SETS:
        return None, [f"Diese Ablage ist nicht freigegeben: {store}"]
    group, origin = _PROJECT_AUTHORED_SPRITE_SETS[store]
    loader = LOADER_GROUP_TABLE.get(group)
    if loader is None:
        return None, [f"{group} ist keine Ladergruppe."]
    targets = {
        str(row["name"]): row["target"]
        for row in read_mapping()
        if row.get("group") == group and row.get("target") is not None
    }

    # Ueber die GANZE Ablage, nicht nur ueber einen Lauf: was von einem
    # frueheren Import dort liegt, wird mitgeliefert und muss deshalb in den
    # Digests stehen - sonst waere der Abschnitt nicht der, den der Bauer
    # nachrechnet.
    store_dir = PROJECT_ROOT.joinpath(*store.split("/"))
    if complete_payloads is not None:
        on_disk = dict(complete_payloads)
    else:
        on_disk: dict[str, bytes] = {}
        if store_dir.is_dir():
            on_disk = {
                path.name: path.read_bytes() for path in sorted(store_dir.glob("*.png"))
            }
        if extra_payloads:
            on_disk.update(extra_payloads)

    mains: dict[str, bytes] = {}
    masks: dict[str, bytes] = {}
    problems: list[str] = []
    for filename, payload in sorted(on_disk.items()):
        flat = filename[: -len(".png")]
        is_mask = flat.endswith("_m")
        name = flat[:-2] if is_mask else flat
        if name not in targets:
            problems.append(f"{filename}: kein Frame von {group}")
            continue
        if len(payload) > MAX_AUTHORED_SPRITE_BYTES:
            problems.append(
                f"{filename}: {len(payload)} Bytes ueber der Grenze von "
                f"{MAX_AUTHORED_SPRITE_BYTES}"
            )
            continue
        try:
            with Image.open(io.BytesIO(payload)) as opened:
                width, height = opened.size
        except Exception as exc:
            problems.append(f"{filename}: nicht lesbar ({exc})")
            continue
        if not all(1 <= edge <= MAX_AUTHORED_SPRITE_EDGE for edge in (width, height)):
            problems.append(
                f"{filename}: {width}x{height} liegt ausserhalb "
                f"1..{MAX_AUTHORED_SPRITE_EDGE} px"
            )
            continue
        ok, detail = authored_foot_check(filename, width, height, targets[name])
        if not ok:
            problems.append(detail)
            continue
        (masks if is_mask else mains)[name] = payload

    if not mains and not problems:
        problems.append(
            f"Die Ablage {store} ist leer - der Bauer weist einen leeren Satz ab."
        )
    problems.extend(
        f"{name}_m.png: Maske ohne Farbbild"
        for name in sorted(masks)
        if name not in mains
    )
    if loader.plain_shader and masks:
        problems.append(f"{group} traegt keine Teammaske, aber es liegen Masken da")
    if not loader.plain_shader:
        problems.extend(
            f"{name}: Maske fehlt" for name in sorted(mains) if name not in masks
        )
    if problems:
        return None, problems

    rows = []
    for name in sorted(mains):
        target = targets[name]
        width = int(round(float(target["width"])))
        height = int(round(float(target["height"])))
        foot_x, foot_y = authored_sprite_foot_point(width, height, target)
        rows.append(
            {
                "name": name,
                "width": width,
                "height": height,
                "foot_px_x": foot_x,
                "foot_px_y": foot_y,
                "main_sha256": hashlib.sha256(mains[name]).hexdigest(),
                "mask_sha256": (
                    "-"
                    if name not in masks
                    else hashlib.sha256(masks[name]).hexdigest()
                ),
            }
        )
    section = {
        "source_dir": store,
        "group": group,
        "category": "authored_sprite",
        "origin": origin,
        "frame_count": len(rows),
        "mask_count": len(masks),
        "expected_names_sha256": authored_sprite_names_digest(
            row["name"] for row in rows
        ),
        "expected_payload_sha256": authored_sprite_payload_digest(rows),
        "allow_atlas_shadow": False,
    }
    return section, []


def cmd_import(args: argparse.Namespace) -> int:
    from stronghold_europe_de.workspace_lock import (
        WorkspaceLockError,
        exclusive_workspace_lock,
    )

    resource = f"sprite-store:{args.origin}:{args.set}"
    try:
        with exclusive_workspace_lock(
            PROJECT_ROOT / "work", resource, f"Sprite-Ablage {args.set}"
        ):
            return _cmd_import_locked(args)
    except WorkspaceLockError as exc:
        print(f"Import abgelehnt: {exc}")
        return 1


def _cmd_import_locked(args: argparse.Namespace) -> int:
    from PIL import Image

    from stronghold_europe_de.installed_art import (
        reject_other_override_plugins,
        verify_installed_mod,
    )
    from stronghold_europe_de.mod_builder import (
        MAX_AUTHORED_SPRITE_BYTES,
        MAX_AUTHORED_SPRITE_EDGE,
        _PROJECT_AUTHORED_SPRITE_SETS,
    )

    source_dir = Path(args.directory)
    if not source_dir.is_absolute():
        source_dir = PROJECT_ROOT / source_dir
    if not source_dir.is_dir():
        print(f"Kein Verzeichnis: {source_dir}")
        return 1

    try:
        index = _load_export_index(source_dir, verify_mapping=True)
        mapping = read_mapping_document()
        config, _match = _verify_mapping_builds(mapping)
    except Exception as exc:
        print(f"Import abgelehnt: Export-/Build-Vertrag ungültig: {exc}")
        return 1

    store = f"assets/sprites/{args.origin}/{args.set}"
    if store not in _PROJECT_AUTHORED_SPRITE_SETS:
        print(f"Diese Ablage ist nicht freigegeben: {store}")
        print("Freigegeben sind:")
        for allowed, (allowed_group, _origin) in sorted(
            _PROJECT_AUTHORED_SPRITE_SETS.items()
        ):
            print(f"  {allowed}  ->  {allowed_group}")
        print()
        print(
            "Die Freigabe steht im Code (_PROJECT_AUTHORED_SPRITE_SETS in "
            "mod_builder.py) und bindet eine Ablage an genau eine GM-Gruppe. "
            "Das ist die eigentliche Schranke: ein Kirchensatz kann so keinen "
            "Einheitenframe ueberschreiben."
        )
        return 1
    group, _origin = _PROJECT_AUTHORED_SPRITE_SETS[store]
    loader = LOADER_GROUP_TABLE.get(group)
    if loader is None:
        print(f"{group} ist keine Ladergruppe.")
        return 1
    if index["group"] != group:
        print(
            f"Import abgelehnt: Exportgruppe {index['group']} passt nicht zur "
            f"freigegebenen Ablage {group}."
        )
        return 1
    tile_result_path = source_dir / "tile-object-result.json"
    if tile_result_path.exists():
        try:
            tile_result = json.loads(tile_result_path.read_text(encoding="utf-8"))
            semantic = tile_result["semantic"]
            if (
                not isinstance(tile_result, dict)
                or tile_result.get("group") != group
                or not isinstance(semantic, dict)
                or semantic.get("status") not in {"verified-preset", "user-confirmed"}
            ):
                raise ValueError("semantische Freigabe fehlt")
            changed = tile_result.get("changed")
            if not isinstance(changed, list) or any(not isinstance(name, str) for name in changed):
                raise ValueError("Änderungsliste ist ungültig")
            indexed_names = {str(frame["name"]) for frame in index["frames"]}
            if not set(changed) <= indexed_names:
                raise ValueError("Änderungsliste enthält fremde Frames")
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            print(f"Import abgelehnt: Tile-Objektnachweis ungültig ({exc})")
            return 1
    if index["game"] == "delivered":
        try:
            mod = verify_installed_mod(config)
            if sha256_file(mod.root / "build-manifest.json") != index.get(
                "installed_build_manifest_sha256"
            ):
                raise ValueError("Installierte Mod wurde seit dem Export geändert")
            if str(mod.build_manifest.get("profile_id", "")) != index.get(
                "installed_profile_id"
            ):
                raise ValueError("Installiertes Profil wurde seit dem Export geändert")
            reject_other_override_plugins(
                config, group, [str(frame["name"]) for frame in index["frames"]]
            )
        except Exception as exc:
            print(f"Import abgelehnt: Installationsbezug ist nicht mehr gültig: {exc}")
            return 1
    targets = {
        str(row["name"]): row["target"]
        for row in mapping["sprites"]
        if row.get("group") == group and row.get("target") is not None
    }

    exported_main = {
        str(frame["name"]): str(frame["pixels_sha256"])
        for frame in index["frames"]
    }
    exported_masks = {
        str(frame["name"]): str(frame["mask_pixels_sha256"])
        for frame in index["frames"]
        if frame.get("mask_pixels_sha256") is not None
    }
    indexed_files = {str(frame["file"]) for frame in index["frames"]}
    indexed_files.update(
        str(frame["mask_file"])
        for frame in index["frames"]
        if frame.get("mask_file") is not None
    )
    extra_pngs = sorted(
        path.name
        for path in source_dir.glob("*.png")
        if path.name not in indexed_files and not path.name.startswith("UEBERSICHT-")
    )
    if extra_pngs:
        print(f"Import abgelehnt: nicht indizierte PNGs: {extra_pngs[:12]}")
        return 1

    accepted: dict[str, bytes] = {}
    normalized_source: dict[str, bytes] = {}
    rejected: list[str] = []
    unchanged: list[str] = []
    for frame in index["frames"]:
        name = str(frame["name"])
        candidates = [(str(frame["file"]), False)]
        if frame.get("mask_file") is not None:
            candidates.append((str(frame["mask_file"]), True))
        for filename, is_mask in candidates:
            path = source_dir / filename
            if not path.is_file():
                rejected.append(f"{filename}: fehlt")
                continue
            try:
                with Image.open(path) as opened:
                    opened.load()
                    image = opened.convert("RGBA")
            except Exception as exc:
                rejected.append(f"{filename}: nicht lesbar ({exc})")
                continue
            if image.size != (int(frame["width"]), int(frame["height"])):
                rejected.append(
                    f"{filename}: {image.width}x{image.height} statt "
                    f"{frame['width']}x{frame['height']}"
                )
                continue
            if not all(1 <= edge <= MAX_AUTHORED_SPRITE_EDGE for edge in image.size):
                rejected.append(
                    f"{filename}: {image.width}x{image.height} liegt ausserhalb "
                    f"1..{MAX_AUTHORED_SPRITE_EDGE} px"
                )
                continue
            ok, detail = authored_foot_check(
                filename, image.width, image.height, targets[name]
            )
            if not ok:
                rejected.append(detail)
                continue
            pixels = hashlib.sha256(image.tobytes()).hexdigest()
            original = exported_masks.get(name) if is_mask else exported_main[name]
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=False, compress_level=9)
            payload = buffer.getvalue()
            if len(payload) > MAX_AUTHORED_SPRITE_BYTES:
                rejected.append(
                    f"{filename}: {len(payload)} Bytes ueber der Grenze von "
                    f"{MAX_AUTHORED_SPRITE_BYTES}"
                )
                continue
            normalized_source[filename] = payload
            if original == pixels:
                unchanged.append(filename)
            else:
                accepted[filename] = payload

    if rejected:
        print("Abgelehnt statt zurechtskaliert:")
        for line in rejected:
            print("  " + line)
        print()
    if unchanged:
        print(
            f"Unveraendert seit dem Export, nicht geliefert: {len(unchanged)}"
        )
        print()
    if rejected:
        return 1

    store_dir = PROJECT_ROOT.joinpath(*store.split("/"))
    existing: dict[str, bytes] = {}
    if store_dir.exists():
        if not store_dir.is_dir():
            print(f"Import abgelehnt: Ablage ist kein Verzeichnis: {store_dir}")
            return 1
        foreign = [path.name for path in store_dir.iterdir() if not path.is_file() or path.suffix.lower() != ".png"]
        if foreign:
            print(f"Import abgelehnt: fremde Einträge in der Ablage: {foreign[:12]}")
            return 1
        existing = {
            path.name: path.read_bytes() for path in sorted(store_dir.glob("*.png"))
        }
    candidate = dict(existing)
    candidate.update(accepted)

    # The builder requires colour and team mask as a pair. For a derived set
    # an unchanged partner may safely be copied from the same proven export;
    # for authored material that would silently place game-derived pixels in
    # the repository, so an authored import must provide/edit both or already
    # have the counterpart in its approved store.
    dependencies: list[str] = []
    if not loader.plain_shader:
        by_name = {str(frame["name"]): frame for frame in index["frames"]}
        for name, frame in sorted(by_name.items()):
            main_file = str(frame["file"])
            mask_file = str(frame["mask_file"])
            touched = main_file in accepted or mask_file in accepted
            if not touched:
                continue
            for required_file in (main_file, mask_file):
                if required_file in candidate:
                    continue
                if args.origin != "derived":
                    rejected.append(
                        f"{name}: {required_file} wäre unverändertes Spielmaterial; "
                        "für authored beide Partner bearbeiten oder den Partner vorher freigeben"
                    )
                    continue
                candidate[required_file] = normalized_source[required_file]
                dependencies.append(required_file)
    if rejected:
        print("Import abgelehnt; die Ablage bleibt byte-identisch:")
        for line in rejected:
            print("  " + line)
        return 1
    if not candidate:
        print("Nichts zu liefern.")
        return 1

    # The profile section is computed over the WHOLE store, not only over what
    # this run wrote. Anything left there from an earlier import ships too, so
    # it has to be inside the digests - otherwise the printed section would not
    # be the section the builder checks. One shared formula with `profile-add`,
    # so the printed section and the written section cannot drift.
    section, problems = collect_store_section(store, complete_payloads=candidate)
    if problems:
        print()
        print("Die Ablage ist nicht lieferbar:")
        for line in problems:
            print("  " + line)
        print("Die bestehende Ablage wurde nicht verändert.")
        return 1

    if args.check_only:
        print(
            f"{len(accepted)} geänderte PNGs und {len(dependencies)} notwendige "
            f"Partnerdateien würden atomar nach {store} gehen (--check-only)"
        )
    elif candidate == existing:
        print("Ablage bereits identisch; nichts geschrieben.")
    else:
        parent = store_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        backup = store_dir.with_name(store_dir.name + ".sprites-import-backup")
        if backup.exists():
            print(f"Import abgelehnt: alte Transaktionssicherung vorhanden: {backup}")
            return 1
        staging = Path(tempfile.mkdtemp(prefix=f".{store_dir.name}.sprites-import-", dir=parent))
        try:
            for filename, payload in sorted(candidate.items()):
                (staging / filename).write_bytes(payload)
            # Re-read the staged bytes and validate what will actually be
            # renamed, not merely the in-memory candidate.
            staged_payloads = {
                path.name: path.read_bytes() for path in sorted(staging.glob("*.png"))
            }
            _staged_section, staged_problems = collect_store_section(
                store, complete_payloads=staged_payloads
            )
            if staged_problems or _staged_section != section:
                raise RuntimeError(
                    "Staging-Nachprüfung widerspricht dem Kandidaten: "
                    + "; ".join(staged_problems)
                )
            if store_dir.exists():
                os.replace(store_dir, backup)
            os.replace(staging, store_dir)
        except Exception as exc:
            if store_dir.exists() and backup.exists():
                shutil.rmtree(store_dir)
            if backup.exists() and not store_dir.exists():
                os.replace(backup, store_dir)
            if staging.exists():
                shutil.rmtree(staging)
            print(f"Import fehlgeschlagen und zurückgerollt: {exc}")
            return 1
        if backup.exists():
            shutil.rmtree(backup)
        print(
            f"{len(accepted)} geänderte PNGs und {len(dependencies)} notwendige "
            f"Partnerdateien atomar nach {store}"
        )
    print()
    print('Profilabschnitt, unter "authored_sprites" einfuegen:')
    print(json.dumps([section], indent=2, ensure_ascii=False))
    print()
    print(
        "allow_atlas_shadow bleibt false, solange dasselbe Profil die Gruppe "
        "nicht auch als Atlas ausliefert. Tut es das, gewinnt das Einzel-PNG "
        "nach Namen, ohne dass ein Pfad kollidiert - deshalb muss diese "
        "Verdraengung im Profil sichtbar gewollt sein."
    )
    print(
        "Diese Datei schreibt hier nicht nach profiles/ - eintragen:  "
        f"python tools/sprites.py profile-add {args.set} --origin {args.origin} --write"
    )
    return 0


DEFAULT_PROFILE = "profiles/europe-production.json"


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
            return _cmd_profile_add_locked(args)
    except WorkspaceLockError as exc:
        print(f"Profiländerung abgelehnt: {exc}")
        return 1


def _cmd_profile_add_locked(args: argparse.Namespace) -> int:
    """Traegt den Abschnitt einer Lieferablage in ein Profil ein.

    Dieselbe Arbeitsteilung wie bei groups.py: das Werkzeug schreibt das
    Profil, eine Oberflaeche ruft hoechstens auf. Ohne ``--write`` wird nur
    gezeigt (pin_xaml-Konvention). Der Abschnitt wird unmittelbar vor dem
    Schreiben NEU aus der Ablage gerechnet und das Profil frisch gelesen -
    dieselbe Datei schreibt auch groups.py, und eine parallele Sitzung kann
    sie eben geaendert haben.
    """

    from stronghold_europe_de.mod_builder import (
        _AUTHORED_SPRITE_KEYS,
        _authored_sprite_group_claims,
    )

    try:
        mapping = read_mapping_document()
        _verify_mapping_builds(mapping)
    except Exception as exc:
        print(f"Profiländerung abgelehnt: Mapping-/Build-Prüfung fehlgeschlagen: {exc}")
        return 1

    store = f"assets/sprites/{args.origin}/{args.set}"
    section, problems = collect_store_section(store)
    if section is None:
        print("Die Ablage ist nicht lieferbar - nichts eingetragen:")
        for line in problems:
            print("  " + line)
        return 1

    profile_path = Path(args.profile)
    if not profile_path.is_absolute():
        profile_path = PROJECT_ROOT / profile_path
    try:
        original = profile_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Profil nicht lesbar: {profile_path} ({exc})")
        return 1
    try:
        profile = json.loads(original)
    except ValueError as exc:
        print(f"Profil ist kein JSON: {profile_path} ({exc})")
        return 1
    if not isinstance(profile, dict):
        print(f"Profil ist kein Objekt: {profile_path}")
        return 1

    selections = profile.get("authored_sprites", [])
    if not isinstance(selections, list) or any(
        not isinstance(entry, dict) for entry in selections
    ):
        print("authored_sprites im Profil ist keine Liste von Objekten - Handarbeit.")
        return 1
    matches = [entry for entry in selections if entry.get("source_dir") == store]
    if len(matches) > 1:
        print(f"Mehrere Eintraege fuer {store} im Profil - Handarbeit.")
        return 1
    old = matches[0] if matches else None
    if old is not None and set(old) != _AUTHORED_SPRITE_KEYS:
        # Der Bauer verwirft Abschnitte mit fremden Schluesseln ("must contain
        # exactly"). Sie stillschweigend zu "reparieren" wuerde Handarbeit
        # loeschen, deren Zweck dieses Werkzeug nicht kennt - also verweigern
        # und zeigen.
        deviation = sorted(set(old) ^ _AUTHORED_SPRITE_KEYS)
        print(
            f"Der bestehende Eintrag fuer {store} traegt nicht exakt die "
            f"Schluessel des Bauers (Abweichung: {deviation}). Bitte von Hand "
            "bereinigen - dieses Werkzeug repariert Profile nicht."
        )
        return 1

    group = str(section["group"])
    folded = group.casefold()
    atlas_claims, sparse_claims = _authored_sprite_group_claims(profile)
    if folded in sparse_claims:
        print(
            f"{group} wird in diesem Profil von einem sparse/shared-Backend "
            "geliefert - das ist mit Einzel-PNGs nie kombinierbar, der Bauer "
            "weist es ab. Nichts eingetragen."
        )
        return 1
    shadow = bool(
        args.allow_atlas_shadow
        or (old is not None and old.get("allow_atlas_shadow") is True)
    )
    if args.allow_atlas_shadow and folded not in atlas_claims:
        print(
            f"{group} liegt nicht in gm_atlases dieses Profils. "
            "--allow-atlas-shadow waere deshalb eine irrefuehrende Zustimmung; "
            "nichts eingetragen."
        )
        return 1
    if folded in atlas_claims and not shadow:
        print(
            f"{group} liegt in gm_atlases desselben Profils. Ein Einzel-PNG "
            "gewinnt beim Laden nach Namen gegen den Atlas, ohne dass ein Pfad "
            "kollidiert - diese Verdraengung muss im Profil sichtbar gewollt "
            "sein. Wenn sie gewollt ist, denselben Befehl ausdruecklich mit "
            "--allow-atlas-shadow wiederholen."
        )
        return 1
    # Eine bestehende Zustimmung bleibt beim Ersetzen erhalten. Eine neue kann
    # nur der sichtbare CLI-Schalter erzeugen; die normale Route bleibt damit
    # fail-closed.
    section["allow_atlas_shadow"] = shadow

    action = "ersetzt" if old is not None else "angehaengt"
    print(f"Profilabschnitt fuer {profile_path.name} ({action}):")
    print(json.dumps([section], indent=2, ensure_ascii=False))
    print()
    if not args.write:
        print("Ohne --write nur gezeigt, nichts geschrieben.")
        print("Der Bauer rechnet beide Digests beim Build unabhaengig nach.")
        return 0

    if old is not None:
        selections = [
            section if entry.get("source_dir") == store else entry
            for entry in selections
        ]
    else:
        selections = [*selections, section]
    profile["authored_sprites"] = selections
    updated = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"
    if updated == original:
        print("Profil unveraendert - der Eintrag ist bereits identisch enthalten.")
        return 0
    # Atomar: erst vollstaendig daneben schreiben, dann ersetzen. Ein
    # abgebrochener Lauf laesst so nie ein halbes Profil zurueck.
    tmp = profile_path.with_name(profile_path.name + ".tmp")
    tmp.write_text(updated, encoding="utf-8")
    os.replace(tmp, profile_path)
    print(f"{action}: {store} in {profile_path}")
    print("Der Bauer rechnet beide Digests beim Build unabhaengig nach.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sprites",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="Welche Gruppen gibt es")
    listing.add_argument(
        "--all", action="store_true", help="auch nicht ladbare Gruppen"
    )
    listing.add_argument(
        "--json",
        action="store_true",
        help="maschinenlesbar, mit den freigegebenen Lieferablagen (fuer die Suite)",
    )
    listing.set_defaults(func=cmd_list)

    export = sub.add_parser("export", help="Eine Gruppe als PNGs herausschreiben")
    export.add_argument("group")
    export.add_argument("--out", default="work/art")
    export.add_argument(
        "--game",
        choices=("delivered", "crusader", "stronghold1"),
        default="delivered",
        help=(
            "delivered = exakt aus der verwalteten installierten Mod (Standard), "
            "crusader/stronghold1 = eine Seite fuer sich"
        ),
    )
    export.add_argument(
        "--replace",
        action="store_true",
        help="einen vorhandenen Exportordner ausdruecklich atomar ersetzen",
    )
    export.add_argument(
        "--from", dest="range_from", type=int, help="nur Frames ab diesem Index"
    )
    export.add_argument(
        "--to", dest="range_to", type=int, help="nur Frames bis zu diesem Index"
    )
    export.set_defaults(func=cmd_export)

    sheet = sub.add_parser("sheet", help="Uebersichtstafeln zu einem Export bauen")
    sheet.add_argument("directory")
    sheet.add_argument("--cell", type=int, default=144)
    sheet.add_argument("--columns", type=int, default=16)
    sheet.add_argument("--rows", type=int, default=20)
    sheet.add_argument("--from", dest="range_from", type=int, help="ab Frameindex")
    sheet.add_argument("--to", dest="range_to", type=int, help="bis Frameindex")
    sheet.set_defaults(func=cmd_sheet)

    check = sub.add_parser("check", help="Bearbeitete PNGs pruefen")
    check.add_argument("directory")
    check.set_defaults(func=cmd_check)

    importer = sub.add_parser(
        "import", help="Gezeichnete PNGs in eine Lieferablage uebernehmen"
    )
    importer.add_argument("directory", help="Ordner mit den bearbeiteten PNGs")
    importer.add_argument(
        "--set", dest="set", required=True, help="Name der Ablage, z.B. tree-cactii-europe"
    )
    importer.add_argument(
        "--origin",
        choices=("authored", "derived"),
        default="authored",
        help=(
            "authored = selbst gezeichnet, gehoert ins Repository; "
            "derived = uebermaltes Spielbild, per .gitignore ausgeschlossen"
        ),
    )
    importer.add_argument(
        "--check-only",
        action="store_true",
        help="nur pruefen und den Profilabschnitt zeigen, nichts schreiben",
    )
    importer.set_defaults(func=cmd_import)

    profile_add = sub.add_parser(
        "profile-add",
        help="Den Abschnitt einer Lieferablage in ein Profil eintragen",
    )
    profile_add.add_argument(
        "set", help="Name der Ablage, z.B. tree-cactii-europe"
    )
    profile_add.add_argument(
        "--origin",
        choices=("authored", "derived"),
        default="authored",
        help="Herkunft der Ablage, wie bei 'import'",
    )
    profile_add.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        help="Zielprofil (Standard: das Produktionsprofil)",
    )
    profile_add.add_argument(
        "--write",
        action="store_true",
        help="wirklich eintragen; ohne --write nur zeigen (wie pin_xaml)",
    )
    profile_add.add_argument(
        "--allow-atlas-shadow",
        action="store_true",
        help=(
            "ausdruecklich erlauben, dass Einzel-PNGs dieselbe Gruppe aus "
            "gm_atlases nach Namen ueberstimmen"
        ),
    )
    profile_add.set_defaults(func=cmd_profile_add)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
