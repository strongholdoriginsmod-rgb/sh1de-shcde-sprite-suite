using System;

namespace StrongholdEuropeDE.Runtime
{
    internal enum VegetationDetourCapabilityStatus
    {
        Unknown,
        Unavailable,
        Available,
    }

    /// <summary>
    /// Immutable, dependency-free observation of the pinned vegetation hook
    /// transaction. Unknown reflection shape is represented separately from a
    /// transaction that is positively known to be unavailable.
    /// </summary>
    internal sealed class VegetationHookSnapshot
    {
        internal VegetationHookSnapshot(
            bool shapeKnown,
            bool? committed,
            int? activeHookCount,
            bool? allHooksActive,
            bool? createExHelpersReady,
            bool directApiAttested,
            string failureReason)
        {
            ShapeKnown = shapeKnown;
            Committed = committed;
            ActiveHookCount = activeHookCount;
            AllHooksActive = allHooksActive;
            CreateExHelpersReady = createExHelpersReady;
            DirectApiAttested = directApiAttested;
            FailureReason = failureReason ?? string.Empty;
        }

        internal bool ShapeKnown { get; private set; }
        internal bool? Committed { get; private set; }
        internal int? ActiveHookCount { get; private set; }
        internal bool? AllHooksActive { get; private set; }
        internal bool? CreateExHelpersReady { get; private set; }
        internal bool DirectApiAttested { get; private set; }
        internal string FailureReason { get; private set; }
    }

    internal sealed class VegetationCapabilityDecision
    {
        internal VegetationCapabilityDecision(
            VegetationDetourCapabilityStatus status,
            string reason,
            int activeHookCount,
            bool? createExHelpersReady,
            bool createExAndImmediateDelete,
            bool growthControl,
            bool vegetationEvents,
            bool directStructAccess,
            bool deleteSafe)
        {
            Status = status;
            Reason = reason;
            ActiveHookCount = activeHookCount;
            CreateExHelpersReady = createExHelpersReady;
            CreateExAndImmediateDelete = createExAndImmediateDelete;
            GrowthControl = growthControl;
            VegetationEvents = vegetationEvents;
            DirectStructAccess = directStructAccess;
            DeleteSafe = deleteSafe;
        }

        internal VegetationDetourCapabilityStatus Status { get; private set; }
        internal string Reason { get; private set; }
        internal int ActiveHookCount { get; private set; }
        internal bool? CreateExHelpersReady { get; private set; }
        internal bool CreateExAndImmediateDelete { get; private set; }
        internal bool GrowthControl { get; private set; }
        internal bool VegetationEvents { get; private set; }
        internal bool DirectStructAccess { get; private set; }
        internal bool DeleteSafe { get; private set; }
    }

    internal static class ScriptExtenderVegetationCapabilityDecision
    {
        internal const int ExpectedActiveHookCount = 8;

        internal static VegetationCapabilityDecision Evaluate(
            VegetationHookSnapshot snapshot)
        {
            if (snapshot == null)
            {
                throw new ArgumentNullException(nameof(snapshot));
            }

            bool direct = snapshot.ShapeKnown
                && snapshot.DirectApiAttested;
            if (!snapshot.ShapeKnown)
            {
                return Result(
                    VegetationDetourCapabilityStatus.Unknown,
                    EmptyTo(snapshot.FailureReason, "reflection_shape_unknown"),
                    snapshot.ActiveHookCount ?? -1,
                    false,
                    direct,
                    snapshot.CreateExHelpersReady);
            }
            if (!snapshot.Committed.HasValue)
            {
                return Result(
                    VegetationDetourCapabilityStatus.Unknown,
                    "commit_state_unknown",
                    snapshot.ActiveHookCount ?? -1,
                    false,
                    direct,
                    snapshot.CreateExHelpersReady);
            }
            if (!snapshot.Committed.Value)
            {
                return Result(
                    VegetationDetourCapabilityStatus.Unavailable,
                    "transaction_uncommitted",
                    snapshot.ActiveHookCount ?? -1,
                    false,
                    direct,
                    snapshot.CreateExHelpersReady);
            }
            if (!snapshot.ActiveHookCount.HasValue)
            {
                return Result(
                    VegetationDetourCapabilityStatus.Unknown,
                    "active_hook_count_unknown",
                    -1,
                    false,
                    direct,
                    snapshot.CreateExHelpersReady);
            }
            if (snapshot.ActiveHookCount.Value != ExpectedActiveHookCount)
            {
                return Result(
                    VegetationDetourCapabilityStatus.Unavailable,
                    "active_hook_count_mismatch",
                    snapshot.ActiveHookCount.Value,
                    false,
                    direct,
                    snapshot.CreateExHelpersReady);
            }
            if (!snapshot.AllHooksActive.HasValue)
            {
                return Result(
                    VegetationDetourCapabilityStatus.Unknown,
                    "hook_activity_unknown",
                    snapshot.ActiveHookCount.Value,
                    false,
                    direct,
                    snapshot.CreateExHelpersReady);
            }
            if (!snapshot.AllHooksActive.Value)
            {
                return Result(
                    VegetationDetourCapabilityStatus.Unavailable,
                    "inactive_hook",
                    snapshot.ActiveHookCount.Value,
                    false,
                    direct,
                    snapshot.CreateExHelpersReady);
            }

            return Result(
                VegetationDetourCapabilityStatus.Available,
                "eight_hooks_active",
                snapshot.ActiveHookCount.Value,
                true,
                direct,
                snapshot.CreateExHelpersReady);
        }

        private static VegetationCapabilityDecision Result(
            VegetationDetourCapabilityStatus status,
            string reason,
            int activeHookCount,
            bool detourBacked,
            bool direct,
            bool? createExHelpersReady)
        {
            return new VegetationCapabilityDecision(
                status,
                reason,
                activeHookCount,
                createExHelpersReady,
                detourBacked && createExHelpersReady == true,
                detourBacked,
                detourBacked,
                direct,
                direct);
        }

        private static string EmptyTo(string value, string fallback)
        {
            return string.IsNullOrWhiteSpace(value) ? fallback : value;
        }
    }
}
