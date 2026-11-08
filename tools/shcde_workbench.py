#!/usr/bin/env python3
"""SpriteSuite SHCDE Workbench: shared GUI for 16 modding areas and real tools.

Launch without arguments for the interactive Tk workspace. --catalog prints
machine-readable capabilities; --self-test checks offline structure without
opening a desktop window. All game-writing operations require an explicit
tool invocation; browsing never starts or changes the game.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from shcde_mod_project import DOMAINS, EDITORS

ROOT = Path(__file__).resolve().parents[1]


def catalog() -> dict:
    return {
        "schema": "spritesuite.shcde.workbench.v1",
        "domainCount": len(DOMAINS),
        "domains": [
            {"id": name, "title": title,
             "tools": [{"file": script, "installed": (ROOT / "tools" / script).is_file()}
                       for script in EDITORS.get(name, ())]}
            for name, title in DOMAINS.items()
        ],
        "nativeGameEditorIncludesAll16": False,
        "assetAndProjectDomainsIntegrated": True,
        "apiRuntimeVerifiedOnlyWhenBuiltAgainstGame": True,
        "gameLaunchRequiredForNativeHookVerification": True,
        "gameWasStarted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", action="store_true",
                        help="List all workspaces, their linked tools and availability")
    parser.add_argument("--self-test", action="store_true",
                        help="Validate the shared project/tool wiring without opening a GUI")
    parser.add_argument("--project", type=Path,
                        help="Existing SpriteSuite SHCDE project directory")
    parser.add_argument("--gui", action="store_true",
                        help="Open graphical SHCDE workbench (also the default)")
    args = parser.parse_args(argv)
    try:
        if args.catalog or args.self_test:
            results = catalog()
            if args.self_test:
                mandatory = (
                    "shcde_api_native_index.py",
                    "shcde_mod_composer.py", "shcde_mod_project.py",
                    "shcde_scenario_graph.py", "shcde_game_inspector.py",
                    "shcde_gameplay_rules.py", "shcde_qa_suite.py",
                    "shcde_mod_settings.py",
                )
                results["selfTestPassed"] = (
                    len(DOMAINS) == 16 and
                    all((ROOT / "tools" / item).is_file() for item in mandatory)
                )
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 0 if results.get("selfTestPassed", True) else 2
        from shcde_workbench_gui import WorkbenchWindow
        app = WorkbenchWindow(project=args.project)
        app.mainloop()
        return 0
    except (OSError, ValueError, ImportError) as err:
        print("SpriteSuite SHCDE workbench: " + str(err), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
