from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .config import BuilderConfig


REQUIRED_DATA_FILES = (
    "globalgamemanagers",
    "resources.assets",
    "resources.assets.resS",
    "sharedassets1.assets",
    "Managed/Assembly-CSharp.dll",
)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _required_file_checks(label: str, data_dir: Path) -> Iterable[Check]:
    yield Check(f"{label}.directory", data_dir.is_dir(), str(data_dir))
    for relative in REQUIRED_DATA_FILES:
        path = data_dir / Path(relative)
        detail = str(path)
        if path.is_file():
            detail += f" ({path.stat().st_size} bytes)"
        yield Check(f"{label}.{relative}", path.is_file(), detail)


def run_doctor(config: BuilderConfig) -> list[Check]:
    checks = [
        Check("policy.private_local_only", config.policy.private_local_only, "must be true"),
        Check(
            "policy.game_archive_writes_disabled",
            not config.policy.allow_game_archive_writes,
            "must be true",
        ),
    ]
    checks.extend(_required_file_checks("source", config.source.data_dir))
    checks.extend(_required_file_checks("target", config.target.data_dir))

    target_game = config.target.game_dir
    checks.append(
        Check(
            "target.game_directory",
            target_game is not None and target_game.is_dir(),
            str(target_game),
        )
    )
    if target_game is not None:
        expected_parent = config.target.data_dir.parent.resolve()
        checks.append(
            Check(
                "target.data_belongs_to_game_directory",
                target_game.resolve() == expected_parent,
                f"game={target_game.resolve()} data-parent={expected_parent}",
            )
        )

    for name, path in (
        ("output.work", config.output.work_dir),
        ("output.cache", config.output.cache_dir),
        ("output.state", config.output.state_dir),
        ("output.dist", config.output.dist_dir),
    ):
        checks.append(Check(name, config.project_root in path.parents, str(path)))
    return checks

