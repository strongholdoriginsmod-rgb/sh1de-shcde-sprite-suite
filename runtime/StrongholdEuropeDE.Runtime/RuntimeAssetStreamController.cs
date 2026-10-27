using System;
using System.Collections.Generic;
using System.Globalization;

namespace StrongholdEuropeDE.Runtime
{
    internal enum AssetStreamGroupState
    {
        Unloaded = 0,
        Verifying = 1,
        Loading = 2,
        Loaded = 3,
        ReleasePending = 4,
        Failed = 5,
        BudgetDenied = 6,
    }

    internal enum AssetStreamEnsureDisposition
    {
        Loaded = 0,
        AlreadyLoaded = 1,
        QueuedFallback = 2,
        BaselineFallback = 3,
        LoadingFallback = 4,
        ReleasePendingFallback = 5,
        BudgetFallback = 6,
        FailureFallback = 7,
        UnknownGroupFallback = 8,
        ShutdownFallback = 9,
        NoMapFallback = 10,
    }

    internal struct AssetStreamEnsureResult
    {
        internal AssetStreamEnsureResult(
            AssetStreamEnsureDisposition disposition,
            AssetStreamGroupState state,
            string groupId,
            long epoch,
            string detail)
        {
            Disposition = disposition;
            State = state;
            GroupId = groupId ?? string.Empty;
            Epoch = epoch;
            Detail = AssetStreamText.Sanitize(detail, 256);
        }

        internal AssetStreamEnsureDisposition Disposition { get; private set; }

        internal AssetStreamGroupState State { get; private set; }

        internal string GroupId { get; private set; }

        internal long Epoch { get; private set; }

        internal string Detail { get; private set; }

        internal bool IsLoaded
        {
            get
            {
                return Disposition == AssetStreamEnsureDisposition.Loaded
                    || Disposition == AssetStreamEnsureDisposition.AlreadyLoaded;
            }
        }
    }

    internal sealed class AssetStreamGroupSnapshot
    {
        internal AssetStreamGroupSnapshot(
            string groupId,
            int? gmId,
            AssetStreamGroupState state,
            long stateEpoch,
            bool baselineRegistered,
            bool queued,
            bool permanentTerminal,
            bool referencesDetached,
            bool releaseBlocked,
            long releaseDueFrame,
            string detail)
        {
            GroupId = groupId;
            GmId = gmId;
            State = state;
            StateEpoch = stateEpoch;
            BaselineRegistered = baselineRegistered;
            Queued = queued;
            PermanentTerminal = permanentTerminal;
            ReferencesDetached = referencesDetached;
            ReleaseBlocked = releaseBlocked;
            ReleaseDueFrame = releaseDueFrame;
            Detail = AssetStreamText.Sanitize(detail, 256);
        }

        internal string GroupId { get; private set; }

        internal int? GmId { get; private set; }

        internal AssetStreamGroupState State { get; private set; }

        internal long StateEpoch { get; private set; }

        internal bool BaselineRegistered { get; private set; }

        internal bool Queued { get; private set; }

        internal bool PermanentTerminal { get; private set; }

        internal bool ReferencesDetached { get; private set; }

        internal bool ReleaseBlocked { get; private set; }

        internal long ReleaseDueFrame { get; private set; }

        internal string Detail { get; private set; }
    }

    /// <summary>
    /// Epoch-based, no-eviction runtime asset controller. All Unity-facing work
    /// stays behind the backend and is entered only through the captured main
    /// thread. Lookup misses never wait: they queue once and use the baseline.
    /// </summary>
    internal sealed class RuntimeAssetStreamController<TBaseline, TCommitted>
        where TBaseline : class
        where TCommitted : class
    {
        private const int MaximumRestoreAttempts = 8;
        private const int MaximumReleaseAttempts = 8;
        private const int MaximumRetryDelayFrames = 60;

        private readonly object _gate = new object();
        private readonly Dictionary<string, GroupEntry> _groups =
            new Dictionary<string, GroupEntry>(StringComparer.Ordinal);
        private readonly Dictionary<int, string> _gmGroups =
            new Dictionary<int, string>();
        private readonly Queue<string> _queue = new Queue<string>();
        private readonly IAssetStreamGroupBackend<TBaseline, TCommitted> _backend;
        private readonly IAssetStreamThreadGate _threadGate;
        private readonly AssetStreamBudgetLedger _budget;
        private readonly AssetStreamControllerOptions _options;
        private readonly IAssetStreamEventSink _events;
        private long _epoch = 1;
        private long _generation;
        private long _baselineGeneration;
        private long _lateFrame;
        private bool _mapActive;
        private bool _shuttingDown;
        private bool _mainTransitioning;

        internal RuntimeAssetStreamController(
            AssetStreamManifest manifest,
            IAssetStreamGroupBackend<TBaseline, TCommitted> backend,
            IAssetStreamThreadGate threadGate,
            AssetStreamBudgetLedger budget,
            AssetStreamControllerOptions options,
            IAssetStreamEventSink events)
        {
            if (manifest == null)
            {
                throw new ArgumentNullException("manifest");
            }
            _backend = backend ?? throw new ArgumentNullException("backend");
            _threadGate = threadGate ?? throw new ArgumentNullException("threadGate");
            _budget = budget ?? throw new ArgumentNullException("budget");
            _options = options ?? throw new ArgumentNullException("options");
            _events = events ?? NullAssetStreamEventSink.Instance;
            foreach (AssetStreamGroupManifest group in manifest.Groups)
            {
                _groups.Add(group.Group, new GroupEntry(group));
                _gmGroups.Add(group.GmId, group.Group);
            }
        }

        internal long CurrentEpoch
        {
            get
            {
                lock (_gate)
                {
                    return _epoch;
                }
            }
        }

        internal long CurrentLateFrame
        {
            get
            {
                lock (_gate)
                {
                    return _lateFrame;
                }
            }
        }

        internal void RegisterBaseline(string groupId, TBaseline value)
        {
            RequireMainThread();
            GroupEntry entry;
            long captureGeneration;
            lock (_gate)
            {
                RequireNoMainTransition();
                entry = RequireGroup(groupId);
                if (entry.Baseline != null)
                {
                    throw new InvalidOperationException(
                        "Baseline is already registered for " + entry.Manifest.Group);
                }
                if (entry.State != AssetStreamGroupState.Unloaded
                    || entry.Owned != null
                    || entry.Budget != null)
                {
                    throw new InvalidOperationException(
                        "Baseline can only be registered before the first load");
                }
                captureGeneration = checked(++_baselineGeneration);
                entry.Baseline = new AssetStreamBaseline<TBaseline>(
                    entry.Manifest.Group,
                    captureGeneration,
                    value);
            }
            Emit(
                AssetStreamEventKind.BaselineRegistered,
                entry.Manifest.Group,
                "capture_generation=" + captureGeneration);
        }

        internal long BeginMapEpoch()
        {
            RequireMainThread();
            lock (_gate)
            {
                RequireNoMainTransition();
                if (_shuttingDown)
                {
                    throw new InvalidOperationException("Asset stream is shutting down");
                }
                if (_mapActive)
                {
                    throw new InvalidOperationException("A map epoch is already active");
                }
                _epoch = checked(_epoch + 1);
                _mapActive = true;
                ClearQueueLocked();
                foreach (GroupEntry entry in _groups.Values)
                {
                    ResetExpiredTerminalLocked(entry);
                }
                return _epoch;
            }
        }

        internal void EndMapEpoch(long epoch)
        {
            RequireMainThread();
            List<GroupEntry> releases = new List<GroupEntry>();
            lock (_gate)
            {
                RequireNoMainTransition();
                if (!_mapActive || epoch != _epoch)
                {
                    return;
                }
                _mapActive = false;
                foreach (GroupEntry entry in _groups.Values)
                {
                    if (entry.State == AssetStreamGroupState.Loaded
                        && entry.Owned != null)
                    {
                        PrepareReleaseLocked(entry);
                        releases.Add(entry);
                    }
                }
                _mainTransitioning = releases.Count != 0;
            }

            try
            {
                for (int index = 0; index < releases.Count; index++)
                {
                    TryRestore(releases[index]);
                }
            }
            finally
            {
                lock (_gate)
                {
                    _mainTransitioning = false;
                }
            }
        }

        internal void BeginShutdown()
        {
            RequireMainThread();
            List<GroupEntry> releases = new List<GroupEntry>();
            lock (_gate)
            {
                RequireNoMainTransition();
                if (_shuttingDown)
                {
                    return;
                }
                _shuttingDown = true;
                _mapActive = false;
                ClearQueueLocked();
                foreach (GroupEntry entry in _groups.Values)
                {
                    if (entry.State == AssetStreamGroupState.Loaded
                        && entry.Owned != null)
                    {
                        PrepareReleaseLocked(entry);
                        releases.Add(entry);
                    }
                }
                _mainTransitioning = releases.Count != 0;
            }

            try
            {
                for (int index = 0; index < releases.Count; index++)
                {
                    TryRestore(releases[index]);
                }
            }
            finally
            {
                lock (_gate)
                {
                    _mainTransitioning = false;
                }
            }
        }

        internal AssetStreamEnsureResult EnsureGm(int gmId)
        {
            string groupId;
            lock (_gate)
            {
                if (!_gmGroups.TryGetValue(gmId, out groupId))
                {
                    return Result(
                        AssetStreamEnsureDisposition.UnknownGroupFallback,
                        AssetStreamGroupState.Unloaded,
                        "gm:" + gmId,
                        "GM id is not declared by the asset-stream manifest");
                }
            }
            return EnsureGroup(groupId);
        }

        internal AssetStreamEnsureResult EnsureGroup(string groupId)
        {
            GroupEntry entry;
            AssetStreamOwnershipToken ownership;
            lock (_gate)
            {
                if (!_groups.TryGetValue(groupId ?? string.Empty, out entry))
                {
                    return Result(
                        AssetStreamEnsureDisposition.UnknownGroupFallback,
                        AssetStreamGroupState.Unloaded,
                        groupId,
                        "Group is not declared by the asset-stream manifest");
                }
                ResetExpiredTerminalLocked(entry);

                if (_shuttingDown)
                {
                    return Result(
                        AssetStreamEnsureDisposition.ShutdownFallback,
                        entry.State,
                        entry.Manifest.Group,
                        "Asset stream is shutting down");
                }
                if (entry.State == AssetStreamGroupState.Loaded)
                {
                    return Result(
                        AssetStreamEnsureDisposition.AlreadyLoaded,
                        entry.State,
                        entry.Manifest.Group,
                        "Group is already loaded");
                }
                if (entry.State == AssetStreamGroupState.BudgetDenied)
                {
                    return Result(
                        AssetStreamEnsureDisposition.BudgetFallback,
                        entry.State,
                        entry.Manifest.Group,
                        entry.Detail);
                }
                if (entry.State == AssetStreamGroupState.Failed)
                {
                    return Result(
                        AssetStreamEnsureDisposition.FailureFallback,
                        entry.State,
                        entry.Manifest.Group,
                        entry.Detail);
                }
                if (entry.State == AssetStreamGroupState.Verifying
                    || entry.State == AssetStreamGroupState.Loading)
                {
                    return Result(
                        AssetStreamEnsureDisposition.LoadingFallback,
                        entry.State,
                        entry.Manifest.Group,
                        "A transactional load is already in progress");
                }
                if (entry.State == AssetStreamGroupState.ReleasePending)
                {
                    if (CanQueueLocked(entry))
                    {
                        QueueLocked(entry);
                    }
                    return Result(
                        AssetStreamEnsureDisposition.ReleasePendingFallback,
                        entry.State,
                        entry.Manifest.Group,
                        entry.ReleaseBlocked
                            ? "Previous assets are retained because release safety is unproved"
                            : "Previous assets are awaiting delayed release");
                }
                if (!_mapActive)
                {
                    return Result(
                        AssetStreamEnsureDisposition.NoMapFallback,
                        entry.State,
                        entry.Manifest.Group,
                        "No map epoch is active");
                }
                if (entry.Baseline == null)
                {
                    return Result(
                        AssetStreamEnsureDisposition.BaselineFallback,
                        entry.State,
                        entry.Manifest.Group,
                        "Baseline has not been registered");
                }
                if (!_threadGate.IsMainThread || _mainTransitioning)
                {
                    QueueLocked(entry);
                    return Result(
                        AssetStreamEnsureDisposition.QueuedFallback,
                        entry.State,
                        entry.Manifest.Group,
                        _threadGate.IsMainThread
                            ? "Main-thread asset transition is busy"
                            : "Unity load was queued for the main thread");
                }

                _generation = checked(_generation + 1);
                ownership = new AssetStreamOwnershipToken(
                    entry.Manifest.Group,
                    _epoch,
                    _generation);
                entry.State = AssetStreamGroupState.Verifying;
                entry.StateEpoch = _epoch;
                entry.Detail = null;
                entry.Queued = false;
                _mainTransitioning = true;
            }

            try
            {
                return Load(entry, ownership);
            }
            finally
            {
                lock (_gate)
                {
                    _mainTransitioning = false;
                }
            }
        }

        /// <summary>Loads at most one deduplicated off-thread request.</summary>
        internal AssetStreamEnsureResult PumpOneQueued()
        {
            RequireMainThread();
            string groupId = null;
            lock (_gate)
            {
                RequireNoMainTransition();
                while (_queue.Count != 0)
                {
                    string candidate = _queue.Dequeue();
                    GroupEntry entry;
                    if (!_groups.TryGetValue(candidate, out entry)
                        || !entry.Queued
                        || entry.QueuedEpoch != _epoch)
                    {
                        continue;
                    }
                    entry.Queued = false;
                    groupId = candidate;
                    break;
                }
            }
            if (groupId == null)
            {
                return Result(
                    AssetStreamEnsureDisposition.BaselineFallback,
                    AssetStreamGroupState.Unloaded,
                    string.Empty,
                    "No queued group");
            }
            return EnsureGroup(groupId);
        }

        /// <summary>
        /// Advances the release clock after LateUpdate, retries only explicitly
        /// retryable baseline restores, and releases only after two or more full
        /// frames with no central owned references.
        /// </summary>
        internal int AdvanceLateFrame()
        {
            RequireMainThread();
            List<GroupEntry> restores = new List<GroupEntry>();
            List<GroupEntry> releases = new List<GroupEntry>();
            lock (_gate)
            {
                RequireNoMainTransition();
                _lateFrame = checked(_lateFrame + 1);
                foreach (GroupEntry entry in _groups.Values)
                {
                    if (entry.State != AssetStreamGroupState.ReleasePending
                        || entry.Owned == null
                        || entry.ReleaseBlocked)
                    {
                        continue;
                    }
                    if (!entry.ReferencesDetached)
                    {
                        if (_lateFrame >= entry.NextRestoreFrame)
                        {
                            restores.Add(entry);
                        }
                    }
                    else if (_lateFrame >= entry.ReleaseDueFrame
                        && _lateFrame >= entry.NextReleaseFrame)
                    {
                        releases.Add(entry);
                    }
                }
                _mainTransitioning = restores.Count != 0 || releases.Count != 0;
            }

            int released = 0;
            try
            {
                for (int index = 0; index < restores.Count; index++)
                {
                    TryRestore(restores[index]);
                }

                // A restore performed above starts a fresh full delay; it is
                // therefore intentionally absent from this release list.
                for (int index = 0; index < releases.Count; index++)
                {
                    if (TryRelease(releases[index]))
                    {
                        released++;
                    }
                }
            }
            finally
            {
                lock (_gate)
                {
                    _mainTransitioning = false;
                }
            }
            return released;
        }

        internal AssetStreamGroupSnapshot Snapshot(string groupId)
        {
            lock (_gate)
            {
                GroupEntry entry = RequireGroup(groupId);
                return new AssetStreamGroupSnapshot(
                    entry.Manifest.Group,
                    entry.Manifest.GmId,
                    entry.State,
                    entry.StateEpoch,
                    entry.Baseline != null,
                    entry.Queued,
                    entry.PermanentTerminal,
                    entry.ReferencesDetached,
                    entry.ReleaseBlocked,
                    entry.ReleaseDueFrame,
                    entry.Detail);
            }
        }

        internal bool ShutdownDrainComplete
        {
            get
            {
                lock (_gate)
                {
                    if (!_shuttingDown)
                    {
                        return false;
                    }
                    foreach (GroupEntry entry in _groups.Values)
                    {
                        if (entry.Owned != null || entry.Budget != null)
                        {
                            return false;
                        }
                    }
                    return true;
                }
            }
        }

        internal bool ShutdownDrainTerminalRetention
        {
            get
            {
                lock (_gate)
                {
                    if (!_shuttingDown)
                    {
                        return false;
                    }
                    bool retained = false;
                    foreach (GroupEntry entry in _groups.Values)
                    {
                        if (entry.Owned == null && entry.Budget == null)
                        {
                            continue;
                        }
                        retained = true;
                        if (!entry.ReleaseBlocked)
                        {
                            return false;
                        }
                    }
                    return retained;
                }
            }
        }

        private AssetStreamEnsureResult Load(
            GroupEntry entry,
            AssetStreamOwnershipToken ownership)
        {
            AssetStreamBudgetReservation reservation;
            AssetStreamAdmissionDecision admission;
            if (!_budget.TryReserve(entry.Manifest, out reservation, out admission))
            {
                lock (_gate)
                {
                    SetBudgetDeniedLocked(entry, admission.Detail);
                }
                Emit(
                    AssetStreamEventKind.BudgetDenied,
                    entry.Manifest.Group,
                    admission.ReasonToken + ": " + admission.Detail);
                return Result(
                    AssetStreamEnsureDisposition.BudgetFallback,
                    AssetStreamGroupState.BudgetDenied,
                    entry.Manifest.Group,
                    admission.Detail);
            }

            IAssetStreamGroupTransaction<TCommitted> transaction = null;
            AssetStreamCleanupCompletion cleanupCompletion = null;
            bool budgetCommitted = false;
            bool committed = false;
            try
            {
                EmitLoadTelemetry(
                    AssetStreamEventKind.LoadStarted,
                    entry.Manifest,
                    "pre-stage",
                    reservation.PreStageTelemetry,
                    reservation.PreStageTelemetry);
                Emit(
                    AssetStreamEventKind.LoadStarted,
                    entry.Manifest.Group,
                    "verifying bundle");
                _backend.Verify(entry.Manifest);
                lock (_gate)
                {
                    RequireLoadTokenLocked(entry, ownership);
                    entry.State = AssetStreamGroupState.Loading;
                }

                cleanupCompletion = new AssetStreamCleanupCompletion();
                transaction = _backend.BeginTransaction(
                    entry.Manifest,
                    entry.Baseline,
                    ownership,
                    cleanupCompletion);
                if (transaction == null)
                {
                    throw new AssetStreamLoadException(
                        "Backend returned no transaction",
                        true);
                }

                // BeginTransaction has completed all bundle/TextAsset/Texture2D/
                // Sprite.Create staging but has not published central arrays.
                // A fresh Windows + external-usage probe is mandatory here.
                bool secondAdmission = reservation.TryConfirmBeforeCommit(out admission);
                EmitLoadTelemetry(
                    secondAdmission
                        ? AssetStreamEventKind.LoadStarted
                        : AssetStreamEventKind.SecondAdmissionDenied,
                    entry.Manifest,
                    "after-stage",
                    reservation.PreStageTelemetry,
                    reservation.AfterStageTelemetry);
                if (!secondAdmission)
                {
                    string cleanup = AbortTransaction(transaction);
                    bool cleanupPending = cleanupCompletion != null
                        && cleanupCompletion.IsPending;
                    if (cleanup == null)
                    {
                        lock (_gate)
                        {
                            SetBudgetDeniedLocked(entry, admission.Detail);
                            if (cleanupPending)
                            {
                                entry.Budget = reservation;
                            }
                        }
                        if (cleanupPending)
                        {
                            TrackBudgetUntilCleanup(
                                entry,
                                reservation,
                                cleanupCompletion,
                                false);
                        }
                        else
                        {
                            reservation.Cancel();
                            EmitLoadTelemetry(
                                AssetStreamEventKind.SecondAdmissionDenied,
                                entry.Manifest,
                                "after-cleanup",
                                reservation.PreStageTelemetry,
                                CaptureTransitionTelemetry(entry.Manifest));
                        }
                        Emit(
                            AssetStreamEventKind.SecondAdmissionDenied,
                            entry.Manifest.Group,
                            admission.ReasonToken + ": " + admission.Detail);
                        return Result(
                            AssetStreamEnsureDisposition.BudgetFallback,
                            AssetStreamGroupState.BudgetDenied,
                            entry.Manifest.Group,
                            admission.Detail);
                    }

                    if (cleanupPending)
                    {
                        string pendingDetail = admission.Detail
                            + "; staged cleanup is tracked asynchronously: "
                            + cleanup;
                        lock (_gate)
                        {
                            entry.State = AssetStreamGroupState.Failed;
                            entry.StateEpoch = _epoch;
                            entry.TerminalEpoch = _epoch;
                            entry.PermanentTerminal = true;
                            entry.Detail = pendingDetail;
                            entry.Budget = reservation;
                        }
                        TrackBudgetUntilCleanup(
                            entry,
                            reservation,
                            cleanupCompletion,
                            false);
                        Emit(
                            AssetStreamEventKind.LoadFailed,
                            entry.Manifest.Group,
                            "permanent: " + pendingDetail);
                        return Result(
                            AssetStreamEnsureDisposition.FailureFallback,
                            AssetStreamGroupState.Failed,
                            entry.Manifest.Group,
                            pendingDetail);
                    }

                    // Cleanup could not be tracked. Retain the full charge
                    // permanently so a retry cannot compound unknown native
                    // allocation.
                    reservation.RetainAsLeak();
                    budgetCommitted = true;
                    string detail = admission.Detail
                        + "; staged cleanup failed: " + cleanup;
                    lock (_gate)
                    {
                        entry.State = AssetStreamGroupState.Failed;
                        entry.StateEpoch = _epoch;
                        entry.TerminalEpoch = _epoch;
                        entry.PermanentTerminal = true;
                        entry.Detail = detail;
                        entry.Budget = reservation;
                        entry.ReleaseBlocked = true;
                    }
                    Emit(
                        AssetStreamEventKind.LoadFailed,
                        entry.Manifest.Group,
                        "permanent: " + detail);
                    return Result(
                        AssetStreamEnsureDisposition.FailureFallback,
                        AssetStreamGroupState.Failed,
                        entry.Manifest.Group,
                        detail);
                }

                // Accounting becomes committed immediately before the only
                // operation that may publish the staged group.
                reservation.Commit();
                budgetCommitted = true;
                TCommitted value = transaction.Commit();
                if (value == null)
                {
                    throw new AssetStreamLoadException(
                        "Backend committed a null group",
                        true);
                }
                committed = true;

                lock (_gate)
                {
                    RequireLoadTokenLocked(entry, ownership);
                    entry.Owned = new AssetStreamOwnedGroup<TCommitted>(ownership, value);
                    entry.Budget = reservation;
                    entry.State = AssetStreamGroupState.Loaded;
                    entry.StateEpoch = ownership.Epoch;
                    entry.TerminalEpoch = 0;
                    entry.PermanentTerminal = false;
                    entry.Detail = null;
                }
                EmitLoadTelemetry(
                    AssetStreamEventKind.LoadCommitted,
                    entry.Manifest,
                    "after-commit",
                    reservation.PreStageTelemetry,
                    CaptureTransitionTelemetry(entry.Manifest));
                Emit(
                    AssetStreamEventKind.LoadCommitted,
                    entry.Manifest.Group,
                    "transaction committed");
                return Result(
                    AssetStreamEnsureDisposition.Loaded,
                    AssetStreamGroupState.Loaded,
                    entry.Manifest.Group,
                    "Group loaded transactionally");
            }
            catch (Exception exception)
            {
                string cleanup = AbortTransaction(transaction);
                AssetStreamLoadException loadFailure =
                    exception as AssetStreamLoadException;
                bool cleanupPending = cleanupCompletion != null
                    && cleanupCompletion.IsPending;
                bool cleanupSafe = cleanup == null
                    && !cleanupPending
                    && (loadFailure == null
                        || !loadFailure.CleanupUnconfirmed);
                string accountingFailure = null;
                if (cleanupPending)
                {
                    // Reservation ownership moves to the one-shot completion
                    // callback after the failed group state is published below.
                }
                else if (!cleanupSafe)
                {
                    if (!budgetCommitted)
                    {
                        try
                        {
                            reservation.RetainAsLeak();
                            budgetCommitted = true;
                        }
                        catch (Exception budgetException)
                        {
                            // Keep the reservation object and do not cancel it.
                            // Its ledger entry remains conservative whether the
                            // failed transition stopped before or after commit.
                            accountingFailure = Describe(budgetException);
                        }
                    }
                }
                else if (budgetCommitted)
                {
                    reservation.Release();
                    EmitLoadTelemetry(
                        AssetStreamEventKind.LoadFailed,
                        entry.Manifest,
                        "after-cleanup",
                        reservation.PreStageTelemetry,
                        CaptureTransitionTelemetry(entry.Manifest));
                }
                else
                {
                    reservation.Cancel();
                    EmitLoadTelemetry(
                        AssetStreamEventKind.LoadFailed,
                        entry.Manifest,
                        "after-cleanup",
                        reservation.PreStageTelemetry,
                        CaptureTransitionTelemetry(entry.Manifest));
                }

                bool permanent = IsPermanent(exception)
                    || (!cleanupSafe && !cleanupPending)
                    || cleanup != null;
                string detail = Describe(exception);
                if (cleanup != null)
                {
                    detail += "; transaction cleanup failed: " + cleanup;
                }
                if (accountingFailure != null)
                {
                    detail += "; budget accounting held conservatively: "
                        + accountingFailure;
                }
                lock (_gate)
                {
                    entry.State = AssetStreamGroupState.Failed;
                    entry.StateEpoch = _epoch;
                    entry.TerminalEpoch = _epoch;
                    entry.PermanentTerminal = permanent;
                    entry.Detail = detail;
                    if (cleanupPending)
                    {
                        entry.Budget = reservation;
                    }
                    else if (!cleanupSafe)
                    {
                        // Keep a conservative ledger claim for a potentially
                        // published allocation that could not be proved detached.
                        entry.Budget = reservation;
                        entry.ReleaseBlocked = true;
                    }
                }
                if (cleanupPending)
                {
                    TrackBudgetUntilCleanup(
                        entry,
                        reservation,
                        cleanupCompletion,
                        budgetCommitted);
                }
                Emit(
                    AssetStreamEventKind.LoadFailed,
                    entry.Manifest.Group,
                    (permanent ? "permanent: " : "epoch: ") + detail);
                return Result(
                    AssetStreamEnsureDisposition.FailureFallback,
                    AssetStreamGroupState.Failed,
                    entry.Manifest.Group,
                    detail);
            }
            finally
            {
                if (transaction != null)
                {
                    try
                    {
                        transaction.Dispose();
                    }
                    catch (Exception exception)
                    {
                        // A committed transaction owns live objects. Dispose is
                        // not allowed to undo it, and a late exception must not
                        // trigger a second commit or a use-after-destroy path.
                        if (!committed)
                        {
                            Emit(
                                AssetStreamEventKind.LoadFailed,
                                entry.Manifest.Group,
                                "transaction dispose failed: " + Describe(exception));
                        }
                    }
                }
            }
        }

        private void TryRestore(GroupEntry entry)
        {
            AssetStreamOwnedGroup<TCommitted> owned;
            AssetStreamBaseline<TBaseline> baseline;
            lock (_gate)
            {
                if (entry.State != AssetStreamGroupState.ReleasePending
                    || entry.Owned == null
                    || entry.ReleaseBlocked
                    || entry.ReferencesDetached)
                {
                    return;
                }
                owned = entry.Owned;
                baseline = entry.Baseline;
            }

            Emit(
                AssetStreamEventKind.RestoreStarted,
                entry.Manifest.Group,
                "restoring baseline references");
            AssetStreamRestoreResult result;
            try
            {
                result = _backend.RestoreBaseline(entry.Manifest, baseline, owned);
            }
            catch (Exception exception)
            {
                result = new AssetStreamRestoreResult(
                    AssetStreamRestoreDisposition.RetryRequired,
                    false,
                    "restore threw: " + Describe(exception));
            }

            bool blocked = false;
            lock (_gate)
            {
                if (entry.State != AssetStreamGroupState.ReleasePending
                    || !ReferenceEquals(entry.Owned, owned))
                {
                    return;
                }
                entry.Detail = result.Detail;
                if (result.OwnedReferencesDetached)
                {
                    entry.ReferencesDetached = true;
                    entry.ReleaseDueFrame = checked(
                        _lateFrame + _options.ReleaseDelayFrames);
                    entry.RestoreAttempts = 0;
                    entry.NextRestoreFrame = 0;
                }
                else if (result.ShouldRetry)
                {
                    entry.RestoreAttempts++;
                    if (entry.RestoreAttempts >= MaximumRestoreAttempts)
                    {
                        entry.ReleaseBlocked = true;
                        entry.Detail = "Restore retry limit reached: " + result.Detail;
                        blocked = true;
                    }
                    else
                    {
                        entry.NextRestoreFrame = checked(
                            _lateFrame + RetryDelay(entry.RestoreAttempts));
                    }
                }
                else
                {
                    entry.ReleaseBlocked = true;
                    blocked = true;
                }
            }

            if (!result.OwnedReferencesDetached)
            {
                Emit(
                    result.ShouldRetry && !blocked
                        ? AssetStreamEventKind.RestoreDeferred
                        : AssetStreamEventKind.ReleaseBlocked,
                    entry.Manifest.Group,
                    result.Detail);
            }
        }

        private bool TryRelease(GroupEntry entry)
        {
            AssetStreamOwnedGroup<TCommitted> owned;
            AssetStreamBudgetReservation budget;
            bool retryDeferred = false;
            bool releaseBlocked = false;
            lock (_gate)
            {
                if (entry.State != AssetStreamGroupState.ReleasePending
                    || entry.Owned == null
                    || !entry.ReferencesDetached
                    || entry.ReleaseBlocked
                    || _lateFrame < entry.ReleaseDueFrame)
                {
                    return false;
                }
                owned = entry.Owned;
                budget = entry.Budget;
            }

            AssetStreamReleaseResult result;
            try
            {
                result = _backend.Release(entry.Manifest, owned);
            }
            catch (Exception exception)
            {
                result = new AssetStreamReleaseResult(
                    false,
                    false,
                    "release threw; ownership is retained: " + Describe(exception));
            }

            lock (_gate)
            {
                if (entry.State != AssetStreamGroupState.ReleasePending
                    || !ReferenceEquals(entry.Owned, owned))
                {
                    return false;
                }
                entry.Detail = result.Detail;
                if (!result.Released)
                {
                    if (result.ProgressPending)
                    {
                        // Unity's UnloadUnusedAssets is asynchronous progress,
                        // not a failed release attempt. Poll it on later real
                        // LateUpdates without exhausting the safety retry cap.
                        entry.NextReleaseFrame = checked(_lateFrame + 1);
                        retryDeferred = true;
                    }
                    else
                    {
                        entry.ReleaseAttempts++;
                        if (result.Retryable
                            && entry.ReleaseAttempts < MaximumReleaseAttempts)
                        {
                            entry.NextReleaseFrame = checked(
                                _lateFrame + RetryDelay(entry.ReleaseAttempts));
                            retryDeferred = true;
                        }
                        else
                        {
                            entry.ReleaseBlocked = true;
                            entry.Detail = result.Retryable
                                ? "Release retry limit reached: " + result.Detail
                                : result.Detail;
                            releaseBlocked = true;
                        }
                    }
                }
                else if (budget == null)
                {
                    // The controller refuses to forget a live allocation if its
                    // accounting token disappeared unexpectedly.
                    entry.ReleaseBlocked = true;
                    entry.Detail = "Release completed but budget ownership was missing";
                    releaseBlocked = true;
                }
                else
                {
                    try
                    {
                        budget.Release();
                    }
                    catch (Exception exception)
                    {
                        // Backend release already completed. Never invoke it a
                        // second time merely because accounting failed.
                        entry.ReleaseBlocked = true;
                        entry.Detail = "Release completed but budget accounting failed: "
                            + Describe(exception);
                        releaseBlocked = true;
                    }
                    if (!releaseBlocked)
                    {
                        entry.Owned = null;
                        entry.Budget = null;
                        entry.State = AssetStreamGroupState.Unloaded;
                        entry.StateEpoch = _epoch;
                        entry.ReferencesDetached = false;
                        entry.ReleaseBlocked = false;
                        entry.ReleaseDueFrame = 0;
                        entry.RestoreAttempts = 0;
                        entry.ReleaseAttempts = 0;
                        entry.NextRestoreFrame = 0;
                        entry.NextReleaseFrame = 0;
                        entry.Detail = null;
                    }
                }
            }
            if (!result.Released || releaseBlocked)
            {
                if (!result.ProgressPending)
                {
                    Emit(
                        retryDeferred
                            ? AssetStreamEventKind.ReleaseDeferred
                            : AssetStreamEventKind.ReleaseBlocked,
                        entry.Manifest.Group,
                        result.Detail);
                }
                return false;
            }
            EmitLoadTelemetry(
                AssetStreamEventKind.ReleaseCompleted,
                entry.Manifest,
                "after-cleanup",
                budget.PreStageTelemetry,
                CaptureTransitionTelemetry(entry.Manifest));
            Emit(
                AssetStreamEventKind.ReleaseCompleted,
                entry.Manifest.Group,
                "owned assets released after delayed detach");
            return true;
        }

        private void PrepareReleaseLocked(GroupEntry entry)
        {
            entry.State = AssetStreamGroupState.ReleasePending;
            entry.StateEpoch = _epoch;
            entry.ReferencesDetached = false;
            entry.ReleaseBlocked = false;
            entry.ReleaseDueFrame = 0;
            entry.RestoreAttempts = 0;
            entry.ReleaseAttempts = 0;
            entry.NextRestoreFrame = 0;
            entry.NextReleaseFrame = 0;
            entry.Detail = null;
            entry.Queued = false;
        }

        private void SetBudgetDeniedLocked(GroupEntry entry, string detail)
        {
            entry.State = AssetStreamGroupState.BudgetDenied;
            entry.StateEpoch = _epoch;
            entry.TerminalEpoch = _epoch;
            entry.PermanentTerminal = false;
            entry.Detail = detail;
        }

        private void ResetExpiredTerminalLocked(GroupEntry entry)
        {
            if ((entry.State == AssetStreamGroupState.Failed
                    || entry.State == AssetStreamGroupState.BudgetDenied)
                && !entry.PermanentTerminal
                && entry.TerminalEpoch != _epoch
                && entry.Owned == null
                && entry.Budget == null)
            {
                entry.State = AssetStreamGroupState.Unloaded;
                entry.StateEpoch = _epoch;
                entry.TerminalEpoch = 0;
                entry.Detail = null;
                entry.ReleaseBlocked = false;
            }
        }

        private bool CanQueueLocked(GroupEntry entry)
        {
            return !_shuttingDown && _mapActive;
        }

        private void QueueLocked(GroupEntry entry)
        {
            if (entry.Queued && entry.QueuedEpoch == _epoch)
            {
                return;
            }
            entry.Queued = true;
            entry.QueuedEpoch = _epoch;
            _queue.Enqueue(entry.Manifest.Group);
        }

        private void ClearQueueLocked()
        {
            _queue.Clear();
            foreach (GroupEntry entry in _groups.Values)
            {
                entry.Queued = false;
                entry.QueuedEpoch = 0;
            }
        }

        private void RequireLoadTokenLocked(
            GroupEntry entry,
            AssetStreamOwnershipToken ownership)
        {
            if (entry.StateEpoch != ownership.Epoch
                || !string.Equals(
                    entry.Manifest.Group,
                    ownership.GroupId,
                    StringComparison.Ordinal)
                || (entry.State != AssetStreamGroupState.Verifying
                    && entry.State != AssetStreamGroupState.Loading))
            {
                throw new AssetStreamLoadException(
                    "Load token no longer owns the group transition",
                    true);
            }
            if (!_mapActive || _epoch != ownership.Epoch)
            {
                throw new AssetStreamLoadException(
                    "Map epoch ended during group load",
                    false);
            }
        }

        private GroupEntry RequireGroup(string groupId)
        {
            GroupEntry entry;
            if (!_groups.TryGetValue(groupId ?? string.Empty, out entry))
            {
                throw new KeyNotFoundException("Unknown asset-stream group");
            }
            return entry;
        }

        private void RequireMainThread()
        {
            if (!_threadGate.IsMainThread)
            {
                throw new InvalidOperationException(
                    "Asset-stream lifecycle transitions require the Unity main thread");
            }
        }

        private void RequireNoMainTransition()
        {
            if (_mainTransitioning)
            {
                throw new InvalidOperationException(
                    "Asset-stream main-thread transitions must not be re-entered");
            }
        }

        private static bool IsPermanent(Exception exception)
        {
            var loadException = exception as AssetStreamLoadException;
            return loadException != null && loadException.Permanent;
        }

        private static string AbortTransaction(
            IAssetStreamGroupTransaction<TCommitted> transaction)
        {
            if (transaction == null)
            {
                return null;
            }
            try
            {
                transaction.Abort();
                return null;
            }
            catch (Exception exception)
            {
                return Describe(exception);
            }
        }

        private void TrackBudgetUntilCleanup(
            GroupEntry entry,
            AssetStreamBudgetReservation reservation,
            AssetStreamCleanupCompletion completion,
            bool committedBudget)
        {
            completion.OnCompleted(delegate
            {
                string failure = null;
                bool matched = false;
                try
                {
                    if (committedBudget)
                    {
                        reservation.Release();
                    }
                    else
                    {
                        reservation.Cancel();
                    }
                }
                catch (Exception exception)
                {
                    failure = Describe(exception);
                }
                lock (_gate)
                {
                    if (!ReferenceEquals(entry.Budget, reservation))
                    {
                        return;
                    }
                    matched = true;
                    if (failure == null)
                    {
                        entry.Budget = null;
                    }
                    else
                    {
                        entry.ReleaseBlocked = true;
                        entry.Detail = "asynchronous cleanup accounting failed: "
                            + failure;
                    }
                }
                if (matched)
                {
                    EmitLoadTelemetry(
                        failure == null
                            ? AssetStreamEventKind.ReleaseCompleted
                            : AssetStreamEventKind.ReleaseBlocked,
                        entry.Manifest,
                        "after-cleanup",
                        reservation.PreStageTelemetry,
                        CaptureTransitionTelemetry(entry.Manifest));
                }
            });
        }

        private static string Describe(Exception exception)
        {
            return AssetStreamText.Sanitize(
                exception.GetType().Name + ": " + exception.Message,
                256);
        }

        private static int RetryDelay(int attempt)
        {
            int delay = 1;
            for (int index = 1; index < attempt && delay < MaximumRetryDelayFrames; index++)
            {
                delay = Math.Min(MaximumRetryDelayFrames, delay * 2);
            }
            return delay;
        }

        private AssetStreamEnsureResult Result(
            AssetStreamEnsureDisposition disposition,
            AssetStreamGroupState state,
            string groupId,
            string detail)
        {
            return new AssetStreamEnsureResult(
                disposition,
                state,
                groupId,
                _epoch,
                detail);
        }

        private void EmitLoadTelemetry(
            AssetStreamEventKind kind,
            AssetStreamGroupManifest manifest,
            string phase,
            AssetStreamResourceTelemetry baseline,
            AssetStreamResourceTelemetry current)
        {
            if (manifest.PipelineVersion
                != AssetStreamPipelineVersion.Bc7VisualEquivalenceV2)
            {
                return;
            }
            string privateValue = current != null && current.PrivateBytes.HasValue
                ? current.PrivateBytes.Value.ToString(CultureInfo.InvariantCulture)
                : "unavailable";
            string privateDelta = "unavailable";
            if (baseline != null && baseline.PrivateBytes.HasValue
                && current != null && current.PrivateBytes.HasValue)
            {
                try
                {
                    privateDelta = checked(
                        current.PrivateBytes.Value - baseline.PrivateBytes.Value)
                        .ToString(CultureInfo.InvariantCulture);
                }
                catch (OverflowException)
                {
                    privateDelta = "unavailable";
                }
            }
            Emit(
                kind,
                manifest.Group,
                "phase=" + phase
                    + "|declared_gpu="
                    + (manifest.PipelineVersion
                        == AssetStreamPipelineVersion.Bc7VisualEquivalenceV2
                            ? manifest.GpuBytes.ToString(CultureInfo.InvariantCulture)
                            : "not_declared_v1")
                    + "|declared_charge="
                    + manifest.ResidentChargeBytes.ToString(CultureInfo.InvariantCulture)
                    + "|private=" + privateValue
                    + "|private_delta=" + privateDelta);
        }

        private AssetStreamResourceTelemetry CaptureTransitionTelemetry(
            AssetStreamGroupManifest manifest)
        {
            return manifest.PipelineVersion
                == AssetStreamPipelineVersion.Bc7VisualEquivalenceV2
                    ? _budget.CaptureTelemetry()
                    : null;
        }

        private void Emit(
            AssetStreamEventKind kind,
            string groupId,
            string detail)
        {
            try
            {
                _events.Emit(new AssetStreamEvent(kind, groupId, _epoch, detail));
            }
            catch
            {
                // Observability must not participate in ownership transitions.
            }
        }

        private sealed class GroupEntry
        {
            internal GroupEntry(AssetStreamGroupManifest manifest)
            {
                Manifest = manifest;
                State = AssetStreamGroupState.Unloaded;
                StateEpoch = 1;
            }

            internal AssetStreamGroupManifest Manifest { get; private set; }

            internal AssetStreamBaseline<TBaseline> Baseline { get; set; }

            internal AssetStreamOwnedGroup<TCommitted> Owned { get; set; }

            internal AssetStreamBudgetReservation Budget { get; set; }

            internal AssetStreamGroupState State { get; set; }

            internal long StateEpoch { get; set; }

            internal long TerminalEpoch { get; set; }

            internal bool PermanentTerminal { get; set; }

            internal bool Queued { get; set; }

            internal long QueuedEpoch { get; set; }

            internal bool ReferencesDetached { get; set; }

            internal bool ReleaseBlocked { get; set; }

            internal long ReleaseDueFrame { get; set; }

            internal int RestoreAttempts { get; set; }

            internal int ReleaseAttempts { get; set; }

            internal long NextRestoreFrame { get; set; }

            internal long NextReleaseFrame { get; set; }

            internal string Detail { get; set; }
        }
    }
}
