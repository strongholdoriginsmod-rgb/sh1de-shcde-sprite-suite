"""Deep, effect-based QA for the additional specialty demo categories."""
from pathlib import Path
import json
import sys
from zipfile import ZipFile

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_workspace as work
import hud_menu_layout as layout
import se_asset_package as package
from suite_demo_engine import DemoSession, MODULES


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    suite=tmp_path/"suite";(suite/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",suite/"work")
    monkeypatch.setattr(layout,"WORK",suite/"work")
    monkeypatch.setattr(package,"ROOT",suite)
    monkeypatch.setattr(package,"WORK",suite/"work")
    monkeypatch.setattr(package,"OUT",suite/"work"/"se-asset-mods")
    return suite


@pytest.mark.parametrize("key",[
    "stone","boar","historic_palette","team_mask","sandbox_scene",
    "button_motif","native_tiles","bc7","capture_diff","extra_atlas",
])
def test_every_specialist_performs_actual_modification_and_keeps_workdir(isolated,key):
    session=DemoSession.start(key)
    seen=0
    while not session.complete:
        proof=session.execute_next()
        assert proof["function"]
        assert proof["outputs"]
        seen+=1
    assert seen==len(session.module.steps)
    assert session.verify_receipts()["valid"]
    assert (session.root/"demo-protokoll.json").is_file()
    assert all(Path(o["path"]).is_file() for x in session.receipts for o in x["outputs"])
    for path in session.root.rglob("*"):
        assert path.resolve().is_relative_to(isolated/"work")
    assert not (isolated/"BepInEx").exists()


def test_actual_extra_atlas_geometry_and_xaml_crop_keys(isolated):
    s=DemoSession.start("extra_atlas")
    while not s.complete:s.execute_next()
    page=s.project/"Override/Assets/GUI/Sprites/DemoAtlas-001.png"
    xaml=s.project/"Override/Assets/GUI/Sprites/DemoAtlas-001.xaml"
    main=s.project/"Override/Assets/GUI/XAMLResources/ApplicationResources.xaml"
    with Image.open(page) as image:
        assert image.size==(256,256)
        assert image.getpixel((5,5))[3]>0
    assert b"Demonstration.Icon0" in xaml.read_bytes()
    assert b"DemoAtlas-001.xaml" in main.read_bytes()
    last=next(Path(a["path"]) for a in s.receipts[-1]["outputs"])
    with ZipFile(last) as z:
        assert z.testzip() is None
        assert any(n.endswith("DemoAtlas-001.xaml") for n in z.namelist())
        assert any(n.endswith("DemoAtlas-001.png") for n in z.namelist())


def test_sandbox_scene_renders_changed_native_projection(isolated):
    s=DemoSession.start("sandbox_scene")
    while not s.complete:s.execute_next()
    a=s.samples/"SandboxFrame0.png";b=s.samples/"SandboxFrame1.png"
    with Image.open(a) as image:
        assert image.width>400
    assert a.read_bytes()!=b.read_bytes()
    assert s.verify_receipts()["valid"]


def test_bc7_encodes_actual_block_data_not_just_png_copy(isolated):
    s=DemoSession.start("bc7")
    while not s.complete:s.execute_next()
    encoded=s.samples/"BC7Data.bin"
    assert encoded.is_file()
    assert encoded.stat().st_size==4096  # 64x64, 16 bytes per 4x4 BC7 block
    before=Image.open(s.samples/"OriginalTexture.png").convert("RGBA")
    after=Image.open(s.samples/"BC7Roundtrip.png").convert("RGBA")
    assert before.size==after.size
    assert before.tobytes()!=after.tobytes()


def test_noesis_capture_diff_does_not_attest_native_renderer(isolated):
    s=DemoSession.start("capture_diff")
    while not s.complete:s.execute_next()
    result=json.loads((s.root/"pixel-exact-diff"/"comparison.json").read_text("utf8"))
    assert result["changed_pixels"]>0
    assert result["pixel_identical"] is False
    assert result["native_noesis_renderer_invoked"] is False
    assert result["game_render_parity_attested"] is False
    control=json.loads((s.root/"identical-reference-check"/"comparison.json").read_text("utf8"))
    assert control["pixel_identical"] is True
    assert s.verify_receipts()["valid"]


def test_custom_original_capture_png_is_copied_never_modified(isolated,tmp_path):
    source=tmp_path/"game-screenshot.png"
    Image.new("RGBA",(384,216),(35,60,120,255)).save(source)
    before=source.read_bytes()
    s=DemoSession.start("capture_diff",source=source)
    while not s.complete:s.execute_next()
    assert source.read_bytes()==before
    assert (s.samples/"Original-Screenshot.png").is_file()
    assert s.verify_receipts()["valid"]



@pytest.mark.skipif(sys.platform!="win32",reason="Windows native C# compiler required")
def test_native_bepinex_menu_demo_compiles_offline_and_never_installs(isolated):
    from origins_native_menu_compiler import CSC
    game=Path(r"D:\Games\Stronghold Crusader Definitive Edition")
    if not game.is_dir() or not CSC.is_file():
        pytest.skip("Installed game or compiler not present")
    source=game/"Stronghold Crusader Definitive Edition_Data"/"Managed"/"Assembly-CSharp.dll"
    original=source.read_bytes()
    demo=DemoSession.start("native_menu",source=game)
    while not demo.complete:
        demo.execute_next()
    report=json.loads((demo.project.parent/".origins-native-menu-candidates"/
                       "demo-native-menu"/"qa-report.json").read_text("utf8"))
    assert report["compiled_candidate_metadata_attested"] is True
    assert all(report["compiled_candidate_metadata_signatures"].values())
    assert report["native_game_hook_registered"] is False
    assert report["installable_mod_produced"] is False
    assert demo.verify_receipts()["valid"] is True
    assert source.read_bytes()==original
    assert not (demo.project/"BepInEx").exists()
