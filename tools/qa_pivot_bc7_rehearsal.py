"""Prepare an isolated, synthetic BC7 V2 Unity input-pair (no Unity run)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from stronghold_europe_de.pivot_bc7_rehearsal import (  # noqa:E402
    PivotRehearsalError,prepare_synthetic_pivot_rehearsal,
)


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(
        description=(
            "Two synthetic groups: validated BC7 V2 baseline/candidate Unity "
            "input preparation and cache invalidation. NEVER installs or runs Unity."
        )
    )
    parser.add_argument("--old-y",type=float,default=1.10909091)
    parser.add_argument("--new-y",type=float,default=1.0)
    args=parser.parse_args(argv)
    try:
        filename=prepare_synthetic_pivot_rehearsal(
            ROOT,old_pivot_y=args.old_y,new_pivot_y=args.new_y
        )
        record=json.loads(filename.read_text(encoding="utf-8"))
        old=record["tested"]["old"]
        proposed=record["tested"]["proposed"]
        print("SYNTHETIC, NONPROMOTABLE BC7 V2 project-preparation rehearsal")
        print("Previous prepared build:",old["build_id"])
        print("Changed prepared build:",proposed["build_id"])
        for name in record["tested"]["changed_groups"]:
            a,b=old["groups"][name],proposed["groups"][name]
            print(
                f"Changed {name}: pivot {a['pivot']} -> {b['pivot']}; "
                f"cache key {a['cache_key_projection'][:16]} -> "
                f"{b['cache_key_projection'][:16]}"
            )
        for name in record["tested"]["unchanged_groups"]:
            print(f"Unchanged {name}: cache key remains "
                  f"{old['groups'][name]['cache_key_projection'][:16]}")
        print("Evidence:",filename)
        unity_status=record["pinned_unity_editor"]["discovery_status"]
        print("Pinned Unity 2021.3.45f2:",unity_status)
        print("Unity not executed. No BC7 bundle or real gameplay proof.")
        print("Original production, cache and installed game remain untouched.")
        return 0
    except (OSError,ValueError,PivotRehearsalError) as exc:
        print(f"Pivot rehearsal blocked: {exc}",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
