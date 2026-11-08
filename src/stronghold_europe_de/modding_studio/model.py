"""Strict version-one project format for twelve isolated Studio tools."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import os
import re
from secrets import token_hex
from typing import Any

from .catalog import (
    API_RELEASE, MIN_SCRIPT_EXTENDER, MODULE_IDS,
    NATIVE_BASELINE_SHA256, minimum_api, version_tuple,
)
from .safety import (
    MAX_PROJECT_BYTES, StudioError, canonical_root, child_path, create_json, json_bytes,
    nfc, read_file, read_json, relative_path, require_id, require_sha,
)

SCHEMA = "spritesuite.modding-studio.project.v1"
PROJECT_FILENAME = "project.json"
SECTION_FIELDS = {
    "sdk": {"requires"},
    "mission": {"triggers"},
    "castle": {"grid_size", "buildings"},
    "hud": {"xaml_files", "expected_images"},
    "balance": {"cost_rules"},
    "maps": {"resources"},
    "lords": {"profiles"},
    "units": {"grid", "routes"},
    "audio": {"clips", "cues"},
    "saves": {"records", "peers"},
    "workshop": {"mods"},
    "native": {"sites"},
}
LIST_LIMIT = 512

def project_template(project_id: str, title: str) -> dict[str, Any]:
    require_id(project_id, "project_id")
    nfc(title, "title", 160)
    return {
        "schema": SCHEMA,
        "project_id": project_id,
        "title": title,
        "revision": 1,
        "target": {
            "game": "SHCDE",
            "api_shared": API_RELEASE,
            "script_extender": MIN_SCRIPT_EXTENDER,
            "native_sha256": NATIVE_BASELINE_SHA256,
            "mode": "offline",
        },
        "modules": {
            "sdk": {"requires": []},
            "mission": {"triggers": []},
            "castle": {"grid_size": 100, "buildings": []},
            "hud": {"xaml_files": [], "expected_images": []},
            "balance": {"cost_rules": []},
            "maps": {"resources": []},
            "lords": {"profiles": []},
            "units": {
                "grid": {"width": 16, "height": 16, "blocked": [], "penalties": []},
                "routes": [],
            },
            "audio": {"clips": [], "cues": []},
            "saves": {"records": [], "peers": []},
            "workshop": {"mods": []},
            "native": {"sites": []},
        },
    }


def _keys(value: object, required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        raise StudioError(f"{label} must contain exactly {sorted(required)}")
    return value


def _array(value: object, label: str) -> list:
    if not isinstance(value, list) or len(value) > LIST_LIMIT:
        raise StudioError(f"{label} must be a bounded array (0..{LIST_LIMIT})")
    return value


def _unsigned(value: object, label: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise StudioError(f"{label} must be an integer in {low}..{high}")
    return value


def validate_project(raw: object) -> dict[str, Any]:
    project = _keys(
        raw, {"schema", "project_id", "title", "revision", "target", "modules"},
        "project",
    )
    if project["schema"] != SCHEMA:
        raise StudioError("unknown SpriteSuite Modding Studio project schema")
    require_id(project["project_id"], "project_id")
    nfc(project["title"], "title", 160)
    _unsigned(project["revision"], "revision", 1, 2_000_000)
    target = _keys(
        project["target"],
        {"game", "api_shared", "script_extender", "native_sha256", "mode"},
        "target",
    )
    if target["game"] != "SHCDE":
        raise StudioError("project is not an SHCDE target")
    if target["mode"] != "offline":
        raise StudioError("only the offline/no-install target mode is supported")
    version_tuple(target["api_shared"])
    version_tuple(target["script_extender"])
    require_sha(target["native_sha256"], "target.native_sha256")
    modules = _keys(project["modules"], set(MODULE_IDS), "modules")
    for module_id, keys in SECTION_FIELDS.items():
        section = _keys(modules[module_id], keys, "modules." + module_id)
        for name, value in section.items():
            if isinstance(value, list):
                _array(value, module_id + "." + name)
    grid_size = modules["castle"]["grid_size"]
    _unsigned(grid_size, "castle.grid_size", 1, 100)
    grid = _keys(
        modules["units"]["grid"],
        {"width", "height", "blocked", "penalties"},
        "units.grid",
    )
    _unsigned(grid["width"], "units.grid.width", 1, 128)
    _unsigned(grid["height"], "units.grid.height", 1, 128)
    _array(grid["blocked"], "units.grid.blocked")
    _array(grid["penalties"], "units.grid.penalties")
    required = _array(modules["sdk"]["requires"], "sdk.requires")
    if len(required) != len(set(map(str, required))):
        raise StudioError("SDK requirement keys are duplicated")
    minimum_api(required)
    # Reject any custom project property not explicitly defined above.
    return deepcopy(project)


def new_project(project_directory: Path, project_id: str, title: str) -> Path:
    destination = Path(project_directory).absolute()
    if destination.exists():
        raise StudioError(f"refusing to reuse existing project directory: {destination}")
    parent = canonical_root(destination.parent)
    destination = parent / destination.name
    destination.mkdir()
    try:
        return create_json(destination, PROJECT_FILENAME, project_template(project_id, title))
    except Exception:
        if not any(destination.iterdir()):
            destination.rmdir()
        raise


def load_project(
    project_directory: Path, relative: str = PROJECT_FILENAME
) -> tuple[dict[str, Any], str]:
    root = canonical_root(project_directory)
    relative_path(relative, "project filename")
    if not relative.endswith(".json"):
        raise StudioError("project source must be a JSON file")
    payload = read_file(root, relative, maximum=MAX_PROJECT_BYTES)
    raw = read_json(root, relative, maximum=MAX_PROJECT_BYTES)
    return validate_project(raw), sha256(payload).hexdigest()


def load_current_project(project_directory: Path) -> tuple[dict[str, Any], str, str]:
    """Reopen the exact saved revision, with a bounded path and full byte hash."""
    root = canonical_root(project_directory)
    pointer = child_path(root, "current.json")
    if not pointer.exists():
        project, digest = load_project(root)
        return project, digest, PROJECT_FILENAME
    raw = read_file(root, "current.json", 4096)
    import json
    try:
        info = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise StudioError("invalid saved Studio revision pointer") from exc
    if not isinstance(info, dict) or info.get("schema") != "spritesuite.studio-current.v1":
        raise StudioError("unknown saved Studio revision pointer")
    source = info.get("source")
    if not isinstance(source, str) or not re.fullmatch(
            r"project\.json|revisions/[0-9]{6}-[a-f0-9]{16}\.json", source):
        raise StudioError("invalid saved Studio revision path")
    expected = require_sha(info.get("sha256"), "saved Studio source SHA-256")
    project, actual = load_project(root, source)
    if actual != expected:
        raise StudioError("saved Studio revision SHA-256 does not match")
    original, _ = load_project(root)
    if any(project[key] != original[key] for key in ("schema", "project_id", "target")):
        raise StudioError("saved Studio revision belongs to another project")
    return project, actual, source


def _remember_current(root: Path, source: Path) -> None:
    import json
    destination = child_path(root, "current.json")
    relative = source.relative_to(root).as_posix()
    info = {"schema": "spritesuite.studio-current.v1", "source": relative,
            "sha256": sha256(read_file(root, relative, MAX_PROJECT_BYTES)).hexdigest()}
    temporary = child_path(root, ".current-" + token_hex(8) + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(info, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def next_revision(
    project_directory: Path,
    original: dict[str, Any],
    edited: object,
    expected_original_sha: str,
    source_path: str = PROJECT_FILENAME,
) -> Path:
    root = canonical_root(project_directory)
    require_sha(expected_original_sha, "expected_original_sha")
    if sha256(read_file(root, source_path, MAX_PROJECT_BYTES)).hexdigest() != expected_original_sha:
        raise StudioError("project changed since the editor loaded it")
    old = validate_project(original)
    if not isinstance(edited, dict):
        raise StudioError("edited project must be a JSON object")
    new = validate_project(edited)
    for field in ("schema", "project_id", "target"):
        if new[field] != old[field]:
            raise StudioError(f"cannot silently rewrite pinned project {field}")
    if new["revision"] != old["revision"] + 1:
        raise StudioError("new revision must be exactly previous revision + one")
    relative = f"revisions/{new['revision']:06d}-{sha256(json_bytes(new)).hexdigest()[:16]}.json"
    saved = child_path(root, relative)
    if saved.exists():
        if read_file(root, relative, MAX_PROJECT_BYTES) != json_bytes(new):
            raise StudioError("existing revision has different bytes")
    else:
        saved = create_json(root, relative, new)
    _remember_current(root, saved)
    return saved


def project_manifest_digest(project: dict[str, Any]) -> str:
    return sha256(json_bytes(validate_project(project))).hexdigest()
