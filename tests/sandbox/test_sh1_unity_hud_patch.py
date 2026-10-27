"""No game files: tests for source-pinned Unity Texture2D bytepatch candidates."""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image
from UnityPy.export import Texture2DConverter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from ui_sh1_hud import HudError
from ui_sh1_unity_patch import (
    BytePatch, _validate_and_apply, bc7_patches, diff_blocks, rgba_patches,
)


def source_and_copy(tmp_path, data: bytes):
    a = tmp_path / "original.bin"
    b = tmp_path / "candidate.bin"
    a.write_bytes(data)
    shutil.copy2(a, b)
    return a, b


def test_no_unnecessary_bc7_blocks_from_alpha_only():
    old = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    new = old.copy()
    new.putpixel((5, 6), (0, 0, 0, 255))
    assert diff_blocks(old, new, [{"rect": [0, 0, 8, 8]}]) == {(1, 1)}


def test_bytepatch_rejects_bad_sizes_and_positions():
    with pytest.raises(HudError):
        BytePatch(-1, b"\x00", b"\x01", "fake")
    with pytest.raises(HudError):
        BytePatch(0, b"\x00\x01", b"\x01", "fake")
    with pytest.raises(HudError):
        BytePatch(0, b"", b"", "fake")


def test_rgba32_exact_unity_bottom_up_rows(tmp_path):
    source_image = Image.new("RGBA", (8, 8), (13, 29, 43, 255))
    desired = source_image.copy()
    desired.putpixel((2, 3), (255, 0, 120, 255))
    desired.putpixel((7, 7), (12, 50, 220, 0))
    encoded, fmt = Texture2DConverter.image_to_texture2d(source_image, 4)
    assert int(fmt) == 4
    prefix, suffix = b"prefix-test-aaaaa", b"suffix-test-bbbbb"
    original, output = source_and_copy(tmp_path, prefix + encoded + suffix)
    edits = rgba_patches(
        source_image, desired,
        [{"rect": [2, 3, 1, 1]}, {"rect": [7, 7, 1, 1]}],
        start=len(prefix), texture="UI-MasterAtlas",
    )
    assert len(edits) == 2
    assert [len(patch.after) for patch in edits] == [4, 4]
    _validate_and_apply(original, output, edits)
    after = output.read_bytes()
    assert after[:len(prefix)] == prefix
    assert after[-len(suffix):] == suffix
    changed = after[len(prefix):-len(suffix)]
    expected, _ = Texture2DConverter.image_to_texture2d(desired, 4)
    assert changed == expected
    assert original.read_bytes() == prefix + encoded + suffix


def test_unchanged_candidate_bitwise_copy(tmp_path):
    a, b = source_and_copy(tmp_path, bytes(range(256)) * 100)
    _validate_and_apply(a, b, [])
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()


def test_patch_outside_original_rejected(tmp_path):
    a, b = source_and_copy(tmp_path, b"abcdefgh")
    with pytest.raises(HudError, match="überlaufender"):
        _validate_and_apply(a, b, [BytePatch(7, b"zz", b"12", "test")])


def test_overlapping_bytepatches_rejected(tmp_path):
    a, b = source_and_copy(tmp_path, b"abcdefgh")
    with pytest.raises(HudError, match="Überlappender"):
        _validate_and_apply(a, b, [
            BytePatch(2, b"cdef", b"1234", "test"),
            BytePatch(4, b"ef", b"67", "test"),
        ])


def test_source_byte_mismatch_rejected(tmp_path):
    a, b = source_and_copy(tmp_path, b"abcdefgh")
    with pytest.raises(HudError, match="Basisdaten"):
        _validate_and_apply(a, b, [BytePatch(2, b"XX", b"12", "test")])


def test_only_dirty_bc7_4x4_block_written(tmp_path):
    base = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    desired = base.copy()
    desired.putpixel((5, 6), (244, 73, 37, 255))
    encoded, fmt = Texture2DConverter.image_to_texture2d(base, 25)
    assert int(fmt) == 25 and len(encoded) == 64
    prefix, suffix = b"bc7-header-abc", b"bc7-tail-def"
    original, candidate = source_and_copy(tmp_path, prefix + encoded + suffix)
    patches, blocks = bc7_patches(
        base, desired, [{"rect": [5, 6, 1, 1]}],
        start=len(prefix), texture_data=encoded, texture="UI-ROL", max_blocks=20
    )
    assert blocks == [(1, 1)] and len(patches) == 1
    assert len(patches[0].after) == 16
    _validate_and_apply(original, candidate, patches)
    assert candidate.read_bytes() != original.read_bytes()
    actual = candidate.read_bytes()[len(prefix):-len(suffix)]
    assert len(actual) == len(encoded)
    changed = [i for i in range(4) if actual[i*16:(i+1)*16] != encoded[i*16:(i+1)*16]]
    assert changed == [1], "block row order must be bottom-up"


def test_bc7_limits_fail_closed():
    base = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    wanted = base.copy()
    for x, y in ((0, 0), (7, 7)):
        wanted.putpixel((x, y), (100, 80, 40, 255))
    fake_bc7 = b"\x00"*64
    with pytest.raises(HudError, match="Sicherheitsgrenze"):
        bc7_patches(
            base, wanted, [{"rect": [0, 0, 8, 8]}],
            start=0, texture_data=fake_bc7, texture="UI-CandleAtlas",
            max_blocks=1,
        )


def test_asset_patch_output_never_can_overwrite_external_file(tmp_path):
    from ui_sh1_hud import ensure_under
    assert ROOT.joinpath("dist").is_dir() or ROOT.joinpath("dist").is_dir() is False
    with pytest.raises(HudError):
        ensure_under(tmp_path / "globalgamemanagers.assets", "dist")


def test_bc7_gross_visible_color_loss_rejected(tmp_path, monkeypatch):
    """Decoded candidate must not silently accept a severely distorted pixel."""
    import UnityPy
    import ui_sh1_unity_patch as patcher
    from types import SimpleNamespace

    class Texture:
        def __init__(self, name, img):
            self.type = SimpleNamespace(name="Texture2D")
            self._name, self._img = name, img
        def peek_name(self):
            return self._name
        def read(self):
            return SimpleNamespace(m_Name=self._name, image=self._img)

    names = tuple(patcher.FORMAT_AND_SHAPE)
    source = {n: Image.new("RGBA", (8, 8), (0, 0, 0, 255)) for n in names}
    images = {n: img.copy() for n, img in source.items()}
    target_color = (250, 245, 240, 255)
    images["UI-ROL"].putpixel((1, 1), target_color)
    badly_reencoded = Image.new("RGBA", (8, 8), (0, 255, 0, 255))
    found = [Texture(n, badly_reencoded if n == "UI-ROL" else source[n])
             for n in names]
    monkeypatch.setattr(UnityPy, "load", lambda *_: SimpleNamespace(objects=found))
    monkeypatch.setattr(patcher, "texture_offset", lambda *_: (0, b""))
    file = tmp_path / "fake-asset.bin"
    file.write_bytes(b"fake" * 64)
    with pytest.raises(HudError, match="BC7.*sichtbare"):
        patcher._validate_reopened_asset(
            file, {"UI-ROL": [(0, 0)]}, images,
            {"UI-ROL": source["UI-ROL"]},
            max_visual_error=64,
        )


def test_bc7_visual_metric_ignores_hidden_transparent_rgb(tmp_path, monkeypatch):
    """Transparent RGB divergence is not a visible premultiplied-alpha error."""
    import UnityPy
    import ui_sh1_unity_patch as patcher
    from types import SimpleNamespace

    class Fake:
        type = SimpleNamespace(name="Texture2D")
        def __init__(self, name):
            self._name = name
        def peek_name(self):
            return self._name
        def read(self):
            color = (12, 244, 90, 0) if self._name == "UI-ROL" else (0, 0, 0, 0)
            return SimpleNamespace(image=Image.new("RGBA", (8, 8), color))

    monkeypatch.setattr(UnityPy, "load", lambda *_: SimpleNamespace(
        objects=[Fake(n) for n in patcher.FORMAT_AND_SHAPE]
    ))
    monkeypatch.setattr(patcher, "texture_offset", lambda *_: (0, b""))
    original = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    edited = original.copy()
    edited.putpixel((0, 0), (255, 13, 7, 0))
    file = tmp_path / "fake-asset.bin"
    file.write_bytes(b"fake")
    report = patcher._validate_reopened_asset(
        file, {"UI-ROL": [(0, 0)]},
        {"UI-ROL": edited}, {"UI-ROL": original},
        max_visual_error=10,
    )
    assert report["UI-ROL"]["maximum_visible_channel_error"] == 0
    assert report["UI-ROL"]["maximum_channel_error"] > 10


def test_unity_candidate_refuses_replacing_its_own_source(tmp_path, monkeypatch):
    """A user-supplied --source inside --out must never be deleted by --replace."""
    import ui_sh1_hud
    import ui_sh1_unity_patch
    monkeypatch.setattr(ui_sh1_hud, "ROOT", tmp_path)
    monkeypatch.setattr(ui_sh1_unity_patch, "ensure_under",
                        ui_sh1_hud.ensure_under)
    candidate=tmp_path/"dist"/"candidate-folder"
    candidate.mkdir(parents=True)
    original=candidate/"globalgamemanagers.assets"
    original.write_bytes(b"precious owner source file")
    with pytest.raises(HudError, match="Quelle|überschneid"):
        ui_sh1_unity_patch.create_candidate(
            source=original,
            workspace=tmp_path/"work"/"dummy",
            target_folder=candidate,
            replace=True,
        )
    assert original.read_bytes()==b"precious owner source file"


def test_build_refuses_nested_output_containing_existing_workdir(tmp_path,monkeypatch):
    """Untrusted source in the prospective backup subtree must fail before loading."""
    import ui_sh1_unity_patch
    import ui_sh1_hud
    monkeypatch.setattr(ui_sh1_hud,"ROOT",tmp_path)
    monkeypatch.setattr(ui_sh1_unity_patch,"ensure_under",ui_sh1_hud.ensure_under)
    destination=tmp_path/"dist"/"new-output"
    workspace=destination/"project-to-preserve"
    workspace.mkdir(parents=True)
    original=workspace/"index.json"
    original.write_text("user source must not be lost",encoding="utf8")
    valid_source=tmp_path/"globalgamemanagers.assets"
    valid_source.write_bytes(b"example source")
    with pytest.raises(HudError,match="Quelle|überschneid"):
        ui_sh1_unity_patch.create_candidate(
            source=valid_source,
            workspace=workspace,
            target_folder=destination,
            replace=True,
        )
    assert original.read_text(encoding="utf8")=="user source must not be lost"
