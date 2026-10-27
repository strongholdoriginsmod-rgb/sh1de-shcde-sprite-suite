"""SH1 HUD converter contract: three atlases, real crop rebuild, no game edits.

Fake Unity asset objects supply tiny source bitmaps; real XAML extraction,
cropping, index checks, source SHA records and transactional write code run.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ui_sh1_hud as hud


@pytest.fixture
def sh1(tmp_path, monkeypatch):
    root = tmp_path / "SH1-workspace"
    (root / "work").mkdir(parents=True)
    (root / "dist").mkdir()
    source_dir = tmp_path / "read-only-Sh1DE"
    source_dir.mkdir()
    source = source_dir / "globalgamemanagers.assets"
    source.write_bytes(b"SYNTHETIC-SH1-ASSET-DO-NOT-INSTALL")
    original = sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(hud, "ROOT", root)
    atlas_images: dict[str, Image.Image] = {}
    objects = []

    for idx, atlas in enumerate(hud.ATLAS_NAMES):
        name = atlas
        xaml = (
            '<ResourceDictionary xmlns="http://schemas.microsoft.com/'
            'winfx/2006/xaml/presentation" '
            'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
            f'<BitmapImage x:Key="Master" UriSource="{name}.png"/>'
            f'<CroppedBitmap x:Key="SH1-{idx}-One" SourceRect="1,1,4,4"/>'
            f'<CroppedBitmap x:Key="SH1-{idx}-Two" SourceRect="8,8,3,3"/>'
            '</ResourceDictionary>'
        )
        raw = (
            bytes(28) + len(name.encode()).to_bytes(4, "little")
            + name.encode() + xaml.encode()
        )
        objects.append(SimpleNamespace(
            type=SimpleNamespace(name="MonoBehaviour"),
            get_raw_data=lambda value=raw: value,
        ))
        pixels = Image.new("RGBA", (16, 16), (30 + 10 * idx, 65, 90, 255))
        atlas_images[name] = pixels
        objects.append(SimpleNamespace(
            type=SimpleNamespace(name="Texture2D"),
            peek_name=lambda value=name: value,
            read=lambda value=pixels: SimpleNamespace(image=value.copy()),
        ))

    monkeypatch.setitem(
        sys.modules, "UnityPy",
        SimpleNamespace(load=lambda path: SimpleNamespace(objects=objects)),
    )
    from ui_sh1_dict import _monobehaviour_name
    assert all(
        _monobehaviour_name(obj.get_raw_data()) == name
        for obj, name in zip(objects[::2], hud.ATLAS_NAMES)
    )
    return root, source, original, atlas_images


def _export(sh1):
    root, source, _, _ = sh1
    export = root / "work/sh1-hud-editierbar"
    report = hud.export_workspace(source, export, replace=False)
    return export, report


def test_sh1_all_atlases_roundtrip_edited_pixels_and_true_source_hash(sh1):
    root, source, source_sha, originals = sh1
    export, report = _export(sh1)
    assert report["editable_images"] == 6
    assert report["source_globalgamemanagers_sha256"] == source_sha
    result, outputs = hud.check_workspace(export)
    assert result["checked"] == 6
    assert result["changed"] == []
    assert outputs == []

    edited = export / "UI-MasterAtlas/SH1-0-One.png"
    with Image.open(edited) as image:
        assert image.size == (4, 4)
    Image.new("RGBA", (4, 4), (218, 40, 20, 255)).save(edited)
    state, _ = hud.check_workspace(export)
    assert state["checked"] == 6 and len(state["changed"]) == 1
    assert state["changed"][0]["key"] == "SH1-0-One"

    output = root / "dist/sh1-hud-editierte-atlanten"
    hud.build_workspace(export, output, replace=False)
    manifest = json.loads(
        (output / "sh1_hud_build_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["source_globalgamemanagers_sha256"] == source_sha
    assert manifest["validated_named_crops"] == 6
    assert len(manifest["edited_crops"]) == 1
    assert len(manifest["sheets"]) == 3
    with Image.open(output / "UI-MasterAtlas.png") as image:
        assert image.size == (16, 16)
        assert image.getpixel((1, 1)) == (218, 40, 20, 255)
        assert image.getpixel((6, 6)) == (30, 65, 90, 255)
    for name in hud.ATLAS_NAMES:
        assert originals[name].getpixel((1, 1)) == (
            30 + 10 * hud.ATLAS_NAMES.index(name), 65, 90, 255
        )
    assert sha256(source.read_bytes()).hexdigest() == source_sha
    assert not list(root.rglob("*.sh1-hud-sicherung"))


def test_sh1_bad_crop_is_reported_before_existing_atlas_output_replaced(sh1):
    root, source, source_sha, _ = sh1
    export, _ = _export(sh1)
    output = root / "dist/sh1-hud-editierte-atlanten"
    hud.build_workspace(export, output, replace=False)
    hashes = {
        file.name: sha256(file.read_bytes()).hexdigest()
        for file in output.iterdir() if file.is_file()
    }
    Image.new("RGBA", (5, 4), (1, 2, 3, 255)).save(
        export / "UI-MasterAtlas/SH1-0-One.png"
    )
    with pytest.raises(hud.HudError, match="statt"):
        hud.build_workspace(export, output, replace=True)
    assert {
        file.name: sha256(file.read_bytes()).hexdigest()
        for file in output.iterdir() if file.is_file()
    } == hashes
    assert not list(root.rglob("*.sh1-hud-sicherung"))
    assert sha256(source.read_bytes()).hexdigest() == source_sha


def test_sh1_rejects_cross_game_index_and_untrusted_crop_paths(sh1):
    root, source, source_sha, _ = sh1
    export, _ = _export(sh1)
    index_path = export / "index.json"
    untouched = index_path.read_bytes()
    doc = json.loads(untouched)
    doc["target_build_id"] = "crusader-ui-not-sh1"
    index_path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(hud.HudError, match="Kein Stronghold"):
        hud.check_workspace(export)
    doc = json.loads(untouched)
    doc["atlases"][0]["crops"][0]["file"] = "../outside.png"
    index_path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises((hud.HudError, ValueError), match="manipuliert|Dateiname"):
        hud.check_workspace(export)
    assert sha256(source.read_bytes()).hexdigest() == source_sha


def test_sh1_disallows_export_to_other_project_trees_and_preserves_game(sh1):
    root, source, source_sha, _ = sh1
    with pytest.raises(hud.HudError, match="UNTER"):
        hud.export_workspace(
            source, root.parent / "unauthorized", replace=True
        )
    assert sha256(source.read_bytes()).hexdigest() == source_sha
    assert not (root.parent / "unauthorized").exists()
