"""CLI for all twelve offline authoring tools, with no game installation path."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .catalog import MODULE_IDS, MODULES, search, version_evidence
from .design import simulate_mission
from .engine import analyze, analyze_suite_ui
from .exporter import export_project
from .integrations import HELPERS, run_helper
from .knowledge import search_native_baseline, search_api_surface, attest_native_image
from .model import (
    PROJECT_FILENAME, load_project, new_project, next_revision,
    validate_project,
)
from .safety import StudioError, json_bytes, read_json, require_sha

def _print(value: object) -> None:
    sys.stdout.buffer.write(json_bytes(value))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="modding_studio",
        description="SpriteSuite 3: twelve read-only/author-owned offline SHCDE tools.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog", help="Search pinned APIShared/SE capabilities")
    catalog.add_argument("--query", default="")
    catalog.add_argument("--module", choices=MODULE_IDS, default="")
    catalog.add_argument("--json", action="store_true")
    commands.add_parser("modules", help="List the twelve available Studio tools")

    init = commands.add_parser("new", help="Create an immutable starter project")
    init.add_argument("workspace", type=Path)
    init.add_argument("--id", required=True)
    init.add_argument("--title", required=True)

    for name in ("check", "export", "simulate", "revise"):
        cmd = commands.add_parser(name)
        cmd.add_argument("workspace", type=Path)
        cmd.add_argument("--project", default=PROJECT_FILENAME)
        if name == "check":
            cmd.add_argument("--module", choices=MODULE_IDS, default="")
            cmd.add_argument("--json", action="store_true")
        if name == "export":
            cmd.add_argument("--export-id", required=True)
        if name == "simulate":
            cmd.add_argument("--events", required=True, help="Workspace-relative JSON event timeline")
        if name == "revise":
            cmd.add_argument("--edited", required=True, help="New project JSON under the workspace")
            cmd.add_argument("--expected-sha256", required=True, help="Optimistic source lease")
    suite = commands.add_parser("audit-suite-ui")
    suite.add_argument("--suite-root", type=Path, default=Path(__file__).resolve().parents[3])
    suite.add_argument("--json", action="store_true")
    native_search = commands.add_parser(
        "native-search", help="Search Serps hash-bound native analysis JSONL"
    )
    native_search.add_argument("--baseline-root", type=Path, required=True)
    native_search.add_argument("--query", default="")
    native_search.add_argument("--limit", type=int, default=30)
    api_surface = commands.add_parser(
        "api-search", help="Search a locally supplied APIShared PublicApi.txt"
    )
    api_surface.add_argument("--api-root", type=Path, required=True)
    api_surface.add_argument("--query", required=True)
    api_surface.add_argument("--limit", type=int, default=50)
    image = commands.add_parser(
        "native-image", help="Check an exact native DLL SHA without loading the game"
    )
    image.add_argument("--dll", type=Path, required=True)

    helper = commands.add_parser(
        "helper",
        help="Run one explicitly SHA-bound Serp MapParser/AIVParser/TrailEditor command",
    )
    helper.add_argument("workspace", type=Path)
    helper.add_argument("--tool", choices=sorted(HELPERS), required=True)
    helper.add_argument("--action", required=True)
    helper.add_argument("--source", required=True)
    helper.add_argument("--source-sha256", required=True)
    helper.add_argument("--executable", type=Path, required=True)
    helper.add_argument("--executable-sha256", required=True)
    helper.add_argument("--output-id", default="")
    gui = commands.add_parser("gui", help="Launch the integrated Tk authoring GUI")
    gui.add_argument("workspace", nargs="?", type=Path, default=None)

    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            rows = search(args.query, module=args.module)
            if args.json:
                _print({"schema": "spritesuite.studio.api-catalog.v1",
                        "source_pins": version_evidence(), "capabilities": rows})
            else:
                for entry in rows:
                    print(
                        f"{entry['module']:<10} {entry['key']:<24} "
                        f"API >= {entry['minimum_api_shared']}  {entry['name']}"
                    )
                print(f"{len(rows)} capabilities (source snapshot, no installation claim)")
            return 0
        if args.command == "modules":
            for i, (_, title, summary) in enumerate(MODULES, 1):
                print(f"{i:02d}. {title}: {summary}")
            return 0
        if args.command == "new":
            result = new_project(args.workspace, args.id, args.title)
            print("Created immutable offline project: " + str(result))
            return 0
        if args.command == "audit-suite-ui":
            result = analyze_suite_ui(args.suite_root)
            if args.json:
                _print(result)
            else:
                print(
                    f"Source {result['source_count']} | wall {result['wall_source_count']} "
                    f"| explicit XAML refs {result['wall_referenced_count']}"
                )
                for path in result["missing_wall_refs"]:
                    print("NOT CONFIRMED IN XAML:", path)
            return 0
        if args.command == "gui":
            from .gui import launch
            return launch(args.workspace)
        if args.command == "native-search":
            _print(search_native_baseline(
                args.baseline_root, args.query, args.limit,
            ))
            return 0
        if args.command == "api-search":
            _print(search_api_surface(args.api_root, args.query, args.limit))
            return 0
        if args.command == "native-image":
            _print(attest_native_image(args.dll))
            return 0
        if args.command == "helper":
            _print(run_helper(
                args.workspace, args.tool, args.action,
                args.source, args.source_sha256,
                args.executable, args.executable_sha256,
                args.output_id,
            ))
            return 0
        project, digest = load_project(args.workspace, args.project)
        if args.command == "check":
            report = analyze(args.workspace, project, only=args.module)
            if args.json:
                _print(report)
            else:
                print(
                    f"SpriteSuite source review: {report['status']}, "
                    f"project={report['project_id']}, revision={report['revision']}"
                )
                for module, details in report["modules"].items():
                    print(module, details["status"], len(details["findings"]), "findings")
                    for row in details["findings"]:
                        print(" ", row["severity"], row["code"], row["message"])
            return 2 if report["status"] == "BLOCKED" else 0
        if args.command == "export":
            path, info = export_project(args.workspace, project, args.export_id)
            print("Offline-only export, no game installation: " + str(path))
            print(f"Files: {len(info['files'])}; state={info['status']}")
            return 0
        if args.command == "simulate":
            result = simulate_mission(
                project["modules"]["mission"],
                read_json(args.workspace, args.events),
            )
            _print(result)
            return 0
        if args.command == "revise":
            edited = read_json(args.workspace, args.edited)
            source = require_sha(args.expected_sha256)
            path = next_revision(
                args.workspace, project, edited, source, args.project,
            )
            print("Published a new immutable project revision: " + str(path))
            return 0
        parser.error("unsupported action")
    except (StudioError, OSError, ValueError) as exc:
        print("STUDIO BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
