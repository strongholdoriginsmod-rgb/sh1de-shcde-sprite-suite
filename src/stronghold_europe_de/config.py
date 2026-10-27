from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


class ConfigurationError(ValueError):
    """Raised when local builder configuration violates a safety invariant."""


@dataclass(frozen=True)
class Installation:
    name: str
    data_dir: Path
    game_dir: Path | None = None
    # Optional game-layout directory below work/ that holds only the managed
    # reference assemblies the runtime companion compiles against. Lets the
    # companion build against a Script Extender that is not installed in
    # game_dir. Used by the runtime build only; installs still go to game_dir.
    reference_root: Path | None = None


@dataclass(frozen=True)
class OutputPaths:
    work_dir: Path
    cache_dir: Path
    state_dir: Path
    dist_dir: Path
    mod_folder_name: str


@dataclass(frozen=True)
class Policy:
    private_local_only: bool
    allow_game_archive_writes: bool
    allow_unknown_builds: bool


@dataclass(frozen=True)
class BuilderConfig:
    project_root: Path
    source: Installation
    target: Installation
    output: OutputPaths
    policy: Policy


def _absolute_or_project(project_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def load_config(path: Path) -> BuilderConfig:
    config_path = path.resolve()
    if not config_path.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {config_path}")

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    project_root = config_path.parent.parent.resolve()

    try:
        source_data = _absolute_or_project(project_root, data["source"]["data_dir"])
        target_data = _absolute_or_project(project_root, data["target"]["data_dir"])
        target_game = _absolute_or_project(project_root, data["target"]["game_dir"])
        output = data["output"]
        policy_data = data["policy"]
    except KeyError as exc:
        raise ConfigurationError(f"Missing configuration key: {exc}") from exc

    reference_value = data["target"].get("runtime_reference_root")
    reference_root = (
        None
        if reference_value is None
        else _absolute_or_project(project_root, reference_value)
    )

    config = BuilderConfig(
        project_root=project_root,
        source=Installation(data["source"]["name"], source_data),
        target=Installation(
            data["target"]["name"], target_data, target_game, reference_root
        ),
        output=OutputPaths(
            work_dir=_absolute_or_project(project_root, output["work_dir"]),
            cache_dir=_absolute_or_project(project_root, output["cache_dir"]),
            state_dir=_absolute_or_project(project_root, output["state_dir"]),
            dist_dir=_absolute_or_project(project_root, output["dist_dir"]),
            mod_folder_name=output["mod_folder_name"],
        ),
        policy=Policy(
            private_local_only=bool(policy_data["private_local_only"]),
            allow_game_archive_writes=bool(policy_data["allow_game_archive_writes"]),
            allow_unknown_builds=bool(policy_data["allow_unknown_builds"]),
        ),
    )
    validate_config(config)
    return config


def validate_config(config: BuilderConfig) -> None:
    if config.source.data_dir == config.target.data_dir:
        raise ConfigurationError("Source and target data directories must differ")
    if config.source.data_dir.name != "Stronghold 1 Definitive Edition_Data":
        raise ConfigurationError("Source must be the canonical SH1DE *_Data directory")
    if config.target.data_dir.name != "Stronghold Crusader Definitive Edition_Data":
        raise ConfigurationError("Target must be the canonical SHCDE *_Data directory")
    if config.policy.allow_game_archive_writes:
        raise ConfigurationError("Writing game archives is forbidden for this project")
    if not config.policy.private_local_only:
        raise ConfigurationError("This project is intentionally private-local-only")

    writable = (
        config.output.work_dir,
        config.output.cache_dir,
        config.output.state_dir,
        config.output.dist_dir,
    )
    for path in writable:
        if path == config.source.data_dir or path == config.target.data_dir:
            raise ConfigurationError(f"Output path aliases a game data directory: {path}")
        if config.source.data_dir in path.parents or config.target.data_dir in path.parents:
            raise ConfigurationError(f"Output path is nested inside a game data directory: {path}")
        # `doctor` reports this, but `build`/`validate`/`install` never call
        # `doctor`.  Enforcing containment here makes every entry point inherit
        # the invariant instead of leaving it advisory.
        if config.project_root not in path.parents:
            raise ConfigurationError(f"Output path escapes the project root: {path}")

    reference_root = config.target.reference_root
    if reference_root is not None and config.output.work_dir not in reference_root.parents:
        raise ConfigurationError(
            f"runtime_reference_root must lie below the work directory: {reference_root}"
        )

    if not config.output.mod_folder_name or any(
        separator in config.output.mod_folder_name for separator in ("/", "\\")
    ):
        raise ConfigurationError("mod_folder_name must be a single safe directory name")

