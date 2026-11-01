"""Manual Origins campaign, profile and season-pack authoring (no native DLL).

The historical Origins actions are implemented by StrongholdOrigins.Core.dll,
not by the XAML files. This module intentionally creates reproducible private
campaign/season drafts and never claims to compile or authorize game handlers.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from PIL import Image,UnidentifiedImageError

from hud_menu_workspace import workspace, WorkshopError, _write_new
from se_asset_package import _check_xml
from suite_windows_paths import is_link_or_reparse

VALID_NAME=re.compile(r"[a-z][a-z0-9-]{2,52}\Z")
GM_IDS={
    "tile_land8":2,
    "tile_chevrons":3,
    "tile_cliffs":9,
    "tile_land_macros":55,
    "tree_pine":30,
    "Tree_Chestnut":31,
}
SEASON_ID=re.compile(r"[a-z][a-z0-9-]{2,52}\Z")
_MAX_MISSIONS=21
_RUNTIME_SUB="origins-runtime-candidates"
_PRES="http://schemas.microsoft.com/winfx/2006/xaml/presentation"


def _sha(data:bytes)->str:
    return sha256(data).hexdigest()


def validate_campaign(data:dict)->dict:
    if (not isinstance(data,dict) or data.get("schema") not in
            {"sprite-suite.origins-campaign-plan.v1",None}):
        raise WorkshopError("Invalid campaign schema")
    name=data.get("name")
    if not isinstance(name,str) or not VALID_NAME.fullmatch(name):
        raise WorkshopError("Campaign slug must be safe and ASCII")
    title=data.get("title")
    if (not isinstance(title,str) or not 1<=len(title)<=85
            or any(x in title for x in ("\r","\n","\x00"))):
        raise WorkshopError("Campaign title is invalid")
    missions=data.get("missions")
    if not isinstance(missions,list) or not 1<=len(missions)<=_MAX_MISSIONS:
        raise WorkshopError("Origins campaign must contain 1–21 missions")
    ids=set()
    validated=[]
    for row in missions:
        if not isinstance(row,dict) or type(row.get("number")) is not int:
            raise WorkshopError("Mission number must be integer")
        number=row["number"]
        if not 1<=number<=_MAX_MISSIONS or number in ids:
            raise WorkshopError("Mission number outside range or duplicated")
        ids.add(number)
        title=row.get("title")
        if not isinstance(title,str) or not 1<=len(title)<=100:
            raise WorkshopError("Mission title missing/too long")
        if any(c in title for c in ("\r","\n","\x00")):
            raise WorkshopError("Mission title contains newline/control")
        map_name=row.get("map","")
        if (not isinstance(map_name,str) or
                not re.fullmatch(r"[A-Za-z0-9 _().-]{1,115}\.map",map_name)
                or map_name.strip()!=map_name):
            raise WorkshopError("Mission needs a safe .map filename")
        act=row.get("act","")
        if not isinstance(act,str) or len(act)>80:
            raise WorkshopError("Mission act is invalid")
        validated.append({"number":number,"title":title,"map":map_name,
                          "act":act})
    if sorted(ids)!=list(range(1,len(ids)+1)):
        raise WorkshopError("Mission numbers must be consecutive from 1")
    return {
        "schema":"sprite-suite.origins-campaign-plan.v1",
        "name":name,"title":data["title"],
        "missions":sorted(validated,key=lambda x:x["number"]),
        "profile_progress_schema":{
            "unlocked_mission":1,
            "completed_missions":[],
            "settings":{"subtitles":True,"skip_seen_scenes":False},
        },
        "handler_contract":{
            "existing_game_command":"ButtonMainMenuCommand",
            "new_route_parameters":["OriginsLegacyCampaign"]+[
                "LegacyM"+str(x) for x in sorted(ids)]+["LegacyStart","LegacyBack"],
            "origins_custom_handler_required":True,
            "runtime_compiled":False,
            "game_api_abi_verified":False,
            "in_game_qa_completed":False,
        },
    }


def campaign_csharp_source(plan:dict)->bytes:
    """Compile-ready C# 5 data adapter for the dependency-free runtime core."""
    verified=validate_campaign(plan)
    rows=[]
    for mission in verified["missions"]:
        # JSON quoted strings are valid C# escaped string literals. All source
        # values have been validated and do not contain executable fragments.
        title=json.dumps(mission["title"],ensure_ascii=True)
        mapfile=json.dumps(mission["map"],ensure_ascii=True)
        rows.append(
            f"            new Mission({mission['number']}, {title}, {mapfile}),"
        )
    source=(
        "// Generated from SHA-verified SpriteSuite Origins campaign data.\n"
        "// This is NOT a native game plugin or a registered BepInEx handler.\n"
        "using System.Collections.Generic;\n"
        "namespace SpriteSuite.Origins.Authoring {\n"
        "  public static class AuthoredCampaign {\n"
        "    public static CampaignSession NewSession() {\n"
        "      return new CampaignSession(new List<Mission> {\n"
        + "\n".join(rows) + "\n"
        "      });\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    return source.encode("utf8")


def campaign_draft_xaml(plan:dict)->bytes:
    """XAML layout draft, explicitly never installed before handler attestation."""
    validated=validate_campaign(plan)
    header=('<?xml version="1.0" encoding="utf-8"?>\n'
            '<Patch>\n'
            ' <Operation Type="Add" XPath="/n:UserControl/n:Grid">\n'
            '  <Content>\n'
            '   <Grid xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
            'Name="SpriteSuiteOriginsCampaignScreen" Visibility="Collapsed" '
            'Panel.ZIndex="50001">\n'
            '    <StackPanel HorizontalAlignment="Center" '
            'VerticalAlignment="Center">\n'
            '     <TextBlock FontSize="34" Text="'+escape(validated["title"],{'\"':'&quot;'})+'" />\n')
    body=['     <TextBlock Name="SpriteSuiteSelectedMission" '
          'Text="Mission 1" FontSize="22" />\n']
    for mission in validated["missions"]:
        number=mission["number"]
        title=escape(mission["title"],{'"':'&quot;'})
        body.append('     <Button Name="SpriteSuiteOriginsMission'+str(number)+'" '
                    'Content="'+title+'" '
                    'Command="{Binding ButtonMainMenuCommand}" '
                    'CommandParameter="LegacyM'+str(number)+'" />\n')
    # These are real Noesis buttons, but the game only gains working commands
    # after a separately verified handler is registered. Keep the page hidden.
    body.extend([
        '     <StackPanel Orientation="Horizontal" HorizontalAlignment="Center">\n',
        '      <Button Name="SpriteSuiteOriginsStart" Content="Mission starten" '
        'Command="{Binding ButtonMainMenuCommand}" '
        'CommandParameter="LegacyStart" />\n',
        '      <Button Name="SpriteSuiteOriginsBack" Content="Zurück" '
        'Command="{Binding ButtonMainMenuCommand}" '
        'CommandParameter="LegacyBack" />\n',
        '     </StackPanel>\n',
    ])
    tail=('    </StackPanel>\n'
          '   </Grid>\n'
          '  </Content>\n'
          ' </Operation>\n'
          '</Patch>\n')
    return (header+"".join(body)+tail).encode("utf8")


def write_campaign_draft(project:Path,data:dict)->dict:
    root=workspace(project,create=True)
    plan=validate_campaign(data)
    output=root.parent/".origins-runtime-candidates"/plan["name"]
    if output.exists() or is_link_or_reparse(output):
        raise WorkshopError("A campaign draft already exists; no overwriting")
    xaml=campaign_draft_xaml(plan)
    generated_cs=campaign_csharp_source(plan)
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(dir=root,prefix="origins-campaign-") as temp:
        staging=Path(temp)/"FrontendMenus.xaml"
        staging.write_bytes(xaml)
        _check_xml(staging,patch=True)
    proof={
        "schema":"sprite-suite.origins-campaign-draft.v1",
        "campaign_slug":plan["name"],
        "campaign_sha256":_sha((json.dumps(plan,sort_keys=True)+"\n").encode()),
        "menu_patch_sha256":_sha(xaml),
        "campaign_data_csharp_sha256":_sha(generated_cs),
        "legacy_campaign_handlers_compiled":False,
        "runtime_attested_for_game":False,
        "installable_mod_produced":False,
        "game_files_modified":False,
        "warning":"XAML draft only. LegacyM#/LegacyStart handlers do NOT exist "
                  "in a default game. Supply and independently verify runtime "
                  "implementation before any in-game installation.",
    }
    from suite_output_transaction import OutputBatch
    with OutputBatch(output) as batch:
        batch.stage("campaign-plan.json").write_text(
            json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        batch.stage("FrontendMenus.draft.xaml").write_bytes(xaml)
        batch.stage("OriginsCampaignData.g.cs").write_bytes(generated_cs)
        batch.stage("qa-status.json").write_text(
            json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        batch.publish()
    return {"output":str(output),**proof}


def season_csharp_source(pack_id:str,maps:list[str])->bytes:
    """Generate a map-specific, reversible season routing table for C# 5."""
    if not SEASON_ID.fullmatch(pack_id):
        raise WorkshopError("Invalid season pack ID")
    unique=set()
    rows=[]
    for map_name in maps:
        if (not isinstance(map_name,str) or
                not re.fullmatch(r"[A-Za-z0-9 _().-]{1,115}\.map",map_name)
                or ".." in map_name or map_name.strip()!=map_name or
                map_name.casefold() in unique):
            raise WorkshopError("Season map must be an unambiguous .map filename")
        unique.add(map_name.casefold())
        rows.append(
            "            new SeasonRoute("+
            json.dumps(map_name,ensure_ascii=True)+", "+
            json.dumps(pack_id,ensure_ascii=True)+"),"
        )
    if not rows or len(rows)>100:
        raise WorkshopError("Select between one and 100 original map names")
    result=(
        "// Managed map/season binding only. No game callback registered.\n"
        "using System.Collections.Generic;\n"
        "namespace SpriteSuite.Origins.Authoring {\n"
        "  public static class AuthoredSeasons {\n"
        "    public static SeasonSession NewSession() {\n"
        "      return new SeasonSession(new List<SeasonRoute> {\n"
        + "\n".join(rows) + "\n"
        "      });\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    return result.encode("utf8")


def _season_entry(name:str,folder:Path)->dict:
    if name not in GM_IDS:
        raise WorkshopError("Group not validated against historical GM IDs")
    folder=Path(folder)
    if not folder.is_dir() or is_link_or_reparse(folder):
        raise WorkshopError("Atlas folder absent or symlinked")
    atlas=folder/"atlas.png"
    manifest=folder/"atlas.json"
    if any(not f.is_file() or is_link_or_reparse(f) for f in (atlas,manifest)):
        raise WorkshopError("Atlas needs a real atlas.png and atlas.json")
    if atlas.stat().st_size>256*1024**2 or manifest.stat().st_size>2*1024**2:
        raise WorkshopError("Atlas group exceeds size limit")
    try:
        with Image.open(atlas) as picture:
            if (picture.format!="PNG" or picture.width>8192 or
                picture.height>8192 or picture.width<=0 or picture.height<=0):
                raise WorkshopError("Invalid season atlas PNG")
            picture.verify()
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError) as exc:
        raise WorkshopError("Season atlas PNG corrupt") from exc
    try:metadata=json.loads(manifest.read_text("utf8"))
    except (UnicodeError,ValueError) as exc:raise WorkshopError("Invalid atlas.json") from exc
    if not isinstance(metadata,dict):
        raise WorkshopError("Atlas JSON must be an object")
    return {"gm":name,"gmId":GM_IDS[name],
            "tag":"vegetation" if name.startswith(("tree_","Tree_")) else "terrain",
            "atlas_png_sha256":_sha(atlas.read_bytes()),
            "atlas_json_sha256":_sha(manifest.read_bytes())}


def write_season_draft(project:Path, *,pack_id:str,
                       groups:dict[str,Path],
                       map_routes:list[str]|None=None)->dict:
    """Copy user-authored group atlases with honest 'requires Origins runtime' gate."""
    root=workspace(project,create=True)
    if not SEASON_ID.fullmatch(pack_id):
        raise WorkshopError("Invalid pack ID")
    if not groups or len(groups)>len(GM_IDS):
        raise WorkshopError("Choose at least one historical validated GM group")
    destination=root.parent/".origins-runtime-candidates"/("season-"+pack_id)
    if destination.exists() or is_link_or_reparse(destination):
        raise WorkshopError("Existing season candidate cannot be overwritten")
    records=[_season_entry(name,Path(folder)) for name,folder in sorted(groups.items())]
    generated_cs=season_csharp_source(pack_id,map_routes or [])
    pack={"schema":1,"packId":pack_id,"packVersion":1,
          "groups":[{"gm":r["gm"],"gmId":r["gmId"],"tag":r["tag"]} for r in records]}
    status={
        "schema":"sprite-suite.origins-season-candidate.v1",
        "pack_id":pack_id,"gm_groups":len(records),"group_hashes":records,
        "maps_with_season":sorted(map_routes or []),
        "csharp_route_sha256":_sha(generated_cs),
        "runtime_needs_map_load_save_state_handlers":True,
        "seasonpack_loader_binary_attested":False,
        "in_game_qa_completed":False,"installable_mod_produced":False,
        "steam_game_modified":False,
    }
    # OutputBatch supports FLAT file names only; season packages need a
    # whole private directory tree. Build/verify that tree in one private
    # sibling and rename it to a previously absent final path.
    import os
    import shutil
    import tempfile
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix=".origins-season-",dir=destination.parent))
    try:
        (stage/"pack.json").write_text(json.dumps(
            pack,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        (stage/"OriginsSeasonData.g.cs").write_bytes(generated_cs)
        for record in records:
            group=record["gm"]
            source=Path(groups[group])
            folder=stage/group
            folder.mkdir()
            for filename,label in (("atlas.png","atlas_png_sha256"),
                                   ("atlas.json","atlas_json_sha256")):
                if is_link_or_reparse(source/filename):
                    raise WorkshopError("Linked season asset changed during build")
                target=folder/filename
                shutil.copyfile(source/filename,target)
                if (_sha(target.read_bytes())!=record[label]
                        or _sha((source/filename).read_bytes())!=record[label]):
                    raise WorkshopError("Atlas changed during staging")
        (stage/"qa-status.json").write_text(json.dumps(
            status,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        if destination.exists() or is_link_or_reparse(destination):
            raise WorkshopError("Season destination changed or now exists")
        os.rename(stage,destination)
    finally:
        if stage.exists() and not is_link_or_reparse(stage):
            shutil.rmtree(stage)
    return {"output":str(destination),**status}
