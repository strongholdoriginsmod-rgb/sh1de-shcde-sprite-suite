"""Build, attest, install and safely roll back SpriteSuite's native BepInEx plugin.

Only the EXACT pinned SHCDE installation is supported. Installation creates a
new folder in BepInEx/plugins/ and NEVER overwrites existing game files,
XAML, other mods or the Script Extender. A private backup and SHA-256 receipt
are recorded before activation. Live runtime proof is a separate game launch.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

from origins_live_patch import build_native_menu_patch,verify_original_xpaths
from origins_runtime_authoring import (
    campaign_csharp_source,season_csharp_source,validate_campaign,
)
from origins_native_abi_probe import CSC
from suite_windows_csharp_scratch import short_csharp_scratch

ROOT=Path(__file__).resolve().parents[1]
PLUGIN_FOLDER="SpriteSuite_Origins_Live_20261101"
GAME_REL={
    "game":"Stronghold Crusader Definitive Edition_Data/Managed/Assembly-CSharp.dll",
    "noesis_managed":"Stronghold Crusader Definitive Edition_Data/Managed/Noesis.NoesisGUI.dll",
    "noesis_native":"Stronghold Crusader Definitive Edition_Data/Plugins/x86_64/Noesis.dll",
    "script_extender":"BepInEx/plugins/000shcdese/SHCDESE.dll",
    "frontend":"BepInEx/plugins/000shcdese/Override/Assets/GUI/XAML/FrontendMenus.xaml",
}
APPROVED_SHA={
    "game":"01da4c57f8a0e04a77804e78f79bacb1ae63d934d6d391f0dcaf3742bcca5de3",
    "noesis_managed":"98476d3ca84ae0f2dcfbaddcc64b01a1f65474bd44402673fd6856d1b5347648",
    "noesis_native":"0e33dcca88c19ea744be3aaf45904f4ac525fc646fc7549b02c1a730d50a9233",
    "script_extender":"20543f2eb7cba4a25298493ec51efc3a5a12af55252bef23566e047f6c0827a4",
    "frontend":"a803f69596bc4f8d2f8d04263e7d27acf2d64b5ed5b40fbacea95154e39d4e62",
}
CS_FILES=[
    "runtime/SpriteSuite.Origins.Authoring/OriginsRuntimeCore.cs",
    "runtime/SpriteSuite.Origins.Authoring/OriginsNativeLivePlugin.cs",
]
REFS=[
    "BepInEx/core/BepInEx.dll",
    "BepInEx/core/0Harmony.dll",
    "BepInEx/plugins/000shcdese/SHCDESE.dll",
    "BepInEx/plugins/000shcdese/R3.dll",
    "BepInEx/plugins/000shcdese/netstandard.dll",
]+["Stronghold Crusader Definitive Edition_Data/Managed/"+f for f in (
     "Assembly-CSharp.dll","Noesis.NoesisGUI.dll","UnityEngine.dll",
     "UnityEngine.CoreModule.dll","UnityEngine.ScreenCaptureModule.dll",
     "UnityEngine.ImageConversionModule.dll","Unity.InputSystem.dll",
     "UnityEngine.UI.dll",
)]
PROBE=ROOT/"tests"/"sandbox"/"origins_live_metadata_probe.cs"


class LiveInstallError(RuntimeError):pass


def _digest(file:Path)->str:
    h=sha256()
    with file.open("rb") as source:
        for block in iter(lambda:source.read(4*1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def _inside(root:Path,rel:str)->Path:
    file=root.joinpath(*rel.split("/"))
    if not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(root.resolve()):
        raise LiveInstallError("Missing or linked game reference: "+rel)
    return file


def preflight_game(game:Path)->dict:
    base=Path(game).resolve(strict=True)
    if not base.is_dir() or base.is_symlink():
        raise LiveInstallError("Game directory is missing or linked")
    refs={key:_inside(base,rel) for key,rel in GAME_REL.items()}
    actual={key:_digest(path) for key,path in refs.items()}
    if actual!=APPROVED_SHA:
        raise LiveInstallError("Installed game/Noesis/Extender hashes differ; refusing unsafe plugin: "+
                               repr({k:(APPROVED_SHA[k],v) for k,v in actual.items()
                                     if v!=APPROVED_SHA[k]}))
    if not (base/"Stronghold Crusader Definitive Edition_Data"/
            "StreamingAssets"/"Maps"/"Antioch.map").is_file():
        raise LiveInstallError("Native map source missing from approved install")
    info=json.loads(_inside(base,"BepInEx/plugins/000shcdese/info.json").read_text("utf8"))
    if info.get("Version")!="2.10.4" or info.get("SupportedGameVersions")!=["2.8.0.2"]:
        raise LiveInstallError("Unsupported Script Extender version")
    names=verify_original_xpaths(refs["frontend"])
    return {"game_root":str(base),"original_sha256":actual,
            "original_gui":names,"script_extender_version":info["Version"],
            "originals_modified":False}


def _safe_project_output(value:Path)->Path:
    output=Path(value).resolve(strict=False)
    workspace=(ROOT/"work").resolve()
    if not output.is_relative_to(workspace) or output==workspace:
        raise LiveInstallError("Build/QA artifacts must remain in SpriteSuite/work")
    if output.exists() or output.is_symlink():
        raise LiveInstallError("Unique private build directory required")
    return output


def build_bundle(game:Path,output:Path)->dict:
    if os.name!="nt" or not CSC.is_file():
        raise LiveInstallError("Native Windows C# compiler unavailable")
    check=preflight_game(game)
    base=Path(check["game_root"])
    destination=_safe_project_output(output)
    approved_map="Antioch.map"
    plan=validate_campaign({"name":"spritesuite-live",
             "title":"SpriteSuite Origins",
             "missions":[{"number":1,"title":"Antioch",
                          "map":approved_map,"act":"Einführung"}]})
    sources=[ROOT/x for x in CS_FILES]
    if any(not p.is_file() or p.is_symlink() for p in sources+[PROBE]):
        raise LiveInstallError("Audited native C# sources absent")
    source_hash={str(p.relative_to(ROOT)):_digest(p) for p in sources+[PROBE]}
    patch=build_native_menu_patch(plan,base/GAME_REL["frontend"])
    generated_campaign=campaign_csharp_source(plan)
    generated_season=season_csharp_source("spritesuite-winter",[approved_map])
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix=".spritesuite-live-stage-",dir=destination.parent))
    try:
        package=stage/PLUGIN_FOLDER
        patch_file=package/"Patches"/"Assets"/"GUI"/"XAML"/"FrontendMenus.xaml"
        patch_file.parent.mkdir(parents=True)
        patch_file.write_bytes(patch)
        (package/"info.json").write_text(json.dumps({
             "GUID":"spritesuiteoriginslive",
             "Author":"SpriteSuite",
             "Name":"SpriteSuite Origins Native Bridge",
             "Description":"Native menu, source-verified mission entry and Noesis frame bridge",
             "Version":"0.2.0",
             "Dependencies":[{"GUID":"000shcdese","MinimumVersion":"2.10.4"}],
             "Manifest":1,"NetworkMode":1,
        },indent=2)+"\n",encoding="utf8")
        # Do not bundle SHCDESE or Unity DLLs, or redistribute game assets.
        with short_csharp_scratch() as scratch:
            generated=scratch/"AuthoredCampaign.g.cs"
            generated.write_bytes(generated_campaign)
            season=scratch/"AuthoredSeasons.g.cs"
            season.write_bytes(generated_season)
            binary=scratch/"SpriteSuite.Origins.Live.dll"
            cmd=[str(CSC),"/nologo","/target:library","/optimize+",
                 "/out:"+str(binary)]
            cmd.extend("/reference:"+str(_inside(base,x)) for x in REFS)
            cmd.extend(str(x) for x in sources)
            cmd.extend([str(generated),str(season)])
            run=subprocess.run(cmd,cwd=scratch,capture_output=True,
                    text=True,errors="replace",timeout=65,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            (stage/"compile.log").write_text(run.stdout+run.stderr,encoding="utf8")
            if run.returncode or not binary.is_file():
                raise LiveInstallError("Native BepInEx C# compile failed: "+
                                       (run.stdout+run.stderr)[-1600:])
            shutil.copyfile(binary,package/binary.name)
            if _digest(binary)!=_digest(package/binary.name):
                raise LiveInstallError("Native binary changed during copying")
            # Cecil pure-metadata verifier: this does not execute game code.
            copy_cecil=scratch/"Mono.Cecil.dll"
            shutil.copyfile(_inside(base,"BepInEx/core/Mono.Cecil.dll"),copy_cecil)
            verifier=scratch/"OriginsLiveMetadata.exe"
            check_cmd=[str(CSC),"/nologo","/target:exe",
                       "/out:"+str(verifier),"/reference:"+str(copy_cecil),str(PROBE)]
            check_compile=subprocess.run(check_cmd,cwd=scratch,capture_output=True,
                   text=True,errors="replace",timeout=40,
                   creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if check_compile.returncode:
                raise LiveInstallError("Native Cecil verifier did not compile: "+
                                       (check_compile.stdout+check_compile.stderr)[-1000:])
            cecil=subprocess.run([str(verifier),str(binary)],cwd=scratch,
                    capture_output=True,text=True,errors="replace",timeout=40,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            (stage/"native-metadata.log").write_text(
                   cecil.stdout+cecil.stderr,encoding="utf8")
            if cecil.returncode or "LIVE_ORIGINAL_GAME_MAP_LOADER_CALL=1" not in cecil.stdout:
                raise LiveInstallError("Native plugin Cecil attestation failed: "+cecil.stderr[-1100:])
        if preflight_game(base)["original_sha256"]!=check["original_sha256"]:
            raise LiveInstallError("Installed game references changed during build")
        if any(_digest(ROOT/p)!=value for p,value in source_hash.items()):
            raise LiveInstallError("C# source changed during build")
        backup=stage/"original-game-backups"
        backup.mkdir()
        for name in ("game","frontend"):
            shutil.copyfile(base/GAME_REL[name],backup/Path(GAME_REL[name]).name)
            if _digest(backup/Path(GAME_REL[name]).name)!=APPROVED_SHA[name]:
                raise LiveInstallError("Game source backup failed integrity")
        manifest={
            "schema":"sprite-suite.origins-native-live-install-candidate.v1",
            "source_commit":subprocess.run(
               ["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,
               text=True,timeout=5).stdout.strip(),
            "game_root":str(base),
            "game_originals_sha256":check["original_sha256"],
            "plugin_contents_sha256":{
                f.relative_to(package).as_posix():_digest(f)
                for f in package.rglob("*") if f.is_file()},
            "patch_anchors":check["original_gui"],
            "source_files_sha256":source_hash,
            "generated_campaign_sha256":sha256(generated_campaign).hexdigest(),
            "generated_season_sha256":sha256(generated_season).hexdigest(),
            "native_plugin_compiles":True,
            "compiled_native_plugin_metadata_attested":True,
            "native_plugin_loaded_in_running_game":False,
            "actual_native_noesis_frame_attested":False,
            "actual_map_start_attested":False,
            "actual_season_atlas_swap_attested":False,
            "game_installation_modified":False,
        }
        (stage/"build-receipt.json").write_text(json.dumps(
            manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        os.rename(stage,destination)
    finally:
        if stage.exists() and not stage.is_symlink():
            shutil.rmtree(stage)
    return {"bundle":str(destination/PLUGIN_FOLDER),
            "receipt":str(destination/"build-receipt.json"),**manifest}


def activate_bundle(bundle:Path,game:Path)->dict:
    check=preflight_game(game)
    base=Path(check["game_root"])
    data=Path(bundle)
    if data.name!=PLUGIN_FOLDER or not data.is_dir() or data.is_symlink():
        raise LiveInstallError("Unexpected or linked SpriteSuite plugin bundle")
    receipt=data.parent/"build-receipt.json"
    proof=json.loads(receipt.read_text("utf8"))
    if proof.get("game_originals_sha256")!=check["original_sha256"]:
        raise LiveInstallError("Built against a different game revision")
    for rel,digest in proof["plugin_contents_sha256"].items():
        file=data/rel
        if not file.is_file() or file.is_symlink() or _digest(file)!=digest:
            raise LiveInstallError("Pre-activation plugin file missing/changed: "+rel)
    root=base/"BepInEx"/"plugins"
    final=root/PLUGIN_FOLDER
    if final.exists() or final.is_symlink():
        raise LiveInstallError("Game plugin already exists; refuse overwrite")
    stage=root/(".spritesuite-installing-"+uuid4().hex[:12])
    try:
        shutil.copytree(data,stage)
        for rel,digest in proof["plugin_contents_sha256"].items():
            if _digest(stage/rel)!=digest:
                raise LiveInstallError("Installed staging bytes differ: "+rel)
        os.rename(stage,final)
    finally:
        if stage.exists() and not stage.is_symlink():shutil.rmtree(stage)
    after=preflight_game(base)
    if after["original_sha256"]!=check["original_sha256"]:
        raise LiveInstallError("Game originals unexpectedly changed")
    status={
        "schema":"sprite-suite.native-plugin-activation.v1",
        "installed":True,"installed_game_directory":str(base),
        "installed_plugin":str(final),
        "package":str(data),
        "original_game_sha256":check["original_sha256"],
        "installed_plugin_sha256":proof["plugin_contents_sha256"],
        "game_originals_unmodified":True,
        "actual_game_runtime_plugin_loaded":False,
        "actual_game_runtime_menu_verified":False,
        "actual_game_runtime_map_and_season_verified":False,
        "actual_noesis_native_render_verified":False,
        "rollback_command":"python tools/origins_native_live_install.py --rollback --game "+str(base),
    }
    (data.parent/"install-receipt.json").write_text(
        json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return status


def rollback(game:Path)->dict:
    check=preflight_game(game)
    base=Path(check["game_root"])
    target=base/"BepInEx"/"plugins"/PLUGIN_FOLDER
    if not target.is_dir() or target.is_symlink():
        raise LiveInstallError("No regular SpriteSuite live plugin installation to rollback")
    manifests=sorted((ROOT/"work").glob("**/install-receipt.json"))
    matching=[]
    for receipt in manifests:
        if receipt.is_symlink() or not receipt.resolve().is_relative_to((ROOT/"work").resolve()):
            continue
        item=json.loads(receipt.read_text("utf8"))
        if (item.get("installed") is True and
            item.get("installed_plugin")==str(target) and
            item.get("original_game_sha256")==check["original_sha256"]):
            matching.append((receipt,item))
    if len(matching)!=1:
        raise LiveInstallError("Rollback receipt is ambiguous or missing")
    receipt,item=matching[0]
    expected=item["installed_plugin_sha256"]
    if any(p.is_symlink() for p in target.rglob("*")):
        raise LiveInstallError("Linked file under installed plugin; rollback refused")
    actual={p.relative_to(target).as_posix():_digest(p)
            for p in target.rglob("*") if p.is_file()}
    if actual!=expected:
        raise LiveInstallError("User changed installed plugin; refusing destructive rollback")
    hidden=target.parent/(".spritesuite-removing-"+uuid4().hex[:12])
    os.rename(target,hidden)
    shutil.rmtree(hidden)
    item["installed"]=False
    item["rolled_back"]=True
    item["game_originals_unmodified"]=preflight_game(base)["original_sha256"]==check["original_sha256"]
    receipt.write_text(json.dumps(item,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return item


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    actions=p.add_mutually_exclusive_group(required=True)
    actions.add_argument("--build",action="store_true")
    actions.add_argument("--install",type=Path)
    actions.add_argument("--rollback",action="store_true")
    p.add_argument("--game",type=Path,required=True)
    p.add_argument("--out",type=Path)
    a=p.parse_args()
    try:
        if a.build:
            result=build_bundle(a.game,a.out or ROOT/"work"/("native-live-"+uuid4().hex[:12]))
        elif a.install:
            result=activate_bundle(a.install,a.game)
        else:
            result=rollback(a.game)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,LiveInstallError,subprocess.SubprocessError) as error:
        print("SPRITESUITE_LIVE_INSTALL_ERROR: "+str(error),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
