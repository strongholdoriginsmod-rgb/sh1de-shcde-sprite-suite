"""Render beauty and material-ID passes from one immutable Blender scene."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

import bpy


def _arguments() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--poses", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_recipe(path: Path):
    module_spec = importlib.util.spec_from_file_location("stronghold_unit_recipe", path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"Cannot import model recipe {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _world_frame(frame: Mapping[str, Any]) -> dict[str, Any]:
    width = int(frame["width"])
    height = int(frame["height"])
    ppu = float(frame["pixels_per_unit"])
    pivot_x_px = float(frame["pivot_x"]) * width
    pivot_y_px = float(frame["pivot_y"]) * height

    def convert(value):
        if value is None:
            return None
        x, y = float(value[0]), float(value[1])
        return [(x - pivot_x_px) / ppu, 0.0, (height - y - pivot_y_px) / ppu]

    landmarks = dict(frame["landmarks"])
    stature = float(landmarks.pop("stature")[0]) / ppu
    axis = landmarks.pop("axis")
    normal = landmarks.pop("normal")
    result = dict(frame)
    result["world_landmarks"] = {name: convert(value) for name, value in landmarks.items()}
    result["stature_world"] = stature
    result["screen_axis"] = axis
    result["screen_normal"] = normal
    return result


def _camera_for_frame(frame: Mapping[str, Any], supersample: int) -> None:
    scene = bpy.context.scene
    width = int(frame["width"])
    height = int(frame["height"])
    ppu = float(frame["pixels_per_unit"])
    pivot_x_px = float(frame["pivot_x"]) * width
    pivot_y_px = float(frame["pivot_y"]) * height
    centre_x = (width / 2.0 - pivot_x_px) / ppu
    centre_z = (height / 2.0 - pivot_y_px) / ppu
    camera = bpy.data.objects["SE_Camera"]
    camera.location = (centre_x, -20.0, centre_z)
    camera.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
    camera.data.ortho_scale = height / ppu
    scene.camera = camera
    scene.render.resolution_x = width * supersample
    scene.render.resolution_y = height * supersample
    scene.render.resolution_percentage = 100


def _id_material(role: str, rgba: list[int]) -> bpy.types.Material:
    name = "SE_ID_" + role
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = tuple(channel / 255.0 for channel in rgba)
    emission.inputs["Strength"].default_value = 1.0
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    material.diffuse_color = tuple(channel / 255.0 for channel in rgba)
    material["se_id_role"] = role
    return material


def _switch_to_id(spec: Mapping[str, Any]) -> dict[str, list[str]]:
    assignments: dict[str, list[str]] = {}
    for object_ in bpy.data.objects:
        if object_.type not in {"MESH", "CURVE"}:
            continue
        role = object_.get("se_role")
        if not role:
            raise RuntimeError(f"Renderable object {object_.name} has no material role")
        assignments[object_.name] = [material.name for material in object_.data.materials]
        object_.data.materials.clear()
        object_.data.materials.append(_id_material(str(role), spec["render"]["material_ids"][str(role)]))
    return assignments


def _restore_beauty(assignments: Mapping[str, list[str]]) -> None:
    for object_name, material_names in assignments.items():
        object_ = bpy.data.objects[object_name]
        object_.data.materials.clear()
        for material_name in material_names:
            material = bpy.data.materials.get(material_name)
            if material is None:
                raise RuntimeError(f"Beauty material vanished: {material_name}")
            object_.data.materials.append(material)


def _render(path: Path) -> None:
    scene = bpy.context.scene
    scene.render.filepath = str(path.resolve())
    bpy.ops.render.render(write_still=True)
    if not path.is_file():
        raise RuntimeError(f"Blender did not produce {path}")


def main() -> None:
    args = _arguments()
    spec_path = args.spec.resolve()
    project_root = spec_path.parents[2]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    poses = json.loads(args.poses.read_text(encoding="utf-8"))
    frame_names = json.loads(args.frames.read_text(encoding="utf-8"))
    if not isinstance(frame_names, list) or not frame_names or len(frame_names) != len(set(frame_names)):
        raise RuntimeError("Frame batch must be a non-empty unique list")
    by_name = {frame["name"]: frame for frame in poses["frames"]}
    unknown = sorted(set(frame_names) - set(by_name))
    if unknown:
        raise RuntimeError(f"Unknown frame names: {unknown}")
    recipe_path = (project_root / spec["model"]["recipe"]).resolve()
    if _sha256(recipe_path) != spec["model"]["recipe_sha256"]:
        raise RuntimeError("Model recipe SHA-256 differs from the unit contract")
    recipe = _load_recipe(recipe_path)
    bpy.ops.wm.open_mainfile(filepath=str(args.model.resolve()))
    if bpy.context.scene.get("se_model_contract") != spec["model"]["contract"]:
        raise RuntimeError("Blend model contract differs from unit manifest")

    scene = bpy.context.scene
    scene.render.engine = spec["render"]["engine"]
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 15
    scene.render.resolution_percentage = 100
    scene.render.use_file_extension = True
    scene.render.image_settings.color_management = "FOLLOW_SCENE"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.render.engine = "BLENDER_EEVEE"
    if hasattr(scene, "eevee"):
        scene.eevee.taa_samples = int(spec["render"]["samples"])
    args.out.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for name in frame_names:
        frame = by_name[name]
        world = _world_frame(frame)
        recipe.apply_pose(world)
        _camera_for_frame(frame, int(spec["render"]["supersample"]))
        beauty_path = args.out / f"{name}.beauty.png"
        id_path = args.out / f"{name}.id.png"
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Medium High Contrast"
        _render(beauty_path)
        assignments = _switch_to_id(spec)
        try:
            scene.view_settings.view_transform = "Raw"
            scene.view_settings.look = "None"
            _render(id_path)
        finally:
            _restore_beauty(assignments)
            scene.view_settings.view_transform = "AgX"
            scene.view_settings.look = "AgX - Medium High Contrast"
        records.append(
            {
                "name": name,
                "width": int(frame["width"]),
                "height": int(frame["height"]),
                "supersample": int(spec["render"]["supersample"]),
                "beauty_file": beauty_path.name,
                "id_file": id_path.name,
                "beauty_file_sha256": _sha256(beauty_path),
                "id_file_sha256": _sha256(id_path),
            }
        )
    report = {
        "schema_version": 1,
        "unit_id": spec["unit_id"],
        "model_sha256": _sha256(args.model),
        "pose_manifest_sha256": _sha256(args.poses),
        "frame_count": len(records),
        "frames": records,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("STRONGHOLD_EUROPE_RENDER_COMPLETE " + json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
