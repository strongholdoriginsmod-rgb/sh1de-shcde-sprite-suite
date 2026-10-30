"""Inspect the HUD_Main.xaml visual tree and identify right-edge anchor points.

This diagnostic is read-only. Supply --xaml when the installed game is not
configured. Importing the module never reads private game files or prints.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from stronghold_europe_de.suite_paths import portable_path
from hud_buildings import read_xaml, local

_XAML_RELATIVE = (
    "BepInEx/plugins/000shcdese/Override/Assets/GUI/"
    "XAMLResources/HUD_Main.xaml"
)
_NAME = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"


def default_xaml() -> Path:
    return Path(portable_path("target_game", _XAML_RELATIVE))


def inspect_xaml(text: str, tree: ET.Element) -> dict:
    rows = []
    for parent in tree.iter():
        for child in parent:
            name = child.get("Name") or child.get(_NAME)
            if not name:
                continue
            rows.append({
                "name":name, "tag":local(child.tag), "parent":local(parent.tag),
                "parent_name":parent.get("Name") or parent.get(_NAME) or "",
                "halign":child.get("HorizontalAlignment",""),
                "valign":child.get("VerticalAlignment",""),
                "margin":child.get("Margin",""),
            })
    sprites = sorted(set(re.findall(
        r"StaticResource (UI-[A-Za-z]+ [A-Z]?\d+)", text
    )))
    top = [
        {"name":child.get("Name") or child.get(_NAME) or "(unbenannt)",
         "tag":local(child.tag),
         "halign":child.get("HorizontalAlignment","-"),
         "valign":child.get("VerticalAlignment","-"),
         "visible":child.get("Visibility","-")}
        for child in tree
        if local(child.tag) not in {"Grid.RowDefinitions","Grid.ColumnDefinitions"}
    ]
    return {"rows":rows, "right":[r for r in rows if r["halign"]=="Right"],
            "top":top,"sprites":sprites}


def report(data: dict) -> str:
    lines=[f"benannte Elemente: {len(data['rows'])}","",
           "=== Rechtsbündige Elemente (Kandidaten für eine Nachbarschaft) ==="]
    for row in data["right"][:20]:
        lines.append(
            f"  {row['name']:<34} {row['tag']:<16} in {row['parent']:<12}"
            f" {row['parent_name']:<22} Margin={row['margin']}"
        )
    lines += [f"  ... {len(data['right'])} rechtsbündig insgesamt",
              "", "=== Oberste Container direkt unter dem Wurzel-Grid ==="]
    for row in data["top"]:
        lines.append(
            f"  {row['name']:<34} {row['tag']:<16} "
            f"H={row['halign']:<8} V={row['valign']:<8} Vis={row['visible']}"
        )
    lines += ["", "=== Sprite-Ressourcen im Schema UI-Buttons Lxxx ===",
              f"  {len(data['sprites'])} verschiedene, Beispiele: {data['sprites'][:12]}",
              "", "=== Baum-Menü-Knöpfe (Vorbild für Optik) ==="]
    for row in data["rows"]:
        if row["name"] in {"Granary","Stockpile","Armoury","Barracks","Keep"}:
            lines.append(f"  {row['name']:<20} {row['tag']:<16} Margin={row['margin']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--xaml", type=Path, default=None,
                        help="HUD_Main.xaml (ohne Änderung am Spiel)")
    args = parser.parse_args(argv)
    path = args.xaml if args.xaml is not None else default_xaml()
    try:
        text, tree = read_xaml(path)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"HUD-Baumanalyse: {exc}\n"
                         "Bitte mit --xaml eine vorhandene Datei auswählen.\n")
    print(report(inspect_xaml(text,tree)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
