"""Local append-only, hash-chained Sprite Suite build attempt history.

The records are *observations*, not authorisations to build, install or
release. A started attempt left open by a crash is always UNCONFIRMED.
All writes are confined to ignored work/reports/suite-build-history.
Every row is byte-canonical JSON, individually SHA-256 addressed, and
bound to a contiguous ordered chain. A malicious user who can rewrite
the complete tail cannot be defeated by local hashes alone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from typing import Any, Mapping

from .release_preflight import ID, _is_link, _strict_pairs, _bad_constant
from .suite_build_completion import SCHEMA as COMPLETION_SCHEMA

SCHEMA = "stronghold-europe.suite-build-history.v1"
RELATIVE = Path("work/reports/suite-build-history")
MAX_EVENTS = 500
MAX_FILE_BYTES = 48 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
MAX_MESSAGE_CHARS = 2048
RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
ENTRY_NAME = re.compile(r"([0-9]{6})-([0-9a-f]{64})\.json\Z")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00\Z")
KINDS = frozenset(("started", "completed", "launch_failed", "inspection_failed"))
SOURCE_KEYS = frozenset((
    "profile_sha256", "config_sha256", "mapping_sha256",
    "unity_contract_sha256", "toolchains_sha256",
))
SOURCE_REQUIRED = frozenset(("profile_sha256", "config_sha256", "mapping_sha256"))
OFFLINE_STATES = frozenset(("offline_ok", "offline_warnings", "same_manifest"))


class BuildHistoryError(ValueError):
    """The local journal is inconsistent or unsafe to use."""


def _encode(obj: object) -> bytes:
    try:
        return (
            json.dumps(
                obj, sort_keys=True, ensure_ascii=False,
                allow_nan=False, separators=(",", ":"),
            ).encode("utf-8") + b"\n"
        )
    except (ValueError, TypeError) as exc:
        raise BuildHistoryError("History contains noncanonical values") from exc


def _folder(root: Path, *, create: bool = False) -> Path:
    if _is_link(root):
        raise BuildHistoryError("Project root must not be a symlink/junction")
    folder = root
    for part in RELATIVE.parts:
        folder = folder / part
        if _is_link(folder):
            raise BuildHistoryError("Build history folder contains a link/junction")
        if folder.exists():
            if not folder.is_dir():
                raise BuildHistoryError("Build history path is not a directory")
        elif create:
            try:
                folder.mkdir()
            except FileExistsError as exc:
                raise BuildHistoryError("History path changed while creating it") from exc
    return folder


def _validate_started(profile: str, payload: dict) -> None:
    before = payload.get("before")
    if (
        not isinstance(before, dict)
        or before.get("schema") != COMPLETION_SCHEMA
        or before.get("profile_id") != profile
        or not isinstance(before.get("output"), str)
        or len(before["output"]) > 2048
        or type(before.get("prior_output_exists")) is not bool
    ):
        raise BuildHistoryError("Started build is not tied to a valid before snapshot")
    previous = before.get("prior_manifest_sha256")
    if previous is not None and (
        not isinstance(previous, str) or SHA.fullmatch(previous) is None
        or before["prior_output_exists"] is False
    ):
        raise BuildHistoryError("Previous manifest digest invalid")
    if (
        not Path(before["output"]).is_absolute()
        or "\x00" in before["output"]
    ):
        raise BuildHistoryError("Started build output is not an absolute path")
    if type(payload.get("replace")) is not bool:
        raise BuildHistoryError("Missing explicit replace choice")
    if set(payload) not in ({"before", "replace"}, {"before", "replace", "source_hashes"}):
        raise BuildHistoryError("Unexpected started-build evidence")
    hashes = payload.get("source_hashes")
    if hashes is not None and (
        not isinstance(hashes, dict)
        or not SOURCE_REQUIRED <= set(hashes) <= SOURCE_KEYS
        or any(
            not isinstance(value, str) or SHA.fullmatch(value) is None
            for value in hashes.values()
        )
    ):
        raise BuildHistoryError("Invalid source SHA-256 bindings at build start")


def _validate_completed(profile: str, payload: dict) -> None:
    result = payload.get("result")
    if (
        not isinstance(result, dict)
        or result.get("schema") != COMPLETION_SCHEMA
        or result.get("profile_id") != profile
        or type(result.get("exit_code")) is not int
        or not isinstance(result.get("state"), str)
        or result.get("state") not in (
            "tool_failed", "offline_failed", "audit_failed",
            "unsupported_output", "same_manifest",
            "offline_warnings", "offline_ok",
        )
        or result.get("release_approved") is not False
        or result.get("ingame_approved") is not False
        or result.get("installation_performed") is not False
        or type(result.get("verified_files")) is not int
        or type(result.get("errors")) is not int
    ):
        raise BuildHistoryError("Completed build is not a safe classified result")
    if result["verified_files"] < 0 or result["errors"] < 0:
        raise BuildHistoryError("Negative completion counts")
    for counter in ("verified_bytes", "warnings"):
        if type(result.get(counter)) is not int or result[counter] < 0:
            raise BuildHistoryError("Invalid completion counter")
    if (
        not isinstance(result.get("output"), str)
        or not isinstance(result.get("detail"), str)
        or result.get("no_output_written_by_audit") is not True
        or result.get("offline_integrity_ok") is not (
            result["state"] in ("offline_ok", "offline_warnings", "same_manifest")
        )
    ):
        raise BuildHistoryError("Completion safety flags disagree")
    if (
        result["state"] in ("offline_ok", "offline_warnings", "same_manifest")
        and result["verified_files"] < 1
    ):
        raise BuildHistoryError("Offline integrity success needs audited files")
    issues = result.get("issues")
    if (
        not isinstance(issues, list)
        or len(issues) > 32
        or any(not isinstance(item, str) or len(item) > 2048 for item in issues)
    ):
        raise BuildHistoryError("Invalid stored audit issues")
    digest = result.get("manifest_sha256")
    if digest is not None and (
        not isinstance(digest, str) or SHA.fullmatch(digest) is None
    ):
        raise BuildHistoryError("Completion manifest SHA invalid")
    if result["exit_code"] != 0 and result["state"] != "tool_failed":
        raise BuildHistoryError("Failed CLI must never be recorded as successful")
    if result["state"] == "tool_failed" and result["exit_code"] == 0:
        raise BuildHistoryError("Successful CLI cannot be recorded as failed CLI")
    prior_comparison = result.get("same_manifest_as_before")
    if type(prior_comparison) not in (bool, type(None)):
        raise BuildHistoryError("Invalid prior-manifest comparison flag")
    if result["state"] in OFFLINE_STATES:
        if (
            result["exit_code"] != 0
            or result["errors"] != 0
            or result["verified_bytes"] <= 0
            or not isinstance(digest, str)
            or SHA.fullmatch(digest) is None
            or (result["state"] == "offline_ok" and result["warnings"] != 0)
            or (result["state"] == "offline_warnings" and result["warnings"] == 0)
            or (result["state"] == "same_manifest"
                and prior_comparison is not True)
            or (result["state"] != "same_manifest"
                and prior_comparison is not False)
        ):
            raise BuildHistoryError("Stored offline success lacks consistent proof fields")
    if result["state"] == "tool_failed" and (
        result["verified_files"] != 0
        or result["verified_bytes"] != 0
        or digest is not None
    ):
        raise BuildHistoryError("Failed CLI cannot inherit earlier verified package bytes")


def _check_completed_against_start(before: dict, result: dict) -> None:
    """Cross-link claimed offline provenance to this exact pre-build manifest."""
    old = before.get("prior_manifest_sha256")
    new = result.get("manifest_sha256")
    state = result.get("state")
    if state == "same_manifest" and (
        old is None or new != old
    ):
        raise BuildHistoryError(
            "Identical-manifest claim disagrees with original build snapshot"
        )
    if state in ("offline_ok", "offline_warnings") and (
        new is None or new == old
    ):
        raise BuildHistoryError(
            "Fresh offline result must not reuse the pre-build manifest identity"
        )
    if state in OFFLINE_STATES and result.get("same_manifest_as_before") is not (
        new == old and old is not None
    ):
        raise BuildHistoryError("Offline result comparison contradicts saved before state")


def _validate_record(row: object, sequence: int, predecessor: str | None) -> dict:
    if not isinstance(row, dict) or row.get("schema") != SCHEMA:
        raise BuildHistoryError("Unknown history schema")
    if set(row) != {
        "schema", "sequence", "previous_sha256", "created_utc",
        "run_id", "profile_id", "kind", "payload",
    }:
        raise BuildHistoryError("Unexpected history record fields")
    if (
        type(row["sequence"]) is not int or row["sequence"] != sequence
        or row["previous_sha256"] != predecessor
        or not isinstance(row["created_utc"], str)
        or STAMP.fullmatch(row["created_utc"]) is None
        or not isinstance(row["run_id"], str)
        or RUN_ID.fullmatch(row["run_id"]) is None
        or not isinstance(row["profile_id"], str)
        or ID.fullmatch(row["profile_id"]) is None
        or not isinstance(row["kind"], str)
        or row["kind"] not in KINDS
        or not isinstance(row["payload"], dict)
    ):
        raise BuildHistoryError("Broken history chronology or identity")
    try:
        datetime.fromisoformat(row["created_utc"])
    except ValueError as exc:
        raise BuildHistoryError("Invalid UTC date in history event") from exc
    if row["kind"] == "started":
        _validate_started(row["profile_id"], row["payload"])
    elif row["kind"] == "completed":
        _validate_completed(row["profile_id"], row["payload"])
    else:
        message = row["payload"].get("message")
        fields = (
            {"message"} if row["kind"] == "launch_failed"
            else {"message", "exit_code"}
        )
        if (
            set(row["payload"]) != fields
            or not isinstance(message, str)
            or not 0 < len(message) <= MAX_MESSAGE_CHARS
            or (row["kind"] == "inspection_failed"
                and type(row["payload"].get("exit_code")) is not int)
        ):
            raise BuildHistoryError("Unsafe failure description")
    return row


def _load(root: Path, *, writer_locked: bool = False) -> tuple[list[dict], str | None]:
    directory = _folder(root)
    if not directory.exists():
        return [], None
    names = sorted(directory.iterdir(), key=lambda p: p.name)
    if len(names) > MAX_EVENTS + (1 if writer_locked else 0):
        raise BuildHistoryError("History has exceeded its bounded event count")
    rows: list[dict] = []
    previous: str | None = None
    all_bytes = 0
    sessions: dict[str, dict] = {}
    for path in names:
        if writer_locked and path.name == ".write-lock":
            continue
        if path.name == ".write-lock":
            raise BuildHistoryError(
                "History is being written or has a stale lock; recheck later"
            )
        if _is_link(path) or not path.is_file():
            raise BuildHistoryError("Unsafe file/link in build history")
        match = ENTRY_NAME.fullmatch(path.name)
        if match is None:
            raise BuildHistoryError(f"Unknown build history filename: {path.name}")
        expected_sequence = len(rows) + 1
        if int(match.group(1)) != expected_sequence:
            raise BuildHistoryError("Missing/reordered build history event")
        size = path.stat().st_size
        all_bytes += size
        if not 0 < size <= MAX_FILE_BYTES or all_bytes > MAX_TOTAL_BYTES:
            raise BuildHistoryError("History file size limit exceeded")
        content = path.read_bytes()
        current = sha256(content).hexdigest()
        if len(content) != size or match.group(2) != current:
            raise BuildHistoryError("History file checksum changed")
        try:
            decoded = json.loads(
                content.decode("utf-8"),
                object_pairs_hook=_strict_pairs, parse_constant=_bad_constant,
            )
        except (UnicodeError, ValueError) as exc:
            raise BuildHistoryError(f"Corrupt history JSON: {exc}") from exc
        if _encode(decoded) != content:
            raise BuildHistoryError("Noncanonical history JSON bytes")
        row = _validate_record(decoded, expected_sequence, previous)
        run = sessions.get(row["run_id"])
        if row["kind"] == "started":
            if run is not None:
                raise BuildHistoryError("Duplicated start of one build run")
            sessions[row["run_id"]] = {
                "profile": row["profile_id"], "state": "started",
            }
        else:
            if run is None or run["profile"] != row["profile_id"]:
                raise BuildHistoryError("Result has no matching earlier start")
            if run["state"] != "started":
                raise BuildHistoryError("Build run has multiple terminal results")
            if row["kind"] == "completed":
                old_output = next(
                    item["payload"]["before"]["output"]
                    for item in rows
                    if item["run_id"] == row["run_id"] and item["kind"] == "started"
                )
                if row["payload"]["result"].get("output") != old_output:
                    raise BuildHistoryError("Completed result belongs to another output")
                start_payload = next(
                    item["payload"] for item in rows
                    if item["run_id"] == row["run_id"] and item["kind"] == "started"
                )
                _check_completed_against_start(
                    start_payload["before"], row["payload"]["result"]
                )
            run["state"] = row["kind"]
        rows.append(row)
        previous = current
    return rows, previous


def read_build_history(project_root: str | Path) -> list[dict]:
    """Read and verify *all* journal files; show newest runs first."""
    root = Path(project_root).resolve(strict=True)
    rows, _ = _load(root)
    runs: dict[str, dict] = {}
    for row in rows:
        run_id = row["run_id"]
        if row["kind"] == "started":
            runs[run_id] = {
                "run_id": run_id,
                "profile_id": row["profile_id"],
                "started_utc": row["created_utc"],
                "last_utc": row["created_utc"],
                "state": "unbestaetigt",
                "result": None,
                "message": (
                    "Ein Start wurde aufgezeichnet, aber kein Abschluss. "
                    "Nach Neustart/Abbruch ist der Build nicht als bestanden bestätigt."
                ),
                "start_sequence": row["sequence"],
                "replace": row["payload"]["replace"],
                "before": row["payload"]["before"],
                "source_hashes": row["payload"].get("source_hashes"),
            }
        else:
            run = runs[run_id]
            run["last_utc"] = row["created_utc"]
            if row["kind"] == "completed":
                run["result"] = row["payload"]["result"]
                run["state"] = row["payload"]["result"]["state"]
                run["message"] = row["payload"]["result"]["detail"]
            else:
                run["state"] = (
                    "start_fehlgeschlagen" if row["kind"] == "launch_failed"
                    else "abschlusspruefung_fehlgeschlagen"
                )
                run["message"] = row["payload"]["message"]
    return sorted(
        runs.values(), key=lambda item: item["start_sequence"], reverse=True
    )


def _append(
    project_root: str | Path, kind: str, run_id: str,
    profile_id: str, payload: dict,
) -> Path:
    if (
        kind not in KINDS or not isinstance(run_id, str)
        or RUN_ID.fullmatch(run_id) is None
        or not isinstance(profile_id, str) or ID.fullmatch(profile_id) is None
        or not isinstance(payload, dict)
    ):
        raise BuildHistoryError("Invalid new build event")
    root = Path(project_root).resolve(strict=True)
    # Reject structurally invalid payloads before creating even an empty
    # journal directory. Cross-event provenance remains checked under lock.
    if kind == "started":
        _validate_started(profile_id, payload)
    elif kind == "completed":
        _validate_completed(profile_id, payload)
    directory = _folder(root, create=True)
    mutex = directory / ".write-lock"
    try:
        mutex.mkdir()
    except FileExistsError as exc:
        raise BuildHistoryError(
            "History writer busy or stale lock; manual inspection required"
        ) from exc
    temp: Path | None = None
    try:
        rows, digest = _load(root, writer_locked=True)
        if len(rows) >= MAX_EVENTS:
            raise BuildHistoryError(
                "Build history full; archive externally before adding new runs"
            )
        if kind == "started":
            if any(row["run_id"] == run_id for row in rows):
                raise BuildHistoryError("Run identity already exists")
        else:
            previous = [
                row for row in rows if row["run_id"] == run_id
            ]
            if (
                len(previous) != 1 or previous[0]["kind"] != "started"
                or previous[0]["profile_id"] != profile_id
            ):
                raise BuildHistoryError("No single outstanding start for this result")
            if kind == "completed":
                result = payload.get("result", {})
                initial = previous[0]["payload"]["before"]
                if result.get("output") != initial["output"]:
                    raise BuildHistoryError(
                        "Completed result is not for the original build output"
                    )
                _validate_completed(profile_id, payload)
                _check_completed_against_start(initial, result)
        number = len(rows) + 1
        data = {
            "schema": SCHEMA,
            "sequence": number,
            "previous_sha256": digest,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "run_id": run_id,
            "profile_id": profile_id,
            "kind": kind,
            "payload": payload,
        }
        _validate_record(data, number, digest)
        content = _encode(data)
        if len(content) > MAX_FILE_BYTES:
            raise BuildHistoryError("Build history payload exceeds size limit")
        target = directory / f"{number:06d}-{sha256(content).hexdigest()}.json"
        fd, path = tempfile.mkstemp(prefix=".temporary-", dir=directory)
        temp = Path(path)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            # os.link() is atomic and refuses to overwrite an existing name.
            # This works on the authorised local NTFS project volume.
            os.link(temp, target)
        finally:
            temp.unlink(missing_ok=True)
            temp = None
        return target
    except (OSError, ValueError) as exc:
        if isinstance(exc, BuildHistoryError):
            raise
        raise BuildHistoryError(f"Could not append build history: {exc}") from exc
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
        mutex.rmdir()


def append_started(
    root: str | Path, profile_id: str, before: dict, *, replace: bool,
    source_hashes: dict[str, str] | None = None,
) -> str:
    """Record the exact source identities checked immediately before launch."""
    if type(replace) is not bool:
        raise BuildHistoryError("Invalid replace intent")
    payload: dict = {"before": before, "replace": replace}
    if source_hashes is not None:
        if not isinstance(source_hashes, dict):
            raise BuildHistoryError("Invalid source identity envelope")
        payload["source_hashes"] = dict(source_hashes)
    run_id = secrets.token_hex(16)
    _append(root, "started", run_id, profile_id, payload)
    return run_id


def append_completed(
    root: str | Path, run_id: str, profile_id: str, result: dict,
) -> Path:
    return _append(
        root, "completed", run_id, profile_id, {"result": result}
    )


def append_launch_failed(
    root: str | Path, run_id: str, profile_id: str, message: str,
) -> Path:
    if not isinstance(message, str):
        raise BuildHistoryError("Invalid launch failure")
    return _append(
        root, "launch_failed", run_id, profile_id,
        {"message": message[:MAX_MESSAGE_CHARS]},
    )


def append_inspection_failed(
    root: str | Path, run_id: str, profile_id: str,
    exit_code: int, message: str,
) -> Path:
    if type(exit_code) is not int or not isinstance(message, str):
        raise BuildHistoryError("Invalid inspection failure")
    return _append(
        root, "inspection_failed", run_id, profile_id,
        {"exit_code": exit_code, "message": message[:MAX_MESSAGE_CHARS]},
    )


__all__ = [
    "SCHEMA", "BuildHistoryError", "read_build_history",
    "append_started", "append_completed", "append_launch_failed",
    "append_inspection_failed",
]
