"""Standalone atlas contracts, using synthetic owned PNG/XAML fixtures only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import zlib

from PIL import Image
import pytest

from ui_atlas_workspace import AtlasProject, AtlasWorkspaceError, main, preview_png


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_pair(tmp_path, *, name="atlas", size=(8, 8), rect="1,2,3,2", extra=""):
    png = tmp_path / f"{name}.png"
    image = Image.new("RGBA", size, (13, 47, 91, 0))
    image.putpixel((0, 0), (121, 31, 211, 255))
    image.save(png)
    image.close()
    xaml = tmp_path / f"{name}.xaml"
    xaml.write_text(
        '<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        f'<BitmapImage x:Key="Sheet" UriSource="{png.name}"/>'
        f'<CroppedBitmap x:Key="icon ü" Source="{{StaticResource Sheet}}" SourceRect="{rect}"/>'
        f'{extra}</ResourceDictionary>', encoding="utf-8")
    return png, xaml


def make_project(tmp_path, **kwargs):
    png, xaml = fixture_pair(tmp_path, **kwargs)
    return AtlasProject.create(png, xaml, tmp_path / "workspace"), png, xaml


def replacement(tmp_path, *, size=(3, 2), color=(204, 11, 19, 0)):
    path = tmp_path / "replacement ü & $(nothing).png"
    with Image.new("RGBA", size, color) as image:
        image.putpixel((0, 0), (20, 230, 90, 255))
        image.save(path)
    return path


def test_exact_pixels_hidden_rgb_outside_rect_and_originals(tmp_path):
    project, png, xaml = make_project(tmp_path)
    before = (digest(png), digest(xaml))
    source = replacement(tmp_path)
    revision = project.info()["revision"]
    project.replace("icon ü", source, expected_revision=revision)
    with project.preview("icon ü") as crop, Image.open(source) as expected:
        assert crop.mode == "RGBA"
        assert crop.tobytes() == expected.tobytes()
        assert crop.getpixel((2, 1)) == (204, 11, 19, 0)
    output = tmp_path / "rebuilt.png"
    receipt = project.export_png(output)
    assert receipt["sha256"] == digest(output)
    with Image.open(png) as original, Image.open(output) as result, Image.open(source) as donor:
        for y in range(8):
            for x in range(8):
                assert result.getpixel((x, y)) == (donor.getpixel((x - 1, y - 2)) if 1 <= x < 4 and 2 <= y < 4 else original.getpixel((x, y)))
    assert (digest(png), digest(xaml)) == before
    assert project.info()["atlas_key"] == "Sheet"
    assert project.info()["sheet"] == png.name


def test_persistent_undo_redo_restore_branch_and_original_preview(tmp_path):
    project, _, _ = make_project(tmp_path)
    source = replacement(tmp_path)
    with project.original_preview("icon ü") as original:
        original_bytes = original.tobytes()
    project.replace("icon ü", source)
    reopened = AtlasProject.open(project.workspace)
    assert reopened.info()["can_undo"]
    reopened.undo()
    with reopened.preview("icon ü") as image:
        assert image.tobytes() == original_bytes
    reopened = AtlasProject.open(project.workspace)
    assert reopened.info()["can_redo"]
    reopened.redo()
    with reopened.preview("icon ü") as image:
        edited = image.tobytes()
    reopened.restore("icon ü")
    with reopened.preview("icon ü") as image:
        assert image.tobytes() == original_bytes
    reopened.undo()
    with reopened.preview("icon ü") as image:
        assert image.tobytes() == edited
    reopened.replace("icon ü", source)
    with pytest.raises(AtlasWorkspaceError, match="No history") as caught:
        reopened.redo()
    assert caught.value.code == "no_redo"


@pytest.mark.parametrize("fit", ["contain", "stretch"])
def test_explicit_nearest_fit_and_exact_size_rejection(tmp_path, fit):
    project, _, _ = make_project(tmp_path)
    source = replacement(tmp_path, size=(1, 1))
    with pytest.raises(AtlasWorkspaceError) as caught:
        project.replace("icon ü", source)
    assert caught.value.code == "size_mismatch"
    assert project.info()["cursor"] == 0
    project.replace("icon ü", source, fit)
    with project.preview("icon ü") as image:
        assert image.size == (3, 2)
        assert image.getpixel((0, 0)) == (20, 230, 90, 255)
        assert image.getpixel((2, 1)) == ((0, 0, 0, 0) if fit == "contain" else (20, 230, 90, 255))


def test_alias_and_overlap_last_applied_restore_and_undo(tmp_path):
    extra = '<CroppedBitmap x:Key="alias" Source="{StaticResource Sheet}" SourceRect="1,2,3,2"/>'
    extra += '<CroppedBitmap x:Key="overlap" Source="{StaticResource Sheet}" SourceRect="3,2,2,2"/>'
    project, _, _ = make_project(tmp_path, extra=extra)
    project.replace("icon ü", replacement(tmp_path))
    with project.preview("alias") as image:
        assert image.getpixel((2, 0)) == (204, 11, 19, 0)
    project.restore("overlap")
    with project.preview("alias") as image:
        assert image.getpixel((2, 0)) == (13, 47, 91, 0)
        assert image.getpixel((1, 0)) == (204, 11, 19, 0)
    project.undo()
    with project.preview("overlap") as image:
        assert image.getpixel((0, 0)) == (204, 11, 19, 0)


def test_transfer_copies_current_donor_and_provenance(tmp_path):
    target_dir, donor_dir = tmp_path / "target", tmp_path / "donor"
    target_dir.mkdir()
    donor_dir.mkdir()
    target, _, _ = make_project(target_dir)
    donor, _, _ = make_project(donor_dir)
    source = replacement(donor_dir)
    donor.replace("icon ü", source)
    target.replace_from("icon ü", donor.workspace, "icon ü")
    donor.restore("icon ü")
    with target.preview("icon ü") as image, Image.open(source) as expected:
        assert image.tobytes() == expected.tobytes()
    manifest = json.loads((target.workspace / "atlas-project.json").read_text(encoding="utf-8"))
    provenance = manifest["history"][0]["provenance"]
    assert provenance["kind"] == "atlas" and provenance["key"] == "icon ü"
    assert provenance["rect"]["width"] == 3
    assert len(provenance["rgba_sha256"]) == 64


def test_immutable_snapshot_external_change_warning_and_owned_hash_failure(tmp_path):
    project, png, _ = make_project(tmp_path)
    with Image.new("RGBA", (8, 8), (255, 0, 0, 255)) as image:
        image.save(png)
    assert {item["code"] for item in project.info()["warnings"]} == {"source_changed"}
    with project.preview("icon ü") as image:
        assert image.getpixel((0, 0)) == (13, 47, 91, 0)
    (project.workspace / "source/atlas.png").write_bytes(png.read_bytes())
    with pytest.raises(AtlasWorkspaceError) as caught:
        AtlasProject.open(project.workspace)
    assert caught.value.code == "integrity_error"


def test_stale_handles_and_explicit_revision_reject_without_edit(tmp_path):
    first, _, _ = make_project(tmp_path)
    second = AtlasProject.open(first.workspace)
    old_revision = first.info()["revision"]
    source = replacement(tmp_path)
    first.replace("icon ü", source)
    with pytest.raises(AtlasWorkspaceError) as caught:
        second.replace("icon ü", source)
    assert caught.value.code == "stale_workspace"
    with pytest.raises(AtlasWorkspaceError) as caught:
        first.restore("icon ü", expected_revision=old_revision)
    assert caught.value.code == "stale_revision"
    assert AtlasProject.open(first.workspace).info()["cursor"] == 1


@pytest.mark.parametrize("rect", ["-1,0,2,2", "0,0,0,2", "7,7,2,2", "0,0,1.5,2", "0,0,1"])
def test_invalid_rectangles_rejected_before_workspace_creation(tmp_path, rect):
    png, xaml = fixture_pair(tmp_path, rect=rect)
    with pytest.raises(AtlasWorkspaceError) as caught:
        AtlasProject.create(png, xaml, tmp_path / "new")
    assert caught.value.code == "invalid_rect"
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("payload", [
    b'<!DOCTYPE root [<!ENTITY x "owned">]><root/>',
    '<!DOCTYPE root [<!ENTITY x "owned">]><root/>'.encode("utf-16"),
    b'<ResourceDictionary><not-closed>',
])
def test_unsafe_or_invalid_xml_never_creates_workspace(tmp_path, payload):
    png, xaml = fixture_pair(tmp_path)
    xaml.write_bytes(payload)
    with pytest.raises(AtlasWorkspaceError) as caught:
        AtlasProject.create(png, xaml, tmp_path / "new")
    assert caught.value.code in {"unsafe_xml", "invalid_xml"}
    assert not (tmp_path / "new").exists()


def test_multi_atlas_select_binding_not_first_resource_and_diagnose_unprovided(tmp_path):
    png, xaml = fixture_pair(tmp_path)
    text = xaml.read_text(encoding="utf-8")
    text = text.replace('<BitmapImage x:Key="Sheet"', '<BitmapImage x:Key="Other" UriSource="other.png"/><CroppedBitmap x:Key="notSelected" Source="{StaticResource Other}" SourceRect="0,0,50,50"/><BitmapImage x:Key="Sheet"')
    xaml.write_text(text, encoding="utf-8")
    project = AtlasProject.create(png, xaml, tmp_path / "workspace")
    assert [entry["key"] for entry in project.entries] == ["icon ü"]
    assert project.info()["warnings"][0]["code"] == "unprovided_atlas_source"
    result = project.export_pair(tmp_path / "published")
    assert Path(result["xaml"]).read_bytes() == xaml.read_bytes()
    assert not (tmp_path / "published/other.png").exists()
    assert result["warnings"]


def test_multi_atlas_ambiguity_requires_explicit_atlas_key(tmp_path):
    png, xaml = fixture_pair(tmp_path, extra='<BitmapImage x:Key="AliasSheet" UriSource="atlas.png"/>')
    with pytest.raises(AtlasWorkspaceError) as caught:
        AtlasProject.create(png, xaml, tmp_path / "ambiguous")
    assert caught.value.code == "atlas_selection"
    project = AtlasProject.create(png, xaml, tmp_path / "selected", atlas_key="Sheet")
    assert project.info()["atlas_key"] == "Sheet"


@pytest.mark.parametrize("uri", ["https://example.invalid/atlas.png", "file:///secret.png", "//host/atlas.png"])
def test_remote_uri_refused_without_fetch(tmp_path, uri):
    png, xaml = fixture_pair(tmp_path)
    xaml.write_text(xaml.read_text(encoding="utf-8").replace('UriSource="atlas.png"', f'UriSource="{uri}"'), encoding="utf-8")
    with pytest.raises(AtlasWorkspaceError) as caught:
        AtlasProject.create(png, xaml, tmp_path / "workspace")
    assert caught.value.code == "unsafe_xml"


def test_keys_are_labels_not_output_paths_and_manifest_path_traversal_refused(tmp_path):
    project, _, _ = make_project(tmp_path, extra='<CroppedBitmap x:Key="../odd:name" Source="{StaticResource Sheet}" SourceRect="0,0,1,1"/>')
    assert project.preview("../odd:name").size == (1, 1)
    project.replace("../odd:name", replacement(tmp_path, size=(1, 1)))
    manifest_path = project.workspace / "atlas-project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["history"][0]["file"] = "../outside.png"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AtlasWorkspaceError) as caught:
        AtlasProject.open(project.workspace)
    assert caught.value.code == "unsafe_path"


def test_exports_no_overwrite_pair_receipt_and_workspace_source_preservation(tmp_path):
    project, png, xaml = make_project(tmp_path)
    project.replace("icon ü", replacement(tmp_path))
    output = tmp_path / "icon.png"
    project.export_crop("icon ü", output)
    old_digest = digest(output)
    with pytest.raises(AtlasWorkspaceError) as caught:
        project.export_crop("icon ü", output)
    assert caught.value.code == "already_exists" and digest(output) == old_digest
    with pytest.raises(AtlasWorkspaceError):
        project.export_png(project.workspace / "source/atlas.png")
    exports = project.workspace / "exports"
    exports.mkdir()
    result = project.export_pair(exports / "v1")
    assert Path(result["xaml"]).read_bytes() == xaml.read_bytes()
    receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))
    assert result["receipt_sha256"] == digest(Path(result["receipt"]))
    assert receipt["png"]["sha256"] == digest(Path(result["png"]))
    assert receipt["xaml"]["sha256"] == digest(xaml)
    assert receipt["sources"]["png"]["sha256"] == digest(png)
    with pytest.raises(AtlasWorkspaceError):
        project.export_pair(exports / "v1")


def test_cancel_before_publication_leaves_state_and_export_unpublished(tmp_path):
    project, _, _ = make_project(tmp_path)
    before = (project.workspace / "atlas-project.json").read_bytes()
    source = replacement(tmp_path)
    calls = 0

    def cancel_late():
        nonlocal calls
        calls += 1
        return calls >= 3

    with pytest.raises(AtlasWorkspaceError) as caught:
        project.replace("icon ü", source, cancel=cancel_late)
    assert caught.value.code == "cancelled"
    assert (project.workspace / "atlas-project.json").read_bytes() == before
    assert list((project.workspace / "patches").iterdir()) == []
    calls = 0
    with pytest.raises(AtlasWorkspaceError) as caught:
        project.export_png(tmp_path / "cancelled.png", cancel=lambda: True)
    assert caught.value.code == "cancelled"
    assert not (tmp_path / "cancelled.png").exists()
    for operation in (project.undo, project.redo, lambda **kw: project.restore("icon ü", **kw)):
        with pytest.raises(AtlasWorkspaceError) as caught:
            operation(cancel=lambda: True)
        assert caught.value.code == "cancelled"


def test_cli_real_subprocess_unicode_argv_pagination_and_typed_errors(tmp_path, capsys):
    project, _, _ = make_project(tmp_path, extra='<CroppedBitmap x:Key="second icon" Source="{StaticResource Sheet}" SourceRect="0,0,1,1"/>')
    script = Path(__file__).resolve().parents[2] / "tools/ui_atlas_workspace.py"
    result = subprocess.run([sys.executable, str(script), "list", "--workspace", str(project.workspace), "--query", "icon", "--offset", "0", "--limit", "1"], capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)["result"]
    assert data["total"] == data["matched"] == 2 and data["next_offset"] == 1
    assert main(["list", "--workspace", str(project.workspace), "--limit", "501"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_arguments"
    source = replacement(tmp_path)
    assert main(["replace", "--workspace", str(project.workspace), "--key", "icon ü", "--source", str(source), "--expected-revision", "stale"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "stale_revision"


def test_actual_8192_square_png_small_roi_no_game_no_ui_pixel_limit(tmp_path):
    project, png, xaml = make_project(tmp_path, size=(8192, 8192), rect="8189,8190,3,2")
    original_hash = digest(png)
    assert project.info()["width"] == project.info()["height"] == 8192
    source = replacement(tmp_path)
    project.replace("icon ü", source)
    with AtlasProject.open(project.workspace).preview("icon ü") as image, Image.open(source) as donor:
        assert image.size == (3, 2) and image.tobytes() == donor.tobytes()
    result = project.export_png(tmp_path / "8192-rebuilt.png")
    with Image.open(result["output"]) as image:
        assert image.size == (8192, 8192)
        assert image.getpixel((0, 0)) == (121, 31, 211, 255)
        assert image.getpixel((8188, 8190)) == (13, 47, 91, 0)
        assert image.getpixel((8191, 8191)) == (204, 11, 19, 0)
    assert digest(png) == original_hash


def test_explicit_atlas_key_can_bind_an_extracted_png_with_a_different_name(tmp_path):
    png, xaml = fixture_pair(tmp_path)
    extracted = tmp_path / "Extracted SH1 ü.png"
    png.rename(extracted)
    project = AtlasProject.create(extracted, xaml, tmp_path / "workspace", atlas_key="Sheet")
    assert project.info()["sheet"] == "atlas.png"
    pair = project.export_pair(tmp_path / "published")
    assert Path(pair["png"]).name == "atlas.png"
    assert Path(pair["xaml"]).read_bytes() == xaml.read_bytes()


def test_oversize_png_header_rejected_without_allocating_large_image(tmp_path):
    png, xaml = fixture_pair(tmp_path)

    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    png.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16384, 8193, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\0\0\0\0\0")) + chunk(b"IEND", b""))
    with pytest.raises(AtlasWorkspaceError) as caught:
        AtlasProject.create(png, xaml, tmp_path / "workspace")
    assert caught.value.code == "pixel_budget"
    assert not (tmp_path / "workspace").exists()


def test_corrupt_png_payload_is_rejected_at_create_without_publishing(tmp_path):
    png, xaml = fixture_pair(tmp_path)
    raw = png.read_bytes()
    png.write_bytes(raw[:raw.index(b"IDAT") + 4] + b"bad data")
    with pytest.raises(AtlasWorkspaceError) as caught:
        AtlasProject.create(png, xaml, tmp_path / "workspace")
    assert caught.value.code == "invalid_png"
    assert not (tmp_path / "workspace").exists()
    assert not list(tmp_path.glob("atlas-create-*"))


def test_patch_integrity_is_verified_before_preview_or_export(tmp_path):
    project, _, _ = make_project(tmp_path)
    project.replace("icon ü", replacement(tmp_path))
    patch = next((project.workspace / "patches").glob("*.png"))
    patch.write_bytes(patch.read_bytes() + b"changed")
    with pytest.raises(AtlasWorkspaceError) as caught:
        project.export_png(tmp_path / "bad-export.png")
    assert caught.value.code == "integrity_error"
    assert not (tmp_path / "bad-export.png").exists()


def test_cancel_after_pair_png_generation_publishes_no_directory(tmp_path):
    project, _, _ = make_project(tmp_path)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        return calls >= 4

    with pytest.raises(AtlasWorkspaceError) as caught:
        project.export_pair(tmp_path / "cancelled-pair", cancel=cancel)
    assert caught.value.code == "cancelled"
    assert not (tmp_path / "cancelled-pair").exists()
    assert not list(tmp_path.glob("atlas-pair-*"))


@pytest.mark.parametrize("operation", ["restore", "undo", "redo"])
def test_history_cancel_at_commit_preserves_manifest(tmp_path, operation):
    project, _, _ = make_project(tmp_path)
    project.replace("icon ü", replacement(tmp_path))
    if operation == "redo":
        project.undo()
    before = (project.workspace / "atlas-project.json").read_bytes()
    calls = 0
    threshold = 3 if operation == "restore" else 2

    def cancel():
        nonlocal calls
        calls += 1
        return calls >= threshold

    with pytest.raises(AtlasWorkspaceError) as caught:
        getattr(project, operation)(*([] if operation != "restore" else ["icon ü"]), cancel=cancel)
    assert caught.value.code == "cancelled"
    assert (project.workspace / "atlas-project.json").read_bytes() == before


def test_display_thumbnail_is_separate_from_replacement_pixels(tmp_path):
    source = replacement(tmp_path, size=(20, 10))
    with preview_png(source, max_size=(8, 8)) as image:
        assert image.size == (8, 4) and image.mode == "RGBA"
    with Image.open(source) as image:
        assert image.size == (20, 10) and image.getpixel((19, 9)) == (204, 11, 19, 0)


def test_xaml_export_path_traversal_refused_but_editing_labels_remains_possible(tmp_path):
    png, xaml = fixture_pair(tmp_path)
    xaml.write_text(xaml.read_text(encoding="utf-8").replace('UriSource="atlas.png"', 'UriSource="../atlas.png"'), encoding="utf-8")
    project = AtlasProject.create(png, xaml, tmp_path / "workspace")
    project.replace("icon ü", replacement(tmp_path))
    with pytest.raises(AtlasWorkspaceError) as caught:
        project.export_pair(tmp_path / "published")
    assert caught.value.code == "unsafe_path"
    assert not (tmp_path / "published").exists()


def test_os_commit_lock_prevents_overlapping_writers_without_stale_lock(tmp_path):
    from ui_atlas_workspace import _commit_lock
    first, _, _ = make_project(tmp_path)
    source = replacement(tmp_path)
    before = (first.workspace / "atlas-project.json").read_bytes()
    with _commit_lock(first.workspace):
        with pytest.raises(AtlasWorkspaceError) as caught:
            first.replace("icon ü", source)
        assert caught.value.code == "workspace_busy"
    assert (first.workspace / "atlas-project.json").read_bytes() == before
    first.replace("icon ü", source)
    assert first.info()["cursor"] == 1


@pytest.mark.parametrize("bad_coordinate", [1.0, True])
def test_manifest_coordinates_are_typed_integers_not_float_or_bool(tmp_path, bad_coordinate):
    project, _, _ = make_project(tmp_path)
    manifest_path = project.workspace / "atlas-project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"][0]["x"] = bad_coordinate
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AtlasWorkspaceError) as caught:
        AtlasProject.open(project.workspace)
    assert caught.value.code == "invalid_manifest"


def test_cli_complete_create_transfer_history_and_pair_flow(tmp_path, capsys):
    png, xaml = fixture_pair(tmp_path)
    workspace = tmp_path / "CLI Workspace ü"

    def command(*arguments):
        assert main(list(arguments)) == 0
        return json.loads(capsys.readouterr().out)["result"]

    info = command("create", "--png", str(png), "--xaml", str(xaml), "--workspace", str(workspace))
    common = ("--workspace", str(workspace))
    source = replacement(tmp_path)
    command("replace", *common, "--key", "icon ü", "--source", str(source), "--expected-revision", info["revision"])
    command("undo", *common)
    command("redo", *common)
    command("replace-from", *common, "--key", "icon ü", "--source-workspace", str(workspace), "--source-key", "icon ü")
    command("restore", *common, "--key", "icon ü")
    command("crop", *common, "--key", "icon ü", "--output", str(tmp_path / "crop.png"))
    command("export", *common, "--output", str(tmp_path / "full.png"))
    pair = command("export-pair", *common, "--output", str(tmp_path / "delivery"))
    assert pair["workspace"] == str(workspace.resolve())
    assert Path(pair["xaml"]).read_bytes() == xaml.read_bytes()
    final_info = command("info", *common)
    assert final_info["cursor"] == 3 and final_info["revision"] == pair["revision"]
