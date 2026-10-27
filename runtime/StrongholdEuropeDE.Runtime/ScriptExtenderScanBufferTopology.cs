namespace StrongholdEuropeDE.Runtime
{
    internal enum ScriptExtenderScanBufferTopologyKind
    {
        Unknown,
        UnpatchedVegetation,
        CommittedVegetation,
    }

    /// <summary>
    /// Dependency-free census decision for the two attested SHCDE-SE 1.44
    /// startup shapes. No count range is accepted: Fixes contributes exactly
    /// zero or two shared LibrarySnapshot views, while either the original
    /// uncommitted vegetation transaction owns one of two scratch buffers, or
    /// all twelve native transactions committed and the sole scratch buffer is
    /// free.
    /// </summary>
    internal sealed class ScriptExtenderScanBufferTopology
    {
        internal ScriptExtenderScanBufferTopology(
            ScriptExtenderScanBufferTopologyKind kind,
            int retainedScratchBuffers,
            bool vegetationCommitted)
        {
            Kind = kind;
            RetainedScratchBuffers = retainedScratchBuffers;
            VegetationCommitted = vegetationCommitted;
        }

        internal ScriptExtenderScanBufferTopologyKind Kind { get; private set; }
        internal int RetainedScratchBuffers { get; private set; }
        internal bool VegetationCommitted { get; private set; }
        internal bool Accepted
        {
            get { return Kind != ScriptExtenderScanBufferTopologyKind.Unknown; }
        }
    }

    internal static class ScriptExtenderScanBufferTopologyDecision
    {
        internal const int ExpectedNativeTransactions = 12;
        internal const int ExpectedFixesSnapshotTransactions = 2;
        internal const int ExpectedUnpatchedCommittedTransactions = 11;
        internal const int ExpectedPatchedCommittedTransactions = 12;

        internal static ScriptExtenderScanBufferTopology Evaluate(
            bool installed,
            int nativeTransactions,
            int snapshotTransactions,
            int fallbackTransactions,
            int scratchBuffers,
            int activeLeases,
            bool pendingLease)
        {
            if (!installed
                || nativeTransactions != ExpectedNativeTransactions
                || !IsAttestedSnapshotTransactions(snapshotTransactions)
                || fallbackTransactions != 0
                || pendingLease)
            {
                return Unknown();
            }
            if (scratchBuffers == 2 && activeLeases == 1)
            {
                return new ScriptExtenderScanBufferTopology(
                    ScriptExtenderScanBufferTopologyKind.UnpatchedVegetation,
                    1,
                    false);
            }
            if (scratchBuffers == 1 && activeLeases == 0)
            {
                return new ScriptExtenderScanBufferTopology(
                    ScriptExtenderScanBufferTopologyKind.CommittedVegetation,
                    0,
                    true);
            }
            return Unknown();
        }

        internal static bool IsAttestedSnapshotTransactions(
            int snapshotTransactions)
        {
            return snapshotTransactions == 0
                || snapshotTransactions == ExpectedFixesSnapshotTransactions;
        }

        internal static bool IsAttestedReleaseTopology(
            int committedTransactions,
            bool vegetationCommitted)
        {
            return vegetationCommitted
                ? committedTransactions == ExpectedPatchedCommittedTransactions
                : committedTransactions == ExpectedUnpatchedCommittedTransactions;
        }

        private static ScriptExtenderScanBufferTopology Unknown()
        {
            return new ScriptExtenderScanBufferTopology(
                ScriptExtenderScanBufferTopologyKind.Unknown,
                0,
                false);
        }
    }
}
