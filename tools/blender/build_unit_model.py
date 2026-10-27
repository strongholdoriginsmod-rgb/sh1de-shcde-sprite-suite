"""Build and validate a project-owned unit model inside Blender."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import bpy


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _arguments() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


def _load_recipe(path: Path):
    module_spec = importlib.util.spec_from_file_location("stronghold_unit_recipe", path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"Cannot import model recipe {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    args = _arguments()
    spec_path = args.spec.resolve()
    project_root = spec_path.parents[2]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    recipe_path = (project_root / spec["model"]["recipe"]).resolve()
    if _sha256(recipe_path) != spec["model"]["recipe_sha256"]:
        raise RuntimeError("Model recipe SHA-256 differs from the unit contract")
    recipe = _load_recipe(recipe_path)
    if recipe.MODEL_CONTRACT != spec["model"]["contract"]:
        raise RuntimeError("Model recipe contract identifier differs from the unit contract")
    result = recipe.build_scene(spec)
    required = set(spec["model"]["required_objects"])
    present = set(bpy.data.objects.keys())
    missing = sorted(required - present)
    if missing:
        raise RuntimeError(f"Generated model misses required objects: {missing}")
    roleless = sorted(
        object_.name
        for object_ in bpy.data.objects
        if object_.type in {"MESH", "CURVE"} and not object_.get("se_role")
    )
    if roleless:
        raise RuntimeError(f"Renderable model objects without material role: {roleless}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve()), check_existing=False)
    report = {
        "schema_version": 1,
        "unit_id": spec["unit_id"],
        "model_contract": result["model_contract"],
        "recipe_sha256": spec["model"]["recipe_sha256"],
        "blend_sha256": _sha256(args.out),
        "objects": sorted(present),
        "renderable_objects": sorted(
            object_.name for object_ in bpy.data.objects if object_.type in {"MESH", "CURVE"}
        ),
        "material_roles": result["materials"],
        "required_objects": sorted(required),
        "missing_objects": missing,
        "roleless_objects": roleless,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("STRONGHOLD_EUROPE_MODEL_BUILT " + json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
