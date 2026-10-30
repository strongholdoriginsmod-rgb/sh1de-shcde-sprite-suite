"""Inspect building-menu XAML without changing the game or project data."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from stronghold_europe_de.suite_paths import portable_path
from suite_windows_paths import is_link_or_reparse

_XAML_RELATIVE = (
    "BepInEx/plugins/000shcdese/Override/Assets/GUI/"
    "XAMLResources/HUD_Buildings.xaml"
)
_NAME = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
MAX_XAML_BYTES = 2 * 1024 * 1024


def default_xaml() -> Path:
    return Path(portable_path("target_game", _XAML_RELATIVE))


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_xaml(path: Path) -> tuple[str, ET.Element]:
    path = Path(path)
    if is_link_or_reparse(path) or not path.is_file():
        raise ValueError("HUD-Buildings-XAML fehlt oder ist verknüpft: " + str(path))
    if path.suffix.lower() != ".xaml" or path.stat().st_size > MAX_XAML_BYTES:
        raise ValueError("Bitte eine reguläre XAML-Datei mit höchstens 2 MiB wählen.")
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("XML-Entitäten und DOCTYPE sind aus Sicherheitsgründen verboten.")
    try:
        return raw.decode("utf-8-sig"), ET.fromstring(raw)
    except (UnicodeError, ET.ParseError) as exc:
        raise ValueError("HUD-Buildings-XAML kann nicht gelesen werden.") from exc


def inspect_xaml(text: str, tree: ET.Element) -> dict:
    named = []
    for parent in tree.iter():
        for child in parent:
            name = child.get("Name") or child.get(_NAME)
            if name:
                named.append((name, local(child.tag), local(parent.tag),
                              parent.get("Name") or parent.get(_NAME) or ""))
    banks = Counter(
        match.split()[0]
        for match in re.findall(r"StaticResource ([A-Za-z\-]+ [A-Z]?\d+)", text)
    )
    buttons = re.search(
        r'<(Button|ToggleButton|RadioButton)[^>]*?Name="[A-Za-z]*Farm[^"]*"[^>]*>',
        text,
    )
    if buttons is None:
        buttons = re.search(
            r'<(Button|ToggleButton|RadioButton)[^>]*?local:PropEx\.Sprite1[^>]*>',
            text,
        )
    return {"named": named, "banks": banks, "top": [
        (child.get("Name") or child.get(_NAME) or "(unbenannt)",local(child.tag))
        for child in tree
        if not local(child.tag).endswith(("Definitions", "Resources"))
    ], "button":buttons.group(0)[:700] if buttons else ""}


def report(data: dict, source: Path) -> str:
    named = data["named"]
    lines = [f"Datei: {source}", f"benannte Elemente: {len(named)}",
             "", "=== Farm-bezogene Knoten ==="]
    for name, tag, parent, parent_name in named:
        if re.search(r"farm|wheat|hops|apple|dairy|cattle", name, flags=re.I):
            lines.append(f"  {name:<28} {tag:<16} in {parent}/{parent_name}")
    lines += ["", "=== Vorschau-/Popup-Kandidaten ==="]
    for name, tag, parent, parent_name in named:
        if re.search(r"preview|popup|tooltip|info|detail|hover|desc",
                     name,flags=re.I):
            lines.append(f"  {name:<32} {tag:<16} in {parent}/{parent_name}")
    lines += ["", "=== Oberste Container ==="]
    for name, tag in data["top"]:
        lines.append(f"  {name:<28} {tag}")
    lines += ["", "=== Sprite-Bänke und ihre Größe ==="]
    for bank, count in data["banks"].most_common():
        lines.append(f"  {bank:<20} {count} Verweise")
    lines += ["", "=== Beispiel eines Baum-Menü-Knopfs ==="]
    if data["button"]:
        lines.append("  " + data["button"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xaml", type=Path, default=None,
                        help="HUD_Buildings.xaml (ohne Änderung am Spiel)")
    args = parser.parse_args(argv)
    path = args.xaml if args.xaml is not None else default_xaml()
    try:
        text, tree = read_xaml(path)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"HUD-Gebäudeanalyse: {exc}\n"
                         "Bitte mit --xaml eine vorhandene Datei auswählen.\n")
    print(report(inspect_xaml(text,tree),path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
