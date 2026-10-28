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

def test_unknown_game_build_can_be_registered_but_requires_matching_map(context):
    root,qa,other,source=context
    assert manager.targets()["aktiv"] is None
    assert manager.targets()["ziele"]=={}
    # A previously unknown game build is never denied during registration.
    assert manager.cmd_hinzufuegen(
        SimpleNamespace(name="old27",spiel=str(other),anzeige=None)) == 0
    assert manager.targets()["aktiv"] is None
    unknown=manager.targets()["ziele"]["old27"]["build_id"]
    assert unknown.startswith("installed-target-")
    with pytest.raises(SystemExit,match="Mapping belongs"):
        manager.cmd_aktivieren(SimpleNamespace(
            name="old27",source_data=str(source)))
    assert not manager.CONFIG.exists()
    assert guard.verify_target(qa,root/"config"/"supported-builds.json",
                               root/"work"/"mapping"/"proposals.json.gz").files_checked==5


def test_generated_unknown_mapping_can_be_activated_without_any_version_pin(context):
    root,qa,other,source=context
    original=other/guard.DATA/"Managed/Assembly-CSharp.dll"
    original_source=source/"Managed/Assembly-CSharp.dll"
    source_before=original_source.read_bytes()
    # Unknown SH1DE edition is also accepted as a read-only source.
    original_source.write_bytes(b"newer SH1DE binary with different SHA")
    att=guard.inspect_target(other,root/"config"/"supported-builds.json")
    with gzip.open(root/"work/mapping/proposals.json.gz","wt",encoding="utf8") as writer:
        json.dump({"sprites":[],"target_build_id":att.build_id},writer)
    assert manager.cmd_hinzufuegen(
        SimpleNamespace(name="newgame",spiel=str(other),anzeige="New SHCDE"))==0
    assert manager.cmd_aktivieren(SimpleNamespace(
        name="newgame",source_data=str(source)))==0
    assert guard.verify_active(root=root)[0]=="newgame"
    assert "allow_unknown_builds = true" in manager.CONFIG.read_text()
    assert original.read_bytes()==((("27"+"Managed/Assembly-CSharp.dll")*3).encode("utf8"))
    assert original_source.read_bytes()!=source_before



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
    assert "allow_unknown_builds = true" in manager.CONFIG.read_text()
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
    with pytest.raises(SystemExit,match="Mapping belongs"):
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


def test_unknown_target_identity_matches_normal_sprite_suite_fingerprint(context):
    from stronghold_europe_de.config import Installation
    from stronghold_europe_de.fingerprint import fingerprint_installation
    from stronghold_europe_de.builds import installation_build_id

    root, qa, unknown, source = context
    game_data = unknown / guard.DATA
    info = guard.inspect_target(unknown, root/"config"/"supported-builds.json")
    standard = fingerprint_installation(Installation("Unknown SHCDE", game_data))
    assert info.build_id == installation_build_id("target", standard)
    assert info.files_checked == len(guard.CANONICAL)
    assert info.game_dir == unknown.resolve()
    # Unknown content is valid input; another game's mapping is still invalid.
    with pytest.raises(guard.TargetSelectionError, match="Mapping belongs"):
        guard.verify_target(unknown, root/"config"/"supported-builds.json",
                            root/"work/mapping/proposals.json.gz")
