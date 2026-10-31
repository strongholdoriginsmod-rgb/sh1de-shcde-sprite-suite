"""Release gate must fail closed on unverified CI, game, and second-PC data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile,ZIP_DEFLATED

import pytest
import suite_distribution_gate as gate

SHA="a"*40


def junit(path:Path,*,skips=0,failures=0):
    suite=ET.Element("testsuite")
    for idx in range(3):
        case=ET.SubElement(suite,"testcase",{"name":str(idx)})
        if idx<skips:ET.SubElement(case,"skipped")
        if idx>=3-failures:ET.SubElement(case,"failure")
    ET.ElementTree(suite).write(path,encoding="utf8")


def portable(path:Path,sha=SHA):
    doc={"source_commit":sha,"application_version":"2.0.0",
         "packager_windows_smoke_passed":True}
    with ZipFile(path,"w",ZIP_DEFLATED) as archive:
        archive.writestr("SpriteSuite/PORTABLE-BUILD.json",json.dumps(doc))


def test_release_blocked_without_manual_and_portable(tmp_path):
    tests=tmp_path/"tests.xml"
    junit(tests,skips=1)
    result=gate.evaluate(version="2.0.0",source_commit=SHA,junit=tests)
    assert not result["release_ready_for_human_review"]
    assert len(result["blockers"])>=3
    assert any("unverified" in item for item in result["blockers"])


def test_release_blocked_with_wrong_or_corrupt_portable(tmp_path):
    tests=tmp_path/"tests.xml"
    junit(tests)
    archive=tmp_path/"portable.zip"
    portable(archive,sha="b"*40)
    result=gate.evaluate(version="2.0.0",source_commit=SHA,
                         junit=tests,portable=archive)
    assert not result["release_ready_for_human_review"]
    assert any("source commit differs" in item for item in result["blockers"])
    archive.write_bytes(b"broken zip")
    result=gate.evaluate(version="2.0.0",source_commit=SHA,
                         junit=tests,portable=archive)
    assert any("not readable" in item for item in result["blockers"])


def test_release_gate_requires_actual_local_manual_proof_files(tmp_path):
    tests=tmp_path/"tests.xml"
    junit(tests)
    archive=tmp_path/"portable.zip"
    portable(archive)
    report=tmp_path/"manual.json"
    checks={}
    for name in gate.MANUAL_CHECKS:
        checks[name]={"passed":True,"file":name+".txt",
                      "evidence_sha256":hashlib.sha256(b"evidence").hexdigest()}
    report.write_text(json.dumps({"schema":gate.SCHEMA,
                                  "source_commit":SHA,"checks":checks}),encoding="utf8")
    result=gate.evaluate(version="2.0.0",source_commit=SHA,
                         junit=tests,portable=archive,manual_evidence=report)
    assert not result["release_ready_for_human_review"]
    evidence=tmp_path/"qa-evidence"
    evidence.mkdir()
    for name in gate.MANUAL_CHECKS:
        (evidence/(name+".txt")).write_bytes(b"evidence")
    result=gate.evaluate(version="2.0.0",source_commit=SHA,
                         junit=tests,portable=archive,manual_evidence=report)
    assert result["release_ready_for_human_review"]
    assert result["note"].startswith("This is not a published release")
    (evidence/(gate.MANUAL_CHECKS[0]+".txt")).write_bytes(b"tampered")
    result=gate.evaluate(version="2.0.0",source_commit=SHA,
                         junit=tests,portable=archive,manual_evidence=report)
    assert not result["release_ready_for_human_review"]


def test_invalid_git_commit_is_not_silently_accepted(tmp_path):
    path=tmp_path/"tests.xml"
    junit(path)
    with pytest.raises(ValueError):
        gate.evaluate(version="2.0.0",source_commit="short",junit=path)
