"""Export and restore an editable HUD/menu project as a checked ZIP.

Includes the project's local files plus portable baselines, layouts, revision
history and export receipts. No installed game files, QA deployment receipts,
or global Suite configuration is included. Restoration creates new folders;
never merges with, replaces or modifies an existing project.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import os
import re
import shutil
import stat
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

import hud_menu_workspace as assets
from suite_hud_menu_session import read_session, save_session

SCHEMA = "sprite-suite.hud-menu-project-archive.v1"
MANIFEST = "project-manifest.json"
MAX_FILES = 20000
MAX_BYTES = 2 * 1024 ** 3
MAX_ONE_FILE = 512 * 1024 ** 2
MAX_MANIFEST = 2 * 1024 ** 2
METADATA_SECTIONS = frozenset(
    {"layouts", "import-baselines", "exports", "revisions"}
)


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _safe_member(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise assets.WorkshopError("Unsicherer Pfad im Projektarchiv.")
    if len(value) > 240 or any(
        part in ("", ".", "..") or ":" in part or
        part.endswith((" ", ".")) or os.path.isreserved(part) or
        any(ord(letter) < 32 for letter in part)
        for part in value.split("/")
    ):
        raise assets.WorkshopError("Unzulässiger Projektarchiv-Dateiname.")
    if PurePosixPath(value).is_absolute():
        raise assets.WorkshopError("Absolute Pfade im Projektarchiv verboten.")
    if value.startswith("project/"):
        relative = value[len("project/"):]
        # Use the same strict resource-key contract as the normal workshop.
        # An archive is untrusted input, not a general file extractor.
        assets._relative(relative, patch=relative.startswith("Patches/"))
    elif value.startswith("metadata/"):
        if value[len("metadata/"):].split("/")[0] not in METADATA_SECTIONS:
            raise assets.WorkshopError("Unbekannter oder unportabler Metadatentyp.")
    else:
        raise assets.WorkshopError("Unbekannter Projektarchiv-Bereich.")
    return value


def _name(value: str) -> str:
    if (not isinstance(value,str) or not 1<=len(value)<=64
            or value!=value.strip() or not value[0].isalpha()
            or not all(char.isalnum() or char in " _-" for char in value)
            or os.path.isreserved(value)):
        raise assets.WorkshopError(
            "Projektname: 1–64 Zeichen, beginnend mit Buchstabe; "
            "Buchstaben, Ziffern, Leerzeichen, _ und - sind zulässig. "
            "Windows-Gerätenamen sind nicht zulässig."
        )
    return value


def _walk(source: Path, prefix: str):
    if _is_link(source):
        raise assets.WorkshopError("Projektarchiv-Quelle ist verknüpft.")
    if not source.exists():
        return
    if not source.is_dir():
        raise assets.WorkshopError("Projektarchiv-Quelle ist kein Ordner.")
    for entry in sorted(source.rglob("*")):
        if _is_link(entry):
            raise assets.WorkshopError("Verknüpfte Projektdateien sind nicht zulässig.")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise assets.WorkshopError("Nicht unterstützter Dateityp im Projekt.")
        relative=entry.relative_to(source).as_posix()
        if prefix=="metadata/" and relative.split("/")[0] not in METADATA_SECTIONS:
            # Deployment receipts belong to a particular game installation,
            # never to an editable project being moved to another computer.
            continue
        yield _safe_member(prefix+relative), entry


def _project_sources(project: Path):
    root=assets.workspace(project)
    if not root.is_dir():
        raise assets.WorkshopError("Projektordner existiert nicht.")
    metadata=assets._metadata_dir(root)  # includes safe legacy migration
    entries=[*_walk(root,"project/"), *_walk(metadata,"metadata/")]
    if len(entries)>MAX_FILES:
        raise assets.WorkshopError("Zu viele Dateien für ein Projektarchiv.")
    if sum(item.stat().st_size for _,item in entries)>MAX_BYTES:
        raise assets.WorkshopError("Projektarchiv überschreitet 2 GiB.")
    if any(item.stat().st_size>MAX_ONE_FILE for _,item in entries):
        raise assets.WorkshopError("Einzeldatei größer als 512 MiB.")
    return root,metadata,entries


def archive_info(path: Path | str) -> dict:
    """Validate the archive index *before* any extraction or disk writes."""
    archive=Path(path)
    if _is_link(archive) or not archive.is_file() or archive.stat().st_size>MAX_BYTES:
        raise assets.WorkshopError("Projektarchiv fehlt oder ist nicht zulässig.")
    try:
        with ZipFile(archive) as handle:
            members=handle.infolist()
            if len(members)>MAX_FILES+1 or not members:
                raise assets.WorkshopError("Ungültige Anzahl von Archivdateien.")
            seen=set()
            contents={}
            for info in members:
                name=info.filename
                canonical=name.casefold()
                if canonical in seen or info.is_dir():
                    raise assets.WorkshopError("Doppelte oder ungültige Archivreferenzen.")
                seen.add(canonical)
                if name!=MANIFEST:
                    _safe_member(name)
                    if (info.file_size>MAX_ONE_FILE or info.file_size<0 or
                            (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK or
                            (info.file_size>1024*1024 and
                             info.file_size>max(1,info.compress_size)*1000)):
                        raise assets.WorkshopError(
                            "Unzulässiger oder verdächtig stark komprimierter Archivinhalt."
                        )
                    contents[name] = info
            if MANIFEST not in seen or len(contents)>MAX_FILES:
                raise assets.WorkshopError("Projektarchiv enthält kein gültiges Manifest.")
            if sum(info.file_size for info in contents.values())>MAX_BYTES:
                raise assets.WorkshopError("Entpackte Projektdateien überschreiten 2 GiB.")
            index=handle.getinfo(MANIFEST)
            if index.file_size>MAX_MANIFEST:
                raise assets.WorkshopError("Projektmanifest ist zu groß.")
            manifest=json.loads(handle.read(MANIFEST).decode("utf8"))
            if not isinstance(manifest,dict) or manifest.get("schema")!=SCHEMA:
                raise assets.WorkshopError("Unbekanntes Projektarchivformat.")
            _name(manifest.get("project_name"))
            active_asset=manifest.get("selected_asset","")
            active_scene=manifest.get("selected_scene","")
            if not isinstance(active_asset,str) or len(active_asset)>1024:
                raise assets.WorkshopError("Ungültige Bildauswahl im Projektarchiv.")
            if active_asset:
                assets._relative(active_asset,patch=active_asset.startswith("Patches/"))
                if "project/"+active_asset not in contents:
                    raise assets.WorkshopError("Zuletzt ausgewähltes Bild fehlt im Archiv.")
            if not isinstance(active_scene,str) or (
                active_scene and not re.fullmatch("[A-Za-z][A-Za-z0-9_-]{0,47}",active_scene)
            ):
                raise assets.WorkshopError("Ungültiger Layoutname im Projektarchiv.")
            if active_scene and "metadata/layouts/"+active_scene+".scene.json" not in contents:
                raise assets.WorkshopError("Zuletzt gespeichertes Layout fehlt im Archiv.")
            rows=manifest.get("files")
            if not isinstance(rows,list) or len(rows)!=len(contents):
                raise assets.WorkshopError("Dateiliste im Projektarchiv ist unvollständig.")
            declared={}
            for row in rows:
                if (not isinstance(row,dict) or
                        set(row)!={"path","bytes","sha256"}):
                    raise assets.WorkshopError("Ungültiger Archiv-Dateieintrag.")
                key=_safe_member(row["path"])
                digest=row["sha256"]
                if (key in declared or key not in contents or
                        type(row["bytes"]) is not int or
                        row["bytes"]!=contents[key].file_size or
                        not isinstance(digest,str) or
                        not re.fullmatch("[0-9a-f]{64}",digest)):
                    raise assets.WorkshopError("Unstimmige Projektarchiv-Dateiliste.")
                declared[key]=row
            if set(declared)!=set(contents):
                raise assets.WorkshopError("Archiv enthält nicht dokumentierte Dateien.")
            return {
                "project_name":manifest["project_name"],
                "files":len(contents),
                "bytes":sum(info.file_size for info in contents.values()),
                "manifest":manifest,
            }
    except assets.WorkshopError:
        raise
    except (BadZipFile,UnicodeError,ValueError,KeyError,EOFError) as exc:
        raise assets.WorkshopError("Projektarchiv beschädigt oder ungültig.") from exc


def create_archive(project: Path | str, destination: Path | str) -> dict:
    """Write checked archive without ever overwriting an existing file."""
    root,metadata,entries=_project_sources(Path(project))
    _name(root.name)
    output=Path(destination)
    if output.suffix.lower()!=".zip" or _is_link(output):
        raise assets.WorkshopError("Projektarchiv muss eine neue .zip-Datei sein.")
    if output.exists():
        raise assets.WorkshopError("Zieldatei existiert bereits; neuen Namen wählen.")
    if (output.resolve(strict=False).is_relative_to(root)
            or output.resolve(strict=False).is_relative_to(metadata)):
        raise assets.WorkshopError("Archiv darf nicht in den Projektdateien liegen.")
    # Check the chain before creating directories or writing a user archive.
    for node in (output.parent, *output.parent.parents):
        if _is_link(node):
            raise assets.WorkshopError("Verknüpfter Archiv-Zielordner ist nicht zulässig.")
    output.parent.mkdir(parents=True,exist_ok=True)
    if _is_link(output.parent):
        raise assets.WorkshopError("Verknüpfter Archiv-Zielordner ist nicht zulässig.")
    fd,temp=tempfile.mkstemp(prefix=".spritesuite-project-",suffix=".tmp",
                            dir=output.parent)
    os.close(fd)
    created_output=False
    try:
        records=[]
        selected=read_session()
        active=selected if selected.get("project")==root else {}
        active_asset=active.get("asset","")
        if active_asset and not any(
            name=="project/"+active_asset for name,_src in entries
        ):
            active_asset=""
        active_scene=active.get("scene","")
        if active_scene and not (
            metadata/"layouts"/(active_scene+".scene.json")
        ).is_file():
            active_scene=""
        with ZipFile(temp,"w",ZIP_DEFLATED,compresslevel=6,allowZip64=True) as zipfile:
            for name,src in entries:
                if _is_link(src):
                    raise assets.WorkshopError("Quelldatei ist inzwischen verknüpft.")
                before=src.stat()
                digest=sha256()
                count=0
                with src.open("rb") as infile, zipfile.open(name,"w") as out:
                    for chunk in iter(lambda:infile.read(1024*1024),b""):
                        count+=len(chunk)
                        if count>MAX_ONE_FILE:
                            raise assets.WorkshopError("Quelldatei wurde zu groß.")
                        digest.update(chunk)
                        out.write(chunk)
                after=src.stat()
                if (_is_link(src) or
                    (before.st_size,before.st_mtime_ns)!=
                    (after.st_size,after.st_mtime_ns) or count!=before.st_size):
                    raise assets.WorkshopError("Projektdatei wurde beim Sichern geändert.")
                records.append({"path":name,"bytes":count,
                                "sha256":digest.hexdigest()})
            payload=json.dumps({
                "schema":SCHEMA,"project_name":root.name,"files":records,
                "selected_asset":active_asset,"selected_scene":active_scene,
            },ensure_ascii=False,sort_keys=True,indent=2).encode("utf8")+b"\n"
            if len(payload)>MAX_MANIFEST:
                raise assets.WorkshopError("Projektmanifest zu groß.")
            zipfile.writestr(MANIFEST,payload)
        archive_info(temp)  # Verify member list before exposing ZIP to the user.
        if output.exists() or _is_link(output):
            raise assets.WorkshopError("Archivziel wurde zwischenzeitlich erstellt.")
        # Exclusive creation; never replace a user file, even on exFAT.
        with open(output,"xb") as target:
            created_output=True
            with open(temp,"rb") as source:
                shutil.copyfileobj(source,target,length=1024*1024)
            target.flush()
            os.fsync(target.fileno())
        return {"archive":str(output),"files":len(records),
                "bytes":sum(row["bytes"] for row in records),
                "sha256":_file_sha(output)}
    except Exception:
        if created_output:
            output.unlink(missing_ok=True)
        raise
    finally:
        Path(temp).unlink(missing_ok=True)


def suggest_project_name(original: str, work: Path | None = None) -> str:
    """Offer a non-conflicting target name without writing anything to disk."""
    name=_name(original)
    folder=Path(work) if work is not None else assets.WORK
    base=folder/assets.BASELINES
    for index in range(100):
        suffix="" if index==0 else "-Kopie" if index==1 else "-Kopie-"+str(index)
        proposed=_name((name[:64-len(suffix)].rstrip(" -_")+suffix))
        metadata=base/("portable-"+_sha(proposed.casefold().encode("utf8"))[:24])
        if not any(
            item.exists() or _is_link(item) for item in (folder/proposed,metadata)
        ):
            return proposed
    raise assets.WorkshopError(
        "Kein freier Projektname gefunden. Bitte eigenen Namen eingeben."
    )


def _file_sha(path: Path)->str:
    digest=sha256()
    with path.open("rb") as src:
        for block in iter(lambda:src.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()


def restore_archive(archive: Path | str, *, project_name: str | None = None) -> dict:
    """Restore into a NEW work/ project and NEW metadata folder; never merge."""
    info=archive_info(archive)
    name=_name(project_name or info["project_name"])
    if _is_link(assets.WORK):
        raise assets.WorkshopError("Verknüpfter Arbeitsordner nicht zulässig.")
    work=assets.WORK.resolve()
    work.mkdir(parents=True,exist_ok=True)
    project=work/name
    base=work/assets.BASELINES
    if _is_link(base):
        raise assets.WorkshopError("Verknüpfter Metadatenordner nicht zulässig.")
    base.mkdir(parents=True,exist_ok=True)
    metadata=base/("portable-"+_sha(name.casefold().encode("utf8"))[:24])
    if any(path.exists() or _is_link(path) for path in (project,metadata)):
        raise assets.WorkshopError(
            "Projekt oder seine Metadaten existieren schon; neuen Namen wählen."
        )
    temp_project=Path(tempfile.mkdtemp(prefix=".restore-project-",dir=work))
    temp_metadata=Path(tempfile.mkdtemp(prefix=".restore-metadata-",dir=base))
    promoted_meta=False
    promoted_project=False
    try:
        index=info["manifest"]
        with ZipFile(archive) as reader:
            for row in index["files"]:
                relative=row["path"]
                target=(temp_project/relative[len("project/"):]) if relative.startswith(
                    "project/") else (temp_metadata/relative[len("metadata/"):])
                target.parent.mkdir(parents=True,exist_ok=True)
                digest=sha256()
                count=0
                with reader.open(relative) as src, open(target,"xb") as out:
                    for data in iter(lambda:src.read(1024*1024),b""):
                        count+=len(data)
                        if count>row["bytes"]:
                            raise assets.WorkshopError("Archivdatei größer als angegeben.")
                        digest.update(data)
                        out.write(data)
                if count!=row["bytes"] or digest.hexdigest()!=row["sha256"]:
                    raise assets.WorkshopError("Projektarchiv-Prüfsumme ist falsch.")
        # Promote metadata first. If the project rename fails, remove only
        # the new metadata created by THIS restore operation.
        if project.exists() or metadata.exists():
            raise assets.WorkshopError("Zielordner wurde zwischenzeitlich erstellt.")
        temp_metadata.rename(metadata)
        promoted_meta=True
        temp_project.rename(project)
        promoted_project=True
        try:
            save_session(
                project,
                asset=index.get("selected_asset",""),
                scene=index.get("selected_scene",""),
            )
        except (OSError,ValueError):
            # Session preferences are optional; the restored project is sound.
            pass
        return {"project":str(project),"files":info["files"],
                "bytes":info["bytes"],"source_name":info["project_name"]}
    except Exception as exc:
        if promoted_project and project.exists():
            shutil.rmtree(project)
        if promoted_meta and metadata.exists():
            shutil.rmtree(metadata)
        if isinstance(exc,(BadZipFile,EOFError,RuntimeError)):
            raise assets.WorkshopError(
                "Archiv beim Entpacken beschädigt; Wiederherstellung abgebrochen."
            ) from exc
        raise
    finally:
        if temp_project.exists():
            shutil.rmtree(temp_project)
        if temp_metadata.exists():
            shutil.rmtree(temp_metadata)
