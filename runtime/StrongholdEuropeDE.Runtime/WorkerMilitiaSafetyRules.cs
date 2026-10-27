using System;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Dependency-free decisions shared by the worker-militia runtime and its
    /// small executable safety harness. Keeping these decisions outside the
    /// game API makes the fail-closed edges executable without loading Unity or
    /// the Script Extender.
    /// </summary>
    internal static class WorkerMilitiaSafetyRules
    {
        internal static bool ShouldRevertImmediately(
            bool insideNativeRunTransaction,
            int currentThreadId,
            int nativeRunThreadId,
            int mainThreadId)
        {
            return insideNativeRunTransaction
                && currentThreadId > 0
                && nativeRunThreadId > 0
                && currentThreadId == nativeRunThreadId
                && (mainThreadId <= 0 || currentThreadId != mainThreadId);
        }

        internal static bool ShouldObserveNativeRun(
            bool mapApplied,
            bool networkSuppressed,
            bool selectionQuarantineSuppressed,
            bool selectionOutstanding,
            bool directWorkPending,
            bool boundarySelectionPending,
            bool commandClassRevertPending,
            bool deferredRollbackRequested)
        {
            return (mapApplied
                    && !networkSuppressed
                    && !selectionQuarantineSuppressed)
                || selectionQuarantineSuppressed
                || selectionOutstanding
                || directWorkPending
                || boundarySelectionPending
                || commandClassRevertPending
                || deferredRollbackRequested;
        }

        internal static bool CanLiftSelectionQuarantine(
            bool selectionDisabled,
            bool commandClassPermanentlyUnavailable,
            bool cleanAuthoritativeOutput,
            bool noOwnedWorkOutstanding,
            int cleanRunCount,
            bool graceElapsed,
            int cleanRunFloor)
        {
            return selectionDisabled
                && !commandClassPermanentlyUnavailable
                && cleanAuthoritativeOutput
                && noOwnedWorkOutstanding
                && cleanRunFloor > 0
                && cleanRunCount >= cleanRunFloor
                && graceElapsed;
        }

        internal static bool ShouldReleasePersistedCommandMode(
            bool exactWorkerIdentity,
            bool liveCommandOwnsWorker,
            bool workProvenanceMatches)
        {
            return exactWorkerIdentity
                && !liveCommandOwnsWorker
                && !workProvenanceMatches;
        }

        internal static bool CanEnterCombat(
            bool workerIsHunter,
            bool hunterRangeCalibrated)
        {
            return !workerIsHunter || hunterRangeCalibrated;
        }

        internal static bool CanApplyAnimationState(
            bool animationCalibrated,
            bool exactCommandIdentity,
            bool liveCommandOwnsWorker)
        {
            return animationCalibrated
                && exactCommandIdentity
                && liveCommandOwnsWorker;
        }
    }

    /// <summary>
    /// Records an executable-memory revert requested away from the engine
    /// thread. The request remains owned until the exact native-run boundary
    /// reports a successful, read-back-verified revert.
    /// </summary>
    internal sealed class WorkerMilitiaNativeRevertQueue
    {
        private bool _pending;
        private string _reason;

        internal bool Pending
        {
            get { return _pending; }
        }

        internal string Reason
        {
            get { return _reason; }
        }

        internal void Request(string reason)
        {
            string safeReason = string.IsNullOrWhiteSpace(reason)
                ? "unspecified native patch release"
                : reason;
            if (!_pending)
            {
                _reason = safeReason;
                _pending = true;
                return;
            }
            if (_reason.IndexOf(safeReason, StringComparison.Ordinal) < 0)
            {
                _reason += "; " + safeReason;
            }
        }

        internal bool TryGetAtNativeBoundary(
            bool insideNativeRunTransaction,
            int currentThreadId,
            int nativeRunThreadId,
            int mainThreadId,
            out string reason)
        {
            reason = _reason;
            return _pending
                && WorkerMilitiaSafetyRules.ShouldRevertImmediately(
                    insideNativeRunTransaction,
                    currentThreadId,
                    nativeRunThreadId,
                    mainThreadId);
        }

        internal void Complete()
        {
            _pending = false;
            _reason = null;
        }
    }
}
