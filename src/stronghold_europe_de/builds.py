from __future__ import annotations

from dataclasses import dataclass
import json
import hashlib
from pathlib import Path
from typing import Any

from .config import BuilderConfig
from .fingerprint import InstallationFingerprint, fingerprint_installation


class UnsupportedBuildError(RuntimeError):
    """Raised when the reference fingerprint document has an unsupported format."""


@dataclass(frozen=True)
class BuildMatch:
    source_id: str
    target_id: str
    source_fingerprint: InstallationFingerprint
    target_fingerprint: InstallationFingerprint


def _file_key(file_data: dict[str, Any]) -> tuple[str, int, str]:
    return (
        str(file_data["relative_path"]),
        int(file_data["size"]),
        str(file_data["sha256"]).lower(),
    )


def _fingerprint_file_keys(fingerprint: InstallationFingerprint) -> set[tuple[str, int, str]]:
    return {
        (entry.relative_path, entry.size, entry.sha256.lower())
        for entry in fingerprint.files
    }


def match_fingerprint(
    fingerprint: InstallationFingerprint,
    supported_entries: list[dict[str, Any]],
) -> str | None:
    actual = _fingerprint_file_keys(fingerprint)
    for entry in supported_entries:
        expected = {_file_key(file_data) for file_data in entry["files"]}
        if actual == expected:
            return str(entry["id"])
    return None


def fingerprint_comparison(fingerprint: InstallationFingerprint, entries: list[dict[str, Any]]) -> dict[str, Any]:
    actual = {f.relative_path: {"size": f.size, "sha256": f.sha256.lower()} for f in fingerprint.files}
    candidates = []
    for entry in entries:
        expected = {str(f["relative_path"]): {"size": int(f["size"]), "sha256": str(f["sha256"]).lower()} for f in entry["files"]}
        differences = [{"relative_path": name, "expected": expected.get(name), "actual": actual.get(name)}
                       for name in sorted(actual.keys() | expected.keys()) if actual.get(name) != expected.get(name)]
        candidates.append({"id": entry["id"], "display_version": entry.get("display_version", entry["id"]),
                           "matching_files": sum(actual.get(name) == value for name, value in expected.items()),
                           "differences": differences})
    candidates.sort(key=lambda item: -item["matching_files"])
    return {"matched_build": match_fingerprint(fingerprint, entries), "files": actual, "known_builds": candidates}


def write_fingerprint_report(config: BuilderConfig, source: InstallationFingerprint,
                             target: InstallationFingerprint, data: dict[str, Any]) -> Path:
    # Export hashes and relative filenames only, never installation paths or account data.
    report = {"schema_version": 1, "generated_at_utc": source.generated_at_utc,
              "source": fingerprint_comparison(source, data.get("source_builds", [])),
              "target": fingerprint_comparison(target, data.get("target_builds", []))}
    destination = config.output.work_dir / "reports" / "build-compatibility.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return destination


def write_build_report(config: BuilderConfig, supported_builds_path: Path) -> Path:
    data = json.loads(supported_builds_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise UnsupportedBuildError("Unsupported supported-builds schema")
    return write_fingerprint_report(config, fingerprint_installation(config.source),
                                    fingerprint_installation(config.target), data)


def installation_build_id(side: str, fingerprint: InstallationFingerprint) -> str:
    payload = json.dumps(sorted(_fingerprint_file_keys(fingerprint)), separators=(",", ":")).encode("utf-8")
    return "installed-" + side + "-" + hashlib.sha256(payload).hexdigest()


def verify_supported_builds(
    config: BuilderConfig,
    supported_builds_path: Path,
) -> BuildMatch:
    data = json.loads(supported_builds_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise UnsupportedBuildError("Unsupported supported-builds schema")

    source = fingerprint_installation(config.source)
    target = fingerprint_installation(config.target)
    source_id = match_fingerprint(source, data.get("source_builds", []))
    target_id = match_fingerprint(target, data.get("target_builds", []))
    # Reference fingerprints identify historical builds. New installations receive
    # content-derived IDs so caches remain tied to their actual inputs.
    if source_id is None or target_id is None:
        write_fingerprint_report(config, source, target, data)
    return BuildMatch(
        source_id=source_id or installation_build_id("source", source),
        target_id=target_id or installation_build_id("target", target),
        source_fingerprint=source,
        target_fingerprint=target,
    )

