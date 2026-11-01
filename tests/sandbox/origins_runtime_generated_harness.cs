// C# 5 offline test for generated campaign or season settings.
using System;
using SpriteSuite.Origins.Authoring;

public static class OriginsGeneratedDataHarness
{
    public static int Main(string[] args)
    {
        try
        {
#if CAMPAIGN
            if (args.Length != 2) return 11;
            var game = AuthoredCampaign.NewSession();
            int expectedCount = Int32.Parse(args[0]);
            if (game.MissionCount != expectedCount) return 12;
            if (game.Missions[expectedCount-1].MapFile != args[1]) return 13;
            if (game.HandleCommand("OriginsLegacyCampaign").Action !=
                MenuAction.OpenCampaign) return 14;
            if (game.HandleCommand("LegacyStart").Action !=
                MenuAction.LaunchRequested) return 15;
            Console.WriteLine("GENERATED_CAMPAIGN_CSHARP_VERIFIED=1");
#elif SEASONS
            if (args.Length != 2) return 21;
            var seasons = AuthoredSeasons.NewSession();
            if (seasons.OnMapLoaded(args[0]) != args[1]) return 22;
            seasons.OnMapUnloaded();
            if (seasons.ActivePack != null) return 23;
            Console.WriteLine("GENERATED_SEASON_ROUTING_VERIFIED=1");
#else
            return 99;
#endif
            Console.WriteLine("NATIVE_GAME_HOOKS_CALLED=0");
            return 0;
        }
        catch (Exception e)
        {
            Console.Error.WriteLine("OFFLINE_GENERATED_QA_ERROR " + e);
            return 98;
        }
    }
}
