from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from .config import BuilderConfig, Installation
from .doctor import REQUIRED_DATA_FILES
from .hashing import sha256_file


@dataclass(frozen=True)
class FingerprintedFile:
    relative_path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class InstallationFingerprint:
    schema_version: int
    generated_at_utc: str
    name: str
    data_dir: str
    files: tuple[FingerprintedFile, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


def fingerprint_installation(installation: Installation) -> InstallationFingerprint:
    files: list[FingerprintedFile] = []
    for relative in REQUIRED_DATA_FILES:
        path = installation.data_dir / Path(relative)
        if not path.is_file():
            raise FileNotFoundError(path)
        files.append(
            FingerprintedFile(
                relative_path=Path(relative).as_posix(),
                size=path.stat().st_size,
                sha256=sha256_file(path),
            )
        )
    return InstallationFingerprint(
        schema_version=1,
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        name=installation.name,
        data_dir=str(installation.data_dir),
        files=tuple(files),
    )


def write_fingerprints(config: BuilderConfig) -> tuple[Path, Path]:
    config.output.state_dir.mkdir(parents=True, exist_ok=True)
    source = fingerprint_installation(config.source)
    target = fingerprint_installation(config.target)
    source_path = config.output.state_dir / "source-fingerprint.json"
    target_path = config.output.state_dir / "target-fingerprint.json"
    source_path.write_text(source.to_json(), encoding="utf-8")
    target_path.write_text(target.to_json(), encoding="utf-8")
    return source_path, target_path

