"""Skirmish start validation from section 1013, no map writes."""
from pathlib import Path
import pytest
from stronghold_europe_de.sandbox.start_keep_audit import audit_start_keeps

MAPS=Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")

@pytest.mark.skipif(not MAPS.is_dir(),reason="Original game maps unavailable")
@pytest.mark.parametrize("name,players,expected",[
    ("Antioch.map",3,"passend"),
    ("Crusader Demo.map",5,"passend"),
    ("A Mighty Oasis.map",0,"kein_skirmish"),
])
def test_actual_skirmish_keep_and_mode(name,players,expected):
    path=MAPS/name
    stamp=(path.stat().st_mtime_ns,path.stat().st_size)
    result=audit_start_keeps(path)
    assert result.players==players
    assert result.state==expected
    if expected=="passend":
        assert len(result.starts)==players
        assert {x[0] for x in result.starts}==set(range(1,players+1))
    else:
        assert result.starts==()
    assert (path.stat().st_mtime_ns,path.stat().st_size)==stamp


@pytest.mark.skipif(not MAPS.is_dir(),reason="Original game maps unavailable")
def test_start_keeps_visible_in_qt_map_inspector(monkeypatch,tmp_path):
    pytest.importorskip("PySide6")
    import sys
    from PySide6.QtWidgets import QApplication
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"tools"))
    import sandbox_studio
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setattr(sandbox_studio,"ROOT",tmp_path)
    app=QApplication.instance() or QApplication([])
    studio=sandbox_studio.SandboxStudio(tmp_path)
    try:
        assert studio.open_map(MAPS/"Antioch.map")
        props={
            studio.info.topLevelItem(i).text(0):studio.info.topLevelItem(i).text(1)
            for i in range(studio.info.topLevelItemCount())
        }
        assert "Passend" in props["Original-Startburgen"]
        assert "3 Spielerslots" in props["Original-Startburgen"]
        assert "1:" in props["Burgstarts (Eigentümer / X / Y)"]
    finally:
        studio.native_canvas._poll.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        if studio.native_canvas.has_map():
            studio._saved_overlay=studio.native_canvas.history.overlay.serialize()
        studio.close()
