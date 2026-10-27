"""Headless original-tool *functional* contracts, not merely matching labels.

The September SU/projekt source is a reference, NOT proven June baseline.
All tests are read-only: independent source code is parsed/loaded; any
historic/new build subprocess is intercepted before execution.
"""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import hashlib,runpy,subprocess,sys
import pytest
from PIL import Image

NEW=Path(__file__).resolve().parents[2]
OLD=Path("E:/SU/projekt")
sys.path[:0]=[str(NEW/"tools"),str(NEW/"src")]


def old_and_new(name:str):
    if not (OLD/"tools"/name).is_file():
        pytest.skip("Historical SU/projekt original unavailable")
    return (
        runpy.run_path(str(OLD/"tools"/name),run_name="original_readonly"),
        runpy.run_path(str(NEW/"tools"/name),run_name="current_readonly"),
    )


@pytest.mark.parametrize("name",[
    "sandkasten.py","sprites.py","tile_objects.py","ui_atlas.py",
    "asset_katalog.py","editor_bruecke.py","groups.py","pin_digests.py",
    "se_atlas.py",
])
def test_original_tool_is_byte_preserved(name):
    a=OLD/"tools"/name
    if not a.is_file():
        pytest.skip("Historical original not available")
    b=NEW/"tools"/name
    assert hashlib.sha256(a.read_bytes()).digest()==hashlib.sha256(
        b.read_bytes()
    ).digest()


def test_independent_image_fit_matches_historical_pixels_without_io():
    old,new=old_and_new("asset_katalog.py")
    source=Image.new("RGBA",(17,23))
    source.putdata([
        (x*13%255,y*23%255,(x*3+y*9)%255,255 if x%3 else 0)
        for y in range(23) for x in range(17)
    ])
    digest=hashlib.sha256(source.tobytes()).hexdigest()
    for mode in ("fusspunkt","exakt","oben-links","oben-rechts",
                 "unten-links","unten-rechts","mitte","skalieren"):
        for flip in (False,True):
            for shift in ((0,0),(-5,2),(2,-4)):
                args=(source,(8.5,20.5),(31,35),(16.,24.))
                opts={"mode":mode,"flip":flip,"dx":shift[0],"dy":shift[1]}
                a,aloss=old["fit_image"](*args,**opts)
                b,bloss=new["fit_image"](*args,**opts)
                assert (a.tobytes(),aloss)==(b.tobytes(),bloss)
                assert 0 <= bloss <= 17*23
    assert hashlib.sha256(source.tobytes()).hexdigest()==digest


def test_canonical_sprite_geometry_and_group_tables_match_original():
    for rel in (
        "config/asset-kategorien.json",
        "config/kachelobjekt-raster.json",
        "config/tile-object-presets.json",
        "config/ui-textures-bc7-v1.json",
        "profiles/vertical-slice.json",
        "profiles/sprite-suite-world-bc7-v2.json",
    ):
        original=OLD/rel
        if not original.is_file():pytest.skip("Historical config absent")
        current=NEW/rel
        assert original.read_bytes()==current.read_bytes(),rel


@pytest.mark.parametrize("strict,expected_original,expected_current",[
    (False,0,23),
    (True,23,23),
])
def test_historical_build_sequence_retained_but_failed_validation_blocks_release(
    strict,expected_original,expected_current,monkeypatch
):
    original,current=old_and_new("suite_workflow.py")
    steps=[]
    def no_real_build(cmd,**kwargs):
        # Intercept EVERY subprocess so no Unity/SDK/game/installer is called.
        steps.append((list(cmd),kwargs["cwd"]))
        return SimpleNamespace(returncode=(0 if len(steps)%2==1 else 23))
    monkeypatch.setattr(subprocess,"run",no_real_build)
    # The current build now performs a separate exact-version target gate
    # *before* invoking either subprocess. In this isolated pipeline-contract
    # test the version gate is explicitly certified by a fake read-only pin.
    import target_selection_guard
    monkeypatch.setattr(target_selection_guard,"verify_active",
        lambda *,root:("test-verified",SimpleNamespace(
            build_id="local-shcde-2.80-unity-2021.3.45f2",files_checked=5)))
    exits=[]
    captured=[]
    for reference,root in ((original,OLD),(current,NEW)):
        steps.clear()
        arguments=["--streng"] if strict else []
        arguments.extend(["build","--profile-id","vertical-slice"])
        exit_code=reference["main"](arguments)
        exits.append(exit_code)
        captured.append([[str(part).replace(str(root),"<ROOT>")
                          for part in cmd[1:]] for cmd,cwd in steps])
    assert exits==[expected_original,expected_current]
    assert captured[0]==captured[1]
    assert len(captured[0])==2


def test_current_build_mapping_does_not_claim_historical_27_target():
    from json import loads
    target_config=NEW/"config/supported-builds.json"
    ids=[x["id"] for x in loads(target_config.read_text(
        encoding="utf8"
    ))["target_builds"]]
    assert "local-shcde-2.7-unity-2021.3.45f2" in ids
    assert "local-shcde-2.80-unity-2021.3.45f2" in ids
    # Exact per-game file SHA checking is a distinct, read-only IO QA.
    # Do not reuse a historic 2.7 mapping identity as a 2.80 proof.
