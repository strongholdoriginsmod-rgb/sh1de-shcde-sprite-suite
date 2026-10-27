"""SE-Atlas-Mods mit Serpens66s AtlasBuilder erzeugen (Override/Atlas, SE >= 2.4, BC7-DDS ab SE 2.8).

Dritter Lieferweg neben dem Europa-BC7-Paket und den Einzelbildern: der
Script Extender 2.11 laedt ``Override/Atlas/<Gruppe>/atlas.png|dds`` selbst -
ohne eigene Laufzeit-DLL und ohne index-Pin. Geeignet fuer einzelne Gruppen,
eigene Aenderungen und schnelles Ausprobieren.

    python tools/se_atlas.py projekt --gruppen tile_buildings2,Tree_Oak --quelle arbeit --name MeineAtlanten
    python tools/se_atlas.py bauen work/se-atlas/MeineAtlanten.atlas-project.json
    python tools/se_atlas.py gui
    python tools/se_atlas.py texconv        # BC7-Encoder (Microsoft DirectXTex, hash-gepinnt) holen

Quellen: ``arbeit`` (Katalog-Arbeitskopie, Crusader-Leinwand -> Pixelanker des
Ziels), ``geliefert`` / ``stronghold1`` (eigene Leinwaende -> Pivots aus den
Exporten als AssetRipper-Metadaten), oder ein beliebiger Ordner.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import asset_katalog as katalog  # noqa: E402

BUILDER = PROJECT_ROOT / "extras" / "atlasbuilder"
OUT = PROJECT_ROOT / "work" / "se-atlas"


def say(text=""):
    print(text, flush=True)


def target_data() -> str:
    try:
        config = tomllib.loads((PROJECT_ROOT / "config" / "installations.local.toml").read_text(encoding="utf-8"))
        return config["target"]["data_dir"]
    except (OSError, ValueError, KeyError):
        return ""


def write_metadata(group: str, directory: Path, side: str) -> Path:
    """Pivots eines Exports als AssetRipper-Sprite-JSON (m_Name, m_Rect, m_Pivot, m_PixelsToUnits)."""
    meta = OUT / "meta" / katalog.slug(group) / side
    meta.mkdir(parents=True, exist_ok=True)
    geometry = "crusader" if side == "arbeit" else side
    for frame in katalog.index_of(directory).get("frames", []):
        w, h, px, py = katalog.pivot_of(frame, geometry)
        payload = {"m_Name": frame["name"], "m_Rect": {"m_X": 0, "m_Y": 0, "m_Width": w, "m_Height": h},
                   "m_Pivot": {"m_X": px, "m_Y": py}, "m_PixelsToUnits": 64.0}
        (meta / f"{frame['name']}.json").write_text(json.dumps(payload), encoding="utf-8")
    return meta


def cmd_projekt(args) -> int:
    groups = [g.strip() for g in args.gruppen.split(",") if g.strip()]
    language = "en" if os.environ.get("SEDE_SPRACHE") == "en" else "de"
    project = {"schemaVersion": 6, "language": language, "targetGameData": args.spieldaten or target_data(),
               "outputModDirectory": str((OUT / args.name).resolve()), "groups": [],
               "packing": {"gap": 2, "maximumTextureSize": 8192}, "createManifestIfMissing": True,
               "modInfo": {"GUID": args.guid or args.name, "Author": args.autor, "Name": args.name,
                           "Description": "SE-Atlas-Mod aus der Stronghold-Europe-Universal-Suite",
                           "Version": "1.0.0", "Website": ""}}
    for group in groups:
        if Path(args.quelle).is_dir():
            directory, side = Path(args.quelle) / group, "ordner"
        elif args.quelle == "arbeit":
            directory, side = katalog.ensure_work(group), "arbeit"
        else:
            katalog.ensure_side(group, args.quelle)
            directory, side = katalog.side_dir(args.quelle, group), args.quelle
        has_masks = any(directory.glob("*_m.png"))
        entry = {"gmFileName": group, "colourDirectory": str(directory.resolve()),
                 "maskMode": "same-directory" if has_masks else "none", "maskDirectory": None,
                 "sourcePrefix": "auto", "pivotMode": "target-pixel-anchor",
                 "missingTargetPolicy": "reject", "missingSourceMetadataPolicy": "target-pixel-anchor",
                 "colourTextureFormat": args.format, "maskTextureFormat": "png"}
        if side in ("geliefert", "stronghold1"):
            entry["pivotMode"] = "source-metadata"
            entry["sourceMetadataDirectory"] = str(write_metadata(group, directory, side).resolve())
        if args.nur_geaenderte and side == "arbeit":
            changed = katalog.changed_frames(group)
            if not changed:
                say(f"{group}: keine Aenderungen in der Arbeitskopie - uebersprungen")
                continue
            numbers = sorted({katalog.frame_number(n) for n in changed})
            entry["sourceFrameFilter"] = ", ".join(f"{i}{'x' if alt else ''}" for i, alt in numbers)
        project["groups"].append(entry)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{args.name}.atlas-project.json"
    path.write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")
    say(f"AtlasBuilder-Projekt mit {len(project['groups'])} Gruppen: {path}")
    say(f"Bauen: python tools/se_atlas.py bauen \"{path}\"   (Ausgabe {project['outputModDirectory']})")
    if args.format == "bc7-dds" and not (BUILDER / "tools" / "texconv.exe").is_file():
        say("Hinweis: fuer BC7-DDS einmal 'se_atlas.py texconv' ausfuehren.")
    return 0


def run_builder(extra: list[str]) -> int:
    runner = BUILDER / "run_atlas_builder.py"
    env_path = str(BUILDER)
    command = [sys.executable, str(runner), *extra]
    say("$ " + " ".join(command))
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = env_path + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(command, cwd=BUILDER, env=env).returncode


def cmd_bauen(args) -> int:
    project = Path(args.projekt).resolve()
    data = json.loads(project.read_text(encoding="utf-8"))
    output = args.ausgabe or data.get("outputModDirectory")
    code = run_builder(["--validate-project", str(project)])
    if code != 0:
        say("WARNUNG (Nachsicht): Die Projektpruefung des AtlasBuilders meldet Probleme - es wird trotzdem gebaut.")
    code = run_builder(["--build-project", str(project), output])
    if code == 0:
        say(f"SE-Atlas-Mod gebaut: {output}")
        say("Installieren: Reiter 'Ziel & SE 2.11' -> Mod installieren (mit Sicherung).")
    return code


def cmd_gui(args) -> int:
    return run_builder([])


def cmd_texconv(args) -> int:
    fetch = BUILDER / "fetch_texconv.py"
    say("Hole texconv.exe (Microsoft DirectXTex, Version und SHA-256 im Skript festgelegt) ...")
    return subprocess.run([sys.executable, str(fetch)], cwd=BUILDER).returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("projekt", help="AtlasBuilder-Projekt aus Katalog-Ansichten erzeugen")
    p.add_argument("--gruppen", required=True)
    p.add_argument("--quelle", default="arbeit", help="arbeit | geliefert | stronghold1 | crusader | <Ordner>")
    p.add_argument("--name", default="EuropaSEAtlas")
    p.add_argument("--guid")
    p.add_argument("--autor", default="")
    p.add_argument("--format", choices=("png", "bc7-dds"), default="png")
    p.add_argument("--spieldaten", help="Stronghold Crusader Definitive Edition_Data des Zielspiels")
    p.add_argument("--nur-geaenderte", action="store_true", help="nur geaenderte Frames der Arbeitskopie")
    p.set_defaults(func=cmd_projekt)
    p = sub.add_parser("bauen", help="AtlasBuilder-Projekt bauen")
    p.add_argument("projekt")
    p.add_argument("--ausgabe")
    p.set_defaults(func=cmd_bauen)
    p = sub.add_parser("gui", help="AtlasBuilder-Oberflaeche starten")
    p.set_defaults(func=cmd_gui)
    p = sub.add_parser("texconv", help="BC7-Encoder texconv.exe holen")
    p.set_defaults(func=cmd_texconv)
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
