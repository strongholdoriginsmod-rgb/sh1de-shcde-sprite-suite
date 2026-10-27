"""Independent, read-only classification of one completed Suite BC7 build.

The mandatory CLI validator runs inside suite_workflow.py. Exit code zero
only authorizes a separate offline hash audit, never a runtime/game approval.
A failed or interrupted job must never inherit success from an older package.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .config import ConfigurationError, load_config
from .release_preflight import (
    ID, ReleasePreflightError, _is_link, _read_json, audit_release,
)

SCHEMA = "stronghold-europe.suite-build-completion.v1"
MOD_FOLDER = "StrongholdEuropeDE"


class BuildCompletionError(ValueError):
    """The tracked build or output identity is invalid."""


def _output_for(root: Path, profile_id: str, output: str | Path) -> Path:
    if not isinstance(profile_id, str) or ID.fullmatch(profile_id) is None:
        raise BuildCompletionError("Invalid build profile identity")
    if not isinstance(output, (str, Path)):
        raise BuildCompletionError("Invalid output location")
    path = Path(output)
    if not path.is_absolute():
        raise BuildCompletionError("Relative output location")
    try:
        if path != path.resolve():
            raise BuildCompletionError("Noncanonical output path")
        config = load_config(root / "config" / "installations.local.toml")
    except (OSError, ConfigurationError, ValueError) as exc:
        raise BuildCompletionError(f"Cannot check build output: {exc}") from exc
    expected = config.output.dist_dir / profile_id / config.output.mod_folder_name
    if path != expected:
        raise BuildCompletionError("Output differs from tracked profile destination")
    return path


def _manifest_identity(mod: Path) -> str | None:
    if _is_link(mod) or _is_link(mod.parent):
        raise BuildCompletionError("Linked output path")
    if not mod.exists():
        return None
    if not mod.is_dir():
        raise BuildCompletionError("Output is not a directory")
    path = mod / "build-manifest.json"
    if _is_link(path):
        raise BuildCompletionError("Linked manifest")
    if not path.exists():
        return None
    try:
        manifest, digest = _read_json(path)
    except (OSError, ReleasePreflightError) as exc:
        raise BuildCompletionError(f"Manifest cannot be checked: {exc}") from exc
    if manifest.get("schema_version") != 1:
        raise BuildCompletionError("Manifest schema is invalid")
    return digest


def capture_build_before(
    project_root: str | Path,
    profile_id: str,
    output: str | Path,
) -> dict[str, Any]:
    """Read-only binding immediately before one tracked CLI start."""
    root = Path(project_root).resolve(strict=True)
    mod = _output_for(root, profile_id, output)
    return {
        "schema": SCHEMA, "profile_id": profile_id,
        "output": str(mod),
        "prior_manifest_sha256": _manifest_identity(mod),
        "prior_output_exists": mod.exists(),
    }


def _validate_before(profile_id: str, mod: Path, before: Mapping[str, object]) -> None:
    if (
        not isinstance(before, Mapping)
        or before.get("schema") != SCHEMA
        or before.get("profile_id") != profile_id
        or before.get("output") != str(mod)
        or type(before.get("prior_output_exists")) is not bool
    ):
        raise BuildCompletionError("Completion is not tied to the launched build")
    digest = before.get("prior_manifest_sha256")
    if digest is not None and (
        not isinstance(digest, str) or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise BuildCompletionError("Pre-build manifest identity is invalid")


def _result(
    profile_id: str, output: Path, state: str, detail: str, *,
    exit_code: int,
    verified_files: int = 0,
    verified_bytes: int = 0,
    errors: int = 0,
    warnings: int = 0,
    new_manifest_sha256: str | None = None,
    same_manifest_as_before: bool | None = None,
    issues: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "profile_id": profile_id,
        "output": str(output),
        "state": state,
        "detail": detail,
        "exit_code": exit_code,
        "verified_files": verified_files,
        "verified_bytes": verified_bytes,
        "errors": errors,
        "warnings": warnings,
        "manifest_sha256": new_manifest_sha256,
        "same_manifest_as_before": same_manifest_as_before,
        "issues": issues or [],
        "offline_integrity_ok": state in (
            "offline_ok", "offline_warnings", "same_manifest"
        ),
        "release_approved": False,
        "ingame_approved": False,
        "installation_performed": False,
        "no_output_written_by_audit": True,
    }


def inspect_completed_build(
    project_root: str | Path, profile_id: str, output: str | Path, *,
    exit_code: int,
    before: Mapping[str, object],
) -> dict[str, Any]:
    """Classify the CLI result; independently audit the published files on success."""
    if type(exit_code) is not int:
        raise BuildCompletionError("Exit code must be an integer")
    if not isinstance(profile_id, str) or ID.fullmatch(profile_id) is None:
        raise BuildCompletionError("Invalid completed build profile identity")
    root = Path(project_root).resolve(strict=True)
    # A nonzero run must never inspect or reuse a prior package, even when
    # the local configuration was removed before an interrupted run exited.
    if exit_code != 0:
        mod = Path(output)
        if not mod.is_absolute():
            raise BuildCompletionError("Invalid failed build output")
        _validate_before(profile_id, mod, before)
        return _result(
            profile_id, mod, "tool_failed",
            f"Build or mandatory validator exited with {exit_code}; "
            "an earlier package cannot count as this attempt.",
            exit_code=exit_code,
            issues=["Build, validation or cancellation did not finish successfully"],
        )

    try:
        mod = _output_for(root, profile_id, output)
    except BuildCompletionError as exc:
        # A completed CLI job may lose its local output configuration during
        # a long build. Preserve the real exit code, but never call it
        # verified or lose the failure behind an uncaught Tk exception.
        candidate = Path(output)
        if not candidate.is_absolute():
            raise
        _validate_before(profile_id, candidate, before)
        return _result(
            profile_id, candidate, "audit_failed",
            f"CLI returned 0 but the output binding is no longer verifiable: {exc}",
            exit_code=0, issues=[str(exc)],
        )
    _validate_before(profile_id, mod, before)
    # The source-pinned preflight audits only the canonical profile path.
    # Do not suggest a custom output has been audited by that function.
    canonical = root / "dist" / profile_id / MOD_FOLDER
    if mod != canonical:
        return _result(
            profile_id, mod, "unsupported_output",
            "The CLI returned 0, but this custom output is not covered by "
            "the canonical release preflight. Separate auditing is required.",
            exit_code=0,
            issues=["No full-file offline integrity proof for noncanonical output"],
        )
    try:
        report = audit_release(root, profile_id)
        if not isinstance(report, dict):
            raise BuildCompletionError("Malformed independent audit")
        summary = report.get("summary")
        stats = report.get("stats")
        hashes = report.get("source_hashes")
        if (
            not isinstance(summary, dict)
            or not isinstance(stats, dict)
            or not isinstance(hashes, dict)
            or type(summary.get("errors")) is not int
            or type(summary.get("warnings")) is not int
            or type(stats.get("verified_outputs")) is not int
            or type(stats.get("verified_bytes")) is not int
            or type(stats.get("expected_outputs")) is not int
            or type(stats.get("index_groups")) is not int
            or summary["errors"] < 0 or summary["warnings"] < 0
        ):
            raise BuildCompletionError("Malformed audit counts")
        digest = hashes.get("manifest_sha256")
        if digest is not None and (
            not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise BuildCompletionError("Invalid manifest hash in audit")
        if (
            not summary["errors"]
            and (
                stats["verified_outputs"] <= 0
                or stats["verified_outputs"] != stats["expected_outputs"]
                or stats["verified_bytes"] <= 0
                or stats["index_groups"] <= 0
            )
        ):
            raise BuildCompletionError(
                "Offline audit did not cover all files and BC7 groups"
            )
        if digest is not None and _manifest_identity(mod) != digest:
            raise BuildCompletionError("Build manifest changed during offline audit")
        findings = report.get("findings")
        if not isinstance(findings, list):
            raise BuildCompletionError("Missing offline findings")
        issues = [
            f"{item.get('gruppe', 'Audit')}: {item.get('text', '')}"
            for item in findings
            if isinstance(item, dict)
            and item.get("schwere") in ("fehler", "warnung")
        ][:12]
        identical = bool(digest) and digest == before["prior_manifest_sha256"]
        if summary["errors"] or not digest:
            state = "offline_failed"
            detail = (
                "CLI returned 0, but independent SHA-256 integrity inspection "
                "reported errors or did not verify a manifest."
            )
        elif identical:
            state = "same_manifest"
            detail = (
                "Offline integrity passed, but the manifest is identical to "
                "the pre-build one; this cannot prove newly generated bytes."
            )
        elif summary["warnings"]:
            state = "offline_warnings"
            detail = "Offline integrity passed with warnings requiring review."
        else:
            state = "offline_ok"
            detail = (
                "CLI build and mandatory validator returned 0; independent "
                "SHA-256 verification passed for the current files."
            )
        return _result(
            profile_id, mod, state, detail, exit_code=0,
            verified_files=stats["verified_outputs"],
            verified_bytes=stats["verified_bytes"],
            errors=summary["errors"], warnings=summary["warnings"],
            new_manifest_sha256=digest,
            same_manifest_as_before=identical,
            issues=issues,
        )
    except (OSError, ValueError, BuildCompletionError, ReleasePreflightError) as exc:
        return _result(
            profile_id, mod, "audit_failed",
            f"CLI completed but independent SHA-256 audit could not complete: {exc}",
            exit_code=0, issues=[str(exc)],
        )


__all__ = [
    "SCHEMA", "BuildCompletionError",
    "capture_build_before", "inspect_completed_build",
]
