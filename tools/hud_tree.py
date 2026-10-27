"""Extract the anchor points a right-edge bar needs from HUD_Main.xaml.

The extender ships the whole file on disk, so the visual tree is readable
without a game run: named elements are the XPath anchors, and the existing
right-aligned containers show where a new panel can live without fighting the
minimap.
"""

from stronghold_europe_de.suite_paths import portable_path

import pathlib
import re
import xml.etree.ElementTree as ET

XAML = pathlib.Path(
    portable_path('target_game', 'BepInEx/plugins/000shcdese/Override/Assets/GUI/XAMLResources/HUD_Main.xaml')
)

text = XAML.read_text(encoding="utf-8")
tree = ET.fromstring(text)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


NAME = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"

rows = []
for parent in tree.iter():
    for child in parent:
        name = child.get("Name") or child.get(NAME)
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "tag": local(child.tag),
                "parent": local(parent.tag),
                "parent_name": parent.get("Name") or parent.get(NAME) or "",
                "halign": child.get("HorizontalAlignment", ""),
                "valign": child.get("VerticalAlignment", ""),
                "margin": child.get("Margin", ""),
            }
        )

print(f"benannte Elemente: {len(rows)}\n")

print("=== rechtsbuendige Elemente (Kandidaten fuer die Nachbarschaft) ===")
right = [r for r in rows if r["halign"] == "Right"]
for row in right[:20]:
    print(
        f"  {row['name']:<34} {row['tag']:<16} in {row['parent']:<12}"
        f" {row['parent_name']:<22} Margin={row['margin']}"
    )
print(f"  ... {len(right)} rechtsbuendig insgesamt\n")

print("=== oberste Container direkt unter dem Wurzel-Grid ===")
for child in tree:
    if local(child.tag) in {"Grid.RowDefinitions", "Grid.ColumnDefinitions"}:
        continue
    name = child.get("Name") or child.get(NAME) or "(unbenannt)"
    print(
        f"  {name:<34} {local(child.tag):<16}"
        f" H={child.get('HorizontalAlignment','-'):<8}"
        f" V={child.get('VerticalAlignment','-'):<8}"
        f" Vis={child.get('Visibility','-')}"
    )

print("\n=== Sprite-Ressourcen im Schema 'UI-Buttons Lxxx' ===")
sprites = sorted(set(re.findall(r"StaticResource (UI-[A-Za-z]+ [A-Z]?\d+)", text)))
print(f"  {len(sprites)} verschiedene, Beispiele: {sprites[:12]}")

print("\n=== Baumenue-Knoepfe (Vorbild fuer Optik) ===")
for row in rows:
    if row["name"] in {"Granary", "Stockpile", "Armoury", "Barracks", "Keep"}:
        print(f"  {row['name']:<20} {row['tag']:<16} Margin={row['margin']}")
