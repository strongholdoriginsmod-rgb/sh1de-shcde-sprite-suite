"""Individual, safely navigable frame rows from the native BC7 geometry proof."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path

import pytest

from stronghold_europe_de.pivot_native_provenance import audit_native_geometry
ROOT=Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0,str(ROOT/"tools"))
from pivot_native_proof_rows import (
    NativeProofRowsError, catalog_frame_name, native_frame_rows,
)


@pytest.fixture
def sample():
    return {
        "schema":"stronghold-europe.pivot-native-provenance.v1",
        "group_proof":{
            "group":"anim_castle",
            "total_frames":2,
            "native_source_frames":1,
            "target_keep_frames":1,
            "frames":[
                {"name":"anim_castle 001","action":"REVIEW_MANUAL",
                 "origin":"SOURCE_SH1DE","pivot":[0.0,1.0],
                 "geometry":[333,165],"source_path_id":12414,
                 "target_path_id":86476},
                {"name":"anim_castle 138","action":"KEEP_CRUSADER",
                 "origin":"TARGET_SHCDE","pivot":[-0.01666667,1.0],
                 "geometry":[60,109],"source_path_id":None,
                 "target_path_id":128546},
            ],
        },
    }


def test_native_frame_rows_explain_origins_and_support_safe_catalog_jump(sample):
    rows=native_frame_rows(sample)
    assert len(rows)==2
    assert rows[0]["pruefung"]=="Nativ-Frame"
    assert rows[0]["gruppe"]=="anim_castle"
    assert rows[0]["frames"]==["anim_castle 001"]
    assert rows[0]["daten"]["pivot"]==[0.0,1.0]
    assert rows[0]["daten"]["groesse"]==[333,165]
    assert "SH1DE-Quellgrafik" in rows[0]["text"]
    assert "Crusader-Fallback" in rows[1]["text"]
    assert catalog_frame_name(rows[1])=="anim_castle 138"


@pytest.mark.parametrize("malformed",[
    ("group_proof","group","tile_castle"),
    ("group_proof","total_frames",3),
    ("group_proof","native_source_frames",2),
    ("group_proof","target_keep_frames",2),
])
def test_reject_inconsistent_group_summary(sample,malformed):
    raw=deepcopy(sample)
    key,field,value=malformed
    raw[key][field]=value
    with pytest.raises(NativeProofRowsError):
        native_frame_rows(raw)


@pytest.mark.parametrize("key,value",[
    ("name","../../anim_castle 001"),
    ("name","anim_castle 001;rm"),
    ("geometry",[0,165]),
    ("geometry",[333,float("inf")]),
    ("pivot",[0,float("nan")]),
    ("pivot",[0,50]),
    ("action","EXECUTE_GAME"),
    ("origin","UNVERIFIED_ORIGIN"),
])
def test_reject_noncanonical_or_untrusted_frame(sample,key,value):
    raw=deepcopy(sample)
    raw["group_proof"]["frames"][0][key]=value
    with pytest.raises(NativeProofRowsError):
        native_frame_rows(raw)


def test_duplicates_and_bogus_doubleclick_rows_are_rejected(sample):
    raw=deepcopy(sample)
    raw["group_proof"]["frames"][1]["name"]="anim_castle 001"
    with pytest.raises(NativeProofRowsError,match="Doppelter"):
        native_frame_rows(raw)
    assert catalog_frame_name({"pruefung":"Nativ-Proof","gruppe":"anim_castle",
                               "frames":["anim_castle 001"]}) is None
    assert catalog_frame_name({"pruefung":"Nativ-Frame","gruppe":"../invalid",
                               "frames":["anim_castle 001"]}) is None
    assert catalog_frame_name({"pruefung":"Nativ-Frame","gruppe":"anim_castle",
                               "frames":["anim_castle 001","anim_castle 138"]}) is None


def test_summary_only_fixture_has_no_unproven_frame_rows(sample):
    sample["group_proof"].pop("frames")
    assert native_frame_rows(sample)==[]


def test_full_published_native_frame_list_matches_real_mapping_and_geometry():
    required=[
        ROOT/"work/mapping/proposals.json.gz",
        ROOT/"dist/sprite-suite-world-bc7-v2/StrongholdEuropeDE/Runtime/AssetBundles/index.json",
    ]
    if any(not path.is_file() for path in required):
        pytest.skip("Private pinned original map and published BC7 not available")
    result=audit_native_geometry(ROOT)
    rows=native_frame_rows(result)
    assert len(rows)==106
    assert len({r["frames"][0] for r in rows})==106
    assert sum("SH1DE-Quellgrafik" in r["text"] for r in rows)==95
    assert sum("Crusader-Fallback" in r["text"] for r in rows)==11
    assert next(r for r in rows if r["frames"]==["anim_castle 002"])["daten"]["groesse"]==[333,165]
