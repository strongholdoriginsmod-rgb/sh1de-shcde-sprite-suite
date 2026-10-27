namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Normalizes the native placement-validator result only after the farm
    /// rule has positively identified a safe land tile.
    /// </summary>
    internal static class FarmPlacementResultDecision
    {
        internal const long CanonicalPlaceableResult = 1L;

        internal static long Normalize(long nativeResult, bool loosen)
        {
            // Native observations contain at least 1, 2, 3, 391 and 395.
            // Earlier code changed only 3 -> 1. Sessions also returned 2, 391
            // and 395 for tiles which our complete land predicate had accepted,
            // leaving those calls at Crusader's oasis-only verdict. Once the
            // predicate has positively answered Loosen, use the one measured
            // canonical placeable state independent of the native encoding.
            // Silent and Block decisions preserve the native result exactly.
            return loosen ? CanonicalPlaceableResult : nativeResult;
        }
    }
}
