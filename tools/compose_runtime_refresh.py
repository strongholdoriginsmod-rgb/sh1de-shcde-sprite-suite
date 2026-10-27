from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import tempfile

from stronghold_europe_de.asset_stream_contract import parse_atlas_backend
from stronghold_europe_de.builds import verify_supported_builds
from stronghold_europe_de.config import load_config
from stronghold_europe_de.installer import install_mod
from stronghold_europe_de.mod_builder import (
    _copy_project_files,
    _prepare_xaml_patches,
    _record,
)
from stronghold_europe_de.runtime_build import build_runtime_artifacts
from stronghold_europe_de.ui_asset_bundle import load_ui_texture_backend_selection
from stronghold_europe_de.validation import validate_mod


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "installations.local.toml"
PROFILE_PATH = PROJECT_ROOT / "profiles" / "europe-production-bc7-v2.json"
DIPLOMACY_PROFILE_PATH = PROJECT_ROOT / "profiles" / "diplomacy-v1-canary.json"
SUPPORTED_BUILDS_PATH = PROJECT_ROOT / "config" / "supported-builds.json"
BASE_PACKAGE_LABEL = "europe-production-bc7-v2"
OUTPUT_LABEL = "europe-production-bc7-v2-all-features-runtime-refresh-v14"
NO_MILITIA_OUTPUT_LABEL = (
    "europe-production-bc7-v2-diplomacy-no-militia-v1"
)


def _load_profile(*, worker_militia: bool = True) -> dict[str, object]:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    diplomacy_profile = json.loads(
        DIPLOMACY_PROFILE_PATH.read_text(encoding="utf-8")
    )
    runtime = profile.get("runtime")
    if not isinstance(runtime, dict):
        raise RuntimeError("BC7 production profile has no runtime contract")
    if runtime.get("worker_militia") is not False:
        raise RuntimeError("BC7 baseline no longer has the expected militia-off state")
    if runtime.get("diplomacy", False) is not False:
        raise RuntimeError("BC7 baseline no longer has the expected diplomacy-off state")
    if profile.get("diplomacy_rules") is not None:
        raise RuntimeError("BC7 baseline unexpectedly carries diplomacy rules")
    if diplomacy_profile.get("id") != "diplomacy-v1-canary":
        raise RuntimeError("Diplomacy source profile identity changed")
    diplomacy_rules = diplomacy_profile.get("diplomacy_rules")
    diplomacy_xaml = diplomacy_profile.get("xaml_patches")
    if not isinstance(diplomacy_rules, dict):
        raise RuntimeError("Diplomacy source profile has no pinned rules")
    if not isinstance(diplomacy_xaml, list) or len(diplomacy_xaml) != 1:
        raise RuntimeError("Diplomacy source profile has no singular HUD patch")
    xaml_patches = profile.get("xaml_patches")
    if not isinstance(xaml_patches, list):
        raise RuntimeError("BC7 production profile has no XAML patch list")
    diplomacy_output = diplomacy_xaml[0].get("output")
    if not isinstance(diplomacy_output, str) or any(
        entry.get("output") == diplomacy_output
        for entry in xaml_patches
        if isinstance(entry, dict)
    ):
        raise RuntimeError("Diplomacy HUD output is malformed or already selected")

    runtime["worker_militia"] = worker_militia
    runtime["diplomacy"] = True
    profile["diplomacy_rules"] = diplomacy_rules
    xaml_patches.append(diplomacy_xaml[0])
    feature_description = (
        "team-mask routing, worker militia, diplomacy V1 and battlement "
        "top alignment enabled"
        if worker_militia
        else "team-mask routing, diplomacy V1 and battlement top alignment "
        "enabled; worker militia disabled"
    )
    profile["description"] = (
        str(profile.get("description", "")) + "; " + feature_description
    )
    return profile


def _assert_contained(path: Path, parent: Path, label: str) -> None:
    resolved = path.resolve()
    root = parent.resolve()
    if root not in resolved.parents:
        raise RuntimeError(f"{label} escapes its guarded root: {resolved}")


def _materialize_missing_xaml(
    config: object,
    root: Path,
    profile: dict[str, object],
) -> list[object]:
    selections = profile.get("xaml_patches")
    if not isinstance(selections, list):
        raise RuntimeError("Combined production profile has no XAML patch list")
    missing: list[object] = []
    for selection in selections:
        if not isinstance(selection, dict) or not isinstance(
            selection.get("output"), str
        ):
            raise RuntimeError("Combined production profile has a malformed XAML patch")
        if not (root / selection["output"]).is_file():
            missing.append(selection)
    prepared = _prepare_xaml_patches(config, {"xaml_patches": missing})
    return _copy_project_files(root, prepared)


def _replace_runtime_records(
    root: Path,
    artifacts: list[object],
    added_records: list[object],
    profile: dict[str, object],
) -> None:
    manifest_path = root / "build-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise RuntimeError("Installed build manifest has no output list")
    by_path = {
        entry.get("relative_path"): entry
        for entry in outputs
        if isinstance(entry, dict) and isinstance(entry.get("relative_path"), str)
    }
    if len(by_path) != len(outputs):
        raise RuntimeError("Installed build manifest has duplicate or malformed outputs")

    for record in added_records:
        relative = record.relative_path
        if relative in by_path:
            raise RuntimeError(
                f"Promoted feature output already exists in the base package: {relative}"
            )
        by_path[relative] = asdict(record)

    replaced: set[str] = set()
    for artifact in artifacts:
        path = Path(artifact.path)
        relative = path.relative_to(root).as_posix()
        if relative not in by_path:
            raise RuntimeError(f"Runtime refresh introduced an unexpected output: {relative}")
        by_path[relative] = asdict(
            _record(
                root,
                path,
                artifact.category,
                artifact.source_reference,
                metadata=artifact.metadata,
            )
        )
        replaced.add(relative)

    required = {
        "StrongholdEuropeDE.Runtime.dll",
        "Runtime/audio-profile.tsv",
        "Runtime/Audio/pcm-stream-manifest.tsv",
        "Runtime/ui-textures-v2.tsv",
    }
    if not required.issubset(replaced):
        raise RuntimeError(
            f"Runtime refresh did not replace its complete contract: {sorted(required - replaced)}"
        )
    if profile["runtime"].get("diplomacy") is True and (
        "Patches/Assets/GUI/XAMLResources/HUD_AlliesPanel.xaml" not in by_path
    ):
        raise RuntimeError("Diplomacy promotion omitted its pinned HUD patch")

    manifest["profile_description"] = profile.get("description", "")
    manifest["outputs"] = [by_path[key] for key in sorted(by_path)]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _validate(
    root: Path,
    profile: dict[str, object],
    source_build_id: str,
    target_build_id: str,
) -> None:
    checks = validate_mod(
        root,
        expected_profile_id=str(profile["id"]),
        expected_source_build_id=source_build_id,
        expected_target_build_id=target_build_id,
        expected_profile=profile,
    )
    failed = [check for check in checks if not check.ok]
    if failed:
        first = failed[0]
        raise RuntimeError(f"Runtime refresh validation failed: {first.name}: {first.detail}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh only the runtime of the validated BC7 production package."
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Atomically replace the existing manifest-owned installation after validation.",
    )
    parser.add_argument(
        "--install-existing",
        action="store_true",
        help="Validate and install an already published refresh package.",
    )
    parser.add_argument(
        "--without-worker-militia",
        action="store_true",
        help=(
            "Keep the production SH1 assets and diplomacy runtime, but compile "
            "the worker militia feature out of the restored package."
        ),
    )
    args = parser.parse_args()

    config = load_config(CONFIG_PATH)
    match = verify_supported_builds(config, SUPPORTED_BUILDS_PATH)
    profile = _load_profile(worker_militia=not args.without_worker_militia)
    if config.target.game_dir is None:
        raise RuntimeError("Target game root is not configured")
    base_package = (
        config.output.dist_dir
        / BASE_PACKAGE_LABEL
        / config.output.mod_folder_name
    ).resolve(strict=True)
    _assert_contained(base_package, config.output.dist_dir, "validated base package")
    output_label = (
        NO_MILITIA_OUTPUT_LABEL
        if args.without_worker_militia
        else OUTPUT_LABEL
    )
    destination_parent = (config.output.dist_dir / output_label).resolve()
    destination = destination_parent / config.output.mod_folder_name
    _assert_contained(destination, config.output.dist_dir, "published package")
    if args.install_existing:
        if not destination.is_dir():
            raise RuntimeError(f"Published runtime refresh is missing: {destination}")
        _validate(destination, profile, match.source_id, match.target_id)
        installed_destination = install_mod(
            config,
            destination,
            expected_profile_id=str(profile["id"]),
            expected_source_build_id=match.source_id,
            expected_target_build_id=match.target_id,
            expected_profile=profile,
            replace_existing=True,
        )
        print(installed_destination)
        return 0
    if destination_parent.exists():
        raise RuntimeError(f"Runtime refresh output already exists: {destination_parent}")

    staging_parent = Path(
        tempfile.mkdtemp(prefix="runtime-refresh-", dir=config.output.work_dir)
    ).resolve()
    _assert_contained(staging_parent, config.output.work_dir, "runtime refresh staging")
    staging = staging_parent / config.output.mod_folder_name
    published = False
    try:
        # The installed slot can temporarily contain a manually refreshed bundle/index
        # beside stale build-manifest records.  Seed from the coherent, validated
        # production package so the runtime-only refresh preserves all 152 recorded
        # bundle hashes (including the rebuilt anim_castle top alignment)
        # exactly.
        shutil.copytree(base_package, staging, copy_function=shutil.copy2)

        added_records = _materialize_missing_xaml(config, staging, profile)

        audio_root = staging / "Runtime" / "Audio"
        _assert_contained(audio_root, staging, "staged audio payload")
        if audio_root.is_dir():
            shutil.rmtree(audio_root)
        pcm_manifest = staging / "Runtime" / "pcm-stream-manifest.tsv"
        if pcm_manifest.is_file():
            pcm_manifest.unlink()

        atlas_backend = parse_atlas_backend(profile)
        ui_backend = load_ui_texture_backend_selection(PROJECT_ROOT, profile)
        artifacts = build_runtime_artifacts(
            config=config,
            build_match=match,
            mod_root=staging,
            profile_id=str(profile["id"]),
            selection=profile["runtime"],
            dock_rules=profile.get("dock_placement_rules"),
            diplomacy_rules=profile.get("diplomacy_rules"),
            atlas_backend=atlas_backend,
            ui_texture_backend=ui_backend,
        )
        _replace_runtime_records(staging, artifacts, added_records, profile)
        _validate(staging, profile, match.source_id, match.target_id)

        destination_parent.mkdir(parents=False)
        os.replace(staging, destination)
        published = True
        print(destination)

        if args.install:
            installed_destination = install_mod(
                config,
                destination,
                expected_profile_id=str(profile["id"]),
                expected_source_build_id=match.source_id,
                expected_target_build_id=match.target_id,
                expected_profile=profile,
                replace_existing=True,
            )
            print(installed_destination)
        return 0
    finally:
        if staging_parent.exists():
            shutil.rmtree(staging_parent)
        if not published and destination_parent.exists() and not any(destination_parent.iterdir()):
            destination_parent.rmdir()


if __name__ == "__main__":
    raise SystemExit(main())
