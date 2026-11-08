#!/usr/bin/env python3
"""Author APIShared-compatible namespaced Lord/Map data without losing peers.

ModLord: sibling <name>.modlord.json beside .lordjson.
ModMap: root-level modmap.json inside the map's *appended* SE archive; this
module prepares the JSON but does not claim to edit the native map container.
All foreign GUID namespaces and unknown fields remain byte-semantically intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROLES = frozenset({"host", "per_player", "local"})
API_SHARED_ROLE_ATTRS = {
    "host": "SyncHostOnly",
    "per_player": "SyncPerPlayer",
    "local": "PresetLocal",
}


def read_document(path: Path) -> dict:
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError("Mod data root must be a JSON object")
    keys = [k.casefold() for k in document]
    if len(keys) != len(set(keys)):
        raise ValueError("Namespace keys collide case-insensitively")
    if any(not k or not isinstance(v, dict) for k, v in document.items()):
        raise ValueError("Every nonempty mod GUID owns a JSON object")
    return document


def namespace_file(lord: Path | None = None, map_archive_folder: Path | None = None) -> Path:
    if (lord is None) == (map_archive_folder is None):
        raise ValueError("Choose exactly one Lord or Map target")
    if lord is not None:
        file = Path(lord)
        if file.suffix.casefold() != ".lordjson":
            raise ValueError("Custom Lord source must be a .lordjson file")
        if not file.is_file():
            raise FileNotFoundError(file)
        return file.with_suffix(".modlord.json")
    path = Path(map_archive_folder)
    if not path.is_dir():
        raise NotADirectoryError(path)
    return path / "modmap.json"


def update_namespace(target: Path, guid: str, values: dict, *,
                     dry_run: bool = False) -> dict:
    if not isinstance(guid, str) or not guid.strip() or not isinstance(values, dict):
        raise ValueError("Provide a nonempty mod GUID and arbitrary object values")
    target = Path(target)
    before = read_document(target)
    existing = next((key for key in before if key.casefold() == guid.casefold()), None)
    key = existing or guid
    result = dict(before)
    result[key] = values
    raw = (json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    namespace_bytes = len(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    warnings = []
    if target.name.casefold().endswith(".modlord.json"):
        if len(raw) > 65536:
            warnings.append("APIShared ModLord reader documents a 64 KiB document limit.")
        if namespace_bytes > 16384:
            warnings.append("APIShared ModLord reader documents a 16 KiB compact namespace limit.")
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            original_bytes = target.read_bytes()
            digest = hashlib.sha256(original_bytes).hexdigest()
            backup = target.with_name(target.name + ".backup." + digest[:16])
            if not backup.exists():
                with backup.open("xb") as sink:
                    sink.write(original_bytes)
            elif backup.read_bytes() != original_bytes:
                raise ValueError("Existing backup has different content")
        scratch = target.with_name(target.name + ".pending")
        if scratch.exists():
            raise FileExistsError("Unresolved previous pending edit: " + str(scratch))
        with scratch.open("xb") as sink:
            sink.write(raw)
        scratch.replace(target)
    return {"target": str(target), "guid": key, "foreignNamespacesPreserved":
            len(before) - bool(existing), "documentBytes": len(raw),
            "namespaceBytes": namespace_bytes, "compatibilityWarnings": warnings,
            "written": not dry_run, "gameArchiveModified": False}


def settings_contract(spec: dict) -> dict:
    if not isinstance(spec, dict) or not isinstance(spec.get("settings"), list):
        raise ValueError("ModSettings contract requires a settings array")
    settings = []
    used = set()
    for prop in spec["settings"]:
        if not isinstance(prop, dict):
            raise ValueError("Each setting must be an object")
        name = prop.get("name")
        role = prop.get("role")
        if not isinstance(name, str) or not name.isidentifier() or name in used:
            raise ValueError("Setting names must be unique C#-compatible identifiers")
        if role not in ROLES:
            raise ValueError("Use role host, per_player or local")
        used.add(name)
        settings.append({
            "name": name, "role": role,
            "apiSharedAttribute": API_SHARED_ROLE_ATTRS[role],
            "valueType": prop.get("valueType", "string"),
            "defaultValue": prop.get("defaultValue"),
            "tooltip": prop.get("tooltip", ""),
        })
    return {
        "schema": "spritesuite.apishared.modsettings-authoring.v1",
        "settings": settings,
        "implementationTarget": "APIShared.ModSettings.PresetLobbyModSettingsViewModel",
        "registrationTarget": "LobbyModSettingsPresetRegistration.Register",
        "sameContractFor": ["lobby", "personal_presets", "map_and_trail_working_sources"],
        "networkAuthority": "host flags remain host-authoritative",
        "apiSharedRuntimeCompiled": False,
        "externalAPISharedAssemblyRequiredForLiveIntegration": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    for action in ("lord", "map"):
        item = subs.add_parser(action)
        item.add_argument("--guid", required=True)
        item.add_argument("--json", required=True, type=Path,
                          help="Your own JSON object; unknown fields are retained")
        item.add_argument("--lord", type=Path, required=True) if action == "lord" else item.add_argument("--map-archive-folder", type=Path, required=True)
        item.add_argument("--dry-run", action="store_true")
    contract = subs.add_parser("contract")
    contract.add_argument("--spec", type=Path, required=True)
    contract.add_argument("--output", type=Path)
    for action in ("inspect-lord", "inspect-map"):
        item = subs.add_parser(action)
        item.add_argument("--lord", type=Path, required=True) if action == "inspect-lord" else item.add_argument("--map-archive-folder", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action in ("lord", "map"):
            values = json.loads(args.json.read_text(encoding="utf-8-sig"))
            file = namespace_file(
                lord=args.lord if args.action == "lord" else None,
                map_archive_folder=args.map_archive_folder if args.action == "map" else None)
            outcome = update_namespace(file, args.guid, values, dry_run=args.dry_run)
        elif args.action == "contract":
            source = json.loads(args.spec.read_text(encoding="utf-8-sig"))
            outcome = settings_contract(source)
            if args.output:
                with args.output.open("x", encoding="utf-8") as target:
                    json.dump(outcome, target, ensure_ascii=False, indent=2)
        else:
            file = namespace_file(
                lord=args.lord if args.action == "inspect-lord" else None,
                map_archive_folder=args.map_archive_folder if args.action == "inspect-map" else None)
            outcome = {"file": str(file), "namespaces": read_document(file),
                       "gameModified": False}
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as err:
        print("SHCDE mod data: " + str(err), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
