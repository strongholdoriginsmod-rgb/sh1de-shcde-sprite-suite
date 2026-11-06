using System;
using System.Collections.Generic;
using StrongholdEuropeDE.Runtime;

internal static class BuildingDamageSelectorHarness
{
    private static int _count;
    private static void Check(bool correct, string label)
    {
        _count++;
        if (!correct) throw new Exception("FAIL " + label);
    }
    private static void ExpectError(Action action, string label)
    {
        bool threw = false;
        try { action(); }
        catch (ArgumentException) { threw = true; }
        Check(threw, label);
    }
    private static BuildingDamageStageSelector.Stage Stage(string id, string scene,
        BuildingDamageStageSelector.Cause cause, int hp)
    {
        return new BuildingDamageStageSelector.Stage(id, scene, cause, hp);
    }
    private static string Current(BuildingDamageStageSelector.Result r)
    {
        return r.Selected == null ? "" : r.Selected.Id;
    }
    public static void Main(string[] args)
    {
        var mechanical = BuildingDamageStageSelector.Cause.Mechanical;
        var fire = BuildingDamageStageSelector.Cause.Fire;
        var profile = new BuildingDamageStageSelector.Profile(108, "tile_abbey",
            new[] {
                Stage("near", "damage_zero", mechanical, 0),
                Stage("heavy", "damage_heavy", mechanical, 40),
                Stage("light", "damage_light", mechanical, 75),
                Stage("f80", "fire_light", fire, 80),
                Stage("f30", "fire_heavy", fire, 30),
            });
        int[] hp = { 100, 76, 75, 41, 40, 1, 0 };
        string[] expect = { "", "", "light", "light", "heavy", "heavy", "near" };
        for (int i = 0; i < hp.Length; i++)
            Check(Current(new BuildingDamageStageSelector.Result(
                1, 12, 108, hp[i], 100, false, mechanical,
                BuildingDamageStageSelector.Choose(profile, mechanical, hp[i], 100),
                "simulation")) == expect[i], "inclusive-HP-" + hp[i]);
        Check(BuildingDamageStageSelector.Choose(profile, mechanical, 75, 100).Id == "light",
            "boundary-included");
        Check(BuildingDamageStageSelector.Choose(profile, mechanical, 76, 100) == null,
            "boundary-excluded");
        Check(BuildingDamageStageSelector.Choose(profile, mechanical, 0, 100).Id == "near",
            "zero-hp");
        Check(BuildingDamageStageSelector.Choose(profile, fire, 50, 100).Id == "f80",
            "fire-branch");
        Check(BuildingDamageStageSelector.Choose(profile, fire, 20, 100).Id == "f30",
            "fire-stronger-branch");

        var onlyMechanical = new BuildingDamageStageSelector.Profile(109, "tile_tower",
            new[] { Stage("mh", "tower_damage", mechanical, 25) });
        Check(BuildingDamageStageSelector.Choose(onlyMechanical, fire, 20, 100).Id == "mh",
            "fire-only-fallback");
        Check(BuildingDamageStageSelector.Choose(profile, fire, 81, 100) == null,
            "no-fire-stage-above-threshold");
        Check(BuildingDamageStageSelector.Choose(profile, fire, 50, 100).Id == "f80",
            "no-mechanical-mixing");

        var observer = new BuildingDamageStageSelector.Observer(new[] { profile, onlyMechanical });
        Check(observer.ProfileCount == 2 && observer.TrackedCount == 0,
            "initial-state");
        Check(Current(observer.Observe(5, 1001, 108, 100, 100, 0)) == "",
            "initial-intact");
        Check(Current(observer.Observe(5, 1001, 108, 70, 100, 0)) == "light",
            "first-mechanical");
        var burning = observer.Observe(5, 1001, 108, 70, 100, 1);
        Check(burning.FireObserved && burning.EffectiveCause == fire &&
            Current(burning) == "f80", "burn-transition");
        var extinguished = observer.Observe(5, 1001, 108, 35, 100, 0);
        Check(extinguished.FireObserved && Current(extinguished) == "f80",
            "fire-persist-until-healed");
        var severelyBurned = observer.Observe(5, 1001, 108, 20, 100, 0);
        Check(Current(severelyBurned) == "f30", "burn-progression");
        Check(Current(observer.Observe(5, 1001, 108, 100, 100, 0)) == "",
            "fully-repaired-clears-burn-history");
        Check(Current(observer.Observe(5, 1001, 108, 35, 100, 0)) == "heavy",
            "repaired-then-mechanical");
        var reuse = observer.Observe(5, 1002, 108, 35, 100, 0);
        Check(!reuse.FireObserved && Current(reuse) == "heavy",
            "building-id-reuse-global-id-guard");
        var changedType = observer.Observe(5, 1002, 109, 20, 100, 0);
        Check(Current(changedType) == "mh", "building-id-reuse-type-guard");
        Check(observer.Observe(5, 1002, 110, 20, 100, 0).UseVanilla,
            "unknown-type-vanilla");
        Check(observer.TrackedCount == 0, "unknown-type-forget");

        var invalid = observer.Observe(5, 1001, 108, -1, 100, 0);
        Check(invalid.UseVanilla && invalid.Reason == "invalid_snapshot", "negative-hp");
        Check(observer.Observe(5, 0, 108, 25, 100, 20).UseVanilla, "invalid-global-id");
        Check(observer.Observe(5, 1003, 108, 101, 100, 0).UseVanilla,
            "max-below-current");
        Check(observer.Observe(5, 1003, 108, 70, 0, 0).UseVanilla,
            "zero-max");
        var big = BuildingDamageStageSelector.Choose(profile, mechanical,
            (int)(0.4 * int.MaxValue), int.MaxValue);
        Check(big != null && big.Id == "heavy", "integer-cross-product-no-overflow");
        var below = BuildingDamageStageSelector.Choose(profile, mechanical,
            int.MaxValue, int.MaxValue);
        Check(below == null, "high-health-integrity");

        observer.Observe(1, 101, 108, 70, 100, 1);
        observer.Observe(2, 102, 108, 50, 100, 1);
        observer.RetainAlive(new[] { 2 });
        Check(observer.TrackedCount == 1, "alive-pruning");
        observer.Forget(2);
        Check(observer.TrackedCount == 0, "deletion-cleanup");
        observer.Observe(3, 103, 108, 40, 100, 1);
        observer.Clear();
        Check(observer.TrackedCount == 0, "map-unload-clears-state");

        ExpectError(delegate { Stage("bad", "scene", mechanical, 100); }, "invalid-threshold");
        ExpectError(delegate { Stage("bad", "", mechanical, 50); }, "invalid-scene");
        ExpectError(delegate {
            new BuildingDamageStageSelector.Profile(108, "x", new[] {
                Stage("id1", "s1", mechanical, 75), Stage("id2", "s2", mechanical, 75)
            });
        }, "duplicate-cause-threshold");
        ExpectError(delegate {
            new BuildingDamageStageSelector.Observer(new[] { profile, profile });
        }, "duplicate-building-type");
        ExpectError(delegate {
            new BuildingDamageStageSelector.Profile(-1, "x", new[] { Stage("ok", "s", fire, 75) });
        }, "invalid-building-type");

        string header = "# stronghold-building-damage-runtime-table-v1\n" +
            "# Generated from SHA-verified damage library; not an active game mod\n" +
            "# package-sha256 ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n" +
            "building_type\tbuilding_group\tdamage_kind\thp_le\tstage_id\tscene_id\n";
        var parsed = BuildingDamageProfileTable.Parse(header +
            "108\tg_abbey\tmechanical\t75\td_light\tg_light\n" +
            "108\tg_abbey\tmechanical\t40\td_heavy\tg_heavy\n" +
            "108\tg_abbey\tfire\t50\td_burned\tg_burned\n");
        Check(parsed.Profiles.Length == 1 && parsed.Profiles[0].Stages.Length == 3,
            "parse-preflight-stages");
        Check(parsed.Profiles[0].BuildingType == 108, "type-carries-into-runtime");
        Check(BuildingDamageProfileTable.MatchesPackage(parsed,
            System.Text.Encoding.ASCII.GetBytes("abc")), "package-hash-pinned");
        Check(!BuildingDamageProfileTable.MatchesPackage(parsed,
            System.Text.Encoding.ASCII.GetBytes("abx")), "package-hash-rejects-replaced-zip");
        var parsedObserver = new BuildingDamageStageSelector.Observer(parsed.Profiles);
        Check(Current(parsedObserver.Observe(3, 300, 108, 42, 100, 0)) == "d_light",
            "real-prepared-table-stage-selection");
        bool formatError = false;
        try { BuildingDamageProfileTable.Parse(header + "108\t../bad\tmechanical\t50\tid\tgroup\n"); }
        catch (FormatException) { formatError = true; }
        Check(formatError, "table-path-traversal-rejected");
        formatError = false;
        try { BuildingDamageProfileTable.Parse(header +
            "108\tg_abbey\tmechanical\t75\td_1\tg_1\n" +
            "108\tg_abbey\tmechanical\t75\td_2\tg_2\n"); }
        catch (FormatException) { formatError = true; }
        Check(formatError, "table-duplicate-threshold-rejected");

        string v2 = "# stronghold-building-damage-runtime-table-v2\n" +
            "# Generated from SHA-verified damage library; not an active game mod\n" +
            "# package-sha256 ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n" +
            "building_type\tbuilding_group\tsprite_a\tsprite_b\tdamage_kind\thp_le\tstage_id\tscene_id\n";
        var parsedGrid = BuildingDamageProfileTable.Parse(v2 +
            "108\tg_abbey\t5\t5\tmechanical\t75\td_light\tg_light\n" +
            "108\tg_abbey\t5\t5\tfire\t40\td_fire\tg_fire\n");
        Check(parsedGrid.Profiles.Length == 1 &&
            parsedGrid.Profiles[0].SpriteA == 5 &&
            parsedGrid.Profiles[0].SpriteB == 5,
            "v2 includes sprite grid dimensions");
        Check(parsed.Profiles[0].SpriteA == 0 && parsed.Profiles[0].SpriteB == 0,
            "v1 continues to parse but has no verified grid");
        formatError = false;
        try {
            BuildingDamageProfileTable.Parse(v2 +
                "108\tg_abbey\t5\t5\tmechanical\t75\td_light\tg_light\n" +
                "108\tg_abbey\t3\t3\tfire\t40\td_fire\tg_fire\n");
        }
        catch (FormatException) { formatError = true; }
        Check(formatError, "v2 rejects inconsistent grid dimensions");
        formatError = false;
        try {
            BuildingDamageProfileTable.Parse(v2 +
                "108\tg_abbey\t0\t5\tmechanical\t75\td_light\tg_light\n");
        }
        catch (FormatException) { formatError = true; }
        Check(formatError, "v2 rejects missing grid dimension");
        formatError = false;
        try {
            BuildingDamageProfileTable.Parse(v2 +
                "108\tg_abbey\t5\t5\tmechanical\t75\td_light\tg_light\ttrailing\n");
        }
        catch (FormatException) { formatError = true; }
        Check(formatError, "v2 rejects unknown columns");

        if (args.Length != 0)
        {
            Check(args.Length == 2, "integration-requires-table-and-zip");
            var tableDoc = BuildingDamageProfileTable.Parse(
                System.IO.File.ReadAllText(args[0], System.Text.Encoding.UTF8));
            Check(BuildingDamageProfileTable.MatchesPackage(tableDoc,
                System.IO.File.ReadAllBytes(args[1])), "real-asset-manifest-hash");
            Check(tableDoc.Profiles.Length == 1, "real-asset-building-count");
            Check(tableDoc.Profiles[0].BuildingType == 108, "real-asset-building-type");
            Check(tableDoc.Profiles[0].Stages.Length == 2, "real-asset-stages-count");
            Check(tableDoc.Profiles[0].SpriteA == 5 &&
                  tableDoc.Profiles[0].SpriteB == 5,
                  "real-export-preserves-5x5-sprite-footprint");
            var live = new BuildingDamageStageSelector.Observer(tableDoc.Profiles);
            var at75 = live.Observe(1, 7001, 108, 75, 100, 0);
            var at40 = live.Observe(1, 7001, 108, 40, 100, 0);
            Check(!at75.UseVanilla && at75.Selected.HpAtOrBelow == 75,
                "real-asset-mechanical-hp");
            Check(!at40.UseVanilla && at40.Selected.HpAtOrBelow == 75,
                "real-asset-mechanical-fallback-until-lower-threshold");
            var registeredFire = live.Observe(1, 7001, 108, 35, 100, 5);
            Check(!registeredFire.UseVanilla &&
                registeredFire.Selected.DamageCause == BuildingDamageStageSelector.Cause.Fire &&
                registeredFire.Selected.HpAtOrBelow == 40,
                "real-asset-fire-selection");
        }
        Console.WriteLine("PASS building damage runtime selection: " + _count + " assertions.");
    }
}
