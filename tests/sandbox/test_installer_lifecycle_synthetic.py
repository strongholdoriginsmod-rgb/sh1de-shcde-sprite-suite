"""Full synthetic installer lifecycle; never points at a real game installation."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

import pytest
from stronghold_europe_de import installer
from stronghold_europe_de.config import BuilderConfig,Installation,OutputPaths,Policy


@pytest.fixture
def fake_game(tmp_path,monkeypatch):
    root=tmp_path/"fictional-project"
    root.mkdir()
    game=tmp_path/"simulated-game-not-installed"
    plugins=game/"BepInEx"/"plugins"
    plugins.mkdir(parents=True)
    (game/installer._TARGET_GAME_EXECUTABLE).write_bytes(b"not an executable")
    source_data=tmp_path/"SH1_data_fake"
    target_data=tmp_path/"SHCDE_data_fake"
    source_data.mkdir()
    target_data.mkdir()
    output=OutputPaths(work_dir=root/"work",
                       cache_dir=root/"cache",
                       state_dir=root/"state",
                       dist_dir=root/"dist",
                       mod_folder_name="test-only-mod")
    config=BuilderConfig(project_root=root,
        source=Installation("fake SH1",source_data),
        target=Installation("fake SHC",target_data,game),
        output=output,
        policy=Policy(private_local_only=True,
                      allow_game_archive_writes=False,
                      allow_unknown_builds=False))
    # Only validation itself is out of scope for this test (covered separately
    # in test_core_validation_negative_contracts). All file/transaction code
    # in install_mod and uninstall_mod runs unchanged.
    monkeypatch.setattr(installer,"validate_mod",
                        lambda *_args,**_kw:[SimpleNamespace(
                            ok=True,name="synthetic-approved",
                            detail="approved by fixture")])
    monkeypatch.setattr(installer,"_assert_target_game_not_running",
                        lambda *args,**kwargs:None)
    return root,game,config


def make_source(root:Path,version:int) -> Path:
    src=root/"builds"/f"version-{version}"/"mod"
    (src/"Override"/"Assets"/"GUI").mkdir(parents=True)
    (src/"info.json").write_text(json.dumps({
        "Manifest":0,"GUID":"example.fixture","Version":str(version)
    }),encoding="utf8")
    (src/"Override"/"Assets"/"GUI"/"demo.png").write_bytes(f"fixture-{version}".encode())
    return src


def installed(config):
    return config.target.game_dir/"BepInEx"/"plugins"/config.output.mod_folder_name


def manifest(config):
    return config.output.state_dir/"install-manifest.json"


def test_new_install_and_uninstall_roundtrip_preserves_foreign_mods(fake_game):
    root,game,config=fake_game
    foreign=game/"BepInEx"/"plugins"/"unrelated-mod"
    foreign.mkdir()
    (foreign/"external.txt").write_bytes(b"do not change")
    src=make_source(root,1)
    dest=installer.install_mod(config,src)
    assert dest==installed(config)
    assert (dest/"Override"/"Assets"/"GUI"/"demo.png").read_bytes()==b"fixture-1"
    assert manifest(config).is_file()
    snapshot=json.loads(manifest(config).read_text("utf8"))
    assert snapshot["destination"]==str(dest)
    assert "Override/Assets/GUI/demo.png" in snapshot["files"]
    assert (foreign/"external.txt").read_bytes()==b"do not change"
    removed=installer.uninstall_mod(config)
    assert removed==dest
    assert not dest.exists()
    assert not manifest(config).exists()
    assert (foreign/"external.txt").read_bytes()==b"do not change"


def test_installer_replace_requires_explicit_consent(fake_game):
    root,_game,config=fake_game
    installer.install_mod(config,make_source(root,1))
    old=installed(config)/"Override"/"Assets"/"GUI"/"demo.png"
    old_bytes=old.read_bytes()
    with pytest.raises(installer.InstallError,match="already exists"):
        installer.install_mod(config,make_source(root,2))
    assert old.read_bytes()==old_bytes
    assert manifest(config).is_file()


def test_installer_replace_transaction_preserves_new_owned_files(fake_game):
    root,_game,config=fake_game
    installer.install_mod(config,make_source(root,1))
    old_manifest=manifest(config).read_bytes()
    installed_path=installed(config)
    assert (installed_path/"Override"/"Assets"/"GUI"/"demo.png").read_bytes()==b"fixture-1"
    installer.install_mod(config,make_source(root,2),replace_existing=True)
    assert (installed_path/"Override"/"Assets"/"GUI"/"demo.png").read_bytes()==b"fixture-2"
    assert manifest(config).read_bytes()!=old_manifest
    installer.uninstall_mod(config)
    assert not installed_path.exists()


def test_modified_owned_file_blocks_uninstall_and_preserves_user_edit(fake_game):
    root,_game,config=fake_game
    installer.install_mod(config,make_source(root,1))
    target=installed(config)/"Override"/"Assets"/"GUI"/"demo.png"
    target.write_bytes(b"changed outside SpriteSuite")
    before_manifest=manifest(config).read_bytes()
    with pytest.raises(installer.InstallError):
        installer.uninstall_mod(config)
    assert target.read_bytes()==b"changed outside SpriteSuite"
    assert manifest(config).read_bytes()==before_manifest


def test_failing_mod_validation_never_starts_install(fake_game,monkeypatch):
    root,_game,config=fake_game
    monkeypatch.setattr(installer,"validate_mod",
                        lambda *_a,**_kw:[SimpleNamespace(
                            ok=False,name="fail",detail="synthetic block")])
    with pytest.raises(installer.InstallError,match="validation"):
        installer.install_mod(config,make_source(root,1))
    assert not installed(config).exists()
    assert not manifest(config).exists()
    assert not config.output.state_dir.exists()


def test_game_process_during_preflight_blocks_installer(fake_game,monkeypatch):
    root,_game,config=fake_game
    def reject(_c,phase):
        raise installer.InstallError("synthetic game running: "+phase)
    monkeypatch.setattr(installer,"_assert_target_game_not_running",reject)
    with pytest.raises(installer.InstallError,match="game running"):
        installer.install_mod(config,make_source(root,1))
    assert not installed(config).exists()
    assert not config.output.state_dir.exists()


def test_post_promotion_manifest_error_rolls_back_install(fake_game,monkeypatch):
    root,_game,config=fake_game
    real=installer._rename_proven_file
    injected=[False]
    def after_manifest_rename(*args,**kwargs):
        result=real(*args,**kwargs)
        if kwargs.get("label")=="new install ownership manifest" and not injected[0]:
            injected[0]=True
            raise OSError("synthetic error after manifest rename")
        return result
    monkeypatch.setattr(installer,"_rename_proven_file",after_manifest_rename)
    with pytest.raises(OSError,match="after manifest rename"):
        installer.install_mod(config,make_source(root,1))
    assert injected==[True]
    assert not installed(config).exists()
    assert not manifest(config).exists()


def test_post_promotion_manifest_error_restores_previous_install(
    fake_game,monkeypatch,
):
    root,_game,config=fake_game
    installer.install_mod(config,make_source(root,1))
    first_manifest=manifest(config).read_bytes()
    dest=installed(config)
    original=dest/"Override"/"Assets"/"GUI"/"demo.png"
    first_bytes=original.read_bytes()
    real=installer._rename_proven_file
    injected=[False]
    def after_manifest_rename(*args,**kwargs):
        result=real(*args,**kwargs)
        if kwargs.get("label")=="new install ownership manifest" and not injected[0]:
            injected[0]=True
            raise OSError("synthetic replacement manifest failure")
        return result
    monkeypatch.setattr(installer,"_rename_proven_file",after_manifest_rename)
    with pytest.raises(OSError,match="replacement manifest"):
        installer.install_mod(config,make_source(root,2),replace_existing=True)
    assert injected==[True]
    assert original.read_bytes()==first_bytes
    assert manifest(config).read_bytes()==first_manifest
