"""What the build menu is made of, and where its building artwork comes from."""

from stronghold_europe_de.suite_paths import portable_path

import collections
import pathlib
import re
import xml.etree.ElementTree as ET

XAML = pathlib.Path(
    portable_path('target_game', 'BepInEx/plugins/000shcdese/Override/Assets/GUI/XAMLResources/HUD_Buildings.xaml')
)

text = XAML.read_text(encoding="utf-8")
tree = ET.fromstring(text)
NAME = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


print(f"Datei: {XAML.stat().st_size / 1024:.1f} KB")

named = []
for parent in tree.iter():
    for child in parent:
        name = child.get("Name") or child.get(NAME)
        if name:
            named.append((name, local(child.tag), local(parent.tag),
                          parent.get("Name") or parent.get(NAME) or ""))
print(f"benannte Elemente: {len(named)}")

print("\n=== Farm-bezogene Knoten ===")
for name, tag, parent, parent_name in named:
    if re.search(r"(?i)farm|wheat|hops|apple|dairy|cattle", name):
        print(f"  {name:<28} {tag:<16} in {parent}/{parent_name}")

print("\n=== Vorschau-/Popup-Kandidaten ===")
for name, tag, parent, parent_name in named:
    if re.search(r"(?i)preview|popup|tooltip|info|detail|hover|desc", name):
        print(f"  {name:<32} {tag:<16} in {parent}/{parent_name}")

print("\n=== Oberste Container ===")
for child in tree:
    if local(child.tag).endswith("Definitions") or local(child.tag).endswith("Resources"):
        continue
    n = child.get("Name") or child.get(NAME) or "(unbenannt)"
    print(f"  {n:<28} {local(child.tag)}")

print("\n=== Sprite-Baenke und ihre Groesse ===")
banks = collections.Counter(
    match.split()[0]
    for match in re.findall(r"StaticResource ([A-Za-z\-]+ [A-Z]?\d+)", text)
)
for bank, count in banks.most_common():
    print(f"  {bank:<20} {count} Verweise")

print("\n=== Wie ein Baumenue-Knopf aussieht (erster Treffer) ===")
match = re.search(r"<(Button|ToggleButton|RadioButton)[^>]*?Name=\"[A-Za-z]*Farm[^\"]*\"[^>]*>", text)
if match is None:
    match = re.search(r"<(Button|ToggleButton|RadioButton)[^>]*?local:PropEx\.Sprite1[^>]*>", text)
if match:
    print("  " + match.group(0)[:700])
