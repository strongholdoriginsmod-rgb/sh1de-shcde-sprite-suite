"""Core release validators fail closed on synthetic incomplete artifacts.

Golden negative contracts: no real game/Unity/SE files and no mutation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from stronghold_europe_de.validation import validate_mod
from stronghold_europe_de.runtime_validation import validate_runtime_log
from stronghold_europe_de.profile_contract import profile_output_contract_checks


def all_failures(checks):
    return [c.name for c in checks if not c.ok]


def test_empty_mod_cannot_validate_or_create_game_data(tmp_path):
    root=tmp_path/"synthetic-mod"
    root.mkdir()
    checks=validate_mod(root,expected_profile_id="synthetic")
    failures=all_failures(checks)
    assert "mod.build_manifest" in failures
    assert "mod.info" in failures
    assert list(root.iterdir())==[]


def test_invalid_json_mod_never_reaches_success(tmp_path):
    root=tmp_path/"fake-package"
    root.mkdir()
    (root/"build-manifest.json").write_text("{broken json",encoding="utf8")
    (root/"info.json").write_text('{"Manifest":0}',encoding="utf8")
    before={p.name:p.read_bytes() for p in root.iterdir()}
    checks=validate_mod(root)
    assert "manifest.json_object" in all_failures(checks)
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before


def test_manifests_with_wrong_shapes_fail_not_crash(tmp_path):
    root=tmp_path/"synthetic-package"
    root.mkdir()
    (root/"build-manifest.json").write_text(json.dumps({
        "schema_version":1, "profile_id":"fake", "outputs":"not-a-list"
    }),encoding="utf8")
    (root/"info.json").write_text(json.dumps({
        "Manifest":0,"GUID":"fake.guid","Version":"0.0.1"
    }),encoding="utf8")
    checks=validate_mod(root)
    assert any(not c.ok for c in checks)
    assert "manifest.input_shape" in all_failures(checks)


def test_runtime_log_requires_both_files_and_remains_read_only(tmp_path):
    log=tmp_path/"Game.log"
    manifest=tmp_path/"install.json"
    checks=validate_runtime_log(log,manifest)
    assert {"runtime.log_exists","runtime.install_manifest_exists"} <= set(all_failures(checks))
    log.write_text("synthetic log",encoding="utf8")
    manifest.write_bytes(b"{not-json")
    before=(log.read_bytes(),manifest.read_bytes())
    checks=validate_runtime_log(log,manifest)
    assert "runtime.install_manifest_schema" in all_failures(checks)
    assert (log.read_bytes(),manifest.read_bytes())==before


def test_external_profile_contract_never_approves_unexplained_build(tmp_path):
    package=tmp_path/"empty-mod"
    package.mkdir()
    expected={"id":"synthetic-profile","gm_atlases":[]}
    manifest={"profile_id":"synthetic-profile","outputs":[]}
    results=profile_output_contract_checks(package,expected,manifest,{})
    assert isinstance(results,list)
    assert results
    assert any(not check.ok for check in results)
    assert list(package.iterdir())==[]
