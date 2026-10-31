"""Independent release gate: missing manual/in-game evidence always blocks.

The gate checks machine-readable evidence; it cannot itself prove that a
screenshot shows the correct game. Approval is always a human decision.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from zipfile import ZipFile,BadZipFile
from xml.etree import ElementTree as ET


SCHEMA="sprite-suite.release-acceptance.v1"
MANUAL_CHECKS=(
    "independent_windows_pc",
    "real_ingame_hud",
    "real_mod_install_rollback",
    "visual_goldens",
    "screenreader_and_200dpi",
)
HASH=re.compile(r"[a-f0-9]{64}\Z")
SOURCE_SHA=re.compile(r"[a-f0-9]{40}\Z")


def inspect_junit(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size>30*1024*1024:
        raise ValueError("JUnit test evidence missing or oversized")
    root=ET.parse(path)
    cases=root.findall(".//testcase")
    if not cases:
        raise ValueError("JUnit contains no test cases")
    failed=sum(c.find("failure") is not None or c.find("error") is not None for c in cases)
    skipped=sum(c.find("skipped") is not None for c in cases)
    return {"tests":len(cases),"failed":failed,"skipped":skipped}


def inspect_manual_evidence(path: Path | None,source_commit: str) -> tuple[bool,list[str]]:
    if path is None or not path.is_file():
        return False,["no independent manual QA evidence"]
    if path.is_symlink() or path.stat().st_size>512*1024:
        return False,["manual evidence is linked or oversized"]
    try:
        obj=json.loads(path.read_text("utf8"))
    except (ValueError,UnicodeError,OSError):
        return False,["manual evidence is unreadable"]
    if not isinstance(obj,dict) or obj.get("schema")!=SCHEMA or obj.get("source_commit")!=source_commit:
        return False,["manual evidence schema or source commit mismatch"]
    checks=obj.get("checks")
    if not isinstance(checks,dict):
        return False,["manual QA checks missing"]
    blockers=[]
    for name in MANUAL_CHECKS:
        record=checks.get(name)
        if (not isinstance(record,dict) or record.get("passed") is not True
                or not isinstance(record.get("evidence_sha256"),str)
                or not HASH.fullmatch(record["evidence_sha256"]) or
                not isinstance(record.get("file"),str) or
                not record["file"] or Path(record["file"]).name!=record["file"]):
            blockers.append(f"manual QA required: {name}")
            continue
        evidence=path.parent/"qa-evidence"/record["file"]
        if (evidence.is_symlink() or not evidence.is_file()
                or evidence.stat().st_size>20*1024*1024 or
                sha256(evidence.read_bytes()).hexdigest()!=record["evidence_sha256"]):
            blockers.append(f"manual QA evidence file missing or changed: {name}")
    return not blockers,blockers


def inspect_portable(path: Path | None, source_commit: str, version: str) -> list[str]:
    if path is None or not path.is_file():
        return ["no published portable ZIP has been verified"]
    try:
        with ZipFile(path) as archive:
            if archive.testzip() is not None:
                return ["portable ZIP has a CRC error"]
            doc=json.loads(archive.read("SpriteSuite/PORTABLE-BUILD.json").decode("utf8"))
            if doc.get("source_commit")!=source_commit:
                return ["portable ZIP source commit differs"]
            if doc.get("application_version")!=version:
                return ["portable ZIP version differs"]
            if doc.get("packager_windows_smoke_passed") is not True:
                return ["portable packaging smoke is not proven"]
    except (BadZipFile,KeyError,OSError,UnicodeError,ValueError):
        return ["portable ZIP metadata is not readable"]
    return []


def evaluate(*,version: str,source_commit: str,junit: Path,
             portable: Path | None=None,manual_evidence: Path | None=None)->dict:
    if not SOURCE_SHA.fullmatch(source_commit):
        raise ValueError("Expected exact 40-character Git source commit")
    tests=inspect_junit(junit)
    blockers=[]
    if tests["failed"]:
        blockers.append(f"{tests['failed']} automated test(s) failed")
    if tests["skipped"]:
        blockers.append(f"{tests['skipped']} automated tests remain unverified")
    blockers.extend(inspect_portable(portable,source_commit,version))
    manual_ok,manual_blockers=inspect_manual_evidence(manual_evidence,source_commit)
    blockers.extend(manual_blockers)
    return {"schema":"sprite-suite.release-gate.v1","source_commit":source_commit,
            "version":version,"automated":tests,"manual_evidence_present":manual_ok,
            "release_ready_for_human_review":not blockers,"blockers":blockers,
            "note":"This is not a published release or independent visual proof"}


def main(argv: list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version",required=True)
    parser.add_argument("--source-commit",required=True)
    parser.add_argument("--junit",required=True,type=Path)
    parser.add_argument("--portable",type=Path)
    parser.add_argument("--manual-evidence",type=Path)
    args=parser.parse_args(argv)
    try:
        result=evaluate(version=args.version,source_commit=args.source_commit,
                        junit=args.junit,portable=args.portable,
                        manual_evidence=args.manual_evidence)
    except (OSError,ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["release_ready_for_human_review"] else 3


if __name__=="__main__":
    raise SystemExit(main())
