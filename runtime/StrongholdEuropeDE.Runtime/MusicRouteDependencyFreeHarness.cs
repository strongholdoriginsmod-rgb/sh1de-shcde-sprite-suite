#if MUSIC_ROUTE_HARNESS
using System;

namespace StrongholdEuropeDE.Runtime
{
    internal static class GeneratedMusicRouteContract
    {
        internal const int EntryCount = 3;
        internal static readonly string[] RequestedFiles =
            { "oud_20.raw", "oud_21.raw", "null_05.raw" };
        internal static readonly string[] ReplacementPaths =
            {
                "fx\\music\\eu_oud_cycle.raw",
                "fx\\music\\eu_oud_cycle.raw",
                "fx\\music\\eu_null_05.raw",
            };
    }

    internal static class MusicRouteDependencyFreeHarness
    {
        private static int Main()
        {
            string replacement;
            string fallback;
            Require(
                MusicRouteRewriter.TryResolvePcmRoute(
                    "FX/MUSIC/OUD_20.RAW",
                    out replacement,
                    out fallback),
                "original request route");
            Require(replacement == "fx\\music\\eu_oud_cycle.raw",
                "canonical replacement");
            Require(fallback == "FX/MUSIC/OUD_20.RAW",
                "original path preserved as fallback");

            Require(
                MusicRouteRewriter.TryResolvePcmRoute(
                    "fx/music/oud_21.raw",
                    out replacement,
                    out fallback),
                "duplicate replacement route remains valid");
            Require(replacement == "fx\\music\\eu_oud_cycle.raw",
                "duplicate route canonical replacement");
            Require(fallback == "fx/music/oud_21.raw",
                "second original remains its own fallback");

            Require(!MusicRouteRewriter.TryResolvePcmRoute(
                    "fx\\music\\unmapped.raw",
                    out replacement,
                    out fallback),
                "unmapped path remains untouched");
            Console.WriteLine("Music route harness: 7/7 passed");
            return 0;
        }

        private static void Require(bool condition, string label)
        {
            if (!condition)
            {
                throw new InvalidOperationException("FAIL " + label);
            }
            Console.WriteLine("PASS " + label);
        }
    }
}
#endif
