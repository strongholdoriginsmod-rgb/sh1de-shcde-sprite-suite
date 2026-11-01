"""Build a private, NON-INSTALLABLE BepInEx Origins menu candidate offline.

Compiles the audited bridge + regenerated campaign + pure C# runtime core
against read-only libraries of the exact local installation. Unity/Noesis
game assemblies are NEVER loaded by Python, modified, copied, bundled or
installed. Successful compilation alone never attests live menu callbacks.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile

from hud_menu_workspace import workspace, WorkshopError
from origins_runtime_offline_qa import verify_campaign
from origins_native_abi_probe import _source as game_file
from origins_native_abi_probe import CSC, PROBE, _digest
from suite_windows_paths import is_link_or_reparse as linked

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "runtime" / "SpriteSuite.Origins.Authoring" / "OriginsRuntimeCore.cs"
BRIDGE = ROOT / "runtime" / "SpriteSuite.Origins.Authoring" / "OriginsFrontendBepInExCandidate.cs"
REFERENCE_KEYS = {
 "bep":"BepInEx/core/BepInEx.dll",
 "harmony":"BepInEx/core/0Harmony.dll",
 "noesis":"Stronghold Crusader Definitive Edition_Data/Managed/Noesis.NoesisGUI.dll",
 "unity":"Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.dll",
 "unity_core":"Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.CoreModule.dll",
 "game":"Stronghold Crusader Definitive Edition_Data/Managed/Assembly-CSharp.dll",
 "cecil":"BepInEx/core/Mono.Cecil.dll",
}


def compile_menu_candidate(project:Path, slug:str, game_root:Path)->dict:
    """Compile only. Never emit a BepInEx/plugins tree, install or load a game."""
    if os.name != "nt" or not CSC.is_file():
        raise WorkshopError("Windows .NET Framework v4 C# compiler unavailable")
    root = workspace(project)
    plan, authored_code = verify_campaign(root, slug)
    installed = Path(game_root)
    if not installed.is_dir() or linked(installed):
        raise WorkshopError("Choose a regular installed SHCDE game directory")
    installed = installed.resolve(strict=True)
    refs = {k:game_file(installed,relative) for k,relative in REFERENCE_KEYS.items()}
    source_files = (CORE,BRIDGE)
    if any(not file.is_file() or linked(file) for file in source_files):
        raise WorkshopError("Original runtime bridge source unavailable")
    original_hashes={k:_digest(v) for k,v in refs.items()}
    core_before=_digest(CORE)
    bridge_before=_digest(BRIDGE)
    # The source is a fixed, audited game-facing adapter, NOT arbitrary code
    # from the selected game directory or from a user-edited campaign file.
    generated=authored_code
    parent=root.parent/".origins-native-menu-candidates"
    if linked(parent):
        raise WorkshopError("Linked private native candidate folder")
    parent.mkdir(exist_ok=True)
    destination=parent/slug
    if destination.exists() or linked(destination):
        raise WorkshopError("Native candidate already exists; use a new campaign ID")
    stage=Path(tempfile.mkdtemp(prefix=".native-menu-",dir=parent))
    try:
        authored=stage/"OriginsCampaignData.g.cs"
        authored.write_bytes(generated)
        output=stage/"OriginsMenuCandidate.dll"
        from suite_windows_csharp_scratch import short_csharp_scratch
        with short_csharp_scratch() as compiler_dir:
            # csc.exe from .NET Framework 4 may fail on deeply nested work/
            # paths. It receives only short user-local source/output paths.
            temp_source=compiler_dir/"OriginsCampaignData.g.cs"
            temp_source.write_bytes(generated)
            temp_output=compiler_dir/"OriginsMenuCandidate.dll"
            args=[str(CSC),"/nologo","/target:library","/optimize+",
                  "/out:"+str(temp_output)]
            args += ["/reference:"+str(refs[k]) for k in
                     ("bep","harmony","noesis","unity","unity_core")]
            args += [str(CORE),str(BRIDGE),str(temp_source)]
            try:
                process=subprocess.run(args,cwd=compiler_dir,capture_output=True,
                            text=True,encoding="utf8",errors="replace",timeout=50,
                            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            except (OSError,subprocess.TimeoutExpired) as err:
                raise WorkshopError("Native menu candidate compiler did not finish") from err
            (stage/"compile.log").write_text(
                (process.stdout+process.stderr)[:32000],encoding="utf8")
            if process.returncode or not temp_output.is_file():
                raise WorkshopError(
                    "Native menu candidate failed compilation: "+
                    (process.stdout+process.stderr)[-1800:])
            shutil.copyfile(temp_output,output)
            if _digest(output)!=_digest(temp_output):
                raise WorkshopError("Compiled candidate changed while copying")
        # Verify compiled plugin metadata through Mono.Cecil without ever
        # loading/executing the DLL, Harmony or Unity game code.
        if not PROBE.is_file() or linked(PROBE):
            raise WorkshopError("Audited candidate metadata verifier missing")
        with short_csharp_scratch() as compiler_dir:
            cecil=compiler_dir/refs["cecil"].name
            shutil.copyfile(refs["cecil"],cecil)
            reader=compiler_dir/"OriginsNativeMetadataReader.exe"
            short_candidate=compiler_dir/"OriginsMenuCandidate.dll"
            shutil.copyfile(output,short_candidate)
            check=subprocess.run([str(CSC),"/nologo","/target:exe",
                        "/out:"+str(reader),"/reference:"+str(cecil),str(PROBE)],
                        cwd=compiler_dir,capture_output=True,text=True,
                        errors="replace",timeout=40,
                        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if check.returncode or not reader.is_file():
                raise WorkshopError("Candidate metadata reader compilation failed: "+
                                    (check.stdout+check.stderr)[-1000:])
            checked=subprocess.run([str(reader),*[str(refs[k]) for k in
                           ("game","noesis","bep","harmony","cecil")],
                           str(short_candidate)],
                        cwd=compiler_dir,capture_output=True,text=True,
                        errors="replace",timeout=35,
                        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            (stage/"candidate-metadata.log").write_text(
                checked.stdout+checked.stderr,encoding="utf8")
            if _digest(output)!=_digest(short_candidate):
                raise WorkshopError("Candidate changed while checking its metadata")
        signs=dict(line.split("=",1) for line in checked.stdout.splitlines()
                   if "=" in line)
        required=("CANDIDATE_HAS_PLUGIN_HOST","CANDIDATE_HAS_PLUGIN_ATTRIBUTE",
                  "CANDIDATE_HAS_HARMONY_PREFIX","CANDIDATE_HAS_AWAKE",
                  "CANDIDATE_HAS_UNPATCH_LIFECYCLE")
        if checked.returncode or any(signs.get(k)!="1" for k in required):
            raise WorkshopError("Native menu candidate metadata check failed: "+
                                (checked.stdout+checked.stderr)[-1000:])
        # Execute the SAME bridge C# against a fake Noesis/Harmony/BepInEx
        # host. This validates command routing and unpatch lifetime without
        # loading the actual game or adding test binaries to the candidate.
        from origins_menu_mock_qa import run_menu_mock_qa
        mock=run_menu_mock_qa(root,slug,destination=stage/"menu-mock-run")
        shutil.copyfile(mock["log"],stage/"menu-mock-behavior.log")
        shutil.copyfile(mock["report"],stage/"menu-mock-report.json")
        shutil.rmtree(stage/"menu-mock-run")
        # The Cecil copy and metadata reader were destroyed with the short
        # compiler scratch folder; never ship game/test binaries.
        if (_digest(CORE)!=core_before or _digest(BRIDGE)!=bridge_before or
              any(_digest(p)!=original_hashes[k] for k,p in refs.items())):
            raise WorkshopError("Game libraries or bridge source changed during compilation")
        _,later=verify_campaign(root,slug)
        if later != authored_code:
            raise WorkshopError("Campaign changed during native candidate build")
        if not output.read_bytes().startswith(b"MZ"):
            raise WorkshopError("C# compiler produced no valid PE library")
        report={
          "schema":"sprite-suite.origins-menu-native-candidate.v1",
          "campaign_slug":slug,
          "mission_count":len(plan["missions"]),
          "compiled_managed_dll_sha256":_digest(output),
          "compiled_managed_dll_bytes":output.stat().st_size,
          "compiler":"Windows .NET Framework v4 csc.exe",
          "managed_core_sha256":core_before,
          "menu_bridge_source_sha256":bridge_before,
          "authored_campaign_source_sha256":sha256(generated).hexdigest(),
          "compiled_candidate_metadata_attested":True,
          "compiled_candidate_metadata_signatures":{k:True for k in required},
          "offline_fake_game_host_executed":True,
          "offline_fake_host_assertions":mock["behavior_assertions_executed"],
          "offline_fake_host_log":"menu-mock-behavior.log",
          "mock_game_commands_preserved":True,
          "source_installation":str(installed),
          "referenced_game_assembly_hashes":original_hashes,
          "compiled_without_game_running":True,
          "game_dll_loaded_by_python":False,
          "game_installation_modified":False,
          "native_game_hook_registered":False,
          "menu_bindings_runtime_verified":False,
          "game_abi_fully_attested":False,
          "map_launch_implemented":False,
          "season_switch_implemented":False,
          "automatic_install_performed":False,
          "installable_mod_produced":False,
          "warnings":[
            "A compilable BepInEx DLL and fake-host tests are NOT proof of in-game functionality.",
            "The menu bridge only displays/hides authored Noesis controls, "
            "allows selection and LOGS launch requests without launching a map.",
            "Check exact running game build, game UI controls, command bindings, "
            "BepInEx patch interactions and rollback in a separate QA copy."
          ],
        }
        (stage/"qa-report.json").write_text(
            json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        os.rename(stage,destination)
    finally:
        if stage.exists() and not linked(stage):
            shutil.rmtree(stage)
    return {"output":str(destination),
            "dll":str(destination/"OriginsMenuCandidate.dll"),
            "report":str(destination/"qa-report.json"),**report}
