"""Read the installed Steam Unity target inventory into a private, unapproved QA workspace.

This tool never creates or changes a file under Steam. It does not reuse a
2.80 sprite mapping and does not authorize mod builds or native ABI calls.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

from stronghold_europe_de.unity_inventory import (
    scan_resources_assets, write_inventory, inventory_summary,
)
from target_selection_guard import inspect_target, TargetSelectionError
from suite_windows_paths import is_link_or_reparse
from suite_steam_compatibility import discover_steam_games


def digest(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def reimport_target(game: Path, repo: Path, output: Path) -> dict:
    """Rebuild Steam target inventory, with staged output and changed-source refusal."""
    root = Path(game).resolve(strict=True)
    project = Path(repo).resolve(strict=True)
    destination = Path(output).resolve(strict=False)
    if not root.is_dir() or root.name != "Stronghold Crusader Definitive Edition":
        raise ValueError("Select the installed Steam game root")
    if destination.exists():
        raise ValueError("Do not replace an existing Steam reference inventory")
    if destination == root or root in destination.parents:
        raise ValueError("Never write to the Steam game")
    if project / "work" not in destination.parents:
        raise ValueError("The output must be inside the isolated work directory")
    if any(is_link_or_reparse(path) for path in
           (destination, destination.parent, project / "work")):
        raise ValueError("Refuse a linked destination")
    steam_assets = root / "Stronghold Crusader Definitive Edition_Data" / "resources.assets"
    before = digest(steam_assets)
    att = inspect_target(root, project / "config" / "supported-builds.json")
    print("STEAM_TARGET_SHA", att.build_id, flush=True)
    print("STEAM_RESOURCES_SHA", before, flush=True)
    started = time.monotonic()
    inventory = scan_resources_assets(steam_assets, "target")
    print("UNITY_TARGET_INVENTORY", inventory_summary(inventory), flush=True)
    after = digest(steam_assets)
    if before != after:
        raise ValueError("Steam Unity resource changed while reading; refusing publication")
    att_after = inspect_target(root, project / "config" / "supported-builds.json")
    if att_after.build_id != att.build_id:
        raise ValueError("Game updated while reading; refusing an invalid inventory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_inventory(inventory, destination)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    if not destination.is_file():
        raise RuntimeError("Target inventory missing after publication")
    report={
        "schema":"sprite-suite.steam-target-inventory.v1",
        "target_build_id":att.build_id,
        "source_game":"Steam AppID 3024040 / current local installed build",
        "steam_resources_sha256":before,
        "inventory_sha256":digest(destination),
        "sprite_count":len(inventory["sprites"]),
        "texture_count":len(inventory["textures"]),
        "audio_count":len(inventory["audio_clips"]),
        "read_seconds":round(time.monotonic()-started,2),
        "steam_original_unchanged":True,
        "new_mapping_generated":False,
        "native_abi_verified":False,
        "mod_install_authorized":False,
    }
    evidence=destination.with_suffix(".evidence.json")
    with evidence.open("x",encoding="utf8") as handle:
        json.dump(report,handle,ensure_ascii=False,indent=2)
        handle.write("\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game",required=True,type=Path)
    parser.add_argument("--project",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args(argv)
    result=reimport_target(args.game,args.project,args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
