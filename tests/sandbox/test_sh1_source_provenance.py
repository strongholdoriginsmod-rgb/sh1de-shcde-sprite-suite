"""No game media: native XAML provenance and original-pixel guard tests."""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ui_sh1_hud
from ui_sh1_hud import HudError, ATLAS_NAMES

KEYS = {"UI-MasterAtlas": "UI-HUD 007", "UI-ROL": "ROL-A001",
        "UI-CandleAtlas": "Candle01"}


def dictionary_bytes(name: str) -> bytes:
    return (
        '<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">\r\n'
        f'<BitmapImage x:Key="{name}" UriSource="{name}.png"/>\r\n'
        f'<CroppedBitmap x:Key="{KEYS[name]}" Source="{{StaticResource {name}}}" '
        'SourceRect="2,3,6,5"/>\r\n'
        '</ResourceDictionary>\r\n'
    ).encode("utf8")


class MockUnityObject:
    def __init__(self, kind, name, native=None, pixels=None):
        self.type = SimpleNamespace(name=kind)
        self.name, self.native, self.pixels = name, native, pixels

    def get_raw_data(self):
        assert self.type.name == "MonoBehaviour"
        key = self.name.encode("utf8")
        # Original MonoBehaviour header: PPtr, m_Enabled, MonoScript, name
        return bytes(28) + struct.pack("<i", len(key)) + key + self.native

    def peek_name(self):
        return self.name

    def read(self):
        return SimpleNamespace(m_Name=self.name, image=self.pixels)


def fake_env():
    objects = []
    images = {}
    for name in ATLAS_NAMES:
        picture = Image.new("RGBA", (16, 16), (100, 200, 35, 255))
        images[name] = picture
        objects.append(MockUnityObject("MonoBehaviour", name, dictionary_bytes(name)))
        objects.append(MockUnityObject("Texture2D", name, pixels=picture))
    return SimpleNamespace(objects=objects), images


def export_fake(tmp_path, monkeypatch):
    import UnityPy
    env, images = fake_env()
    monkeypatch.setattr(UnityPy, "load", lambda *args: env)
    monkeypatch.setattr(ui_sh1_hud, "ROOT", tmp_path)
    original = tmp_path / "globalgamemanagers.assets"
    original.write_bytes(b"synthetic-Unity-asset-data")
    destination = tmp_path / "work" / "original-crlf"
    ui_sh1_hud.export_workspace(original, destination, False)
    return destination, env, images


def test_export_retains_exact_original_crlf_xaml(tmp_path, monkeypatch):
    destination, _env, _images = export_fake(tmp_path, monkeypatch)
    for name in ATLAS_NAMES:
        raw = (destination / "baseline" / (name + ".xaml")).read_bytes()
        assert raw == dictionary_bytes(name).rstrip(b"\r\n")
        assert b"\r\r\n" not in raw
    # Legacy imports should not disable Pillow's decompression safety.
    assert Image.MAX_IMAGE_PIXELS is not None
    checked, _ = ui_sh1_hud.check_workspace(destination)
    assert checked["checked"] == 3


def test_source_provenance_accepts_native_export(tmp_path, monkeypatch):
    from ui_sh1_unity_patch import verify_native_provenance
    workspace, env, images = export_fake(tmp_path, monkeypatch)
    assert verify_native_provenance(env, workspace, images)["xaml_dictionaries_checked"] == 3


def test_source_provenance_accepts_legacy_double_crlf(tmp_path, monkeypatch):
    from ui_sh1_unity_patch import verify_native_provenance
    workspace, env, images = export_fake(tmp_path, monkeypatch)
    for name in ATLAS_NAMES:
        xaml = workspace / "baseline" / (name + ".xaml")
        xaml.write_bytes(dictionary_bytes(name).rstrip(b"\r\n").replace(b"\n", b"\r\n"))
    assert verify_native_provenance(env, workspace, images)["legacy_xaml_accepted"] == 3


def test_forged_xaml_manifest_is_rejected(tmp_path, monkeypatch):
    from ui_sh1_unity_patch import verify_native_provenance
    workspace, env, images = export_fake(tmp_path, monkeypatch)
    xaml = workspace / "baseline" / "UI-ROL.xaml"
    xaml.write_bytes(xaml.read_bytes().replace(b"2,3,6,5", b"3,3,6,5"))
    with pytest.raises(HudError, match="Original-XAML"):
        verify_native_provenance(env, workspace, images)


def test_forged_baseline_png_is_rejected(tmp_path, monkeypatch):
    from ui_sh1_unity_patch import verify_native_provenance
    workspace, env, images = export_fake(tmp_path, monkeypatch)
    png = workspace / "baseline" / "UI-ROL.png"
    with Image.open(png) as raw:
        changed = raw.convert("RGBA")
    changed.putpixel((0, 0), (255, 0, 0, 255))
    changed.save(png)
    with pytest.raises(HudError, match="Original-PNG"):
        verify_native_provenance(env, workspace, images)


def test_missing_unity_dictionary_is_rejected(tmp_path, monkeypatch):
    from ui_sh1_unity_patch import verify_native_provenance
    workspace, env, images = export_fake(tmp_path, monkeypatch)
    env.objects = [obj for obj in env.objects if not
                   (obj.type.name == "MonoBehaviour" and obj.name == "UI-ROL")]
    with pytest.raises(HudError, match="XAML"):
        verify_native_provenance(env, workspace, images)


def test_export_rejects_duplicate_sanitized_png_names(tmp_path, monkeypatch):
    """Different Noesis XAML keys may collapse to the same Windows filename."""
    import UnityPy
    env, _images = fake_env()
    atlas = next(obj for obj in env.objects
                 if obj.type.name == "MonoBehaviour" and obj.name == "UI-MasterAtlas")
    native = atlas.native.replace(b"UI-HUD 007", b"UI/HUD")
    extra = (
        b'<CroppedBitmap x:Key="UI:HUD" Source="{StaticResource UI-MasterAtlas}" '
        b'SourceRect="10,3,6,5"/>\r\n'
    )
    atlas.native = native.replace(b"</ResourceDictionary>", extra + b"</ResourceDictionary>")
    monkeypatch.setattr(UnityPy, "load", lambda *args: env)
    monkeypatch.setattr(ui_sh1_hud, "ROOT", tmp_path)
    source = tmp_path / "globalgamemanagers.assets"
    source.write_bytes(b"synthetic source")
    dest = tmp_path / "work" / "colliding-crops"
    from ui_atlas import UiAtlasError
    with pytest.raises(UiAtlasError, match="Dateinamen kollidieren"):
        ui_sh1_hud.export_workspace(source, dest, replace=False)
    assert not dest.exists(), "No partial export should be published"
    assert source.read_bytes() == b"synthetic source"
