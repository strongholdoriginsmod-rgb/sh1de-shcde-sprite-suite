"""Offline executable test for the actual authored Origins menu bridge.

Compiles the *unchanged production C# core+bridge* against small, test-only
Noesis/BepInEx/Harmony stand-ins, executes the resulting program, and checks
that original game menu commands pass through, custom commands update their
view controls and hooks are unregistered. Never installs or loads game DLLs.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile

import hud_menu_workspace as private_work
from hud_menu_workspace import workspace,WorkshopError
from origins_runtime_offline_qa import verify_campaign
from origins_native_abi_probe import CSC
from suite_windows_paths import is_link_or_reparse

ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/"runtime"/"SpriteSuite.Origins.Authoring"/"OriginsRuntimeCore.cs"
BRIDGE=ROOT/"runtime"/"SpriteSuite.Origins.Authoring"/"OriginsFrontendBepInExCandidate.cs"
HARNESS=ROOT/"tests"/"sandbox"/"origins_menu_mock_harness.cs"
OUTPUT_SCHEMA="sprite-suite.origins-menu-behavior-mock.v1"
REQUIRED={
    "MOCK_HARMONY_PATCHES":"1",
    "MOCK_HARMONY_UNPATCHES":"1",
    "REAL_GAME_DLL_LOADED":"0",
    "REAL_NOESIS_RENDERER_LOADED":"0",
    "NATIVE_GAME_HOOK_REGISTERED":"0",
}


def _hash(blob:bytes)->str:
    return sha256(blob).hexdigest()


def run_menu_mock_qa(project:Path,slug:str, *,
                     destination:Path|None=None)->dict:
    """Compile and execute a fake host for one SHA-verified campaign."""
    if os.name!="nt" or not CSC.is_file():
        raise WorkshopError("Windows C# compiler needed for menu QA")
    root=workspace(project)
    plan,generated=verify_campaign(root,slug)
    if any(not file.is_file() or is_link_or_reparse(file)
           for file in (CORE,BRIDGE,HARNESS)):
        raise WorkshopError("Audited menu mock source unavailable")
    sources={name:_hash(path.read_bytes()) for name,path in
             (("core",CORE),("bridge",BRIDGE),("mock_harness",HARNESS))}
    expected_data=_hash(generated)
    if destination is None:
        destination=root.parent/".origins-menu-behavior-qa"/slug
    destination=Path(destination)
    private_root=private_work.WORK.resolve()
    if not destination.resolve(strict=False).is_relative_to(private_root):
        raise WorkshopError("Menu mock QA must remain inside private work/")
    if destination.exists() or is_link_or_reparse(destination):
        raise WorkshopError("Menu QA already exists; choose a fresh campaign")
    if is_link_or_reparse(destination.parent):
        raise WorkshopError("Menu QA parent is linked")
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix=".origins-mock-",dir=destination.parent))
    try:
        executable=stage/"MenuBehaviorMock.exe"
        (stage/"OriginsCampaignData.g.cs").write_bytes(generated)
        from suite_windows_csharp_scratch import short_csharp_scratch
        with short_csharp_scratch() as compiler_dir:
            # Legacy .NET csc.exe has path-length limits. Compile and execute
            # in a short private path, then copy only verified output bytes.
            source=compiler_dir/"OriginsCampaignData.g.cs"
            source.write_bytes(generated)
            temporary_exe=compiler_dir/"MenuBehaviorMock.exe"
            args=[str(CSC),"/nologo","/target:exe","/optimize+",
                  "/out:"+str(temporary_exe),str(CORE),str(BRIDGE),
                  str(HARNESS),str(source)]
            build=subprocess.run(args,cwd=compiler_dir,capture_output=True,
                   text=True,encoding="utf8",errors="replace",timeout=45,
                   creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            (stage/"compiler.log").write_text(
                 build.stdout+build.stderr,encoding="utf8")
            if build.returncode or not temporary_exe.is_file():
                raise WorkshopError("Real menu C# mock compile failed: "+
                                    (build.stdout+build.stderr)[-1800:])
            actual=subprocess.run([str(temporary_exe)],cwd=compiler_dir,
                    capture_output=True,text=True,encoding="utf8",errors="replace",
                    timeout=30,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            shutil.copyfile(temporary_exe,executable)
            if _hash(executable.read_bytes())!=_hash(temporary_exe.read_bytes()):
                raise WorkshopError("Menu QA executable changed while copying")
            (stage/"behavior.log").write_text(
                 actual.stdout+actual.stderr,encoding="utf8")
        flags=dict(line.strip().split("=",1)
                   for line in actual.stdout.splitlines() if "=" in line)
        try:assertions=int(flags.get("SPRITESUITE_MOCK_MENU_ASSERTIONS","0"))
        except ValueError:assertions=0
        if (actual.returncode!=0 or assertions<25
                or any(flags.get(key)!=val for key,val in REQUIRED.items())):
            raise WorkshopError("Menu C# adapter behavior failed: "+
                                (actual.stdout+actual.stderr)[-2000:])
        if (any(_hash(path.read_bytes())!=sources[name] for name,path in
                (("core",CORE),("bridge",BRIDGE),
                 ("mock_harness",HARNESS))) or
                verify_campaign(root,slug)[1]!=generated):
            raise WorkshopError("Menu QA source or authored campaign changed")
        report={
          "schema":OUTPUT_SCHEMA,
          "campaign_slug":slug,
          "mission_count":len(plan["missions"]),
          "behavior_assertions_executed":assertions,
          "real_menu_bridge_csharp_compiled":True,
          "mock_host_executable_executed":True,
          "harmony_mock_patch_calls":int(flags["MOCK_HARMONY_PATCHES"]),
          "harmony_mock_unpatch_calls":int(flags["MOCK_HARMONY_UNPATCHES"]),
          "game_binaries_loaded":False,
          "native_noesis_renderer_loaded":False,
          "native_game_hook_registered":False,
          "menu_callback_in_game_attested":False,
          "source_hashes":sources,
          "campaign_source_sha256":expected_data,
          "mock_exe_sha256":_hash(executable.read_bytes()),
          "game_installation_modified":False,
          "note":"The real menu bridge was EXECUTED against stand-ins, "
                 "NOT against the running Unity/Noesis game.",
        }
        (stage/"qa-report.json").write_text(
             json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        os.rename(stage,destination)
    finally:
        if stage.exists() and not is_link_or_reparse(stage):
            shutil.rmtree(stage)
    return {"output":str(destination),
            "report":str(destination/"qa-report.json"),
            "log":str(destination/"behavior.log"),
            "exe":str(destination/"MenuBehaviorMock.exe"),**report}
