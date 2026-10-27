"""Authoritative local-engine graphics, strict ABI and derived-cache validation."""
from pathlib import Path
import hashlib
import json
import os
import numpy as np
import pytest

from stronghold_europe_de.sandbox.native_runtime import (
    RuntimeSnapshot, NativeRuntimeError, load_contract, capture_snapshot,
    read_snapshot, SNAPSHOT_SCHEMA, CAPTURE_REVISION, sha256,
)
from stronghold_europe_de.sandbox.runtime_graphics import (
    RuntimeSpriteResolver, remap_tile_frame, light_multiplier,
)

MAPS=Path('E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps')
REAL_ENGINE = os.name == 'nt' and (MAPS.parents[1]/'Plugins/x86_64/CrusaderDE.dll').is_file()


def records():
    entries=np.zeros((3,21),dtype='<i2')
    entries[0,:7]=[0,400,400,55,305,8,3]
    entries[1,:7]=[0,401,400,52,732,8,0]
    entries[2,:12]=[1,399,400,200,17,-8,0,0,0,0,99,0]
    return entries


def test_snapshot_lookup_and_duplicate_rejection():
    frame=RuntimeSnapshot(records(),{})
    assert frame.visible_tile_count==2 and frame.object_count==1
    assert frame.tile(400,400)[4]==305
    assert frame.tile(400,399) is None
    assert len(frame.rows[400])==3
    assert all(len(frame.rows[y])==0 for y in (0,399,401,799))
    invalid=records();invalid[1,1:3]=invalid[0,1:3]
    with pytest.raises(NativeRuntimeError,match='Doppelte'):
        RuntimeSnapshot(invalid,{})
    with pytest.raises(NativeRuntimeError):
        RuntimeSnapshot(records().astype('int32'),{})
    invalid=records();invalid[0,1]=900
    with pytest.raises(NativeRuntimeError):RuntimeSnapshot(invalid,{})


def test_cache_checks_count_hash_source_and_revision(tmp_path):
    data=records().tobytes()
    (tmp_path/'records.bin').write_bytes(data)
    meta={'schema':SNAPSHOT_SCHEMA,'capture_revision':CAPTURE_REVISION,
          'map_sha256':'a'*64,'dll_sha256':'b'*64,
          'records_sha256':hashlib.sha256(data).hexdigest(),'record_count':3}
    (tmp_path/'snapshot.json').write_text(json.dumps(meta),encoding='utf-8')
    assert read_snapshot(tmp_path,'a'*64,'b'*64).tile(401,400)[3]==52
    with pytest.raises(NativeRuntimeError):read_snapshot(tmp_path,'c'*64,'b'*64)
    (tmp_path/'records.bin').write_bytes(data[:-2])
    with pytest.raises(NativeRuntimeError):read_snapshot(tmp_path,'a'*64,'b'*64)
    (tmp_path/'records.bin').write_bytes(bytes([0])*len(data))
    with pytest.raises(NativeRuntimeError):read_snapshot(tmp_path,'a'*64,'b'*64)


@pytest.mark.parametrize('file,frame,group,index',[
    (2,1,'tile_land8',1),(55,305,'tile_land_macros',305),
    (52,732,'tile_castle',732),(29,1,'tree_birch',0),
    (200,17,'tree_cactii',16),(100,173,'body_lord',172),
    (54,28,'anim_castle',28),(167,145,'body_seagull',28),
    (223,209,'body_condor',28),
])
def test_exact_runtime_sprite_family_and_one_based_body_rules(file,frame,group,index):
    tile=file in (2,52,55)
    result=RuntimeSpriteResolver().resolve(file,frame,tile=tile)
    assert result.group==group and result.frame==index
    if not tile:
        assert RuntimeSpriteResolver().resolve(29,0,tile=False) is None


@pytest.mark.parametrize('gm,image,expected_frame,expected_light',[
    (5,1,1,50),(5,32,4,55),(5,33,5,55),(5,65,9,50),
    (5,72,9,55),(5,543,535,50),(5,660,632,55),
    (5,1805,1805,50),(5,1985,1805,51),
    (6,3,1,0),(6,24,24,13),(55,5,5,13),
    (166,1,1,0),(166,1476,246,5),
    (166,2168,2168,0),(166,2984,2168,1),(166,7063,2983,5),
])
def test_water_frame_and_shadow_normalization(gm,image,expected_frame,expected_light):
    assert remap_tile_frame(gm,image,5)==(expected_frame,expected_light)


def test_split_shore_atlas_and_light_constants():
    source=RuntimeSpriteResolver()
    assert source.resolve(166,2168).group=='tile_sea_shore'
    assert source.resolve(166,2168).frame==1
    assert source.resolve(166,2984).frame==1
    assert source.resolve(38,321) is None
    assert light_multiplier(3)==pytest.approx(.7)
    assert light_multiplier(17)==pytest.approx(.58)
    assert light_multiplier(52)==pytest.approx(.9)
    assert light_multiplier(50)==1


@pytest.mark.skipif(not REAL_ENGINE,reason='Authorized local SHCDE native engine unavailable')
@pytest.mark.parametrize('name,tiles,objects',[
    ('Antioch.map',44104,1040),('Crusader Demo.map',44104,1080),
    ('A Mighty Oasis.map',78804,1242),
])
def test_three_original_maps_exact_native_commands_and_no_source_writes(name,tiles,objects):
    path=MAPS/name
    before=sha256(path)
    frame=capture_snapshot(path)
    assert frame.visible_tile_count==tiles
    assert frame.object_count==objects
    assert frame.metadata['paused'] is True
    assert frame.metadata['map_sha256']==before
    assert len(frame.records)>320000
    if name=='Antioch.map':
        assert tuple(frame.tile(400,400)[3:7])==(55,305,8,3)
        assert tuple(frame.tile(505,385)[3:6])==(52,732,8)
        assert tuple(frame.tile(505,388)[3:6])==(52,717,8)
    # Cached render decisions must be reproducible, not running a later tick.
    cached=capture_snapshot(path)
    assert np.array_equal(cached.records,frame.records)
    assert sha256(path)==before


def test_unknown_engine_hash_is_not_loaded(monkeypatch,tmp_path):
    if os.name!='nt':pytest.skip('Windows path validation')
    import stronghold_europe_de.sandbox.native_runtime as runtime
    source=tmp_path/'Game_Data/StreamingAssets/Maps/a.map'
    source.parent.mkdir(parents=True);source.write_bytes(b'map')
    plugin=tmp_path/'Game_Data/Plugins/x86_64/CrusaderDE.dll'
    plugin.parent.mkdir(parents=True);plugin.write_bytes(b'unknown dll')
    managed=tmp_path/'Game_Data/Managed/Assembly-CSharp.dll'
    managed.parent.mkdir(parents=True);managed.write_bytes(b'unknown assembly')
    with pytest.raises(NativeRuntimeError,match='verifizierten ABI'):
        capture_snapshot(source,tmp_path/'cache')
    assert not (tmp_path/'cache').exists()


def test_abi_contract_rejects_path_and_array_tampering(tmp_path):
    import copy
    baseline=load_contract()
    path=tmp_path/'contract.json'
    bad=copy.deepcopy(baseline)
    bad['gm_files']['200'][0]['group']='../../outside'
    path.write_text(json.dumps(bad))
    with pytest.raises(NativeRuntimeError):load_contract(path)
    bad=copy.deepcopy(baseline);bad['abi']['array_shorts']=5
    path.write_text(json.dumps(bad))
    with pytest.raises(NativeRuntimeError):load_contract(path)
    bad=copy.deepcopy(baseline);bad['dll_sha256']='not a known digest'
    path.write_text(json.dumps(bad))
    with pytest.raises(NativeRuntimeError):load_contract(path)
