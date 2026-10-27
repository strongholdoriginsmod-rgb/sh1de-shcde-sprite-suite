"""The Suite build chain cannot report a failed validator as success."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def workflow(tmp_path,monkeypatch):
    # Loading the standalone tool by importlib does not put its sibling
    # tools/ directory on sys.path as direct script execution would.
    monkeypatch.syspath_prepend(str(ROOT/"tools"))
    script=ROOT/"tools"/"suite_workflow.py"
    spec=importlib.util.spec_from_file_location("suite_workflow_contract_test",script)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module,"ROOT",tmp_path)
    profiles=tmp_path/"profiles"
    profiles.mkdir()
    (profiles/"test-profile.json").write_text(
        '{"id":"test-profile"}',encoding="utf-8"
    )
    return module


@pytest.mark.parametrize("strict", [False, True])
def test_build_steps_never_allow_soft_validate_failures(workflow,monkeypatch,strict):
    seen=[]
    def fake_runner(steps,soft,strict):
        seen.append((steps,soft,strict))
        return 7
    monkeypatch.setattr(workflow,"run_steps",fake_runner)
    import target_selection_guard as guard
    # The build guard is independently tested with real pinned source/target
    # files. This test isolates only strict vs lenient *validator exit codes*.
    monkeypatch.setattr(
        guard,"verify_active",
        lambda *,root:("test-target",SimpleNamespace(
            build_id="synthetic-version-attested",files_checked=5
        )),
    )
    flags=["--streng"] if strict else []
    code=workflow.main([*flags,"build","--profile-id","test-profile","--replace"])
    assert code==7
    assert len(seen)==1
    steps,soft,strict_mode=seen[0]
    assert soft==frozenset()
    assert strict_mode is strict
    assert steps[0][-3:]==[
        "--profile","profiles/test-profile.json","--replace"
    ]
    assert steps[-1][-2:]==["--profile-id","test-profile"]
    assert steps[-1][1:3]==["stronghold_europe_de","validate"]


def test_lenient_setup_doctor_retains_warning_behavior(workflow,monkeypatch):
    seen=[]
    monkeypatch.setattr(workflow,"run_steps",lambda steps,soft,strict:
                        seen.append((steps,soft,strict)) or 0)
    assert workflow.main(["check"])==0
    assert len(seen)==1
    assert seen[0][1]==frozenset({0,1})
    assert seen[0][2] is False


def test_real_run_steps_propagates_validator_error_in_lenient_mode(
    workflow,monkeypatch
):
    statuses=iter([0,9])
    observed=[]
    def fake_subprocess(args,**kwargs):
        observed.append((args,kwargs))
        return SimpleNamespace(returncode=next(statuses))
    monkeypatch.setattr(workflow.subprocess,"run",fake_subprocess)
    build=[["-m","stronghold_europe_de","build"],
           ["-m","stronghold_europe_de","validate"]]
    assert workflow.run_steps(build,soft=frozenset(),strict=False)==9
    assert len(observed)==2


def test_lenient_setup_failure_does_not_become_release_verification(
    workflow,monkeypatch
):
    failures=iter([4,5])
    monkeypatch.setattr(
        workflow.subprocess,"run",
        lambda *args,**kwargs:SimpleNamespace(returncode=next(failures)),
    )
    check=[["check"],["doctor"]]
    assert workflow.run_steps(check,soft=frozenset({0,1}),strict=False)==0
    # Intentional only for diagnostics, never selected by workflow.main(build).


def test_real_target_gate_blocks_unselected_build_before_any_step(
    workflow,monkeypatch
):
    """Never relax the exact game-version check to satisfy legacy QA."""
    monkeypatch.setattr(
        workflow,"run_steps",
        lambda *args,**kw:pytest.fail(
            "Build must not run without an explicitly pinned active target"
        ),
    )
    assert workflow.main([
        "build","--profile-id","test-profile","--replace"
    ])==27
    assert not (workflow.ROOT/"config"/"ziele.json").exists()
