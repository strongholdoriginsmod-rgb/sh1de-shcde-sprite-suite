"""Version-neutral, read-only game/Noesis/Script Extender capability survey.

Static structure and verified engine/library fingerprints are not proof of
runtime hook behavior. This tool never modifies game files or grants native
plugin installation rights. Optional --metadata performs a local C# Cecil
metadata probe in a NEW private QA folder (not the game directory).
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

EXPECTED={
 "unity_game":"Stronghold Crusader Definitive Edition_Data/Managed/Assembly-CSharp.dll",
 "noesis_managed":"Stronghold Crusader Definitive Edition_Data/Managed/Noesis.NoesisGUI.dll",
 "noesis_native":"Stronghold Crusader Definitive Edition_Data/Plugins/x86_64/Noesis.dll",
 "script_extender":"BepInEx/plugins/000shcdese/SHCDESE.dll",
 "frontend":"BepInEx/plugins/000shcdese/Override/Assets/GUI/XAML/FrontendMenus.xaml",
}
GUID="BepInEx/plugins/000shcdese/info.json"
XAMLROOT="BepInEx/plugins/000shcdese/Override/Assets/GUI"
REQUIRED_METADATA=(
 "HAS_FRONTEND_TYPE","FRONTEND_EXTENDS_NOESIS_USERCONTROL",
 "HAS_MENU_COMMAND_STRING_CALLBACK","HAS_NOESIS_FINDNAME",
 "HAS_BEPINEX_PLUGIN_HOST","HAS_HARMONY_PATCH_HOST",
 "HAS_METADATA_READER",
)


def _sha(path:Path)->str:
    h=sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def inspect(game:Path,*,metadata_out:Path|None=None)->dict:
    root=Path(game)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Missing or linked game root")
    root=root.resolve(strict=True)
    from hud_menu_noesis_integration import discover_grid_targets,WorkshopError
    checked={}
    for name,rel in EXPECTED.items():
        file=root.joinpath(*rel.split("/"))
        if file.is_symlink():
            raise ValueError("Linked native dependency: "+name)
        if file.is_file():
            checked[name]={"present":True,"bytes":file.stat().st_size,
                           "sha256":_sha(file)}
        else:
            checked[name]={"present":False}
    info=root.joinpath(*GUID.split("/"))
    version=None
    version_targets=[]
    if info.is_file() and not info.is_symlink():
        metadata=json.loads(info.read_text(encoding="utf-8"))
        if metadata.get("GUID")!="000shcdese":
            raise ValueError("Not the expected Script Extender plugin")
        version=str(metadata.get("Version",""))[:64]
        targets=metadata.get("SupportedGameVersions",[])
        if isinstance(targets,list):
            version_targets=[str(v)[:64] for v in targets[:20]]
    targets=[];source_error=None
    if (root/XAMLROOT).is_dir():
        try:
            for item in discover_grid_targets(root/XAMLROOT):
                targets.append({"document":item.xaml_document,
                                "grid":item.grid_name,
                                "kind":item.name_kind,
                                "sha256":item.source_sha256})
        except (WorkshopError,OSError) as exc:
            source_error=str(exc)[:500]
    result={
        "schema":"sprite-suite.native-game-structural-compat.v1",
        "game_root":str(root),
        "script_extender_version":version,
        "extender_declared_game_versions":version_targets,
        "sha_pinned_current_references":checked,
        "noesis_grid_target_count":len(targets),
        "noesis_xaml_documents":sorted(set(t["document"] for t in targets)),
        "noesis_targets":targets,
        "noesis_xml_errors":source_error,
        "game_was_executed":False,
        "game_originals_modified":False,
        "native_runtime_approved":False,
        "plugin_install_allowed_by_this_report":False,
    }
    if metadata_out is not None:
        folder=Path(metadata_out).resolve(strict=False)
        if folder.exists() or folder.is_symlink():
            raise ValueError("Metadata output must be a new directory")
        if folder.is_relative_to(root):
            raise ValueError("Metadata output must be outside game root")
        from origins_native_abi_probe import probe_installed_game
        probe=probe_installed_game(root,folder)
        result["metadata_check"]={
            "source_hashes":probe["source_hashes"],
            "signatures":probe["structural_signatures"],
            "missing":probe["missing_signatures"],
            "all_expected_structures":all(
                probe["structural_signatures"].get(key,False)
                for key in REQUIRED_METADATA),
            "abi_fully_attested":False,
            "evidence_file":probe["report"],
        }
    return result


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game",required=True,type=Path)
    parser.add_argument("--metadata-qa-dir",type=Path)
    parser.add_argument("--json-out",type=Path)
    options=parser.parse_args(argv)
    try:
        result=inspect(options.game,metadata_out=options.metadata_qa_dir)
        if options.json_out:
            if (options.json_out.exists() or options.json_out.is_symlink()
                    or options.json_out.resolve(strict=False).is_relative_to(
                            options.game.resolve(strict=True))):
                raise ValueError("Report must be a NEW output outside the game")
            options.json_out.parent.mkdir(parents=True,exist_ok=True)
            options.json_out.write_text(
                json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if (result["noesis_grid_target_count"]>0
                     and all(row["present"] for row in result[
                         "sha_pinned_current_references"].values())) else 2
    except (OSError,RuntimeError,ValueError,ImportError) as exc:
        print("NATIVE_CAPABILITY_SCAN_FAILED: "+str(exc),file=sys.stderr)
        return 3


if __name__=="__main__":
    raise SystemExit(main())
