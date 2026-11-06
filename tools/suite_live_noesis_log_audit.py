"""Audit a *real* SHCDESE session without claiming native rendering from offline XML.

Read-only by design. A mod merely being indexed is not evidence its XAML
patch was requested. A patch being invoked is not evidence its pixels rendered.
For explicit QA usage, not automatically run at suite startup.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from xml.etree import ElementTree as ET

_MAX_LOG=45*1024*1024
_MAX_PATCH=4*1024*1024
_GUID=re.compile(r"[a-zA-Z][A-Za-z0-9_-]{2,79}\Z")
_XAML=re.compile(r"[a-zA-Z][A-Za-z0-9_-]{0,90}\.xaml\Z")


def sha(path:Path) -> str:
    h=sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda:stream.read(4*1024*1024),b""):
            h.update(part)
    return h.hexdigest()


def read_patch(path:Path) -> tuple[str,str]:
    """Validate a static XAML patch without resolving/expanding DTDs."""
    path=Path(path)
    if (path.is_symlink() or not path.is_file()
            or path.stat().st_size>_MAX_PATCH):
        raise ValueError("Missing, linked or oversized Noesis patch")
    raw=path.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("External XML entities and DTDs are not permitted")
    try:
        root=ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("Malformed XAML patch") from exc
    if root.tag!="Patch":
        raise ValueError("Not a Noesis Patch document")
    operations=root.findall("Operation")
    if not operations or any(e.get("Type")!="Add" or not e.get("XPath")
                             for e in operations):
        raise ValueError("No valid Add/XPath operation")
    return operations[0].get("XPath",""),sha(path)


def analyze(*,game_root:Path,guid:str,document:str,
            log_file:Path|None=None,patch:Path|None=None,
            expected_source_hash:str|None=None) -> dict:
    if not _GUID.fullmatch(guid) or not _XAML.fullmatch(document):
        raise ValueError("Invalid mod GUID or XAML document")
    game=Path(game_root)
    if not game.is_dir() or game.is_symlink():
        raise ValueError("QA game root missing or linked")
    if game.name.casefold()=="stronghold crusader definitive edition" and (
        str(game).lower().startswith("c:\\program files") or
        str(game).lower().startswith("c:/program files")):
        raise ValueError("Do not use production Steam installation as live QA target")
    if not (game/".sprite-suite-qa-copy.marker").is_file():
        raise ValueError("Explicit QA copy marker is required")
    installed=game/"BepInEx"/"plugins"/guid
    if installed.is_symlink() or not installed.is_dir():
        raise ValueError("QA mod directory not installed")
    info=installed/"info.json"
    if not info.is_file() or info.is_symlink():
        raise ValueError("Missing mod info.json")
    manifest=json.loads(info.read_text(encoding="utf-8"))
    if manifest.get("GUID")!=guid or manifest.get("Manifest")!=0:
        raise ValueError("Installed mod is not a static asset mod")
    if patch is None:patch=installed/"Patches"/"Assets"/"GUI"/"XAML"/document
    else:
        patch=Path(patch)
        if not patch.resolve().is_relative_to(installed.resolve()):
            raise ValueError("Patch must be under installed QA mod")
    xpath,pin=read_patch(patch)
    rel=f"Assets/GUI/XAML/{document}"
    log=Path(log_file) if log_file else game/"BepInEx"/"LogOutput.log"
    if log.is_symlink() or not log.is_file() or log.stat().st_size>_MAX_LOG:
        raise ValueError("Missing, linked or oversized BepInEx log")
    raw=log.read_text(encoding="utf-8",errors="replace")
    escguid=re.escape(guid)
    escrel=re.escape(rel)
    indexed=bool(re.search(r"Indexed\s+\d+\s+files\s+for\s+\["+escguid+r"\]",raw))
    registered=bool(re.search(r"Loading Asset Mod:\s+\[[^\]\r\n]*[/\\]"+escguid+r"\]",raw))
    discovered=bool(re.search(r"Found patch for\s+\["+escrel+r"\]\s+in mod\s+\["+escguid+r"\]",raw))
    applied=bool(re.search(r"Applying\s+\d+\s+patch files to\s+"+escrel+r"\b",raw))
    reason=("No mod registration found in the supplied live session log" if not(indexed and registered)
         else "Mod was indexed, but the target XAML was not requested by the runtime" if not discovered
         else "Target was requested but no runtime patch application logged" if not applied
         else "Runtime patch invocation was logged; only an actual screenshot can attest visible pixels")
    status=("not_registered" if not(indexed and registered)
       else "registered_not_requested" if not discovered
       else "requested_not_applied" if not applied
       else "patch_invoked_visual_unverified")
    output={
      "schema":"sprite-suite.real-noesis-log-audit.v1",
      "qa_game_root":str(game),"game_executable":str(game/"Stronghold Crusader Definitive Edition.exe"),
      "mod_guid":guid,"target_document":document,"target_xpath":xpath,
      "installed_patch_sha256":pin,"log_path":str(log),"log_sha256":sha(log),
      "mod_registered":registered,"asset_files_indexed":indexed,
      "target_xaml_requested_for_this_mod":discovered,
      "runtime_patch_call_seen":applied,
      "status":status,"reason":reason,
      "native_rendered_pixels_attested":False,
      "native_game_abi_approved":False,
      "game_originals_modified":False
    }
    if expected_source_hash:
        if not re.fullmatch(r"[a-fA-F0-9]{64}",expected_source_hash):
            raise ValueError("Invalid expected reference XAML SHA")
        source=game/"BepInEx"/"plugins"/"000shcdese"/"Override"/"Assets"/"GUI"/"XAML"/document
        if not source.is_file():
            output["game_xaml_source_matched"]=False
        else:
            output["game_xaml_source_matched"]=sha(source)==expected_source_hash.lower()
            output["game_xaml_sha256"]=sha(source)
    return output


def main(argv=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--qa-game",type=Path,required=True)
    p.add_argument("--mod-guid",required=True)
    p.add_argument("--document",required=True)
    p.add_argument("--log",type=Path)
    p.add_argument("--expected-xaml-sha")
    p.add_argument("--out",type=Path)
    args=p.parse_args(argv)
    try:
        report=analyze(game_root=args.qa_game,guid=args.mod_guid,
                       document=args.document,log_file=args.log,
                       expected_source_hash=args.expected_xaml_sha)
        if args.out:
            dest=Path(args.out)
            if dest.exists() or dest.is_symlink():
                raise ValueError("Report path exists; refusing overwrite")
            # Do not create QA report in original game install directory.
            if dest.resolve(strict=False).is_relative_to(args.qa_game.resolve()):
                raise ValueError("QA evidence must be stored outside game root")
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        print(json.dumps(report,indent=2,ensure_ascii=False))
        return 0 if report["runtime_patch_call_seen"] else 2
    except (ValueError,OSError,TypeError,json.JSONDecodeError) as exc:
        print("LIVE_NOESIS_QA_BLOCKED: "+str(exc),file=sys.stderr)
        return 3


if __name__=="__main__":
    raise SystemExit(main())
