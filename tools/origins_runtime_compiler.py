"""Compile *only* generated, independently checked Origins C# runtime data.

The output is a standalone managed helper library. It is deliberately not a
BepInEx plugin or a Stronghold game hook and is not auto-installed anywhere.
No user-authored C# is compiled; generated .cs must match trusted templates.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from hud_menu_workspace import workspace, WorkshopError, _write_new
from suite_windows_paths import is_link_or_reparse
from origins_runtime_authoring import (
    campaign_csharp_source,season_csharp_source,validate_campaign,
)


ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/"runtime"/"SpriteSuite.Origins.Authoring"/"OriginsRuntimeCore.cs"
HARNESS=ROOT/"tests"/"sandbox"/"origins_runtime_generated_harness.cs"
CS_COMPILERS=(
    Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"),
    Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
)


def _digest(blob:bytes)->str:
    return sha256(blob).hexdigest()


def _candidate(project:Path,location:Path,kind:str)->Path:
    work=workspace(project)
    file=Path(location).resolve(strict=True)
    parent=work.parent/".origins-runtime-candidates"
    if (not file.is_dir() or file.parent!=parent or
        is_link_or_reparse(file) or is_link_or_reparse(parent) or
        is_link_or_reparse(work)):
        raise WorkshopError("Select an existing private Origins candidate only")
    if kind=="campaign" and file.name.startswith("season-"):
        raise WorkshopError("Season draft is not a campaign")
    if kind=="season" and not file.name.startswith("season-"):
        raise WorkshopError("Select a season draft")
    return file


def _prepare(candidate:Path,kind:str)->tuple[bytes,list[str]]:
    evidence_file=candidate/"qa-status.json"
    if not evidence_file.is_file() or is_link_or_reparse(evidence_file):
        raise WorkshopError("Missing verified draft receipt")
    try:
        evidence=json.loads(evidence_file.read_text("utf8"))
    except (OSError,UnicodeError,ValueError) as exc:
        raise WorkshopError("Broken draft receipt") from exc
    if (evidence.get("installable_mod_produced") is not False or
        evidence.get("in_game_qa_completed") is True):
        raise WorkshopError("Unexpected runtime status")
    if kind=="campaign":
        plan_file=candidate/"campaign-plan.json"
        generated=candidate/"OriginsCampaignData.g.cs"
        patch=candidate/"FrontendMenus.draft.xaml"
        if (evidence.get("schema")!="sprite-suite.origins-campaign-draft.v1"
            or any(not item.is_file() or is_link_or_reparse(item)
                   for item in (plan_file,generated,patch))):
            raise WorkshopError("Incomplete campaign draft")
        try:
            plan=json.loads(plan_file.read_text("utf8"))
            checked=validate_campaign(plan)
        except (OSError,UnicodeError,ValueError) as exc:
            raise WorkshopError("Unverified campaign specification") from exc
        if (evidence.get("campaign_sha256")!=_digest(
                (json.dumps(checked,sort_keys=True)+"\n").encode()) or
            evidence.get("menu_patch_sha256")!=_digest(patch.read_bytes())):
            raise WorkshopError("Campaign changed after authoring")
        expected=campaign_csharp_source(plan)
        if (generated.read_bytes()!=expected or
            evidence.get("campaign_data_csharp_sha256")!=_digest(expected)):
            raise WorkshopError("Generated campaign source changed after review")
        return expected,[str(len(plan["missions"])),plan["missions"][-1]["map"]]
    if kind=="season":
        pack_file=candidate/"pack.json"
        generated=candidate/"OriginsSeasonData.g.cs"
        if (evidence.get("schema")!="sprite-suite.origins-season-candidate.v1"
            or any(not item.is_file() or is_link_or_reparse(item)
                   for item in (pack_file,generated))):
            raise WorkshopError("Incomplete season draft")
        try:
            pack=json.loads(pack_file.read_text("utf8"))
            maps=evidence["maps_with_season"]
            if (pack.get("packId")!=evidence["pack_id"] or
                pack.get("schema")!=1 or
                len(pack["groups"])!=evidence["gm_groups"] or
                len(pack["groups"])!=len(evidence["group_hashes"])):
                raise WorkshopError("Pack metadata changed")
        except (OSError,UnicodeError,ValueError,KeyError,TypeError) as exc:
            raise WorkshopError("Broken season pack specification") from exc
        expected=season_csharp_source(pack["packId"],maps)
        if (generated.read_bytes()!=expected or
            evidence.get("csharp_route_sha256")!=_digest(expected)):
            raise WorkshopError("Generated season source changed")
        for group in evidence["group_hashes"]:
            name=group["gm"]
            if name not in [x["gm"] for x in pack["groups"]]:
                raise WorkshopError("Atlas group missing from pack")
            for filename,key in (("atlas.png","atlas_png_sha256"),
                                 ("atlas.json","atlas_json_sha256")):
                file=candidate/name/filename
                if (not file.is_file() or is_link_or_reparse(file) or
                    _digest(file.read_bytes())!=group[key]):
                    raise WorkshopError("Atlas changed since draft")
        return expected,[maps[0],pack["packId"]]
    raise WorkshopError("Unknown candidate kind")


def compile_offline(*,project:Path,candidate:Path,kind:str)->dict:
    if os.name!="nt":
        raise WorkshopError("Use the Windows .NET Framework compiler")
    folder=_candidate(project,candidate,kind)
    source,arguments=_prepare(folder,kind)
    compiler=next((item for item in CS_COMPILERS if item.is_file()),None)
    if compiler is None:
        raise WorkshopError("Windows .NET Framework C# compiler not installed")
    if not CORE.is_file() or not HARNESS.is_file():
        raise WorkshopError("Bundled C# runtime core or offline harness missing")
    existing=(folder/"OriginsAuthoredCore.dll",folder/"offline-compile-evidence.json")
    if any(item.exists() or is_link_or_reparse(item) for item in existing):
        raise WorkshopError("Offline assembly or proof already exists")
    generated_path=folder/("OriginsCampaignData.g.cs"
                           if kind=="campaign" else "OriginsSeasonData.g.cs")
    before={p:_digest(p.read_bytes()) for p in
            (generated_path,CORE,HARNESS,folder/"qa-status.json")}
    with tempfile.TemporaryDirectory(prefix=".origins-core-",dir=folder) as tmp:
        temp=Path(tmp)
        library=temp/"OriginsAuthoredCore.dll"
        test_exe=temp/"OriginsAuthoredCoreTest.exe"
        files=[str(CORE),str(generated_path)]
        compile_command=[str(compiler),"/nologo","/target:library",
                         "/optimize+","/out:"+str(library)]+files
        result=subprocess.run(compile_command,capture_output=True,text=True,
                              timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or not library.is_file():
            raise WorkshopError("C# compile failed: "+(result.stdout+result.stderr)[-800:])
        define=("CAMPAIGN" if kind=="campaign" else "SEASONS")
        qa_command=[str(compiler),"/nologo","/target:exe",
                    "/define:"+define,"/out:"+str(test_exe),
                    str(CORE),str(generated_path),str(HARNESS)]
        qa=subprocess.run(qa_command,capture_output=True,text=True,timeout=45,
                          creationflags=subprocess.CREATE_NO_WINDOW)
        if qa.returncode or not test_exe.is_file():
            raise WorkshopError("C# runtime selftest compilation failed: "+
                                (qa.stdout+qa.stderr)[-800:])
        completed=subprocess.run(
            [str(test_exe),*arguments],capture_output=True,text=True,
            timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        if (completed.returncode or
                "NATIVE_GAME_HOOKS_CALLED=0" not in completed.stdout or
                "VERIFIED=1" not in completed.stdout):
            raise WorkshopError("The authored C# runtime data failed offline QA: "+
                                (completed.stdout+completed.stderr)[-800:])
        if any(_digest(p.read_bytes())!=before[p] for p in before):
            raise WorkshopError("Runtime source or authored data changed during compilation")
        dll_bytes=library.read_bytes()
        if not dll_bytes.startswith(b"MZ") or len(dll_bytes)>4*1024*1024:
            raise WorkshopError("Compiled C# assembly invalid")
        record={
            "schema":"sprite-suite.origins-managed-offline-compile.v1",
            "candidate_kind":kind,"compiler":"Windows .NET Framework C# 5",
            "generated_source_sha256":_digest(source),
            "runtime_core_sha256":before[CORE],
            "compiled_dll_sha256":_digest(dll_bytes),
            "offline_runtime_data_selftest_passed":True,
            "native_game_dll_loaded":False,
            "game_plugin_compiled":False,
            "script_extender_abi_verified":False,
            "ingame_menu_commands_connected":False,
            "public_mod_release_approved":False,
        }
        _write_new(existing[0],dll_bytes)
        try:
            _write_new(existing[1],(json.dumps(record,ensure_ascii=False,indent=2)+
                                     "\n").encode("utf8"))
        except Exception:
            # Delete only our own just-created artifact if its hash is intact.
            if existing[0].is_file() and _digest(existing[0].read_bytes())==record[
                    "compiled_dll_sha256"]:
                existing[0].unlink()
            raise
    return record
