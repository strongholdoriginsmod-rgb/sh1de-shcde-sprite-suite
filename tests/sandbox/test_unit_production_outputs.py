"""Exercise unit output transactions independently of the artistic renderer."""
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from stronghold_europe_de import unit_production as units


@pytest.fixture
def export(tmp_path):
    source = tmp_path / "source"
    frame = {"name": "unit-0", "file": "frames/colour.png", "mask_file": "frames/mask.png",
             "width": 24, "height": 24}
    spec = SimpleNamespace(group="unit", unit_id="example", path=tmp_path / "spec.json",
                           expected_frames=1, expected_main=1, expected_alternate=0,
                           reference_sha256="a" * 64)
    index = {"schema_version": 1, "group": spec.group, "frames": [frame]}
    (source / "frames").mkdir(parents=True)
    (source / "index.json").write_text(json.dumps(index), encoding="utf-8")
    for key in ("file", "mask_file"):
        Image.new("RGBA", (24, 24), (31, 44, 77, 255)).save(source / frame[key])
    return source, spec, index


@pytest.mark.parametrize("bad", ["../escape.png", "C:/escape.png", "frames/NUL.png",
                                  "index.json", "FRAMES/MASK.PNG"])
def test_rejects_invalid_or_conflicting_export_paths(export, tmp_path, bad):
    source, spec, index = export
    index["frames"][0]["file"] = bad
    (source / "index.json").write_text(json.dumps(index), encoding="utf-8")
    output = tmp_path / "out"
    with pytest.raises(units.UnitProductionError):
        units.build_unit_series(source, output, spec)
    assert not output.exists()
    assert not (tmp_path / "escape.png").exists()


def test_outputs_are_staged_without_touching_existing_projects(export, tmp_path, monkeypatch):
    source, spec, _ = export
    existing = tmp_path / "user-output"
    existing.mkdir()
    marker = existing / "user-data.txt"
    marker.write_text("preserve", encoding="utf-8")
    for destination in (source, existing, source / "nested"):
        with pytest.raises(units.UnitProductionError):
            units.build_unit_series(source, destination, spec)
    with pytest.raises(units.UnitProductionError):
        units.render_prototype(source, existing, spec, ["unit-0"])
    assert marker.read_text("utf-8") == "preserve"

    def fail_render(*_args, **_kwargs):
        raise units.UnitProductionError("render stopped")

    monkeypatch.setattr(units, "render_unit_frame", fail_render)
    with pytest.raises(units.UnitProductionError, match="render stopped"):
        units.render_prototype(source, tmp_path / "unfinished", spec, ["unit-0"])
    assert not (tmp_path / "unfinished").exists()
    assert not list(tmp_path.glob(".unit-output-*"))


def test_rendered_files_and_comparison_keep_the_export_layout(export, tmp_path, monkeypatch):
    source, spec, index = export
    frame = index["frames"][0]
    original = {path: path.read_bytes() for path in source.rglob("*") if path.is_file()}

    def render(colour, _mask, _spec, *, name):
        image = Image.new("RGBA", colour.size, (77, 12, 28, 128))
        mask = Image.new("RGBA", colour.size, (255, 0, 0, 128))
        pixels = colour.width * colour.height
        stats = units.FrameRenderStats(
            name=name, width=colour.width, height=colour.height, direction=0,
            reference_direction=0, pose_confidence=1.0, source_visible_pixels=pixels,
            output_visible_pixels=pixels, alpha_changed_pixels=pixels, mask_changed_pixels=pixels,
            source_rgb_equal_pixels=0, source_rgb_equal_ratio=0.0, alpha_change_ratio=1.0,
            border_visible_pixels=0, border_ratio=0.0, colour_sha256="c" * 64, mask_sha256="d" * 64,
        )
        return image, mask, stats

    monkeypatch.setattr(units, "render_unit_frame", render)
    built, prototype = tmp_path / "built", tmp_path / "prototype"
    proof = units.build_unit_series(source, built, spec)
    units.render_prototype(source, prototype, spec, [frame["name"]])
    assert (built / "index.json").read_bytes() == original[source / "index.json"]
    for key in ("file", "mask_file"):
        filename = frame[key]
        assert (built / filename).read_bytes() == (prototype / filename).read_bytes()
        assert (built / filename).read_bytes() != original[source / filename]
    assert proof.frame_count == proof.changed_alpha_frames == proof.changed_mask_frames == 1
    assert proof.output_payload_sha256 == units._payload_digest(
        [built / frame["file"], built / frame["mask_file"]], built)
    sheet = tmp_path / "review.png"
    units.build_comparison_sheet(source, prototype, sheet, spec, [frame["name"]])
    with Image.open(sheet) as preview:
        assert preview.size == (180, 510)
    prior_sheet = sheet.read_bytes()
    with pytest.raises(FileExistsError):
        units.build_comparison_sheet(source, prototype, sheet, spec, [frame["name"]])
    assert sheet.read_bytes() == prior_sheet
    assert {path: path.read_bytes() for path in original} == original
