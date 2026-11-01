"""Build a private static-only Origins UI compatibility QA copy, never install.

Original Origins GUI includes runtime-backed menu actions; the generated
Manifest:0 *asset-only* test output is an audit fixture, NOT a playable mod.
Any copyrighted game images and videos remain under the user's private work/.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from zipfile import ZipFile

import se_asset_package as package

STATIC_ASSETS=(
 "Override/Assets/GUI/Images/MenusBackground.png",
 "Override/Assets/GUI/Images/origins-logo.png",
 "Override/Assets/GUI/Images/origins-menu-background.png",
 "Override/Assets/GUI/Images/origins-loading-background.png",
 "Override/Assets/GUI/Images/origins-loading-bar.png",
 "Override/Assets/GUI/Video/front_end_background.webm",
 "Override/Assets/GUI/Video/front_end_background_low.webm",
 "Override/Assets/GUI/XAMLResources/Theme.Brushes.DarkRed.xaml",
 "Patches/Assets/GUI/XAML/FrontendMenus.xaml",
 "Patches/Assets/GUI/XAML/IntroSequence.xaml",
 "Locales/de-DE/crusader.txt",
)


def _sha(file:Path)->str:
    h=sha256()
    with file.open("rb") as f:
        for block in iter(lambda:f.read(4*1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def main(base:Path,out:Path)->dict:
    historical=Path(base).resolve(strict=True)
    dest=Path(out).resolve(strict=False)
    if dest.exists() or dest != package.ROOT/"work"/"private-origins-static-qa":
        raise ValueError("Only a new, local, ignored private Origins QA folder")
    marker=historical/"branding-manifest.json"
    doc=json.loads(marker.read_text("utf8"))
    if doc.get("schema")!="stronghold-origins-branding-v1":
        raise ValueError("Historical package manifest changed")
    entries={x["path"]:x for x in doc["files"]}
    for rel in STATIC_ASSETS:
        if rel not in entries:raise ValueError("Missing historical Origins manifest item "+rel)
        path=historical/rel
        if not path.is_file() or path.is_symlink():
            raise ValueError("Missing real historical asset "+rel)
        if path.stat().st_size!=entries[rel]["bytes"] or _sha(path)!=entries[rel]["sha256"]:
            raise ValueError("Historical Origins bytes do not match Git-LFS source "+rel)
        package._validate_asset(path,rel)
    dest.mkdir(parents=True)
    try:
        for rel in STATIC_ASSETS:
            source=historical/rel
            target=dest/rel
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
            if _sha(target)!=entries[rel]["sha256"]:
                raise ValueError("Origins copy checksum mismatch "+rel)
        result=package.build(
            dest,"originsstaticaudit",
            name="Offline Origins Static Audit ONLY",
            author="SpriteSuite local QA",
        )
        with ZipFile(result["zip"]) as zipped:
            names=set(zipped.namelist())
            if zipped.testzip():
                raise ValueError("Origins static ZIP CRC error")
            if not all("BepInEx/plugins/originsstaticaudit/"+r in names for r in STATIC_ASSETS):
                raise ValueError("Origins static ZIP did not include every resource")
        output={
            "schema":"sprite-suite.origins-historical-static-parity.v1",
            "historical_manifest_sha256":_sha(marker),
            "asset_files_validated":len(STATIC_ASSETS),
            "patches_validated":2,
            "videos_validated":2,
            "locales_validated":1,
            "themes_validated":1,
            "source_bytes_unchanged":True,
            "all_source_files_sha256_match_historical_manifest":True,
            "static_only_private_package_created":True,
            "stronghold_origins_core_dll_included":False,
            "new_origins_mission_and_campaign_handlers_available":False,
            "usable_as_a_playable_origins_mod":False,
            "in_game_test_completed":False,
        }
        report=dest.parent/"origins-static-qa-evidence.json"
        report.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        return output
    except Exception:
        # Preserve partially generated evidence for diagnosis; never touch games.
        raise


if __name__=="__main__":
    result=main(Path(sys.argv[1]),Path(sys.argv[2]))
    print(json.dumps(result,ensure_ascii=False,indent=2))
