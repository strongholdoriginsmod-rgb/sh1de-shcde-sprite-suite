"""Produce an installable, self-contained Noesis menu patch without editing XAML.

Unlike the historical draft, this patch adds a visible entry button to the
ACTUAL main-menu button grid and a hidden campaign overlay in the genuine
1920x1080 frontend viewport. Every XPath must match exactly one node in the
user's own original installed FrontendMenus.xaml. The patch is written only
to a private staging directory until installation is explicitly authorized.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

from origins_runtime_authoring import validate_campaign

PRES="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
ENTRY_XPATH="//n:Grid[n:Button[@Name='MainMenu_OptionsButton']]"
VIEW_XPATH=(
    "//n:Grid[@Width='1920' and @Height='1080' "
    "and contains(@Visibility,'Show_FrontMenus')]"
)


class NativePatchError(ValueError): pass


def verify_original_xpaths(original:Path)->dict:
    file=Path(original)
    if not file.is_file() or file.is_symlink():
        raise NativePatchError("Original frontend XAML missing or linked")
    root=ET.fromstring(file.read_bytes())
    ns="{"+PRES+"}"
    entry=[grid for grid in root.iter(ns+"Grid")
           if any(child.tag==ns+"Button" and
                  child.attrib.get("Name")=="MainMenu_OptionsButton"
                  for child in grid)]
    view=[grid for grid in root.iter(ns+"Grid")
          if grid.attrib.get("Width")=="1920" and
             grid.attrib.get("Height")=="1080" and
             "Show_FrontMenus" in grid.attrib.get("Visibility","")]
    if len(entry)!=1 or len(view)!=1:
        raise NativePatchError("Game frontend XAML anchors ambiguous: "+
                               repr((len(entry),len(view))))
    original_names={child.attrib.get("Name") for child in root.iter()
                    if child.attrib.get("Name")}
    required=("SpriteSuiteOriginsOpen","SpriteSuiteOriginsCampaignScreen",
              "SpriteSuiteSelectedMission","SpriteSuiteOriginsStart",
              "SpriteSuiteOriginsBack")
    if any(name in original_names for name in required):
        raise NativePatchError("The original menu already has SpriteSuite controls")
    return {"entry_grid_matches":len(entry),
            "original_viewport_matches":len(view),
            "installed_game_xaml_bytes":file.stat().st_size,
            "existing_names_checked":len(original_names)}


def build_native_menu_patch(campaign:dict,original:Path)->bytes:
    plan=validate_campaign(campaign)
    verify_original_xpaths(original)
    title=escape(plan["title"],{'"':"&quot;"})
    rows=[]
    for mission in plan["missions"]:
        name=escape(mission["title"],{'"':"&quot;"})
        rows.append(
          f'<Button Name="SpriteSuiteOriginsMission{mission["number"]}" '
          'Width="440" Height="55" Margin="0,5,0,5" '
          f'Content="{name}" '
          'Command="{Binding ButtonMainMenuCommand}" '
          f'CommandParameter="LegacyM{mission["number"]}"/>')
    one=(
       f'<Button xmlns="{PRES}" Name="SpriteSuiteOriginsOpen" '
       'Width="260" Height="54" Margin="0,0,0,146" '
       'HorizontalAlignment="Center" VerticalAlignment="Bottom" '
       'Foreground="#FFF4E2B3" Background="#FF1C3441" '
       'BorderBrush="#FFD9B976" BorderThickness="2" FontSize="24" '
       'Content="SpriteSuite Origins" '
       'Command="{Binding ButtonMainMenuCommand}" '
       'CommandParameter="OriginsLegacyCampaign"/>')
    two=(
       f'<Grid xmlns="{PRES}" Name="SpriteSuiteOriginsCampaignScreen" '
       'Width="1920" Height="1080" Panel.ZIndex="50001" '
       'Background="#EE101820" Visibility="Collapsed">'
       '<StackPanel HorizontalAlignment="Center" VerticalAlignment="Center">'
       f'<TextBlock FontSize="44" Foreground="#FFE9D5A5" Text="{title}" '
       'HorizontalAlignment="Center" Margin="0,0,0,28"/>'
       '<TextBlock Name="SpriteSuiteSelectedMission" '
       'Text="Mission 1" FontSize="26" Foreground="#FFF2E7CB" '
       'HorizontalAlignment="Center" Margin="0,0,0,20"/>'
       + "".join(rows)+
       '<StackPanel Orientation="Horizontal" HorizontalAlignment="Center">'
       '<Button Name="SpriteSuiteOriginsStart" Content="Mission starten" '
       'FontSize="24" Width="270" Height="62" Margin="5,20,5,0" '
       'Foreground="#FFEDDBB2" Background="#FF254D3E" '
       'Command="{Binding ButtonMainMenuCommand}" '
       'CommandParameter="LegacyStart"/>'
       '<Button Name="SpriteSuiteOriginsBack" Content="Zurück" '
       'FontSize="24" Width="180" Height="62" Margin="5,20,5,0" '
       'Foreground="#FFEDDBB2" Background="#FF3C3431" '
       'Command="{Binding ButtonMainMenuCommand}" '
       'CommandParameter="LegacyBack"/>'
       '</StackPanel></StackPanel></Grid>')
    output=(
       '<?xml version="1.0" encoding="utf-8"?>\n'
       '<Patch>\n'
       f'  <Operation Type="Add" XPath="{escape(ENTRY_XPATH,{"\"":"&quot;"})}">'
       f'<Content>{one}</Content></Operation>\n'
       f'  <Operation Type="Add" XPath="{escape(VIEW_XPATH,{"\"":"&quot;"})}">'
       f'<Content>{two}</Content></Operation>\n'
       '</Patch>\n'
    ).encode("utf8")
    patch=ET.fromstring(output)
    operations=list(patch)
    if len(operations)!=2 or any(len(x.find("Content"))!=1 for x in operations):
        raise NativePatchError("Native menu patch structure invalid")
    for entry in operations:
        ET.fromstring(ET.tostring(entry.find("Content")[0]))
    return output
