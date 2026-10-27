using SHCDESE.API;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Which hook library the loaded Script Extender is built on.
    /// </summary>
    /// <remarks>
    /// SE 1.x shipped Zhuqiaomon, SE 2.x replaced it with RedBird (same
    /// member names, different assembly). This runtime compiles against
    /// RedBird, so on every configuration it can load at all, the SE-1.44
    /// workarounds that reach into Zhuqiaomon internals
    /// (<see cref="ScriptExtenderScanBufferBorrowPatch"/>,
    /// <see cref="ScriptExtenderScanBufferRelease"/>,
    /// <see cref="ScriptExtenderVegetationCapabilities"/>) have nothing to
    /// patch. They stay in the tree until they are either re-measured for
    /// RedBird or removed in the cleanup pass; this switch keeps them off.
    /// </remarks>
    internal static class ScriptExtenderGeneration
    {
        internal static bool UsesRedBird
        {
            get
            {
                return typeof(GameAssetManagerAPI).Assembly.GetName().Version.Major >= 2;
            }
        }

        internal static string Describe()
        {
            return "SEDE_RUNTIME_V1|event=script_extender_generation"
                + "|version=" + typeof(GameAssetManagerAPI).Assembly.GetName().Version
                + "|hook_library=" + (UsesRedBird ? "redbird" : "zhuqiaomon")
                + "|zhuqiaomon_workarounds=" + (UsesRedBird ? "not_applicable" : "available");
        }
    }
}
