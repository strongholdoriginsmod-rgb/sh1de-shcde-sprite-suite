"""Five-file build attestations, explicit activation and no game writes."""
from __future__ import annotations
import gzip,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import target_selection_guard as guard
import ziel_se211 as manager

CANON=guard.CANONICAL

def install_fake_build(directory:Path,salt:str):
    directory.mkdir(parents=True,exist_ok=True)
    files=[]
    for index,rel in enumerate(CANON):
        file=directory/rel
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_bytes(((salt+rel)*3).encode("utf-8"))
        files.append(dict(relative_path=rel,size=file.stat().st_size,
                          sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    return files

@pytest.fixture
def context(tmp_path,monkeypatch):
    cfg=tmp_path/"config"
    cfg.mkdir()
    mapping=tmp_path/"work"/"mapping"/"proposals.json.gz"
    mapping.parent.mkdir(parents=True)
    with gzip.open(mapping,"wt",encoding="utf-8") as io:
        json.dump({"source_build_id":"sh1-exact","sprites":[],
                   "target_build_id":"shc280"},io)
    qa=tmp_path/"mock-crusader-280"
    qa_files=install_fake_build(qa/guard.DATA,"280")
    other=tmp_path/"mock-crusader-27"
    install_fake_build(other/guard.DATA,"27")
    src=tmp_path/"SH1"/"Stronghold 1 Definitive Edition_Data"
    src_files=install_fake_build(src,"SH1")
    pins={"target_builds":[{"id":"shc280","files":qa_files}],
          "source_builds":[{"id":"sh1-exact","files":src_files}]}
    (cfg/"supported-builds.json").write_text(json.dumps(pins),encoding="utf-8")
    monkeypatch.setattr(manager,"PROJECT_ROOT",tmp_path)
    monkeypatch.setattr(manager,"ZIELE",cfg/"ziele.json")
    monkeypatch.setattr(manager,"CONFIG",cfg/"installations.local.toml")
    yield tmp_path,qa,other,src

def test_registry_never_autoselects_and_fails_wrong_mapping_version(context):
    root,qa,other,source=context
    assert manager.targets()["aktiv"] is None
    assert manager.targets()["ziele"]=={}
    with pytest.raises(SystemExit,match="nicht eingetragen"):
        manager.cmd_hinzufuegen(SimpleNamespace(name="old27",spiel=str(other),anzeige=None))
    assert not manager.ZIELE.exists()
    assert not manager.CONFIG.exists()
    assert guard.verify_target(qa,root/"config"/"supported-builds.json",
                               root/"work"/"mapping"/"proposals.json.gz").files_checked==5

def test_register_then_activate_requires_source_and_explicit_choice(context):
    root,qa,other,source=context
    info=SimpleNamespace(name="qa280",spiel=str(qa),anzeige="Testspiel 2.80")
    before={rel:(qa/guard.DATA/rel).read_bytes() for rel in CANON}
    assert manager.cmd_hinzufuegen(info)==0
    registered=manager.targets()
    assert registered["aktiv"] is None
    assert registered["ziele"]["qa280"]["build_id"]=="shc280"
    with pytest.raises(SystemExit,match="source-data"):
        manager.cmd_aktivieren(SimpleNamespace(name="qa280",source_data=None))
    assert not manager.CONFIG.exists()
    assert manager.cmd_aktivieren(SimpleNamespace(
        name="qa280",source_data=str(source)))==0
    assert manager.targets()["aktiv"]=="qa280"
    assert guard.verify_active(root=root)[0]=="qa280"
    assert "allow_unknown_builds = false" in manager.CONFIG.read_text()
    for rel in CANON:assert (qa/guard.DATA/rel).read_bytes()==before[rel]
    assert not (qa/"_suite-sicherungen").exists()

def test_mutated_target_prevents_activation_and_installation(context):
    root,qa,other,source=context
    manager.cmd_hinzufuegen(SimpleNamespace(name="qa280",spiel=str(qa),anzeige=None))
    # Same file length, DIFFERENT HASH: size checks alone must not approve.
    changed=qa/guard.DATA/"Managed/Assembly-CSharp.dll"
    before=changed.read_bytes()
    changed.write_bytes(b"Z"+before[1:])
    saved=manager.ZIELE.read_bytes()
    with pytest.raises(SystemExit,match="SHA-256"):
        manager.cmd_aktivieren(SimpleNamespace(name="qa280",source_data=str(source)))
    assert not manager.CONFIG.exists()
    assert manager.ZIELE.read_bytes()==saved
    with pytest.raises(guard.TargetSelectionError):
        manager.safe_target("qa280")
    assert not (qa/"_suite-sicherungen").exists()

def test_unknown_mod_paths_and_unselected_target_are_denied(context):
    root,qa,other,source=context
    manager.cmd_hinzufuegen(SimpleNamespace(name="qa280",spiel=str(qa),anzeige=None))
    fake=SimpleNamespace(name="qa280",quelle=str(root),ordner="../bad")
    with pytest.raises(SystemExit,match="aktives Installationsziel"):
        manager.cmd_mod_installieren(fake)
    assert not (qa/"BepInEx").exists()
