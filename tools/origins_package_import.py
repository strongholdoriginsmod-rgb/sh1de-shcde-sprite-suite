"""Import a historic Origins-style plugin as editable STATIC assets, privately.

This is not an install/upgrade tool. Native DLLs, BepInEx hooks and season
runtime content are neither executed nor packaged. The original source folder
is read-only and every accepted asset retains its original resource path.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from hud_menu_workspace import WORK,ROOT,WorkshopError,_write_new
from se_asset_package import _relative_key,_validate_asset,AssetModError
from suite_windows_paths import is_link_or_reparse

SLUG=re.compile(r"[a-z][a-z0-9-]{2,52}\Z")
STATIC_PREFIXES=("Override","Patches","Locales")
_MAX_FILES=10000
_MAX_TOTAL=2*1024**3


def _sha(path:Path)->str:
    h=sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def _existing_regular(path:Path)->Path:
    value=Path(path)
    if not value.is_file() or is_link_or_reparse(value):
        raise WorkshopError("Linked or missing original Origins source")
    for parent in value.parents:
        if is_link_or_reparse(parent):
            raise WorkshopError("Linked parent in source path")
    return value


def import_static_origins(*,plugin:Path,project_slug:str)->dict:
    if not isinstance(project_slug,str) or not SLUG.fullmatch(project_slug):
        raise WorkshopError("Choose a safe new project slug")
    root=Path(plugin)
    if not root.is_dir() or is_link_or_reparse(root):
        raise WorkshopError("Choose the original installed plugin directory")
    metadata=_existing_regular(root/"info.json")
    if metadata.stat().st_size>512*1024:
        raise WorkshopError("Oversized plugin info.json")
    try:
        info=json.loads(metadata.read_text("utf8"))
    except (OSError,UnicodeError,ValueError) as exc:
        raise WorkshopError("Invalid plugin info.json") from exc
    if (not isinstance(info,dict) or not isinstance(info.get("GUID"),str)
        or not info.get("GUID") or
        not isinstance(info.get("Name"),str)):
        raise WorkshopError("Missing plugin identity")
    base=WORK.resolve(strict=True)
    destination=base/project_slug
    if (destination.exists() or is_link_or_reparse(destination) or
        is_link_or_reparse(base) or
        root.resolve(strict=True)==destination.resolve(strict=False)):
        raise WorkshopError("A private project already exists or is linked")
    manifest=root/"branding-manifest.json"
    attested=None
    if manifest.is_file():
        if is_link_or_reparse(manifest) or manifest.stat().st_size>2*1024*1024:
            raise WorkshopError("Unsafe historical asset manifest")
        try:
            data=json.loads(manifest.read_text("utf8"))
            if data.get("schema")=="stronghold-origins-branding-v1":
                attested={x["path"]:(x["bytes"],x["sha256"]) for x in data["files"]}
        except (OSError,UnicodeError,ValueError,KeyError,TypeError) as exc:
            raise WorkshopError("Invalid original asset provenance manifest") from exc
    files=[]
    folded_paths=set()
    ignored=Counter()
    total=0
    for folder in sorted(root.iterdir()):
        if is_link_or_reparse(folder):
            raise WorkshopError("Linked folder in plugin source")
        if folder.name not in STATIC_PREFIXES:
            if folder.is_file():ignored["plugin-runtime-or-metadata"]+=1
            elif folder.is_dir():
                ignored["external-runtime-folders"]+=1
            continue
        if not folder.is_dir():
            raise WorkshopError("Expected an asset directory")
        for file in sorted(folder.rglob("*")):
            if is_link_or_reparse(file):
                raise WorkshopError("Linked file in source plugin")
            if file.is_dir():continue
            if not file.is_file():
                raise WorkshopError("Nonregular original plugin resource")
            relative=_relative_key(file.relative_to(root))
            if relative.casefold() in folded_paths:
                raise WorkshopError("Duplicate resource path on Windows: "+relative)
            folded_paths.add(relative.casefold())
            try:_validate_asset(file,relative)
            except (AssetModError,OSError,ValueError) as exc:
                raise WorkshopError("Unsafe/static unsupported plugin resource: "+relative) from exc
            size=file.stat().st_size
            total+=size
            if size>512*1024**2 or total>_MAX_TOTAL:
                raise WorkshopError("Plugin resource size budget exceeded")
            files.append((relative,file,size,_sha(file),file.stat().st_mtime_ns))
            if len(files)>_MAX_FILES:
                raise WorkshopError("Excessive original resources")
    if not files:
        raise WorkshopError("No supported static HUD/menu assets in plugin")
    # The historical branding manifest is a useful reference, NOT a lock on
    # the user's own already-modified Origins resources. Preserve the fact of
    # a difference as a diagnostic and continue with normal asset validation.
    modified_against_manifest=[]
    if attested is not None:
        for relative,_file,size,digest,_mtime in files:
            if relative in attested and (size,digest)!=attested[relative]:
                modified_against_manifest.append(relative)
    # Stage every nested resource before creating the new public project path.
    stage=Path(tempfile.mkdtemp(prefix=".origins-static-import-",dir=base))
    committed=False
    try:
        for relative,source,size,digest,mtime in files:
            dest=stage/relative
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,dest)
            if (dest.stat().st_size!=size or _sha(dest)!=digest or
                source.stat().st_size!=size or
                source.stat().st_mtime_ns!=mtime or _sha(source)!=digest):
                raise WorkshopError("Original file changed during import")
        if destination.exists() or is_link_or_reparse(destination):
            raise WorkshopError("A private project appeared during import")
        os.rename(stage,destination)  # Windows rejects pre-existing directory.
        committed=True
    finally:
        if not committed and stage.is_dir() and not is_link_or_reparse(stage):
            shutil.rmtree(stage)

    proof={
        "schema":"sprite-suite.origins-static-import.v1",
        "original_plugin_guid":info["GUID"],
        "original_plugin_name":info["Name"],
        "source_version":info.get("Version"),
        "original_supported_game_versions":info.get("SupportedGameVersions",[]),
        "project_slug":project_slug,
        "file_count":len(files),
        "total_bytes":total,
        "resource_names":[x[0] for x in files],
        "resource_sha256":{x[0]:x[3] for x in files},
        "historical_manifest_if_present_sha256":(
            _sha(manifest) if attested is not None else None),
        "user_modified_resources_accepted":modified_against_manifest,
        "baseline_hashes_are_editable_references_not_write_locks":True,
        "excluded":dict(ignored),
        "native_runtime_dll_imported":False,
        "season_runtime_imported":False,
        "in_game_behaviour_attested":False,
        "static_asset_packaging_available":True,
        "no_original_files_modified":True,
    }
    evidence=base/".origins-import-receipts"/(project_slug+".json")
    _write_new(evidence,(json.dumps(proof,ensure_ascii=False,indent=2)+
                         "\n").encode("utf8"))
    return {"project":str(destination),**proof}
