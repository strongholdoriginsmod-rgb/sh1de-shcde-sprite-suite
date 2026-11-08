#!/usr/bin/env python3
"""One editable SHCDE modding project shared across graphics and game systems.

Stores arbitrary creator-owned settings and assets without constraining game
versions, file extensions or artwork approval. Generated project contracts
describe author intent; native gameplay changes require an installed runtime
adapter rather than being fabricated by the project editor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

from shcde_mod_composer import compose, entry_name, sha256_file

SCHEMA = "spritesuite.shcde.unified-modding-project.v1"
MANIFEST = "SpriteSuite-Project.json"
ASSETS = "Payload"
# Existing domain editors remain responsible for native/game-specific authoring.
DOMAINS = {
    "api": "SHCDE API and APIShared contracts",
    "native": "Serp Native Baseline and hook evidence",
    "modpack": "Asset and plugin composition",
    "building": "Building graphics, HP stages and fire damage",
    "aiv": "AI castle, AIV build steps and layouts",
    "aic": "AI personalities and Custom Lord data",
    "units": "Unit visuals, animations and combat attributes",
    "economy": "Buildings, market prices, costs and limits",
    "scenario": "Scenario triggers, script graphs and missions",
    "terrain": "Terrain, map layers and pathing geometry",
    "hud": "Noesis XAML, HUD and tooltips",
    "inspector": "In-game object snapshots",
    "audio": "Sound, effects and Custom Lord media",
    "multiplayer": "APIShared settings, presets and peer sync",
    "pathing": "AI paths, movement bottlenecks and diagnostic logs",
    "qa": "Build, runtime, visual and regression verification",
}
EDITORS = {
    "api": ["shcde_api_native_index.py"],
    "native": ["shcde_api_native_index.py"],
    "modpack": ["shcde_mod_composer.py", "se_asset_package.py", "shcde_mod_project.py"],
    "building": ["building_damage_bindings.py",
                 "suite_building_damage_live_mod.py",
                 "building_damage_original_reference.py", "shcde_gameplay_rules.py"],
    "aiv": ["shcde_aiv_lord_studio.py", "sandbox_studio.py"],
    "aic": ["shcde_aiv_lord_studio.py", "shcde_mod_settings.py", "se_asset_package.py"],
    "units": ["shcde_gameplay_rules.py", "unit_pipeline.py", "sprites.py"],
    "economy": ["shcde_gameplay_rules.py", "suite_native_game_capabilities.py"],
    "scenario": ["shcde_scenario_graph.py"],
    "terrain": ["sandbox_studio.py", "sandbox_gameplay_mode.py"],
    "hud": ["suite_hud_menu_workshop.py", "suite_origins_xaml_editor.py"],
    "inspector": ["shcde_game_inspector.py"],
    "audio": ["shcde_aiv_lord_studio.py", "se_asset_package.py"],
    "multiplayer": ["shcde_mod_settings.py"],
    "pathing": ["shcde_pathing_report.py"],
    "qa": ["shcde_qa_suite.py", "qa_building_damage_runtime.py"],
}


def make_project(directory: Path, *, name: str,
                 guid: str, version: str = "1.0.0",
                 author: str = "SpriteSuite Creator") -> dict:
    root = Path(directory)
    if root.exists():
        raise FileExistsError("Destination already exists: " + str(root))
    if not name.strip() or not guid.strip():
        raise ValueError("Project requires an editable name and mod GUID")
    root.mkdir(parents=True)
    payload = root / ASSETS
    payload.mkdir()
    info = {
        "GUID": guid, "Name": name, "Author": author,
        "Description": "Created with SpriteSuite SHCDE Workbench",
        "Version": version, "Manifest": 1, "NetworkMode": 1,
    }
    write_exclusive(payload / "info.json", json.dumps(info, ensure_ascii=False, indent=2) + "\n")
    data = {
        "schema": SCHEMA,
        "identity": info,
        "domains": {key: {} for key in DOMAINS},
        "assets": [],
        "sourceArchives": [],
        "gameVersionRequirements": [],
        "creativeStageApprovalsRequired": False,
    }
    write_exclusive(root / MANIFEST, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return data


def write_exclusive(path: Path, value: str) -> None:
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


def load_project(root: Path) -> dict:
    path = Path(root) / MANIFEST
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema") != SCHEMA:
        raise ValueError("Unknown SpriteSuite project schema")
    for key in ("domains", "assets", "sourceArchives", "identity"):
        if key not in data:
            raise ValueError("Incomplete project metadata: " + key)
    if not isinstance(data["domains"], dict) or not isinstance(data["assets"], list):
        raise ValueError("Invalid project domain/asset records")
    return data


def _save_project(root: Path, data: dict) -> None:
    path = Path(root) / MANIFEST
    raw = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    scratch = path.with_suffix(".pending")
    if scratch.exists():
        raise FileExistsError("Unresolved project write: " + str(scratch))
    write_exclusive(scratch, raw)
    try:
        scratch.replace(path)
    except BaseException:
        scratch.unlink(missing_ok=True)
        raise


def edit_domain(root: Path, domain: str, key: str, value: Any) -> dict:
    if not domain or domain not in DOMAINS:
        raise ValueError("Unknown project domain; use one of: " +
                         ", ".join(DOMAINS))
    if not key or any(part == "" for part in key.split(".")):
        raise ValueError("Provide an editable nonempty property path")
    doc = load_project(root)
    fields = doc["domains"].setdefault(domain, {})
    for part in key.split(".")[:-1]:
        field = fields.setdefault(part, {})
        if not isinstance(field, dict):
            raise ValueError("Cannot descend into a non-object property: " + part)
        fields = field
    fields[key.split(".")[-1]] = value
    _save_project(root, doc)
    return {"domain": domain, "property": key, "value": value}


def add_asset(root: Path, source: Path, destination: str) -> dict:
    path = Path(root)
    doc = load_project(path)
    target_name = entry_name(destination)
    src = Path(source).resolve(strict=True)
    if not src.is_file() or src.is_symlink():
        raise ValueError("Select a regular file to import")
    out = path / ASSETS / Path(*target_name.split("/"))
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise FileExistsError("This project already owns: " + target_name)
    # Creator-provided files can be .lua, .dll, .ogg, .aiv, .aic or custom.
    with src.open("rb") as inp, out.open("xb") as dest:
        shutil.copyfileobj(inp, dest, 1024 * 1024)
    try:
        record = {
            "path": target_name, "bytes": out.stat().st_size,
            "sha256": sha256_file(out), "sourceName": src.name,
            "gameAssetImportedNotExecuted": True,
        }
        doc["assets"].append(record)
        _save_project(path, doc)
        return record
    except BaseException:
        out.unlink(missing_ok=True)
        raise


def add_source_archive(root: Path, source: Path) -> dict:
    doc = load_project(root)
    path = Path(source).resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != ".zip":
        raise ValueError("External source must be an existing mod ZIP")
    item = {"path": str(path), "sha256": sha256_file(path)}
    if item not in doc["sourceArchives"]:
        doc["sourceArchives"].append(item)
        _save_project(root, doc)
    return item



def link_suite_project(root: Path, shared: Path) -> dict:
    """Use the main Suite's current assets directly when composing a mod."""
    # Keep a direct source-checkout invocation on the same local project
    # implementation as this tool, even when Python has another editable
    # Suite checkout installed.
    source = str(Path(__file__).resolve().parents[1] / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    from suite_unified_project import ProjectPipeline
    pipeline = ProjectPipeline(shared)
    if pipeline.project.resolve() == Path(root).resolve():
        raise ValueError("Choose the main editable asset project as the linked source")
    data = load_project(root)
    record = {"path": str(pipeline.project), "sharedAssetsRemainEditable": True}
    data["suiteProject"] = record
    _save_project(root, data)
    return record


def _shared_source(data: dict) -> Path | None:
    source = data.get("suiteProject")
    if source is None:
        return None
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        raise ValueError("Invalid shared Suite project link")
    import hud_menu_workspace
    shared = hud_menu_workspace.workspace(source["path"])
    if not shared.is_dir():
        raise ValueError("Linked Suite project is unavailable")
    return shared

def inspect_project(root: Path) -> dict:
    project = Path(root)
    doc = load_project(project)
    payload = project / ASSETS
    mismatches = []
    files = {item.get("path", ""): item for item in doc["assets"]}
    for name, record in files.items():
        try:
            file = payload / Path(*entry_name(name).split("/"))
            if not file.is_file() or sha256_file(file) != record.get("sha256"):
                mismatches.append({"path": name, "reason": "missing_or_changed"})
        except (ValueError, OSError):
            mismatches.append({"path": name, "reason": "invalid_path"})
    # Other creator-authored payload files (e.g. info.json) are supported.
    source_errors = []
    for item in doc["sourceArchives"]:
        source = Path(item.get("path", ""))
        if not source.is_file() or sha256_file(source) != item.get("sha256"):
            source_errors.append(str(source))
    shared_assets = []
    try:
        shared = _shared_source(doc)
        if shared is not None:
            import hud_menu_workspace
            shared_assets = [item.relative_path for item in
                             hud_menu_workspace.list_assets(shared, include_mod_files=True)]
    except (OSError, ValueError) as error:
        source_errors.append(str(error))
    return {
        "sharedSuiteProject": doc.get("suiteProject"),
        "sharedSuiteAssets": shared_assets,
        "schema": SCHEMA, "name": doc["identity"].get("Name"),
        "guid": doc["identity"].get("GUID"),
        "domainsWithData": sorted(name for name, value in doc["domains"].items() if value),
        "domainEditors": {
            domain: [
                {"script": editor, "present": (Path(__file__).parent / editor).is_file()}
                for editor in EDITORS.get(domain, ())
            ] for domain in DOMAINS
        },
        "recordedAssets": len(files), "assetIntegrityIssues": mismatches,
        "externalSourceIssues": source_errors,
        "projectIsGameExecutable": False,
        "modExportCanContainArbitraryFiles": True,
    }


def export_project(root: Path, output: Path, *, conflict_policy: str = "last") -> dict:
    data = load_project(root)
    report = inspect_project(root)
    if report["assetIntegrityIssues"] or report["externalSourceIssues"]:
        raise ValueError("Changed or missing source files; inspect the report first")
    inputs = [Path(root) / ASSETS]
    shared = _shared_source(data)
    if shared is not None and any(shared.iterdir()):
        inputs.append(shared)
    inputs.extend(Path(item["path"]) for item in data["sourceArchives"])
    result = compose(inputs, output, policy=conflict_policy)
    return {"project": str(root), "modZip": result["zip"],
            "sha256": result["sha256"], "conflicts": result["conflicts"],
            "files": result["files"], "gameModified": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    create = subs.add_parser("new")
    create.add_argument("--directory", type=Path, required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--guid", required=True)
    create.add_argument("--version", default="1.0.0")
    create.add_argument("--author", default="SpriteSuite Creator")
    for action in ("inspect", "set", "asset", "source", "link-suite", "export"):
        item = subs.add_parser(action)
        item.add_argument("--project", type=Path, required=True)
        if action == "set":
            item.add_argument("--domain", choices=tuple(DOMAINS), required=True)
            item.add_argument("--key", required=True)
            item.add_argument("--json-value", required=True,
                              help="JSON scalar, array, object or string")
        elif action == "asset":
            item.add_argument("--file", type=Path, required=True)
            item.add_argument("--target", required=True,
                              help="Relative desired mod asset name, any extension")
        elif action == "source":
            item.add_argument("--archive", type=Path, required=True)
        elif action == "link-suite":
            item.add_argument("--suite-project", type=Path, required=True)
        elif action == "export":
            item.add_argument("--output", type=Path, required=True)
            item.add_argument("--conflicts", choices=("first", "last", "error"),
                              default="last")
    args = parser.parse_args(argv)
    try:
        if args.action == "new":
            result = make_project(args.directory, name=args.name,
                                  guid=args.guid, version=args.version,
                                  author=args.author)
        elif args.action == "inspect":
            result = inspect_project(args.project)
        elif args.action == "set":
            result = edit_domain(args.project, args.domain, args.key,
                                 json.loads(args.json_value))
        elif args.action == "asset":
            result = add_asset(args.project, args.file, args.target)
        elif args.action == "source":
            result = add_source_archive(args.project, args.archive)
        elif args.action == "link-suite":
            result = link_suite_project(args.project, args.suite_project)
        else:
            result = export_project(args.project, args.output,
                                    conflict_policy=args.conflicts)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print("SpriteSuite project: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
