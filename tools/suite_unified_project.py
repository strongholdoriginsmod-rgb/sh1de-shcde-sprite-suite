"""One real SpriteSuite project from original import through independently checked ZIP.

This is a coordinator over EXISTING image, Noesis and Script Extender
implementations, not another competing renderer, editor or exporter.
Only work/ projects are writable. Installed game originals remain read-only.
"""
from __future__ import annotations

from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
from secrets import token_hex
from zipfile import ZipFile

import hud_menu_workspace as hud
from suite_windows_paths import is_link_or_reparse
from suite_hud_menu_session import read_session, save_session
from se_asset_package import build as build_static_mod, AssetModError, package_zip_path


class UnifiedFlowError(ValueError):
    pass


SOURCE_SCHEMA = "sprite-suite.unified-source.v1"
RECEIPT_SCHEMA = "sprite-suite.unified-project-export.v1"


def _sha_file(path: Path) -> str:
    with Path(path).open("rb") as file:
        return _sha_stream(file)


def _sha_stream(stream) -> str:
    return file_digest(stream, "sha256").hexdigest()


def project_id(project: Path) -> str:
    root = hud.workspace(project)
    rel = root.relative_to(hud.WORK.resolve()).as_posix()
    return sha256(rel.encode("utf8")).hexdigest()[:16]


def project_from_recent() -> Path:
    record = read_session()
    try:
        return hud.workspace(record.get("project", hud.DEFAULT), create=True)
    except (ValueError, OSError):
        return hud.workspace(hud.DEFAULT, create=True)


def new_project(slug: str) -> Path:
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,49}", slug):
        raise UnifiedFlowError("Projekt-ID: 3–50 Zeichen, a-z, 0-9 und Bindestrich")
    output = hud.WORK / "projects" / slug
    if output.exists() or is_link_or_reparse(output):
        raise UnifiedFlowError("Projekt existiert bereits – bitte vorhandenes Projekt öffnen")
    # Only the caller activates a new project, after it has confirmed
    # that all editors from the previous project are saved.
    return hud.workspace(output, create=True)


class ProjectPipeline:
    """Single source of truth shared by visual, pixel, layout and mod editors."""

    def __init__(self, project: Path):
        self.project = hud.workspace(project, create=True)

    def activate(self) -> Path:
        save_session(self.project)
        return self.project

    def import_image(self, path: Path, *, category: str = "Menüs / UI-Bilder") -> Path:
        return hud.import_image(path, folder=category, project=self.project)

    def import_mod_file(self, path: Path, *, relative: str) -> Path:
        return hud.import_mod_file(path, relative, project=self.project)

    def create_image(self, name: str, width: int, height: int,
                     *, category: str = "Menüs / UI-Bilder") -> Path:
        return hud.create_image(name,width,height,folder=category,project=self.project)

    def import_patch(self, path: Path, *, game_document: str | None = None) -> Path:
        original=Path(path)
        # This is an already-authored Script Extender patch, never a full
        # UserControl XAML silently reclassified as a patch.
        from xml.etree import ElementTree as ET
        parsed=ET.fromstring(original.read_bytes())
        if parsed.tag.split("}")[-1] not in ("Patch","XamlPatch"):
            raise UnifiedFlowError(
                "Vollständige Noesis-Seiten zuerst im Seiten-Designer bearbeiten")
        document=game_document or "XAML/"+original.name
        return hud.import_patch(original, target_document=document,
                                project=self.project)

    def _source_dir(self) -> Path:
        # Existing project transfer already archives this metadata folder.
        # Portable Noesis sources must follow the editable project.
        return hud._metadata_dir(self.project)/"origins-sources"

    def register_original_xaml(self, path: Path) -> Path:
        """Private SHA-checked immutable snapshot, independent of game directory."""
        from origins_visual_document import VisualXamlDocument
        original=Path(path)
        if not original.is_file() or is_link_or_reparse(original):
            raise UnifiedFlowError("Original-XAML fehlt oder ist verlinkt")
        if (not re.fullmatch(r"[^\\/:*?\"<>|]{1,125}\.xaml",original.name,re.I)
                or original.name.startswith(".")):
            raise UnifiedFlowError("Ungültiger XAML-Dateiname")
        # Validate genuine Noesis XAML, not just the file extension.
        source=VisualXamlDocument(original)
        if source.root.tag.split("}")[-1] in ("Patch","XamlPatch"):
            raise UnifiedFlowError("Bestehende Patches bitte direkt importieren")
        blob=source.source_bytes
        digest=sha256(blob).hexdigest()
        folder=self._source_dir()
        if is_link_or_reparse(folder):
            raise UnifiedFlowError("Verknüpftes Quellenverzeichnis ist unsicher")
        # Short digest directory avoids the Windows legacy MAX_PATH boundary.
        # The entire SHA-256 still guards the original byte sequence.
        snapshot=folder/digest[:16]/original.name
        if snapshot.exists():
            if is_link_or_reparse(snapshot) or sha256(snapshot.read_bytes()).hexdigest()!=digest:
                raise UnifiedFlowError("Original-Sicherung widerspricht dem SHA-256")
        else:
            snapshot.parent.mkdir(parents=True,exist_ok=True)
            with snapshot.open("xb") as stream:
                stream.write(blob)
        state={
            "schema":SOURCE_SCHEMA, "filename":original.name,
            "sha256":digest,
            "original_path":str(original.resolve()),
            "snapshot":str(snapshot.relative_to(folder).as_posix()),
        }
        folder.mkdir(parents=True,exist_ok=True)
        destination=folder/"current.json"
        temporary=folder/(".source-"+token_hex(7)+".json")
        try:
            with temporary.open("x",encoding="utf8") as opened:
                json.dump(state,opened,ensure_ascii=False,indent=2)
                opened.write("\n")
            os.replace(temporary,destination)
        finally:
            temporary.unlink(missing_ok=True)
        return snapshot

    def original_xaml(self) -> Path | None:
        folder=self._source_dir()
        state=folder/"current.json"
        if not state.is_file():
            return None
        if is_link_or_reparse(state) or state.stat().st_size>8192:
            raise UnifiedFlowError("Veränderte XAML-Quellenliste")
        data=json.loads(state.read_text("utf8"))
        if not isinstance(data,dict) or data.get("schema")!=SOURCE_SCHEMA:
            raise UnifiedFlowError("Unbekanntes Quellenregister")
        name=data.get("filename")
        digest=data.get("sha256")
        if (not isinstance(name,str) or not re.fullmatch(r"[^\\/:*?\"<>|]{1,125}\.xaml",name,re.I)
                or not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest)):
            raise UnifiedFlowError("Ungültige Original-Dateibezeichnung")
        relative=data.get("snapshot")
        if relative not in (f"{digest[:16]}/{name}",f"{digest}/{name}"):
            raise UnifiedFlowError("Original-XAML-Snapshot-Bezeichnung stimmt nicht")
        result=folder/relative
        if (
                not result.is_file() or is_link_or_reparse(result) or
                not result.resolve().is_relative_to(folder.resolve()) or
                sha256(result.read_bytes()).hexdigest()!=digest):
            raise UnifiedFlowError("Original-XAML-Snapshot fehlt oder hat sich geändert")
        return result

    def latest_visual_revision(self) -> Path | None:
        source=self.original_xaml()
        if source is None:
            return None
        metadata=hud._metadata_dir(self.project)
        revision_root=metadata/"origins-revisions"/source.name
        if not revision_root.is_dir():
            # Older installed versions keep a separate read-only history.
            # Reopening it remains possible; the next save writes portable
            # revisions and does not alter or erase the older records.
            revision_root=(hud.WORK.resolve()/".origins-visual-revisions"/
                           project_id(self.project)/source.name)
        if is_link_or_reparse(revision_root) or not revision_root.is_dir():
            return None
        for candidate in sorted(revision_root.glob("rev-[0-9][0-9][0-9][0-9]"),
                                reverse=True):
            if candidate.is_dir() and not is_link_or_reparse(candidate):
                # Only revive the editor if this revision really belongs to
                # the currently chosen original XAML, not another snapshot.
                stored=candidate/"source.xaml"
                if (stored.is_file() and not is_link_or_reparse(stored) and
                        sha256(stored.read_bytes()).digest()==
                        sha256(source.read_bytes()).digest()):
                    return candidate
        return None

    def _last_export_file(self) -> Path:
        return self._source_dir()/"last-export.json"

    def latest_export(self) -> dict | None:
        pointer=self._last_export_file()
        if not pointer.is_file():return None
        if is_link_or_reparse(pointer) or pointer.stat().st_size>4096:
            raise UnifiedFlowError("Exportverweis ist nicht vertrauenswürdig")
        ref=json.loads(pointer.read_text("utf8"))
        if (not isinstance(ref,dict) or ref.get("schema")!=RECEIPT_SCHEMA or
            ref.get("project")!=str(self.project)):
            raise UnifiedFlowError("Exportverweis gehört nicht zu diesem Projekt")
        receipt_name=ref.get("receipt")
        if (not isinstance(receipt_name,str) or not receipt_name or
                len(receipt_name)>2048):
            raise UnifiedFlowError("Exportverweis enthält keinen gültigen Belegpfad")
        source=Path(receipt_name)
        base=(hud.WORK.resolve()/"se-asset-mods")
        if (not source.is_file() or is_link_or_reparse(source) or
            not source.resolve().is_relative_to(base)):
            raise UnifiedFlowError("Vorheriger Exportbeleg fehlt oder liegt außerhalb von work/")
        if source.stat().st_size>65536:
            raise UnifiedFlowError("Exportbeleg ist zu groß")
        proof=json.loads(source.read_text("utf8"))
        if (not isinstance(proof,dict) or
                proof.get("schema")!=RECEIPT_SCHEMA or
                proof.get("project")!=str(self.project) or
                proof.get("zip_verified_against_project") is not True):
            raise UnifiedFlowError("Vorheriger Exportbeleg ist unpassend")
        package_name=proof.get("zip")
        package_bytes=proof.get("zip_bytes")
        package_sha=proof.get("zip_sha256")
        asset_sha=proof.get("assets_sha256")
        if (not isinstance(package_name,str) or not package_name or
                len(package_name)>2048 or
                type(package_bytes) is not int or package_bytes<1 or
                not isinstance(package_sha,str) or
                not re.fullmatch(r"[0-9a-f]{64}",package_sha) or
                not isinstance(asset_sha,str) or
                not re.fullmatch(r"[0-9a-f]{64}",asset_sha)):
            raise UnifiedFlowError("Exportbeleg enthält ungültige ZIP- oder Hashdaten")
        package=Path(package_name)
        if (not package.is_file() or is_link_or_reparse(package) or
            not package.resolve().is_relative_to(base) or
            package.stat().st_size!=package_bytes or
            _sha_file(package)!=package_sha):
            raise UnifiedFlowError("Vorherige Mod-ZIP-Datei ist verändert oder fehlt")
        try:current=self.audit()["bytes_sha256"]==asset_sha
        except (OSError,ValueError,AssetModError):current=False
        return {**proof,"receipt":str(source),"project_current":current}

    def assets(self) -> list[hud.WorkshopAsset]:
        return hud.list_assets(self.project, include_mod_files=True)

    def audit(self) -> dict:
        assets=self.assets()
        evidence=hud.audit_assets(self.project)
        warnings=[]
        image_names=[a.name for a in assets if
                    a.relative_path.startswith("Override/Assets/GUI/Images/")]
        patch_bytes=[a.path.read_bytes() for a in assets if
                     a.relative_path.startswith("Patches/") and
                     a.path.suffix.lower()==".xaml"]
        for name in image_names:
            if not any(name.encode("utf8") in doc for doc in patch_bytes):
                warnings.append(
                    "Kein Verweis auf "+name+" in den Projekt-XAML-Patches; "+
                    "bestehende Spielreferenz muss separat geprüft werden")
        if any(b"LegacyStart" in doc or b"OriginsLegacyCampaign" in doc
               for doc in patch_bytes):
            warnings.append("Neue Legacy-Menübefehle benötigen einen separat "+
                            "im Spiel verifizierten C#-Handler")
        if any(a.relative_path.startswith("Override/Sprites/") for a in assets):
            warnings.append("Spiel-Sprite-Indizes und Atlaszuordnung sind "+
                            "im statischen ZIP nicht ingame nachgewiesen")
        return {**evidence,"warnings":warnings,"project":str(self.project),
                "native_game_runtime_verified":False,
                "original_game_files_modified":False}

    def build(self, *, guid: str, name: str, author: str = "SpriteSuite", version: str = "1.0.0",
              output: Path | None = None) -> dict:
        """Real guarded exporter; never silently call native game installation."""
        preflight=self.audit()
        target=Path(output) if output is not None else (
            hud.WORK/"se-asset-mods"/(guid+"-export-"+token_hex(6)))
        if target.exists() or package_zip_path(target).exists():
            raise UnifiedFlowError("Zielpaket existiert bereits; kein Überschreiben")
        result=build_static_mod(self.project,guid,name=name,author=author,version=version,
                                target=target)
        package=Path(result["zip"])
        if not package.is_file():
            raise UnifiedFlowError("Export meldete ZIP, aber ZIP-Datei fehlt")
        from se_asset_package import _discover
        expected=_discover(self.project)
        members={f"BepInEx/plugins/{guid}/{row[0]}" for row in expected}
        manifest_path=f"BepInEx/plugins/{guid}/info.json"
        has_custom_manifest=any(member.casefold()==manifest_path.casefold() for member in members)
        if not has_custom_manifest:
            members.add(manifest_path)
        with ZipFile(package) as archive:
            if archive.testzip() is not None:
                raise UnifiedFlowError("ZIP CRC ungültig")
            found=set(archive.namelist())
            if found!=members or len(found)!=len(archive.infolist()):
                raise UnifiedFlowError("ZIP-Inhalt entspricht nicht dem bearbeiteten Projekt")
            for rel,_,_,digest in expected:
                with archive.open(f"BepInEx/plugins/{guid}/{rel}") as member:
                    actual=_sha_stream(member)
                if actual!=digest:
                    raise UnifiedFlowError("ZIP enthält geändertes Asset: "+rel)
            if not has_custom_manifest:
                manifest=json.loads(archive.read(manifest_path))
                if manifest.get("GUID")!=guid or manifest.get("Manifest")!=0:
                    raise UnifiedFlowError("Paketmanifest widerspricht Projekt")
        post=self.audit()
        if preflight["bytes_sha256"]!=post["bytes_sha256"]:
            raise UnifiedFlowError("Assets während des Exports verändert; nicht freigegeben")
        proof={
            "schema":RECEIPT_SCHEMA,
            "project":str(self.project),
            "guid":guid,"name":name,"asset_count":preflight["assets"],
            "assets_sha256":preflight["bytes_sha256"],
            "zip":str(package),"zip_bytes":package.stat().st_size,
            "zip_sha256":_sha_file(package),
            "zip_verified_against_project":True,
            "game_files_modified":False,
            "installed_into_game":False,
            "native_game_runtime_verified":False,
            "warnings":post["warnings"],
        }
        receipt=target.with_name(target.name+".receipt.json")
        with receipt.open("x",encoding="utf8") as stream:
            json.dump(proof,stream,ensure_ascii=False,indent=2)
            stream.write("\n")
        proof["receipt"]=str(receipt)
        folder=self._source_dir()
        if is_link_or_reparse(folder):
            raise UnifiedFlowError("Verknüpfter Exportstatus nicht zulässig")
        folder.mkdir(parents=True,exist_ok=True)
        state=folder/"last-export.json"
        temporary=folder/(".export-"+token_hex(7)+".json")
        try:
            with temporary.open("x",encoding="utf8") as stream:
                json.dump({"schema":RECEIPT_SCHEMA,"project":str(self.project),
                           "receipt":str(receipt)},stream,ensure_ascii=False)
                stream.write("\n")
            os.replace(temporary,state)
        finally:temporary.unlink(missing_ok=True)
        return proof
