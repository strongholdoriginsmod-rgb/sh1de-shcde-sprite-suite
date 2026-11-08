"""Shared non-invasive C# builder and reversible BepInEx plugin installer.

Both the SpriteSuite object inspector and gameplay-rules editor compile against
the selected installed SHCDESE/Unity ABI. No fixed game-version gate. Install
and remove are explicit and byte-verified; build alone never edits the game.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

from suite_windows_paths import is_link_or_reparse, is_reserved_windows_component

REQUIRED_REFS = (
    "BepInEx/core/BepInEx.dll",
    "BepInEx/plugins/000shcdese/SHCDESE.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/Assembly-CSharp.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.CoreModule.dll",
)
OPTIONAL_REFS = (
    "BepInEx/plugins/000shcdese/RedBird.Core.dll",
    "BepInEx/core/RedBird.Core.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/netstandard.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.InputLegacyModule.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.JSONSerializeModule.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.TilemapModule.dll",
)
DEFAULT_CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe"
RECEIPT = "spritesuite-compiled-plugin-receipt.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as file:
        for data in iter(lambda: file.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def compile_managed(game: Path, source: Path, output: Path, *, csc: Path = DEFAULT_CSC) -> dict:
    game = Path(game).resolve(strict=True)
    source = Path(source).resolve(strict=True)
    target = Path(output)
    if target.exists():
        raise FileExistsError("Output DLL already exists: " + str(target))
    if not csc.is_file() or not source.is_file():
        raise FileNotFoundError("C# compiler or source missing")
    refs = []
    for name in REQUIRED_REFS:
        path = game / Path(*name.split("/"))
        if not path.is_file():
            raise FileNotFoundError("Missing game SDK reference " + str(path))
        refs.append(path)
    for name in OPTIONAL_REFS:
        path = game / Path(*name.split("/"))
        if path.is_file():
            refs.append(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    args = [str(csc), "/nologo", "/target:library", "/optimize+",
            "/out:" + str(target)]
    args += ["/reference:" + str(path) for path in refs]
    args.append(str(source))
    result = subprocess.run(args, capture_output=True, text=True,
                            errors="replace", timeout=120, check=False)
    if result.returncode or not target.is_file():
        raise RuntimeError("Actual game SDK C# build failed:\n" +
                           "\n".join((result.stdout + result.stderr).splitlines()[-16:]))
    return {"dll": str(target), "sha256": sha(target),
            "references": [{"file": path.name, "sha256": sha(path)} for path in refs],
            "gameBuildVersionHardcoded": False,
            "compiledAgainstSelectedGame": True,
            "gameExecuted": False}



def _component(name: str) -> None:
    if (not isinstance(name, str) or not name or name in {".", ".."} or
            "/" in name or "\\" in name or is_reserved_windows_component(name)):
        raise ValueError("Choose an ordinary plugin folder or root filename")


def _plugin_directory(game: Path, folder: str) -> Path:
    _component(folder)
    root = Path(game).resolve(strict=True)
    target = root / "BepInEx" / "plugins" / folder
    if any(is_link_or_reparse(path) for path in (target, target.parent, target.parent.parent)):
        raise ValueError("Plugin location contains a linked path")
    return target

def install_managed(game: Path, folder: str, dll: Path, metadata: dict,
                    files: dict[str, bytes] | None = None) -> dict:
    target = _plugin_directory(game, folder)
    if target.exists():
        raise FileExistsError("Plugin directory exists: " + str(target))
    if not dll.is_file():
        raise FileNotFoundError(dll)
    contents = dict(files or {})
    if dll.name in contents or "info.json" in contents or RECEIPT in contents:
        raise ValueError("Mod files overlap compiler-owned installation records")
    contents[dll.name] = dll.read_bytes()
    contents["info.json"] = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    for name in contents:
        _component(name)
    target.mkdir(parents=True)
    try:
        for name, content in contents.items():
            if not name or "/" in name or "\\" in name or name.startswith("."):
                raise ValueError("Plugin install extra file must be a root filename")
            with (target / name).open("xb") as file:
                file.write(content)
        receipt = {"schema": "spritesuite.shcde.compiled-plugin.v1",
                   "files": {name: sha(target / name) for name in contents},
                   "sourceCompiledAgainstGame": True}
        with (target / RECEIPT).open("x", encoding="utf-8") as file:
            json.dump(receipt, file, indent=2)
        return {"plugin": str(target), "dllSHA256": receipt["files"][dll.name]}
    except BaseException:
        for name in contents:
            (target / name).unlink(missing_ok=True)
        (target / RECEIPT).unlink(missing_ok=True)
        target.rmdir()
        raise


def remove_managed(game: Path, folder: str) -> dict:
    path = _plugin_directory(game, folder)
    receipt = json.loads((path / RECEIPT).read_text(encoding="utf-8-sig"))
    if receipt.get("schema") != "spritesuite.shcde.compiled-plugin.v1":
        raise ValueError("Unknown SpriteSuite plugin receipt")
    files = receipt.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("Invalid installed plugin inventory")
    for name in files:
        _component(name)
        if is_link_or_reparse(path / name):
            raise ValueError("Linked installed plugin file")
    if {p.name for p in path.iterdir()} != set(files) | {RECEIPT}:
        raise ValueError("Plugin files differ from installer-owned inventory")
    for name, digest in files.items():
        if sha(path / name) != digest:
            raise ValueError("Plugin file changed since installation: " + name)
    for name in files:
        (path / name).unlink()
    (path / RECEIPT).unlink()
    path.rmdir()
    return {"removed": str(path), "otherGameFilesTouched": False}
