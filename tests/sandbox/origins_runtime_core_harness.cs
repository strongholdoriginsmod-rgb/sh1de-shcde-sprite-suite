// Dependency-free runtime core QA harness, compiled and run OUTSIDE the game.
using System;
using System.Collections.Generic;
using SpriteSuite.Origins.Authoring;

public sealed class FakeVerifiedGameHost : IOriginsVerifiedGameHost
{
    public bool Abi, Menu, Seasons, LaunchAllowed=true, RestoreAllowed=true;
    public int MenuShows, MenuBacks, Launches, Activations, Restores;
    public string LastMap, LastPack;
    public bool IsNativeGameAbiVerified { get { return Abi; } }
    public bool IsNoesisMenuBindingsVerified { get { return Menu; } }
    public bool IsSeasonAtlasLoaderVerified { get { return Seasons; } }
    public bool TryShowCampaignScreen() { ++MenuShows; return true; }
    public bool TryShowOriginalMainMenu() { ++MenuBacks; return true; }
    public bool TryLaunchMission(string map)
    {
        ++Launches;
        LastMap=map;
        return LaunchAllowed;
    }
    public bool TryActivateSeason(string pack)
    {
        ++Activations; LastPack=pack; return true;
    }
    public bool TryRestoreOriginalAtlases()
    {
        ++Restores; return RestoreAllowed;
    }
}

public static class OriginsRuntimeCoreHarness
{
    private static int _passed;
    private static void Assert(bool condition, string name)
    {
        if (!condition) throw new Exception("FAILED " + name);
        ++_passed;
    }

    private static bool Throws<T>(Action callback) where T: Exception
    {
        try { callback(); }
        catch (T) { return true; }
        return false;
    }

    public static int Main(string[] args)
    {
        try
        {
            var list = new List<Mission>();
            for (int i=1; i<=21; ++i)
                list.Add(new Mission(i, "Mission " + i, "Map " + i + ".map"));
            var campaign = new CampaignSession(list);
            Assert(campaign.MissionCount==21,"all 21 missions");
            Assert(campaign.HandleCommand("LegacyStart").Action ==
                   MenuAction.RejectedState,"no launch without screen");
            Assert(campaign.HandleCommand("LegacyM2").Action ==
                   MenuAction.RejectedState,"no selection before menu");
            Assert(campaign.HandleCommand("OriginsLegacyCampaign").Action ==
                   MenuAction.OpenCampaign,"campaign opens");
            Assert(campaign.HandleCommand("LegacyM2").Action ==
                   MenuAction.RejectedLocked,"locked mission rejected");
            Assert(campaign.HandleCommand("LegacyM1").Action ==
                   MenuAction.SelectedMission,"first mission selected");
            var launch=campaign.HandleCommand("LegacyStart");
            Assert(launch.Action==MenuAction.LaunchRequested &&
                   launch.MapFile=="Map 1.map","exact map request returned");
            Assert(campaign.MarkCompleted(1),"first mission completed");
            Assert(campaign.UnlockedMission==2,"next mission unlocked");
            Assert(!campaign.MarkCompleted(1),"completion idempotent");
            Assert(!campaign.MarkCompleted(5),"locked mission never completed");
            Assert(campaign.HandleCommand("LegacyM2").Action==
                   MenuAction.SelectedMission,"mission two selected");
            Assert(campaign.HandleCommand("LegacyStart").MapFile=="Map 2.map",
                   "second map request");
            Assert(campaign.HandleCommand("LegacyM999").Action==
                   MenuAction.Ignored,"unknown index ignored");
            Assert(campaign.HandleCommand("LegacyM02").Action==
                   MenuAction.Ignored,"ambiguous mission index ignored");
            Assert(campaign.HandleCommand("OriginsScriptHook").Action==
                   MenuAction.Ignored,"unknown native hook never executed");
            var state=campaign.ExportProgress();
            Assert(state.UnlockedMission==2 && state.SelectedMission==2 &&
                   state.CompletedMissions.Length==1,"progress snapshot");
            var restored=new CampaignSession(list);
            restored.RestoreProgress(state);
            Assert(restored.UnlockedMission==2 && restored.SelectedMission==2,
                   "valid progress restored");
            Assert(!restored.IsCampaignScreenOpen,
                   "restoring progress never triggers game UI");
            Assert(Throws<ArgumentException>(() => restored.RestoreProgress(
                new ProgressSnapshot(4,4,new int[0]))),
                "corrupt progress cannot unlock missions");
            Assert(Throws<ArgumentException>(() => restored.RestoreProgress(
                new ProgressSnapshot(2,2,new int[]{1,1}))),
                "duplicate completed missions forbidden");
            Assert(restored.UnlockedMission==2,
                   "failed restore never modifies current state");
            Assert(campaign.HandleCommand("LegacyBack").Action==
                   MenuAction.BackToMenu,"return to original menu");
            Assert(!campaign.IsCampaignScreenOpen,"menu closed");
            Assert(Throws<ArgumentException>(()=> new Mission(1,"Title","../escape.map")),
                   "unsafe map path blocked");
            Assert(Throws<ArgumentException>(()=> new Mission(1,"Title","C:evil.map")),
                   "Windows path blocked");
            Assert(Throws<ArgumentException>(()=> new CampaignSession(
                new List<Mission>{new Mission(1,"One","One.map"),
                                  new Mission(1,"Duplicate","Duplicate.map")})),
                   "duplicate mission number rejected");
            var group=new SeasonGroup("tree_pine",30);
            Assert(group.GmId==30,"historical GM group identity");
            Assert(Throws<ArgumentException>(()=> new SeasonGroup("tree_pine",31)),
                   "native GM mismatch rejected");
            Assert(Throws<ArgumentException>(()=> new SeasonGroup("evil_engine",30)),
                   "unapproved native GM group rejected");
            var season=new SeasonSession(new List<SeasonRoute>{
                new SeasonRoute("Antioch.map","winterpack"),
                new SeasonRoute("Demo.map","summerpack")
            });
            Assert(season.ActivePack==null,"season begins clean");
            Assert(season.OnMapLoaded("Antioch.map")=="winterpack",
                   "map specific season resolution");
            Assert(season.OnMapLoaded("Unknown.map")==null,
                   "unmatched maps use original game season");
            Assert(season.OnMapLoaded("../evil.map")==null &&
                   season.CurrentMap==null,"unsafe maps reset state");
            Assert(season.OnMapLoaded("Demo.map")=="summerpack",
                   "subsequent map season");
            season.OnMapUnloaded();
            Assert(season.ActivePack==null && season.CurrentMap==null,
                   "map unload returns baseline");
            Assert(Throws<ArgumentException>(() => new SeasonSession(
                new List<SeasonRoute>{new SeasonRoute("X.map","winter"),
                    new SeasonRoute("x.map","summer")})),
                    "duplicate map route blocked case insensitively");
            // The host bridge proves all runtime effects are blocked until
            // the *actual* game and Noesis adapters verify their contracts.
            var host=new FakeVerifiedGameHost();
            var bridgeCampaign=new CampaignSession(list);
            var bridgeSeasons=new SeasonSession(new List<SeasonRoute>{
                new SeasonRoute("Antioch.map","winterpack"),
                new SeasonRoute("Demo.map","summerpack")
            });
            var bridge=new OriginsGameBridge(bridgeCampaign,bridgeSeasons,host);
            Assert(bridge.OnNoesisCommand("OriginsLegacyCampaign").Action==
                   MenuAction.RejectedState,"unverified Noesis command blocked");
            Assert(!bridge.OnMapLoaded("Antioch.map"),
                   "unverified native season loader blocked");
            Assert(host.MenuShows==0 && host.Activations==0,
                   "no game calls when ABI is unverified");
            host.Abi=true;
            Assert(bridge.OnNoesisCommand("OriginsLegacyCampaign").Action==
                   MenuAction.RejectedState,
                   "ABI alone cannot enable unverified Noesis binding");
            host.Menu=true;
            Assert(bridge.OnNoesisCommand("OriginsLegacyCampaign").Action==
                   MenuAction.OpenCampaign && host.MenuShows==1,
                   "reviewed host command opens campaign");
            Assert(bridge.OnNoesisCommand("LegacyM2").Action==
                   MenuAction.RejectedLocked,"bound new game commands still enforce locks");
            host.LaunchAllowed=false;
            Assert(bridge.OnNoesisCommand("LegacyStart").Action==
                   MenuAction.RejectedState,"native host refused the launch");
            host.LaunchAllowed=true;
            Assert(bridge.OnNoesisCommand("LegacyStart").Action==
                   MenuAction.LaunchRequested && host.LastMap=="Map 1.map",
                   "verified host receives exact selected mission map");
            Assert(bridge.OnNoesisCommand("LegacyBack").Action==
                   MenuAction.BackToMenu && host.MenuBacks==1,
                   "host routes back to original menu");
            Assert(!bridge.OnMapLoaded("Antioch.map"),
                   "native ABI alone never permits unverified season atlas loader");
            host.Seasons=true;
            Assert(bridge.OnMapLoaded("Antioch.map") &&
                   bridgeSeasons.ActivePack=="winterpack" &&
                   host.LastPack=="winterpack","attested season map activates atlas");
            host.RestoreAllowed=false;
            Assert(!bridge.OnMapLoaded("Demo.map") &&
                   bridgeSeasons.ActivePack=="winterpack",
                   "failed old-atlas recovery blocks next season");
            host.RestoreAllowed=true;
            Assert(bridge.OnMapLoaded("Demo.map") &&
                   bridgeSeasons.ActivePack=="summerpack" &&
                   host.Restores>=2,
                   "previous season restored before loading next map");
            Assert(bridge.OnMapUnloaded() &&
                   bridgeSeasons.ActivePack==null,
                   "map-unload requires full original atlas restoration");
            host.Abi=false;
            Assert(!bridge.OnMapLoaded("Antioch.map"),
                   "ABI revoked blocks all future season requests");
            Console.WriteLine("ORIGINS_RUNTIME_CORE_TESTS_PASSED=" + _passed);
            Console.WriteLine("ORIGINS_NATIVE_GAME_DLL_LOADED=0");
            Console.WriteLine("ORIGINS_IN_GAME_QA_APPROVED=0");
            return 0;
        }
        catch (Exception exc)
        {
            Console.Error.WriteLine("ORIGINS_RUNTIME_CORE_TEST_FAILURE: " + exc);
            return 1;
        }
    }
}
