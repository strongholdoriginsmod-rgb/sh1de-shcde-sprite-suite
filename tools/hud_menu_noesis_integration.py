"""Game-targeted, static Noesis/XAML integration for edited HUD/menu scenes.

This module creates the exact Script Extender asset-mod folder layout:
  Override/Assets/GUI/Images/<composite>.png
  Patches/Assets/GUI/XAML/<existing-game-file>.xaml

A real, user-selected and SHA-pinned Grid from the installed Extender XAML
must be identified before a patch is generated. Offline XML application is a
preflight, not evidence of a successful in-game load. No original game changes.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

from hud_menu_layout import (
    Scene, _atomic_save, _safe_output_path, audit_export,
    load_scene, prepare_package_source,
)
from hud_menu_workspace import WORK, WorkshopError, _existing, _metadata_dir, workspace
from se_asset_package import _check_xml, _discover, build as build_asset_mod

PRES = "http://schemas.microsoft.com/winfx/2006/xaml/presentation"
XNS = "http://schemas.microsoft.com/winfx/2006/xaml"
XNAME = "{"+XNS+"}Name"
GRID = "{"+PRES+"}Grid"
_IMAGE = "{"+PRES+"}Image"
_CANVAS = "{"+PRES+"}Canvas"
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,79}\Z")
_XAML_DOC = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,94}[.]xaml\Z")
SCHEMA = "sprite-suite.noesis-target-bindings.v1"
ALL_ALIGNMENTS = {
    "Oben links": ("Left","Top"), "Oben Mitte": ("Center","Top"),
    "Oben rechts": ("Right","Top"),
    "Mitte links": ("Left","Center"), "Mitte": ("Center","Center"),
    "Mitte rechts": ("Right","Center"),
    "Unten links": ("Left","Bottom"), "Unten Mitte": ("Center","Bottom"),
    "Unten rechts": ("Right","Bottom"),
}
_RESOURCE_BASE = "Override/Assets/GUI/Images/"
_REAL_SOURCE_PARTS = (
    "BepInEx","plugins","000shcdese","Override","Assets","GUI"
)
_MAX_XML = 4*1024*1024


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


@dataclass(frozen=True)
class GridTarget:
    xaml_document: str
    grid_name: str
    name_kind: str  # "x:Name" or "Name" (both supported by the patch API)
    source_sha256: str
    source_bytes: int
    extender_version: str
    horizontal_alignment: str = ""
    vertical_alignment: str = ""

    @property
    def label(self):
        name=("Gesamte Oberfläche (Wurzel-Grid)" if
              self.name_kind=="root" else self.grid_name)
        return f"{self.xaml_document} · {name}"

    @property
    def relative_patch(self):
        return f"Patches/Assets/GUI/XAML/{self.xaml_document}"

    @property
    def xpath(self):
        if self.name_kind=="root":
            return "/n:UserControl/n:Grid"
        attr="x:Name" if self.name_kind=="x:Name" else "Name"
        return f"//n:Grid[@{attr}='{self.grid_name}']"


def _reject_links(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise WorkshopError(f"Linked game/source path is not trusted: {part}")


def installed_gui(folder: str | Path) -> tuple[Path, str]:
    """Accept only a genuine SHCDESE-style installed XAML source root.

    No version allowlist: old and new SE installations can be inspected.
    A matching target is re-verified by file content immediately before build.
    """
    given=Path(folder)
    _reject_links(given)
    root=given.resolve(strict=True)
    if not root.is_dir() or tuple(root.parts[-6:])!=_REAL_SOURCE_PARTS:
        raise WorkshopError(
            "Select .../BepInEx/plugins/000shcdese/Override/Assets/GUI"
        )
    info=root.parent.parent.parent / "info.json"  # 000shcdese/info.json
    if not info.is_file() or info.is_symlink():
        raise WorkshopError("Installed Script Extender info.json missing")
    try:
        record=json.loads(info.read_text("utf8"))
    except (OSError,UnicodeError,ValueError) as exc:
        raise WorkshopError("Cannot read installed Script Extender metadata") from exc
    if not isinstance(record,dict) or record.get("GUID")!="000shcdese":
        raise WorkshopError("This is not the expected installed SE plugin")
    if not (root/"XAML").is_dir():
        raise WorkshopError("No installed Noesis XAML collection")
    version=str(record.get("Version","unknown"))[:80]
    return root,version


def _source_document(root: Path, document: str) -> tuple[Path,bytes,ET.Element]:
    if not _XAML_DOC.fullmatch(document):
        raise WorkshopError("Unsafe or unsupported Noesis XAML filename")
    source=root/"XAML"/document
    _reject_links(source)
    if not source.is_file() or source.stat().st_size>_MAX_XML:
        raise WorkshopError("Noesis XAML source missing or too large")
    raw=source.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise WorkshopError("Untrusted DTD/ENTITY in source Noesis XAML")
    try:
        parsed=ET.fromstring(raw)
    except ET.ParseError as exc:
        raise WorkshopError("Installed Noesis XAML cannot be XML parsed") from exc
    return source,raw,parsed


def _grids(parsed: ET.Element):
    for node in parsed.iter():
        if node.tag != GRID:
            continue
        xname=node.get(XNAME)
        name=node.get("Name")
        if xname and _NAME.fullmatch(xname):
            yield node,xname,"x:Name"
        elif name and _NAME.fullmatch(name):
            yield node,name,"Name"


def _matches(parsed: ET.Element, name: str) -> list[tuple]:
    # The anonymous immediate child Grid is a valid, unique global menu
    # target without inventing an x:Name. It is rechecked by full XML hash.
    if name=="__ROOT_GRID__":
        if parsed.tag!="{"+PRES+"}UserControl":
            return []
        grids=[node for node in parsed if node.tag==GRID]
        return [(grids[0],name,"root")] if len(grids)==1 else []
    # Reject collisions even when one tag uses Name, the other x:Name.
    return [row for row in _grids(parsed) if row[1]==name]


def discover_grid_targets(game_gui: str | Path) -> list[GridTarget]:
    root,version=installed_gui(game_gui)
    files=sorted((root/"XAML").glob("*.xaml"))
    if len(files)>150:
        raise WorkshopError("Unusually large XAML source collection")
    result=[]
    for file in files:
        try:
            _,source,parsed=_source_document(root,file.name)
        except WorkshopError:
            # A malformed unrelated upstream file does not block every
            # version; user can still select other verified documents.
            continue
        rows=list(_grids(parsed))
        if parsed.tag=="{"+PRES+"}UserControl":
            immediate=[element for element in parsed if element.tag==GRID]
            if len(immediate)==1:
                rows.append((immediate[0],"__ROOT_GRID__","root"))
        counts={}
        for _,name,_ in rows: counts[name]=counts.get(name,0)+1
        for node,name,kind in rows:
            if counts[name]!=1:
                continue
            result.append(GridTarget(
                xaml_document=file.name,grid_name=name,name_kind=kind,
                source_sha256=_digest(source),source_bytes=len(source),
                extender_version=version,
                horizontal_alignment=node.get("HorizontalAlignment",""),
                vertical_alignment=node.get("VerticalAlignment",""),
            ))
    if not result:
        raise WorkshopError("No uniquely named Grid elements in installed XAML")
    return result


def verify_grid_target(game_gui: Path | str, target: GridTarget) -> tuple[ET.Element,ET.Element]:
    root,version=installed_gui(game_gui)
    _,contents,parsed=_source_document(root,target.xaml_document)
    if len(contents)!=target.source_bytes or _digest(contents)!=target.source_sha256:
        raise WorkshopError(
            "Installed game/SE XAML changed since target selection; scan again"
        )
    matches=_matches(parsed,target.grid_name)
    if len(matches)!=1 or matches[0][2]!=target.name_kind:
        raise WorkshopError("Selected Grid is missing, renamed or ambiguous")
    return parsed,matches[0][0]


def _grid_spans(grid: ET.Element) -> tuple[int,int]:
    """Fill all explicit Grid rows/columns, not only the first HUD cell."""
    def count(owner: str, entry: str) -> int:
        parent="{"+PRES+"}"+owner
        child="{"+PRES+"}"+entry
        n=max((sum(item.tag==child for item in section)
               for section in grid if section.tag==parent),default=1)
        if n>256:
            raise WorkshopError("Noesis target Grid has too many definitions")
        return max(1,n)
    return count("Grid.RowDefinitions","RowDefinition"),count(
        "Grid.ColumnDefinitions","ColumnDefinition")


def _mod_overlay(scene: Scene, target: GridTarget, *, alignment: str,
                 rows: int=1, cols: int=1) -> bytes:
    if alignment not in ALL_ALIGNMENTS:
        raise WorkshopError("Invalid UI attachment alignment")
    if not scene.target_resource.startswith(_RESOURCE_BASE):
        raise WorkshopError("A baked GUI image resource is required")
    name=Path(scene.target_resource).name
    if any(ch in name for ch in ('"',"'",'<','>','&','/','\\')):
        raise WorkshopError("Resource name cannot be represented in Noesis XAML")
    horiz,vert=ALL_ALIGNMENTS[alignment]
    overlay_id="SpriteSuite_"+_digest((
        scene.name+"/"+target.xaml_document+"/"+target.grid_name
    ).encode("utf8"))[:16]
    xpath=target.xpath
    image_uri="/Assets/GUI/Images/"+name
    # Do not intercept existing game button clicks; static asset mods have
    # no ViewModel, so making a new clickable button would be misleading.
    patch=(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Patch>\n'
        f'  <Operation Type="Add" XPath={quoteattr(xpath)}>\n'
        '    <Content>\n'
        f'      <Canvas xmlns={quoteattr(PRES)} xmlns:x={quoteattr(XNS)}'
        f' x:Name={quoteattr(overlay_id)}'
        f' Grid.RowSpan="{rows}" Grid.ColumnSpan="{cols}"'
        ' IsHitTestVisible="False" ClipToBounds="False"'
        f' Width="{scene.width}" Height="{scene.height}"'
        f' HorizontalAlignment="{horiz}" VerticalAlignment="{vert}">\n'
        f'        <Image Source={quoteattr(image_uri)}'
        f' Width="{scene.width}" Height="{scene.height}"'
        ' Stretch="Fill" Canvas.Left="0" Canvas.Top="0"'
        ' IsHitTestVisible="False"/>\n'
        '      </Canvas>\n'
        '    </Content>\n'
        '  </Operation>\n'
        '</Patch>\n'
    )
    return patch.encode("utf8")


def generate_patch(scene: Scene, project: str | Path, *,
                   game_gui: str | Path, target: GridTarget,
                   alignment: str="Oben links", scene_sha256: str) -> tuple[bytes,dict]:
    root=workspace(project)
    scene.validate(root)
    export=audit_export(scene,root,scene_sha256=scene_sha256)
    original,selected=verify_grid_target(game_gui,target)
    gui,_=installed_gui(game_gui)
    if (gui/"Images"/Path(scene.target_resource).name).exists():
        raise WorkshopError(
            "Composite name already exists in the installed game: "
            "choose a unique exported PNG resource name"
        )
    rows,cols=_grid_spans(selected)
    patch=_mod_overlay(scene,target,alignment=alignment,rows=rows,cols=cols)
    try:
        xml=ET.fromstring(patch)
        op=xml.find("Operation")
        if op is None or op.get("Type")!="Add" or op.get("XPath")!=target.xpath:
            raise WorkshopError("Malformed generated patch operation")
        content=op.find("Content")
        if content is None or len(content)!=1:
            raise WorkshopError("Patch does not contain one Noesis visual")
        canvas=content[0]
        if canvas.tag!=_CANVAS or len(canvas)!=1 or canvas[0].tag!=_IMAGE:
            raise WorkshopError("Generated visual does not bind the exported PNG")
        if (canvas.get("Grid.RowSpan")!=str(rows) or
                canvas.get("Grid.ColumnSpan")!=str(cols)):
            raise WorkshopError("Generated overlay does not fill target Grid")
        if canvas[0].get("Source")!="/"+scene.target_resource.removeprefix("Override/"):
            raise WorkshopError("Noesis Source does not match the exported resource")
        # Model an Add operation on an unmodified copy of the installed DOM.
        import copy
        before=len(list(original.iter()))
        selected.append(copy.deepcopy(canvas))
        if len(list(original.iter())) <= before:
            raise WorkshopError("Offline patch did not add the overlay")
        simulation=ET.tostring(original,encoding="utf8")
    except (ET.ParseError,IndexError,TypeError) as exc:
        raise WorkshopError("Generated XAML failed offline DOM validation") from exc
    report={
        "schema":SCHEMA,
        "game_xaml":target.xaml_document,
        "target_grid":target.grid_name,
        "target_xpath":target.xpath,
        "target_grid_rows":rows,"target_grid_columns":cols,
        "source_xaml_sha256":target.source_sha256,
        "installed_extender_version":target.extender_version,
        "alignment":alignment,
        "operation":"Add",
        "patch_path":target.relative_patch,
        "patch_sha256":_digest(patch),
        "resource":scene.target_resource,
        "png_sha256":export["png_sha256"],
        "layout_sha256":scene_sha256,
        "offline_patched_xml_sha256":_digest(simulation),
        "render_only":True,
        "no_custom_click_handlers":True,
        "no_game_files_were_modified":True,
        "ingame_rendering_verified":False,
    }
    return patch,report


def stage_binding(scene: Scene, project: str | Path, *,
                  scene_sha256: str, game_gui: str | Path,
                  target: GridTarget, alignment: str="Oben links",
                  include_existing_patches: bool=False) -> tuple[Path,dict]:
    root=workspace(project)
    patch,report=generate_patch(
        scene,root,game_gui=game_gui,target=target,
        alignment=alignment,scene_sha256=scene_sha256,
    )
    # Prepare a clean package, never the raw editable assets. Deliberately
    # include only the checked, position-correct composite and this patch.
    original=prepare_package_source(
        scene,root,scene_sha256=scene_sha256,
        include_patches=include_existing_patches,
    )
    import se_asset_package
    baseline=_discover(original)
    expected={relative:digest for relative,_,_,digest in baseline}
    if target.relative_patch in expected:
        raise WorkshopError("An authored patch already targets the same XAML file")
    expected[target.relative_patch]=_digest(patch)
    identity=_digest(json.dumps(
        sorted(expected.items()),separators=(",",":")
    ).encode("utf8"))[:24]
    base=WORK.resolve()/"hud-menu-noesis-sources"
    dest=base/(scene.name+"-"+identity)
    _safe_output_path(dest)
    def validate(folder: Path):
        _safe_output_path(folder)
        if not folder.is_dir() or folder.is_symlink():
            raise WorkshopError("Noesis staging source is missing or linked")
        indexed={relative:digest for relative,_,_,digest in _discover(folder)}
        if indexed!=expected:
            raise WorkshopError("Noesis staging files do not match the source pins")
    if dest.exists():
        validate(dest)
        return dest,report
    base.mkdir(parents=True,exist_ok=True)
    temporary=Path(tempfile.mkdtemp(prefix=".noesis-stage-",dir=base))
    try:
        for relative,source,_,digest in baseline:
            destfile=temporary/relative
            destfile.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,destfile)
            if _digest(destfile.read_bytes())!=digest:
                raise WorkshopError("Original composite changed during staging")
        patchfile=temporary/target.relative_patch
        patchfile.parent.mkdir(parents=True,exist_ok=True)
        patchfile.write_bytes(patch)
        _check_xml(patchfile,patch=True)
        validate(temporary)
        # Do not blindly overwrite an existing, other caller's staged files.
        if dest.exists():
            validate(dest)
        else:
            os.rename(temporary,dest)
        return dest,report
    finally:
        if temporary.exists():
            shutil.rmtree(temporary,ignore_errors=True)


def build_bound_mod(scene: Scene, project: Path | str, *,
                    scene_sha256: str, game_gui: str | Path,
                    target: GridTarget, alignment: str, guid: str,
                    name: str, include_existing_patches: bool=False) -> dict:
    root=workspace(project)
    source,report=stage_binding(
        scene,root,scene_sha256=scene_sha256,game_gui=game_gui,
        target=target,alignment=alignment,
        include_existing_patches=include_existing_patches,
    )
    # The established static asset package builder forbids DLLs and protects
    # existing package GUIDs; do not bypass it with custom ZIP logic.
    mod=build_asset_mod(source,guid,name=name,author="Sprite Suite")
    meta=_metadata_dir(root)/"noesis-bindings"/(
        scene.name+"-"+report["patch_sha256"][:16]+".json")
    _safe_output_path(meta)
    raw=(json.dumps(report,ensure_ascii=False,indent=2)+"\n").encode("utf8")
    expected_hash=_digest(meta.read_bytes()) if meta.is_file() else None
    _atomic_save(meta,raw,expected_hash=expected_hash)
    return {
        **mod, "target":report,"binding_report":str(meta),
        "stage_source":str(source),
    }


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("list","build"))
    parser.add_argument("--gui",type=Path,required=True,
                        help="Installed .../000shcdese/Override/Assets/GUI")
    parser.add_argument("--project",type=Path)
    parser.add_argument("--scene",default="menu-layout")
    parser.add_argument("--xaml-document")
    parser.add_argument("--grid")
    parser.add_argument("--alignment",default="Oben links",
                        choices=tuple(ALL_ALIGNMENTS))
    parser.add_argument("--guid")
    parser.add_argument("--name")
    parser.add_argument("--include-user-xaml",action="store_true")
    args=parser.parse_args(argv)
    try:
        targets=discover_grid_targets(args.gui)
        if args.command=="list":
            print(json.dumps([
                {"file":t.xaml_document,"grid":t.grid_name,
                 "xpath":t.xpath,"source_sha256":t.source_sha256,
                 "se_version":t.extender_version}
                for t in targets
            ],indent=2))
            return 0
        if not all((args.project,args.xaml_document,args.grid,
                    args.guid,args.name)):
            raise WorkshopError("Build requires project, XAML, grid, GUID and name")
        selected=[t for t in targets if (
            t.xaml_document==args.xaml_document and t.grid_name==args.grid)]
        if len(selected)!=1:
            raise WorkshopError("A unique existing Noesis Grid must be selected")
        scene,etag=load_scene(args.project,args.scene)
        result=build_bound_mod(
            scene,args.project,scene_sha256=etag,game_gui=args.gui,
            target=selected[0],alignment=args.alignment,guid=args.guid,
            name=args.name,include_existing_patches=args.include_user_xaml,
        )
        print(json.dumps(result,indent=2,ensure_ascii=False))
        return 0
    except (OSError,ValueError,RuntimeError) as exc:
        print("NOESIS_BINDING_ERROR:",str(exc),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
