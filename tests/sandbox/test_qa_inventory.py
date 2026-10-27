"""Inventory prior QA tools *without* transplanting unsafe build scripts."""
from pathlib import Path
import json

import pytest
from stronghold_europe_de.qa_inventory import (
    InventoryError, CANDIDATES, inventory_legacy_tools, save_inventory,
)


def test_qa_inventory_reports_missing_identical_and_version_drift(tmp_path):
    current=tmp_path/"current"
    old=tmp_path/"old"
    for root in (current,old):
        (root/"tools").mkdir(parents=True)
        (root/"tests").mkdir()
    (old/"tools"/"ram_acceptance.py").write_text("VERSION = 1\n",encoding="utf-8")
    (current/"tools"/"ram_acceptance.py").write_text("VERSION = 1\n",encoding="utf-8")
    (old/"tools"/"full152_ingame_acceptance.py").write_text("VERSION = 2\n",encoding="utf-8")
    (current/"tools"/"full152_ingame_acceptance.py").write_text("VERSION = 3\n",encoding="utf-8")
    (old/"tools"/"runtime_install.py").write_text("DANGEROUS INSTALLER",encoding="utf-8")
    (old/"tests"/"test_foo.py").write_text("pass\n",encoding="utf-8")
    report=inventory_legacy_tools(old,current)
    rows={r["name"]:r for r in report["tools"]}
    assert rows["ram_acceptance.py"]["status"]=="bereits_identisch"
    assert rows["full152_ingame_acceptance.py"]["status"]=="abweichende_version"
    assert rows["runtime_install.py"]["status"]=="nur_im_altbestand"
    assert rows["shcdese_install.py"]["status"]=="nicht_gefunden"
    assert rows["runtime_install.py"]["risiko"]=="schreibend"
    assert report["legacy_test_module_count"]==1
    assert report["current_test_module_count"]==0
    before=(old/"tools"/"runtime_install.py").read_bytes()
    output=save_inventory(report,current)
    assert output.is_relative_to(current/"work"/"reports"/"qa-inventory")
    assert json.loads(output.read_text(encoding="utf-8"))==report
    assert save_inventory(report,current)==output
    assert (old/"tools"/"runtime_install.py").read_bytes()==before
    assert not list(output.parent.glob("*.tmp"))


def test_qa_inventory_rejects_self_scan_and_invalid_roots(tmp_path):
    current=tmp_path/"project"
    (current/"tools").mkdir(parents=True)
    with pytest.raises(InventoryError):
        inventory_legacy_tools(current,current)
    with pytest.raises(InventoryError):
        inventory_legacy_tools(tmp_path/"missing",current)
    with pytest.raises(InventoryError):
        save_inventory({"schema":"unexpected"},current)


def test_candidate_programs_are_review_only_never_executed():
    assert CANDIDATES
    assert all(r.file.endswith(".py") for r in CANDIDATES)
    assert "schreibend" in {r.risk for r in CANDIDATES}
    assert "versiongebunden" in {r.risk for r in CANDIDATES}
