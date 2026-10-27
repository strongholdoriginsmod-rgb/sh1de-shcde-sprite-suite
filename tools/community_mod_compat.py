"""Read-only SHCDE community-mod compatibility and install preflight.

Snapshot contracts are version-pinned from public maintainers, NOT automatic
permission to install, update or modify other plugins. A clean static scan
does not demonstrate joint in-game hook/ABI compatibility.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"config"/"shcde-community-compat-20261022.json"
PREREQS=ROOT/"config"/"runtime-prerequisites.json"
OWN_GUID="strongholdeuropede.private"
OWN_DIR="StrongholdEuropeDE"
SE_GUID="000shcdese"
BEP_DLL="BepInEx/core/BepInEx.dll"
SE_DLL="BepInEx/plugins/000shcdese/SHCDESE.dll"
_PROTECTED_DLLS=frozenset({
    "bepinex.dll","shcdese.dll","apishared.dll","nlua.dll",
    "redbird.core.dll","redbird.x64.dll","r3.dll","0harmony.dll",
    "monomod.runtimedetour.dll",
})
_VERSION=re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")

class CompatibilityError(ValueError):
    """Unsupported, conflicting or insufficiently proven SHCDE mod setup."""

def version(value):
    matched=_VERSION.match(str(value or ""))
    return (int(matched[1]),int(matched[2]),int(matched[3] or 0)) if matched else None

def digest(path):
    sha=hashlib.sha256()
    with path.open("rb") as input:
        for chunk in iter(lambda:input.read(4*1024*1024), b""):
            sha.update(chunk)
    return sha.hexdigest()

def load_json(path, limit=1_048_576):
    if not path.is_file() or path.is_symlink() or path.stat().st_size>limit:
        raise CompatibilityError(f"Manifest fehlt, ist verknüpft oder zu groß: {path}")
    try:
        result=json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(result,dict):
            raise ValueError("JSON root must be object")
    except (OSError,UnicodeError,ValueError) as exc:
        raise CompatibilityError(f"Manifest ungültig: {path}: {exc}") from exc
    return result


def read_runtime_attestation(path):
    """Read the packaged runtime BepInEx ID and SE ABI without executing DLLs."""
    if not path.is_file() or path.is_symlink() or path.stat().st_size>1_048_576:
        raise CompatibilityError(f"Runtime-Identitätsbeleg fehlt oder ist unsicher: {path}")
    try:
        lines=path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CompatibilityError(f"Runtime-Beleg nicht lesbar: {exc}") from exc
    if not lines or lines[0]!="stronghold-europe-audio-profile\t1":
        raise CompatibilityError("Unbekanntes Runtime/audio-profile.tsv-Format")
    wanted={"plugin_id","script_extender_version"}
    result={}
    for entry in lines[1:]:
        name,sep,value=entry.partition("\t")
        if name in wanted:
            if not sep or not value.strip() or name in result:
                raise CompatibilityError("Doppelte oder ungültige Runtime-Identitätsdaten")
            result[name]=value.strip()
    if set(result)!=wanted:
        raise CompatibilityError("Runtime-Plugin-ID bzw. Script-Extender-Version fehlt")
    return result


def check(game, candidate=None, *, project=ROOT):
    project=Path(project).resolve()
    game=Path(game).resolve()
    snapshot=load_json(project/"config"/"shcde-community-compat-20261022.json")
    pins=load_json(project/"config"/"runtime-prerequisites.json")
    issues=[]
    def add(level,code,details):
        issues.append(dict(severity=level,code=code,details=str(details)))

    plugins=game/"BepInEx"/"plugins"
    core=game/BEP_DLL
    registry={}
    if not plugins.is_dir():
        add("BLOCK","NO_PLUGIN_ROOT","BepInEx/plugins fehlt")
    else:
        for folder in sorted(plugins.iterdir()):
            if not folder.is_dir():
                continue
            if folder.is_symlink():
                add("BLOCK","SYMLINKED_PLUGIN",str(folder))
                continue
            info=folder/"info.json"
            if not info.exists():
                # Not all BepInEx plugins have info.json; do not claim
                # unknown DLL folders are compatible or delete them.
                # A BepInEx plugin can keep its DLL below a nested subfolder.
                # An unknown DLL without an explicit manifest is not a safe
                # basis for claiming hook coexistence with SpriteSuite.
                dlls=list(folder.rglob("*.dll"))
                if dlls:
                    add("REVIEW","PLUGIN_WITHOUT_MANIFEST",
                        f"{folder.name}: {len(dlls)} DLL(s) without info.json")
                continue
            try:
                obj=load_json(info)
            except CompatibilityError as exc:
                add("BLOCK","BROKEN_PLUGIN_MANIFEST",str(exc))
                continue
            guid=obj.get("GUID")
            if not isinstance(guid,str) or not guid.strip():
                add("BLOCK","MISSING_PLUGIN_ID",str(info))
                continue
            folded=guid.casefold()
            if folded in registry:
                add("BLOCK","DUPLICATE_PLUGIN_GUID",
                    f"{guid}: {registry[folded]['folder'].name} and {folder.name}")
            registry[folded]=dict(guid=guid,version=obj.get("Version"),
                                  folder=folder,manifest=obj)

    dependencies={row.get("id"):row for row in pins.get("files",[])
                  if isinstance(row,dict)}
    pinchecks=[]
    for identifier,relative in (("bepinex_core",BEP_DLL),("shcdese",SE_DLL)):
        path=game/relative
        pin=dependencies.get(identifier)
        if pin is None:
            add("BLOCK","MISSING_RUNTIME_PIN",identifier)
            continue
        if not path.is_file() or path.is_symlink():
            add("BLOCK","MISSING_RUNTIME_FILE",relative)
            continue
        try:
            matches=(path.stat().st_size==pin.get("size") and
                     digest(path)==pin.get("sha256"))
        except OSError as exc:
            add("BLOCK","UNREADABLE_RUNTIME",f"{relative}: {exc}")
            continue
        pinchecks.append(dict(id=identifier,relative_path=relative,
                              matches=matches,expected_assembly=pin.get("assembly_version")))
        if not matches:
            add("BLOCK","RUNTIME_ABI_PIN_MISMATCH",
                f"{relative} differs from SpriteSuite's tested {pin.get('assembly_version')}; "
                "a new Script-Extender/BepInEx build requires independent ABI/asset tests")

    extender=registry.get(SE_GUID)
    extender_version=extender["version"] if extender else None
    if extender is None:
        add("BLOCK","SCRIPT_EXTENDER_NOT_REGISTERED",SE_GUID)
    elif version(extender_version) is None:
        add("BLOCK","INVALID_SCRIPT_EXTENDER_VERSION",extender_version)

    api_guid=snapshot["plugin_contracts"]["api_shared_guid"]
    api=registry.get(api_guid.casefold())
    reference_api=next(row for row in snapshot["official_releases"]
                       if row["id"]=="api_shared")
    if api is None:
        add("REVIEW","API_SHARED_NOT_INSTALLED",
            f"APIShared {reference_api['version']} is not installed; no APIShared co-run verified")
    else:
        if api["folder"].name!=api_guid:
            add("BLOCK","API_SHARED_NONCANONICAL_FOLDER",
                f"Expected BepInEx/plugins/{api_guid}, found {api['folder'].name}")
        minimum=api["manifest"].get("MinimumScriptExtenderVersion")
        if minimum is None and api["version"]==reference_api["version"]:
            minimum=reference_api["minimum_script_extender_version"]
        if minimum:
            if version(minimum) is None or version(extender_version) is None:
                add("BLOCK","API_SHARED_VERSION_UNVERIFIED",f"requires {minimum}")
            elif version(extender_version)<version(minimum):
                add("BLOCK","API_SHARED_MIN_SE",
                    f"APIShared {api['version']} requires SE >= {minimum}; installed SE {extender_version}")
        else:
            add("REVIEW","API_SHARED_MIN_UNPROVEN",
                f"Installed APIShared {api['version']} has no minimum SE version")

    latest_se=next(row for row in snapshot["official_releases"]
                   if row["id"]=="rawra_script_extender")
    if version(extender_version) and version(extender_version)<version(
        reference_api["minimum_script_extender_version"]
    ):
        add("REVIEW","LATEST_API_SHARED_CANNOT_RUN",
            f"Installed SE {extender_version}; current APIShared {reference_api['version']} "
            f"requires >= {reference_api['minimum_script_extender_version']}, "
            f"Rawra published {latest_se['version']}")

    for guid,entry in registry.items():
        if guid not in {SE_GUID,OWN_GUID}:
            add("REVIEW","FOREIGN_PLUGIN_IN_GAME_UNTESTED",
                f"{entry['guid']} {entry['version']} requires a joint in-game hook and save QA")

    for guid,label in (("fixes","Rawra Fixes"),
                       ("CrusaderDETweaker","Ensrick Tweaker"),
                       ("APIShared_Serp","APIShared")):
        if guid.casefold() in registry:
            add("REVIEW","IN_GAME_HOOK_INTEROPERABILITY_UNTESTED",
                f"Co-run with {label} not established by a static scan")
    if any(k in registry for k in ("serpsmods","serpsmodshost")):
        add("REVIEW","SERPS_MODPACK_IN_GAME_UNTESTED",
            "Serps modpack loaded; native hooks/AI/multiplayer need an in-game comparison")

    candidate_summary=None
    if candidate is not None:
        candidate=Path(candidate).resolve()
        candidate_summary=dict(path=str(candidate),guid=None,
                               runtime_guid=None,runtime_se_version=None,dlls=[])
        if candidate.name!=OWN_DIR or not candidate.is_dir():
            add("BLOCK","WRONG_CANDIDATE_DIR",
                f"Expected the StrongholdEuropeDE plugin directory: {candidate}")
        else:
            try:
                meta=load_json(candidate/"info.json")
                candidate_summary["guid"]=meta.get("GUID")
                if meta.get("GUID")!=OWN_GUID:
                    add("BLOCK","WRONG_CANDIDATE_GUID",
                        f"Expected {OWN_GUID}, got {meta.get('GUID')}")
            except CompatibilityError as exc:
                add("BLOCK","INVALID_CANDIDATE_MANIFEST",str(exc))
            try:
                runtime=read_runtime_attestation(candidate/"Runtime"/"audio-profile.tsv")
            except CompatibilityError as exc:
                add("BLOCK","INVALID_PACKAGE_RUNTIME_ATTESTATION",str(exc))
            else:
                candidate_summary["runtime_guid"]=runtime["plugin_id"]
                candidate_summary["runtime_se_version"]=runtime["script_extender_version"]
                expected_guid=snapshot["plugin_contracts"]["suite_runtime_plugin_guid"]
                if runtime["plugin_id"]!=expected_guid:
                    add("BLOCK","PACKAGE_RUNTIME_GUID_MISMATCH",
                        f"Expected BepInEx Runtime GUID {expected_guid}, got {runtime['plugin_id']}")
                required_se=pins.get("script_extender_version")
                if (version(runtime["script_extender_version"]) is None or
                        version(required_se) is None or
                        version(runtime["script_extender_version"])!=version(required_se)):
                    add("BLOCK","PACKAGE_SE_ATTESTATION_MISMATCH",
                        f"Package runtime built for SE {runtime['script_extender_version']}, "
                        f"SpriteSuite pins SE {required_se}; the shipped artifact is not a "
                        "verified build from the current source contract")
                if (version(extender_version) is not None and
                        version(runtime["script_extender_version"])!=version(extender_version)):
                    add("BLOCK","PACKAGE_INSTALLED_SE_MISMATCH",
                        f"Package says SE {runtime['script_extender_version']}, "
                        f"installed SE is {extender_version}")
            for entry in candidate.rglob("*"):
                if entry.is_symlink():
                    add("BLOCK","SYMLINK_IN_CANDIDATE",str(entry))
                elif entry.is_file() and entry.suffix.casefold()==".dll":
                    candidate_summary["dlls"].append(str(entry.relative_to(candidate)))
                    if entry.name.casefold() in _PROTECTED_DLLS:
                        add("BLOCK","BUNDLED_SHARED_DLL",
                            f"{entry.name} must stay with its authoritative provider")
                    elif entry.name.casefold()!="strongholdeuropede.runtime.dll":
                        add("BLOCK","UNKNOWN_PLUGIN_DLL",
                            f"{entry.name} is not owned by SpriteSuite")
            if not candidate_summary["dlls"]:
                add("BLOCK","MISSING_PRIVATE_RUNTIME","StrongholdEuropeDE.Runtime.dll missing")
            existing=registry.get(OWN_GUID)
            if existing and existing["folder"].name!=OWN_DIR:
                add("BLOCK","PRIVATE_GUID_ALREADY_OWNED",
                    f"StrongholdEuropeDE GUID already registered by {existing['folder']}")
            destination=plugins/OWN_DIR
            if destination.is_dir() and (destination/"info.json").is_file():
                try:
                    old=load_json(destination/"info.json")
                    if old.get("GUID")!=OWN_GUID:
                        add("BLOCK","FOREIGN_DESTINATION_OWNERSHIP",
                            f"Cannot replace {destination}: GUID {old.get('GUID')}")
                except CompatibilityError as exc:
                    add("BLOCK","FOREIGN_DESTINATION_UNREADABLE",str(exc))

    status=("BLOCKED" if any(x["severity"]=="BLOCK" for x in issues)
            else "REVIEW_REQUIRED")
    return dict(
        schema="sprite-suite.community-compat-audit.v1",
        checked_utc=datetime.now(timezone.utc).isoformat(),
        game_root=str(game),snapshot_checked_on=snapshot["checked_on"],
        status=status,source_contracts=CONTRACT.name,
        installed_script_extender_version=extender_version,
        installed_plugins=[dict(guid=row["guid"],version=row["version"],
                                folder=row["folder"].name)
                           for row in sorted(registry.values(),key=lambda r:r["folder"].name)],
        tested_runtime_pins=pinchecks,candidate=candidate_summary,
        issues=issues,
        limitations=[
            "No game launched and no native hook compatibility demonstrated",
            "No APIShared/Rawra/Tweaker/Serps in-game interaction test",
            "Latest upstream version cannot replace SpriteSuite ABI pins automatically",
            "AI-Toolkit classic .aiv is not Serpens DE .aivjson or .baiv",
            "Serpens MapParser reads .map/.trail, not .sav/.msv",
        ],
        writes_game_files=False,
    )

def require_safe_to_install(game,candidate,*,project=ROOT):
    result=check(game,candidate,project=project)
    problems=[x for x in result["issues"] if x["severity"]=="BLOCK"]
    risky=[x for x in result["issues"] if x["code"] in {
           "IN_GAME_HOOK_INTEROPERABILITY_UNTESTED",
           "FOREIGN_PLUGIN_IN_GAME_UNTESTED",
           "PLUGIN_WITHOUT_MANIFEST",
           "API_SHARED_MIN_UNPROVEN",
           "SERPS_MODPACK_IN_GAME_UNTESTED"}]
    if problems or risky:
        top=(problems+risky)[:4]
        raise CompatibilityError(
            "Community-Kompatibilität nicht freigegeben: "+
            "; ".join(f"{x['code']}: {x['details']}" for x in top))
    return result

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game-root",type=Path,required=True,
                        help="Existing local game root (read-only audit)")
    parser.add_argument("--candidate",type=Path,
                        help="Optional StrongholdEuropeDE output directory")
    parser.add_argument("--project",type=Path,default=ROOT)
    parser.add_argument("--json-out",type=Path)
    args=parser.parse_args(argv)
    result=check(args.game_root,args.candidate,project=args.project)
    print(json.dumps(result,indent=2,ensure_ascii=False))
    if args.json_out:
        base=(args.project/"work").resolve()
        destination=args.json_out.resolve()
        if not destination.is_relative_to(base) or destination.suffix.lower()!=".json":
            raise SystemExit("Report writes permitted under work/ only")
        destination.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=".community-",suffix=".tmp",
                                dir=destination.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as stream:
                json.dump(result,stream,ensure_ascii=False,indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp,destination)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    return 2 if result["status"]=="BLOCKED" else 0

if __name__=="__main__":
    raise SystemExit(main())
