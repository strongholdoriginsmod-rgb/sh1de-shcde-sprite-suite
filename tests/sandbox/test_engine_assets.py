"""Native original sprite fallback does not alter game files or user art."""
from pathlib import Path
from types import SimpleNamespace
import sys
import json
from PIL import Image
import pytest

TOOLS=str(Path(__file__).resolve().parents[2]/'tools')
if TOOLS not in sys.path:sys.path.insert(0,TOOLS)
import sandbox_engine_assets as assets
from sandkasten import FrameSource


def setup_provider(tmp_path,monkeypatch):
    data=tmp_path/'Game_Data'
    path=data/'StreamingAssets/Maps/test.map';path.parent.mkdir(parents=True)
    path.write_bytes(b'original map data')
    archive=data/'resources.assets';archive.write_bytes(b'original game resources')
    provider=assets.EngineSpriteAssets(path)
    reader=SimpleNamespace(read=lambda:SimpleNamespace(
        image=Image.new('RGBA',(8,10),(40,80,120,255)),m_Pivot=SimpleNamespace(x=.25,y=.3)))
    provider._readers={'tree_cactii-0':reader}
    provider._source_hash='a'*64
    store=tmp_path/'derived'
    monkeypatch.setattr(assets.catalog,'work_dir',lambda group:store/'arbeit'/group)
    monkeypatch.setattr(assets.catalog,'side_dir',lambda side,group:store/side/group)
    monkeypatch.setattr(assets.catalog,'native_name',lambda group,n:f'{group}-{n}')
    monkeypatch.setattr(assets.catalog,'ensure_side',lambda *a,**kw:0)
    return provider,path,archive,store


def test_missing_native_frame_creates_only_derived_catalog(tmp_path,monkeypatch):
    provider,path,archive,store=setup_provider(tmp_path,monkeypatch)
    frame=provider.frame('tree_cactii',0,FrameSource('arbeit',log=lambda _:None))
    assert frame.image.size==(8,10)
    assert frame.foot==pytest.approx((2,7))
    dest=store/'crusader/tree_cactii'
    assert (dest/'tree_cactii-0.png').is_file()
    index=json.loads((dest/'index.json').read_text(encoding='utf-8'))
    assert index['frames'][0]['pivot_x']==.25
    assert index['frames'][0]['pivot_y']==pytest.approx(.3)
    assert index['frames'][0]['native_source']['sha256']=='a'*64
    assert path.read_bytes()==b'original map data'
    assert archive.read_bytes()==b'original game resources'
    assert not list(store.rglob('*.tmp'))
    assert provider.exported==1
    again=provider.frame('tree_cactii',0,FrameSource('arbeit',log=lambda _:None))
    assert again.image.tobytes()==frame.image.tobytes()
    assert provider.exported==1


def test_original_reference_does_not_use_or_overwrite_authored_frame(tmp_path,monkeypatch):
    provider,path,archive,store=setup_provider(tmp_path,monkeypatch)
    work=store/'arbeit/tree_cactii';work.mkdir(parents=True)
    authored=Image.new('RGBA',(8,10),(255,12,15,255));authored.save(work/'tree_cactii-0.png')
    payload={'frames':[{'name':'tree_cactii-0','file':'tree_cactii-0.png','width':8,'height':10,'pivot_x':.5,'pivot_y':.1}]}
    (work/'index.json').write_text(json.dumps(payload))
    preserved=(work/'tree_cactii-0.png').read_bytes()
    provider.original_only=True
    frame=provider.frame('tree_cactii',0,FrameSource('arbeit',log=lambda _:None))
    assert frame.image.getpixel((0,0))==(40,80,120,255)
    assert (work/'tree_cactii-0.png').read_bytes()==preserved
    assert not (store/'crusader').exists()


def test_missing_original_name_is_reported_once(tmp_path,monkeypatch):
    provider,_,_,store=setup_provider(tmp_path,monkeypatch)
    assert provider.original('tree_cactii',17) is None
    assert provider.original('tree_cactii',17) is None
    assert provider.missing=={('tree_cactii',17)}
    assert not store.exists()
