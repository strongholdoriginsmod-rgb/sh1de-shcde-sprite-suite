"""The Sandbox PNG Export tools must not overwrite game files or alien data."""
from pathlib import Path
import sys

import pytest
from PIL import Image

TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
from sandbox_png_export import (
    ExportTargetError, atomic_export_png, validate_png_destination
)


def _save(image, destination):
    image.save(destination, "PNG")


def test_map_and_json_paths_are_never_image_export_targets(tmp_path):
    image = Image.new("RGB", (8, 8), "red")
    for extension in (".map", ".json", ".assets", ".txt"):
        target = tmp_path / ("original" + extension)
        target.write_bytes(b"Original game bytes")
        with pytest.raises(ExportTargetError, match="png"):
            atomic_export_png(target, lambda p: _save(image, p), project_root=tmp_path)
        assert target.read_bytes() == b"Original game bytes"


def test_map_installation_folder_is_never_an_export_target(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    game = tmp_path / "Crusader_Data"
    maps = game / "StreamingAssets" / "Maps"
    maps.mkdir(parents=True)
    target = game / "UI" / "screenshot.png"
    with pytest.raises(ExportTargetError, match="Originalspiel"):
        validate_png_destination(
            target, project_root=project, map_root=maps,
            map_file=maps / "test.map"
        )
    assert not target.exists()


def test_existing_external_png_cannot_be_overwritten(tmp_path):
    target = tmp_path / "private.png"
    _save(Image.new("RGB", (2, 2), "black"), target)
    initial = target.read_bytes()
    with pytest.raises(ExportTargetError, match="außerhalb"):
        atomic_export_png(
            target, lambda p: _save(Image.new("RGB", (2, 2), "red"), p),
            project_root=tmp_path,
        )
    assert target.read_bytes() == initial


def test_work_output_is_atomic_and_writable_again(tmp_path):
    work = tmp_path / "work"
    target = work / "test.png"
    atomic_export_png(target, lambda p: _save(Image.new("RGB", (2, 2), "red"), p),
                      project_root=tmp_path, map_root=tmp_path)
    with Image.open(target) as img:
        assert img.convert("RGB").getpixel((0, 0)) == (255, 0, 0)
    atomic_export_png(target, lambda p: _save(Image.new("RGB", (2, 2), "green"), p),
                      project_root=tmp_path)
    with Image.open(target) as img:
        assert img.convert("RGB").getpixel((0, 0)) == (0, 128, 0)
    assert not list(work.glob(".*.png"))


def test_failed_writer_preserves_existing_output(tmp_path):
    target = tmp_path / "work" / "stable.png"
    atomic_export_png(target, lambda p: _save(Image.new("RGB", (2, 2), "blue"), p),
                      project_root=tmp_path)
    old = target.read_bytes()
    def failed_writer(path):
        path.write_bytes(b"broken partial image")
        raise OSError("Simulated full disk")
    with pytest.raises(OSError, match="full disk"):
        atomic_export_png(target, failed_writer, project_root=tmp_path)
    assert target.read_bytes() == old
    assert not list(target.parent.glob(".*.png"))


def test_symlink_png_is_never_overwritten(tmp_path):
    existing = tmp_path / "original.png"
    _save(Image.new("RGB", (2, 2), "white"), existing)
    link = tmp_path / "linked.png"
    try:
        link.symlink_to(existing)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not enabled on this test account")
    with pytest.raises(ExportTargetError, match="Verknüpfte"):
        validate_png_destination(link, project_root=tmp_path)
