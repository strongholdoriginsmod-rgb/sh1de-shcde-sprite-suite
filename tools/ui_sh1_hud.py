"""Editable, source-pinned Stronghold 1 DE HUD workflow for Sprite Suite.

Commands:
    export --source <installed game's globalgamemanagers.assets> --out work/sh1-hud-editierbar
    check  --from work/sh1-hud-editierbar
    build  --from work/sh1-hud-editierbar --out dist/sh1-hud-editierte-atlanten

All outputs are local project working copies; never patch an installed game.
The SH1 dictionaries are extracted from SH1 MonoBehaviours, not SHCDE XAML.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import struct
import tempfile
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from ui_atlas import Crop, UiAtlasError, _reject_overlaps, read_atlas

ATLAS_NAMES = ("UI-MasterAtlas", "UI-ROL", "UI-CandleAtlas")
SCHEMA = "sprite-suite.stronghold1.hud-edit.v1"
BUILD_ID = "stronghold-1-definitive-edition-original-hud-v1"
DEFAULT_WORK = ROOT / "work" / "sh1-hud-editierbar"
DEFAULT_DIST = ROOT / "dist" / "sh1-hud-editierte-atlanten"

class HudError(RuntimeError):
    pass


def monobehaviour_name(raw: bytes) -> str:
    """Read the original SH1 Noesis MonoBehaviour m_Name without side effects.

    Uses the fixed Unity IL2CPP header also used by legacy ui_sh1_dict.py.
    The portable editor must not import another tool that can globally
    change Pillow's decompression-bomb protection.
    """
    if len(raw) < 32:
        return ""
    (length,) = struct.unpack_from("<i", raw, 28)
    if length <= 0 or length >= 200 or 32 + length > len(raw):
        return ""
    return raw[32:32 + length].decode("utf-8", "replace")


def digest_file(file: Path) -> str:
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def pixel_digest(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()

def ensure_under(path: Path, section: str) -> Path:
    resolved = path.resolve()
    root = (ROOT / section).resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise HudError(f"Ausgabe muss UNTER {root} liegen: {resolved}")
    return resolved

def locate(folder: str | Path) -> Path:
    raw = Path(folder)
    return (raw if raw.is_absolute() else ROOT / raw).resolve()


def require_disjoint_output(target: Path, *sources: Path) -> None:
    """Reject targets that replace or live inside their own input worktree.

    In particular, --replace must never rename an input folder to a backup
    and then delete it as part of a successful output commit.
    """
    destination = target.resolve()
    for source in sources:
        original = Path(source).resolve()
        if (original == destination or original.is_relative_to(destination)
                or destination.is_relative_to(original)):
            raise HudError(
                f"Quelle und Ziel überschneiden sich: {original} / {destination}. "
                "Anderen Arbeits- bzw. Ausgabeordner wählen."
            )


def flat(name: object, label: str, extension: str | None = None) -> str:
    if not isinstance(name, str) or not name or len(name)>240 or name in (".", ".."):
        raise HudError(f"{label}: kein sicherer Dateiname")
    if Path(name).name != name or any(x in name for x in ("/", "\\", ":", "\x00")):
        raise HudError(f"{label}: Pfadverlassen untersagt")
    if extension and not name.endswith(extension):
        raise HudError(f"{label}: Dateiendung {extension} erwartet")
    return name

def json_read(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32*1024*1024:
        raise HudError(f"Manifest fehlt oder ist unsicher: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise HudError(f"Manifest ist kein Objekt: {path}")
    return value

def stage_for(target: Path, replace: bool) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not target.is_dir():
        raise HudError(f"Ausgabe ist keine reguläre Arbeitsmappe: {target}")
    if target.exists() and any(target.iterdir()) and not replace:
        raise HudError(f"Ausgabe nicht leer: {target}. Nur mit --replace ersetzen.")
    backup = target.with_name(target.name+".sh1-hud-sicherung")
    if backup.exists():
        raise HudError(f"Alte Sicherung bitte zuerst pruefen: {backup}")
    return Path(tempfile.mkdtemp(prefix="."+target.name+"-stage-",dir=target.parent))

def commit(stage: Path, target: Path, replace: bool) -> None:
    backup = target.with_name(target.name+".sh1-hud-sicherung")
    if target.exists():
        if not replace and any(target.iterdir()):
            raise HudError(f"Ziel waehrend des Exports belegt: {target}")
        os.replace(target, backup)
    try:
        os.replace(stage, target)
    except Exception:
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    if backup.exists():
        shutil.rmtree(backup)

def export_workspace(source: Path, target: Path, replace: bool) -> dict:
    if source.name != "globalgamemanagers.assets" or not source.is_file():
        raise HudError("Original Stronghold-1-Datei globalgamemanagers.assets angeben")
    target = ensure_under(target, "work")
    require_disjoint_output(target, source)
    stage = stage_for(target, replace)
    try:
        import UnityPy
        print("Lese Stronghold-1-Original:",source,flush=True)
        source_hash = digest_file(source)
        env = UnityPy.load(str(source))
        dictionaries: dict[str,bytes] = {}
        textures: dict[str,object] = {}
        for obj in env.objects:
            if obj.type.name == "MonoBehaviour":
                raw = bytes(obj.get_raw_data())
                name = monobehaviour_name(raw)
                if name not in ATLAS_NAMES:
                    continue
                start,end=raw.find(b"<ResourceDictionary"),raw.rfind(b"</ResourceDictionary>")
                if start<0 or end<=start or name in dictionaries:
                    raise HudError(f"Original-XAML nicht eindeutig: {name}")
                dictionaries[name]=raw[start:end+len(b"</ResourceDictionary>")]
            elif obj.type.name == "Texture2D":
                name = str(obj.peek_name() if hasattr(obj,"peek_name") else "")
                if name in ATLAS_NAMES:
                    if name in textures:
                        raise HudError(f"Textur doppelt: {name}")
                    textures[name]=obj
        if set(dictionaries)!=set(ATLAS_NAMES) or set(textures)!=set(ATLAS_NAMES):
            raise HudError("Original-Stronghold-1-UI-Dictionaries/Texturen fehlen: "+str((set(dictionaries),set(textures))))
        b = stage/"baseline"
        b.mkdir()
        index={"schema_version":1,"target_build_id":BUILD_ID,
               "texture_asset_name":"globalgamemanagers.assets",
               "texture_asset_sha256":source_hash,"atlases":[]}
        baseline_files=[]
        unique=set()
        for name in ATLAS_NAMES:
            xaml=b/(name+".xaml")
            # Unity XAML already includes CRLF. Text-mode writing on Windows
            # turns CRLF into CRCRLF and breaks byte-for-byte provenance.
            xaml.write_bytes(dictionaries[name])
            texture= textures[name].read().image.convert("RGBA")
            sheet, crops = read_atlas(xaml)
            if sheet != name+".png":
                raise HudError(f"{name}: Dictionary nennt fremden Atlas {sheet}")
            _reject_overlaps(crops,name)
            sheet_file=b/(name+".png")
            texture.save(sheet_file,"PNG")
            entries=[]
            folder=stage/name
            folder.mkdir()
            for crop in crops:
                if crop.key in unique:
                    raise HudError(f"Mehrfacher Key ueber Atlanten: {crop.key}")
                unique.add(crop.key)
                if crop.x<0 or crop.y<0 or crop.x+crop.width>texture.width or crop.y+crop.height>texture.height:
                    raise HudError(f"Ungültiges XAML-Rechteck: {name}/{crop.key}")
                img=texture.crop(crop.box)
                img.save(folder/crop.filename,"PNG")
                entries.append({"key":crop.key,"file":crop.filename,"x":crop.x,"y":crop.y,
                     "width":crop.width,"height":crop.height,"baseline_pixels_sha256":pixel_digest(img)})
            index["atlases"].append({
                 "dictionary":name+".xaml","dictionary_sha256":digest_file(xaml),
                 "sheet":sheet,"sheet_width":texture.width,"sheet_height":texture.height,
                 "directory":name,"crops":entries})
            baseline_files.append({"sheet":sheet,"sha256":digest_file(sheet_file),"dictionary":xaml.name,"dictionary_sha256":digest_file(xaml)})
            print("SH1-HUD",name,len(entries),"editierbare PNGs",texture.size,flush=True)
        (stage/"index.json").write_text(json.dumps(index,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        meta={"schema":SCHEMA,"source":"Stronghold 1 Definitive Edition",
              "source_globalgamemanagers_sha256":source_hash,"source_globalgamemanagers_bytes":source.stat().st_size,
              "baseline_files":baseline_files,"editable_images":len(unique),
              "output_note":"Only PNGs/XAML are exported. No Unity game files are patched."}
        (stage/"sh1_hud_source.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (stage/"BITTE_LESEN.md").write_text(
            "# Stronghold 1 DE HUD - Sprite Suite Bearbeitungsprojekt\n"
            "In Sprite Suite > UI-Fläche > 'SH1-HUD laden' öffnen, Bild auswählen und "
            "'SH1-Bild bearbeiten' anklicken. Pixelabmessungen dürfen sich nicht ändern.\n\n"
            "Nach der Bearbeitung 'SH1 prüfen', dann 'SH1-Atlanten bauen' verwenden.\n"
            "Das erstellt drei vollständig rekonstruierte PNG-Atlanten in dist/, "
            "ohne die Original-Unity-Datei zu überschreiben.\n"
            "Nicht die Crusader-Buttons 'Alles prüfen'/'Produktionsprofil' verwenden.\n",
            encoding="utf-8")
        commit(stage,target,replace)
        print("SH1-HUD-EXPORT_OK",len(unique),target,flush=True)
        return meta
    finally:
        if stage.exists():shutil.rmtree(stage)

def check_workspace(source: Path, *, construct: bool = False):
    source=locate(source)
    idx=json_read(source/"index.json")
    meta=json_read(source/"sh1_hud_source.json")
    if set(idx)!={"schema_version","target_build_id","texture_asset_name","texture_asset_sha256","atlases"}:
        raise HudError("Unpassender SH1-UI-Index")
    if idx["schema_version"]!=1 or idx["target_build_id"]!=BUILD_ID or idx["texture_asset_name"]!="globalgamemanagers.assets":
        raise HudError("Kein Stronghold-1-DE-HUD-Export (Crusader-Index?)")
    if meta.get("schema")!=SCHEMA or meta.get("source_globalgamemanagers_sha256")!=idx["texture_asset_sha256"]:
        raise HudError("HUD-Herkunft und Index widersprechen sich")
    atlas_entries = idx["atlases"]
    if not isinstance(atlas_entries,list) or len(atlas_entries)!=3:
        raise HudError("Original-HUD benoetigt alle 3 Atlaslisten")
    original_baselines = meta.get("baseline_files")
    if (not isinstance(original_baselines,list) or len(original_baselines)!=3
        or any(not isinstance(entry,dict)
               or not all(isinstance(entry.get(field),str) for field in
                          ("sheet","dictionary","sha256","dictionary_sha256"))
               for entry in original_baselines)):
        raise HudError("Original-HUD-Baseline-Metadaten sind unvollständig")
    baseline = {entry["sheet"]:entry for entry in original_baselines}
    if set(baseline)!={n+".png" for n in ATLAS_NAMES}:
        raise HudError("Baseline unvollständig")
    expected_global=set()
    outputs=[]
    changed=[]
    total=0
    for name,atlas in zip(ATLAS_NAMES,atlas_entries):
        if (not isinstance(atlas,dict) or
            set(atlas)!={"dictionary","dictionary_sha256","sheet","sheet_width",
                         "sheet_height","directory","crops"}):
            raise HudError(f"Unbekannte oder beschädigte Atlasfelder: {name}")
        if atlas["dictionary"]!=name+".xaml" or atlas["directory"]!=name or atlas["sheet"]!=name+".png":
            raise HudError("SH1-Blattnamen weichen vom Original ab")
        if any(not isinstance(atlas[dim],int) or isinstance(atlas[dim],bool)
               or atlas[dim]<=0 for dim in ("sheet_width","sheet_height")):
            raise HudError(f"Originalatlas hat ungültige Abmessungen: {name}")
        if not isinstance(atlas["crops"],list) or not atlas["crops"]:
            raise HudError("Leerer SH1-Atlasindex")
        for entry in atlas["crops"]:
            if (not isinstance(entry,dict)
                or set(entry)!={"key","file","x","y","width","height","baseline_pixels_sha256"}
                or not isinstance(entry["key"],str)):
                raise HudError(f"Beschädigter HUD-Ausschnittindex in {name}")
        xaml=source/"baseline"/(name+".xaml")
        png=source/"baseline"/(name+".png")
        directory=source/name
        for p in (xaml,png,directory):
            if p.is_symlink() or not p.exists() or not p.resolve().is_relative_to(source):
                raise HudError(f"Fehlende oder verlinkte Quelle: {p}")
        if digest_file(xaml)!=atlas["dictionary_sha256"] or digest_file(xaml)!=baseline[name+".png"]["dictionary_sha256"]:
            raise HudError("XAML geaendert, Quelle nicht vertrauenswürdig: "+name)
        if digest_file(png)!=baseline[name+".png"]["sha256"]:
            raise HudError("Original-Basisatlas verändert: "+name)
        sheet_name,crops=read_atlas(xaml)
        if sheet_name!=name+".png":
            raise HudError(f"XAML referenziert nicht {name}")
        _reject_overlaps(crops,name)
        by_key={c.key:c for c in crops}
        if set(by_key)!={x["key"] for x in atlas["crops"]} or len(crops)!=len(atlas["crops"]):
            raise HudError("Index lässt XAML-Bildelemente aus oder enthält Duplikate: "+name)
        listed=set()
        with Image.open(png) as opened:
            original=opened.convert("RGBA")
        if (atlas["sheet_width"],atlas["sheet_height"])!=original.size:
            raise HudError("Baseline-Atlasabmessungen falsch: "+name)
        updated=original.copy() if construct else None
        for entry in atlas["crops"]:
            if set(entry)!={"key","file","x","y","width","height","baseline_pixels_sha256"}:
                raise HudError("Fremder Bildeintrag: "+name)
            key=entry["key"]
            crop=by_key[key]
            if key in expected_global:
                raise HudError("Doppelter GUI-Key: "+key)
            expected_global.add(key)
            if entry["file"]!=crop.filename or (entry["x"],entry["y"],entry["width"],entry["height"])!=(crop.x,crop.y,crop.width,crop.height):
                raise HudError("Schlüssel/Position manipuliert: "+key)
            filename=flat(crop.filename,"Ausschnitt",".png")
            listed.add(filename)
            file=directory/filename
            if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(source):
                raise HudError("HUD-PNG fehlt oder ist verlinkt: "+key)
            orig_part=original.crop(crop.box)
            if entry["baseline_pixels_sha256"]!=pixel_digest(orig_part):
                raise HudError("Original-Pixelprüfung nicht bestanden: "+key)
            with Image.open(file) as fp:
                if fp.size!=(crop.width,crop.height):
                    raise HudError(f"{key}: {fp.size} statt {crop.width}x{crop.height}")
                user_img=fp.convert("RGBA")
            if user_img.tobytes()!=orig_part.tobytes():
                changed.append({"key":key,"atlas":name,"rect":[crop.x,crop.y,crop.width,crop.height],
                                "edited_sha256":pixel_digest(user_img)})
                if construct:updated.paste(user_img,(crop.x,crop.y))
            total+=1
        actual={p.name for p in directory.glob("*.png")}
        if actual!=listed:
            raise HudError(f"{name}: Fehlende oder fremde PNGs {list((listed ^ actual))[:8]}")
        if construct:outputs.append((name,updated))
    if meta.get("editable_images")!=total:
        raise HudError("Originalcount stimmt nicht: "+str((total,meta.get("editable_images"))))
    return {"checked":total,"changed":changed,"source_sha256":idx["texture_asset_sha256"]},outputs

def build_workspace(source: Path, destination: Path, replace: bool):
    destination=ensure_under(destination,"dist")
    require_disjoint_output(destination, locate(source))
    result,images=check_workspace(source,construct=True)
    stage=stage_for(destination,replace)
    try:
        sheets=[]
        for name,image in images:
            f=stage/(name+".png")
            image.save(f,"PNG")
            with Image.open(f) as saved:
                reread=saved.convert("RGBA")
            if reread.size!=image.size or reread.tobytes()!=image.tobytes():
                raise HudError("Rekonstruiertes Blatt stimmt nicht: "+name)
            sheets.append({"file":f.name,"size":[image.width,image.height],"sha256":digest_file(f)})
        manifest={"schema":SCHEMA+".build","source_globalgamemanagers_sha256":result["source_sha256"],
                  "validated_named_crops":result["checked"],"edited_crops":result["changed"],
                  "sheets":sheets,"purpose":"Stronghold 1 Unity UI texture replacements. Manual integration requires compatible Unity asset workflow; not installed."}
        (stage/"HINWEISE_ZUM_EINBAU.md").write_text(
           "# Geprüfter Stronghold-1-HUD-Atlasexport\n"
           "Die drei PNG-Atlanten haben originale Größe und unveränderte Spritepositionen. "
           "Zum Einfügen in die Spiele-Unity-Assets ist ein kompatibler Unity-Texture-Patcher "
           "mit korrekt passendem Spiel-Build nötig. Dieser Vorgang wird NICHT automatisch vorgenommen.\n"
           "Die Dateien sind NICHT kompatibel mit Crusaders 8192×8192 Atlas-Koordinaten.\n",
           encoding="utf-8")
        (stage/"sh1_hud_build_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        commit(stage,destination,replace)
        print("SH1-HUD-BUILD_OK",result["checked"],"geprueft",len(result["changed"]),"geändert",destination,flush=True)
    finally:
        if stage.exists():shutil.rmtree(stage)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    cmd=parser.add_subparsers(dest="action",required=True)
    e=cmd.add_parser("export",help="Stronghold 1 Original-HUD ins SpriteSuite-Arbeitsverzeichnis exportieren")
    e.add_argument("--source",required=True,help="Datei globalgamemanagers.assets aus der SH1DE-Installation")
    e.add_argument("--out",default=str(DEFAULT_WORK))
    e.add_argument("--replace",action="store_true")
    c=cmd.add_parser("check",help="Ausgeschnittene HUD-Dateien gegen lokale Originalbaselines prüfen")
    c.add_argument("--from",dest="source",default=str(DEFAULT_WORK))
    b=cmd.add_parser("build",help="Gepruefte SH1-HUD-Atlanten in dist neu erzeugen")
    b.add_argument("--from",dest="source",default=str(DEFAULT_WORK))
    b.add_argument("--out",default=str(DEFAULT_DIST))
    b.add_argument("--replace",action="store_true")
    a=parser.parse_args(argv)
    try:
        if a.action=="export":export_workspace(locate(a.source),locate(a.out),a.replace)
        elif a.action=="check":
            report,_=check_workspace(locate(a.source))
            print("SH1-HUD-CHECK_OK",report["checked"],"Bausteine;",len(report["changed"]),"bearbeitet",flush=True)
        else:build_workspace(locate(a.source),locate(a.out),a.replace)
        return 0
    except (HudError,UiAtlasError,ValueError,OSError,RuntimeError) as error:
        print("SH1-HUD-ABGELEHNT:",error,file=sys.stderr,flush=True)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
