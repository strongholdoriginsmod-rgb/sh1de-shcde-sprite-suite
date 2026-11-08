"""One strict analysis dispatcher for the twelve SpriteSuite Studio areas."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import assets, catalog, design, runtime
from .catalog import MODULE_IDS
from .model import validate_project
from .report import Report, report_all
from .safety import StudioError, canonical_root, read_json


def analyze(
    project_root: Path,
    project: object,
    only: str = "",
) -> dict[str, Any]:
    project = validate_project(project)
    workspace = canonical_root(project_root)
    if only and only not in MODULE_IDS:
        raise StudioError("requested analyzer does not exist: " + only)
    parts = project["modules"]
    targets = project["target"]
    known_cues = {
        entry["id"] for entry in parts["audio"]["cues"]
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    analyzers = {
        "sdk": lambda: runtime.sdk(parts["sdk"], targets),
        "mission": lambda: design.mission(parts["mission"], known_cues),
        "castle": lambda: design.castle(parts["castle"]),
        "hud": lambda: design.hud(parts["hud"], workspace),
        "balance": lambda: design.balance(parts["balance"]),
        "maps": lambda: assets.maps(parts["maps"], workspace),
        "lords": lambda: assets.lords(parts["lords"], workspace),
        "units": lambda: runtime.units(parts["units"]),
        "audio": lambda: assets.audio(parts["audio"], workspace),
        "saves": lambda: runtime.saves(parts["saves"]),
        "workshop": lambda: assets.workshop(parts["workshop"], workspace),
        "native": lambda: runtime.native(parts["native"], targets),
    }
    reports: dict[str, Report] = {}
    for module_id in MODULE_IDS:
        if only and module_id != only:
            continue
        try:
            reports[module_id] = analyzers[module_id]()
        except (StudioError, OSError, ValueError) as exc:
            report = Report(module_id)
            report.add("BLOCK", "MODULE_FAILED_CLOSED", str(exc))
            reports[module_id] = report
    result = report_all(reports)
    result["project_id"] = project["project_id"]
    result["revision"] = project["revision"]
    result["target"] = project["target"]
    result["scope"] = "offline_only_no_game_installation"
    return result


def analyze_suite_ui(suite_root: Path) -> dict[str, Any]:
    """Optional audit of the actual shipped Suite XAML vs committed BC7 list.

    This consumes no proprietary PNG bytes and never changes the suite.
    """
    from .design import _analyze_xaml
    from hashlib import sha256
    import json

    root = canonical_root(suite_root)
    config = read_json(root, "config/ui-textures-bc7-v1.json")
    if type(config) is not dict or "entries" not in config:
        raise StudioError("UI BC7 source list has an unsupported shape")
    entries = config["entries"]
    if type(entries) is not list:
        raise StudioError("UI BC7 source list entries are invalid")
    declared = config.get("expected_entry_count")
    if declared != len(entries) or len(entries) != 128:
        raise StudioError("UI BC7 committed source inventory is not 128 entries")
    wall = {
        item["noesis_path"]
        for item in entries
        if isinstance(item, dict)
        and isinstance(item.get("noesis_path"), str)
        and item["noesis_path"].startswith("Assets/GUI/Images/sede-wall-")
    }
    if len(wall) != 14:
        raise StudioError("14 wall texture identities are not present")
    bound = {}
    for relative in ("assets/xaml/HUD_Main.xaml",
                     "assets/xaml/HUD_Main.fortifications.xaml"):
        from .safety import read_text
        images, warnings = _analyze_xaml(read_text(root, relative, 2 * 1024 * 1024), relative)
        bound[relative] = {
            "matched_wall_uris": sorted(images & wall),
            "count": len(images & wall),
            "parser_warnings": warnings,
        }
    union = set().union(*(set(row["matched_wall_uris"]) for row in bound.values()))
    return {
        "schema": "spritesuite.modding-studio.suite-xaml-audit.v1",
        "source_count": len(entries),
        "wall_source_count": len(wall),
        "wall_referenced_count": len(union),
        "missing_wall_refs": sorted(wall - union),
        "files": bound,
        "runtime_compatibility": "not_established",
        "note": "Static URI appearance is not runtime loader demand; unreferenced PNGs are retained.",
    }
