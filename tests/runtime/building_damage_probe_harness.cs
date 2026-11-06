using System;
using System.Collections.Generic;
using StrongholdEuropeDE.Runtime;

namespace SHCDESE.API
{
    // Synthetic compile-only facade matching the documented API signatures.
    // No game assemblies, process, hook, renderer or installation are loaded.
    public enum TestBuildingType { Abbey = 108, Hovel = 109 }
    public class GameBuildingManagerAPI
    {
        public static GameBuildingManagerAPI Instance { get; set; }
        public int[] Alive = new int[] { 3 };
        public int Global = 9001;
        public int ChangedGlobal = 0;
        public int Health = 80, Max = 100, Fire = 0;
        public TestBuildingType Type = TestBuildingType.Abbey;
        public bool IsAlive = true, ThrowOnRead = false;
        public bool SwapGlobalDuringRead = false;
        public bool SwapInstanceDuringRead = false;
        public int GlobalReadCount = 0;

        public int[] GetAllAliveBuildings() { return Alive; }
        public bool IsValid(int id) { return id > 0 && IsAlive; }
        public int GetGlobalId(int id)
        {
            GlobalReadCount++;
            if (SwapGlobalDuringRead && GlobalReadCount > 1)
                return ChangedGlobal;
            return Global;
        }
        public TestBuildingType GetType(int id) { return Type; }
        public int GetCurrentHealth(int id)
        {
            if (ThrowOnRead) throw new InvalidOperationException("synthetic get health");
            if (SwapInstanceDuringRead) Instance = new GameBuildingManagerAPI();
            return Health;
        }
        public int GetMaxHealth(int id) { return Max; }
        public ushort GetOnFireTicks(int id) { return (ushort)Fire; }
    }
}

internal static class BuildingDamageProbeHarness
{
    private static int _tests;
    private static void Assert(bool ok, string label)
    {
        _tests++;
        if (!ok) throw new Exception("FAIL: " + label);
    }

    internal sealed class BogusSource : BuildingDamageReadOnlyProbe.ISource
    {
        internal int[] Ids = new[] { 7 };
        internal bool Mismatch, Throw, Fire, Invalid;
        public int[] GetAliveBuildingIds()
        {
            if (Throw) throw new InvalidOperationException("synthetic list");
            return Ids;
        }
        public bool TryRead(int id, out BuildingDamageReadOnlyProbe.Snapshot snapshot)
        {
            snapshot = new BuildingDamageReadOnlyProbe.Snapshot(
                Mismatch ? id + 1 : id, 701, 108,
                Invalid ? -1 : 35, 100, Fire ? 5 : 0);
            return true;
        }
    }

    private static BuildingDamageStageSelector.Observer Observer()
    {
        var mech = BuildingDamageStageSelector.Cause.Mechanical;
        var fire = BuildingDamageStageSelector.Cause.Fire;
        var profile = new BuildingDamageStageSelector.Profile(108, "g_abbey",
            new[] {
                new BuildingDamageStageSelector.Stage("light", "scene_light", mech, 75),
                new BuildingDamageStageSelector.Stage("heavy", "scene_heavy", mech, 40),
                new BuildingDamageStageSelector.Stage("burn", "scene_burn", fire, 50)
            });
        return new BuildingDamageStageSelector.Observer(new[] { profile });
    }

    private static string Selected(BuildingDamageReadOnlyProbe.PollReport report)
    {
        return report.Buildings.Length == 0 || report.Buildings[0].Selected == null ?
            "" : report.Buildings[0].Selected.Id;
    }

    public static void Main()
    {
        var fakeApi = new SHCDESE.API.GameBuildingManagerAPI();
        SHCDESE.API.GameBuildingManagerAPI.Instance = fakeApi;
        var gameSource = new BuildingDamageGameBuildingSource();
        var loop = new BuildingDamageReadOnlyProbe.Monitor(gameSource, Observer());
        var current = loop.Poll();
        Assert(current.Ready && Selected(current) == "", "80 percent uses intact");
        Assert(current.Buildings[0].BuildingId == 3 &&
               current.Buildings[0].GlobalId == 9001, "game global identity");
        fakeApi.Health = 75;
        current = loop.Poll();
        Assert(Selected(current) == "light", "published API mechanical HP threshold");
        fakeApi.Health = 45;
        current = loop.Poll();
        Assert(Selected(current) == "light", "stage until heavy threshold");
        fakeApi.Fire = 5;
        current = loop.Poll();
        Assert(Selected(current) == "burn" &&
               current.Buildings[0].EffectiveCause == BuildingDamageStageSelector.Cause.Fire,
               "published API fire ticks");
        fakeApi.Fire = 0; fakeApi.Health = 30;
        current = loop.Poll();
        Assert(Selected(current) == "burn", "extinguished flame remains damaged");
        fakeApi.Health = 100;
        current = loop.Poll();
        Assert(Selected(current) == "", "fully repaired returns vanilla");
        fakeApi.Health = 30;
        current = loop.Poll();
        Assert(Selected(current) == "heavy", "after repair mechanical");
        fakeApi.Global = 9002;
        current = loop.Poll();
        Assert(Selected(current) == "heavy" &&
               current.Buildings[0].GlobalId == 9002, "global slot reused safely");
        fakeApi.Type = SHCDESE.API.TestBuildingType.Hovel;
        current = loop.Poll();
        Assert(current.Ready && current.Buildings[0].UseVanilla,
            "unknown building type uses vanilla");
        Assert(loop.PollCount == 9, "read-only tick count");
        loop.Reset();
        Assert(loop.PollCount == 0 && !loop.Faulted, "map reset");

        fakeApi = new SHCDESE.API.GameBuildingManagerAPI();
        fakeApi.Health = 38;
        fakeApi.SwapGlobalDuringRead = true;
        fakeApi.ChangedGlobal = 6002;
        SHCDESE.API.GameBuildingManagerAPI.Instance = fakeApi;
        loop = new BuildingDamageReadOnlyProbe.Monitor(gameSource, Observer());
        current = loop.Poll();
        Assert(!current.Ready && current.Reason == "inconsistent_building_snapshot",
            "global ID change mid-read fails closed");
        Assert(loop.Faulted && !loop.Poll().Ready &&
               loop.Poll().Reason == "observer_faulted", "latches failure");
        fakeApi.SwapGlobalDuringRead = false;
        loop.Reset();
        Assert(loop.Poll().Ready, "explicit reset recovers");

        fakeApi.ThrowOnRead = true;
        current = loop.Poll();
        Assert(!current.Ready && current.Reason == "building_api_exception",
            "API exception fails closed");
        Assert(current.Buildings.Length == 0, "no stale result after failure");
        fakeApi.ThrowOnRead = false;
        loop.Reset();

        fakeApi.SwapInstanceDuringRead = true;
        current = loop.Poll();
        Assert(!current.Ready, "singleton switched mid-read fails closed");
        SHCDESE.API.GameBuildingManagerAPI.Instance = fakeApi;
        fakeApi.SwapInstanceDuringRead = false;
        loop.Reset();
        Assert(loop.Poll().Ready, "stable singleton recovers");

        var source = new BogusSource();
        var checker = new BuildingDamageReadOnlyProbe.Monitor(source, Observer());
        current = checker.Poll();
        Assert(current.Ready && Selected(current) == "heavy", "portable synthetic source");
        source.Fire = true;
        current = checker.Poll();
        Assert(current.Ready && Selected(current) == "burn", "portable fire classification");
        source.Ids = new int[] { 7, 7 };
        current = checker.Poll();
        Assert(!current.Ready && current.Reason == "invalid_or_duplicate_building_id",
            "reject duplicate IDs");
        source.Ids = new int[] { 7 };
        Assert(!checker.Poll().Ready, "still stopped after corrupted list");
        checker.Reset();
        source.Mismatch = true;
        current = checker.Poll();
        Assert(!current.Ready && current.Reason == "inconsistent_building_snapshot",
            "snapshot cannot swap ID");
        checker.Reset();
        source.Mismatch = false;
        source.Invalid = true;
        Assert(!checker.Poll().Ready, "negative health fails closed");
        checker.Reset();
        source.Invalid = false;
        source.Ids = new int[] { 7, 8, 9 };
        current = checker.Poll();
        Assert(current.Ready && current.Buildings.Length == 3,
            "reads valid multiple buildings");
        source.Ids = new int[] { 8 };
        current = checker.Poll();
        Assert(current.Ready && current.Buildings.Length == 1,
            "prunes dead buildings");
        source.Ids = null;
        current = checker.Poll();
        Assert(!current.Ready && current.Reason == "invalid_building_list",
            "invalid list disables monitoring");
        checker.Reset();
        source.Ids = new int[] { 10 };
        source.Throw = true;
        current = checker.Poll();
        Assert(!current.Ready && current.Reason == "building_api_exception",
            "source list exception disables monitoring");

        Console.WriteLine("PASS building damage read-only API probe: " + _tests +
                          " assertions.");
    }
}
