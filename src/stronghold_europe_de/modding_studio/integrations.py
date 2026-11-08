"""Explicit, SHA-bound adapters for Serps' separately installed file tools.

This does not import or vendor Serps code. By default only documented read-only
subcommands are offered. An explicit export uses a fresh isolated workspace
output, never a source file or installed game directory.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from .safety import (
    StudioError, canonical_root, child_path, is_link, read_file,
    require_id, require_sha,
)

HELPERS = {
    "mapparser": {
        "info": ((".map", ".trail"), False),
        "list": ((".map", ".trail"), False),
        "keeps": ((".map", ".trail"), False),
        "validate": ((".map", ".trail"), False),
    },
    "aivparser": {
        "validate": ((".aivjson",), False),
        "inspect": ((".aivjson",), True),
    },
    "traileditor": {
        "inspect": ((".trail",), False),
        "validate": ((".trail", ".json"), False),
        "export": ((".trail",), True),
    },
}
MAX_EXTERNAL_OUTPUT_BYTES = 16 * 1024 * 1024


def _sha_file(path: Path, maximum: int) -> str:
    if not path.is_file() or is_link(path) or path.resolve(strict=True) != path:
        raise StudioError("external executable is not a canonical regular nonlinked file")
    if not 1 <= path.stat().st_size <= maximum:
        raise StudioError("external executable has unsupported byte size")
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_helper(
    workspace: Path, helper: str, action: str, relative_source: str,
    source_sha256: str, executable: Path, executable_sha256: str,
    output_id: str = "",
) -> dict[str, Any]:
    root = canonical_root(workspace)
    entry = HELPERS.get(helper, {}).get(action)
    if entry is None:
        raise StudioError("unknown or unsupported Serp helper read-only operation")
    extensions, writes_new = entry
    require_sha(source_sha256, "expected source SHA-256")
    require_sha(executable_sha256, "expected helper binary SHA-256")
    source = child_path(root, relative_source, require_file=True)
    if not source.name.lower().endswith(extensions):
        raise StudioError("source extension is not supported by selected helper")
    if sha256(read_file(root, relative_source)).hexdigest() != source_sha256:
        raise StudioError("source SHA-256 differs before helper execution")
    executable = Path(executable).absolute()
    if not executable.name.lower().endswith(".exe"):
        raise StudioError("helper must be an explicitly selected Windows EXE")
    if _sha_file(executable, 256 * 1024 * 1024) != executable_sha256:
        raise StudioError("helper executable SHA-256 does not match approved binary")
    if writes_new and not output_id:
        raise StudioError("exporting helper operation requires an explicit output ID")
    if not writes_new and output_id:
        raise StudioError("read-only helper operation does not accept an output ID")
    args = [str(executable), action, str(source)]
    output = None
    stage = None
    destination = None
    if writes_new:
        output_id = require_id(output_id, "helper output_id")
        outputs = child_path(root, "helper-outputs")
        if not outputs.exists():
            outputs.mkdir()
        destination = child_path(root, "helper-outputs/" + output_id)
        if destination.exists():
            raise StudioError("refusing to replace a previous helper output")
        stage = Path(tempfile.mkdtemp(prefix=".helper-stage-", dir=outputs))
        args += ["-o", str(stage)]
    # External tools can default to writing in their current directory.
    # The author workspace must never be their working directory.
    work_dir = stage if stage is not None else Path(
        tempfile.mkdtemp(prefix="spritesuite-helper-readonly-")
    )
    try:
        # Never use shell=True; prevent arbitrary extra parameters, inherited
        # working-directory writes and invisible process execution.
        with tempfile.TemporaryFile(mode="w+b") as temp:
            try:
                process = subprocess.Popen(
                    args,
                    cwd=str(work_dir),
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    stdout=temp,
                    stderr=subprocess.STDOUT,
                    env={key: value for key, value in os.environ.items()
                         if key.upper() not in {"PYTHONPATH", "PYTHONHOME"}},
                )
                try:
                    exit_code = process.wait(timeout=60)
                except subprocess.TimeoutExpired as exc:
                    process.kill()
                    process.wait(timeout=15)
                    raise StudioError("helper timed out and was terminated") from exc
            except OSError as exc:
                raise StudioError("helper failed to start: " + str(exc)) from exc
            temp.seek(0, 2)
            length = temp.tell()
            if length > MAX_EXTERNAL_OUTPUT_BYTES:
                raise StudioError("helper output exceeded the 16-MiB diagnostic limit")
            temp.seek(0)
            output = temp.read().decode("utf-8", "replace")
        if sha256(read_file(root, relative_source)).hexdigest() != source_sha256:
            raise StudioError("helper mutated the original source; reject the result")
        if exit_code != 0:
            raise StudioError(
                f"helper returned exit code {exit_code}: " + output[-2000:]
            )
        generated = []
        if stage is not None:
            paths = sorted(stage.rglob("*"))
            if len(paths) > 2048:
                raise StudioError("helper created too many output entries")
            for path in paths:
                if is_link(path):
                    raise StudioError("helper generated linked output")
                if path.is_file():
                    if path.stat().st_size > MAX_EXTERNAL_OUTPUT_BYTES:
                        raise StudioError("helper generated an oversized output")
                    generated.append({
                        "path": path.relative_to(stage).as_posix(),
                        "sha256": _sha_file(path, MAX_EXTERNAL_OUTPUT_BYTES),
                        "bytes": path.stat().st_size,
                    })
                elif not path.is_dir():
                    raise StudioError("helper generated unsupported output type")
            if not generated:
                raise StudioError("helper export did not create any files")
            if destination is None or destination.exists():
                raise StudioError("helper output destination is no longer available")
            os.rename(stage, destination)
            stage = None
        return {
            "schema": "spritesuite.modding-studio.helper-proof.v1",
            "helper": helper, "action": action,
            "original_source_sha256": source_sha256,
            "helper_executable_sha256": executable_sha256,
            "exit_code": 0, "stdout": output[:100_000],
            "generated": generated,
            "output_folder": str(destination) if destination else None,
            "in_game_compatibility": "not_established",
        }
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        elif work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)
