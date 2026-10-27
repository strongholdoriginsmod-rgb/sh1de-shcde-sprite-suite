"""Re-pin the digests of the authored XAML patches after editing one.

Every patch file the build ships is pinned by SHA-256 in the profile. That is
deliberate: a Noesis patch that reaches the game malformed does not throw, it
blanks the interface, so the build refuses anything it was not shown. The price
is that editing a patch means updating its digest.

    python tools/pin_xaml.py            zeigt, was sich geaendert hat
    python tools/pin_xaml.py --write    traegt die neuen Digests ein

This is separate from tools/pin_digests.py on purpose. Those digests are
measurements the build produces; this one is a statement that a human looked at
the file and meant to change it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE = PROJECT_ROOT / "profiles" / "europe-production.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pin_xaml", description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="die neuen Digests wirklich eintragen",
    )
    args = parser.parse_args(argv)

    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    patches = profile.get("xaml_patches", [])
    if not patches:
        print("Keine xaml_patches im Profil.")
        return 0

    changed = 0
    for entry in patches:
        source = PROJECT_ROOT / entry["source"]
        if not source.is_file():
            print(f"  fehlt: {entry['source']}")
            return 1
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest == entry["expected_sha256"]:
            print(f"  unveraendert: {entry['source']}")
            continue
        changed += 1
        print(f"  geaendert: {entry['source']}")
        print(f"    bisher : {entry['expected_sha256']}")
        print(f"    jetzt  : {digest}")
        if args.write:
            entry["expected_sha256"] = digest

    if not changed:
        return 0
    if not args.write:
        print(f"\n{changed} Datei(en) geaendert. Mit --write eintragen.")
        return 1
    PROFILE.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\n{changed} Digest(e) eingetragen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
