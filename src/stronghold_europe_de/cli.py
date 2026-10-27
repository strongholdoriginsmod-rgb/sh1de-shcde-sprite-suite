from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from .builds import UnsupportedBuildError, verify_supported_builds
from .config import ConfigurationError, load_config
from .derived_feasibility import (
    DerivedFeasibilityError,
    scan_unity_derived_groups,
    scan_unity_review_groups,
    write_feasibility_report,
)
from .doctor import run_doctor
from .gm_atlas import GMAtlasError, describe_group_manifest
from .fingerprint import write_fingerprints
from .group_audit import audit_groups, write_group_audit
from .installer import InstallError, install_mod, uninstall_mod
from .mapping import build_mapping_from_files, read_mapping
from .mod_builder import ModBuildError, build_mod, load_profile
from .pixel_identity import (
    DEFAULT_PIXEL_AUDIT_TEXTURES,
    PixelIdentityError,
    audit_pixel_identity,
    audit_texture_payloads,
    write_pixel_identity_report,
    write_texture_payload_report,
)
from .runtime_validation import validate_runtime_log
from .unity_inventory import (
    AssetDependencyError,
    inventory_summary,
    read_inventory,
    scan_resources_assets,
    write_inventory,
)
from .validation import validate_mod, write_validation_report


_RUNTIME_PROFILE_ID_RE = re.compile(
    r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$"
)
_WINDOWS_PROFILE_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


def _validated_runtime_profile_id(profile_id: str) -> str:
    device_stem = profile_id.split(".", 1)[0].casefold()
    if (
        _RUNTIME_PROFILE_ID_RE.fullmatch(profile_id) is None
        or ".." in profile_id
        or device_stem in _WINDOWS_PROFILE_DEVICE_NAMES
    ):
        raise ConfigurationError(
            "Runtime profile id must be a safe lowercase identifier "
            "(1-64 characters: letters, digits, '.', '_', '-')"
        )
    return profile_id


def _load_named_profile(project_root: Path, profile_id: str) -> dict[str, object]:
    profiles_root = (project_root / "profiles").resolve()
    profile_path = (profiles_root / f"{profile_id}.json").resolve()
    if profile_path.parent != profiles_root or not profile_path.is_file():
        raise ConfigurationError(
            f"Canonical profile document is missing: {profile_path}"
        )
    try:
        profile = load_profile(profile_path)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        AttributeError,
        TypeError,
        ModBuildError,
    ) as exc:
        raise ConfigurationError(
            f"Canonical profile document is invalid: {profile_path}"
        ) from exc
    if profile.get("id") != profile_id:
        raise ConfigurationError(
            f"Canonical profile id differs: {profile.get('id')!r} != {profile_id!r}"
        )
    return profile


def _load_profile_document(
    project_root: Path,
    profile_path: Path,
) -> tuple[str, dict[str, object]]:
    """Load an explicit work-only profile without weakening path safety."""

    project_root = project_root.resolve()
    resolved = (
        profile_path.resolve()
        if profile_path.is_absolute()
        else (project_root / profile_path).resolve()
    )
    if (
        resolved == project_root
        or project_root not in resolved.parents
        or not resolved.is_file()
        or resolved.is_symlink()
    ):
        raise ConfigurationError(
            f"Explicit profile must be a regular file inside the project: {resolved}"
        )
    try:
        profile = load_profile(resolved)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        AttributeError,
        TypeError,
        ModBuildError,
    ) as exc:
        raise ConfigurationError(
            f"Explicit profile document is invalid: {resolved}"
        ) from exc
    raw_id = profile.get("id")
    if not isinstance(raw_id, str):
        raise ConfigurationError(
            f"Explicit profile has no string id: {resolved}"
        )
    return _validated_runtime_profile_id(raw_id), profile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stronghold-europe-de",
        description="Private local Stronghold Europe DE builder",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("doctor", "fingerprint", "verify"):
        subparser = subcommands.add_parser(command)
        subparser.add_argument(
            "--config",
            type=Path,
            default=Path("config/installations.local.toml"),
        )
    inventory = subcommands.add_parser("inventory")
    inventory.add_argument(
        "--config",
        type=Path,
        default=Path("config/installations.local.toml"),
    )
    inventory.add_argument(
        "--side",
        choices=("source", "target", "both"),
        default="both",
    )
    mapping = subcommands.add_parser("map")
    mapping.add_argument(
        "action",
        choices=(
            "propose",
            "audit",
            "geometry-audit",
            "review-geometry-audit",
            "texture-audit",
            "pixel-audit",
            "manifest",
        ),
    )
    mapping.add_argument(
        "--config",
        type=Path,
        default=Path("config/installations.local.toml"),
    )
    mapping.add_argument(
        "--groups",
        nargs="+",
        default=[
            "tile_farmland",
            "tile_flatties",
            "tile_cliffs",
            "tile_land_and_stones",
            "tile_chevrons",
            "tile_walls",
            "killing_pits",
            "pitch_ditches",
        ],
        help="mapping groups for geometry-audit or review-geometry-audit",
    )
    mapping.add_argument(
        "--textures",
        nargs="*",
        default=list(DEFAULT_PIXEL_AUDIT_TEXTURES),
        help="source/target Texture2D names selected for pixel-audit",
    )
    mapping.add_argument(
        "--sprite-groups",
        nargs="*",
        default=[],
        help="additional mapping groups selected for pixel-audit",
    )
    build = subcommands.add_parser("build")
    build.add_argument(
        "--config",
        type=Path,
        default=Path("config/installations.local.toml"),
    )
    build.add_argument(
        "--profile",
        type=Path,
        default=Path("profiles/vertical-slice.json"),
    )
    build.add_argument("--replace", action="store_true")
    validate = subcommands.add_parser("validate")
    validate.add_argument(
        "--config",
        type=Path,
        default=Path("config/installations.local.toml"),
    )
    validate_profile = validate.add_mutually_exclusive_group()
    validate_profile.add_argument("--profile-id")
    validate_profile.add_argument(
        "--profile",
        type=Path,
        help="explicit work-only profile document inside the repository",
    )
    runtime_validate = subcommands.add_parser("runtime-validate")
    runtime_validate.add_argument(
        "--config",
        type=Path,
        default=Path("config/installations.local.toml"),
    )
    runtime_validate.add_argument("--profile-id", default="installed")
    runtime_validate.add_argument("--log", type=Path)
    install = subcommands.add_parser("install")
    install.add_argument(
        "--config",
        type=Path,
        default=Path("config/installations.local.toml"),
    )
    install.add_argument("--profile-id", default="vertical-slice")
    install.add_argument(
        "--replace",
        action="store_true",
        help=(
            "replace only an unchanged, manifest-owned existing installation "
            "using the transactional backup path"
        ),
    )
    uninstall = subcommands.add_parser("uninstall")
    uninstall.add_argument(
        "--config",
        type=Path,
        default=Path("config/installations.local.toml"),
    )
    return parser


def _doctor(config_path: Path) -> int:
    config = load_config(config_path)
    checks = run_doctor(config)
    for check in checks:
        marker = "OK" if check.ok else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}")
    return 0 if all(check.ok for check in checks) else 2


def _fingerprint(config_path: Path) -> int:
    config = load_config(config_path)
    checks = run_doctor(config)
    failed = [check.to_dict() for check in checks if not check.ok]
    if failed:
        print(json.dumps({"error": "doctor_failed", "checks": failed}, indent=2), file=sys.stderr)
        return 2
    source_path, target_path = write_fingerprints(config)
    print(source_path)
    print(target_path)
    return 0


def _verify(config_path: Path) -> int:
    config = load_config(config_path)
    supported_path = config.project_root / "config" / "supported-builds.json"
    match = verify_supported_builds(config, supported_path)
    print(f"source={match.source_id}")
    print(f"target={match.target_id}")
    return 0


def _inventory(config_path: Path, side: str) -> int:
    config = load_config(config_path)
    supported_path = config.project_root / "config" / "supported-builds.json"
    verify_supported_builds(config, supported_path)
    selected = (
        (("source", config.source), ("target", config.target))
        if side == "both"
        else ((side, config.source if side == "source" else config.target),)
    )
    for role, installation in selected:
        inventory = scan_resources_assets(installation.data_dir / "resources.assets", role)
        output_path = config.output.work_dir / "inventory" / f"{role}.resources.json.gz"
        write_inventory(inventory, output_path)
        print(f"{output_path}: {inventory_summary(inventory)}")
    return 0


def _map(
    config_path: Path,
    action: str,
    groups: list[str],
    textures: list[str],
    sprite_groups: list[str],
) -> int:
    config = load_config(config_path)
    supported_path = config.project_root / "config" / "supported-builds.json"
    match = verify_supported_builds(config, supported_path)
    inventory_dir = config.output.work_dir / "inventory"
    mapping_path = config.output.work_dir / "mapping" / "proposals.json.gz"
    reports_dir = config.output.work_dir / "reports"
    if action == "manifest":
        mapping = read_mapping(mapping_path)
        manifests = [
            describe_group_manifest(mapping["sprites"], group) for group in groups
        ]
        print(json.dumps(manifests, indent=2, sort_keys=True))
        return 0
    if action == "texture-audit":
        audit = audit_texture_payloads(
            config.source.data_dir / "resources.assets",
            config.target.data_dir / "resources.assets",
            read_inventory(inventory_dir / "source.resources.json.gz"),
            read_inventory(inventory_dir / "target.resources.json.gz"),
            source_build_id=match.source_id,
            target_build_id=match.target_id,
        )
        output_path = reports_dir / "texture-payload-audit.json"
        report_path = reports_dir / "texture-payload-audit.md"
        write_texture_payload_report(audit, output_path, report_path)
        print(output_path)
        print(report_path)
        print(json.dumps(audit["summary"], sort_keys=True))
        return 0
    if action == "pixel-audit":
        audit = audit_pixel_identity(
            config.source.data_dir / "resources.assets",
            config.target.data_dir / "resources.assets",
            read_inventory(inventory_dir / "source.resources.json.gz"),
            read_inventory(inventory_dir / "target.resources.json.gz"),
            read_mapping(mapping_path),
            source_build_id=match.source_id,
            target_build_id=match.target_id,
            selected_textures=textures,
            selected_groups=sprite_groups,
        )
        output_path = reports_dir / "pixel-identity-audit.json"
        report_path = reports_dir / "pixel-identity-audit.md"
        write_pixel_identity_report(audit, output_path, report_path)
        print(output_path)
        print(report_path)
        print(json.dumps(audit["summary"], sort_keys=True))
        return 0
    if action == "geometry-audit":
        report = scan_unity_derived_groups(
            config.source.data_dir / "resources.assets",
            read_mapping(mapping_path),
            groups,
        )
        output_path = config.output.work_dir / "reports" / "derived-feasibility.json"
        report_path = config.output.work_dir / "reports" / "derived-feasibility.md"
        write_feasibility_report(report, output_path, report_path)
        print(output_path)
        print(report_path)
        print(json.dumps(report["summary"], sort_keys=True))
        return 0 if not report["summary"]["group_decisions"].get("BLOCKED") else 2
    if action == "review-geometry-audit":
        report = scan_unity_review_groups(
            config.source.data_dir / "resources.assets",
            read_mapping(mapping_path),
            groups,
        )
        output_path = reports_dir / "review-geometry-feasibility.json"
        report_path = reports_dir / "review-geometry-feasibility.md"
        write_feasibility_report(report, output_path, report_path)
        print(output_path)
        print(report_path)
        print(json.dumps(report["summary"], sort_keys=True))
        return 0 if not report["summary"]["group_decisions"].get("BLOCKED") else 2
    if action == "audit":
        audit = audit_groups(
            read_mapping(mapping_path),
            read_inventory(inventory_dir / "source.resources.json.gz"),
            read_inventory(inventory_dir / "target.resources.json.gz"),
        )
        output_path = config.output.work_dir / "reports" / "group-audit.json"
        report_path = config.output.work_dir / "reports" / "group-audit.md"
        write_group_audit(audit, output_path, report_path)
        print(output_path)
        print(report_path)
        print(json.dumps(audit["summary"], sort_keys=True))
        return 0
    if action != "propose":
        raise ValueError(f"Unsupported map action: {action}")
    output_path = config.output.work_dir / "mapping" / "proposals.json.gz"
    report_path = config.output.work_dir / "reports" / "mapping-summary.md"
    mapping = build_mapping_from_files(
        inventory_dir / "source.resources.json.gz",
        inventory_dir / "target.resources.json.gz",
        output_path,
        report_path,
        match.source_id,
        match.target_id,
    )
    print(output_path)
    print(report_path)
    print(json.dumps(mapping["sprite_summary"]["action_counts"], sort_keys=True))
    return 0


def _build(config_path: Path, profile_path: Path, replace: bool) -> int:
    config = load_config(config_path)
    supported_path = config.project_root / "config" / "supported-builds.json"
    match = verify_supported_builds(config, supported_path)
    resolved_profile = (
        profile_path.resolve()
        if profile_path.is_absolute()
        else (config.project_root / profile_path).resolve()
    )
    mapping_path = config.output.work_dir / "mapping" / "proposals.json.gz"
    mod_root = build_mod(config, match, resolved_profile, mapping_path, replace)
    print(mod_root)
    return 0


def _validate(
    config_path: Path,
    profile_id: str | None,
    profile_path: Path | None = None,
) -> int:
    if profile_path is None:
        profile_id = _validated_runtime_profile_id(
            "vertical-slice" if profile_id is None else profile_id
        )
    elif profile_id is not None:
        raise ConfigurationError(
            "Static validation accepts either --profile-id or --profile, not both"
        )
    else:
        # Load the configuration first only after argparse has guaranteed the
        # mutually exclusive CLI shape.  The resolved project root is the
        # authority for the explicit profile containment check below.
        profile_id = None
    assert profile_id is None or isinstance(profile_id, str)
    if profile_id == "installed":
        raise ConfigurationError(
            "The 'installed' profile sentinel is valid only for runtime validation"
        )
    config = load_config(config_path)
    supported_path = config.project_root / "config" / "supported-builds.json"
    match = verify_supported_builds(config, supported_path)
    if profile_path is None:
        assert profile_id is not None
        expected_profile = _load_named_profile(config.project_root, profile_id)
    else:
        profile_id, expected_profile = _load_profile_document(
            config.project_root,
            profile_path,
        )
    mod_root = config.output.dist_dir / profile_id / config.output.mod_folder_name
    checks = validate_mod(
        mod_root,
        expected_profile_id=profile_id,
        expected_source_build_id=match.source_id,
        expected_target_build_id=match.target_id,
        expected_profile=expected_profile,
    )
    report_root = (config.output.work_dir / "reports").resolve()
    report_path = (report_root / f"{profile_id}-validation.json").resolve()
    if report_path.parent != report_root:
        raise ConfigurationError("Validation report path escapes reports root")
    write_validation_report(checks, report_path)
    for check in checks:
        marker = "OK" if check.ok else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}")
    print(report_path)
    return 0 if all(check.ok for check in checks) else 2


def _runtime_validate(config_path: Path, profile_id: str, log_path: Path | None) -> int:
    profile_id = _validated_runtime_profile_id(profile_id)
    config = load_config(config_path)
    supported_path = config.project_root / "config" / "supported-builds.json"
    match = verify_supported_builds(config, supported_path)
    if config.target.game_dir is None:
        raise ConfigurationError("Target game directory is not configured")
    expected_destination = (
        config.target.game_dir
        / "BepInEx"
        / "plugins"
        / config.output.mod_folder_name
    ).absolute()
    if log_path is None:
        resolved_log = config.target.game_dir / "BepInEx" / "LogOutput.log"
    else:
        resolved_log = log_path.resolve()
    checks = validate_runtime_log(
        resolved_log,
        config.output.state_dir / "install-manifest.json",
        expected_destination=expected_destination,
        expected_source_build_id=match.source_id,
        expected_target_build_id=match.target_id,
        expected_profile_id=None if profile_id == "installed" else profile_id,
        expected_guid="strongholdeuropede.private",
    )
    report_root = (config.output.work_dir / "reports").resolve()
    report_path = (
        report_root / f"{profile_id}-runtime-validation.json"
    ).resolve()
    if report_path.parent != report_root:
        raise ConfigurationError("Runtime validation report path escapes reports root")
    write_validation_report(checks, report_path)
    for check in checks:
        marker = "OK" if check.ok else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}")
    print(report_path)
    return 0 if all(check.ok for check in checks) else 2


def _install(config_path: Path, profile_id: str, replace: bool = False) -> int:
    profile_id = _validated_runtime_profile_id(profile_id)
    if profile_id == "installed":
        raise ConfigurationError(
            "The 'installed' profile sentinel is valid only for runtime validation"
        )
    config = load_config(config_path)
    supported_path = config.project_root / "config" / "supported-builds.json"
    match = verify_supported_builds(config, supported_path)
    expected_profile = _load_named_profile(config.project_root, profile_id)
    mod_root = config.output.dist_dir / profile_id / config.output.mod_folder_name
    destination = install_mod(
        config,
        mod_root,
        expected_profile_id=profile_id,
        expected_source_build_id=match.source_id,
        expected_target_build_id=match.target_id,
        expected_profile=expected_profile,
        replace_existing=replace,
    )
    print(destination)
    return 0


def _uninstall(config_path: Path) -> int:
    config = load_config(config_path)
    destination = uninstall_mod(config)
    print(destination)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return _doctor(args.config)
        if args.command == "fingerprint":
            return _fingerprint(args.config)
        if args.command == "verify":
            return _verify(args.config)
        if args.command == "inventory":
            return _inventory(args.config, args.side)
        if args.command == "map":
            return _map(
                args.config,
                args.action,
                args.groups,
                args.textures,
                args.sprite_groups,
            )
        if args.command == "build":
            return _build(args.config, args.profile, args.replace)
        if args.command == "validate":
            return _validate(args.config, args.profile_id, args.profile)
        if args.command == "runtime-validate":
            return _runtime_validate(args.config, args.profile_id, args.log)
        if args.command == "install":
            return _install(args.config, args.profile_id, args.replace)
        if args.command == "uninstall":
            return _uninstall(args.config)
    except (
        AssetDependencyError,
        ConfigurationError,
        DerivedFeasibilityError,
        UnsupportedBuildError,
        FileNotFoundError,
        GMAtlasError,
        InstallError,
        ModBuildError,
        PixelIdentityError,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
