"""Deterministic, no-install Studio report export to a new owned directory."""
from __future__ import annotations

from hashlib import sha256
import html
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from .catalog import MODULE_IDS, MODULE_DESCRIPTIONS, version_evidence
from .engine import analyze
from .model import validate_project
from .scaffold import plugin_scaffold
from .safety import StudioError, canonical_root, child_path, json_bytes, require_id

STATUS_COLORS = {
    "BLOCKED": "#bc514a", "REVIEW": "#a87328", "SOURCE_PASS": "#30896e"
}


def _lua_string(s: str) -> str:
    # Lua byte strings support UTF-8; quote control characters exactly.
    buf = ['"']
    for ch in s:
        n = ord(ch)
        if ch == "\\":
            buf.append("\\\\")
        elif ch == '"':
            buf.append('\\"')
        elif n == 10:
            buf.append("\\n")
        elif n == 13:
            buf.append("\\r")
        elif n == 9:
            buf.append("\\t")
        elif n < 32 or n == 127:
            buf.append("\\" + f"{n:03d}")
        else:
            buf.append(ch)
    return "".join(buf) + '"'


def _to_lua(value: Any, level: int = 0) -> str:
    if level > 16:
        raise StudioError("mission JSON is nested too deeply")
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) is str:
        return _lua_string(value)
    if type(value) is int:
        return str(value)
    if isinstance(value, list):
        return "{" + ", ".join(_to_lua(item, level + 1) for item in value) + "}"
    if isinstance(value, dict):
        return "{" + ", ".join(
            "[" + _lua_string(k) + "] = " + _to_lua(v, level + 1)
            for k, v in sorted(value.items())
        ) + "}"
    raise StudioError("Lua plan serializer supports only JSON-safe literals")


def mission_data_lua(project: dict) -> bytes:
    """A Lua *data module*, not an auto-registered Script Extender mission hook."""
    plan = {
        "schema": "spritesuite.mission.plan.v1",
        "project_id": project["project_id"],
        "triggers": project["modules"]["mission"]["triggers"],
        "requires_explicit_verified_event_adapter": True,
    }
    return (
        "-- SpriteSuite offline mission data. No gameplay hooks are registered here.\n"
        "-- Verify event contracts and use a separately approved runtime consumer.\n"
        "return " + _to_lua(plan) + "\n"
    ).encode("utf-8")


def castle_svg(report: dict) -> bytes:
    report = report["modules"]["castle"]
    layout = report["facts"]["elements"]
    size = report["facts"]["grid_size"]
    cell = 5 if size == 100 else max(5, int(480 / size))
    canvas = size * cell
    colours = ("#73abc7", "#daa86d", "#9a84bf", "#6baa9b", "#c78484")
    rows = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas}" '
        f'height="{canvas}" viewBox="0 0 {canvas} {canvas}">',
        f'<rect width="{canvas}" height="{canvas}" fill="#1b2026"/>',
    ]
    for i, row in enumerate(layout):
        if not isinstance(row, dict):
            continue
        x = row["x"] * cell
        y = row["y"] * cell
        w = row["width"] * cell
        h = row["height"] * cell
        # Fixed hex colours and validated integer geometry; no embedded assets.
        rows.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'fill="{colours[i % len(colours)]}" stroke="#f7f3e7" '
            'stroke-width="1" opacity="0.85"/>'
        )
    rows.append("</svg>")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _overview_html(report: dict, project: dict) -> bytes:
    title = html.escape(project["title"])
    entries = []
    for module in MODULE_IDS:
        item = report["modules"][module]
        status = item["status"]
        label = html.escape(MODULE_DESCRIPTIONS[module][0])
        issues = len(item["findings"])
        entries.append(
            '<div class="tile"><h2>' + label + '</h2>'
            '<p class="state" style="color:' + STATUS_COLORS[status] + '">'
            + html.escape(status) + '</p><p>'
            + str(issues) + ' Prüfhinweise</p></div>'
        )
    body = "\n".join(entries)
    return (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>SpriteSuite 3: ' + title + '</title><style>'
        'body{margin:0;padding:2rem;background:#171b22;color:#f0eee9;'
        'font:16px system-ui,sans-serif}main{max-width:1200px;margin:auto}'
        '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));'
        'gap:1rem}.tile{background:#262b35;border:1px solid #424a5c;'
        'border-radius:12px;padding:1rem}h2{font-size:1rem}a{color:#96bedc}'
        '.state{font-weight:700}small{color:#c8c8d0}'
        '</style></head><body><main><h1>SpriteSuite 3 – '
        + title + '</h1><p>Nur Offline-Entwurf: keine Spielinstallation, '
        'kein Unity-Build, kein Ingame-Test.</p><div class="grid">'
        + body + '</div><p><small>Für vollständige Befunde report.json öffnen. '
        'Auch SOURCE_PASS beweist keine Spielkompatibilität.</small></p>'
        '</main></body></html>\n'
    ).encode("utf-8")


def export_project(root: Path, project: dict, export_id: str) -> tuple[Path, dict]:
    root = canonical_root(root)
    project = validate_project(project)
    export_id = require_id(export_id, "export_id")
    report = analyze(root, project)
    if report["status"] == "BLOCKED":
        raise StudioError("cannot export a project with blocking validation issues")
    outputs: dict[str, bytes] = {
        "project-snapshot.json": json_bytes(project),
        "report.json": json_bytes(report),
        "sdk/sources.json": json_bytes(version_evidence()),
        "mission/trigger-plan.lua": mission_data_lua(project),
        "castle/layout.svg": castle_svg(report),
        "index.html": _overview_html(report, project),
    }
    for module in MODULE_IDS:
        outputs[f"modules/{module}.json"] = json_bytes(report["modules"][module])
    outputs.update(plugin_scaffold(project))
    manifest = {
        "schema": "spritesuite.modding-studio.export.v1",
        "source_project": project["project_id"],
        "revision": project["revision"],
        "status": report["status"],
        "game_installation": "not_touched",
        "script_extender_adapter": "not_built",
        "in_game_compatibility": "not_established",
        "files": [
            {
                "path": path,
                "bytes": len(payload),
                "sha256": sha256(payload).hexdigest(),
            }
            for path, payload in sorted(outputs.items())
        ],
    }
    outputs["export-manifest.json"] = json_bytes(manifest)
    # All publication goes into one new directory. The staging directory
    # never becomes an export if a file creation or analysis fails.
    root_exports = child_path(root, "exports")
    if not root_exports.exists():
        root_exports.mkdir()
    if not root_exports.is_dir():
        raise StudioError("exports is not a directory")
    destination = child_path(root, "exports/" + export_id)
    if destination.exists():
        raise StudioError("refusing to overwrite a previous immutable export")
    stage = Path(tempfile.mkdtemp(prefix=".studio-stage-", dir=root_exports))
    try:
        for relative, payload in sorted(outputs.items()):
            relative_file = stage.joinpath(*relative.split("/"))
            relative_file.parent.mkdir(exist_ok=True, parents=True)
            with relative_file.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        if destination.exists():
            raise StudioError("export destination appeared concurrently")
        os.rename(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return destination, manifest
