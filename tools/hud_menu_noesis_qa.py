"""Guarded temporary deployment of a Noesis mod into an EXPLICIT QA game copy.

Real Steam/installed originals are not installation targets. The only allowed
targets are a directory literally named SSGameQA or a game folder carrying a
user-created .sprite-suite-qa-copy.marker. Does not modify or install SE itself.
Every deployed file is SHA-recorded and removal refuses unexpected changes.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import uuid

from hud_menu_workspace import WorkshopError, _metadata_dir, workspace
from hud_menu_noesis_integration import installed_gui, _reject_links
from hud_menu_layout import _atomic_save, _safe_output_path
import se_asset_package as asset

MARKER = ".sprite-suite-qa-copy.marker"
QA_SCHEMA = "sprite-suite.qa-noesis-install-receipt.v1"


def _sha(data:bytes) -> str:
    return sha256(data).hexdigest()


def _game_running() -> bool:
    """Windows process check without adding third-party dependencies."""
    import subprocess
    if os.name!="nt":
        raise WorkshopError("QA installation requires Windows")
    code=(
        "$p=@(Get-Process -ErrorAction Stop | Where-Object { "
        "$_.ProcessName -match '(?i)stronghold.*crusader' });"
        "if($p.Count -gt 0){exit 42}else{exit 0}"
    )
    try:
        result=subprocess.run(
            ["powershell.exe","-NoProfile","-NonInteractive","-Command",code],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12,
        )
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise WorkshopError("Cannot safely inspect running game processes") from exc
    if result.returncode not in (0,42):
        raise WorkshopError("Game process check failed; refusing QA game writes")
    return result.returncode==42


def qa_game_root(gui_root: Path | str) -> Path:
    gui,_=installed_gui(gui_root)
    game=gui.parents[5]
    if (game.name.casefold() != "ssgameqa"
            and not (game/MARKER).is_file()):
        raise WorkshopError("Only an explicitly marked QA game copy is writable")
    if _game_running():
        raise WorkshopError("Close Stronghold Crusader before QA install/remove")
    _reject_links(game)
    if not (game/"BepInEx/plugins").is_dir():
        raise WorkshopError("QA game has no BepInEx/plugins folder")
    return game


def _files(folder: Path) -> dict[str,str]:
    if folder.is_symlink() or not folder.is_dir():
        raise WorkshopError("Missing or linked mod root")
    found={}
    for entry in sorted(folder.rglob("*")):
        if entry.is_symlink():
            raise WorkshopError("Mod folder contains symlinks")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise WorkshopError("Mod folder contains unsupported filesystem objects")
        rel=entry.relative_to(folder).as_posix()
        if ".." in Path(rel).parts:
            raise WorkshopError("Invalid mod path")
        found[rel]=_sha(entry.read_bytes())
    return found


def _receipt(project:Path, guid:str) -> Path:
    if not isinstance(guid,str) or not asset._GUID.fullmatch(guid):
        raise WorkshopError("Unsafe QA mod GUID")
    return _metadata_dir(project)/"qa-installs"/(guid+".json")


def _validate_mod_source(mod_folder:Path, guid:str) -> dict[str,str]:
    if mod_folder.name!=guid or mod_folder.is_symlink():
        raise WorkshopError("Mod folder must match the requested GUID")
    info=mod_folder/"info.json"
    if not info.is_file():
        raise WorkshopError("No asset-mod info.json")
    meta=json.loads(info.read_text("utf8"))
    if (meta.get("GUID")!=guid or meta.get("Manifest")!=0
            or meta.get("AssetMode")!="Global"):
        raise WorkshopError("Only a valid static global asset mod may be installed")
    content=_files(mod_folder)
    if not content or "info.json" not in content:
        raise WorkshopError("Invalid empty mod package")
    for dirname in ("Override","Patches"):
        subtree=mod_folder/dirname
        if subtree.exists() and subtree.is_symlink():
            raise WorkshopError("Linked package subtree")
    # Existing asset builder sees paths under Override/Patches only.
    visual_files={k:v for k,v in content.items() if k!="info.json"}
    if len(visual_files)!=2:
        raise WorkshopError("Expected one composite PNG and one XAML patch")
    if not any(k.startswith("Override/Assets/GUI/Images/")
               and k.endswith(".png") for k in visual_files):
        raise WorkshopError("No rendered GUI PNG")
    if not any(k.startswith("Patches/Assets/GUI/XAML/")
               and k.endswith(".xaml") for k in visual_files):
        raise WorkshopError("No bound game XAML patch")
    from se_asset_package import _validate_asset
    for rel in visual_files:
        _validate_asset(mod_folder/rel,rel)
    return content


def qa_install(project:Path|str, game_gui:Path|str, mod_folder:Path|str) -> dict:
    project=workspace(project)
    game=qa_game_root(game_gui)
    source=Path(mod_folder).resolve(strict=True)
    # No arbitrary external folder copied into the game!
    allowed=(asset.WORK/"se-asset-mods").resolve()
    if not source.is_relative_to(allowed) or source==allowed:
        raise WorkshopError("Only SpriteSuite-built asset mods are eligible")
    _reject_links(source)
    guid=source.name
    content=_validate_mod_source(source,guid)
    plugins=game/"BepInEx/plugins"
    dest=plugins/guid
    record=_receipt(project,guid)
    if dest.exists() or record.exists():
        raise WorkshopError("QA mod or receipt already exists; no overwrite")
    temp=plugins/(".sprite-suite-qa-"+uuid.uuid4().hex)
    _reject_links(plugins)
    if temp.exists():
        raise WorkshopError("QA staging destination exists")
    created=False
    try:
        shutil.copytree(source,temp,symlinks=False)
        if _files(temp)!=content:
            raise WorkshopError("QA staging copy did not preserve SHA-256")
        if dest.exists():
            raise WorkshopError("QA mod appeared during copy; refuse overwrite")
        os.rename(temp,dest)
        created=True
        receipt={
            "schema":QA_SCHEMA,"guid":guid,"qa_game":str(game),
            "folder":str(dest),"files":content,
            "install_method":"new isolated BepInEx asset-mod directory",
            "does_not_install_script_extender":True,
        }
        data=(json.dumps(receipt,indent=2,ensure_ascii=False)+"\n").encode("utf8")
        _atomic_save(record,data,expected_hash=None)
        return receipt
    except Exception:
        if temp.exists():shutil.rmtree(temp,ignore_errors=True)
        if created and dest.is_dir() and _files(dest)==content:
            shutil.rmtree(dest)
        raise


def qa_status(project:Path|str, game_gui:Path|str, guid:str) -> dict:
    """Read-only verification of a managed QA installation and all file pins."""
    project=workspace(project)
    game=qa_game_root(game_gui)
    record=_receipt(project,guid)
    if not record.is_file() or record.is_symlink():
        raise WorkshopError("No SpriteSuite QA installation receipt")
    receipt=json.loads(record.read_text("utf8"))
    dest=game/"BepInEx/plugins"/guid
    if (receipt.get("schema")!=QA_SCHEMA or receipt.get("guid")!=guid
            or receipt.get("qa_game")!=str(game)
            or receipt.get("folder")!=str(dest)):
        raise WorkshopError("QA installation receipt does not match this game")
    _reject_links(dest)
    if _files(dest)!=receipt.get("files"):
        raise WorkshopError("Installed QA mod changed; refuse unsafe launch/removal")
    return receipt


def qa_remove(project:Path|str, game_gui:Path|str, guid:str) -> dict:
    receipt=qa_status(project,game_gui,guid)
    dest=Path(receipt["folder"])
    record=_receipt(workspace(project),guid)
    # Only remove the folder created and SHA-pinned by this QA installer.
    shutil.rmtree(dest)
    record.unlink()
    return {"qa_game":receipt["qa_game"],"removed_guid":guid,
            "removed_files":len(receipt["files"]),
            "game_originals_unchanged":True}
