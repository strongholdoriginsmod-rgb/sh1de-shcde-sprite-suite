from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stronghold_europe_de.asset_stream_builder import _resolve_toolchain  # noqa: E402
from stronghold_europe_de.asset_stream_contract import parse_atlas_backend  # noqa: E402
from stronghold_europe_de.ui_asset_bundle import (  # noqa: E402
    UiAssetBundleError,
    build_ui_texture_backend,
    load_ui_texture_backend_selection,
    load_ui_texture_source_manifest,
)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build/cache the pinned direct UI BC7 packages from an existing "
            "read-only mod payload without modifying that payload."
        )
    )
    parser.add_argument("--source-mod-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--profile",
        type=Path,
        default=PROJECT_ROOT / "profiles/europe-production-bc7-v2.json",
    )
    args = parser.parse_args()

    workspace = PROJECT_ROOT.resolve(strict=True)
    source_mod = args.source_mod_root.resolve(strict=True)
    profile_path = args.profile.resolve(strict=True)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    selection = load_ui_texture_backend_selection(workspace, profile)
    if selection is None:
        raise SystemExit("Selected profile has no ui_texture_backend")
    backend = parse_atlas_backend(profile)
    if backend is None:
        raise SystemExit("UI BC7 profile requires atlas_backend resource policy")

    allowed_parent = workspace / "work/ui-bc7-standalone"
    allowed_parent.mkdir(parents=True, exist_ok=True)
    output = args.output_root.resolve()
    if output.parent.resolve(strict=True) != allowed_parent.resolve(strict=True):
        raise SystemExit(
            f"--output-root must be one direct child of {allowed_parent}"
        )
    if output.exists() or output.is_symlink():
        raise SystemExit(f"Refusing to reuse output root: {output}")
    output.mkdir(parents=False, exist_ok=False)

    manifest = load_ui_texture_source_manifest(selection.source_manifest_path)
    copied = 0
    for entry in manifest.entries:
        if entry.source_kind != "profile_output":
            continue
        source = source_mod.joinpath(*PurePosixPath(entry.source).parts)
        source = source.resolve(strict=True)
        if source_mod != source and source_mod not in source.parents:
            raise SystemExit(f"Profile UI source escaped source mod: {entry.source}")
        if _sha256_file(source) != entry.expected_source_sha256:
            raise SystemExit(f"Profile UI source hash changed: {entry.id}")
        destination = output.joinpath(*PurePosixPath(entry.source).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if _sha256_file(destination) != entry.expected_source_sha256:
            raise SystemExit(f"Profile UI source copy changed: {entry.id}")
        copied += 1
    if copied != sum(
        entry.source_kind == "profile_output" for entry in manifest.entries
    ):
        raise SystemExit("Profile UI source copy count changed")

    toolchain = _resolve_toolchain(workspace, None)
    try:
        result = build_ui_texture_backend(
            workspace_root=workspace,
            mod_root=output,
            source_manifest_path=selection.source_manifest_path,
            quality_policy_path=selection.quality_policy_path,
            unity_editor=toolchain.executable,
            max_resident_bytes=backend.resource_policy.ui_resident_bytes,
            timeout_seconds=toolchain.timeout_seconds,
        )
    except UiAssetBundleError as exc:
        raise SystemExit(f"UI BC7 build failed closed: {exc}") from exc
    print(
        "UI BC7 payload complete: "
        f"hits={result.cache_hit_count} misses={result.cache_miss_count} "
        f"resident={result.runtime.declared_resident_charge_bytes} "
        f"manifest={result.runtime.manifest_sha256} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
