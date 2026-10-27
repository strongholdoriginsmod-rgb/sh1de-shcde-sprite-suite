"""Assemble a game-layout reference root for the runtime companion build.

The companion compiles against managed assemblies that live in three places:
the official Script Extender package, BepInEx in an installed game, and the
game's own Managed folder. This tool copies exactly those files into
work/reference-roots/<name>/ with the relative paths runtime-prerequisites.json
expects, and writes manifest.json with the SHA-256 of every copied file.

Read-only on every source. Writes only below work/reference-roots/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
MANAGED = "Stronghold Crusader Definitive Edition_Data/Managed"
SE_PREFIX = "BepInEx/plugins/000shcdese/"

MANAGED_FILES = (
    "Assembly-CSharp.dll",
    "Noesis.NoesisGUI.dll",
    "UnityEngine.dll",
    "UnityEngine.CoreModule.dll",
    "UnityEngine.AssetBundleModule.dll",
    "UnityEngine.AudioModule.dll",
    "UnityEngine.ImageConversionModule.dll",
)
BEPINEX_FILES = ("BepInEx.dll", "0Harmony.dll")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--se-zip", required=True, type=Path)
    ap.add_argument("--se-zip-sha256", required=True)
    ap.add_argument("--bepinex-game", required=True, type=Path,
                    help="installed game whose BepInEx/core is used")
    ap.add_argument("--managed-game", required=True, type=Path,
                    help="installed game whose Managed folder is used")
    a = ap.parse_args(argv)

    root = (PROJECT / "work" / "reference-roots" / a.name).resolve()
    if (PROJECT / "work") not in root.parents:
        raise SystemExit("reference root escapes work/")
    if sha256(a.se_zip) != a.se_zip_sha256:
        raise SystemExit("Script Extender package hash mismatch")
    if root.exists():
        shutil.rmtree(root)
    manifest = {"name": a.name, "se_zip": str(a.se_zip), "se_zip_sha256": a.se_zip_sha256,
                "bepinex_game": str(a.bepinex_game), "managed_game": str(a.managed_game),
                "files": {}}

    def put(rel: str, data_source) -> None:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data_source, Path):
            shutil.copyfile(data_source, dest)
        else:
            dest.write_bytes(data_source)
        manifest["files"][rel] = {"sha256": sha256(dest), "size": dest.stat().st_size}

    with zipfile.ZipFile(a.se_zip) as z:
        for info in z.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            rest = name[len(SE_PREFIX):] if name.startswith(SE_PREFIX) else None
            if rest is None:
                continue
            # Top-level managed DLLs (compile references) and the extender's
            # own Override tree (the XAML base the HUD patches are pinned to).
            if (rest.lower().endswith(".dll") and "/" not in rest) or rest.startswith("Override/"):
                put(name, z.read(info))
    for f in BEPINEX_FILES:
        put(f"BepInEx/core/{f}", a.bepinex_game / "BepInEx" / "core" / f)
    for f in MANAGED_FILES:
        put(f"{MANAGED}/{f}", a.managed_game / MANAGED / f)
    # Unit roster names are read from the game's own text table.
    put("Assets/Text/crusader.txt", a.managed_game / "Assets" / "Text" / "crusader.txt")

    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for rel, meta in sorted(manifest["files"].items()):
        print(f"{meta['sha256'][:16]}  {meta['size']:>9}  {rel}")
    print(f"reference root: {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
