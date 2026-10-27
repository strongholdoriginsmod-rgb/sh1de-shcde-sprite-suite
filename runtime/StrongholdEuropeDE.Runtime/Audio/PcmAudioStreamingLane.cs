using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using HarmonyLib;
using UnityEngine;
using UnityObject = UnityEngine.Object;

namespace StrongholdEuropeDE.Runtime.Audio
{
    internal sealed class PcmAudioClipLease : IDisposable
    {
        private int _disposed;

        internal PcmAudioClipLease(
            long id,
            PcmStreamTrack track,
            AudioClip clip,
            Pcm16StreamReader reader,
            PcmStreamBudgetReservation budget,
            PcmOriginalMusicRoute originalRoute,
            long attachDeadlinePump)
        {
            Id = id;
            Track = track;
            Clip = new WeakReference(clip, false);
            Reader = reader;
            Budget = budget;
            OriginalRoute = originalRoute
                ?? throw new ArgumentNullException("originalRoute");
            AttachDeadlinePump = attachDeadlinePump;
        }

        internal long Id { get; private set; }

        internal PcmStreamTrack Track { get; private set; }

        internal string Request
        {
            get { return Track.Request; }
        }

        internal WeakReference Clip { get; private set; }

        internal Pcm16StreamReader Reader { get; private set; }

        internal PcmStreamBudgetReservation Budget { get; private set; }

        internal PcmOriginalMusicRoute OriginalRoute { get; private set; }

        internal long AttachDeadlinePump { get; private set; }

        internal string FailureKind
        {
            get { return Track.RuntimeFailureKind; }
        }

        internal void MarkAwaitingAttachment(long attachDeadlinePump)
        {
            if (attachDeadlinePump < 0)
            {
                throw new ArgumentOutOfRangeException("attachDeadlinePump");
            }
            AttachDeadlinePump = attachDeadlinePump;
        }

        public void Dispose()
        {
            if (Interlocked.Exchange(ref _disposed, 1) != 0)
            {
                return;
            }
            try
            {
                Reader.Dispose();
            }
            finally
            {
                Budget.Dispose();
            }
        }
    }

    internal sealed class PcmPreparedRoute
    {
        internal PcmPreparedRoute(
            string request,
            AudioClip clip,
            long leaseId,
            PcmOriginalMusicRoute originalRoute,
            long shortDeadlinePump,
            bool deferredFadeAllowed,
            long absoluteDeadlineTimestamp)
        {
            Request = request;
            Clip = clip;
            LeaseId = leaseId;
            OriginalRoute = originalRoute
                ?? throw new ArgumentNullException("originalRoute");
            ShortDeadlinePump = shortDeadlinePump;
            DeferredFadeAllowed = deferredFadeAllowed;
            AbsoluteDeadlineTimestamp = absoluteDeadlineTimestamp;
        }

        internal string Request { get; private set; }
        internal AudioClip Clip { get; private set; }
        internal long LeaseId { get; private set; }
        internal PcmOriginalMusicRoute OriginalRoute { get; private set; }
        internal long ShortDeadlinePump { get; private set; }
        internal bool DeferredFadeAllowed { get; private set; }
        internal long AbsoluteDeadlineTimestamp { get; private set; }
    }

    /// <summary>
    /// Procedural PCM music provider that precedes only SHCDE-SE's exact
    /// TryLoadAudioClip method. Returning true from the Harmony prefix means
    /// "run SHCDE-SE/original Crusader handling"; only a successfully created
    /// manifest-owned eu_ clip skips the original.
    /// </summary>
    internal sealed class PcmAudioStreamingLane : IDisposable
    {
        private const string TargetTypeName = "SHCDESE.API.GameAssetManagerAPI";
        private const string TargetMethodName = "TryLoadAudioClip";
        private const string RawMusicPrefix = "fx\\music\\";
        private const long PreparedRouteGracePumps = 8;
        private static readonly long MaximumDeferredFadeTimestampDelta =
            checked(Stopwatch.Frequency * 30L);

        private static readonly object InstallationGate = new object();
        private static PcmAudioStreamingLane _current;
        private static bool _installationAttempted;

        private readonly object _gate = new object();
        private readonly PcmStreamManifest _manifest;
        private readonly PcmStreamBudgetLedger _budget;
        private readonly PcmStreamFailureRegistry _failures;
        private readonly PcmMusicOwnershipSurface _musicOwnership;
        private readonly PcmFaultRecoveryRetrySlot _faultRecoveryRetry;
        private readonly Dictionary<long, PcmAudioClipLease> _active;
        private readonly Dictionary<string, PcmPreparedRoute> _prepared;
        private readonly List<long> _releaseScratch;
        private readonly List<string> _preparedReleaseScratch;
        private readonly HashSet<string> _loggedFallbacks;
        private readonly Action<string> _information;
        private readonly Action<string> _warning;
        private readonly int _mainThreadId;
        private long _nextLeaseId;
        private long _pumpGeneration;
        private long _requestCount;
        private long _servedCount;
        private long _fallbackCount;
        private long _budgetDeniedCount;
        private int _ready;
        private int _shutdown;
        private int _shutdownDrain;
        private int _retainForApplicationExit;
        private int _ownershipProbeFailureLogged;
        private int _faultDetachFailureLogged;
        private int _faultRecoveryDepth;
        private int _shutdownDetachFailureLogged;
        private int _summaryLogged;
        private long _shutdownReleaseAfterPump;
        private GameObject _hostObject;

        private PcmAudioStreamingLane(
            PcmStreamManifest manifest,
            Action<string> information,
            Action<string> warning)
        {
            _manifest = manifest;
            _budget = new PcmStreamBudgetLedger(
                PcmStreamingLimits.MaximumActiveStreams,
                PcmStreamingLimits.MaximumBufferBytes);
            _failures = new PcmStreamFailureRegistry();
            _musicOwnership = PcmMusicOwnershipSurface.ResolveExact();
            _faultRecoveryRetry = new PcmFaultRecoveryRetrySlot();
            _active = new Dictionary<long, PcmAudioClipLease>();
            _prepared = new Dictionary<string, PcmPreparedRoute>(
                StringComparer.Ordinal);
            _releaseScratch = new List<long>(PcmStreamingLimits.MaximumActiveStreams);
            _preparedReleaseScratch = new List<string>(
                PcmStreamingLimits.MaximumActiveStreams);
            _loggedFallbacks = new HashSet<string>(StringComparer.Ordinal);
            _information = information;
            _warning = warning;
            _mainThreadId = Thread.CurrentThread.ManagedThreadId;
        }

        internal bool Ready
        {
            get { return Volatile.Read(ref _ready) != 0; }
        }

        internal static bool IsReadyForMusicRewrite
        {
            get
            {
                PcmAudioStreamingLane lane = Volatile.Read(ref _current);
                return lane != null && lane.Ready;
            }
        }

        /// <summary>
        /// Read-only process usage for the cross-lane asset-stream admission.
        /// Null is intentional: when the build expects PCM streaming but its
        /// lane is not ready, callers must fail closed instead of charging an
        /// invented zero bytes.
        /// </summary>
        internal static long? CurrentBufferBytes
        {
            get
            {
                PcmAudioStreamingLane lane = Volatile.Read(ref _current);
                if (lane == null || !lane.Ready)
                {
                    return null;
                }
                return lane.BudgetSnapshot().BufferBytes;
            }
        }

        /// <summary>
        /// Atomic gate for MusicRoutePrefix. True means the buffer reservation,
        /// pinned WAV and procedural clip already exist as a one-shot route;
        /// the caller may then expose the eu_ raw path without a later TOCTOU
        /// fallback to a nonexistent replacement.
        /// </summary>
        internal static bool CanRewriteTo(
            string replacementRawPath,
            PcmOriginalMusicRoute originalRoute)
        {
            PcmAudioStreamingLane lane = Volatile.Read(ref _current);
            if (lane == null
                || originalRoute == null
                || Volatile.Read(ref lane._faultRecoveryDepth) != 0)
            {
                return false;
            }
            lane.PumpClipLifetimes();
            return lane.TryPrepareRawReplacement(
                replacementRawPath,
                originalRoute);
        }

        internal static bool TryPrepareAndInstall(
            string pluginDirectory,
            string expectedManifestSha256,
            long expectedManifestSize,
            int expectedTrackCount,
            Harmony harmony,
            Action<string> information,
            Action<string> warning,
            out PcmAudioStreamingLane lane)
        {
            lane = null;
            lock (InstallationGate)
            {
                if (_installationAttempted)
                {
                    LogPrepareFallback(warning, "already_attempted");
                    return false;
                }
                _installationAttempted = true;
            }
            if (harmony == null)
            {
                LogPrepareFallback(warning, "harmony_missing");
                return false;
            }

            PcmAudioStreamingLane candidate = null;
            try
            {
                string manifestPath = Path.Combine(
                    pluginDirectory,
                    "Runtime",
                    "Audio",
                    PcmStreamingLimits.ManifestFileName);
                FileInfo manifestInfo = new FileInfo(manifestPath);
                if (!manifestInfo.Exists
                    || manifestInfo.Length != expectedManifestSize)
                {
                    throw new InvalidDataException(
                        "PCM manifest size does not match the compiled anchor");
                }
                PcmStreamManifest manifest = PcmStreamManifest.LoadAndValidate(
                    pluginDirectory,
                    expectedManifestSha256);
                if (manifest.Tracks.Length != expectedTrackCount)
                {
                    throw new InvalidDataException(
                        "PCM track count does not match the compiled anchor");
                }
                candidate = new PcmAudioStreamingLane(manifest, information, warning);
                candidate.CreateLifetimeHost();
                MethodInfo target = ResolveExactPatchTarget();
                MethodInfo prefix = typeof(PcmAudioStreamingLane).GetMethod(
                    "TryLoadAudioClipPrefix",
                    BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly);
                if (prefix == null || prefix.ReturnType != typeof(bool))
                {
                    throw new MissingMethodException("PCM streaming Harmony prefix is missing");
                }
                harmony.Patch(target, prefix: new HarmonyMethod(prefix));
                MethodInfo lifecyclePostfix = typeof(PcmAudioStreamingLane).GetMethod(
                    "MusicOwnershipChangedPostfix",
                    BindingFlags.NonPublic
                        | BindingFlags.Static
                        | BindingFlags.DeclaredOnly);
                if (lifecyclePostfix == null
                    || lifecyclePostfix.ReturnType != typeof(void)
                    || lifecyclePostfix.GetParameters().Length != 0)
                {
                    throw new MissingMethodException(
                        "PCM music ownership postfix is missing");
                }
                MethodInfo[] lifecycleTargets =
                    PcmMusicOwnershipSurface.ResolveLifecycleTargetsExact();
                for (int index = 0; index < lifecycleTargets.Length; index++)
                {
                    harmony.Patch(
                        lifecycleTargets[index],
                        postfix: new HarmonyMethod(lifecyclePostfix));
                }

                lock (InstallationGate)
                {
                    if (_current != null)
                    {
                        throw new InvalidOperationException(
                            "A PCM streaming lane was installed concurrently");
                    }
                    _current = candidate;
                    Volatile.Write(ref candidate._ready, 1);
                }
                lane = candidate;
                Info(
                    information,
                    "SEDE_RUNTIME_V1|event=pcm_stream|status=ready|tracks="
                    + manifest.Tracks.Length
                    + "|max_streams=" + PcmStreamingLimits.MaximumActiveStreams
                    + "|buffer_budget=" + PcmStreamingLimits.MaximumBufferBytes);
                return true;
            }
            catch (Exception exception)
            {
                if (candidate != null)
                {
                    candidate.ShutdownCore(true, false);
                }
                Warn(
                    warning,
                    "SEDE_RUNTIME_V1|event=pcm_stream|status=fallback"
                    + "|scope=lane|reason=prepare_failed"
                    + "|detail=" + exception.GetType().Name);
                Info(
                    information,
                    "SEDE_RUNTIME_V1|event=pcm_stream_summary|status=complete"
                    + "|requested=0|served=0|fallback=1|budget_denied=0");
                lane = null;
                return false;
            }
        }

        internal void PumpClipLifetimes()
        {
            if (Thread.CurrentThread.ManagedThreadId != _mainThreadId)
            {
                return;
            }
            if (Volatile.Read(ref _shutdown) != 0)
            {
                PumpShutdownDrain();
                return;
            }

            long currentPump;
            lock (_gate)
            {
                _pumpGeneration = checked(_pumpGeneration + 1);
                currentPump = _pumpGeneration;
            }
            PumpFaultRecoveryRetry(currentPump);

            PcmMusicOwnershipSnapshot ownership;
            bool ownershipAvailable =
                _musicOwnership.TryCapture(out ownership);
            if (!ownershipAvailable
                && Interlocked.Exchange(
                    ref _ownershipProbeFailureLogged,
                    1) == 0)
            {
                Warn(
                    _warning,
                    "PCM ownership probe failed closed; active leases are retained");
            }

            _releaseScratch.Clear();
            _preparedReleaseScratch.Clear();
            var faultedOwnedLeases = new List<PcmAudioClipLease>();
            var faultedOwnedClips = new List<AudioClip>();
            var faultedOwnedRequests = new List<string>();
            long monotonicNow = Stopwatch.GetTimestamp();
            lock (_gate)
            {
                foreach (KeyValuePair<string, PcmPreparedRoute> pair in _prepared)
                {
                    PcmPreparedRoute route = pair.Value;
                    bool sameFadePending = ownershipAvailable
                        && ownership.HasPendingFade(route.Request);
                    if (PcmPreparedRouteLifetimeDecision.ShouldExpire(
                            _pumpGeneration,
                            route.ShortDeadlinePump,
                            route.DeferredFadeAllowed,
                            ownershipAvailable,
                            sameFadePending,
                            monotonicNow,
                            route.AbsoluteDeadlineTimestamp))
                    {
                        _preparedReleaseScratch.Add(pair.Key);
                        _releaseScratch.Add(pair.Value.LeaseId);
                    }
                }
                for (int index = 0;
                    index < _preparedReleaseScratch.Count;
                    index++)
                {
                    _prepared.Remove(_preparedReleaseScratch[index]);
                }
                foreach (KeyValuePair<long, PcmAudioClipLease> pair in _active)
                {
                    PcmAudioClipLease lease = pair.Value;
                    bool prepared = IsPreparedLeaseLocked(pair.Key);
                    AudioClip activeClip = lease.Clip.Target as AudioClip;
                    bool clipAlive = !ReferenceEquals(activeClip, null)
                        && activeClip != null;
                    bool owned = ownershipAvailable
                        && clipAlive
                        && ownership.Owns(activeClip);
                    if (lease.Reader.Faulted && owned)
                    {
                        faultedOwnedLeases.Add(lease);
                        faultedOwnedClips.Add(activeClip);
                        faultedOwnedRequests.Add(lease.Request);
                        continue;
                    }
                    if (PcmLeaseLifetimeDecision.ShouldRelease(
                            prepared,
                            lease.Reader.Faulted,
                            clipAlive,
                            ownershipAvailable,
                            owned,
                            _pumpGeneration,
                            lease.AttachDeadlinePump)
                        && !_releaseScratch.Contains(pair.Key))
                    {
                        _releaseScratch.Add(pair.Key);
                    }
                }
            }

            if (faultedOwnedLeases.Count != 0)
            {
                bool detachedAny;
                PcmOriginalMusicRoute originalRoute =
                    FindFaultedCurrentOriginalRoute(
                        ownership,
                        faultedOwnedLeases,
                        faultedOwnedClips);
                bool recovered;
                PcmFaultRecoveryOutcome recoveryOutcome;
                Interlocked.Increment(ref _faultRecoveryDepth);
                try
                {
                    recovered = _musicOwnership.TryRecoverFaultedClips(
                        faultedOwnedClips,
                        faultedOwnedRequests,
                        originalRoute,
                        out detachedAny,
                        out recoveryOutcome);
                }
                finally
                {
                    Interlocked.Decrement(ref _faultRecoveryDepth);
                }
                if (recovered && detachedAny)
                {
                    string recoveryRequest = FaultRecoveryRequest(
                        originalRoute,
                        faultedOwnedLeases);
                    if (recoveryOutcome
                            == PcmFaultRecoveryOutcome.OriginalRouteRetryPending
                        && !_faultRecoveryRetry.TrySchedule(
                            currentPump,
                            recoveryRequest,
                            originalRoute,
                            faultedOwnedClips,
                            faultedOwnedRequests))
                    {
                        // The manager is already idle and owned-free. A full
                        // retry slot means this newer route must stay vanilla
                        // idle rather than replacing the bounded older retry.
                        recoveryOutcome = PcmFaultRecoveryOutcome.VanillaIdle;
                    }
                    LogFaultRecoveryOutcome(
                        recoveryOutcome,
                        recoveryRequest,
                        false);
                    for (int index = 0;
                        index < faultedOwnedLeases.Count;
                        index++)
                    {
                        if (!_releaseScratch.Contains(
                                faultedOwnedLeases[index].Id))
                        {
                            _releaseScratch.Add(
                                faultedOwnedLeases[index].Id);
                        }
                    }
                }
                else if (!recovered && Interlocked.Exchange(
                        ref _faultDetachFailureLogged,
                        1) == 0)
                {
                    Warn(
                        _warning,
                        "PCM reader fault retained its clip because exact "
                        + "MyAudioManager detach could not be proved");
                }
            }

            for (int index = 0; index < _releaseScratch.Count; index++)
            {
                PcmAudioClipLease lease = RemoveLease(_releaseScratch[index]);
                if (lease == null)
                {
                    continue;
                }
                string failureKind = lease.FailureKind;
                if (failureKind == null && lease.Reader.Faulted)
                {
                    failureKind = "PcmReaderFault";
                }
                AudioClip clip = lease.Clip.Target as AudioClip;
                lease.Dispose();
                DestroyClip(clip);
                if (failureKind != null
                    && _failures.MarkPermanent(lease.Request))
                {
                    RecordFallback(lease.Request, "reader_fault", false);
                    Warn(
                        _warning,
                        "PCM stream failed closed: request=" + lease.Request
                        + " reason=" + failureKind);
                }
            }
        }

        private void PumpFaultRecoveryRetry(long currentPump)
        {
            PcmFaultRecoveryRetry retry;
            if (!_faultRecoveryRetry.TryTakeDue(currentPump, out retry))
            {
                return;
            }

            bool recovered;
            PcmFaultRecoveryOutcome outcome;
            Interlocked.Increment(ref _faultRecoveryDepth);
            try
            {
                recovered = _musicOwnership.TryRetryFaultedOriginalRoute(
                    retry.FaultedClips,
                    retry.FaultedRequests,
                    retry.OriginalRoute,
                    out outcome);
            }
            finally
            {
                Interlocked.Decrement(ref _faultRecoveryDepth);
            }
            if (recovered)
            {
                LogFaultRecoveryOutcome(outcome, retry.Request, true);
                return;
            }
            if (Interlocked.Exchange(ref _faultDetachFailureLogged, 1) == 0)
            {
                Warn(
                    _warning,
                    "PCM delayed fault recovery could not prove an owned-free "
                    + "manager; the retry was not repeated");
            }
        }

        private static PcmOriginalMusicRoute FindFaultedCurrentOriginalRoute(
            PcmMusicOwnershipSnapshot ownership,
            IList<PcmAudioClipLease> leases,
            IList<AudioClip> clips)
        {
            if (ownership == null || leases == null || clips == null)
            {
                return null;
            }
            for (int index = 0; index < clips.Count; index++)
            {
                if (ReferenceEquals(ownership.Current, clips[index]))
                {
                    return leases[index].OriginalRoute;
                }
            }
            for (int index = 0; index < clips.Count; index++)
            {
                if (ReferenceEquals(ownership.PlayingSource, clips[index]))
                {
                    return leases[index].OriginalRoute;
                }
            }
            return null;
        }

        private static string FaultRecoveryRequest(
            PcmOriginalMusicRoute originalRoute,
            IList<PcmAudioClipLease> leases)
        {
            if (leases == null || leases.Count == 0)
            {
                return string.Empty;
            }
            if (originalRoute != null)
            {
                for (int index = 0; index < leases.Count; index++)
                {
                    if (ReferenceEquals(
                            leases[index].OriginalRoute,
                            originalRoute))
                    {
                        return leases[index].Request;
                    }
                }
            }
            return leases[0].Request;
        }

        private void LogFaultRecoveryOutcome(
            PcmFaultRecoveryOutcome outcome,
            string request,
            bool delayedRetry)
        {
            string sanitized = StrongholdEuropeDE.Runtime.AssetStreamText.Sanitize(
                request,
                96);
            if (outcome == PcmFaultRecoveryOutcome.OriginalRouteRetryPending)
            {
                Warn(
                    _warning,
                    "PCM fault recovery status=vanilla_idle_retry_pending"
                    + "|request=" + sanitized
                    + "|owned=false|retry=next_pump");
                return;
            }
            if (outcome == PcmFaultRecoveryOutcome.VanillaIdle)
            {
                Warn(
                    _warning,
                    "PCM fault recovery status=vanilla_idle|request="
                    + sanitized
                    + "|owned=false|reason=original_restart_unavailable");
                return;
            }
            Info(
                _information,
                "PCM fault recovery status=" + RecoveryOutcomeToken(outcome)
                + "|request=" + sanitized + "|owned=false"
                + (delayedRetry ? "|retry=delayed" : string.Empty));
        }

        private static string RecoveryOutcomeToken(PcmFaultRecoveryOutcome outcome)
        {
            switch (outcome)
            {
                case PcmFaultRecoveryOutcome.UnownedCurrentPreserved:
                    return "unowned_current_preserved";
                case PcmFaultRecoveryOutcome.VanillaNextPromoted:
                    return "vanilla_next_promoted";
                case PcmFaultRecoveryOutcome.OriginalRouteRestarted:
                    return "original_route_restarted";
                case PcmFaultRecoveryOutcome.VanillaIdle:
                    return "vanilla_idle";
                case PcmFaultRecoveryOutcome.OriginalRouteRetryPending:
                    return "vanilla_idle_retry_pending";
                default:
                    return "owned_detached";
            }
        }

        private bool IsPreparedLeaseLocked(long leaseId)
        {
            foreach (PcmPreparedRoute route in _prepared.Values)
            {
                if (route.LeaseId == leaseId)
                {
                    return true;
                }
            }
            return false;
        }

        internal PcmStreamBudgetSnapshot BudgetSnapshot()
        {
            return _budget.Snapshot();
        }

        public void Dispose()
        {
            ShutdownCore(true, false);
        }

        internal void Rollback(bool applicationQuitting)
        {
            ShutdownCore(true, applicationQuitting);
        }

        private static MethodInfo ResolveExactPatchTarget()
        {
            Type targetType = typeof(SHCDESE.API.GameAssetManagerAPI);
            if (!string.Equals(
                targetType.FullName,
                TargetTypeName,
                StringComparison.Ordinal))
            {
                throw new TypeLoadException("Exact SHCDE-SE asset manager type was not found");
            }
            MethodInfo target = targetType.GetMethod(
                TargetMethodName,
                BindingFlags.Instance
                    | BindingFlags.NonPublic
                    | BindingFlags.DeclaredOnly,
                null,
                new[]
                {
                    typeof(string),
                    typeof(AudioClip).MakeByRefType(),
                    typeof(bool)
                },
                null);
            if (target == null
                || target.IsStatic
                || target.IsPublic
                || !target.IsAssembly
                || target.ReturnType != typeof(bool)
                || target.DeclaringType != targetType)
            {
                throw new MissingMethodException(
                    "Exact internal GameAssetManagerAPI.TryLoadAudioClip signature was not found");
            }
            ParameterInfo[] parameters = target.GetParameters();
            if (parameters.Length != 3
                || !string.Equals(parameters[0].Name, "relativePath", StringComparison.Ordinal)
                || parameters[0].ParameterType != typeof(string)
                || !string.Equals(parameters[1].Name, "clip", StringComparison.Ordinal)
                || parameters[1].ParameterType != typeof(AudioClip).MakeByRefType()
                || !parameters[1].IsOut
                || !string.Equals(parameters[2].Name, "useCache", StringComparison.Ordinal)
                || parameters[2].ParameterType != typeof(bool)
                || !parameters[2].IsOptional
                || !object.Equals(parameters[2].DefaultValue, true))
            {
                throw new MissingMethodException(
                    "GameAssetManagerAPI.TryLoadAudioClip parameter contract changed");
            }
            return target;
        }

        private static bool TryLoadAudioClipPrefix(
            string relativePath,
            ref AudioClip clip,
            bool useCache,
            ref bool __result)
        {
            PcmAudioStreamingLane lane = Volatile.Read(ref _current);
            if (lane == null || !lane.Ready)
            {
                return true;
            }
            try
            {
                AudioClip prepared;
                if (useCache
                    || !lane.TryTakePreparedRoute(relativePath, out prepared))
                {
                    return true;
                }
                clip = prepared;
                __result = true;
                return false;
            }
            catch
            {
                // The original SHCDE-SE/Crusader path is the only fallback.
                return true;
            }
        }

        private bool TryCreateClip(
            string relativePath,
            bool useCache,
            PcmOriginalMusicRoute originalRoute,
            out AudioClip clip,
            out long createdLeaseId)
        {
            clip = null;
            createdLeaseId = 0;
            if (originalRoute == null)
            {
                return false;
            }
            PcmStreamTrack track;
            try
            {
                if (!Ready || !_manifest.TryGetTrack(relativePath, out track))
                {
                    return false;
                }
            }
            catch
            {
                return false;
            }
            Interlocked.Increment(ref _requestCount);

            // SHCDE-SE documents false for music/speech because the game unloads
            // each clip. Let its original path handle any cacheable request.
            if (useCache || Thread.CurrentThread.ManagedThreadId != _mainThreadId)
            {
                RecordFallback(
                    track.Request,
                    useCache ? "cache_request" : "wrong_thread",
                    false);
                return false;
            }
            PumpClipLifetimes();
            if (_failures.IsPermanent(track.Request))
            {
                RecordFallback(track.Request, "permanent_failure", false);
                return false;
            }
            if (track.RuntimeFaulted)
            {
                if (_failures.MarkPermanent(track.Request))
                {
                    Warn(
                        _warning,
                        "PCM stream failed closed: request=" + track.Request
                        + " reason=" + (track.RuntimeFailureKind ?? "UnknownFailure"));
                }
                RecordFallback(track.Request, "runtime_fault", false);
                return false;
            }
            PcmStreamBudgetSnapshot before = _budget.Snapshot();
            if (_failures.IsBudgetDenied(track.Request, before.Generation))
            {
                RecordFallback(track.Request, "budget_denied", true);
                return false;
            }

            PcmStreamBudgetReservation reservation;
            if (!_budget.TryReserve(
                PcmStreamingLimits.BufferBytesPerStream,
                out reservation))
            {
                _failures.MarkBudgetDenied(
                    track.Request,
                    _budget.Snapshot().Generation);
                RecordFallback(track.Request, "budget_denied", true);
                return false;
            }

            Pcm16StreamReader reader = null;
            AudioClip created = null;
            long leaseId = Interlocked.Increment(ref _nextLeaseId);
            try
            {
                FileStream stream = PcmWaveFile.OpenPinned(track);
                try
                {
                    reader = new Pcm16StreamReader(
                        stream,
                        track.Wave,
                        PcmStreamingLimits.BufferBytesPerStream,
                        true,
                        track.MarkRuntimeFault);
                }
                catch
                {
                    stream.Dispose();
                    throw;
                }

                created = AudioClip.Create(
                    track.Request,
                    checked((int)track.Wave.SampleFrames),
                    track.Channels,
                    track.SampleRate,
                    true,
                    reader.PcmReaderCallback,
                    reader.PcmSetPositionCallback);
                if (created == null)
                {
                    throw new InvalidOperationException(
                        "Unity rejected the procedural PCM AudioClip");
                }
                created.name = track.Request;
                var lease = new PcmAudioClipLease(
                    leaseId,
                    track,
                    created,
                    reader,
                    reservation,
                    originalRoute,
                    long.MaxValue);
                lock (_gate)
                {
                    if (!Ready || Volatile.Read(ref _shutdown) != 0)
                    {
                        throw new InvalidOperationException(
                            "PCM streaming shut down during clip creation");
                    }
                    _active.Add(leaseId, lease);
                }
                reader = null;
                reservation = null;
                clip = created;
                createdLeaseId = leaseId;
                Interlocked.Increment(ref _servedCount);
                return true;
            }
            catch (Exception exception)
            {
                bool firstFailure = _failures.MarkPermanent(track.Request);
                if (reader != null)
                {
                    reader.Dispose();
                }
                if (reservation != null)
                {
                    reservation.Dispose();
                }
                DestroyClip(created);
                if (firstFailure)
                {
                    Warn(
                        _warning,
                        "PCM stream failed closed: request=" + track.Request
                        + " reason=" + exception.GetType().Name);
                }
                RecordFallback(track.Request, "clip_create_failed", false);
                return false;
            }
        }

        private bool TryPrepareRawReplacement(
            string replacementRawPath,
            PcmOriginalMusicRoute originalRoute)
        {
            if (!Ready
                || originalRoute == null
                || string.IsNullOrEmpty(replacementRawPath)
                || !replacementRawPath.StartsWith(RawMusicPrefix, StringComparison.Ordinal)
                || !replacementRawPath.EndsWith(".raw", StringComparison.Ordinal)
                || replacementRawPath.IndexOf('/') >= 0)
            {
                return false;
            }
            string stem = replacementRawPath.Substring(
                RawMusicPrefix.Length,
                replacementRawPath.Length - RawMusicPrefix.Length - 4);
            string request = stem + ".wav";
            lock (_gate)
            {
                if (_prepared.ContainsKey(request))
                {
                    return false;
                }
            }

            AudioClip clip;
            long leaseId;
            if (!TryCreateClip(
                    request,
                    false,
                    originalRoute,
                    out clip,
                    out leaseId))
            {
                return false;
            }
            bool installed = false;
            try
            {
                lock (_gate)
                {
                    if (Ready
                        && Volatile.Read(ref _shutdown) == 0
                        && !_prepared.ContainsKey(request))
                    {
                        _prepared.Add(
                            request,
                            new PcmPreparedRoute(
                                request,
                                clip,
                                leaseId,
                                originalRoute,
                                checked(
                                    _pumpGeneration
                                    + PreparedRouteGracePumps),
                                originalRoute.FadePrevious,
                                checked(
                                    Stopwatch.GetTimestamp()
                                    + MaximumDeferredFadeTimestampDelta)));
                        installed = true;
                    }
                }
                return installed;
            }
            finally
            {
                if (!installed)
                {
                    PcmAudioClipLease lease = RemoveLease(leaseId);
                    if (lease != null)
                    {
                        lease.Dispose();
                    }
                    DestroyClip(clip);
                }
            }
        }

        private bool TryTakePreparedRoute(
            string relativePath,
            out AudioClip clip)
        {
            clip = null;
            PcmStreamTrack track;
            try
            {
                if (!Ready || !_manifest.TryGetTrack(relativePath, out track))
                {
                    return false;
                }
            }
            catch
            {
                return false;
            }
            lock (_gate)
            {
                PcmPreparedRoute route;
                if (!_prepared.TryGetValue(track.Request, out route))
                {
                    return false;
                }
                PcmAudioClipLease lease;
                if (!_active.TryGetValue(route.LeaseId, out lease))
                {
                    throw new InvalidOperationException(
                        "Prepared PCM route lost its active lease");
                }
                if (!ReferenceEquals(
                        route.OriginalRoute,
                        lease.OriginalRoute))
                {
                    throw new InvalidOperationException(
                        "Prepared PCM route lost its original Crusader route");
                }
                lease.MarkAwaitingAttachment(
                    checked(_pumpGeneration + 2));
                _prepared.Remove(track.Request);
                clip = route.Clip;
                return clip != null;
            }
        }

        private static void MusicOwnershipChangedPostfix()
        {
            PcmAudioStreamingLane lane = Volatile.Read(ref _current);
            if (lane != null && lane.Ready)
            {
                if (Volatile.Read(ref lane._faultRecoveryDepth) == 0)
                {
                    lane.PumpClipLifetimes();
                }
            }
        }

        private PcmAudioClipLease RemoveLease(long leaseId)
        {
            lock (_gate)
            {
                PcmAudioClipLease lease;
                if (!_active.TryGetValue(leaseId, out lease))
                {
                    return null;
                }
                _active.Remove(leaseId);
                return lease;
            }
        }

        private void CreateLifetimeHost()
        {
            GameObject hostObject = null;
            try
            {
                hostObject = new GameObject("StrongholdEuropeDE.PcmStreamLifetimeHost");
                UnityObject.DontDestroyOnLoad(hostObject);
                hostObject.hideFlags = HideFlags.HideAndDontSave;
                PcmStreamLifetimeHost host =
                    hostObject.AddComponent<PcmStreamLifetimeHost>();
                host.Bind(this);
                _hostObject = hostObject;
                hostObject = null;
            }
            finally
            {
                if (hostObject != null)
                {
                    UnityObject.Destroy(hostObject);
                }
            }
        }

        internal void HostDestroyed()
        {
            _hostObject = null;
            ShutdownCore(false, !Application.isPlaying);
        }

        private void ShutdownCore(
            bool destroyHost,
            bool applicationQuitting)
        {
            bool mainThread = Thread.CurrentThread.ManagedThreadId == _mainThreadId;
            bool first = Interlocked.Exchange(ref _shutdown, 1) == 0;
            if (applicationQuitting)
            {
                Volatile.Write(ref _retainForApplicationExit, 1);
            }
            if (first)
            {
                _faultRecoveryRetry.Clear();
                Volatile.Write(ref _ready, 0);
                lock (InstallationGate)
                {
                    if (ReferenceEquals(_current, this))
                    {
                        _current = null;
                    }
                }

                lock (_gate)
                {
                    _shutdownReleaseAfterPump = checked(_pumpGeneration + 2);
                    foreach (PcmAudioClipLease lease in _active.Values)
                    {
                        lease.MarkAwaitingAttachment(_shutdownReleaseAfterPump);
                    }
                }
            }

            if (Volatile.Read(ref _retainForApplicationExit) == 0)
            {
                Volatile.Write(ref _shutdownDrain, 1);
                if (mainThread && ActiveLeaseCount != 0 && _hostObject == null)
                {
                    CreateLifetimeHost();
                }
            }

            if (destroyHost
                && mainThread
                && (Volatile.Read(ref _retainForApplicationExit) != 0
                    || ActiveLeaseCount == 0))
            {
                DestroyLifetimeHost();
            }
            LogShutdownSummaryOnce();
        }

        private void PumpShutdownDrain()
        {
            if (Volatile.Read(ref _shutdownDrain) == 0
                || Volatile.Read(ref _retainForApplicationExit) != 0)
            {
                return;
            }

            var clips = new List<AudioClip>();
            var pendingFadeRequests = new List<string>();
            lock (_gate)
            {
                _pumpGeneration = checked(_pumpGeneration + 1);
                foreach (PcmAudioClipLease lease in _active.Values)
                {
                    AudioClip clip = lease.Clip.Target as AudioClip;
                    if (!ReferenceEquals(clip, null) && clip != null)
                    {
                        clips.Add(clip);
                    }
                }
                foreach (PcmPreparedRoute route in _prepared.Values)
                {
                    pendingFadeRequests.Add(route.Request);
                }
            }
            if (ActiveLeaseCount == 0)
            {
                CompleteShutdownDrain();
                return;
            }

            bool detachedAny;
            if (!_musicOwnership.TryDetachOwnedClips(
                    clips,
                    pendingFadeRequests,
                    out detachedAny))
            {
                LogShutdownDetachFailureOnce();
                return;
            }
            if (detachedAny)
            {
                lock (_gate)
                {
                    _shutdownReleaseAfterPump = checked(_pumpGeneration + 2);
                    foreach (PcmAudioClipLease lease in _active.Values)
                    {
                        lease.MarkAwaitingAttachment(_shutdownReleaseAfterPump);
                    }
                }
            }
            lock (_gate)
            {
                // The exact manager no longer contains any route token. No
                // patched TryLoad call can consume these after Ready=false.
                _prepared.Clear();
            }

            PcmMusicOwnershipSnapshot ownership;
            if (!_musicOwnership.TryCapture(out ownership))
            {
                LogShutdownDetachFailureOnce();
                return;
            }

            _releaseScratch.Clear();
            lock (_gate)
            {
                foreach (KeyValuePair<long, PcmAudioClipLease> pair in _active)
                {
                    AudioClip clip = pair.Value.Clip.Target as AudioClip;
                    bool alive = !ReferenceEquals(clip, null) && clip != null;
                    bool owned = alive && ownership.Owns(clip);
                    if (PcmLeaseLifetimeDecision.ShouldRelease(
                            false,
                            pair.Value.Reader.Faulted,
                            alive,
                            true,
                            owned,
                            _pumpGeneration,
                            pair.Value.AttachDeadlinePump))
                    {
                        _releaseScratch.Add(pair.Key);
                    }
                }
            }
            for (int index = 0; index < _releaseScratch.Count; index++)
            {
                PcmAudioClipLease lease = RemoveLease(_releaseScratch[index]);
                if (lease == null)
                {
                    continue;
                }
                AudioClip clip = lease.Clip.Target as AudioClip;
                lease.Dispose();
                DestroyClip(clip);
            }
            if (ActiveLeaseCount == 0)
            {
                CompleteShutdownDrain();
            }
        }

        private int ActiveLeaseCount
        {
            get { lock (_gate) { return _active.Count; } }
        }

        private void CompleteShutdownDrain()
        {
            lock (_gate)
            {
                _prepared.Clear();
            }
            Volatile.Write(ref _shutdownDrain, 0);
            DestroyLifetimeHost();
        }

        private void DestroyLifetimeHost()
        {
            GameObject hostObject = _hostObject;
            _hostObject = null;
            if (hostObject != null)
            {
                UnityObject.Destroy(hostObject);
            }
        }

        private void LogShutdownDetachFailureOnce()
        {
            if (Interlocked.Exchange(ref _shutdownDetachFailureLogged, 1) == 0)
            {
                Warn(
                    _warning,
                    "PCM shutdown retained procedural clips because exact "
                    + "MyAudioManager detach could not be proved");
            }
        }

        private void LogShutdownSummaryOnce()
        {
            if (Interlocked.Exchange(ref _summaryLogged, 1) != 0)
            {
                return;
            }
            Info(_information, "SEDE_RUNTIME_V1|event=pcm_stream|status=inactive");
            Info(
                _information,
                "SEDE_RUNTIME_V1|event=pcm_stream_summary|status=complete"
                + "|requested=" + Interlocked.Read(ref _requestCount)
                + "|served=" + Interlocked.Read(ref _servedCount)
                + "|fallback=" + Interlocked.Read(ref _fallbackCount)
                + "|budget_denied=" + Interlocked.Read(ref _budgetDeniedCount));
        }

        private void RecordFallback(
            string request,
            string reason,
            bool budgetDenied)
        {
            string key = (request ?? string.Empty) + "\t" + reason;
            lock (_gate)
            {
                if (!_loggedFallbacks.Add(key))
                {
                    return;
                }
            }
            Interlocked.Increment(ref _fallbackCount);
            if (budgetDenied)
            {
                Interlocked.Increment(ref _budgetDeniedCount);
            }
            Warn(
                _warning,
                "SEDE_RUNTIME_V1|event=pcm_stream|status=fallback"
                + "|scope=track|request="
                + StrongholdEuropeDE.Runtime.AssetStreamText.Sanitize(request, 96)
                + "|reason=" + reason);
        }

        private static void LogPrepareFallback(
            Action<string> warning,
            string reason)
        {
            Warn(
                warning,
                "SEDE_RUNTIME_V1|event=pcm_stream|status=fallback"
                + "|scope=lane|reason=" + reason);
        }

        private static void DestroyClip(AudioClip clip)
        {
            if (!ReferenceEquals(clip, null) && clip != null)
            {
                try
                {
                    UnityObject.Destroy(clip);
                }
                catch
                {
                    // Stream ownership is already released; Unity cleanup is best-effort.
                }
            }
        }

        private static void Info(Action<string> sink, string message)
        {
            if (sink != null)
            {
                try
                {
                    sink(message);
                }
                catch
                {
                    // Logging cannot affect the audio lane.
                }
            }
        }

        private static void Warn(Action<string> sink, string message)
        {
            Info(sink, message);
        }

    }
}
