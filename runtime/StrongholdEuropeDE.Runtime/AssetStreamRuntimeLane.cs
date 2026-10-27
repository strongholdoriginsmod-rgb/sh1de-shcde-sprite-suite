using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using System.Threading;
using CrusaderDE;
using HarmonyLib;
using R3;
using SHCDESE.API;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.MapLoader;
using UnityEngine;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Separate Harmony/lifecycle lane for map-scoped GM AssetBundles. Every
    /// callback catches locally; a rejected or failed group stays on the exact
    /// post-extender baseline.
    /// </summary>
    internal sealed class AssetStreamRuntimeLane
    {
        private const string HarmonySuffix = ".asset-stream.v1";
        private const string BodyHookTypeName =
            "SHCDESE.ManagedHooks.ManagedHookManager";
        private const string BodyHookMethodName =
            "SpriteMapping_SetBodySprite_Hook";
        private const int MaximumTransientRetries = 6;
        private const int RetryDelayBaseFrames = 2;
        private const int RetryDelayMaxFrames = 60;
        private const float BattlementPivotTolerancePixels = 0.02f;

        private static readonly object InstallationGate = new object();
        private static readonly List<AssetStreamRuntimeLane> RetainedShutdownLanes =
            new List<AssetStreamRuntimeLane>();
        private static GameObject _drainHostObject;
        private static AssetStreamRuntimeLane _current;
        private static bool _installationAttempted;

        private readonly object _gate = new object();
        // Captured in the constructor and, since 2026-09-02, re-checked on the
        // first Update tick: Update() is Unity's main thread by definition.
        private int _mainThreadId;
        private int _tickDiagnosticsLogged;
        private int _idleGateTicks;
        private readonly AssetStreamManifest _manifest;
        private readonly AssetStreamSpriteLoaderSurface _surface;
        private readonly AssetStreamPageMaterialRegistry _routes;
        private readonly int _teamMaskPropertyId;
        private readonly Texture _neutralTeamMask;
        private readonly MaterialPropertyBlock _pageMaskBlock;
        private readonly AssetStreamPageMaskOwnership<Texture> _pageMaskOwnership;
        private readonly AssetStreamPageMaskProbeDiagnostics _maskRouteProbe;
        private readonly UnityAssetStreamGroupBackend _backend;
        private readonly AssetStreamMainThreadTimeline _timeline;
        private readonly AssetStreamQueuedEventSink _controllerEvents;
        private readonly RuntimeAssetStreamController<
            AssetStreamUnityBaseline,
            AssetStreamUnityCommitted> _controller;
        private readonly AssetStreamBudgetLedger _budget;
        private readonly Harmony _harmony;
        private readonly Action<string> _information;
        private readonly Action<string> _warning;
        private readonly HashSet<int> _manifestGms;
        private readonly Dictionary<string, int> _groupGms;
        private readonly string[] _gmGroups = new string[234];
        private readonly Dictionary<string, AssetStreamGroupManifest> _groupsById;
        private readonly int[] _gmFastState = new int[234];
        private readonly AssetStreamUnityBaseline[] _gmBaselines =
            new AssetStreamUnityBaseline[234];
        private readonly AssetStreamOffMainRequestQueue _offMainRequests;
        private readonly Dictionary<string, string> _spriteNameGroups;
        private readonly Queue<MapTransition> _mapTransitions =
            new Queue<MapTransition>();
        private readonly AssetStreamMapStartGate _mapStartGate =
            new AssetStreamMapStartGate();
        private readonly HashSet<string> _terminalGroupEpochs =
            new HashSet<string>(StringComparer.Ordinal);
        private readonly HashSet<long> _summarizedEpochs = new HashSet<long>();
        private readonly Dictionary<string, string> _pendingGroups =
            new Dictionary<string, string>(StringComparer.Ordinal);
        private readonly Dictionary<int, AssetStreamRetryPlan> _retryPlans =
            new Dictionary<int, AssetStreamRetryPlan>();
        private readonly FieldInfo _buildingAnimsField;
        private readonly FieldInfo _wallFillinsField;
        private readonly Dictionary<int, BattlementOverlayVariant>
            _battlementOverlayVariants =
                new Dictionary<int, BattlementOverlayVariant>();

        private IDisposable _mapStartSubscription;
        private IDisposable _mapLoadSubscription;
        private IDisposable _mapSaveSubscription;
        private IDisposable _mapUnloadSubscription;
        private long _mapEpoch;
        private volatile bool _mapActive;
        private bool _baselineCaptureStarted;
        private bool _baselineCaptured;
        private bool _editorReadyObserved;
        private int _routeConflicts;
        // Page-mask release telemetry. Cumulative for the process so a
        // SUCCESSFUL session leaves evidence too: before this, the counters
        // only ever appeared inside the failure message, so a clean run was
        // indistinguishable from a run where the path never executed.
        private int _neutralizeRuns;
        private int _neutralizeTracked;
        private int _neutralizeNeutralized;
        private int _neutralizeBlocked;
        private int _neutralizeFailures;

        /// <summary>
        /// True once some lane has finished registering all group baselines.
        /// </summary>
        /// <remarks>
        /// Read-only observation point for the UI base-texture reclaim, which
        /// must not touch asset lifetime before the 152 per-group baselines are
        /// rooted. A process-global unused-assets scan ran inside that window
        /// and collected substantially more objects than the normal session,
        /// so lifetime changes remain gated until the baselines are rooted.
        /// A later A/B check showed that the archer colour flicker persisted
        /// without that scan; it is therefore not claimed as the flicker cause.
        /// Nothing here writes lane state.
        /// </remarks>
        internal static bool AnyBaselineCaptured
        {
            get { return Volatile.Read(ref _anyBaselineCaptured) != 0; }
        }

        private static int _anyBaselineCaptured;
        private int _spriteRoutesPublished;
        private int _fastReady;
        private ReadOnlyDictionary<string, Sprite> _frozenAllSprites;
        private bool _ready;
        private bool _stopped;
        private bool _retainForApplicationExit;
        private bool _shutdownInitiated;
        private bool _drainTerminal;
        private bool _drainFailureLogged;
        private bool _failureLogged;
        private bool _battlementOverlayFailureLogged;
        private long _summaryEpoch;
        private int _requestedGroups;
        private int _loadedGroups;
        private int _fallbackGroups;
        private int _budgetDeniedGroups;
        private int _telemetrySamples;
        private long _maximumPrivateBytes;
        private long _minimumAvailableCommitBytes = long.MaxValue;
        private long _minimumAvailablePhysicalBytes = long.MaxValue;
        private long _maximumCommittedGmBytes;
        private long _maximumUiBytes;
        private long _maximumAudioBytes;
        private bool _hasPrivateBytes;
        private bool _hasAvailableCommitBytes;
        private bool _hasAvailablePhysicalBytes;
        private bool _hasCommittedGmBytes;
        private bool _hasUiBytes;
        private bool _hasAudioBytes;

        private AssetStreamRuntimeLane(
            AssetStreamManifest manifest,
            AssetStreamSpriteLoaderSurface surface,
            AssetStreamPageMaterialRegistry routes,
            UnityAssetStreamGroupBackend backend,
            AssetStreamMainThreadTimeline timeline,
            AssetStreamQueuedEventSink controllerEvents,
            RuntimeAssetStreamController<AssetStreamUnityBaseline,
                AssetStreamUnityCommitted> controller,
            AssetStreamBudgetLedger budget,
            Harmony harmony,
            Action<string> information,
            Action<string> warning)
        {
            _manifest = manifest;
            _surface = surface;
            _routes = routes;
            _backend = backend;
            _timeline = timeline;
            _controllerEvents = controllerEvents;
            _controller = controller;
            _budget = budget;
            _harmony = harmony;
            _information = information;
            _warning = warning;
            _mainThreadId = Thread.CurrentThread.ManagedThreadId;
            _buildingAnimsField = ResolveBuildingAnimsField();
            _wallFillinsField = ResolveWallFillinsField();
            _teamMaskPropertyId = Shader.PropertyToID("_TeamMask");
            _neutralTeamMask = Texture2D.blackTexture;
            if (_neutralTeamMask == null)
            {
                throw new InvalidOperationException(
                    "Unity did not provide the process-stable neutral texture");
            }
            _pageMaskBlock = new MaterialPropertyBlock();
            _pageMaskOwnership = new AssetStreamPageMaskOwnership<Texture>();
            _maskRouteProbe = new AssetStreamPageMaskProbeDiagnostics();
            _offMainRequests = new AssetStreamOffMainRequestQueue(
                _gmFastState.Length);
            _manifestGms = new HashSet<int>();
            _groupGms = new Dictionary<string, int>(StringComparer.Ordinal);
            _groupsById = new Dictionary<string, AssetStreamGroupManifest>(
                StringComparer.Ordinal);
            for (int index = 0; index < manifest.Groups.Count; index++)
            {
                AssetStreamGroupManifest group = manifest.Groups[index];
                _manifestGms.Add(group.GmId);
                _groupGms.Add(group.Group, group.GmId);
                _gmGroups[group.GmId] = group.Group;
                _groupsById.Add(group.Group, group);
            }
            _spriteNameGroups = new Dictionary<string, string>(
                StringComparer.Ordinal);
        }

        internal bool Ready
        {
            get { lock (_gate) { return _ready && !_stopped; } }
        }

        private bool FastReady
        {
            get { return Volatile.Read(ref _fastReady) != 0; }
        }

        internal static bool TryPrepareAndInstall(
            string pluginDirectory,
            string pluginId,
            AssetStreamCompiledContract compiled,
            Action<string> information,
            Action<string> warning,
            out AssetStreamRuntimeLane lane)
        {
            lane = null;
            if (compiled == null) throw new ArgumentNullException("compiled");
            if (!compiled.Enabled)
            {
                return false;
            }
            lock (InstallationGate)
            {
                if (_installationAttempted)
                {
                    SafeLog(warning,
                        "Asset-stream lane stayed vanilla: already_attempted");
                    return false;
                }
                _installationAttempted = true;
            }

            AssetStreamRuntimeLane candidate = null;
            Harmony harmony = null;
            try
            {
                if (string.IsNullOrEmpty(pluginId))
                {
                    throw new ArgumentNullException("pluginId");
                }
                RuntimeBuildGuard.VerifyCoreReportingDrift();
                RuntimeBuildGuard.VerifyOptionalReportingDrift("r3");
                AssetStreamManifest manifest = LoadAnchoredIndex(
                    pluginDirectory,
                    compiled);
                if (manifest.PipelineVersion
                    == AssetStreamPipelineVersion.Bc7VisualEquivalenceV2)
                {
                    if (manifest.QualityPolicy == null
                        || !manifest.QualityPolicy.IsPromotable)
                    {
                        throw new InvalidDataException("quality_not_promotable");
                    }
                    AssetStreamManifestRules.RequireBc7RuntimeSupport(
                        true,
                        SystemInfo.SupportsTextureFormat(TextureFormat.BC7));
                }
                var surface = new AssetStreamSpriteLoaderSurface();
                VerifyExactPatchSurface();
                var routes = new AssetStreamPageMaterialRegistry();
                var backend = new UnityAssetStreamGroupBackend(
                    pluginDirectory,
                    surface,
                    routes,
                    compiled.FoliageGroups);
                var ledger = new AssetStreamBudgetLedger(
                    manifest.PipelineVersion
                        == AssetStreamPipelineVersion.Bc7VisualEquivalenceV2
                            ? AssetStreamResourcePolicy.Windows24GbIgpuBc7TwelveGibProcessPrivateV5()
                            : AssetStreamResourcePolicy.Windows24GbIgpuSafeV1(),
                    new WindowsAssetStreamMemoryProbe(),
                    new AssetStreamExternalUsageBridge(
                        compiled.UiStreamingExpected,
                        compiled.PcmStreamingExpected));
                var timeline = new AssetStreamMainThreadTimeline();
                var controllerEvents = new AssetStreamQueuedEventSink(
                    new AssetStreamLogEventSink(information, warning));
                var controller = new RuntimeAssetStreamController<
                    AssetStreamUnityBaseline,
                    AssetStreamUnityCommitted>(
                        manifest,
                        backend,
                        new AssetStreamCapturedThreadGate(),
                        ledger,
                        AssetStreamControllerOptions.SafeDefaults(),
                        controllerEvents);
                harmony = new Harmony(pluginId + HarmonySuffix);
                candidate = new AssetStreamRuntimeLane(
                    manifest,
                    surface,
                    routes,
                    backend,
                    timeline,
                    controllerEvents,
                    controller,
                    ledger,
                    harmony,
                    information,
                    warning);
                candidate.InstallPatches();
                lock (InstallationGate)
                {
                    if (_current != null)
                    {
                        throw new InvalidOperationException(
                            "Asset-stream lane was installed concurrently");
                    }
                    _current = candidate;
                }
                candidate.SubscribeMapLifecycle();
                lock (candidate._gate)
                {
                    candidate._ready = true;
                }
                Volatile.Write(ref candidate._fastReady, 1);
                lane = candidate;
                SafeLog(
                    information,
                    "SEDE_RUNTIME_V1|event=asset_stream|status=initialized|groups="
                    + manifest.Groups.Count
                    + "|backend=" + manifest.BackendKind
                    + "|policy=" + manifest.ResourcePolicyKind);
                return true;
            }
            catch (Exception exception)
            {
                lock (InstallationGate)
                {
                    if (ReferenceEquals(_current, candidate))
                    {
                        _current = null;
                    }
                }
                if (candidate != null)
                {
                    candidate.Rollback(false);
                }
                else if (harmony != null)
                {
                    try { harmony.UnpatchSelf(); }
                    catch { }
                }
                SafeLog(
                    warning,
                    "SEDE_RUNTIME_V1|event=asset_stream|status=vanilla"
                    + "|reason=" + Describe(exception));
                lane = null;
                return false;
            }
        }

        internal void Tick()
        {
            if (Volatile.Read(ref _tickDiagnosticsLogged) == 0)
            {
                Volatile.Write(ref _tickDiagnosticsLogged, 1);
                LogFirstTick();
            }
            if (!Ready || !IsMainThread)
            {
                return;
            }
            try
            {
                ObserveEditorReadyGate();
                LogIdleGateIfStalled();
                DrainMapTransitions();
                _timeline.Execute(delegate
                {
                    DrainQueuedResultsOnMainLocked();
                    AssetStreamEnsureResult pumped;
                    int requestedGm;
                    if (_mapActive
                        && TryPumpRetry(out pumped))
                    {
                        // Retries are intentionally limited; one retry attempt per
                        // tick is enough for a stable frame budget.
                    }
                    else if (_mapActive
                        && _offMainRequests.TryDequeue(
                            _mapEpoch,
                            out requestedGm))
                    {
                        pumped = _controller.EnsureGm(requestedGm);
                    }
                    else
                    {
                        pumped = _controller.PumpOneQueued();
                    }
                    DrainControllerEventsOnMainLocked();
                    if (!string.IsNullOrEmpty(pumped.GroupId))
                    {
                        ProcessEnsureResultOnMainLocked(pumped);
                    }
                });
            }
            catch (Exception exception)
            {
                StopToVanilla("tick_failed: " + Describe(exception), false);
            }
        }

        // Diagnostics added 2026-09-02. Two SHCDE 2.80 editor sessions (the
        // 2-group origins probe and the 152-group canary) captured every
        // baseline but never opened a map epoch: no editor_epoch_fallback, no
        // scene_reset, no group request, while the fortification feature's
        // identical editor predicate did fire in the same frames. The lines
        // below make the gate observable in the game log instead of leaving
        // "no SH1 world art" as the only symptom.
        private void LogFirstTick()
        {
            int current = Thread.CurrentThread.ManagedThreadId;
            int captured = _mainThreadId;
            bool adopted = false;
            if (current != captured)
            {
                _mainThreadId = current;
                adopted = true;
            }
            SafeLog(
                adopted ? _warning : _information,
                "SEDE_RUNTIME_V1|event=asset_stream_tick|status=first"
                + "|ready=" + (Ready ? "true" : "false")
                + "|thread=" + current.ToString(CultureInfo.InvariantCulture)
                + "|captured_thread="
                + captured.ToString(CultureInfo.InvariantCulture)
                + "|adopted=" + (adopted ? "true" : "false"));
        }

        private void LogIdleGateIfStalled()
        {
            bool stalled;
            lock (_gate)
            {
                stalled = _baselineCaptured && !_mapActive;
            }
            if (!stalled)
            {
                _idleGateTicks = 0;
                return;
            }
            _idleGateTicks++;
            if (_idleGateTicks != 600 && _idleGateTicks % 3600 != 0)
            {
                return;
            }
            string viewModelLoaded = "false";
            string editorMode = "n/a";
            string director = "n/a";
            string inEditor = "n/a";
            try
            {
                if (MainViewModel.viewModelLoaded)
                {
                    viewModelLoaded = "true";
                    MainViewModel viewModel = MainViewModel.Instance;
                    editorMode = viewModel == null
                        ? "null"
                        : (viewModel.IsMapEditorMode ? "true" : "false");
                    director = EditorDirector.instance != null
                        ? "present" : "null";
                    inEditor = GamePlayerManagerAPI.Instance.IsInMapEditor()
                        ? "true" : "false";
                }
            }
            catch (Exception exception)
            {
                inEditor = "error:" + exception.GetType().Name;
            }
            string epochBegun;
            string pairsOpen;
            lock (_gate)
            {
                epochBegun = _mapStartGate.EpochBegun ? "true" : "false";
                pairsOpen = _mapStartGate.IgnoreNestedUnload ? "true" : "false";
            }
            SafeLog(
                _information,
                "SEDE_RUNTIME_V1|event=asset_stream_gate|status=idle"
                + "|ticks=" + _idleGateTicks.ToString(CultureInfo.InvariantCulture)
                + "|view_model_loaded=" + viewModelLoaded
                + "|editor_mode=" + editorMode
                + "|editor_director=" + director
                + "|in_map_editor=" + inEditor
                + "|epoch_begun=" + epochBegun
                + "|load_pair_open=" + pairsOpen);
        }

        internal void AdvanceLateFrame()
        {
            if (!Ready || !IsMainThread)
            {
                return;
            }
            try
            {
                _timeline.Execute(delegate
                {
                    DrainQueuedResultsOnMainLocked();
                    _backend.AdvancePendingCleanup();
                    _controller.AdvanceLateFrame();
                    DrainControllerEventsOnMainLocked();
                });
            }
            catch (Exception exception)
            {
                StopToVanilla(
                    "late_frame_failed: " + Describe(exception),
                    false);
            }
        }

        internal void Rollback(bool applicationQuitting)
        {
            StopToVanilla(
                applicationQuitting ? "application_quit" : "rollback",
                applicationQuitting);
        }

        internal static bool AdvanceRetainedLateFrames()
        {
            AssetStreamRuntimeLane[] retained;
            lock (InstallationGate)
            {
                retained = RetainedShutdownLanes.ToArray();
            }
            for (int index = 0; index < retained.Length; index++)
            {
                AssetStreamRuntimeLane lane = retained[index];
                if (lane._retainForApplicationExit)
                {
                    continue;
                }
                if (lane._drainTerminal)
                {
                    continue;
                }
                if (lane.AdvanceShutdownDrain())
                {
                    lock (InstallationGate)
                    {
                        RetainedShutdownLanes.Remove(lane);
                    }
                }
            }
            lock (InstallationGate)
            {
                for (int index = 0; index < RetainedShutdownLanes.Count; index++)
                {
                    if (!RetainedShutdownLanes[index]._retainForApplicationExit)
                    {
                        if (!RetainedShutdownLanes[index]._drainTerminal)
                        {
                            return true;
                        }
                    }
                }
            }
            return false;
        }

        internal static void DrainHostDestroyed(GameObject host)
        {
            lock (InstallationGate)
            {
                if (ReferenceEquals(_drainHostObject, host))
                {
                    _drainHostObject = null;
                }
            }
        }

        private void InstallPatches()
        {
            MethodInfo apply = ResolveApplyRuntimeOverrides();
            MethodInfo gmSprite = ResolveGetGmSprite();
            MethodInfo gmMaterial = ResolveGetGmMaterial();
            MethodInfo sprite = ResolveGetSprite();
            MethodInfo body = ResolveBodyHook();
            MethodInfo toggleFlattened = ResolveToggleFlattenedLandscapeMode();
            MethodInfo setFlattened = ResolveSetFlattenedLandscapeMode();
            _harmony.Patch(
                apply,
                postfix: new HarmonyMethod(RequirePatch(
                    "ApplyRuntimeOverridesPostfix")));
            _harmony.Patch(
                gmSprite,
                prefix: new HarmonyMethod(RequirePatch("GetGmSpritePrefix")));
            _harmony.Patch(
                gmMaterial,
                prefix: new HarmonyMethod(RequirePatch("GetGmMaterialPrefix")));
            _harmony.Patch(
                sprite,
                prefix: new HarmonyMethod(RequirePatch("GetSpritePrefix")));
            _harmony.Patch(
                body,
                postfix: new HarmonyMethod(RequirePatch("BodySpritePostfix")));
            HarmonyMethod flattenedPostfix = new HarmonyMethod(RequirePatch(
                "FlattenedLandscapeStatePostfix"));
            _harmony.Patch(toggleFlattened, postfix: flattenedPostfix);
            _harmony.Patch(setFlattened, postfix: flattenedPostfix);
        }

        private void SubscribeMapLifecycle()
        {
            Observable<MapStartEventArgs> start =
                MapLoaderR3EventHooks.OnStartMap.Observable;
            Observable<MapLoadEventArgs> load =
                MapLoaderR3EventHooks.OnLoadMap.Observable;
            Observable<LoadSaveGameEventArgs> save =
                MapLoaderR3EventHooks.OnLoadSave.Observable;
            Observable<MapUnloadEventArgs> unload =
                MapLoaderR3EventHooks.OnUnloadMap.Observable;
            if (start == null || load == null || save == null || unload == null)
            {
                throw new InvalidOperationException(
                    "SHCDE-SE exposes no exact map lifecycle observable");
            }
            _mapStartSubscription =
                ObservableSubscribeExtensions.Subscribe(start, OnStartMap);
            try
            {
                _mapLoadSubscription =
                    ObservableSubscribeExtensions.Subscribe(load, OnLoadMap);
                _mapSaveSubscription =
                    ObservableSubscribeExtensions.Subscribe(save, OnLoadSave);
                _mapUnloadSubscription =
                    ObservableSubscribeExtensions.Subscribe(unload, OnUnloadMap);
            }
            catch
            {
                DisposeSubscription(_mapStartSubscription);
                DisposeSubscription(_mapLoadSubscription);
                DisposeSubscription(_mapSaveSubscription);
                DisposeSubscription(_mapUnloadSubscription);
                _mapStartSubscription = null;
                _mapLoadSubscription = null;
                _mapSaveSubscription = null;
                _mapUnloadSubscription = null;
                throw;
            }
        }

        private void OnLoadMap(MapLoadEventArgs value)
        {
            if (value != null)
            {
                OnLoadPhase(value.Phase, false);
            }
        }

        private void OnLoadSave(LoadSaveGameEventArgs value)
        {
            if (value != null)
            {
                OnLoadPhase(value.Phase, true);
            }
        }

        private void OnLoadPhase(EventHookPhase phase, bool saveLoad)
        {
            if (!Ready)
            {
                return;
            }
            if (phase == EventHookPhase.Pre)
            {
                AssetStreamMapGateAction action;
                lock (_gate)
                {
                    action = saveLoad
                        ? _mapStartGate.OnSaveLoadPre(_baselineCaptured)
                        : _mapStartGate.OnMapLoadPre(_baselineCaptured);
                }
                HandleMapGateAction(action);
            }
            else if (phase == EventHookPhase.Post)
            {
                lock (_gate)
                {
                    if (saveLoad)
                    {
                        _mapStartGate.OnSaveLoadPost();
                    }
                    else
                    {
                        _mapStartGate.OnMapLoadPost();
                    }
                }
            }
        }

        private void OnStartMap(MapStartEventArgs value)
        {
            if (value == null || !Ready)
            {
                return;
            }
            if (value.Phase == EventHookPhase.Pre)
            {
                AssetStreamMapGateAction action;
                lock (_gate)
                {
                    action = _mapStartGate.OnStartPre(_baselineCaptured);
                }
                // Start PRE is a fallback for flows that expose no Load PRE.
                HandleMapGateAction(action);
            }
            else if (value.Phase == EventHookPhase.Post)
            {
                lock (_gate)
                {
                    // PRE already started (or deliberately stayed vanilla
                    // because baseline capture never completed). POST only
                    // closes the pair and never creates a second epoch.
                    _mapStartGate.OnStartPost();
                }
            }
        }

        private void OnUnloadMap(MapUnloadEventArgs value)
        {
            if (value == null || value.Phase != EventHookPhase.Pre || !Ready)
            {
                return;
            }
            bool nested;
            lock (_gate)
            {
                nested = _mapStartGate.IgnoreNestedUnload;
                if (!nested)
                {
                    _mapStartGate.OnExternalUnload();
                    _editorReadyObserved = false;
                }
            }
            if (!nested)
            {
                EnqueueMapTransition(MapTransition.Unload);
            }
        }

        private void HandleMapGateAction(AssetStreamMapGateAction action)
        {
            if (action == AssetStreamMapGateAction.BeginEpoch)
            {
                EnqueueMapTransition(MapTransition.Start);
            }
            else if (action == AssetStreamMapGateAction.EndOldToVanilla)
            {
                EnqueueMapTransition(MapTransition.Unload);
            }
        }

        private void ObserveEditorReadyGate()
        {
            // Match the already-proven editor gate used by the fortification
            // feature. Accessing MainViewModel.Instance before its loaded flag
            // is unsafe because the constructor still depends on game state.
            bool editorReady = false;
            if (MainViewModel.viewModelLoaded)
            {
                MainViewModel viewModel = MainViewModel.Instance;
                editorReady = viewModel != null
                    && viewModel.IsMapEditorMode
                    && EditorDirector.instance != null
                    && GamePlayerManagerAPI.Instance.IsInMapEditor();
            }

            AssetStreamMapGateAction action = AssetStreamMapGateAction.None;
            bool endEditorEpoch = false;
            string observed = null;
            lock (_gate)
            {
                if (editorReady)
                {
                    if (!_editorReadyObserved)
                    {
                        observed = "SEDE_RUNTIME_V1|event=asset_stream"
                            + "|status=editor_ready_observed"
                            + "|baseline=" + (_baselineCaptured ? "true" : "false")
                            + "|epoch_begun="
                            + (_mapStartGate.EpochBegun ? "true" : "false")
                            + "|map_active=" + (_mapActive ? "true" : "false");
                    }
                    _editorReadyObserved = true;
                    action = _mapStartGate.OnEditorReady(_baselineCaptured);
                }
                else if (_editorReadyObserved)
                {
                    _editorReadyObserved = false;
                    _mapStartGate.OnExternalUnload();
                    endEditorEpoch = true;
                }
            }

            if (observed != null)
            {
                SafeLog(_information, observed);
            }
            if (action == AssetStreamMapGateAction.BeginEpoch)
            {
                SafeLog(
                    _information,
                    "SEDE_RUNTIME_V1|event=asset_stream"
                    + "|status=editor_epoch_fallback");
            }
            HandleMapGateAction(action);
            if (endEditorEpoch)
            {
                EnqueueMapTransition(MapTransition.Unload);
            }
        }

        private void EnqueueMapTransition(MapTransition value)
        {
            lock (_gate)
            {
                if (_stopped)
                {
                    return;
                }
                _mapTransitions.Enqueue(value);
            }
            if (IsMainThread)
            {
                try
                {
                    DrainMapTransitions();
                }
                catch (Exception exception)
                {
                    StopToVanilla(
                        "map_transition_failed: " + Describe(exception),
                        false);
                }
            }
        }

        private void DrainMapTransitions()
        {
            RequireMainThread();
            _timeline.Execute(DrainMapTransitionsOnMainLocked);
        }

        private void DrainMapTransitionsOnMainLocked()
        {
            RequireMainThread();
            _timeline.RequireEntered();
            DrainQueuedResultsOnMainLocked();
            while (true)
            {
                MapTransition transition;
                lock (_gate)
                {
                    if (_mapTransitions.Count == 0)
                    {
                        DrainControllerEventsOnMainLocked();
                        return;
                    }
                    transition = _mapTransitions.Dequeue();
                }
                if (transition == MapTransition.Start)
                {
                    if (_mapActive)
                    {
                        ReleaseBattlementOverlayVariants();
                        NeutralizePageMasksForRelease();
                        FinalizeOffMainRequestsOnMainLocked(_mapEpoch);
                        _controller.EndMapEpoch(_mapEpoch);
                        DrainControllerEventsOnMainLocked();
                        _mapActive = false;
                        LogSceneResetAndSummary(_mapEpoch, "map_to_map");
                    }
                    long nextEpoch = _controller.BeginMapEpoch();
                    Volatile.Write(ref _mapEpoch, nextEpoch);
                    DrainControllerEventsOnMainLocked();
                    _offMainRequests.OpenEpoch(nextEpoch);
                    _mapActive = true;
                    ResetSummary(_mapEpoch);
                }
                else if (_mapActive)
                {
                    ReleaseBattlementOverlayVariants();
                    NeutralizePageMasksForRelease();
                    FinalizeOffMainRequestsOnMainLocked(_mapEpoch);
                    _controller.EndMapEpoch(_mapEpoch);
                    DrainControllerEventsOnMainLocked();
                    _mapActive = false;
                    LogSceneResetAndSummary(_mapEpoch, "map_unload");
                }
            }
        }

        private void CaptureBaseline(spriteLoader loader)
        {
            RequireMainThread();
            lock (_gate)
            {
                if (_baselineCaptureStarted || _stopped)
                {
                    return;
                }
                _baselineCaptureStarted = true;
            }
            int captured = 0;
            AssetStreamLoaderSnapshot central = _surface.Read(loader);
            var frozenAllSprites = new ReadOnlyDictionary<string, Sprite>(
                new Dictionary<string, Sprite>(
                    central.AllSprites,
                    central.AllSprites.Comparer));
            var baselines = new List<KeyValuePair<
                AssetStreamGroupManifest,
                AssetStreamUnityBaseline>>(_manifest.Groups.Count);
            for (int index = 0; index < _manifest.Groups.Count; index++)
            {
                AssetStreamGroupManifest group = _manifest.Groups[index];
                try
                {
                    AssetStreamUnityBaseline baseline =
                        _surface.CaptureBaseline(
                            loader,
                            group,
                            central,
                            frozenAllSprites);
                    _controller.RegisterBaseline(group.Group, baseline);
                    Volatile.Write(ref _gmBaselines[group.GmId], baseline);
                    baselines.Add(new KeyValuePair<
                        AssetStreamGroupManifest,
                        AssetStreamUnityBaseline>(group, baseline));
                    captured++;
                }
                catch (Exception exception)
                {
                    SafeLog(
                        _warning,
                        "SEDE_RUNTIME_V1|event=asset_stream_baseline"
                        + "|status=vanilla|group=" + group.Group
                        + "|reason=" + Describe(exception));
                }
            }
            _frozenAllSprites = frozenAllSprites;
            BuildExactSpriteNameRoutes(baselines, frozenAllSprites);
            Volatile.Write(ref _spriteRoutesPublished, 1);
            _timeline.Execute(DrainControllerEventsOnMainLocked);
            AssetStreamMapGateAction waitingAction;
            lock (_gate)
            {
                _baselineCaptured = true;
                Volatile.Write(ref _anyBaselineCaptured, 1);
                waitingAction = _mapStartGate.OnBaselineCompleted();
            }
            SafeLog(
                _information,
                "SEDE_RUNTIME_V1|event=asset_stream_baseline|status=captured"
                + "|groups=" + captured);
            TextureMemoryInventory.TryCaptureOnce(_information, _warning);
            HandleMapGateAction(waitingAction);
        }

        private void EnsureGm(int gm)
        {
            if (!IsMainThread)
            {
                QueueOffMain(gm, Volatile.Read(ref _mapEpoch));
                return;
            }
            if (!_mapActive)
            {
                TryOpenEpochOnSpriteRequest(gm);
            }
            long observedEpoch = Volatile.Read(ref _mapEpoch);
            if (!Ready
                || !_mapActive
                || gm < 0
                || gm >= _gmFastState.Length
                || !_manifestGms.Contains(gm)
                || Volatile.Read(ref _gmFastState[gm]) != 0)
            {
                return;
            }
            _timeline.Execute(delegate
            {
                if (!Ready
                    || !_mapActive
                    || _mapEpoch != observedEpoch
                    || Volatile.Read(ref _gmFastState[gm]) != 0)
                {
                    return;
                }
                AssetStreamEnsureResult result = _controller.EnsureGm(gm);
                DrainControllerEventsOnMainLocked();
                ProcessEnsureResultOnMainLocked(result);
            });
        }

        // 2026-09-02: three SHCDE 2.80 editor sessions rooted every baseline
        // but never opened an epoch through Load/Start PRE or the editor-ready
        // predicate, so no group was ever requested and the world stayed
        // Crusader. A GM sprite request is only made while a map is drawn;
        // after the baselines exist it is therefore a sufficient map boundary.
        // The cursor group is excluded because the menus draw it too.
        private void TryOpenEpochOnSpriteRequest(int gm)
        {
            string group;
            if (gm < 0
                || gm >= _gmGroups.Length
                || (group = _gmGroups[gm]) == null
                || string.Equals(group, "cursors", StringComparison.Ordinal))
            {
                return;
            }
            AssetStreamMapGateAction action;
            lock (_gate)
            {
                if (_stopped || _mapActive || !_baselineCaptured)
                {
                    return;
                }
                action = _mapStartGate.OnSpriteRequest(_baselineCaptured);
            }
            if (action != AssetStreamMapGateAction.BeginEpoch)
            {
                return;
            }
            SafeLog(
                _information,
                "SEDE_RUNTIME_V1|event=asset_stream"
                + "|status=sprite_request_epoch_fallback"
                + "|group=" + group);
            HandleMapGateAction(action);
        }

        private void EnsureSpriteName(string name)
        {
            if (!IsMainThread)
            {
                string requestedGroup;
                int requestedGm;
                if (!string.IsNullOrEmpty(name)
                    && Volatile.Read(ref _spriteRoutesPublished) != 0
                    && _spriteNameGroups.TryGetValue(name, out requestedGroup)
                    && _groupGms.TryGetValue(requestedGroup, out requestedGm))
                {
                    QueueOffMain(
                        requestedGm,
                        Volatile.Read(ref _mapEpoch));
                }
                return;
            }
            long observedEpoch = Volatile.Read(ref _mapEpoch);
            if (!Ready
                || !_mapActive
                || string.IsNullOrEmpty(name)
                || Volatile.Read(ref _spriteRoutesPublished) == 0)
            {
                return;
            }
            string group;
            if (!_spriteNameGroups.TryGetValue(name, out group))
            {
                return;
            }
            int gm;
            if (!_groupGms.TryGetValue(group, out gm)
                || Volatile.Read(ref _gmFastState[gm]) != 0)
            {
                return;
            }
            _timeline.Execute(delegate
            {
                if (!Ready
                    || !_mapActive
                    || _mapEpoch != observedEpoch
                    || Volatile.Read(ref _gmFastState[gm]) != 0)
                {
                    return;
                }
                AssetStreamEnsureResult result = _controller.EnsureGroup(group);
                DrainControllerEventsOnMainLocked();
                ProcessEnsureResultOnMainLocked(result);
            });
        }

        private bool TryGetBattlementOverlaySprite(
            spriteLoader loader,
            int gm,
            int imageId,
            bool altFrame,
            bool flattenedLandscape,
            out Sprite result)
        {
            result = null;
            if (gm != BattlementOverlayAnchor.CastleAnimationsGm || altFrame)
            {
                return false;
            }

            AssetStreamLoaderSnapshot central = _surface.Read(loader);
            if (gm < 0 || gm >= central.GmSprites.Length)
            {
                return false;
            }
            Sprite[] group = central.GmSprites[gm];
            if (group == null || imageId < 0 || imageId >= group.Length)
            {
                return false;
            }
            Sprite source = group[imageId];
            if (source == null)
            {
                return false;
            }

            Rect rect = source.rect;
            float desiredPivotY;
            float flattenedPivotY;
            if (!BattlementOverlayAnchor.TryResolvePivotY(
                    gm,
                    imageId,
                    altFrame,
                    rect.height,
                    flattenedLandscape,
                    out desiredPivotY)
                || !BattlementOverlayAnchor.TryResolvePivotY(
                    gm,
                    imageId,
                    altFrame,
                    rect.height,
                    true,
                    out flattenedPivotY))
            {
                return false;
            }

            // The published atlas sprite is deliberately the ground-anchored
            // variant. Refuse an unexpected asset generation instead of
            // applying measurements made for the reviewed SH1DE canvases.
            if (Math.Abs(
                    source.pivot.y - flattenedPivotY * rect.height)
                > BattlementPivotTolerancePixels)
            {
                return false;
            }
            if (flattenedLandscape)
            {
                result = source;
                return true;
            }
            if (rect.width <= 0f || source.texture == null)
            {
                return false;
            }

            BattlementOverlayVariant cached;
            if (_battlementOverlayVariants.TryGetValue(imageId, out cached)
                && ReferenceEquals(cached.Source, source)
                && cached.TopAligned != null)
            {
                result = cached.TopAligned;
                return true;
            }

            Sprite topAligned = Sprite.Create(
                source.texture,
                rect,
                new Vector2(source.pivot.x / rect.width, desiredPivotY),
                source.pixelsPerUnit,
                0,
                SpriteMeshType.FullRect,
                source.border,
                false);
            if (topAligned == null)
            {
                throw new InvalidOperationException(
                    "Sprite.Create returned no battlement overlay variant");
            }
            topAligned.name = source.name;
            if (Math.Abs(topAligned.pivot.y - rect.height)
                > BattlementPivotTolerancePixels)
            {
                UnityEngine.Object.Destroy(topAligned);
                throw new InvalidOperationException(
                    "Unity did not preserve the top-aligned battlement pivot");
            }

            var replacement = new BattlementOverlayVariant(
                imageId,
                source,
                topAligned);
            if (cached != null)
            {
                try
                {
                    RebindBattlementRendererReferences(
                        imageId,
                        cached.TopAligned,
                        topAligned);
                }
                catch
                {
                    UnityEngine.Object.Destroy(topAligned);
                    throw;
                }
                _battlementOverlayVariants[imageId] = replacement;
                if (cached.TopAligned != null)
                {
                    UnityEngine.Object.Destroy(cached.TopAligned);
                }
            }
            else
            {
                _battlementOverlayVariants.Add(imageId, replacement);
            }
            result = topAligned;
            return true;
        }

        private void RefreshBattlementRenderers()
        {
            RequireMainThread();
            if (!_mapActive)
            {
                return;
            }
            spriteLoader loader = spriteLoader.instance;
            GameMap map = GameMap.instance;
            if (loader == null || map == null)
            {
                return;
            }

            EnsureGm(BattlementOverlayAnchor.CastleAnimationsGm);
            Dictionary<int, WallFillin> wallFillins = ReadWallFillins(map);
            var wallFillinSnapshot = new WallFillin[wallFillins.Count];
            wallFillins.Values.CopyTo(wallFillinSnapshot, 0);
            Dictionary<int, BuildingAnim> buildingAnims =
                ReadBuildingAnims(map);
            var buildingAnimSnapshot = new BuildingAnim[buildingAnims.Count];
            buildingAnims.Values.CopyTo(buildingAnimSnapshot, 0);
            bool flattened = EngineInterface.FlattenedLandscape;
            for (int index = 0; index < wallFillinSnapshot.Length; index++)
            {
                WallFillin wallFillin = wallFillinSnapshot[index];
                if (wallFillin == null || wallFillin.sprRenderer == null)
                {
                    continue;
                }
                Sprite sprite;
                if (TryGetBattlementOverlaySprite(
                        loader,
                        BattlementOverlayAnchor.CastleAnimationsGm,
                        wallFillin.state,
                        false,
                        flattened,
                        out sprite))
                {
                    wallFillin.sprRenderer.sprite = sprite;
                }
            }
            for (int index = 0; index < buildingAnimSnapshot.Length; index++)
            {
                BuildingAnim buildingAnim = buildingAnimSnapshot[index];
                if (buildingAnim == null
                    || buildingAnim.type
                        != BattlementOverlayAnchor.CastleAnimationsGm
                    || buildingAnim.sprRenderer == null)
                {
                    continue;
                }
                Sprite sprite;
                if (TryGetBattlementOverlaySprite(
                        loader,
                        buildingAnim.type,
                        buildingAnim.state,
                        false,
                        flattened,
                        out sprite))
                {
                    buildingAnim.sprRenderer.sprite = sprite;
                }
            }
        }

        private Dictionary<int, BuildingAnim> ReadBuildingAnims(GameMap map)
        {
            if (map.GetType() != typeof(GameMap))
            {
                throw new InvalidOperationException(
                    "Runtime GameMap instance is not the exact reviewed type");
            }
            var value = _buildingAnimsField.GetValue(map)
                as Dictionary<int, BuildingAnim>;
            if (value == null)
            {
                throw new InvalidOperationException(
                    "GameMap.buildingAnims is unavailable");
            }
            return value;
        }

        private Dictionary<int, WallFillin> ReadWallFillins(GameMap map)
        {
            if (map.GetType() != typeof(GameMap))
            {
                throw new InvalidOperationException(
                    "Runtime GameMap instance is not the exact reviewed type");
            }
            var value = _wallFillinsField.GetValue(map)
                as Dictionary<int, WallFillin>;
            if (value == null)
            {
                throw new InvalidOperationException(
                    "GameMap.wallFillins is unavailable");
            }
            return value;
        }

        private void RebindBattlementRendererReferences(
            int imageId,
            Sprite expected,
            Sprite replacement)
        {
            if (expected == null || replacement == null)
            {
                return;
            }
            GameMap map = GameMap.instance;
            if (map == null)
            {
                return;
            }
            Dictionary<int, WallFillin> wallFillins = ReadWallFillins(map);
            foreach (WallFillin wallFillin in wallFillins.Values)
            {
                if (wallFillin != null
                    && wallFillin.state == imageId
                    && wallFillin.sprRenderer != null
                    && ReferenceEquals(
                        wallFillin.sprRenderer.sprite,
                        expected))
                {
                    wallFillin.sprRenderer.sprite = replacement;
                }
            }
            Dictionary<int, BuildingAnim> buildingAnims =
                ReadBuildingAnims(map);
            foreach (BuildingAnim buildingAnim in buildingAnims.Values)
            {
                if (buildingAnim != null
                    && buildingAnim.type
                        == BattlementOverlayAnchor.CastleAnimationsGm
                    && buildingAnim.state == imageId
                    && buildingAnim.sprRenderer != null
                    && ReferenceEquals(
                        buildingAnim.sprRenderer.sprite,
                        expected))
                {
                    buildingAnim.sprRenderer.sprite = replacement;
                }
            }
        }

        private void ReleaseBattlementOverlayVariants()
        {
            RequireMainThread();
            if (_battlementOverlayVariants.Count == 0)
            {
                return;
            }

            GameMap map = GameMap.instance;
            if (map != null)
            {
                Dictionary<int, WallFillin> wallFillins = ReadWallFillins(map);
                foreach (WallFillin wallFillin in wallFillins.Values)
                {
                    if (wallFillin == null || wallFillin.sprRenderer == null)
                    {
                        continue;
                    }
                    BattlementOverlayVariant variant;
                    if (_battlementOverlayVariants.TryGetValue(
                            wallFillin.state,
                            out variant)
                        && ReferenceEquals(
                            wallFillin.sprRenderer.sprite,
                            variant.TopAligned))
                    {
                        wallFillin.sprRenderer.sprite = variant.Source;
                    }
                }
                Dictionary<int, BuildingAnim> buildingAnims =
                    ReadBuildingAnims(map);
                foreach (BuildingAnim buildingAnim in buildingAnims.Values)
                {
                    if (buildingAnim == null
                        || buildingAnim.type
                            != BattlementOverlayAnchor.CastleAnimationsGm
                        || buildingAnim.sprRenderer == null)
                    {
                        continue;
                    }
                    BattlementOverlayVariant variant;
                    if (_battlementOverlayVariants.TryGetValue(
                            buildingAnim.state,
                            out variant)
                        && ReferenceEquals(
                            buildingAnim.sprRenderer.sprite,
                            variant.TopAligned))
                    {
                        buildingAnim.sprRenderer.sprite = variant.Source;
                    }
                }
            }

            BattlementOverlayVariant[] owned =
                new BattlementOverlayVariant[_battlementOverlayVariants.Count];
            _battlementOverlayVariants.Values.CopyTo(owned, 0);
            _battlementOverlayVariants.Clear();
            for (int index = 0; index < owned.Length; index++)
            {
                if (owned[index].TopAligned != null)
                {
                    UnityEngine.Object.Destroy(owned[index].TopAligned);
                }
            }
        }

        private void WarnBattlementOverlayFailure(string reason)
        {
            if (_battlementOverlayFailureLogged)
            {
                return;
            }
            _battlementOverlayFailureLogged = true;
            SafeLog(
                _warning,
                "SEDE_RUNTIME_V1|event=battlement_overlay|status=vanilla"
                + "|reason=" + AssetStreamText.Sanitize(reason, 180));
        }

        private void QueueOffMain(int gm, long epoch)
        {
            if (!FastReady
                || !_mapActive
                || gm < 0
                || gm >= _gmFastState.Length
                || Volatile.Read(ref _gmFastState[gm]) != 0)
            {
                return;
            }
            _offMainRequests.TryEnqueue(gm, epoch);
        }

        private bool TryGetOffMainGmSprite(
            int gm,
            int imageId,
            bool altFrame,
            out Sprite result)
        {
            result = null;
            long epoch = Volatile.Read(ref _mapEpoch);
            if (!FastReady
                || !_mapActive
                || gm < 0
                || gm >= _gmBaselines.Length)
            {
                return false;
            }
            AssetStreamUnityBaseline baseline = Volatile.Read(
                ref _gmBaselines[gm]);
            if (baseline == null
                || epoch != Volatile.Read(ref _mapEpoch)
                || !_mapActive
                || !baseline.TryGetFrozenSprite(
                    imageId,
                    altFrame,
                    out result))
            {
                return false;
            }
            QueueOffMain(gm, epoch);
            return true;
        }

        private bool TryGetOffMainNamedSprite(
            string name,
            out Sprite result)
        {
            result = null;
            long epoch = Volatile.Read(ref _mapEpoch);
            if (!FastReady
                || !_mapActive
                || string.IsNullOrEmpty(name)
                || Volatile.Read(ref _spriteRoutesPublished) == 0)
            {
                return false;
            }
            string group;
            int gm;
            ReadOnlyDictionary<string, Sprite> frozen = _frozenAllSprites;
            if (frozen == null
                || !_spriteNameGroups.TryGetValue(name, out group)
                || !_groupGms.TryGetValue(group, out gm)
                || epoch != Volatile.Read(ref _mapEpoch)
                || !_mapActive)
            {
                return false;
            }
            frozen.TryGetValue(name, out result);
            QueueOffMain(gm, epoch);
            return true;
        }

        private bool TryGetOffMainGmMaterial(
            int gm,
            int colourOffset,
            int chopFeet,
            int transparency,
            out Color outputColour,
            out Material result)
        {
            outputColour = Color.white;
            result = null;
            long epoch = Volatile.Read(ref _mapEpoch);
            if (!FastReady
                || !_mapActive
                || gm < 0
                || gm >= _gmBaselines.Length)
            {
                return false;
            }
            AssetStreamUnityBaseline baseline = Volatile.Read(
                ref _gmBaselines[gm]);
            if (baseline == null
                || epoch != Volatile.Read(ref _mapEpoch)
                || !_mapActive
                || !baseline.TryGetFrozenMaterial(
                    colourOffset,
                    chopFeet,
                    transparency,
                    out outputColour,
                    out result))
            {
                return false;
            }
            QueueOffMain(gm, epoch);
            return true;
        }

        private void DrainQueuedResultsOnMainLocked()
        {
            RequireMainThread();
            _timeline.RequireEntered();
            DrainControllerEventsOnMainLocked();
            _timeline.DrainResultsLocked(ProcessEnsureResultOnMainLocked);
        }

        private void FinalizeOffMainRequestsOnMainLocked(long epoch)
        {
            RequireMainThread();
            _timeline.RequireEntered();
            IList<int> queued = _offMainRequests.CloseEpochAndDrain(epoch);
            for (int index = 0; index < queued.Count; index++)
            {
                int gm = queued[index];
                string group = gm >= 0 && gm < _gmGroups.Length
                    ? _gmGroups[gm]
                    : null;
                if (string.IsNullOrEmpty(group))
                {
                    continue;
                }
                string terminalKey = epoch.ToString(CultureInfo.InvariantCulture)
                    + "\t" + group;
                if (_terminalGroupEpochs.Contains(terminalKey)
                    || _pendingGroups.ContainsKey(group))
                {
                    continue;
                }
                // The worker already received the frozen baseline. Complete
                // that accepted request as exactly one fallback before the
                // epoch summary instead of silently discarding it next map.
                _pendingGroups.Add(group, "queued");
            }
        }

        private void DrainControllerEventsOnMainLocked()
        {
            RequireMainThread();
            _timeline.RequireEntered();
            _controllerEvents.Drain();
        }

        private void ProcessEnsureResultOnMainLocked(AssetStreamEnsureResult result)
        {
            RequireMainThread();
            _timeline.RequireEntered();
            if (!_mapActive || result.Epoch != _mapEpoch)
            {
                return;
            }
            string key = result.Epoch.ToString(CultureInfo.InvariantCulture)
                + "\t" + result.GroupId;
            // Must be initialised: && short-circuits when GroupId is empty, so
            // TryGetValue never runs on that path and gm would be unassigned.
            // Every read below is guarded by hasGm, so the value is never used.
            int gm = 0;
            bool hasGm = !string.IsNullOrEmpty(result.GroupId)
                && _groupGms.TryGetValue(result.GroupId, out gm);
            bool terminal = result.IsLoaded
                || result.Disposition == AssetStreamEnsureDisposition.BudgetFallback
                || result.Disposition == AssetStreamEnsureDisposition.FailureFallback
                || result.Disposition == AssetStreamEnsureDisposition.UnknownGroupFallback
                || (result.Disposition == AssetStreamEnsureDisposition.BaselineFallback
                    && _baselineCaptured);
            bool retryableFailure = false;
            if (hasGm
                && result.Disposition == AssetStreamEnsureDisposition.FailureFallback
                && IsRetryableFailure(result.GroupId))
            {
                retryableFailure = true;
                terminal = false;
            }
            PublishFastStateLocked(result);
            if (terminal && hasGm)
            {
                _retryPlans.Remove(gm);
            }
            if (!terminal)
            {
                string pendingReason = EnsureReason(result.Disposition);
                if (hasGm
                    && (ShouldRetryDisposition(result.Disposition) ||
                        (retryableFailure
                            && result.Disposition
                                == AssetStreamEnsureDisposition.FailureFallback)))
                {
                    ScheduleRetry(gm, result.GroupId, pendingReason);
                }
                if (!_pendingGroups.ContainsKey(result.GroupId))
                {
                    _pendingGroups.Add(result.GroupId, pendingReason);
                    SafeLog(
                        _information,
                        "SEDE_RUNTIME_V1|event=asset_stream_group|status=pending"
                        + "|group=" + AssetStreamText.Sanitize(result.GroupId, 96)
                        + "|epoch=" + result.Epoch.ToString(CultureInfo.InvariantCulture)
                        + "|reason=" + pendingReason);
                }
                else
                {
                    _pendingGroups[result.GroupId] = pendingReason;
                }
                return;
            }
            if (!_terminalGroupEpochs.Add(key))
            {
                return;
            }
            _pendingGroups.Remove(result.GroupId);
            _requestedGroups++;
            string status;
            string reason;
            if (result.IsLoaded)
            {
                status = "group_loaded";
                reason = "loaded";
                _loadedGroups++;
            }
            else if (result.Disposition == AssetStreamEnsureDisposition.BudgetFallback)
            {
                status = "group_fallback";
                reason = "budget_denied";
                _budgetDeniedGroups++;
                _fallbackGroups++;
            }
            else
            {
                status = "group_fallback";
                reason = EnsureReason(result.Disposition);
                _fallbackGroups++;
            }
            LogGroupTerminal(
                status,
                result.GroupId,
                result.Epoch,
                reason);
        }

        private void PublishFastStateLocked(AssetStreamEnsureResult result)
        {
            _timeline.RequireEntered();
            int gm;
            if (!_groupGms.TryGetValue(result.GroupId, out gm))
            {
                return;
            }
            bool terminal = result.IsLoaded
                || result.Disposition == AssetStreamEnsureDisposition.BudgetFallback
                || result.Disposition == AssetStreamEnsureDisposition.FailureFallback
                || result.Disposition == AssetStreamEnsureDisposition.UnknownGroupFallback
                || (result.Disposition == AssetStreamEnsureDisposition.BaselineFallback
                    && _baselineCaptured);
            if (terminal)
            {
                Volatile.Write(
                    ref _gmFastState[gm],
                    result.IsLoaded ? 1 : 2);
            }
            else if (result.Disposition
                    == AssetStreamEnsureDisposition.QueuedFallback
                || result.Disposition
                    == AssetStreamEnsureDisposition.LoadingFallback
                || result.Disposition
                    == AssetStreamEnsureDisposition.ReleasePendingFallback)
            {
                Volatile.Write(ref _gmFastState[gm], 3);
            }
        }

        private void ResetSummary(long epoch)
        {
            RequireMainThread();
            _timeline.RequireEntered();
            Array.Clear(_gmFastState, 0, _gmFastState.Length);
            _summaryEpoch = epoch;
            _requestedGroups = 0;
            _loadedGroups = 0;
            _fallbackGroups = 0;
            _budgetDeniedGroups = 0;
            _telemetrySamples = 0;
            _maximumPrivateBytes = 0;
            _minimumAvailableCommitBytes = long.MaxValue;
            _minimumAvailablePhysicalBytes = long.MaxValue;
            _maximumCommittedGmBytes = 0;
            _maximumUiBytes = 0;
            _maximumAudioBytes = 0;
            _hasPrivateBytes = false;
            _hasAvailableCommitBytes = false;
            _hasAvailablePhysicalBytes = false;
            _hasCommittedGmBytes = false;
            _hasUiBytes = false;
            _hasAudioBytes = false;
            _pendingGroups.Clear();
            _retryPlans.Clear();
            _maskRouteProbe.Reset(epoch);
        }

        private void LogSceneResetAndSummary(long epoch, string reason)
        {
            RequireMainThread();
            _timeline.RequireEntered();
            if (!_summarizedEpochs.Add(epoch))
            {
                return;
            }
            FinalizePendingGroups(epoch);
            _retryPlans.Clear();
            SafeLog(
                _information,
                "SEDE_RUNTIME_V1|event=asset_stream|status=scene_reset"
                + "|epoch=" + epoch.ToString(CultureInfo.InvariantCulture)
                + "|reason=" + reason);
            int requested = _summaryEpoch == epoch ? _requestedGroups : 0;
            int loaded = _summaryEpoch == epoch ? _loadedGroups : 0;
            int fallback = _summaryEpoch == epoch ? _fallbackGroups : 0;
            int budget = _summaryEpoch == epoch ? _budgetDeniedGroups : 0;
            SafeLog(
                _information,
                "SEDE_RUNTIME_V1|event=asset_stream_summary|status=complete"
                + "|epoch=" + epoch.ToString(CultureInfo.InvariantCulture)
                + "|requested=" + requested.ToString(CultureInfo.InvariantCulture)
                + "|loaded=" + loaded.ToString(CultureInfo.InvariantCulture)
                + "|fallback=" + fallback.ToString(CultureInfo.InvariantCulture)
                + "|budget_denied=" + budget.ToString(CultureInfo.InvariantCulture)
                + "|memory_samples=" + _telemetrySamples.ToString(CultureInfo.InvariantCulture)
                + "|max_private_bytes=" + SummaryValue(
                    _maximumPrivateBytes,
                    _hasPrivateBytes)
                + "|min_available_commit_bytes=" + SummaryValue(
                    _minimumAvailableCommitBytes,
                    _hasAvailableCommitBytes)
                + "|page_mask_runs=" + _neutralizeRuns.ToString(
                    CultureInfo.InvariantCulture)
                + "|page_mask_tracked=" + _neutralizeTracked.ToString(
                    CultureInfo.InvariantCulture)
                + "|page_mask_neutralized=" + _neutralizeNeutralized.ToString(
                    CultureInfo.InvariantCulture)
                + "|page_mask_blocked=" + _neutralizeBlocked.ToString(
                    CultureInfo.InvariantCulture)
                + "|page_mask_failures=" + _neutralizeFailures.ToString(
                    CultureInfo.InvariantCulture)
                + "|route_conflicts=" + Volatile.Read(ref _routeConflicts)
                    .ToString(CultureInfo.InvariantCulture)
                + "|mask_route_events=" + _maskRouteProbe.Events.ToString(
                    CultureInfo.InvariantCulture)
                + "|mask_route_corrections=" + _maskRouteProbe.Corrections.ToString(
                    CultureInfo.InvariantCulture)
                + "|mask_route_postfix_mismatches="
                    + _maskRouteProbe.PostfixMismatches.ToString(
                        CultureInfo.InvariantCulture)
                + "|mask_route_logs_dropped=" + _maskRouteProbe.Dropped.ToString(
                    CultureInfo.InvariantCulture)
                + "|min_available_physical_bytes=" + SummaryValue(
                    _minimumAvailablePhysicalBytes,
                    _hasAvailablePhysicalBytes)
                + "|max_gm_resident_bytes=" + SummaryValue(
                    _maximumCommittedGmBytes,
                    _hasCommittedGmBytes)
                + "|max_ui_resident_bytes=" + SummaryValue(
                    _maximumUiBytes,
                    _hasUiBytes)
                + "|max_audio_stream_bytes=" + SummaryValue(
                    _maximumAudioBytes,
                    _hasAudioBytes));
        }

        private void FinalizePendingGroups(long epoch)
        {
            RequireMainThread();
            _timeline.RequireEntered();
            if (_summaryEpoch != epoch || _pendingGroups.Count == 0)
            {
                return;
            }
            var pending = new List<KeyValuePair<string, string>>(_pendingGroups);
            _pendingGroups.Clear();
            for (int index = 0; index < pending.Count; index++)
            {
                string key = epoch.ToString(CultureInfo.InvariantCulture)
                    + "\t" + pending[index].Key;
                if (!_terminalGroupEpochs.Add(key))
                {
                    continue;
                }
                _requestedGroups++;
                _fallbackGroups++;
                LogGroupTerminal(
                    "group_fallback",
                    pending[index].Key,
                    epoch,
                    pending[index].Value);
            }
        }

        private void LogGroupTerminal(
            string eventName,
            string groupId,
            long epoch,
            string reason)
        {
            AssetStreamResourceTelemetry telemetry = _budget.CaptureTelemetry();
            UpdateTelemetrySummary(telemetry);
            AssetStreamGroupManifest group;
            long charge = -1;
            long peak = -1;
            if (_groupsById.TryGetValue(groupId, out group))
            {
                charge = group.ResidentChargeBytes;
                peak = group.PredictedLoadPeakBytes;
            }
            bool loaded = string.Equals(
                eventName,
                "group_loaded",
                StringComparison.Ordinal);
            SafeLog(
                loaded ? _information : _warning,
                "SEDE_RUNTIME_V1|event=" + eventName
                + "|group=" + AssetStreamText.Sanitize(groupId, 96)
                + "|epoch=" + epoch.ToString(CultureInfo.InvariantCulture)
                + "|reason=" + AssetStreamText.Sanitize(reason, 96)
                + "|resident_charge_bytes=" + Number(charge)
                + "|predicted_load_peak_bytes=" + Number(peak)
                + "|gm_resident_bytes=" + Number(telemetry.CommittedGmBytes)
                + "|ui_resident_bytes=" + NullableNumber(telemetry.UiBytes)
                + "|audio_stream_bytes=" + NullableNumber(telemetry.AudioBytes)
                + "|process_private_bytes=" + NullableNumber(telemetry.PrivateBytes)
                + "|available_commit_bytes=" + NullableNumber(
                    telemetry.AvailableCommitBytes)
                + "|available_physical_bytes=" + NullableNumber(
                    telemetry.AvailablePhysicalBytes)
                + "|memory_status=" + (telemetry.Complete
                    ? "complete"
                    : "unavailable"));
        }

        private void UpdateTelemetrySummary(AssetStreamResourceTelemetry value)
        {
            if (value == null)
            {
                return;
            }
            _telemetrySamples++;
            _maximumCommittedGmBytes = Math.Max(
                _maximumCommittedGmBytes,
                value.CommittedGmBytes);
            _hasCommittedGmBytes = true;
            if (value.UiBytes.HasValue)
            {
                _maximumUiBytes = Math.Max(_maximumUiBytes, value.UiBytes.Value);
                _hasUiBytes = true;
            }
            if (value.AudioBytes.HasValue)
            {
                _maximumAudioBytes = Math.Max(
                    _maximumAudioBytes,
                    value.AudioBytes.Value);
                _hasAudioBytes = true;
            }
            if (value.PrivateBytes.HasValue)
            {
                _maximumPrivateBytes = Math.Max(
                    _maximumPrivateBytes,
                    value.PrivateBytes.Value);
                _hasPrivateBytes = true;
            }
            if (value.AvailableCommitBytes.HasValue)
            {
                _minimumAvailableCommitBytes = Math.Min(
                    _minimumAvailableCommitBytes,
                    value.AvailableCommitBytes.Value);
                _hasAvailableCommitBytes = true;
            }
            if (value.AvailablePhysicalBytes.HasValue)
            {
                _minimumAvailablePhysicalBytes = Math.Min(
                    _minimumAvailablePhysicalBytes,
                    value.AvailablePhysicalBytes.Value);
                _hasAvailablePhysicalBytes = true;
            }
        }

        private static string Number(long value)
        {
            return value.ToString(CultureInfo.InvariantCulture);
        }

        private static string NullableNumber(long? value)
        {
            return value.HasValue ? Number(value.Value) : "-1";
        }

        private static string SummaryValue(long value, bool available)
        {
            return available ? Number(value) : "-1";
        }

        private static string EnsureReason(AssetStreamEnsureDisposition value)
        {
            switch (value)
            {
                case AssetStreamEnsureDisposition.QueuedFallback:
                    return "queued";
                case AssetStreamEnsureDisposition.BaselineFallback:
                    return "baseline_unavailable";
                case AssetStreamEnsureDisposition.LoadingFallback:
                    return "load_in_progress";
                case AssetStreamEnsureDisposition.ReleasePendingFallback:
                    return "release_pending";
                case AssetStreamEnsureDisposition.FailureFallback:
                    return "load_failed";
                case AssetStreamEnsureDisposition.UnknownGroupFallback:
                    return "unknown_group";
                case AssetStreamEnsureDisposition.ShutdownFallback:
                    return "shutdown";
                case AssetStreamEnsureDisposition.NoMapFallback:
                    return "no_map";
                default:
                    return "vanilla";
            }
        }

        private static bool ShouldRetryDisposition(
            AssetStreamEnsureDisposition disposition)
        {
            return disposition == AssetStreamEnsureDisposition.QueuedFallback
                || disposition == AssetStreamEnsureDisposition.LoadingFallback
                || disposition == AssetStreamEnsureDisposition.ReleasePendingFallback
                || disposition == AssetStreamEnsureDisposition.BaselineFallback;
        }

        private bool IsRetryableFailure(string groupId)
        {
            try
            {
                AssetStreamGroupSnapshot snapshot = _controller.Snapshot(groupId);
                return snapshot.State == AssetStreamGroupState.Failed
                    && !snapshot.PermanentTerminal;
            }
            catch
            {
                return false;
            }
        }

        private bool TryPumpRetry(out AssetStreamEnsureResult result)
        {
            result = new AssetStreamEnsureResult(
                AssetStreamEnsureDisposition.BaselineFallback,
                AssetStreamGroupState.Unloaded,
                string.Empty,
                0,
                string.Empty);
            if (!_mapActive || _retryPlans.Count == 0)
            {
                return false;
            }
            int now = Time.frameCount;
            int dueGm = -1;
            int bestDue = int.MaxValue;
            foreach (KeyValuePair<int, AssetStreamRetryPlan> pair in _retryPlans)
            {
                if (pair.Value == null || pair.Value.NextRetryFrame > now)
                {
                    continue;
                }
                if (pair.Value.NextRetryFrame < bestDue)
                {
                    dueGm = pair.Key;
                    bestDue = pair.Value.NextRetryFrame;
                }
            }
            if (dueGm < 0)
            {
                return false;
            }
            _retryPlans.Remove(dueGm);
            result = _controller.EnsureGm(dueGm);
            return true;
        }

        private void ScheduleRetry(
            int gm,
            string groupId,
            string reason)
        {
            if (!_mapActive
                || gm < 0
                || gm >= _gmFastState.Length)
            {
                return;
            }

            AssetStreamRetryPlan plan;
            if (!_retryPlans.TryGetValue(gm, out plan))
            {
                plan = new AssetStreamRetryPlan();
                _retryPlans.Add(gm, plan);
            }
            if (plan.Attempts >= MaximumTransientRetries)
            {
                _retryPlans.Remove(gm);
                SafeLog(
                    _warning,
                    "SEDE_RUNTIME_V1|event=asset_stream_group|status=retry_exhausted"
                    + "|group=" + AssetStreamText.Sanitize(groupId, 96)
                    + "|gm=" + gm.ToString(CultureInfo.InvariantCulture)
                    + "|attempts=" + (plan.Attempts + 1).ToString(
                        CultureInfo.InvariantCulture)
                    + "|reason=" + AssetStreamText.Sanitize(reason, 64));
                return;
            }
            plan.Attempts++;
            plan.NextRetryFrame = checked(
                Time.frameCount + ComputeRetryDelay(plan.Attempts));
            plan.Reason = reason;
            SafeLog(
                _information,
                "SEDE_RUNTIME_V1|event=asset_stream_group|status=retry_scheduled"
                + "|group=" + AssetStreamText.Sanitize(groupId, 96)
                + "|gm=" + gm.ToString(CultureInfo.InvariantCulture)
                + "|attempt=" + plan.Attempts.ToString(CultureInfo.InvariantCulture)
                + "|reason=" + AssetStreamText.Sanitize(reason, 64)
                + "|frame=" + plan.NextRetryFrame.ToString(
                    CultureInfo.InvariantCulture));
        }

        private int ComputeRetryDelay(int attempt)
        {
            if (attempt <= 0)
            {
                return RetryDelayBaseFrames;
            }
            int scale = 1 << Math.Min(4, attempt - 1);
            return Math.Min(RetryDelayMaxFrames, RetryDelayBaseFrames * scale);
        }

        private sealed class AssetStreamRetryPlan
        {
            internal int Attempts;
            internal int NextRetryFrame;
            internal string Reason;
        }

        private void BuildExactSpriteNameRoutes(
            IList<KeyValuePair<AssetStreamGroupManifest,
                AssetStreamUnityBaseline>> baselines,
            IDictionary<string, Sprite> allSprites)
        {
            var spriteOwners = new Dictionary<Sprite, string>(
                AssetStreamReferenceComparer<Sprite>.Instance);
            var ambiguousSprites = new HashSet<Sprite>(
                AssetStreamReferenceComparer<Sprite>.Instance);
            for (int index = 0; index < baselines.Count; index++)
            {
                string group = baselines[index].Key.Group;
                AddSpriteOwners(
                    baselines[index].Value.FrozenGroupSprites,
                    group,
                    spriteOwners,
                    ambiguousSprites);
                AddSpriteOwners(
                    baselines[index].Value.FrozenGroupAltSprites,
                    group,
                    spriteOwners,
                    ambiguousSprites);
            }

            var ambiguousNames = new HashSet<string>(StringComparer.Ordinal);
            foreach (KeyValuePair<string, Sprite> pair in allSprites)
            {
                string group;
                if (!ReferenceEquals(pair.Value, null)
                    && !ambiguousSprites.Contains(pair.Value)
                    && spriteOwners.TryGetValue(pair.Value, out group))
                {
                    AddNameRoute(
                        pair.Key,
                        group,
                        _spriteNameGroups,
                        ambiguousNames);
                }
            }
            foreach (KeyValuePair<Sprite, string> pair in spriteOwners)
            {
                Sprite sprite = pair.Key;
                if (!ambiguousSprites.Contains(sprite)
                    && sprite != null
                    && !string.IsNullOrEmpty(sprite.name))
                {
                    AddNameRoute(
                        sprite.name,
                        pair.Value,
                        _spriteNameGroups,
                        ambiguousNames);
                }
            }
        }

        private static void AddSpriteOwners(
            Sprite[] sprites,
            string group,
            Dictionary<Sprite, string> owners,
            HashSet<Sprite> ambiguous)
        {
            if (sprites == null) return;
            for (int index = 0; index < sprites.Length; index++)
            {
                Sprite sprite = sprites[index];
                if (ReferenceEquals(sprite, null) || sprite == null)
                {
                    continue;
                }
                string previous;
                if (owners.TryGetValue(sprite, out previous))
                {
                    if (!string.Equals(previous, group, StringComparison.Ordinal))
                    {
                        ambiguous.Add(sprite);
                    }
                }
                else
                {
                    owners.Add(sprite, group);
                }
            }
        }

        private static void AddNameRoute(
            string name,
            string group,
            Dictionary<string, string> routes,
            HashSet<string> ambiguous)
        {
            if (string.IsNullOrEmpty(name) || ambiguous.Contains(name))
            {
                return;
            }
            string previous;
            if (routes.TryGetValue(name, out previous))
            {
                if (!string.Equals(previous, group, StringComparison.Ordinal))
                {
                    routes.Remove(name);
                    ambiguous.Add(name);
                }
            }
            else
            {
                routes.Add(name, group);
            }
        }

        private bool ShouldObserveMaskRoute(
            SpriteRenderer renderer,
            int file)
        {
            string fileGroup = file >= 0 && file < _gmGroups.Length
                ? _gmGroups[file]
                : null;
            AssetStreamGroupManifest fileManifest;
            bool fileMaskRequired = fileGroup != null
                && _groupsById.TryGetValue(fileGroup, out fileManifest)
                && fileManifest.MaskPolicy == AssetStreamMaskPolicy.Required;
            if (!_mapActive
                || Volatile.Read(ref _mapEpoch) < 1
                || ReferenceEquals(renderer, null)
                || renderer == null)
            {
                return false;
            }
            int rendererId = renderer.GetInstanceID();
            Sprite sprite = renderer.sprite;
            Texture ignored;
            string routeGroup;
            _routes.TryGet(sprite, out ignored, out routeGroup);
            return _maskRouteProbe.ShouldObserve(
                rendererId,
                renderer,
                fileMaskRequired,
                routeGroup);
        }

        private AssetStreamPageMaskProbeSnapshot CaptureMaskRouteProbe(
            SpriteRenderer renderer,
            int file,
            int image,
            int colour,
            bool altFrame,
            int chopFeet,
            int transparency,
            out string captureFailure)
        {
            captureFailure = string.Empty;
            int rendererId = 0;
            string fileGroup = file >= 0 && file < _gmGroups.Length
                ? _gmGroups[file]
                : null;
            AssetStreamGroupManifest fileManifest;
            bool fileMaskRequired = fileGroup != null
                && _groupsById.TryGetValue(fileGroup, out fileManifest)
                && fileManifest.MaskPolicy == AssetStreamMaskPolicy.Required;
            string routeGroup = null;
            Sprite sprite = null;
            Material material = null;
            Shader shader = null;
            Texture expectedMask = null;
            bool expectedMaskOwned = false;
            bool blockHasMask = false;
            Texture blockMask = null;
            bool materialHasMask = false;
            Texture materialMask = null;
            bool unityNull = true;
            try
            {
                rendererId = renderer.GetInstanceID();
                unityNull = renderer == null;
                if (!unityNull)
                {
                    sprite = renderer.sprite;
                    if (_routes.TryGet(
                            sprite,
                            out expectedMask,
                            out routeGroup))
                    {
                        expectedMaskOwned = _routes.OwnsMask(expectedMask);
                    }
                    material = renderer.sharedMaterial;
                    shader = material == null ? null : material.shader;
                    _pageMaskBlock.Clear();
                    renderer.GetPropertyBlock(_pageMaskBlock);
                    blockHasMask =
                        _pageMaskBlock.HasTexture(_teamMaskPropertyId);
                    if (blockHasMask)
                    {
                        blockMask = _pageMaskBlock.GetTexture(
                            _teamMaskPropertyId);
                    }
                    materialHasMask = material != null
                        && material.HasProperty(_teamMaskPropertyId);
                    if (materialHasMask)
                    {
                        materialMask = material.GetTexture(_teamMaskPropertyId);
                    }
                }
            }
            catch (Exception exception)
            {
                captureFailure = exception.GetType().Name;
            }
            return new AssetStreamPageMaskProbeSnapshot(
                Volatile.Read(ref _mapEpoch),
                rendererId,
                renderer,
                unityNull,
                fileGroup,
                fileMaskRequired,
                routeGroup,
                UnityIdentity(sprite),
                UnityIdentity(material),
                UnityIdentity(shader),
                UnityIdentity(expectedMask),
                expectedMaskOwned,
                blockHasMask,
                UnityIdentity(blockMask),
                materialHasMask,
                UnityIdentity(materialMask),
                file,
                image,
                colour,
                altFrame,
                chopFeet,
                transparency);
        }

        private void ObserveMaskRouteProbe(
            AssetStreamPageMaskProbeSnapshot before,
            AssetStreamPageMaskProbeSnapshot after,
            string exceptionType)
        {
            AssetStreamPageMaskProbeEvent observed;
            if (!_maskRouteProbe.TryObserve(
                    before,
                    after,
                    exceptionType,
                    out observed))
            {
                return;
            }
            AssetStreamPageMaskProbeSnapshot current = observed.After;
            string message =
                "SEDE_RUNTIME_V1|event=asset_stream_mask_route"
                + "|status=observed"
                + "|epoch=" + current.Epoch.ToString(CultureInfo.InvariantCulture)
                + "|reason=" + observed.Reason
                + "|anomaly=" + (observed.Anomaly ? "1" : "0")
                + "|correction=" + (observed.Correction ? "1" : "0")
                + "|renderer_id=" + current.RendererId.ToString(
                    CultureInfo.InvariantCulture)
                + "|renderer_id_reused="
                    + (observed.RendererIdReused ? "1" : "0")
                + "|renderer_unity_null="
                    + (current.RendererUnityNull ? "1" : "0")
                + "|file=" + current.File.ToString(CultureInfo.InvariantCulture)
                + "|file_group=" + ProbeToken(current.FileGroup)
                + "|mask_required=" + (current.MaskRequired ? "1" : "0")
                + "|route_group=" + ProbeToken(current.RouteGroup)
                + "|image=" + current.Image.ToString(CultureInfo.InvariantCulture)
                + "|colour=" + current.Colour.ToString(CultureInfo.InvariantCulture)
                + "|alt_frame=" + (current.AltFrame ? "1" : "0")
                + "|chop_feet=" + current.ChopFeet.ToString(
                    CultureInfo.InvariantCulture)
                + "|transparency=" + current.Transparency.ToString(
                    CultureInfo.InvariantCulture)
                + "|sprite_before=" + observed.Before.SpriteIdentity
                + "|sprite_after=" + current.SpriteIdentity
                + "|material_before=" + observed.Before.MaterialIdentity
                + "|material_after=" + current.MaterialIdentity
                + "|shader_before=" + observed.Before.ShaderIdentity
                + "|shader_after=" + current.ShaderIdentity
                + "|expected_mask_before="
                    + observed.Before.ExpectedMaskIdentity
                + "|expected_mask_after=" + current.ExpectedMaskIdentity
                + "|block_mask_before=" + observed.Before.BlockMaskIdentity
                + "|block_mask_after=" + current.BlockMaskIdentity
                + "|material_mask_before="
                    + observed.Before.MaterialMaskIdentity
                + "|material_mask_after=" + current.MaterialMaskIdentity
                + "|exception=" + ProbeToken(observed.ExceptionType);
            SafeLog(observed.Anomaly ? _warning : _information, message);
        }

        private static string UnityIdentity(UnityEngine.Object value)
        {
            if (ReferenceEquals(value, null)) return "null";
            int referenceId = RuntimeHelpers.GetHashCode(value);
            try
            {
                bool destroyed = value == null;
                return (destroyed ? "destroyed:" : "live:")
                    + value.GetInstanceID().ToString(CultureInfo.InvariantCulture)
                    + "@" + referenceId.ToString(CultureInfo.InvariantCulture);
            }
            catch
            {
                return "unreadable:@"
                    + referenceId.ToString(CultureInfo.InvariantCulture);
            }
        }

        private static string ProbeToken(string value)
        {
            if (string.IsNullOrEmpty(value)) return "none";
            value = value.Replace('|', '/').Replace('=', ':')
                .Replace('\r', ' ').Replace('\n', ' ');
            return value.Length <= 96 ? value : value.Substring(0, 96);
        }

        private void RoutePageMask(SpriteRenderer renderer)
        {
            if (!Ready || renderer == null)
            {
                return;
            }
            Sprite sprite = renderer.sprite;
            Texture ownedMask = null;
            bool owned = _mapActive
                && _routes.TryGet(sprite, out ownedMask);
            int rendererId = renderer.GetInstanceID();
            if (!owned
                && !_pageMaskOwnership.IsTracked(rendererId, renderer))
            {
                return;
            }

            _pageMaskBlock.Clear();
            renderer.GetPropertyBlock(_pageMaskBlock);
            bool blockHasMask = _pageMaskBlock.HasTexture(_teamMaskPropertyId);
            Texture blockMask = blockHasMask
                ? _pageMaskBlock.GetTexture(_teamMaskPropertyId)
                : null;
            bool blockMaskOwned = blockHasMask
                && _routes.OwnsMask(blockMask);
            Material material = renderer.sharedMaterial;
            bool materialHasMask = material != null
                && material.HasProperty(_teamMaskPropertyId);
            Texture materialMask = materialHasMask
                ? material.GetTexture(_teamMaskPropertyId)
                : null;
            bool materialMaskOwned = materialHasMask
                && _routes.OwnsMask(materialMask);
            AssetStreamPageMaskDecision<Texture> decision =
                _pageMaskOwnership.Route(
                    rendererId,
                    renderer,
                    owned,
                    ownedMask,
                    blockHasMask,
                    blockMask,
                    blockMaskOwned,
                    materialHasMask,
                    materialMask,
                    materialMaskOwned,
                    materialHasMask && _routes.OwnsMaterial(material),
                    _neutralTeamMask);
            if (decision.Write)
            {
                // GetPropertyBlock copied the complete current block. Changing
                // one texture keeps foreign colours, alpha, cutoff and any
                // unrelated shader properties intact; sharedMaterial identity
                // is never replaced by this route.
                _pageMaskBlock.SetTexture(
                    _teamMaskPropertyId,
                    decision.Texture);
                renderer.SetPropertyBlock(_pageMaskBlock);
                _pageMaskOwnership.RecordWriteSucceeded(
                    rendererId,
                    renderer,
                    decision.Texture,
                    owned);
            }
            if (decision.ReleaseBlocked)
            {
                // A foreign/shared material still owns one of the registered
                // bundle masks. Mutating or replacing that material would
                // violate foreign ownership; retaining the epoch is the only
                // safe outcome until its owner changes the material again.
                throw new InvalidOperationException(
                    "Current renderer material retains an owned page mask");
            }
        }

        private void NeutralizePageMasksForRelease()
        {
            RequireMainThread();
            IList<AssetStreamTrackedPageMask<Texture>> tracked =
                _pageMaskOwnership.SnapshotTracked();
            Exception failure = null;
            int blocked = 0;
            int neutralized = 0;
            _neutralizeRuns++;
            _neutralizeTracked += tracked.Count;
            for (int index = 0; index < tracked.Count; index++)
            {
                try
                {
                    SpriteRenderer renderer =
                        tracked[index].Renderer as SpriteRenderer;
                    if (renderer == null)
                    {
                        _pageMaskOwnership.Forget(
                            tracked[index].RendererId,
                            tracked[index].Renderer);
                        continue;
                    }
                    _pageMaskBlock.Clear();
                    renderer.GetPropertyBlock(_pageMaskBlock);
                    bool blockHasMask =
                        _pageMaskBlock.HasTexture(_teamMaskPropertyId);
                    Texture blockMask = blockHasMask
                        ? _pageMaskBlock.GetTexture(_teamMaskPropertyId)
                        : null;
                    bool blockMaskOwned = blockHasMask
                        && _routes.OwnsMask(blockMask);
                    Material material = renderer.sharedMaterial;
                    bool materialHasMask = material != null
                        && material.HasProperty(_teamMaskPropertyId);
                    Texture materialMask = materialHasMask
                        ? material.GetTexture(_teamMaskPropertyId)
                        : null;
                    bool materialMaskOwned = materialHasMask
                        && _routes.OwnsMask(materialMask);
                    AssetStreamPageMaskDecision<Texture> decision =
                        _pageMaskOwnership.Route(
                            tracked[index].RendererId,
                            renderer,
                            false,
                            null,
                            blockHasMask,
                            blockMask,
                            blockMaskOwned,
                            materialHasMask,
                            materialMask,
                            materialMaskOwned,
                            materialHasMask && _routes.OwnsMaterial(material),
                            _neutralTeamMask);
                    if (decision.Write)
                    {
                        _pageMaskBlock.SetTexture(
                            _teamMaskPropertyId,
                            decision.Texture);
                        renderer.SetPropertyBlock(_pageMaskBlock);
                        _pageMaskOwnership.RecordWriteSucceeded(
                            tracked[index].RendererId,
                            renderer,
                            decision.Texture,
                            false);
                        neutralized++;
                    }
                    if (decision.ReleaseBlocked)
                    {
                        blocked++;
                        Material blockingMaterial = renderer.sharedMaterial;
                        throw new InvalidOperationException(
                            "Current renderer material retains an owned page mask"
                            + " renderer=" + AssetStreamText.Sanitize(
                                renderer.name, 48)
                            + " material=" + AssetStreamText.Sanitize(
                                blockingMaterial == null
                                    ? "<null>"
                                    : blockingMaterial.name,
                                48)
                            + " mask=" + AssetStreamText.Sanitize(
                                materialMask == null
                                    ? "<null>"
                                    : materialMask.name,
                                48));
                    }
                }
                catch (Exception exception)
                {
                    if (failure == null)
                    {
                        failure = exception;
                    }
                }
            }
            _neutralizeNeutralized += neutralized;
            _neutralizeBlocked += blocked;
            if (failure != null)
            {
                _neutralizeFailures++;
                // Never detach/destroy bundle textures while a live renderer
                // might still hold an owned mask in its native property block.
                throw new InvalidOperationException(
                    "Page-mask neutralization failed before release"
                    + " tracked=" + tracked.Count.ToString(
                        CultureInfo.InvariantCulture)
                    + " neutralized=" + neutralized.ToString(
                        CultureInfo.InvariantCulture)
                    + " blocked=" + blocked.ToString(
                        CultureInfo.InvariantCulture)
                    + " route_conflicts=" + Volatile.Read(ref _routeConflicts)
                        .ToString(CultureInfo.InvariantCulture),
                    failure);
            }
        }

        private bool AdvanceShutdownDrain()
        {
            if (!IsMainThread || _retainForApplicationExit)
            {
                return false;
            }
            try
            {
                return _timeline.Execute(delegate
                {
                    DrainQueuedResultsOnMainLocked();
                    if (!_shutdownInitiated)
                    {
                        // BeginShutdown synchronously detaches/restores every
                        // published group before any reset/summary attests the
                        // epoch as complete.
                        ReleaseBattlementOverlayVariants();
                        NeutralizePageMasksForRelease();
                        if (_mapActive)
                        {
                            FinalizeOffMainRequestsOnMainLocked(_mapEpoch);
                        }
                        _controller.BeginShutdown();
                        _shutdownInitiated = true;
                        DrainControllerEventsOnMainLocked();
                    }
                    if (_mapActive)
                    {
                        _mapActive = false;
                        LogSceneResetAndSummary(_mapEpoch, "shutdown");
                    }
                    _backend.AdvancePendingCleanup();
                    _controller.AdvanceLateFrame();
                    DrainControllerEventsOnMainLocked();
                    if (_controller.ShutdownDrainComplete
                        && !_backend.HasPendingCleanup)
                    {
                        return true;
                    }
                    if (!_backend.HasPendingCleanup
                        && _controller.ShutdownDrainTerminalRetention)
                    {
                        _drainTerminal = true;
                        if (!_drainFailureLogged)
                        {
                            _drainFailureLogged = true;
                            SafeLog(
                                _warning,
                                "Asset-stream cleanup reached terminal retained ownership; "
                                + "hooks remain detached and the drain host will stop");
                        }
                    }
                    return false;
                });
            }
            catch (Exception exception)
            {
                _drainTerminal = true;
                if (!_drainFailureLogged)
                {
                    _drainFailureLogged = true;
                    SafeLog(
                        _warning,
                        "Asset-stream shutdown drain retained ownership: "
                        + Describe(exception));
                }
                return false;
            }
        }

        private static void EnsureDrainHost()
        {
            lock (InstallationGate)
            {
                if (_drainHostObject != null)
                {
                    return;
                }
                GameObject host = null;
                try
                {
                    host = new GameObject(
                        "StrongholdEuropeDE.AssetStreamDrainHost");
                    UnityEngine.Object.DontDestroyOnLoad(host);
                    host.hideFlags = HideFlags.HideAndDontSave;
                    host.AddComponent<AssetStreamDrainHost>();
                    _drainHostObject = host;
                    host = null;
                }
                finally
                {
                    if (host != null)
                    {
                        UnityEngine.Object.Destroy(host);
                    }
                }
            }
        }

        private void StopToVanilla(string reason, bool applicationQuitting)
        {
            Volatile.Write(ref _fastReady, 0);
            bool first;
            lock (_gate)
            {
                first = !_stopped;
                _stopped = true;
                _ready = false;
                _retainForApplicationExit = applicationQuitting;
                _mapTransitions.Clear();
                _mapStartGate.Reset();
                _editorReadyObserved = false;
            }
            if (!first)
            {
                return;
            }
            lock (InstallationGate)
            {
                if (ReferenceEquals(_current, this))
                {
                    _current = null;
                }
            }
            if (IsMainThread)
            {
                try
                {
                    _timeline.Execute(delegate
                    {
                        DrainQueuedResultsOnMainLocked();
                        // Restore owned central references before publishing
                        // the scene-reset and resource-summary terminals.
                        ReleaseBattlementOverlayVariants();
                        NeutralizePageMasksForRelease();
                        if (_mapActive)
                        {
                            FinalizeOffMainRequestsOnMainLocked(_mapEpoch);
                        }
                        _controller.BeginShutdown();
                        _shutdownInitiated = true;
                        DrainControllerEventsOnMainLocked();
                        if (_mapActive)
                        {
                            _mapActive = false;
                            LogSceneResetAndSummary(_mapEpoch, "shutdown");
                        }
                    });
                }
                catch (Exception exception)
                {
                    SafeLog(
                        _warning,
                        "Asset-stream baseline restore failed during shutdown: "
                        + Describe(exception));
                }
            }
            DisposeSubscription(_mapStartSubscription);
            DisposeSubscription(_mapLoadSubscription);
            DisposeSubscription(_mapSaveSubscription);
            DisposeSubscription(_mapUnloadSubscription);
            _mapStartSubscription = null;
            _mapLoadSubscription = null;
            _mapSaveSubscription = null;
            _mapUnloadSubscription = null;
            try
            {
                _harmony.UnpatchSelf();
            }
            catch (Exception exception)
            {
                SafeLog(
                    _warning,
                    "Asset-stream Harmony detach failed: " + Describe(exception));
            }

            // Shutdown has no guaranteed future LateUpdate. Retaining the lane
            // is safer than fabricating two frames and destroying an object a
            // renderer may still reference. Normal map unload performs the
            // real two-LateUpdate release through AdvanceLateFrame.
            lock (InstallationGate)
            {
                RetainedShutdownLanes.Add(this);
            }
            if (!applicationQuitting && IsMainThread)
            {
                try
                {
                    EnsureDrainHost();
                }
                catch (Exception exception)
                {
                    SafeLog(
                        _warning,
                        "Asset-stream drain host could not be created: "
                        + Describe(exception));
                }
            }
            if (!_failureLogged || applicationQuitting)
            {
                _failureLogged = true;
                SafeLog(
                    applicationQuitting ? _information : _warning,
                    "SEDE_RUNTIME_V1|event=asset_stream|status="
                    + (applicationQuitting ? "inactive" : "vanilla")
                    + "|reason=" + AssetStreamText.Sanitize(reason, 180));
            }
        }

        private static AssetStreamManifest LoadAnchoredIndex(
            string pluginDirectory,
            AssetStreamCompiledContract compiled)
        {
            string path = AssetStreamBundleVerifier.ResolveUnderRoot(
                pluginDirectory,
                AssetStreamContract.IndexRelativePath);
            FileInfo before = new FileInfo(path);
            if (!before.Exists || before.Length != compiled.IndexSize)
            {
                throw new InvalidDataException(
                    "External asset-stream index size does not match compiled anchor");
            }
            byte[] raw;
            using (var stream = new FileStream(
                path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                1024 * 1024,
                FileOptions.SequentialScan))
            {
                raw = new byte[checked((int)compiled.IndexSize)];
                int offset = 0;
                while (offset < raw.Length)
                {
                    int read = stream.Read(raw, offset, raw.Length - offset);
                    if (read == 0)
                    {
                        throw new EndOfStreamException(
                            "External asset-stream index ended early");
                    }
                    offset += read;
                }
                if (stream.ReadByte() != -1)
                {
                    throw new InvalidDataException(
                        "External asset-stream index grew during read");
                }
            }
            FileInfo after = new FileInfo(path);
            if (!after.Exists || after.Length != before.Length
                || after.LastWriteTimeUtc != before.LastWriteTimeUtc)
            {
                throw new IOException(
                    "External asset-stream index changed during read");
            }
            string digest = Hashing.Sha256(raw);
            if (!string.Equals(
                digest,
                compiled.IndexSha256,
                StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "External asset-stream index SHA-256 mismatch");
            }
            AssetStreamManifest manifest = AssetStreamManifestParser.ParseIndex(raw);
            string manifestQualityState = manifest.QualityPolicy == null
                ? "v1"
                : manifest.QualityPolicy.State;
            bool manifestPromotable = manifest.QualityPolicy == null
                || manifest.QualityPolicy.IsPromotable;
            if (!string.Equals(
                    manifest.ContentSha256,
                    compiled.IndexSha256,
                StringComparison.Ordinal)
                || !string.Equals(
                    manifest.BackendKind,
                    compiled.BackendKind,
                    StringComparison.Ordinal)
                || !string.Equals(
                    manifest.Schema,
                    compiled.IndexSchema,
                    StringComparison.Ordinal)
                || !string.Equals(
                    manifestQualityState,
                    compiled.QualityState,
                    StringComparison.Ordinal)
                || manifestPromotable != compiled.Promotable
                || manifest.Groups.Count != compiled.GroupCount
                || manifest.VanillaOmittedGroups.Count
                    != compiled.VanillaOmittedGroupCount)
            {
                throw new InvalidDataException(
                    "Parsed asset-stream index does not match compiled anchors");
            }
            return manifest;
        }

        private static void VerifyExactPatchSurface()
        {
            ResolveApplyRuntimeOverrides();
            ResolveGetGmSprite();
            ResolveGetSprite();
            ResolveGetGmMaterial();
            ResolveBodyHook();
            ResolveToggleFlattenedLandscapeMode();
            ResolveSetFlattenedLandscapeMode();
            ResolveBuildingAnimsField();
            ResolveWallFillinsField();
        }

        private static MethodInfo ResolveApplyRuntimeOverrides()
        {
            Type type = typeof(GameAssetManagerAPI).Assembly.GetType(
                "SHCDESE.API.GameSpriteManagerAPI",
                false,
                false);
            if (type == null)
            {
                throw new TypeLoadException(
                    "Exact GameSpriteManagerAPI type was not found");
            }
            MethodInfo method = type.GetMethod(
                "ApplyRuntimeOverrides",
                BindingFlags.Instance | BindingFlags.NonPublic
                    | BindingFlags.DeclaredOnly,
                null,
                new[] { typeof(spriteLoader) },
                null);
            if (method == null || method.IsStatic || !method.IsAssembly
                || method.ReturnType != typeof(void) || method.DeclaringType != type)
            {
                throw new MissingMethodException(
                    "Exact GameSpriteManagerAPI.ApplyRuntimeOverrides was not found");
            }
            return method;
        }

        private static MethodInfo ResolveGetGmSprite()
        {
            Type type = typeof(spriteLoader);
            MethodInfo method = type.GetMethod(
                "GetGMSprite",
                BindingFlags.Instance | BindingFlags.Public
                    | BindingFlags.DeclaredOnly,
                null,
                new[] { typeof(Enums.GM), typeof(int), typeof(bool) },
                null);
            if (method == null || method.IsStatic
                || method.ReturnType != typeof(Sprite)
                || method.DeclaringType != type)
            {
                throw new MissingMethodException(
                    "Exact spriteLoader.GetGMSprite was not found");
            }
            return method;
        }

        private static MethodInfo ResolveGetSprite()
        {
            Type type = typeof(spriteLoader);
            MethodInfo method = type.GetMethod(
                "GetSprite",
                BindingFlags.Instance | BindingFlags.Public
                    | BindingFlags.DeclaredOnly,
                null,
                new[] { typeof(string) },
                null);
            if (method == null || method.IsStatic
                || method.ReturnType != typeof(Sprite)
                || method.DeclaringType != type)
            {
                throw new MissingMethodException(
                    "Exact spriteLoader.GetSprite was not found");
            }
            return method;
        }

        private static MethodInfo ResolveGetGmMaterial()
        {
            Type type = typeof(spriteLoader);
            MethodInfo method = type.GetMethod(
                "GetGMMaterial",
                BindingFlags.Instance | BindingFlags.Public
                    | BindingFlags.DeclaredOnly,
                null,
                new[]
                {
                    typeof(Enums.GM), typeof(int), typeof(int),
                    typeof(Color).MakeByRefType(), typeof(int)
                },
                null);
            if (method == null || method.IsStatic
                || method.ReturnType != typeof(Material)
                || method.DeclaringType != type)
            {
                throw new MissingMethodException(
                    "Exact spriteLoader.GetGMMaterial was not found");
            }
            return method;
        }

        private static MethodInfo ResolveBodyHook()
        {
            Type type = typeof(GameAssetManagerAPI).Assembly.GetType(
                BodyHookTypeName,
                false,
                false);
            if (type == null)
            {
                throw new TypeLoadException("Exact managed sprite hook type was not found");
            }
            MethodInfo method = type.GetMethod(
                BodyHookMethodName,
                BindingFlags.Instance | BindingFlags.NonPublic
                    | BindingFlags.DeclaredOnly,
                null,
                new[]
                {
                    typeof(SpriteRenderer), typeof(int), typeof(int), typeof(int),
                    typeof(bool), typeof(int), typeof(int)
                },
                null);
            if (method == null || method.IsStatic || !method.IsAssembly
                || method.ReturnType != typeof(void) || method.DeclaringType != type)
            {
                throw new MissingMethodException(
                    "Exact SpriteMapping_SetBodySprite_Hook was not found");
            }
            return method;
        }

        private static MethodInfo ResolveToggleFlattenedLandscapeMode()
        {
            Type type = typeof(EngineInterface);
            MethodInfo method = type.GetMethod(
                "toggleFlattenedLandscapeMode",
                BindingFlags.Static | BindingFlags.Public
                    | BindingFlags.DeclaredOnly,
                null,
                Type.EmptyTypes,
                null);
            if (method == null || !method.IsStatic
                || method.ReturnType != typeof(void)
                || method.DeclaringType != type)
            {
                throw new MissingMethodException(
                    "Exact EngineInterface.toggleFlattenedLandscapeMode was not found");
            }
            return method;
        }

        private static MethodInfo ResolveSetFlattenedLandscapeMode()
        {
            Type type = typeof(EngineInterface);
            MethodInfo method = type.GetMethod(
                "setFlattenedLandscapeMode",
                BindingFlags.Static | BindingFlags.Public
                    | BindingFlags.DeclaredOnly,
                null,
                new[] { typeof(bool) },
                null);
            if (method == null || !method.IsStatic
                || method.ReturnType != typeof(void)
                || method.DeclaringType != type)
            {
                throw new MissingMethodException(
                    "Exact EngineInterface.setFlattenedLandscapeMode was not found");
            }
            return method;
        }

        private static FieldInfo ResolveBuildingAnimsField()
        {
            Type mapType = typeof(GameMap);
            FieldInfo mapInstance = mapType.GetField(
                "instance",
                BindingFlags.Static | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            FieldInfo buildingAnims = mapType.GetField(
                "buildingAnims",
                BindingFlags.Instance | BindingFlags.NonPublic
                    | BindingFlags.DeclaredOnly);
            FieldInfo type = typeof(BuildingAnim).GetField(
                "type",
                BindingFlags.Instance | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            FieldInfo state = typeof(BuildingAnim).GetField(
                "state",
                BindingFlags.Instance | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            FieldInfo renderer = typeof(GameSprite).GetField(
                "sprRenderer",
                BindingFlags.Instance | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            if (mapInstance == null || !mapInstance.IsStatic
                || mapInstance.FieldType != mapType
                || mapInstance.DeclaringType != mapType
                || buildingAnims == null || buildingAnims.IsStatic
                || !buildingAnims.IsPrivate || !buildingAnims.IsInitOnly
                || buildingAnims.FieldType
                    != typeof(Dictionary<int, BuildingAnim>)
                || buildingAnims.DeclaringType != mapType
                || type == null || type.IsStatic
                || type.FieldType != typeof(int)
                || type.DeclaringType != typeof(BuildingAnim)
                || state == null || state.IsStatic
                || state.FieldType != typeof(int)
                || state.DeclaringType != typeof(BuildingAnim)
                || renderer == null || renderer.IsStatic
                || renderer.FieldType != typeof(SpriteRenderer)
                || renderer.DeclaringType != typeof(GameSprite))
            {
                throw new MissingFieldException(
                    "Exact GameMap building-animation sprite surface was not found");
            }
            return buildingAnims;
        }

        private static FieldInfo ResolveWallFillinsField()
        {
            Type mapType = typeof(GameMap);
            FieldInfo mapInstance = mapType.GetField(
                "instance",
                BindingFlags.Static | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            FieldInfo wallFillins = mapType.GetField(
                "wallFillins",
                BindingFlags.Instance | BindingFlags.NonPublic
                    | BindingFlags.DeclaredOnly);
            FieldInfo state = typeof(WallFillin).GetField(
                "state",
                BindingFlags.Instance | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            FieldInfo renderer = typeof(GameSprite).GetField(
                "sprRenderer",
                BindingFlags.Instance | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            if (mapInstance == null || !mapInstance.IsStatic
                || mapInstance.FieldType != mapType
                || mapInstance.DeclaringType != mapType
                || wallFillins == null || wallFillins.IsStatic
                || !wallFillins.IsPrivate || !wallFillins.IsInitOnly
                || wallFillins.FieldType
                    != typeof(Dictionary<int, WallFillin>)
                || wallFillins.DeclaringType != mapType
                || state == null || state.IsStatic
                || state.FieldType != typeof(int)
                || state.DeclaringType != typeof(WallFillin)
                || renderer == null || renderer.IsStatic
                || renderer.FieldType != typeof(SpriteRenderer)
                || renderer.DeclaringType != typeof(GameSprite))
            {
                throw new MissingFieldException(
                    "Exact GameMap wall-fillin sprite surface was not found");
            }
            return wallFillins;
        }

        private static MethodInfo RequirePatch(string name)
        {
            MethodInfo method = typeof(AssetStreamRuntimeLane).GetMethod(
                name,
                BindingFlags.Static | BindingFlags.NonPublic
                    | BindingFlags.DeclaredOnly);
            if (method == null)
            {
                throw new MissingMethodException(
                    "Asset-stream Harmony callback is missing: " + name);
            }
            return method;
        }

        private static void ApplyRuntimeOverridesPostfix(spriteLoader loaderInstance)
        {
            AssetStreamRuntimeLane lane = Volatile.Read(ref _current);
            if (lane == null || !lane.Ready)
            {
                return;
            }
            try
            {
                lane.CaptureBaseline(loaderInstance);
            }
            catch (Exception exception)
            {
                lane.StopToVanilla(
                    "baseline_capture_failed: " + Describe(exception),
                    false);
            }
        }

        private static bool GetGmSpritePrefix(
            spriteLoader __instance,
            Enums.GM gmFile,
            int imageID,
            bool altFrame,
            ref Sprite __result)
        {
            AssetStreamRuntimeLane lane = Volatile.Read(ref _current);
            if (lane == null)
            {
                return true;
            }
            if (!lane.IsMainThread)
            {
                Sprite baseline;
                if (lane.TryGetOffMainGmSprite(
                        (int)gmFile,
                        imageID,
                        altFrame,
                        out baseline))
                {
                    __result = baseline;
                    return false;
                }
                return true;
            }
            if (!lane.Ready)
            {
                return true;
            }
            try
            {
                lane.EnsureGm((int)gmFile);
            }
            catch
            {
                // The original getter remains the only result path.
                return true;
            }
            try
            {
                Sprite battlementOverlay;
                if (lane.TryGetBattlementOverlaySprite(
                        __instance,
                        (int)gmFile,
                        imageID,
                        altFrame,
                        EngineInterface.FlattenedLandscape,
                        out battlementOverlay))
                {
                    __result = battlementOverlay;
                    return false;
                }
            }
            catch (Exception exception)
            {
                lane.WarnBattlementOverlayFailure(
                    "getter_route_failed: " + Describe(exception));
            }
            return true;
        }

        private static void FlattenedLandscapeStatePostfix()
        {
            AssetStreamRuntimeLane lane = Volatile.Read(ref _current);
            if (lane == null || !lane.IsMainThread || !lane.Ready)
            {
                return;
            }
            try
            {
                lane.RefreshBattlementRenderers();
            }
            catch (Exception exception)
            {
                lane.WarnBattlementOverlayFailure(
                    "state_refresh_failed: " + Describe(exception));
            }
        }

        private static bool GetSpritePrefix(string name, ref Sprite __result)
        {
            AssetStreamRuntimeLane lane = Volatile.Read(ref _current);
            if (lane == null)
            {
                return true;
            }
            if (!lane.IsMainThread)
            {
                Sprite baseline;
                if (lane.TryGetOffMainNamedSprite(name, out baseline))
                {
                    __result = baseline;
                    return false;
                }
                return true;
            }
            if (!lane.Ready)
            {
                return true;
            }
            try
            {
                lane.EnsureSpriteName(name);
            }
            catch
            {
                // The original getter remains the only result path.
            }
            return true;
        }

        private static bool GetGmMaterialPrefix(
            Enums.GM gmFile,
            int colourOffset,
            int chop_feet,
            ref Color outputColour,
            int transparency,
            ref Material __result)
        {
            AssetStreamRuntimeLane lane = Volatile.Read(ref _current);
            if (lane == null)
            {
                return true;
            }
            if (!lane.IsMainThread)
            {
                Color baselineColour;
                Material baseline;
                if (lane.TryGetOffMainGmMaterial(
                        (int)gmFile,
                        colourOffset,
                        chop_feet,
                        transparency,
                        out baselineColour,
                        out baseline))
                {
                    outputColour = baselineColour;
                    __result = baseline;
                    return false;
                }
                return true;
            }
            if (!lane.Ready)
            {
                return true;
            }
            try
            {
                lane.EnsureGm((int)gmFile);
            }
            catch
            {
                // The original material getter remains the only result path.
            }
            return true;
        }

        private static void BodySpritePostfix(
            SpriteRenderer renderer,
            int file,
            int image,
            int colour,
            bool altFrame,
            int chopFeet,
            int transparency)
        {
            AssetStreamRuntimeLane lane = Volatile.Read(ref _current);
            if (lane == null || !lane.IsMainThread || !lane.Ready)
            {
                return;
            }
            bool observe = false;
            try
            {
                observe = lane.ShouldObserveMaskRoute(
                    renderer,
                    file);
            }
            catch
            {
                observe = false;
            }
            AssetStreamPageMaskProbeSnapshot before = null;
            string beforeFailure = string.Empty;
            if (observe)
            {
                try
                {
                    before = lane.CaptureMaskRouteProbe(
                        renderer,
                        file,
                        image,
                        colour,
                        altFrame,
                        chopFeet,
                        transparency,
                        out beforeFailure);
                }
                catch (Exception exception)
                {
                    beforeFailure = exception.GetType().Name;
                }
            }
            Exception routeFailure = null;
            try
            {
                // SHCDE-SE has already selected the exact material and written
                // _SpriteCutoff for this chopFeet value. Only the atlas-page
                // mask belongs to this postfix.
                lane.RoutePageMask(renderer);
            }
            catch (Exception exception)
            {
                // Leave the material selected by SHCDE-SE/Crusader untouched.
                // Counted only: this is the routine per-frame conflict that a
                // pooled renderer produces when it changes unit type, and it
                // is the same condition that later blocks release. Knowing how
                // often it happens is what separates "normal" from "the map
                // transition is about to fail".
                Interlocked.Increment(ref lane._routeConflicts);
                routeFailure = exception;
            }
            if (observe && before != null)
            {
                try
                {
                    string afterFailure;
                    AssetStreamPageMaskProbeSnapshot after =
                        lane.CaptureMaskRouteProbe(
                            renderer,
                            file,
                            image,
                            colour,
                            altFrame,
                            chopFeet,
                            transparency,
                            out afterFailure);
                    string failure = routeFailure == null
                        ? string.Empty
                        : routeFailure.GetType().Name;
                    if (!string.IsNullOrEmpty(beforeFailure))
                    {
                        failure = "before_capture_" + beforeFailure;
                    }
                    if (!string.IsNullOrEmpty(afterFailure))
                    {
                        failure = "after_capture_" + afterFailure;
                    }
                    lane.ObserveMaskRouteProbe(before, after, failure);
                }
                catch
                {
                    // Diagnostics are observation-only and must never alter
                    // the already completed page-mask route.
                }
            }
        }

        private bool IsMainThread
        {
            get { return Thread.CurrentThread.ManagedThreadId == _mainThreadId; }
        }

        private void RequireMainThread()
        {
            if (!IsMainThread)
            {
                throw new InvalidOperationException(
                    "Asset-stream Unity lifecycle requires the captured main thread");
            }
        }

        private static void DisposeSubscription(IDisposable value)
        {
            if (value == null) return;
            try { value.Dispose(); }
            catch { }
        }

        private static void SafeLog(Action<string> sink, string message)
        {
            if (sink == null) return;
            try { sink(message); }
            catch { }
        }

        private static string Describe(Exception exception)
        {
            // Include the inner chain. Without it "Page-mask neutralization
            // failed before release" says nothing about WHICH condition
            // blocked, and the real cause has to be guessed from source
            // reading instead of read from the log.
            var text = new StringBuilder();
            Exception current = exception;
            int depth = 0;
            while (current != null && depth < 4)
            {
                if (depth != 0) text.Append(" <- ");
                text.Append(current.GetType().Name)
                    .Append(": ")
                    .Append(current.Message);
                current = current.InnerException;
                depth++;
            }
            return AssetStreamText.Sanitize(text.ToString(), 400);
        }

        private sealed class BattlementOverlayVariant
        {
            internal BattlementOverlayVariant(
                int imageId,
                Sprite source,
                Sprite topAligned)
            {
                ImageId = imageId;
                Source = source;
                TopAligned = topAligned;
            }

            internal int ImageId { get; private set; }
            internal Sprite Source { get; private set; }
            internal Sprite TopAligned { get; private set; }
        }

        private enum MapTransition
        {
            Start = 0,
            Unload = 1,
        }
    }
}
