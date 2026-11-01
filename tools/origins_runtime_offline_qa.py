"""Reproducible managed Origins authoring QA; NEVER installs or loads a game DLL.

The compiler is invoked only on regenerated, verified C# files and a fixed,
audited C# harness. It does not execute user-supplied files as program code.
This attests the independent managed core, NOT the Steam native engine ABI.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import tempfile

from hud_menu_workspace import workspace, WorkshopError
from origins_runtime_authoring import (
    GM_IDS, VALID_NAME, _season_entry, validate_campaign,
    campaign_csharp_source, campaign_draft_xaml, season_csharp_source,
)
from suite_windows_paths import is_link_or_reparse as linked

ROOT = Path(__file__).resolve().parents[1]
COMPILER = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")
CORE = ROOT / "runtime" / "SpriteSuite.Origins.Authoring" / "OriginsRuntimeCore.cs"
_MAX_META = 256 * 1024
_MAX_CS = 512 * 1024
_HARNESS = r"""
using System;
using SpriteSuite.Origins.Authoring;
public static class AuthoredOriginsOfflineQATest {
    static int assertions;
    static void Check(bool b, string message) {
        if (!b) throw new Exception(message);
        ++assertions;
    }
    public static int Main(string[] args) {
        try {
            var game = AuthoredCampaign.NewSession();
            Check(game.MissionCount == Int32.Parse(args[0]), "mission count");
            Check(game.Missions[0].MapFile == args[1], "first map");
            Check(game.HandleCommand("LegacyStart").Action ==
                  MenuAction.RejectedState, "hidden menu is protected");
            Check(game.HandleCommand("OriginsLegacyCampaign").Action ==
                  MenuAction.OpenCampaign, "open campaign route");
            Check(game.HandleCommand("LegacyStart").MapFile == args[1],
                  "start request returns authored map");
            Check(game.HandleCommand("LegacyBack").Action ==
                  MenuAction.BackToMenu, "back returns to menu");
            Check(!game.IsCampaignScreenOpen, "menu is closed");
#if SEASON
            var season = AuthoredSeasons.NewSession();
            Check(season.OnMapLoaded(args[2]) == args[3],
                  "authored season map binds to exact pack");
            season.OnMapUnloaded();
            Check(season.ActivePack == null, "season unload resets");
#endif
            Console.WriteLine("ORIGINS_AUTHORED_QA_ASSERTIONS=" + assertions);
            Console.WriteLine("ORIGINS_GAME_DLL_LOADED=0");
            Console.WriteLine("ORIGINS_NATIVE_ABI_ATTESTED=0");
            return 0;
        } catch (Exception e) {
            Console.Error.WriteLine("AUTHORED_QA_FAILED: " + e);
            return 1;
        }
    }
}
"""


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _small(folder: Path, name: str, maximum: int = _MAX_META) -> bytes:
    target = folder / name
    if (not target.is_file() or linked(target)
            or target.stat().st_size > maximum):
        raise WorkshopError("Missing, linked or oversized QA input: " + name)
    return target.read_bytes()


def _json(folder: Path, name: str) -> dict:
    try:
        data = json.loads(_small(folder, name).decode("utf8"))
    except (UnicodeError, ValueError) as error:
        raise WorkshopError("Invalid candidate JSON: " + name) from error
    if not isinstance(data, dict):
        raise WorkshopError("Candidate metadata must be an object")
    return data


def _candidate(root: Path, name: str) -> Path:
    base = root.parent / ".origins-runtime-candidates"
    target = base / name
    if (not target.is_dir() or linked(base) or linked(target)
            or target.resolve(strict=True).parent != base.resolve(strict=True)):
        raise WorkshopError("Missing or linked private Origins candidate")
    return target


def verify_campaign(root: Path, slug: str) -> tuple[dict, bytes]:
    if not isinstance(slug, str) or not VALID_NAME.fullmatch(slug):
        raise WorkshopError("Unsafe campaign identifier")
    folder = _candidate(root, slug)
    plan = _json(folder, "campaign-plan.json")
    clean = validate_campaign(plan)
    if plan != clean or plan["name"] != slug:
        raise WorkshopError("Campaign plan does not match the validated schema")
    code = campaign_csharp_source(plan)
    xaml = campaign_draft_xaml(plan)
    if (_small(folder, "OriginsCampaignData.g.cs", _MAX_CS) != code
            or _small(folder, "FrontendMenus.draft.xaml", _MAX_CS) != xaml):
        raise WorkshopError("Authored XAML or C# has changed since generation")
    status = _json(folder, "qa-status.json")
    digest = _sha((json.dumps(plan, sort_keys=True) + "\n").encode())
    if (status.get("schema") != "sprite-suite.origins-campaign-draft.v1"
            or status.get("campaign_slug") != slug
            or status.get("campaign_sha256") != digest
            or status.get("menu_patch_sha256") != _sha(xaml)
            or status.get("campaign_data_csharp_sha256") != _sha(code)
            or status.get("legacy_campaign_handlers_compiled") is not False
            or status.get("runtime_attested_for_game") is not False
            or status.get("installable_mod_produced") is not False):
        raise WorkshopError("Campaign provenance or safety flags have changed")
    return plan, code


def verify_season(root: Path, pack_id: str) -> tuple[list[str], bytes]:
    if not isinstance(pack_id, str) or not VALID_NAME.fullmatch(pack_id):
        raise WorkshopError("Unsafe season identifier")
    folder = _candidate(root, "season-" + pack_id)
    status = _json(folder, "qa-status.json")
    pack = _json(folder, "pack.json")
    maps = status.get("maps_with_season")
    if (not isinstance(maps, list) or not maps or len(maps) > 100
            or not all(isinstance(m, str) for m in maps)):
        raise WorkshopError("Missing season map routes")
    code = season_csharp_source(pack_id, maps)
    if _small(folder, "OriginsSeasonData.g.cs", _MAX_CS) != code:
        raise WorkshopError("Season C# route table changed")
    rows = status.get("group_hashes")
    if (not isinstance(rows, list) or not rows
            or len(rows) > len(GM_IDS)):
        raise WorkshopError("Season provenance groups missing")
    attested = []
    for row in rows:
        if not isinstance(row, dict) or row.get("gm") not in GM_IDS:
            raise WorkshopError("Unapproved season atlas group")
        attested.append(_season_entry(row["gm"], folder / row["gm"]))
    expected_pack = {
        "schema": 1, "packId": pack_id, "packVersion": 1,
        "groups": [
            {"gm": x["gm"], "gmId": x["gmId"], "tag": x["tag"]}
            for x in attested
        ],
    }
    if (len({r["gm"] for r in attested}) != len(attested)
            or pack != expected_pack or rows != attested
            or status.get("schema") != "sprite-suite.origins-season-candidate.v1"
            or status.get("pack_id") != pack_id
            or status.get("gm_groups") != len(attested)
            or status.get("csharp_route_sha256") != _sha(code)
            or status.get("seasonpack_loader_binary_attested") is not False
            or status.get("installable_mod_produced") is not False
            or status.get("in_game_qa_completed") is not False
            or status.get("steam_game_modified") is not False):
        raise WorkshopError("Season atlas or manifest failed provenance checks")
    return maps, code


def run_offline_qa(project: Path, campaign_slug: str,
                   season_pack_id: str | None = None) -> dict:
    """Verify source bytes, build managed code and execute a sandbox-only harness.

    Output is a new private QA folder. No game/Steam/ScriptExtender path is
    accepted, visited, overwritten or passed to a subprocess.
    """
    root = workspace(project)
    plan, campaign_code = verify_campaign(root, campaign_slug)
    season_code = None
    season_maps = None
    if season_pack_id is not None:
        season_maps, season_code = verify_season(root, season_pack_id)
    if not COMPILER.is_file() or not CORE.is_file() or linked(CORE):
        raise WorkshopError("Windows .NET 4 compiler or audited core unavailable")
    core_before = _sha(CORE.read_bytes())
    # Keep the candidate untouched; staging is a sibling under the work tree.
    parent = root.parent / ".origins-offline-qa"
    if linked(parent):
        raise WorkshopError("Linked QA output directory")
    parent.mkdir(exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="campaign-qa-", dir=parent))
    (folder / "OriginsCampaignData.g.cs").write_bytes(campaign_code)
    (folder / "AuthoredOriginsOfflineQATest.cs").write_text(
        _HARNESS, encoding="utf8")
    names = [str(CORE), str(folder / "OriginsCampaignData.g.cs")]
    if season_code is not None:
        (folder / "OriginsSeasonData.g.cs").write_bytes(season_code)
        names.append(str(folder / "OriginsSeasonData.g.cs"))
    names.append(str(folder / "AuthoredOriginsOfflineQATest.cs"))
    binary = folder / "OriginsOfflineQATest.exe"
    args = [str(COMPILER), "/nologo", "/target:exe", "/optimize+",
            "/out:" + str(binary)]
    if season_code is not None:
        args.append("/define:SEASON")
    args += names
    try:
        compile_result = subprocess.run(
            args, cwd=folder, capture_output=True, text=True,
            encoding="utf8", errors="replace", timeout=40, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WorkshopError("Offline C# compiler could not complete") from error
    (folder / "compile.log").write_text(
        (compile_result.stdout + compile_result.stderr)[:32000],
        encoding="utf8")
    if compile_result.returncode != 0 or not binary.is_file():
        raise WorkshopError("Generated C# offline build failed; see " + str(folder))
    arguments = [str(binary), str(len(plan["missions"])),
                 plan["missions"][0]["map"]]
    if season_code is not None:
        arguments.extend([season_maps[0], season_pack_id])
    try:
        result = subprocess.run(
            arguments, cwd=folder, capture_output=True, text=True,
            encoding="utf8", errors="replace", timeout=15, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WorkshopError("Offline C# behavior test could not complete") from error
    log = result.stdout + result.stderr
    (folder / "behavior.log").write_text(log[:32000], encoding="utf8")
    if (result.returncode != 0
            or "ORIGINS_GAME_DLL_LOADED=0" not in log
            or "ORIGINS_NATIVE_ABI_ATTESTED=0" not in log
            or "ORIGINS_AUTHORED_QA_ASSERTIONS=" not in log):
        raise WorkshopError("Generated C# offline QA failed; see " + str(folder))
    # Verification is repeated *after* execution, ruling out candidate/core
    # races while the managed C# executable was built and exercised.
    _, later = verify_campaign(root, campaign_slug)
    if later != campaign_code or _sha(CORE.read_bytes()) != core_before:
        raise WorkshopError("Runtime or campaign changed during offline QA")
    if season_code is not None:
        _, later_season = verify_season(root, season_pack_id)
        if later_season != season_code:
            raise WorkshopError("Season changed during offline QA")
    report = {
        "schema": "sprite-suite.origins-offline-qa.v1",
        "output": str(folder),
        "campaign_slug": campaign_slug,
        "mission_count": len(plan["missions"]),
        "season_pack_id": season_pack_id,
        "core_sha256": core_before,
        "campaign_data_sha256": _sha(campaign_code),
        "season_data_sha256": _sha(season_code) if season_code else None,
        "managed_core_and_authored_data_compiled": True,
        "offline_behavior_tests_passed": True,
        "native_game_handler_present": False,
        "steam_build_abi_attested": False,
        "in_game_qa_completed": False,
        "installable_mod_produced": False,
        "steam_game_modified": False,
    }
    (folder / "qa-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return report
