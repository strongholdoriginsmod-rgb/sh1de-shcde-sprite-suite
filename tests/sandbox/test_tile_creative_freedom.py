"""Custom tile artwork round-trips without semantic approval or a preset gate."""
from hashlib import sha256
import json

from PIL import Image
import pytest

from stronghold_europe_de.tile_presets import load_tile_presets
from stronghold_europe_de.tile_roundtrip import compose_object, split_object, TileRoundtripError


def test_custom_tile_split_needs_no_confirmation_and_preserves_pixels(tmp_path):
    source=tmp_path/'source'
    source.mkdir()
    png=source/'tile_1.png'
    with Image.new('RGBA',(64,64),(103,37,11,0)) as image:
        image.putpixel((31,31),(100,200,30,255))
        image.save(png)
        expected=image.tobytes()
    index={'group':'tile_castle','frames':[{'name':'tile_1','file':png.name,
        'crusader':{'width':64,'height':64,'pivot_x':0.5,'pivot_y':16.5/64}}]}
    (source/'index.json').write_text(json.dumps(index),encoding='utf8')
    before=sha256(png.read_bytes()).hexdigest()
    package=tmp_path/'custom'
    manifest=compose_object(source,package,start=1,end=1,columns=1,rows=1)
    assert manifest['semantic']['status']=='custom-unconfirmed'
    result=split_object(package,tmp_path/'returned')
    assert result['semantic']['status']=='custom-unconfirmed'
    assert result['frame_count']==1
    with Image.open(tmp_path/'returned'/png.name) as image:
        assert image.convert('RGBA').tobytes()==expected
    assert sha256(png.read_bytes()).hexdigest()==before
    assert json.loads((tmp_path/'returned'/'tile-object-result.json').read_text())['semantic']['status']=='custom-unconfirmed'


def test_user_catalog_preset_does_not_need_a_quality_release(tmp_path):
    path=tmp_path/'presets.json'
    path.write_text(json.dumps({'schema_version':1,'presets':[{
        'id':'custom','label':'My experiment','group':'tile_castle','from':1,'to':1,
        'columns':1,'rows':1,'layout':'row-major','verification':'draft'}]}),encoding='utf8')
    presets=load_tile_presets(path)
    assert presets[0].verification=='draft'
    assert presets[0].start==1 and presets[0].columns==1


def test_custom_preset_still_requires_a_representable_grid(tmp_path):
    path=tmp_path/'bad.json'
    path.write_text(json.dumps({'schema_version':1,'presets':[{
        'id':'custom','label':'My experiment','group':'tile_castle','from':1,'to':2,
        'columns':1,'rows':1,'layout':'row-major','verification':'draft'}]}),encoding='utf8')
    from stronghold_europe_de.tile_presets import TilePresetError
    with pytest.raises(TilePresetError,match='Raster'):
        load_tile_presets(path)
