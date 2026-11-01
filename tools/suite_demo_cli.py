r"""Run the same genuine SpriteSuite module demos without the graphical window.

Usage:
  python tools/suite_demo_cli.py --list
  python tools/suite_demo_cli.py --module noesis --source C:\game\FrontendMenus.xaml
  python tools/suite_demo_cli.py --module pixels
  python tools/suite_demo_cli.py --all [--video E:\private\sample.webm]

For each module this calls the EXACT demo backend used by the GUI, creates new
private work/demo-sessions outputs, verifies recorded bytes and prints paths.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from suite_demo_engine import MODULES, MODULE_BY_KEY, DemoSession


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--list",action="store_true",help="List individually runnable modules")
    choice.add_argument("--module",choices=sorted(MODULE_BY_KEY),help="One module")
    choice.add_argument("--all",action="store_true",help="All modules with supplied inputs")
    parser.add_argument("--source",type=Path,help="Read-only user-owned original Noesis XAML")
    parser.add_argument("--video",type=Path,help="Read-only, genuine WebM source")
    args=parser.parse_args(argv)
    if args.list:
        for item in MODULES:
            print(f"{item.key:11s} {item.title} ({len(item.steps)} Schritte)")
        return 0
    names=[item.key for item in MODULES] if args.all else [args.module]
    success=[]
    failed=[]
    skipped=[]
    for key in names:
        if key=="video" and args.video is None:
            skipped.append({"module":key,"reason":"Echtes WebM benötigt"})
            continue
        source=(args.video if key=="video" else
                args.source if key in {"noesis","patch"} else None)
        try:
            session=DemoSession.start(key,source=source)
            for step in session.module.steps:
                result=session.execute_next()
                print(f"{key}: {result['title']} – {result['message']}",flush=True)
            verified=session.verify_receipts()
            if not verified["valid"]:
                raise RuntimeError("Ausgabebelege unterscheiden sich: "+
                                   repr(verified["problems"]))
            success.append({"module":key,"project":str(session.project),
                            "report":str(session.root/"demo-protokoll.json"),
                            "steps":len(session.receipts),
                            "verified_outputs":verified["current_files"]})
        except (OSError,ValueError,RuntimeError) as error:
            failed.append({"module":key,"error":str(error)})
            print("DEMO_FEHLER: "+key+": "+str(error),file=sys.stderr,flush=True)
    summary={"schema":"spritesuite.demo-cli.v1","passed":success,
             "failed":failed,"skipped":skipped,
             "native_game_calls":False}
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 1 if failed else 0


if __name__=="__main__":
    raise SystemExit(main())
