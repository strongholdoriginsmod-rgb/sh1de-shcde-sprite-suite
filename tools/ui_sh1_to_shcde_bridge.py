"""Explicit SH1-HUD -> SHCDE-UI crop bridge; never writes to games.

The SHCDE XAML rectangles and atlas geometry remain authoritative. This does
not create new Noesis resources, import new HUD states or prove gameplay parity.
Users freely select one or many mappings and a fitting mode. No justification,
semantic approval or running-game acceptance is required to build a candidate.
All unselected target crop files remain byte-for-byte unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from PIL import Image

from ui_sh1_hud import (
    ROOT, BUILD_ID, ATLAS_NAMES, HudError, check_workspace, digest_file
)
from suite_ui_atlas_preview import (
    read_ui_preview_index, validate_sh1_hud_preview, UiPreviewIndexError,
)

SCHEMA = "sprite-suite.sh1-to-shcde-bridge-plan.v1"
RESULT_SCHEMA = "sprite-suite.sh1-to-shcde-bridge-result.v1"
FITS = ("exact", "contain", "stretch")
MAX_MAPPINGS = 10000


class BridgeError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return digest_file(path)


def under_work(path: str | Path, *, must_exist: bool = True) -> Path:
    """Keep every read/write inside the application workspace, no symlink hops."""
    raw = Path(path)
    raw = raw if raw.is_absolute() else ROOT / raw
    base = (ROOT / "work").resolve()
    # Resolve without requiring existence first: even a missing path outside
    # work must report a bridge containment error, not an unrelated ENOENT.
    absolute = raw.resolve(strict=False)
    if absolute == base or not absolute.is_relative_to(base):
        raise BridgeError("Ein- und Ausgaben dürfen nur UNTER SpriteSuite/work liegen")
    parent = raw
    while parent != base and parent != parent.parent:
        if parent.is_symlink():
            raise BridgeError("Symbolische Verzeichnisse sind nicht erlaubt")
        parent = parent.parent
    return absolute


def _disjoint(a: Path, b: Path):
    if a == b or a.is_relative_to(b) or b.is_relative_to(a):
        raise BridgeError("Quell-, Ziel- und Ausgabebäume dürfen sich nicht überschneiden")


def _read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise BridgeError(f"Manifest fehlt, ist verlinkt oder zu groß: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError, OSError) as exc:
        raise BridgeError(f"Manifest nicht lesbar: {path}") from exc
    if not isinstance(document, dict):
        raise BridgeError("Manifest muss ein JSON-Objekt sein")
    return document


def _load_exports(source: Path, target: Path):
    source = under_work(source)
    target = under_work(target)
    _disjoint(source, target)
    try:
        src = read_ui_preview_index(source)
        validate_sh1_hud_preview(source, src)
        checked, _ = check_workspace(source)
        tgt = read_ui_preview_index(target)
    except (HudError, UiPreviewIndexError, ValueError, OSError) as exc:
        raise BridgeError(f"Quellexport/Zielexport nicht vertrauenswürdig: {exc}") from exc
    src_idx = _read_json(source / "index.json")
    tgt_idx = _read_json(target / "index.json")
    if src_idx["target_build_id"] != BUILD_ID or set(e["atlas"] for e in src) != set(ATLAS_NAMES):
        raise BridgeError("Quellprojekt ist kein vollständiges SH1-HUD")
    if tgt_idx["target_build_id"] == BUILD_ID or tgt_idx["texture_asset_name"] != "globalgamemanagers.assets":
        raise BridgeError("Zielprojekt ist kein Crusader-UI-Export")
    if not tgt:
        raise BridgeError("Crusader-Zielindex enthält keine Bildrechtecke")
    if checked["checked"] != len(src):
        raise BridgeError("SH1-HUD-Prüfzahl weicht vom Quellexport ab")
    return ({e["key"]: e for e in src}, {e["key"]: e for e in tgt},
            src_idx, tgt_idx)


def _row(src: dict, target: dict, *, explicit_alias: bool = False) -> dict:
    same = (src["width"], src["height"]) == (target["width"], target["height"])
    return {
        "source_key": src["key"],
        "target_key": target["key"],
        "source_atlas": src["atlas"],
        "target_atlas": target["atlas"],
        "source_size": [src["width"], src["height"]],
        "target_size": [target["width"], target["height"]],
        "source_png_sha256": _sha(Path(src["path"])),
        "target_png_sha256": _sha(Path(target["path"])),
        "fit": "exact" if same else "contain",
        "selected": False,
        "explicit_alias": explicit_alias,
        "state_note": "",
    }


def create_plan(source: str | Path, target: str | Path) -> dict:
    srcroot, tgtroot = under_work(source), under_work(target)
    sources, targets, src_idx, tgt_idx = _load_exports(srcroot, tgtroot)
    matching = sorted(sources.keys() & targets.keys())
    mapping = [_row(sources[key], targets[key]) for key in matching]
    same = sum(row["fit"] == "exact" for row in mapping)
    return {
        "schema": SCHEMA,
        "source_export": str(srcroot),
        "target_export": str(tgtroot),
        "source_index_sha256": _sha(srcroot / "index.json"),
        "target_index_sha256": _sha(tgtroot / "index.json"),
        "source_game_sha256": src_idx["texture_asset_sha256"],
        "target_game_sha256": tgt_idx["texture_asset_sha256"],
        "target_build_id": tgt_idx["target_build_id"],
        "mapping": mapping,
        "coverage": {
            "sh1_sprites": len(sources), "shcde_sprites": len(targets),
            "matching_keys": len(matching), "same_size": same,
            "different_size": len(matching) - same,
            "source_without_target_key": len(sources) - len(matching),
            "target_without_source_key": len(targets) - len(matching),
            "selected": 0, "notes": (
                "Grafiken und Zielslots frei auswählen. Unterschiedliche Maße "
                "mit contain oder stretch einpassen; Zielrechtecke bleiben fest."
            )
        },
    }


def _save_plan(path: Path, data: dict):
    path = under_work(path, must_exist=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise BridgeError("Plan darf keine Dateiverknüpfung sein")
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".bridge-plan-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _validate_plan(plan_path: Path):
    plan_path = under_work(plan_path)
    plan = _read_json(plan_path)
    required = {
        "schema", "source_export", "target_export", "source_index_sha256",
        "target_index_sha256", "source_game_sha256", "target_game_sha256",
        "target_build_id", "mapping", "coverage"
    }
    if set(plan) != required or plan["schema"] != SCHEMA:
        raise BridgeError("Unbekannter Planvertrag")
    source = under_work(plan["source_export"])
    target = under_work(plan["target_export"])
    sources, targets, src_idx, tgt_idx = _load_exports(source, target)
    if (plan["source_index_sha256"] != _sha(source / "index.json") or
        plan["target_index_sha256"] != _sha(target / "index.json") or
        plan["source_game_sha256"] != src_idx["texture_asset_sha256"] or
        plan["target_game_sha256"] != tgt_idx["texture_asset_sha256"] or
        plan["target_build_id"] != tgt_idx["target_build_id"]):
        raise BridgeError("Plan passt nicht mehr zur SH1-/Crusader-Version")
    if not isinstance(plan["mapping"], list) or len(plan["mapping"]) > MAX_MAPPINGS:
        raise BridgeError("Zu viele oder ungültige Zuordnungen")
    occupied: set[str] = set()
    for row in plan["mapping"]:
        if not isinstance(row, dict) or row["source_key"] not in sources or row["target_key"] not in targets:
            raise BridgeError("Zuordnung enthält unbekannten SH1- oder Crusader-Schlüssel")
        src, tgt = sources[row["source_key"]], targets[row["target_key"]]
        expected = _row(src, tgt, explicit_alias=row.get("explicit_alias", False))
        for pinned in ("source_key", "target_key", "source_atlas", "target_atlas",
                       "source_size", "target_size", "source_png_sha256",
                       "target_png_sha256"):
            if row.get(pinned) != expected[pinned]:
                raise BridgeError(f"{row['target_key']}: Herkunft, Geometrie oder Bearbeitungsstand hat sich geändert")
        if row["target_key"] in occupied:
            raise BridgeError(f"Crusader-Ziel doppelt zugeordnet: {row['target_key']}")
        occupied.add(row["target_key"])
        if row.get("fit") not in (*FITS, "skip"):
            raise BridgeError("Nur exaktes Kopieren, Einpassen oder bewusstes Strecken erlaubt")
        # Read old plans without enforcing their former policy/approval fields.
        # Selection is an editing choice, never a separate permission gate.
        row["selected"] = row.get("selected", row.get("approved", False))
        if type(row["selected"]) is not bool:
            raise BridgeError(f"{row['target_key']}: selected muss bool sein")
        row["explicit_alias"] = row["source_key"] != row["target_key"]
        if row["fit"] == "exact" and row["source_size"] != row["target_size"]:
            if row["selected"]:
                raise BridgeError(f"{row['target_key']}: Größenkonflikt darf nicht exakt kopiert werden")
        if row["selected"] and row["fit"] == "skip":
            raise BridgeError(f"{row['target_key']}: Für ausgewählte Grafiken einen Fit-Modus wählen")
    return plan, source, target, sources, targets


def _fit_image(image: Image.Image, target_size: tuple[int, int], mode: str) -> Image.Image:
    if mode == "exact":
        if image.size != target_size:
            raise BridgeError("Exakter Modus erfordert identische Pixelmaße")
        return image.copy()
    width, height = target_size
    if mode == "stretch":
        return image.resize(target_size, Image.Resampling.NEAREST)
    if mode != "contain":
        raise BridgeError("Unbekannter Geometriemodus")
    factor = min(width / image.width, height / image.height)
    new_size = (max(1, min(width, round(image.width * factor))),
                max(1, min(height, round(image.height * factor))))
    scaled = image.resize(new_size, Image.Resampling.NEAREST)
    result = Image.new("RGBA", target_size, (0, 0, 0, 0))
    result.paste(scaled, ((width - new_size[0]) // 2,
                          (height - new_size[1]) // 2))
    scaled.close()
    return result


def _native_sh1_check(asset: Path, workspace: Path, expected_sha: str) -> dict:
    """Bind the self-consistent exported manifests to actual Unity resources."""
    import UnityPy
    from ui_sh1_unity_patch import verify_native_provenance

    if asset.name != "globalgamemanagers.assets" or not asset.is_file() or asset.is_symlink():
        raise BridgeError("Die native SH1-Quelle muss globalgamemanagers.assets sein")
    if _sha(asset) != expected_sha:
        raise BridgeError("Originaldatei SH1 entspricht nicht dem Export-SHA-256")
    env = UnityPy.load(str(asset))
    atlases = {}
    for obj in env.objects:
        if obj.type.name == "Texture2D" and obj.peek_name() in ATLAS_NAMES:
            name = obj.peek_name()
            if name in atlases:
                raise BridgeError("Doppelte Original-SH1-Textur")
            atlases[name] = obj.read().image.convert("RGBA")
    try:
        result = verify_native_provenance(env, workspace, atlases)
    except (HudError, ValueError, OSError) as exc:
        raise BridgeError(f"Native SH1-Quellbindung fehlgeschlagen: {exc}") from exc
    return result


def _native_shcde_check(
    asset: Path, xaml_root: Path, target: Path, expected_sha: str
) -> dict:
    """Check the build-pinned target asset plus *actual* Crusader XAML rectangles."""
    from ui_atlas import discover

    if asset.name != "globalgamemanagers.assets" or not asset.is_file() or asset.is_symlink():
        raise BridgeError("SHCDE-Assetdatei fehlt oder hat einen falschen Namen")
    if _sha(asset) != expected_sha:
        raise BridgeError("SHCDE-Unity-Zieldatei hat eine andere SHA-256")
    if not xaml_root.is_dir() or xaml_root.is_symlink():
        raise BridgeError("SHCDE-XAML-Verzeichnis fehlt oder ist verlinkt")
    sources = {path.name: (path, sheet, crops)
               for path, sheet, crops in discover(xaml_root)}
    index = _read_json(target / "index.json")
    checked = 0
    for atlas in index["atlases"]:
        triple = sources.get(atlas["dictionary"])
        if triple is None:
            raise BridgeError(f"SHCDE-Dictionary nicht in Originalquelle: {atlas['dictionary']}")
        native_path, native_sheet, native_crops = triple
        if (_sha(native_path) != atlas["dictionary_sha256"]
                or native_sheet != atlas["sheet"]):
            raise BridgeError("SHCDE-Original-XAML oder Atlasblatt weicht ab")
        by_key = {entry.key: entry for entry in native_crops}
        if len(by_key) != len(atlas["crops"]) or set(by_key) != {
            row["key"] for row in atlas["crops"]
        }:
            raise BridgeError("SHCDE-Original-XAML hat andere Schlüssel")
        for row in atlas["crops"]:
            crop = by_key[row["key"]]
            if (crop.x, crop.y, crop.width, crop.height) != (
                row["x"], row["y"], row["width"], row["height"]
            ):
                raise BridgeError(f"SHCDE-Zielkoordinaten nicht original: {row['key']}")
            checked += 1
    # Native XAML geometry alone is insufficient: bind *every indexed crop*
    # to the original decoded Unity texture, using the existing Crusader
    # validator rather than trusting the JSON's self-reported pixel digests.
    from ui_atlas import _inspect_edits
    try:
        rebuilt, problems = _inspect_edits(
            target, sprites_dir=xaml_root, texture_asset=asset,
            target_build_id=index["target_build_id"],
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise BridgeError(f"Native SHCDE-Textur-/XAML-Prüfung fehlgeschlagen: {exc}") from exc
    if problems or len(rebuilt) != len(index["atlases"]):
        raise BridgeError("Native SHCDE-Pixelparität nicht vollständig: "
                          + "; ".join(problems[:4]))
    prior_edits = sum(changed for _name, _image, changed in rebuilt)
    del rebuilt
    return {"native_unity_sha256_matches": True,
            "native_xaml_atlases_checked": len(index["atlases"]),
            "original_target_rectangles_checked": checked,
            "native_texture_rectangles_checked": checked,
            "existing_target_edits_preserved": prior_edits}


def _copy_target_tree(target: Path, stage: Path, targets: dict):
    shutil.copy2(target / "index.json", stage / "index.json")
    for entry in targets.values():
        parent = stage / entry["atlas"]
        parent.mkdir(parents=True, exist_ok=True)
        source = Path(entry["path"])
        if source.is_symlink() or not source.is_file():
            raise BridgeError("Crusader-Quell-PNG wurde entfernt oder ist verlinkt")
        shutil.copy2(source, parent / entry["file"])


def apply_plan(
    plan_file: str | Path, output: str | Path, *,
    source_game: Path | None = None, target_game: Path | None = None,
    target_xaml: Path | None = None, allow_offline: bool = False,
    target_keys: list[str] | None = None, fit: str | None = None,
) -> dict:
    plan, source, target, sources, targets = _validate_plan(Path(plan_file))
    output = under_work(output, must_exist=False)
    _disjoint(output, source)
    _disjoint(output, target)
    _disjoint(output, under_work(plan_file))
    if output.exists():
        raise BridgeError("Kandidaten-Ausgabe besteht bereits: niemals stillschweigend ersetzen")
    if output.parent.is_symlink():
        raise BridgeError("Ausgabeordner darf kein Link sein")
    if target_keys is not None:
        if (not isinstance(target_keys, list) or any(not isinstance(key, str) for key in target_keys)
                or len(set(target_keys)) != len(target_keys)):
            raise BridgeError("Zielauswahl muss eine Liste eindeutiger Schlüssel sein")
        by_target = {row["target_key"]: row for row in plan["mapping"]}
        if any(key not in by_target for key in target_keys):
            raise BridgeError("Unbekannter Zielschlüssel in der Auswahl")
        selected = [dict(by_target[key]) for key in target_keys]
    else:
        selected = [dict(row) for row in plan["mapping"] if row["selected"]]
    if not selected:
        raise BridgeError("Keine Grafiken ausgewählt")
    if len(selected) > MAX_MAPPINGS:
        raise BridgeError("Zu viele ausgewählte Grafiken")
    for row in selected:
        row["fit"] = fit if fit is not None else row["fit"]
        if row["fit"] not in FITS:
            raise BridgeError("Bitte exact, contain oder stretch wählen")
        if row["fit"] == "exact" and row["source_size"] != row["target_size"]:
            raise BridgeError("Ungleiche Größen erfordern contain oder stretch")
    proofs: dict = {"source_native_verified": False, "target_native_verified": False,
                    "native_provenance_checked": False}
    if any(item is not None for item in (source_game, target_game, target_xaml)):
        if source_game is None or target_game is None or target_xaml is None:
            raise BridgeError(
                "Für die optionale native Herkunftsprüfung alle drei Quellen angeben: "
                "SH1-Asset, SHCDE-Asset und SHCDE-XAML-Ordner"
            )
        source_proof = _native_sh1_check(Path(source_game), source, plan["source_game_sha256"])
        target_proof = _native_shcde_check(
            Path(target_game), Path(target_xaml), target, plan["target_game_sha256"]
        )
        proofs = {"source_native_verified": True, "target_native_verified": True,
                  "source": source_proof, "target": target_proof,
                  "native_provenance_checked": True}
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="." + output.name + "-stage-", dir=output.parent))
    try:
        _copy_target_tree(target, stage, targets)
        details = []
        for row in selected:
            src, tgt = sources[row["source_key"]], targets[row["target_key"]]
            current = Path(src["path"])
            destination = stage / tgt["atlas"] / tgt["file"]
            if _sha(current) != row["source_png_sha256"]:
                raise BridgeError(f"SH1-Bild seit Planung verändert: {src['key']}")
            if _sha(destination) != row["target_png_sha256"]:
                raise BridgeError(f"SHCDE-Bild seit Planung verändert: {tgt['key']}")
            with Image.open(current) as original:
                if original.size != tuple(row["source_size"]):
                    raise BridgeError(f"SH1-Bildgröße geändert: {src['key']}")
                image = original.convert("RGBA")
            result = _fit_image(image, tuple(row["target_size"]), row["fit"])
            result.save(destination, format="PNG")
            with Image.open(destination) as reread:
                if reread.size != tuple(row["target_size"]) or (
                    reread.convert("RGBA").tobytes() != result.tobytes()
                ):
                    raise BridgeError("Gespeichertes Crusader-Bild hat falsche Pixel")
            details.append({
                "source_key": row["source_key"],
                "target_key": row["target_key"],
                "source_atlas": row["source_atlas"],
                "target_atlas": row["target_atlas"],
                "fit": row["fit"],
                "state_note": row.get("state_note", ""),
                "before_target_png_sha256": row["target_png_sha256"],
                "after_target_png_sha256": _sha(destination),
                "target_size": row["target_size"],
                "source_size": row["source_size"],
            })
        # Every unselected output PNG must be preserved *byte-for-byte*.
        altered = {row["target_key"] for row in selected}
        for key, entry in targets.items():
            if key not in altered and _sha(Path(entry["path"])) != _sha(
                stage / entry["atlas"] / entry["file"]
            ):
                raise BridgeError(f"Unbeteiligtes Crusader-Bild verändert: {key}")
        if (stage / "index.json").read_bytes() != (target / "index.json").read_bytes():
            raise BridgeError("Crusader-Index darf nicht verändert werden")
        opened = read_ui_preview_index(stage)
        if len(opened) != len(targets):
            raise BridgeError("Nach dem Kopieren fehlen Crusader-HUD-Bilder")
        report = {
            "schema": RESULT_SCHEMA,
            "source_export": str(source),
            "target_export": str(target),
            "source_game_sha256": plan["source_game_sha256"],
            "target_game_sha256": plan["target_game_sha256"],
            "target_index_sha256": plan["target_index_sha256"],
            "plan_sha256": _sha(under_work(plan_file)),
            "output_is_editable_crusader_export": True,
            "requires_crusader_atlas_check_and_import": True,
            "runtime_game_tested": False,
            "new_xaml_resources_created": False,
            "native_provenance": proofs,
            "transfers": details,
            "approved_transfers": details,  # Compatibility for older readers.
            "total_target_sprites": len(targets),
            "untouched_target_sprites": len(targets) - len(details),
        }
        (stage / "sh1_to_shcde_bridge.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if output.exists():
            raise BridgeError("Kandidaten-Ausgabe wurde inzwischen erstellt: keine Überschreibung")
        os.rename(stage, output)
        return report
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def verify_candidate(output: str | Path):
    """Validate later edits without discarding the transferred target contract."""
    output = under_work(output)
    report = _read_json(output / "sh1_to_shcde_bridge.json")
    if report.get("schema") != RESULT_SCHEMA:
        raise BridgeError("Kein SH1→SHCDE-Kandidatenbericht")
    index = output / "index.json"
    if _sha(index) != report["target_index_sha256"]:
        raise BridgeError("SHCDE-Zielkoordinaten seit dem Import verändert")
    entries = read_ui_preview_index(output)
    touched = {row["target_key"]: row for row in report["approved_transfers"]}
    modifications = []
    for item in entries:
        with Image.open(item["path"]) as open_image:
            if open_image.size != (item["width"], item["height"]):
                raise BridgeError(f"Crusader-Bild hat falsche Größe: {item['key']}")
            pixel = open_image.convert("RGBA")
        if item["key"] in touched:
            if _sha(Path(item["path"])) != touched[item["key"]]["after_target_png_sha256"]:
                modifications.append(item["key"])
    return {"target_crops_checked": len(entries),
            "transferred_crops": len(touched),
            "transferred_crops_further_edited": modifications,
            "target_geometry_unchanged": True,
            "in_game_certified": False}


def select_mappings(
    plan_path: str | Path, selections: list[dict], *, replace_selection: bool = True,
) -> list[dict]:
    """Select freely chosen source/target pairs in one autosaved operation.

    Every selection is an ordinary edit choice. Notes and prior semantic,
    visual, geometry or in-game approvals are never required.
    """
    plan, source, target, sources, targets = _validate_plan(Path(plan_path))
    if not isinstance(selections, list) or len(selections) > MAX_MAPPINGS:
        raise BridgeError("Auswahl muss eine Liste von Zuordnungen sein")
    if replace_selection:
        for row in plan["mapping"]:
            row["selected"] = False
    result = []
    occupied = set()
    for choice in selections:
        if not isinstance(choice, dict) or set(choice) - {"source_key", "target_key", "fit", "state_note"}:
            raise BridgeError("Auswahl enthält ungültige Zuordnungsfelder")
        source_key, target_key = choice.get("source_key"), choice.get("target_key")
        if source_key not in sources or target_key not in targets:
            raise BridgeError("SH1-Quell- oder SHCDE-Zielschlüssel fehlt")
        if target_key in occupied:
            raise BridgeError("Zielschlüssel mehrfach ausgewählt")
        occupied.add(target_key)
        row = _row(sources[source_key], targets[target_key], explicit_alias=source_key != target_key)
        fit = choice.get("fit", row["fit"])
        if fit not in FITS:
            raise BridgeError("Bitte exact, contain oder stretch wählen")
        if fit == "exact" and row["source_size"] != row["target_size"]:
            raise BridgeError("Ungleiche Größen erfordern contain oder stretch")
        note = choice.get("state_note", "")
        if not isinstance(note, str):
            raise BridgeError("Eine optionale Notiz muss Text sein")
        row.update(fit=fit, selected=True, state_note=note)
        existing = next((index for index, old in enumerate(plan["mapping"]) if old["target_key"] == target_key), None)
        if existing is None:
            plan["mapping"].append(row)
        else:
            plan["mapping"][existing] = row
        result.append(row)
    _validate_plan_rows_in_memory(plan, sources, targets)
    plan["coverage"].pop("approved", None)
    plan["coverage"]["selected"] = sum(row["selected"] for row in plan["mapping"])
    _save_plan(Path(plan_path), plan)
    return result


def select_mapping(
    plan_path: str | Path, source_key: str, target_key: str, *,
    fit: str = "exact", state_note: str = "",
) -> dict:
    return select_mappings(plan_path, [dict(source_key=source_key, target_key=target_key,
                                           fit=fit, state_note=state_note)], replace_selection=False)[0]


def approve_mapping(
    plan_path: str | Path, source_key: str, target_key: str, *,
    fit: str = "exact", state_note: str = "",
):
    """Compatibility spelling for select_mapping; no approval requirement."""
    return select_mapping(plan_path, source_key, target_key, fit=fit, state_note=state_note)


def _validate_plan_rows_in_memory(plan: dict, sources: dict, targets: dict):
    occupied = set()
    for row in plan["mapping"]:
        source_key, target_key = row["source_key"], row["target_key"]
        if source_key not in sources or target_key not in targets or target_key in occupied:
            raise BridgeError("Doppeltes oder unbekanntes SHCDE-Ziel im Plan")
        occupied.add(target_key)
        s, t = sources[source_key], targets[target_key]
        if row["source_png_sha256"] != _sha(Path(s["path"])) or row[
            "target_png_sha256"
        ] != _sha(Path(t["path"])):
            raise BridgeError("Eine Bilddatei wurde seit dem Plan verändert")
        if row["selected"] and (row["fit"] not in FITS or
                (row["fit"] == "exact" and row["source_size"] != row["target_size"])):
            raise BridgeError("Ausgewählte Grafik benötigt einen passenden Fit-Modus")


def revoke_mapping(plan_path: str | Path, target_key: str):
    plan, _source, _target, _sources, _targets = _validate_plan(Path(plan_path))
    rows = [row for row in plan["mapping"] if row["target_key"] == target_key]
    if len(rows) != 1:
        raise BridgeError("Zielzuordnung nicht gefunden")
    rows[0]["selected"] = False
    plan["coverage"].pop("approved", None)
    plan["coverage"]["selected"] = sum(x["selected"] for x in plan["mapping"])
    _save_plan(Path(plan_path), plan)
    return rows[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)

    p = subs.add_parser("plan", help="Quell-/Zielzuordnungen für freie Grafikauswahl vorbereiten")
    p.add_argument("--sh1", required=True, help="SH1-HUD-Arbeitsprojekt")
    p.add_argument("--shcde", required=True, help="SHCDE-ui_atlas-Export")
    p.add_argument("--out", required=True, help="Neues Mapping-JSON UNTER work")

    p = subs.add_parser("select", aliases=["approve"], help="Eine oder mehrere Grafiken direkt auswählen")
    p.add_argument("--plan", required=True)
    p.add_argument("--source-key", action="append", required=True)
    p.add_argument("--target-key", action="append", required=True)
    p.add_argument("--fit", choices=FITS, required=True)
    p.add_argument("--state-note", default="", help="Optionale Notiz, ohne Mindestlänge")

    p = subs.add_parser("revoke", help="Grafik aus der gespeicherten Auswahl nehmen")
    p.add_argument("--plan", required=True)
    p.add_argument("--target-key", required=True)

    p = subs.add_parser("apply", help="Ausgewählte Bilder direkt in einen NEUEN SHCDE-Zielexport übertragen")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--target-key", action="append", help="Direkte Mehrfachauswahl ohne vorherigen select-Aufruf")
    p.add_argument("--fit", choices=FITS, help="Fit-Modus für diese Auswahl")
    p.add_argument("--source-game", help="Native SH1-DE-Assetdatei")
    p.add_argument("--target-game", help="Native SHCDE-Assetdatei")
    p.add_argument("--target-xaml", help="Originaler SHCDE-Noesis-XAML-Ordner")
    p.add_argument("--offline-no-native", action="store_true",
                   help="Kompatibilitätsflag; ohne Originalquellen ist Übertragung standardmäßig offline")

    p = subs.add_parser("verify", help="Weiter bearbeitete SHCDE-Exportkopie prüfen")
    p.add_argument("--from", dest="folder", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            file = under_work(args.out, must_exist=False)
            if file.exists():
                raise BridgeError("Mapping-Datei bereits vorhanden: keine Überschreibung")
            document = create_plan(args.sh1, args.shcde)
            _save_plan(file, document)
            result = {"plan": str(file), "coverage": document["coverage"]}
        elif args.command in {"select", "approve"}:
            if len(args.source_key) != len(args.target_key):
                raise BridgeError("Gleich viele Quell- und Zielschlüssel angeben")
            result = select_mappings(args.plan, [dict(source_key=source, target_key=target,
                fit=args.fit, state_note=args.state_note) for source, target in zip(args.source_key, args.target_key)],
                replace_selection=False)
        elif args.command == "revoke":
            result = revoke_mapping(args.plan, args.target_key)
        elif args.command == "apply":
            result = apply_plan(
                args.plan, args.out,
                source_game=Path(args.source_game) if args.source_game else None,
                target_game=Path(args.target_game) if args.target_game else None,
                target_xaml=Path(args.target_xaml) if args.target_xaml else None,
                allow_offline=args.offline_no_native,
                target_keys=args.target_key, fit=args.fit,
            )
            result = {"candidate": str(under_work(args.out)),
                      "transfers": len(result["approved_transfers"]),
                      "native_provenance": result["native_provenance"]}
        else:
            result = verify_candidate(args.folder)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    except (BridgeError, HudError, UiPreviewIndexError, ValueError,
            OSError, TypeError, KeyError, RuntimeError) as exc:
        print(f"SH1_SHCDE_BRIDGE_ABGELEHNT: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
