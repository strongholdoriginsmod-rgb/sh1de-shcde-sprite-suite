using System;
using System.Collections.Generic;
using SpriteSuite.BuildingDamage;

internal static class HpFireStageHarness
{
    private static int checks;
    private static readonly List<StageDefinition> Stages = new List<StageDefinition> {
        new StageDefinition { Id = "m75", Kind = "mechanical", Threshold = 75 },
        new StageDefinition { Id = "m40", Kind = "mechanical", Threshold = 40 },
        new StageDefinition { Id = "m0", Kind = "mechanical", Threshold = 0 },
        new StageDefinition { Id = "f75", Kind = "fire", Threshold = 75 },
        new StageDefinition { Id = "f40", Kind = "fire", Threshold = 40 },
        new StageDefinition { Id = "f0", Kind = "fire", Threshold = 0 }
    };
    private static void Check(bool value, string reason)
    {
        checks++;
        if (!value) throw new Exception("ASSERTION FAILED: " + reason);
    }
    private static void Choice(int hp, int max, bool fire, string expected)
    {
        string got = BuildingDamageStageLogic.Choose(Stages, hp, max, fire);
        Check(got == expected, hp + "/" + max + " fire=" + fire +
            " expected=" + expected + " got=" + got);
    }
    private static void Main()
    {
        Choice(100, 100, false, null);
        Choice(76, 100, false, null);
        Choice(75, 100, false, "m75");
        Choice(41, 100, false, "m75");
        Choice(40, 100, false, "m40");
        Choice(1, 100, false, "m40");
        Choice(0, 100, false, "m0");
        Choice(17, 40, false, "m75");
        Choice(16, 40, false, "m40");
        Choice(0, 40, false, "m0");
        Choice(100, 100, true, "f75");
        Choice(90, 100, true, null);
        Choice(75, 100, true, "f75");
        Choice(40, 100, true, "f40");
        Choice(0, 100, true, "f0");
        Choice(16, 40, true, "f40");
        Choice(101, 100, false, null);
        Choice(-1, 100, false, null);
        Choice(10, 0, false, null);
        var onlyMechanical = Stages.GetRange(0, 3);
        Check(BuildingDamageStageLogic.Choose(onlyMechanical, 30, 100, true) == "m40",
            "fire fallback to mechanical");
        var history = new BuildingFireHistory();
        Check(!history.Update(1001, 100, 100, 0), "initially unburned");
        Check(history.Update(1001, 100, 100, 10), "fire starts at 100 HP");
        Check(history.Update(1001, 55, 100, 0), "fire remains after extinguish");
        Check(!history.Update(1002, 55, 100, 0), "unrelated building remains unburned");
        Check(history.Update(1001, 99, 100, 0), "fire remains while partially repaired");
        Check(!history.Update(1001, 100, 100, 0), "fire clears on full repair");
        Check(history.Update(1001, 70, 100, 12), "fire reattaches");
        history.Remove(1001);
        Check(!history.Update(1001, 70, 100, 0), "remove clears identity");
        history.Update(1003, 30, 100, 8);
        history.Clear();
        Check(!history.Update(1003, 30, 100, 0), "scene clear drops history");
        Check(!history.Update(0, 55, 100, 9), "zero identity ignored");
        Check(!history.Update(1001, 30, 0, 9), "invalid max ignored");
        Console.WriteLine("HP_FIRE_CSHARP_ASSERTIONS=" + checks);
    }
}
