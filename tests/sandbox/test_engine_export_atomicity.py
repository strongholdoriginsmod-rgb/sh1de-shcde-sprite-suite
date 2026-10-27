"""Safety contract: generated native PNG and index must commit as one unit.

Headless tempfile fixtures; never touch installed resources or user catalog.
An index-write failure previously stranded a newly created, unindexed PNG.
That ghost entry blocked every subsequent export retry for that frame.
"""
from pathlib import Path
from types import SimpleNamespace
import json,os,sys
import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT/"tools") not in sys.path:sys.path.insert(0,str(ROOT/"tools"))
import sandbox_engine_assets as assets


def provider(tmp_path,monkeypatch,with_index=False):
    game=tmp_path/"Game_Data"
    original=game/"StreamingAssets/Maps/dummy.map"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"immutable-fake-map")
    (game/"resources.assets").write_bytes(b"immutable-fake-game-archive")
    provider=assets.EngineSpriteAssets(original)
    provider._source_hash="a"*64
    folder=tmp_path/"derived"/"crusader"/"tree_cactii"
    folder.mkdir(parents=True)
    index=folder/"index.json"
    if with_index:
        index.write_text(json.dumps({"schema_version":1,
            "group":"tree_cactii","game":"crusader",
            "frames":[{"name":"other-safe-frame","file":"other.png"}]}))
    monkeypatch.setattr(assets.catalog,"native_name",
                        lambda group,number:f"{group}-{number}")
    monkeypatch.setattr(assets.catalog,"side_dir",
                        lambda side,group:tmp_path/"derived"/side/group)
    monkeypatch.setattr(assets.catalog,"index_of",
                        lambda folder: json.loads(index.read_text())
                        if index.exists() else {})
    frame=SimpleNamespace(image=Image.new("RGBA",(8,10),(40,90,150,255)),
                          foot=(4,9))
    return provider,frame,folder,index,original,game/"resources.assets"


@pytest.mark.parametrize("existing_index",[False,True])
def test_index_swap_failure_must_not_leave_unregistered_original_fallback(
    tmp_path,monkeypatch,existing_index
):
    obj,frame,folder,index,source,archive=provider(
        tmp_path,monkeypatch,with_index=existing_index
    )
    source_before=source.read_bytes()
    archive_before=archive.read_bytes()
    index_before=index.read_bytes() if index.exists() else None
    original_replace=os.replace
    replacements=[]
    def deny_index(source_path,target_path):
        replacements.append(Path(target_path).name)
        if Path(target_path).name=="index.json":
            raise PermissionError("index storage is read-only (QA injected)")
        return original_replace(source_path,target_path)
    monkeypatch.setattr(assets.os,"replace",deny_index)
    with pytest.raises(PermissionError,match="read-only"):
        obj._export_missing("tree_cactii",0,frame)
    assert "tree_cactii-0.png" in replacements
    assert "index.json" in replacements
    assert not (folder/"tree_cactii-0.png").exists(), (
        "A new unindexed PNG was stranded; a retry then cannot register it"
    )
    assert not list(folder.glob(".native-*")), "Temporary export files leaked"
    assert not index.exists() if index_before is None else index.read_bytes()==index_before
    assert source.read_bytes()==source_before
    assert archive.read_bytes()==archive_before
    assert obj.exported==0
    # A fixed writer can recover and register the original frame next time.
    monkeypatch.setattr(assets.os,"replace",original_replace)
    obj._export_missing("tree_cactii",0,frame)
    assert (folder/"tree_cactii-0.png").is_file()
    records=json.loads(index.read_text())["frames"]
    assert sum(row["name"]=="tree_cactii-0" for row in records)==1
    assert obj.exported==1


@pytest.mark.parametrize("payload",[
    b"{malformed JSON; precious previous catalog bytes",
    b'{"schema":"sprite-suite.global-settings.v1","settings":["keep-me"]}',
    b'{"schema_version":1,"group":"not-tree-cactii","game":"crusader","frames":[]}',
    b'{"schema_version":1,"group":"tree_cactii","game":"crusader","frames":[],"future_build_metadata":{"not":"discardable"}}'
])
def test_existing_unknown_or_corrupt_catalog_index_must_not_be_rewritten(
    tmp_path,monkeypatch,payload
):
    obj,frame,folder,index,source,archive=provider(tmp_path,monkeypatch)
    index.write_bytes(payload)
    before_index=index.read_bytes()
    before_map=source.read_bytes()
    with pytest.raises(ValueError):
        obj._export_missing("tree_cactii",0,frame)
    assert index.read_bytes()==before_index
    assert source.read_bytes()==before_map
    assert not (folder/"tree_cactii-0.png").exists()
    assert not list(folder.glob(".native-*"))


@pytest.mark.parametrize("phase",["png_replace","index_serialization"])
def test_any_export_stage_failure_is_recoverable_and_leaves_no_artifacts(
    tmp_path,monkeypatch,phase
):
    obj,frame,folder,index,source,archive=provider(tmp_path,monkeypatch)
    before_map=source.read_bytes()
    before_archive=archive.read_bytes()
    if phase=="png_replace":
        original=os.replace
        def deny_png(src,dst):
            if Path(dst).suffix.lower()==".png":
                raise PermissionError("QA: PNG destination not writable")
            return original(src,dst)
        monkeypatch.setattr(assets.os,"replace",deny_png)
    else:
        def deny_serialization(*args,**kwargs):
            raise OSError("QA: index serialization interrupted")
        monkeypatch.setattr(assets.json,"dump",deny_serialization)
    with pytest.raises(OSError):
        obj._export_missing("tree_cactii",0,frame)
    assert not (folder/"tree_cactii-0.png").exists()
    assert not index.exists()
    assert not list(folder.glob(".native-*"))
    assert obj.exported==0
    assert source.read_bytes()==before_map
    assert archive.read_bytes()==before_archive


def test_valid_preexisting_crusader_index_retains_other_authored_entries(
    tmp_path,monkeypatch
):
    obj,frame,folder,index,source,archive=provider(
        tmp_path,monkeypatch,with_index=True
    )
    before=json.loads(index.read_text(encoding="utf8"))
    obj._export_missing("tree_cactii",0,frame)
    changed=json.loads(index.read_text(encoding="utf8"))
    assert changed["frames"][0]==before["frames"][0]
    assert [item["name"] for item in changed["frames"]]==[
        "other-safe-frame","tree_cactii-0"
    ]
    assert obj.exported==1


def test_corrupt_index_never_deletes_existing_unrelated_png(
    tmp_path,monkeypatch
):
    obj,frame,folder,index,source,archive=provider(tmp_path,monkeypatch)
    manual=folder/"other-safe-frame.png"
    Image.new("RGBA",(3,3),(240,31,60,255)).save(manual)
    existing=manual.read_bytes()
    index.write_bytes(b'{"schema":"foreign-user-settings","keep":"every byte"}')
    original=index.read_bytes()
    with pytest.raises(ValueError):
        obj._export_missing("tree_cactii",0,frame)
    assert index.read_bytes()==original
    assert manual.read_bytes()==existing
    assert not (folder/"tree_cactii-0.png").exists()
