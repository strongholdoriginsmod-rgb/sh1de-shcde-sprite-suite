namespace StrongholdEuropeDE.Runtime.Audio
{
    /// <summary>
    /// Dependency-free decision core for procedural clip ownership. Unity's
    /// AudioClip.loadState is deliberately absent: AudioClip.Create instances
    /// do not become Unloaded when MyAudioManager calls UnloadAudioData().
    /// </summary>
    internal static class PcmLeaseLifetimeDecision
    {
        internal static bool ShouldRelease(
            bool prepared,
            bool readerFaulted,
            bool clipAlive,
            bool ownershipSnapshotAvailable,
            bool ownedByMusicManager,
            long pumpGeneration,
            long attachDeadlinePump)
        {
            if (prepared)
            {
                return false;
            }
            if (!clipAlive)
            {
                return true;
            }
            if (!ownershipSnapshotAvailable || ownedByMusicManager)
            {
                return false;
            }
            if (readerFaulted)
            {
                return true;
            }
            return pumpGeneration >= attachDeadlinePump;
        }
    }

    /// <summary>
    /// A normal one-shot route gets only a short frame grace. A fade route may
    /// survive that grace while the exact MyAudioManager surface confirms the
    /// same pending request. The absolute wall-clock deadline prevents a stale
    /// or never-consumed fade request from retaining a stream indefinitely.
    /// </summary>
    internal static class PcmPreparedRouteLifetimeDecision
    {
        internal static bool ShouldExpire(
            long pumpGeneration,
            long shortDeadlinePump,
            bool deferredFadeAllowed,
            bool ownershipSnapshotAvailable,
            bool sameFadeRequestPending,
            long monotonicNow,
            long absoluteDeadlineTimestamp)
        {
            if (pumpGeneration < shortDeadlinePump)
            {
                return false;
            }
            if (!deferredFadeAllowed)
            {
                return true;
            }
            if (ownershipSnapshotAvailable)
            {
                // Script update order is unspecified. A route still named by
                // the exact manager must survive even after a pause exceeds
                // the wall-clock cap; the next manager Update consumes it.
                return !sameFadeRequestPending;
            }
            // With no exact snapshot, retain only up to the hard deadline.
            return monotonicNow >= absoluteDeadlineTimestamp;
        }
    }

    internal struct PcmMusicDetachPlan
    {
        internal bool CurrentPathOwned { get; private set; }
        internal bool RemoveOwnedNext { get; private set; }
        internal bool PromoteUnownedNext { get; private set; }
        internal bool StopCurrentPath { get; private set; }
        internal bool ResetLoopCue { get; private set; }
        internal bool CancelPendingFade { get; private set; }
        internal bool RestoreCurrentVolume { get; private set; }
        internal bool RestartOriginalRoute { get; private set; }

        internal static PcmMusicDetachPlan Create(
            bool currentOwned,
            bool sourceOwned,
            bool nextOwned,
            bool nextExists,
            bool pendingFadeOwned)
        {
            bool currentPathOwned = currentOwned || sourceOwned;
            return new PcmMusicDetachPlan
            {
                CurrentPathOwned = currentPathOwned,
                RemoveOwnedNext = nextOwned,
                PromoteUnownedNext = currentPathOwned
                    && nextExists
                    && !nextOwned,
                StopCurrentPath = currentPathOwned
                    && (!nextExists || nextOwned),
                ResetLoopCue = currentPathOwned
                    && nextExists
                    && !nextOwned,
                CancelPendingFade = pendingFadeOwned || currentPathOwned,
                RestoreCurrentVolume = pendingFadeOwned && !currentPathOwned,
                RestartOriginalRoute = currentPathOwned
                    && (!nextExists || nextOwned),
            };
        }
    }
}
