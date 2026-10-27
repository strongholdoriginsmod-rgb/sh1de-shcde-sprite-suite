namespace StrongholdEuropeDE.Runtime
{
    internal enum ScriptExtenderScanBufferMemoryShape
    {
        Empty,
        ArrayCopy,
        LibrarySnapshotView,
        UnmanagedLease,
    }

    internal enum ScriptExtenderScanBufferReleaseAction
    {
        Reject,
        AlreadyCleared,
        RetainActiveLease,
        ReleaseArrayCopy,
        ClearLibrarySnapshotView,
        RetainUncommittedActiveLease,
        RetainUncommitted,
    }

    internal static class ScriptExtenderScanBufferReleaseDecision
    {
        internal static ScriptExtenderScanBufferReleaseAction Evaluate(
            bool committed,
            bool vegetationOwner,
            bool allowLibrarySnapshotView,
            ScriptExtenderScanBufferTrackedMemoryState trackedState,
            ScriptExtenderScanBufferMemoryShape memoryShape)
        {
            if (allowLibrarySnapshotView
                && trackedState
                    != ScriptExtenderScanBufferTrackedMemoryState.Untracked)
            {
                return ScriptExtenderScanBufferReleaseAction.Reject;
            }
            if (committed)
            {
                if (trackedState
                    == ScriptExtenderScanBufferTrackedMemoryState.Cleared)
                {
                    return memoryShape == ScriptExtenderScanBufferMemoryShape.Empty
                        ? ScriptExtenderScanBufferReleaseAction.AlreadyCleared
                        : ScriptExtenderScanBufferReleaseAction.Reject;
                }
                if (trackedState
                    == ScriptExtenderScanBufferTrackedMemoryState.Active)
                {
                    return (memoryShape
                                == ScriptExtenderScanBufferMemoryShape.UnmanagedLease
                            || memoryShape
                                == ScriptExtenderScanBufferMemoryShape.Empty)
                            ? ScriptExtenderScanBufferReleaseAction
                                .RetainActiveLease
                            : ScriptExtenderScanBufferReleaseAction.Reject;
                }
                if (trackedState
                    != ScriptExtenderScanBufferTrackedMemoryState.Untracked)
                {
                    return ScriptExtenderScanBufferReleaseAction.Reject;
                }
                if (memoryShape
                    == ScriptExtenderScanBufferMemoryShape.ArrayCopy)
                {
                    return ScriptExtenderScanBufferReleaseAction.ReleaseArrayCopy;
                }
                if (allowLibrarySnapshotView
                    && memoryShape
                        == ScriptExtenderScanBufferMemoryShape.LibrarySnapshotView)
                {
                    return ScriptExtenderScanBufferReleaseAction
                        .ClearLibrarySnapshotView;
                }
                return ScriptExtenderScanBufferReleaseAction.Reject;
            }

            if (!vegetationOwner)
            {
                return ScriptExtenderScanBufferReleaseAction.Reject;
            }
            if (trackedState
                    == ScriptExtenderScanBufferTrackedMemoryState.Active
                && memoryShape
                    == ScriptExtenderScanBufferMemoryShape.UnmanagedLease)
            {
                return ScriptExtenderScanBufferReleaseAction
                    .RetainUncommittedActiveLease;
            }
            if (trackedState
                    == ScriptExtenderScanBufferTrackedMemoryState.Untracked
                && memoryShape
                    == ScriptExtenderScanBufferMemoryShape.ArrayCopy)
            {
                return ScriptExtenderScanBufferReleaseAction.RetainUncommitted;
            }
            return ScriptExtenderScanBufferReleaseAction.Reject;
        }
    }

    /// <summary>
    /// Dependency-free counter operation shared by the runtime collector and
    /// the mixed-topology harness. The committed counter remains suitable for
    /// the committed-only release census; the uncommitted lease is separate.
    /// </summary>
    internal static class ScriptExtenderScanBufferRetentionCensus
    {
        internal static void Record(
            ScriptExtenderScanBufferReleaseAction action,
            ref int committedActiveLeaseRetainedTransactions,
            ref int uncommittedActiveLeaseRetainedTransactions)
        {
            if (action
                == ScriptExtenderScanBufferReleaseAction.RetainActiveLease)
            {
                committedActiveLeaseRetainedTransactions = checked(
                    committedActiveLeaseRetainedTransactions + 1);
            }
            else if (action == ScriptExtenderScanBufferReleaseAction
                    .RetainUncommittedActiveLease)
            {
                uncommittedActiveLeaseRetainedTransactions = checked(
                    uncommittedActiveLeaseRetainedTransactions + 1);
            }
        }
    }
}
