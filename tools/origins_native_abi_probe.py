"""Read-only installed game/Noesis/BepInEx structural ABI inspection.

Compiles a small Mono.Cecil *metadata reader* against the exact, user-owned
installed BepInEx Mono.Cecil library. The target game's code is never loaded,
invoked, patched or redistributed. Structural signatures are NOT evidence
that a runtime hook is registered or that rendering actually succeeded.
"""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile

from suite_windows_paths import is_link_or_reparse

ROOT=Path(__file__).resolve().parents[1]
PROBE=ROOT/"tests"/"sandbox"/"origins_native_signature_probe.cs"
CSC=Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")
MARKERS=(
 "HAS_FRONTEND_TYPE","FRONTEND_EXTENDS_NOESIS_USERCONTROL",
 "HAS_MENU_COMMAND_STRING_CALLBACK","HAS_NOESIS_FINDNAME",
 "HAS_BEPINEX_PLUGIN_HOST","HAS_HARMONY_PATCH_HOST","HAS_METADATA_READER",
)


class NativeProbeError(ValueError):pass


def _digest(file:Path)->str:
    digest=sha256()
    with file.open("rb") as source:
        for chunk in iter(lambda:source.read(4*1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source(root:Path,relative:str)->Path:
    path=root.joinpath(*relative.split("/"))
    if not path.is_file() or is_link_or_reparse(path):
        raise NativeProbeError("Native dependency is missing/linked: "+relative)
    if path.stat().st_size<=0 or path.stat().st_size>250*1024**2:
        raise NativeProbeError("Unexpected native dependency size: "+relative)
    return path


def probe_installed_game(game_root:Path,output:Path)->dict:
    if os.name!="nt" or not CSC.is_file():
        raise NativeProbeError("Windows .NET Framework compiler required")
    root=Path(game_root)
    if not root.is_dir() or is_link_or_reparse(root):
        raise NativeProbeError("Choose a local, regular installed game root")
    root=root.resolve(strict=True)
    if output.exists() or is_link_or_reparse(output):
        raise NativeProbeError("Choose a new private output directory")
    files={
      "game":_source(root,"Stronghold Crusader Definitive Edition_Data/Managed/Assembly-CSharp.dll"),
      "noesis":_source(root,"Stronghold Crusader Definitive Edition_Data/Managed/Noesis.NoesisGUI.dll"),
      "bep":_source(root,"BepInEx/core/BepInEx.dll"),
      "harmony":_source(root,"BepInEx/core/0Harmony.dll"),
      "cecil":_source(root,"BepInEx/core/Mono.Cecil.dll"),
      "native_noesis":_source(root,"Stronghold Crusader Definitive Edition_Data/Plugins/x86_64/Noesis.dll"),
      "script_extender":_source(root,"BepInEx/plugins/000shcdese/SHCDESE.dll"),
      "info":_source(root,"BepInEx/plugins/000shcdese/info.json"),
    }
    if not PROBE.is_file() or is_link_or_reparse(PROBE):
        raise NativeProbeError("Expected audited managed metadata probe source")
    output.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix=".origins-native-abi-",dir=output.parent))
    try:
        for name in ("cecil",):
            shutil.copyfile(files[name],stage/files[name].name)
        exe=stage/"OriginsAbiMetadataProbe.exe"
        args=[str(CSC),"/nologo","/target:exe","/out:"+str(exe),
              "/reference:"+str(stage/files["cecil"].name),str(PROBE)]
        compiled=subprocess.run(args,cwd=stage,capture_output=True,text=True,
                                errors="replace",timeout=45,
                                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        (stage/"compile.log").write_text(compiled.stdout+compiled.stderr,encoding="utf8")
        if compiled.returncode or not exe.is_file():
            raise NativeProbeError("Mono.Cecil metadata probe compilation failed: "+
                                   (compiled.stdout+compiled.stderr)[-1200:])
        read=subprocess.run([str(exe),*[str(files[x]) for x in
                               ("game","noesis","bep","harmony","cecil")]],
                    cwd=stage,capture_output=True,text=True,errors="replace",
                    timeout=40,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        (stage/"abi-probe.log").write_text(read.stdout+read.stderr,encoding="utf8")
        if read.returncode:
            raise NativeProbeError("Native ABI metadata audit failed: "+read.stderr[-1200:])
        seen=dict(line.strip().split("=",1) for line in read.stdout.splitlines()
                  if "=" in line)
        missing=[m for m in MARKERS if seen.get(m)!="1"]
        try:
            info=json.loads(files["info"].read_text("utf8"))
        except (OSError,UnicodeError,ValueError) as error:
            raise NativeProbeError("Extender metadata could not be decoded") from error
        result={
          "schema":"sprite-suite.origins-installed-abi-metadata.v1",
          "source_game_root":str(root),
          "script_extender_version":info.get("Version"),
          "script_extender_declared_game_versions":info.get("SupportedGameVersions"),
          "game_version_independently_verified":False,
          "source_hashes":{key:_digest(path) for key,path in files.items()},
          "structural_signatures":{marker:seen.get(marker)=="1" for marker in MARKERS},
          "missing_signatures":missing,
          "csharp_metadata_probe_compiled":True,
          "game_dll_executed":False,
          "native_noesis_renderer_executed":False,
          "native_game_command_handler_registered":False,
          "runtime_gui_events_tested":False,
          "game_abi_fully_attested":False,
          "in_game_QA_required":True,
          "game_installation_modified":False,
          "notes":[
           "Noesis native and managed binaries are PRESENT, but not a standalone rendering host.",
           "CrusaderDE.FrontendMenus.ButtonClicked(System.String) is a metadata-only signature check.",
           "Native game hooks and new menu command handlers require their own registered plugin and in-game QA.",
          ],
        }
        (stage/"abi-report.json").write_text(json.dumps(
            result,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
        os.rename(stage,output)
    finally:
        if stage.exists() and not is_link_or_reparse(stage):
            shutil.rmtree(stage)
    return {"report":str(output/"abi-report.json"),"log":str(output/"abi-probe.log"),
            "output":str(output),**result}
