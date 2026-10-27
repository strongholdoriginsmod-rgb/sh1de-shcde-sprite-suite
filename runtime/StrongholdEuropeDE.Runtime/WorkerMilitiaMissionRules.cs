namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Pure decisions from the militia state machine. Keeping these rules free
    /// of game APIs makes the safety-critical edge cases executable with
    /// deterministic inputs.
    /// </summary>
    internal static class WorkerMilitiaMissionRules
    {
        internal static bool UsesLocalPursuitLeash(
            bool manual,
            bool explicitTarget)
        {
            return !(manual && explicitTarget);
        }

        internal static bool MayChainAutomaticTarget(
            bool manual,
            bool explicitTarget)
        {
            return !(manual && explicitTarget);
        }

        internal static bool ShouldResumePausedHold(
            int remainingMilliseconds)
        {
            return remainingMilliseconds > 0;
        }

        internal static bool ShouldAbortStalledManualMove(
            bool manual,
            int retryCount,
            int elapsedMilliseconds,
            int retryFloor,
            int abortMilliseconds)
        {
            return manual
                && retryFloor > 0
                && abortMilliseconds >= 0
                && retryCount >= retryFloor
                && elapsedMilliseconds >= abortMilliseconds;
        }
    }
}
