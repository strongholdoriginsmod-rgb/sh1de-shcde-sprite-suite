"""Synthetic tests of integrated HUD Studio against XAML and Origins contracts."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from ui_sh1_hud import HudError
import suite_sh1_hud_core as core

from test_sh1_hud_edit_roundtrip import make


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    project = make(tmp_path)
    with (project/"sh1_hud_source.json").open("r",encoding="utf8") as f:
        meta=json.load(f)
    meta["source"]="Stronghold 1 Definitive Edition"
    (project/"sh1_hud_source.json").write_text(json.dumps(meta),encoding="utf8")
    monkeypatch.setattr(core,"ROOT",tmp_path)
    monkeypatch.setattr(core,"WORK",tmp_path/"work")
    return project


def test_studio_reuses_original_index_and_noesis_keys(workspace):
    entries=core.load_project(workspace)
    assert len(entries)==3
    assert {e["key"] for e in entries} == {"UI-HUD 007","ROL-A001","Candle01"}
    assert all(core.entry_state(entry)=="Original" for entry in entries)


def test_editor_cache_preserves_per_crop_dimensions_and_pixel_checksums(workspace):
    entries=core.load_project(workspace)
    for entry in entries:
        original=core.original_crop(workspace,entry)
        assert original.size == (entry["width"],entry["height"])


def test_reset_creates_independent_backup_and_restores_original(workspace):
    entries=core.load_project(workspace)
    entry=next(e for e in entries if e["key"]=="ROL-A001")
    path=Path(entry["path"])
    with Image.open(path) as stream:changed=stream.convert("RGBA")
    changed.putpixel((0,0),(28,200,112,255))
    changed.save(path)
    assert core.entry_state(entry)=="Geändert"
    previous=path.read_bytes()
    result=core.restore_original(workspace,entry)
    assert result.is_file() and result.read_bytes()==previous
    assert result.parent.name == "sh1-hud-ruecksetzen"
    assert core.entry_state(entry)=="Original"


def test_reset_refuses_concurrent_image_update(workspace):
    from ui_sh1_hud import digest_file
    entry=next(e for e in core.load_project(workspace) if e["key"]=="Candle01")
    path=Path(entry["path"])
    earlier=digest_file(path)
    Image.new("RGBA",(6,5),(200,17,45,255)).save(path)
    with pytest.raises(HudError,match="extern verändert"):
        core.restore_original(workspace,entry,expected_disk_hash=earlier)
    assert core.entry_state(entry)=="Geändert"


def test_root_and_symlink_escape_rejected(workspace, tmp_path):
    with pytest.raises(HudError,match="unter SpriteSuite/work"):
        core.load_project(tmp_path)
    with pytest.raises(HudError):
        core.load_project(workspace.parent)


def test_origins_bridge_uses_names_never_coordinates(workspace, tmp_path):
    other=tmp_path/"legacy_crusader"
    shutil.copytree(workspace,other)
    path=other/"index.json"
    index=json.loads(path.read_text(encoding="utf8"))
    # Legacy target has the same named motif, but packed elsewhere in atlas.
    index["atlases"][0]["crops"][0]["x"]=8
    index["atlases"][0]["crops"][0]["y"]=9
    # Preview geometry allows original 16x16 as long as crop stays inside.
    index["atlases"][0]["crops"][0]["width"]=5
    index["atlases"][0]["crops"][0]["height"]=5
    path.write_text(json.dumps(index),encoding="utf8")
    report=core.compare_legacy(workspace,other)
    assert report["same_key_count"]==3
    assert report["same_dimensions_count"]==2
    assert report["different_dimensions_count"]==1
    assert report["layout_positions_shared"] is False
    assert report["unity_path_ids_shared"] is False
    assert report["writes_to_game"] is False


def test_ui_editor_rejects_arbitrary_png_even_under_known_atlas(workspace, monkeypatch):
    import tkinter as tk
    import ui_sh1_hud
    import suite_sh1_hud_editor as editor
    monkeypatch.setattr(ui_sh1_hud,"DEFAULT_WORK",workspace)
    arbitrary=workspace/"UI-MasterAtlas"/"unindexed.png"
    Image.new("RGBA",(6,5)).save(arbitrary)
    try:
        root=tk.Tk()
        root.withdraw()
    except tk.TclError as exc:
        pytest.skip(f"Tk runtime unavailable: {exc}")
    try:
        with pytest.raises(ValueError,match="keine benannte"):
            editor.Sh1HudPixelEditor(root,arbitrary,workspace=workspace)
    finally:
        root.destroy()
