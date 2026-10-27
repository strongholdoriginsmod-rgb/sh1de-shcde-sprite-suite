"""Explicit SH1-HUD -> SHCDE-UI crop bridge; never writes to games.

The SHCDE XAML rectangles and atlas geometry remain authoritative. This does
not create new Noesis resources, import new HUD states or prove gameplay parity.
Mappings require a human's semantic approval; mismatched geometry requires
separate explicit approval. All unselected target crops remain byte-for-byte.
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
        "fit": "exact" if same else "skip",
        "approved": False,
        "semantic_reviewed": False,
        "geometry_reviewed": False,
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
            "approved": 0, "notes": (
                "Keine automatische Semantikfreigabe. Fehlende SHCDE-Schlüssel "
                "benötigen eine explizite Zielzuordnung oder neue XAML/Noesis-Logik."
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
        for key in ("approved", "semantic_reviewed", "geometry_reviewed", "explicit_alias"):
            if type(row.get(key)) is not bool:
                raise BridgeError(f"{row['target_key']}: {key} muss bool sein")
        if row["source_key"] != row["target_key"] and not row["explicit_alias"]:
            raise BridgeError("Aliase müssen ausdrücklich als solche markiert sein")
        if row["fit"] == "exact" and row["source_size"] != row["target_size"]:
            if row["approved"]:
                raise BridgeError(f"{row['target_key']}: Größenkonflikt darf nicht exakt kopiert werden")
        if row["approved"] and (not row["semantic_reviewed"] or row["fit"] == "skip"
                               or (row["fit"] != "exact" and not row["geometry_reviewed"])):
            raise BridgeError(f"{row['target_key']}: Funktions- oder Größenfreigabe fehlt")
    return plan, source, target, sources, targets


def _fit_image(image: Image.Image, target_size: tuple[int, int], mode: str) -> Image.Image:
    if mode == "exact":
        if image.size != target_size:
            raise BridgeError("Exakter Modus erfordert identische Pixelmaße")
        return image.copy()
    width, height = target_size
    if mode == "stretch":
        return image.resize(target_size, Image.Resampling.LANCZOS)
    if mode != "contain":
        raise BridgeError("Unbekannter Geometriemodus")
    factor = min(width / image.width, height / image.height)
    new_size = (max(1, min(width, round(image.width * factor))),
                max(1, min(height, round(image.height * factor))))
    scaled = image.resize(new_size, Image.Resampling.LANCZOS)
    result = Image.new("RGBA", target_size, (0, 0, 0, 0))
    result.alpha_composite(scaled, ((width - new_size[0]) // 2,
                                    (height - new_size[1]) // 2))
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
    approved = [row for row in plan["mapping"] if row["approved"]]
    if not approved:
        raise BridgeError("Kein Element fachlich freigegeben; keine automatische Übernahme")
    if len(approved) > MAX_MAPPINGS:
        raise BridgeError("Zu viele Elementfreigaben")
    if allow_offline:
        if any(item is not None for item in (source_game, target_game, target_xaml)):
            raise BridgeError("Offline-Modus niemals mit Teilnachweisen mischen")
        proofs: dict = {"source_native_verified": False, "target_native_verified": False,
                        "offline_only_not_release_approved": True}
    else:
        if source_game is None or target_game is None or target_xaml is None:
            raise BridgeError(
                "Für eine quellgebundene Übertragung SH1-Asset, SHCDE-Asset "
                "und SHCDE-XAML-Ordner übergeben"
            )
        source_proof = _native_sh1_check(Path(source_game), source, plan["source_game_sha256"])
        target_proof = _native_shcde_check(
            Path(target_game), Path(target_xaml), target, plan["target_game_sha256"]
        )
        proofs = {"source_native_verified": True, "target_native_verified": True,
                  "source": source_proof, "target": target_proof,
                  "offline_only_not_release_approved": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="." + output.name + "-stage-", dir=output.parent))
    try:
        _copy_target_tree(target, stage, targets)
        details = []
        for row in approved:
            src, tgt = sources[row["source_key"]], targets[row["target_key"]]
            current = Path(src["path"])
            destination = stage / tgt["atlas"] / tgt["file"]
            if _sha(current) != row["source_png_sha256"]:
                raise BridgeError(f"SH1-Bild seit Freigabe verändert: {src['key']}")
            if _sha(destination) != row["target_png_sha256"]:
                raise BridgeError(f"SHCDE-Bild seit Freigabe verändert: {tgt['key']}")
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
                "semantic_reviewed": True,
                "geometry_reviewed": row["geometry_reviewed"],
            })
        # Every unselected output PNG must be preserved *byte-for-byte*.
        altered = {row["target_key"] for row in approved}
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
            "approved_transfers": details,
            "total_target_sprites": len(targets),
            "untouched_target_sprites": len(targets) - len(details),
        }
        (stage / "sh1_to_shcde_bridge.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(stage, output)
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


def approve_mapping(
    plan_path: str | Path, source_key: str, target_key: str, *,
    fit: str, state_note: str,
):
    """Approve exactly one named mapping; names alone are never enough."""
    if fit not in FITS:
        raise BridgeError("Bitte einen der Modi exact, contain oder stretch wählen")
    if len(state_note.strip()) < 8:
        raise BridgeError("Fachliche Element-/Zustandsbegründung (mind. 8 Zeichen) fehlt")
    plan, source, target, sources, targets = _validate_plan(Path(plan_path))
    if source_key not in sources or target_key not in targets:
        raise BridgeError("SH1-Quell- oder SHCDE-Zielschlüssel fehlt")
    matching = [
        row for row in plan["mapping"] if row["target_key"] == target_key
    ]
    if len(matching) > 1:
        raise BridgeError("Zielschlüssel mehrfach vorhanden")
    if matching:
        if matching[0]["source_key"] != source_key:
            raise BridgeError("Ziel bereits anderweitig zugeordnet")
        row = matching[0]
    else:
        row = _row(sources[source_key], targets[target_key], explicit_alias=True)
        plan["mapping"].append(row)
    if fit == "exact" and row["source_size"] != row["target_size"]:
        raise BridgeError("Ungleiche Größen erfordern bewusstes contain oder stretch")
    row.update({
        "fit": fit, "approved": True, "semantic_reviewed": True,
        "geometry_reviewed": fit != "exact",
        "state_note": state_note.strip(),
    })
    # Format, paths, disjoint trees, source PNG digests and target PNG digests
    # are all checked again before accepting the approval.
    _validate_plan_rows_in_memory(plan, sources, targets)
    plan["coverage"]["approved"] = sum(x["approved"] for x in plan["mapping"])
    _save_plan(Path(plan_path), plan)
    return row


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
        if row["approved"] and (not row["semantic_reviewed"]
                                or row["fit"] == "skip"
                                or (row["fit"] != "exact" and not row["geometry_reviewed"])):
            raise BridgeError("Freigabe ohne vollständige Prüfung")


def revoke_mapping(plan_path: str | Path, target_key: str):
    plan, _source, _target, _sources, _targets = _validate_plan(Path(plan_path))
    rows = [row for row in plan["mapping"] if row["target_key"] == target_key]
    if len(rows) != 1:
        raise BridgeError("Zielzuordnung nicht gefunden")
    rows[0].update({"approved": False, "semantic_reviewed": False,
                    "geometry_reviewed": False, "fit": "skip"})
    plan["coverage"]["approved"] = sum(x["approved"] for x in plan["mapping"])
    _save_plan(Path(plan_path), plan)
    return rows[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)

    p = subs.add_parser("plan", help="Nur Zuordnungsvorschläge; keine automatischen Freigaben")
    p.add_argument("--sh1", required=True, help="SH1-HUD-Arbeitsprojekt")
    p.add_argument("--shcde", required=True, help="SHCDE-ui_atlas-Export")
    p.add_argument("--out", required=True, help="Neues Mapping-JSON UNTER work")

    p = subs.add_parser("approve", help="Bestätigte einzelne Zuordnung in den Plan aufnehmen")
    p.add_argument("--plan", required=True)
    p.add_argument("--source-key", required=True)
    p.add_argument("--target-key", required=True)
    p.add_argument("--fit", choices=FITS, required=True)
    p.add_argument("--state-note", required=True,
                   help="Manuell geprüfte Funktion/Zustand des Zielslots")

    p = subs.add_parser("revoke", help="Zuordnung sperren")
    p.add_argument("--plan", required=True)
    p.add_argument("--target-key", required=True)

    p = subs.add_parser("apply", help="Genehmigte Bilder in einen NEUEN SHCDE-Zielexport übertragen")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--source-game", help="Native SH1-DE-Assetdatei")
    p.add_argument("--target-game", help="Native SHCDE-Assetdatei")
    p.add_argument("--target-xaml", help="Originaler SHCDE-Noesis-XAML-Ordner")
    p.add_argument("--offline-no-native", action="store_true",
                   help="Nur synthetisches Offline-QA; ausdrücklich keine Releasefreigabe")

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
        elif args.command == "approve":
            result = approve_mapping(args.plan, args.source_key, args.target_key,
                                     fit=args.fit, state_note=args.state_note)
        elif args.command == "revoke":
            result = revoke_mapping(args.plan, args.target_key)
        elif args.command == "apply":
            result = apply_plan(
                args.plan, args.out,
                source_game=Path(args.source_game) if args.source_game else None,
                target_game=Path(args.target_game) if args.target_game else None,
                target_xaml=Path(args.target_xaml) if args.target_xaml else None,
                allow_offline=args.offline_no_native,
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
