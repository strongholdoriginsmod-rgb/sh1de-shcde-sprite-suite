"""End-to-end V1 lossless model, old renderer, editable Qt and source guards."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"tools")]
ORIGINAL=Path("E:/SU/projekt/sandbox/szenen")
from stronghold_europe_de.sandbox.scene_model import (
    SceneError,EditableScene,SceneHistory,load_scene,save_scene
)
from sandkasten import scene_items,render

@pytest.mark.parametrize("name",["beispieldorf.json","katalog-vorschau.json"])
def test_v1_read_modify_undo_save_reload_semantics_are_lossless(name,tmp_path):
    source=ORIGINAL/name
    if not source.is_file():pytest.skip("Historical original scenes absent")
    original=source.read_bytes()
    before=json.loads(original.decode("utf-8-sig"))
    scene=load_scene(source)
    assert scene.is_legacy_v1
    assert scene.serialize()==before
    for time in (0,1.37,5.5):
        a=scene_items(before,time)
        b=scene_items(scene.serialize(),time)
        assert [(x.group,x.name,x.x,x.y,x.layer,x.order) for x in a]==[
            (x.group,x.name,x.x,x.y,x.layer,x.order) for x in b]
    history=SceneHistory(scene)
    obj=history.scene.objects[0]
    history.move(obj.id,obj.x,obj.y-1)
    assert history.scene.serialize()["objekte"][0]["y"]==obj.y-1
    history.undo()
    assert history.scene.serialize()==before
    history.redo()
    history.undo()
    history.legacy_set_scene_details(
        ground_group="tile_land8",ground_frames=[1,3,7],
        ground_seed=2026,hud_visible=False,name="Nachgeprüfte V1-Kopie")
    history.legacy_update_object_details(
        obj.id,title="Ganzer GM1-Bau",columns=4,rows=4,layout="gm1")
    animated=next((o for o in history.scene.objects if
                   history.scene.legacy_entries[o.id].get("animation")),None)
    assert animated
    history.legacy_update_object_details(animated.id,
        animation={"von":0,"bis":24,"fps":12.5},alternate=True)
    frame=next(o for o in history.scene.objects
               if history.scene.legacy_entries[o.id]["art"]=="sprite")
    history.update(frame.id,team="orange")
    identity=history.scene.serialize()
    target=tmp_path/"v1-work-copy.json"
    save_scene(target,history.scene)
    restored=load_scene(target)
    assert restored.is_legacy_v1
    assert restored.serialize()==identity
    assert restored.serialize()["objekte"][0]["layout"]=="gm1"
    assert restored.serialize()["boden"]["saat"]==2026
    assert restored.serialize()["hud"]["sichtbar"] is False
    assert sha256(source.read_bytes()).digest()==sha256(original).digest()

def test_unknown_v1_semantics_fail_closed(tmp_path):
    source=json.loads((ORIGINAL/"beispieldorf.json").read_text(encoding="utf-8-sig"))
    for record in [
        {**source,"non_documented_field":{"future":"critical"}},
        {**source,"boden":{**source["boden"],"strange_shader":"lost"}},
        {**source,"objekte":[{**source["objekte"][0],"future_gameplay_state":1}]},
    ]:
        with pytest.raises(SceneError):
            EditableScene.deserialize(record)


@pytest.fixture
def app_studio(tmp_path,monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication,QMessageBox
    import sandbox_studio
    import sandbox_test_board
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setenv("SEDE_SPRACHE","de")
    monkeypatch.setattr(sandbox_studio,"ROOT",tmp_path)
    qt=QApplication.instance() or QApplication([])
    scene_window=sandbox_studio.SandboxStudio(tmp_path)
    class FakeSource:
        def __init__(self,*args,**kwargs):self.cache={}
        def frame(self,group,name):
            key=group,name
            if key not in self.cache:
                rgb=sha256(f"{group}/{name}".encode()).digest()
                self.cache[key]=SimpleNamespace(
                    image=Image.new("RGBA",(17,19),(*rgb[:3],255)),
                    foot=(8.5,17.5),mask=None,side="test"
                )
            return self.cache[key]
    monkeypatch.setattr(sandbox_test_board,"FrameSource",FakeSource)
    monkeypatch.setattr(QMessageBox,"warning",lambda *a,**k: None)
    try:yield scene_window,qt
    finally:
        dialog=scene_window._legacy_dialog
        if dialog is not None:dialog.close()
        scene_window.native_canvas._poll.stop()
        scene_window.board._asset_poll.stop()
        scene_window.asset_preview.timer.stop()
        scene_window._saved_scene=scene_window.board.history.scene.serialize()
        scene_window.close()
        qt.processEvents()


def test_real_qt_v1_edit_controls_preserve_gm1_and_animation(app_studio,tmp_path):
    window,qt=app_studio
    original=ORIGINAL/"beispieldorf.json"
    before=sha256(original.read_bytes()).hexdigest()
    assert window.load_test_scene(original)
    assert window.board.history.scene.is_legacy_v1
    assert window._scene_path is None  # original never a Save target
    assert window.open_legacy_scene_editor()
    dialog=window._legacy_dialog
    dialog.seed.setValue(2026)
    dialog.name.setText("Historisches Dorf / Arbeitskopie")
    dialog.save_general()
    assert window.board.history.scene.serialize()["boden"]["saat"]==2026
    first=window.board.history.scene.objects[0]
    window.board._items[first.id].setSelected(True)
    qt.processEvents()
    dialog.title.setText("Neuer GM1-Titel")
    dialog.save_object()
    assert window.board.history.scene.serialize()["objekte"][0]["titel"]=="Neuer GM1-Titel"
    assert window.board.history.scene.serialize()["objekte"][0]["spalten"]==4
    assert window.board.set_legacy_tick(1.37)
    assert window.board.history.scene.serialize()["objekte"][0]["titel"]=="Neuer GM1-Titel"
    window.board.undo()
    assert window.board.history.scene.serialize()["objekte"][0]["titel"]=="Huette 1"
    window.board.redo()
    target=tmp_path/"work"/"v1-copy.json"
    assert window.save_test_scene(target)
    assert load_scene(target).serialize()==window.board.history.scene.serialize()
    assert sha256(original.read_bytes()).hexdigest()==before
    assert not window.save_test_scene(original)
    assert sha256(original.read_bytes()).hexdigest()==before


def test_legacy_selection_and_slider_do_not_reenter_scene_deletion(app_studio):
    """Rebuild/selection must not destroy the active QGraphicsItem mid-signal."""
    window,qt=app_studio
    assert window.load_test_scene(ORIGINAL/"beispieldorf.json")
    board=window.board
    assert board.history.scene.is_legacy_v1
    history=board.history.scene.serialize()
    objects=list(board.history.scene.objects)
    signals=[]
    board.selected_id_changed.connect(signals.append)
    for index in range(24):
        ident=objects[index % len(objects)].id
        board.scene().clearSelection()
        item=board._items[ident]
        item.setSelected(True)
        qt.processEvents()
        assert board.selected_id()==ident
        assert board._legacy_frame_overrides=={}
        assert not board._legacy_rebuilding
    assert board.history.scene.serialize()==history
    # Directly preview a frame and return to the original without writing
    # scene history; both actions must remain safe inside the same Qt session.
    target=objects[-1]
    board.preview_object_frame(target.id,target.frame+1)
    qt.processEvents()
    board.restore_object_frame(target.id)
    qt.processEvents()
    assert not board._legacy_rebuilding
    assert board.history.scene.serialize()==history
    assert signals
