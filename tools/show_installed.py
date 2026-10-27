"""Print what is currently installed in the game's mod slot.

There is exactly one install slot — `BepInEx/plugins/StrongholdEuropeDE` — and
more than one session installs into it. An in-game test is only meaningful if
the profile you think you are testing is the one actually sitting there.

That is not hypothetical. On 2026-08-09 a roster locale test came back "the
names are unchanged". They were unchanged because a different profile had been
installed into the slot in the meantime; the locale overlay was never on disk
during that run.

Run this immediately before starting the game, and again before believing a
negative result. ``--expect`` proves profile identity only; it does not prove
that the installed DLL still matches the profile build or its runtime contract.
The regular installer checks the manifest-owned tree before replacement or
removal; after a game run use ``stronghold-europe-de runtime-validate`` for the
runtime/log contract.

Usage::

    python tools/show_installed.py
    python tools/show_installed.py --expect europe-roster-locale-canary
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config" / "installations.local.toml"
STATE = REPO_ROOT / "state" / "install-manifest.json"


def install_root() -> Path:
    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    game_dir = Path(config["target"]["game_dir"])
    folder = config["output"].get("mod_folder_name", "StrongholdEuropeDE")
    return game_dir / "BepInEx" / "plugins" / folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expect",
        help=(
            "profile id you believe is installed; exit 1 if it is not "
            "(identity only, not runtime/build integrity)"
        ),
    )
    args = parser.parse_args(argv)

    root = install_root()
    info_path = root / "info.json"
    if not info_path.is_file():
        print(f"Nothing installed at {root}")
        return 1 if args.expect else 0

    info = json.loads(info_path.read_text(encoding="utf-8"))
    manifest_path = root / "build-manifest.json"
    profile_id = None
    if manifest_path.is_file():
        profile_id = json.loads(manifest_path.read_text(encoding="utf-8")).get("profile_id")

    print(f"Installed at : {root}")
    print(f"Profile id   : {profile_id or '(unknown — no build manifest)'}")
    print(f"Description  : {info.get('Description')}")
    print(f"Version      : {info.get('Version')}")

    if STATE.is_file():
        manifest = json.loads(STATE.read_text(encoding="utf-8"))
        stamp = manifest.get("installed_at_utc")
        if stamp:
            when = datetime.fromisoformat(stamp).astimezone()
            age = datetime.now(timezone.utc) - datetime.fromisoformat(stamp)
            print(f"Installed    : {when:%Y-%m-%d %H:%M:%S} ({int(age.total_seconds() // 60)} min ago)")
        print(f"Owned files  : {len(manifest.get('files', []))}")

    payload = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name not in {"info.json", "build-manifest.json"}
    )
    print("Payload      :")
    for item in payload:
        print(f"  {item}")

    if args.expect:
        # build-manifest.json carries the exact profile id the builder wrote.
        # Never match on the description: it is prose and produces false
        # negatives, which are worse than no check at all.
        if profile_id is None:
            print(
                "\nCannot verify --expect: the installed mod has no build manifest.",
                file=sys.stderr,
            )
            return 1
        if profile_id == args.expect:
            print(f"\nMatches --expect {args.expect}")
            print(
                "Profile identity only; after the run use "
                "`stronghold-europe-de runtime-validate --profile-id installed` "
                "for the runtime/log contract."
            )
            return 0
        print(
            f"\nInstalled profile is {profile_id!r}, expected {args.expect!r}. "
            "Reinstall before testing, or the run proves the wrong profile.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
