using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BepInEx;
using HarmonyLib;
using SHCDESE.API;
using StrongholdEuropeDE.Runtime.Audio;
using UnityEngine;
using UnityObject = UnityEngine.Object;

namespace StrongholdEuropeDE.Runtime
{
    [BepInPlugin(
        GeneratedAudioContract.PluginId,
        "Stronghold Europe DE Runtime (Private)",
        "0.2.0")]
    // Lower bound of the RedBird generation this DLL binds to. Newer or
    // unverified SE builds load; the capability report says so in one line.
    [BepInDependency("000shcdese", "2.0.0")]
    [BepInDependency(
        "fixes",
        BepInDependency.DependencyFlags.SoftDependency)]
    public sealed class StrongholdEuropeRuntimePlugin : BaseUnityPlugin
    {
        private const int TreeAppleGmIndex = 97;
        private const int MaterialSlotCount = 7;
        private const int TreeAppleSpriteCount = 101;
        private const int TreeAppleAtlasWidth = 2048;
        private const int TreeAppleAtlasHeight = 4096;
        private const string TreeAppleAtlasTextureName = "atlas";
        private const string TreeAppleMaskTextureName = "atlas_m";
        private const string TeamColourShader = "Unlit/TeamColour";
        private const string FoliageShader = "Unlit/Foliage";
        private const string TeamMaskProperty = "_TeamMask";

        private static StrongholdEuropeRuntimePlugin _instance;

        private readonly object _gate = new object();
        private Harmony _harmony;
        private RuntimeManifest _manifest;
        private string _pluginDirectory;
        private string _treeAppleAtlasPath;
        private bool _runtimeVerified;
        private bool _luaStateGuardInstalled;
        private bool _shuttingDown;
        private bool _applicationQuitting;
        private bool _assetProviderRegistered;
        private bool _audioRejected;
        private bool _audioApplied;
        private bool _runtimeTerminalLogged;
        private bool _audioTerminalLogged;
        private bool _foliagePending;
        private bool _foliageTerminalLogged;

        private object _audioManager;
        private FieldInfo _musicFilenamesField;
        private FieldInfo _volumeDataField;
        private Dictionary<int, string> _originalMusic = new Dictionary<int, string>();
        private Dictionary<string, object> _ownedVolumeData =
            new Dictionary<string, object>(StringComparer.Ordinal);

        private object _foliageLoader;
        private FieldInfo _gmMaterialsField;
        private Material[] _originalFoliageMaterials;
        private Material[] _replacementFoliageMaterials;
        private Material _ownedFoliageMaterial;
        // Every vegetation group we ship an atlas for, beyond tree_apple.
        private readonly List<FoliageGroup> _foliageGroups = new List<FoliageGroup>();
        private RosterRuntimeController _rosterController;
        private FarmPlacementController _farmController;
        private bool _farmTerminalLogged;
        private DockPlacementController _dockController;
        private bool _dockTerminalLogged;
        private ExtensionFeatureHost _extensionHost;
        private IExtensionFeature _workerMilitia;
        private DiplomacyFeature _diplomacy;
        private FortificationFeature _fortifications;
        private bool _diplomacyTerminalLogged;
        private bool _fortificationsTerminalLogged;
        private bool _workerMilitiaTerminalLogged;
        private bool _workerMilitiaFailureLogged;
        // The roster terminal line must appear exactly once, whether it is the
        // roster lane itself that fails or a later failure in Awake.
        private bool _rosterFailureLogged;
        private GameObject _runtimeHostObject;
        private StrongholdEuropePersistentHost _runtimeHost;
        private EuropeCapabilities _capabilities;
        private AssetStreamRuntimeLane _assetStreamLane;
        private UiTextureRuntimeLane _uiTextureLane;
        private PcmAudioStreamingLane _pcmAudioStreamingLane;
        private ScriptExtenderScanBufferRelease _scanBufferRelease;
        private BuildingPlacementGridFeature _buildingPlacementGrid;

        private void Awake()
        {
            try
            {
                // BepInEx normally hosts plugins on its persistent manager, but
                // this game performs an unusually early scene transition while
                // the atlas loader is still working.  Make persistence explicit:
                // foliage finalization must remain alive until ApplySingle has
                // replaced the registered GM arrays.
                UnityObject.DontDestroyOnLoad(gameObject);
                _pluginDirectory = Path.GetDirectoryName(
                    typeof(StrongholdEuropeRuntimePlugin).Assembly.Location);
                if (string.IsNullOrEmpty(_pluginDirectory))
                {
                    throw new InvalidOperationException("Runtime plugin directory is unavailable");
                }
                _treeAppleAtlasPath = Path.Combine(
                    _pluginDirectory,
                    "Override",
                    "Atlas",
                    "tree_apple",
                    "atlas.json");

                string manifestPath = Path.Combine(
                    _pluginDirectory,
                    "Runtime",
                    "audio-profile.tsv");
                _manifest = RuntimeManifest.Load(manifestPath);
                // Decide per lane, not once for everything. The core check
                // still throws and still takes the plugin down - below it there
                // is no useful degraded mode. R3 is probed separately because
                // it serves only the farm rule, and folding it into the core
                // decision is what once turned a missing optional dependency
                // into a black screen after the Firefly logo.
                _capabilities = EuropeCapabilities.Probe();
                Logger.LogInfo(_capabilities.Report);
                if (!_capabilities.Core)
                {
                    throw new InvalidDataException(
                        "Core runtime prerequisites failed: " + _capabilities.CoreFailure);
                }

                // This is a process-safety fix for SHCDE-SE's single NLua
                // state, not an optional Europe feature lane. Install it as
                // soon as the core identities pass. Its dedicated Harmony
                // owner survives any later UI/audio/asset-lane rollback.
                // A newer SE may rename the guarded internals. Without the
                // guard the game runs exactly as it would without this mod, so
                // a refused guard is a warning, never the end of every lane.
                try
                {
                    ScriptExtenderLuaStateGuardPatch.Install(
                        message => Logger.LogInfo(message),
                        message => Logger.LogWarning(message));
                    _luaStateGuardInstalled = true;
                }
                catch (Exception exception)
                {
                    Logger.LogWarning(
                        "SEDE_RUNTIME_V1|event=lua_state_guard|status=unavailable"
                        + "|reason=" + exception.GetType().Name + ": "
                        + exception.Message);
                }

                // The scan-buffer and vegetation workarounds below reach into
                // Zhuqiaomon internals; under RedBird (SE 2.x) they have no
                // target. One line says which generation is loaded.
                Logger.LogInfo(ScriptExtenderGeneration.Describe());
                if (!ScriptExtenderGeneration.UsesRedBird)
                {
                    // The early plugin patches Zhuqiaomon before SHCDE-SE Awake so
                    // its twelve native transaction arrays, plus the optional two
                    // Fixes snapshot arrays, are never allocated. The old
                    // post-start releaser remains a fail-open fallback for an
                    // unknown binary/caller and keeps LibrarySnapshot intact.
                    int residentScratchBytes;
                    int peakScratchBytes;
                    if (ScriptExtenderScanBufferBorrowPatch.TryFinalizeStartup(
                        out residentScratchBytes,
                        out peakScratchBytes))
                    {
                        int preventedTransactions = checked(
                            ScriptExtenderScanBufferBorrowPatch.NativeTransactions
                            + ScriptExtenderScanBufferBorrowPatch
                                .SnapshotTransactions);
                        long preventedBytes = checked(
                            (long)preventedTransactions
                            * ScriptExtenderScanBufferBorrowPatch
                                .ExpectedModuleBytes);
                        Logger.LogInfo(
                            "SEDE_RUNTIME_V1|event=script_extender_scan_buffers"
                            + "|status=allocation_prevented"
                            + "|transactions="
                            + preventedTransactions.ToString()
                            + "|prevented_bytes="
                            + preventedBytes.ToString()
                            + "|native_snapshots="
                            + ScriptExtenderScanBufferBorrowPatch.NativeTransactions
                                .ToString()
                            + "|snapshot_views="
                            + ScriptExtenderScanBufferBorrowPatch.SnapshotTransactions
                                .ToString()
                            + "|fallback_copies=0"
                            + "|snapshot_retained_bytes="
                            + ScriptExtenderScanBufferBorrowPatch.ExpectedModuleBytes
                                .ToString()
                            + "|scratch_resident_bytes="
                            + residentScratchBytes.ToString()
                            + "|scratch_peak_bytes="
                            + peakScratchBytes.ToString());
                    }
                    else
                    {
                        Logger.LogWarning(
                            "SEDE_RUNTIME_V1|event=script_extender_scan_buffers"
                            + "|status=post_start_fallback"
                            + "|early_installed="
                            + (ScriptExtenderScanBufferBorrowPatch.Installed
                                ? "true"
                                : "false")
                            + "|native_snapshots="
                            + ScriptExtenderScanBufferBorrowPatch.NativeTransactions
                                .ToString()
                            + "|snapshot_views="
                            + ScriptExtenderScanBufferBorrowPatch.SnapshotTransactions
                                .ToString()
                            + "|fallback_copies="
                            + ScriptExtenderScanBufferBorrowPatch.FallbackTransactions
                                .ToString());
                        _scanBufferRelease = new ScriptExtenderScanBufferRelease(
                            message => Logger.LogInfo(message),
                            message => Logger.LogWarning(message));
                    }

                    // Attest vegetation detours after either scan-buffer startup
                    // path. The post-start releaser does not exist on the successful
                    // early path, so ReleasePhase cannot be the sole probe site.
                    // Diagnostics never own startup and must remain non-fatal.
                    try
                    {
                        ScriptExtenderVegetationCapabilities.ProbeOnce(
                            message => Logger.LogInfo(message),
                            message => Logger.LogWarning(message));
                    }
                    catch (Exception exception)
                    {
                        Logger.LogWarning(
                            "SEDE_RUNTIME_V1|event=vegetation_capability"
                            + "|status=unknown|reason=probe_exception_"
                            + exception.GetType().Name.ToLowerInvariant());
                    }
                }

                if (!_capabilities.R3)
                {
                    Logger.LogWarning(
                        "SEDE_RUNTIME_V1|event=capabilities|status=degraded|lane=farm_placement"
                        + "|reason=" + _capabilities.R3Failure);
                }

                _runtimeVerified = true;
                _instance = this;
                _harmony = new Harmony(GeneratedAudioContract.PluginId);
                _extensionHost = new ExtensionFeatureHost();

                // This prefix must exist before roster/Noesis can request the
                // first owned UI texture. It owns a process-lifetime Harmony id;
                // native Noesis references make mid-process unpatch unsafe.
                if (GeneratedUiTextureContract.Enabled)
                {
                    try
                    {
                        _uiTextureLane = UiTextureLoadTexturePatch.PrepareAndInstall(
                            _pluginDirectory,
                            new UiTextureCompiledContract(
                                GeneratedUiTextureContract.Enabled,
                                GeneratedUiTextureContract.ManifestSha256,
                                GeneratedUiTextureContract.ManifestSize,
                                GeneratedUiTextureContract.EntryCount),
                            message => Logger.LogInfo(message),
                            message => Logger.LogWarning(message));
                    }
                    catch (Exception exception)
                    {
                        _uiTextureLane = null;
                        Logger.LogError(
                            "SEDE_RUNTIME_V1|event=ui_texture_stream"
                            + "|status=failed_closed|reason="
                            + exception.GetType().Name);
                        throw new InvalidOperationException(
                            "Pinned UI texture lane failed closed",
                            exception);
                    }
                }

                if (GeneratedPcmStreamContract.Enabled)
                {
                    try
                    {
                        PcmAudioStreamingLane pcmLane;
                        if (!PcmAudioStreamingLane.TryPrepareAndInstall(
                            _pluginDirectory,
                            GeneratedPcmStreamContract.ManifestSha256,
                            GeneratedPcmStreamContract.ManifestSize,
                            GeneratedPcmStreamContract.TrackCount,
                            _harmony,
                            message => Logger.LogInfo(message),
                            message => Logger.LogWarning(message),
                            out pcmLane))
                        {
                            throw new InvalidOperationException(
                                "PCM streaming lane did not become ready");
                        }
                        _pcmAudioStreamingLane = pcmLane;
                        // The table/volume transaction is still required: IDs
                        // 4/5 otherwise remain null.raw, and the eu_* volume
                        // keys do not exist. Only provider registration is
                        // forbidden in streaming mode.
                        InstallAudioPatch();
                        TryApplyAudioOverride();
                    }
                    catch (Exception exception)
                    {
                        if (_pcmAudioStreamingLane != null)
                        {
                            _pcmAudioStreamingLane.Rollback(false);
                        }
                        _pcmAudioStreamingLane = null;
                        try { _harmony.UnpatchSelf(); }
                        catch { }
                        _harmony = new Harmony(GeneratedAudioContract.PluginId);
                        LogAudioTerminal("failed");
                        Logger.LogError(
                            "PCM/table lane failed closed; other lanes continue: "
                            + exception);
                    }
                }

                // Install before any feature can trigger the extender's sprite
                // finalization; the baseline is legal only in that exact
                // ApplyRuntimeOverrides postfix.
                if (GeneratedAssetStreamContract.Enabled)
                {
                    AssetStreamRuntimeLane streamingLane;
                    AssetStreamRuntimeLane.TryPrepareAndInstall(
                        _pluginDirectory,
                        GeneratedAudioContract.PluginId,
                        new AssetStreamCompiledContract(
                            GeneratedAssetStreamContract.Enabled,
                            GeneratedAssetStreamContract.IndexSha256,
                            GeneratedAssetStreamContract.IndexSize,
                            GeneratedAssetStreamContract.GroupCount,
                            GeneratedAssetStreamContract.VanillaOmittedGroupCount,
                            GeneratedAssetStreamContract.BackendKind,
                            GeneratedAssetStreamContract.IndexSchema,
                            GeneratedAssetStreamContract.QualityState,
                            GeneratedAssetStreamContract.Promotable,
                            GeneratedUiTextureContract.Enabled,
                            GeneratedPcmStreamContract.Enabled,
                            GeneratedFoliageContract.GroupNames),
                        message => Logger.LogInfo(message),
                        message => Logger.LogWarning(message),
                        out streamingLane);
                    _assetStreamLane = streamingLane;
                }
                else
                {
                    Logger.LogInfo(
                        "SEDE_RUNTIME_V1|event=asset_stream|status=inactive");
                }

                if (GeneratedRosterContract.Enabled)
                {
                    // The roster owns HUD XAML and therefore refuses to run when
                    // another mod patches the same file - SHCDEAutoRecruit does,
                    // legitimately. That refusal used to travel up into Awake and
                    // take the whole plugin with it, so a foreign HUD mod silently
                    // switched off the music, the music route and the farm rule as
                    // well. Those three touch no XAML at all; they have no business
                    // sharing the roster's fate.
                    RosterRuntimeController controller = new RosterRuntimeController(
                        _pluginDirectory,
                        _harmony,
                        message => Logger.LogInfo(message),
                        message => Logger.LogWarning(message),
                        message => Logger.LogError(message));
                    try
                    {
                        controller.PrepareAndPatch();
                        _rosterController = controller;
                    }
                    catch (Exception exception)
                    {
                        // The controller rolls its own state back; nothing of the
                        // roster remains applied.
                        try
                        {
                            controller.RollbackOwned(false);
                        }
                        catch (Exception rollbackException)
                        {
                            Logger.LogError(
                                "Roster rollback after a failed preparation errored: "
                                + rollbackException);
                        }
                        _rosterController = null;
                        if (!controller.Failed)
                        {
                            _rosterFailureLogged = true;
                            Logger.LogError(
                                RuntimeLogContract.RosterFailedClosed("preparation_failed"));
                        }
                        Logger.LogError(
                            "Roster lane failed closed and was skipped; the remaining "
                            + "features continue: " + exception);
                    }
                }
                else
                {
                    Logger.LogInfo(RuntimeLogContract.RosterInactive);
                }

                // The external streaming index supersedes the old eager atlas
                // mutation. Running both would make its post-extender baseline
                // stale and defeat ownership-aware rollback.
                if (GeneratedAssetStreamContract.Enabled)
                {
                    LogFoliageInactive();
                }
                else
                {
                    CollectFoliageGroups();
                    bool atlasExists = File.Exists(_treeAppleAtlasPath);
                    if (_manifest.FoliageTreeApple && atlasExists)
                    {
                        _foliagePending = true;
                    }
                    else if (_manifest.FoliageTreeApple)
                    {
                        LogFoliageTerminal(false);
                        throw new FileNotFoundException(
                            "Requested tree_apple foliage atlas is missing",
                            _treeAppleAtlasPath);
                    }
                    else
                    {
                        LogFoliageInactive();
                    }
                }

                if (GeneratedPcmStreamContract.Enabled)
                {
                    // Streaming builds own only Runtime/Audio WAVs. Registering
                    // the legacy Override/Sounds provider would index a second
                    // payload and reintroduce eager AudioClip allocations.
                }
                else if (_manifest.AudioPayload)
                {
                    string audioDirectory = Path.Combine(
                        _pluginDirectory,
                        "Override",
                        "Sounds",
                        "Music");
                    ValidateAudioPayload(audioDirectory);
                    if (!RuntimeDecision.ShouldActivateAudio(true, true, true, true))
                    {
                        throw new InvalidOperationException("Audio activation guard rejected a valid payload");
                    }
                    InstallAudioPatch();
                    GameAssetManagerAPI.Instance.RegisterAssetProvider(
                        GeneratedAudioContract.PluginId + ".audio",
                        audioDirectory);
                    _assetProviderRegistered = true;
                    TryApplyAudioOverride();
                }
                else
                {
                    LogAudioTerminal("inactive");
                }

                if (!GeneratedWorkerMilitiaContract.IsolatedCanary)
                {
                    InstallWolfSpriteRoute();
                }

                // Enabled says the build shipped this lane; FarmPlacement says
                // the machine can actually run it. Both have to hold.
                if (GeneratedFarmPlacementContract.Enabled
                    && _capabilities.FarmPlacement)
                {
                    _farmController = new FarmPlacementController(
                        message => Logger.LogInfo(message),
                        message => Logger.LogError(message));
                    _farmController.Subscribe();
                    InstallFarmResultPatch();
                    LogFarmTerminal("active");
                }
                else
                {
                    LogFarmTerminal("inactive");
                }

                if (GeneratedWorkerMilitiaContract.Enabled)
                {
                    if (!_capabilities.WorkerMilitia)
                    {
                        LogWorkerMilitiaTerminal("failed");
                        Logger.LogError(
                            "Worker militia was selected but its pinned R3 capability "
                            + "is unavailable: " + _capabilities.R3Failure);
                    }
                    else
                    {
                        // 2026-09-28 (user decision): the militia runs as native
                        // soldiers. WorkerMilitiaFeature (the rebuilt-selection
                        // model) stays in the tree but is no longer created.
                        var candidate = new WorkerMilitiaNativeSoldiers(
                            _harmony,
                            message => Logger.LogInfo(message),
                            message => Logger.LogWarning(message),
                            message => Logger.LogError(message));
                        string registrationFailure;
                        if (!_extensionHost.TryRegister(
                                candidate,
                                out registrationFailure))
                        {
                            LogWorkerMilitiaTerminal("failed");
                            Logger.LogError(
                                "Worker militia claim registration failed: "
                                + registrationFailure);
                        }
                        else
                        {
                            _extensionHost.ActivateAll();
                            ExtensionFeatureSnapshot snapshot =
                                FindExtensionSnapshot(candidate.Id);
                            if (snapshot != null
                                && snapshot.State == ExtensionFeatureState.Active)
                            {
                                _workerMilitia = candidate;
                                LogWorkerMilitiaTerminal("active");
                            }
                            else
                            {
                                LogWorkerMilitiaTerminal("failed");
                                Logger.LogError(
                                    "Worker militia activation failed: "
                                    + (snapshot == null
                                        ? "missing feature snapshot"
                                        : snapshot.Failure));
                            }
                        }
                    }
                }
                else
                {
                    LogWorkerMilitiaTerminal("inactive");
                }

                if (GeneratedDiplomacyContract.Enabled)
                {
                    if (!_capabilities.R3)
                    {
                        LogDiplomacyTerminal("failed", "r3_unavailable");
                    }
                    else
                    {
                        DiplomacyFeature candidate = new DiplomacyFeature(
                            _harmony,
                            message => Logger.LogInfo(message),
                            message => Logger.LogWarning(message),
                            message => Logger.LogError(message));
                        string registrationFailure;
                        if (!_extensionHost.TryRegister(
                                candidate,
                                out registrationFailure))
                        {
                            LogDiplomacyTerminal(
                                "failed",
                                "claim_registration:" + registrationFailure);
                        }
                        else
                        {
                            _extensionHost.ActivateAll();
                            ExtensionFeatureSnapshot snapshot =
                                FindExtensionSnapshot(candidate.Id);
                            if (snapshot != null
                                && snapshot.State == ExtensionFeatureState.Active)
                            {
                                _diplomacy = candidate;
                                LogDiplomacyTerminal("active", null);
                            }
                            else
                            {
                                LogDiplomacyTerminal(
                                    "failed",
                                    snapshot == null
                                        ? "missing_snapshot"
                                        : snapshot.Failure);
                            }
                        }
                    }
                }
                else
                {
                    LogDiplomacyTerminal("inactive", null);
                }

                // The fortification lane owns only its pinned HUD patch and
                // its own mapper/save subscriptions. A rejected 1.44/XAML or
                // measurement gate must leave every unrelated runtime lane
                // alive and the vanilla construction pages usable.
                if (GeneratedFortificationContract.Enabled)
                {
                    if (!_capabilities.R3)
                    {
                        LogFortificationsTerminal("failed", "r3_unavailable");
                    }
                    else
                    {
                        FortificationFeature candidate =
                            new FortificationFeature(
                                _harmony,
                                _pluginDirectory,
                                message => Logger.LogInfo(message),
                                message => Logger.LogWarning(message),
                                message => Logger.LogError(message));
                        string registrationFailure;
                        if (!_extensionHost.TryRegister(
                                candidate,
                                out registrationFailure))
                        {
                            LogFortificationsTerminal(
                                "failed",
                                "claim_registration:" + registrationFailure);
                        }
                        else
                        {
                            _extensionHost.ActivateAll();
                            ExtensionFeatureSnapshot snapshot =
                                FindExtensionSnapshot(candidate.Id);
                            if (snapshot != null
                                && snapshot.State
                                    == ExtensionFeatureState.Active)
                            {
                                _fortifications = candidate;
                                LogFortificationsTerminal("active", null);
                            }
                            else
                            {
                                LogFortificationsTerminal(
                                    "failed",
                                    snapshot == null
                                        ? "missing_snapshot"
                                        : snapshot.Failure);
                            }
                        }
                    }
                }
                else
                {
                    LogFortificationsTerminal("inactive", null);
                }

                // Eigener try/catch, und das ist der Punkt: der gemeinsame
                // catch von Awake unten ruft ShutdownAndRollback und nimmt
                // Audio, Laubwerk, Musikleitung, Roster und Farmregel mit. Eine
                // reine Messbahn darf niemals so viel Gewicht haben.
                if (GeneratedDockPlacementContract.Enabled
                    && _capabilities.DockPlacement)
                {
                    DockPlacementController dockCandidate =
                        new DockPlacementController(
                            message => Logger.LogInfo(message),
                            message => Logger.LogError(message));
                    try
                    {
                        // Subscribe kann nach dem ersten Abonnement werfen, und
                        // der Harmony-Patch danach ebenso. Zurueckgenommen wird
                        // deshalb der lokale Regler, nicht das Feld - das Feld
                        // steht in beiden Faellen noch auf null.
                        dockCandidate.Subscribe();
                        InstallDockResultPatch();
                        _dockController = dockCandidate;
                        LogDockTerminal("active");
                    }
                    catch (Exception exception)
                    {
                        dockCandidate.Rollback();
                        _dockController = null;
                        LogDockTerminal("failed");
                        Logger.LogError(
                            "Dock placement measurement was skipped; every other "
                            + "lane continues: " + exception);
                    }
                }
                else
                {
                    LogDockTerminal("inactive");
                }

                // This is an opt-in hotkey lane: until Ctrl+Alt+G is pressed it
                // only observes map lifecycle and performs no debug-mode writes.
                // Keep construction and subscription local so a missing legacy-input
                // surface or changed extender API cannot unwind unrelated lanes.
                if (_capabilities.R3)
                {
                    BuildingPlacementGridFeature gridCandidate = null;
                    try
                    {
                        gridCandidate = new BuildingPlacementGridFeature(
                            message => Logger.LogInfo(message),
                            message => Logger.LogError(message));
                        gridCandidate.Subscribe();
                        _buildingPlacementGrid = gridCandidate;
                    }
                    catch (Exception exception)
                    {
                        if (gridCandidate != null)
                        {
                            try
                            {
                                gridCandidate.Rollback();
                            }
                            catch (Exception rollbackException)
                            {
                                Logger.LogError(
                                    "Building placement grid rollback after a failed "
                                    + "preparation errored: " + rollbackException);
                            }
                        }
                        _buildingPlacementGrid = null;
                        Logger.LogError(
                            "Building placement grid failed closed and was skipped; "
                            + "the remaining features continue: " + exception);
                    }
                }
                else
                {
                    Logger.LogInfo(
                        "SEDE_RUNTIME_V1|event=building_placement_grid"
                        + "|status=inactive|reason=r3_unavailable");
                }

                if (_foliagePending
                    || _manifest.AudioPayload
                    || _pcmAudioStreamingLane != null
                    || _uiTextureLane != null
                    || GeneratedRosterContract.Enabled
                    || _farmController != null
                    || _workerMilitia != null
                    || _diplomacy != null
                    || _fortifications != null
                    || _dockController != null
                    || _buildingPlacementGrid != null
                    || _assetStreamLane != null
                    || _scanBufferRelease != null)
                {
                    CreatePersistentRuntimeHost();
                }
                LogRuntimeTerminal(true);
            }
            catch (Exception exception)
            {
                try
                {
                    ScriptExtenderScanBufferBorrowPatch
                        .ReleaseProvablyFreeScratch();
                }
                catch (Exception cleanupException)
                {
                    Logger.LogWarning(
                        "Free scan-buffer cleanup after startup failure errored: "
                        + cleanupException.GetType().Name);
                }
                if (GeneratedRosterContract.Enabled
                    && !_rosterFailureLogged
                    && (_rosterController == null || !_rosterController.Failed))
                {
                    _rosterFailureLogged = true;
                    Logger.LogError(
                        RuntimeLogContract.RosterFailedClosed("preparation_failed"));
                }
                if (GeneratedWorkerMilitiaContract.Enabled
                    && !_workerMilitiaTerminalLogged)
                {
                    LogWorkerMilitiaTerminal("failed");
                }
                if (GeneratedDiplomacyContract.Enabled
                    && !_diplomacyTerminalLogged)
                {
                    LogDiplomacyTerminal("failed", "startup_failure");
                }
                if (GeneratedFortificationContract.Enabled
                    && !_fortificationsTerminalLogged)
                {
                    LogFortificationsTerminal("failed", "startup_failure");
                }
                LogRuntimeTerminal(false);
                Logger.LogError(
                    "Runtime initialization failed closed; no unsupported patch will remain active: "
                    + exception);
                ShutdownAndRollback("initialization failure");
                enabled = false;
            }
        }

        internal void RuntimeTick()
        {
            if (_shuttingDown)
            {
                return;
            }
            if (_scanBufferRelease != null)
            {
                _scanBufferRelease.Tick();
            }
            if (_assetStreamLane != null)
            {
                _assetStreamLane.Tick();
            }
            if (_rosterController != null)
            {
                string shutdownReason;
                if (!_rosterController.Tick(out shutdownReason))
                {
                    ShutdownAndRollback(shutdownReason);
                    return;
                }
            }
            if (_dockController != null)
            {
                // Zwingend VOR dem unbedingten Foliage-Ausstieg direkt
                // darunter (SEE Abschnitt 6, Befund B): dahinter waere der
                // 1200-ms-Nachschlag der Hafenregeln toter Code, und die
                // Zusammenfassung wuerde eine Messung behaupten, die nie lief.
                _dockController.Tick();
            }
            if (_buildingPlacementGrid != null)
            {
                _buildingPlacementGrid.Tick();
            }
            if (_extensionHost != null)
            {
                _extensionHost.TickAll();
                ExtensionFeatureSnapshot militia =
                    FindExtensionSnapshot("unit.worker_militia");
                // _workerMilitia is the "not yet reported" latch: the snapshot
                // stays Failed on every later frame, and without the latch the
                // same terminal line was written once per Update (591 times in
                // one short session).
                if (_workerMilitia != null
                    && militia != null
                    && militia.State == ExtensionFeatureState.Failed)
                {
                    LogWorkerMilitiaTerminal("failed");
                    Logger.LogError(
                        "Worker militia stopped fail-closed: " + militia.Failure);
                    _workerMilitia = null;
                }
                ExtensionFeatureSnapshot diplomacy =
                    FindExtensionSnapshot("gameplay.diplomacy");
                if (_diplomacy != null
                    && diplomacy != null
                    && diplomacy.State == ExtensionFeatureState.Failed)
                {
                    Logger.LogError(
                        "SEDE_RUNTIME_V1|lane=diplomacy|event=feature"
                        + "|status=failed_closed|reason="
                        + diplomacy.Failure);
                    _diplomacy = null;
                }
                ExtensionFeatureSnapshot fortifications =
                    FindExtensionSnapshot("building.fortifications");
                if (_fortifications != null
                    && fortifications != null
                    && fortifications.State == ExtensionFeatureState.Failed)
                {
                    string fortificationFailure =
                        (fortifications.Failure ?? "unknown")
                            .Replace('|', ' ').Replace('\r', ' ')
                            .Replace('\n', ' ');
                    if (fortificationFailure.Length > 512)
                    {
                        fortificationFailure =
                            fortificationFailure.Substring(0, 512);
                    }
                    Logger.LogError(
                        "SEDE_RUNTIME_V1|lane=fortifications|event=feature"
                        + "|status=failed_closed|reason="
                        + fortificationFailure);
                    _fortifications = null;
                }
            }
            if (!_foliagePending || _foliageTerminalLogged)
            {
                return;
            }
            spriteLoader loader = spriteLoader.instance;
            if (IsUnityNull(loader) || !loader.spritesLoaded)
            {
                return;
            }
            TryApplyFoliageOverride(loader);
        }

        internal void RuntimeLateUpdate()
        {
            if (_shuttingDown)
            {
                return;
            }
            AssetStreamRuntimeLane lane = _assetStreamLane;
            if (lane != null)
            {
                lane.AdvanceLateFrame();
            }
        }

        private void OnApplicationQuit()
        {
            RuntimeApplicationQuit();
        }

        private void OnDestroy()
        {
            if (_applicationQuitting || IsUnityNull(_runtimeHostObject))
            {
                ShutdownAndRollback(
                    _applicationQuitting
                        ? "application quit"
                        : "plugin component destroyed without a persistent runtime host");
                return;
            }
            Logger.LogInfo(
                "BepInEx plugin component was destroyed during startup; "
                + "the dedicated persistent runtime host remains active.");
        }

        internal void RuntimeApplicationQuit()
        {
            _applicationQuitting = true;
            // Unity invokes application-quit callbacks before tearing down the
            // active Noesis tree. Restore the currently owned 17 Tags here;
            // OnDestroy/host callbacks may arrive later and are idempotently
            // absorbed by _shuttingDown under _gate.
            ShutdownAndRollback("application quit");
        }

        internal void RuntimeHostDestroyed(bool applicationQuitting)
        {
            _runtimeHostObject = null;
            _runtimeHost = null;
            if (applicationQuitting)
            {
                _applicationQuitting = true;
            }
            ShutdownAndRollback(
                applicationQuitting
                    ? "persistent runtime host application quit"
                    : "persistent runtime host destroyed before application quit");
        }

        private void CreatePersistentRuntimeHost()
        {
            if (!IsUnityNull(_runtimeHostObject) || !IsUnityNull(_runtimeHost))
            {
                throw new InvalidOperationException("Persistent runtime host already exists");
            }
            GameObject hostObject = null;
            try
            {
                hostObject = new GameObject("StrongholdEuropeDE.PersistentRuntimeHost");
                UnityObject.DontDestroyOnLoad(hostObject);
                hostObject.hideFlags = HideFlags.HideAndDontSave;
                StrongholdEuropePersistentHost host =
                    hostObject.AddComponent<StrongholdEuropePersistentHost>();
                host.Bind(this);
                _runtimeHostObject = hostObject;
                _runtimeHost = host;
                hostObject = null;
                Logger.LogInfo("Dedicated persistent runtime host created.");
            }
            finally
            {
                if (!IsUnityNull(hostObject))
                {
                    UnityObject.Destroy(hostObject);
                }
            }
        }

        private void InstallAudioPatch()
        {
            MethodInfo target = typeof(SFXManager).GetMethod(
                "InitSoundFX",
                BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly,
                null,
                Type.EmptyTypes,
                null);
            if (target == null || target.ReturnType != typeof(void))
            {
                throw new MissingMethodException("Exact SFXManager.InitSoundFX() target was not found");
            }
            MethodInfo postfix = typeof(StrongholdEuropeRuntimePlugin).GetMethod(
                "AudioInitPostfix",
                BindingFlags.NonPublic | BindingFlags.Static);
            if (postfix == null)
            {
                throw new MissingMethodException("Audio Harmony postfix is missing");
            }
            _harmony.Patch(target, postfix: new HarmonyMethod(postfix));
            InstallMusicRoutePatch();
        }

        private void InstallMusicRoutePatch()
        {
            MethodInfo target = typeof(SFXManager).GetMethod(
                "playMusic",
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly,
                null,
                new[]
                {
                    typeof(string),
                    typeof(float),
                    typeof(bool),
                    typeof(bool),
                    typeof(bool),
                    typeof(bool),
                },
                null);
            if (target == null || target.ReturnType != typeof(void))
            {
                throw new MissingMethodException(
                    "Exact SFXManager.playMusic(string, float, bool, bool, bool, bool) target was not found");
            }
            ParameterInfo[] parameters = target.GetParameters();
            // Harmony binds a prefix parameter to the target parameter of the
            // same name.  A renamed first parameter would silently stop the
            // rewrite, so require the exact name rather than discovering the
            // failure as "the music is still Crusader's".
            if (parameters.Length != 6
                || !string.Equals(parameters[0].Name, "fullpath", StringComparison.Ordinal)
                || parameters[0].ParameterType != typeof(string)
                || !string.Equals(parameters[1].Name, "gameVolume", StringComparison.Ordinal)
                || parameters[1].ParameterType != typeof(float)
                || !string.Equals(parameters[2].Name, "loop", StringComparison.Ordinal)
                || parameters[2].ParameterType != typeof(bool)
                || !string.Equals(parameters[3].Name, "followon", StringComparison.Ordinal)
                || parameters[3].ParameterType != typeof(bool)
                || !string.Equals(parameters[4].Name, "fadePrevious", StringComparison.Ordinal)
                || parameters[4].ParameterType != typeof(bool)
                || !string.Equals(parameters[5].Name, "restartOnSamePiece", StringComparison.Ordinal)
                || parameters[5].ParameterType != typeof(bool))
            {
                throw new MissingMethodException(
                    "SFXManager.playMusic(string, ...) does not expose the expected 'fullpath' parameter");
            }
            MethodInfo prefix = typeof(StrongholdEuropeRuntimePlugin).GetMethod(
                "MusicRoutePrefix",
                BindingFlags.NonPublic | BindingFlags.Static);
            if (prefix == null)
            {
                throw new MissingMethodException("Music route Harmony prefix is missing");
            }
            _harmony.Patch(target, prefix: new HarmonyMethod(prefix));
        }

        /// <summary>
        /// Haengt die Loewe-auf-Wolf-Umleitung ein (siehe WolfSpriteRoute).
        ///
        /// Bewusst ohne eigenes Profilflag: Ein Loewe gehoert in einer
        /// europaeischen Umsetzung nicht auf die Karte, und Crusaders
        /// Wolfsgrafik liegt ohnehin ungenutzt im Spiel. Ein Flag haette vier
        /// Dateien der Bauspur beruehrt, ohne eine Entscheidung offenzuhalten,
        /// die jemand treffen will.
        ///
        /// Bewusst **nicht** fail-closed: Diese Umleitung ist rein optisch.
        /// Wenn ein Spielpatch `addGMFile` umbenennt, soll das Ergebnis ein
        /// Loewe und eine deutliche Logzeile sein - nicht eine Runtime, die
        /// deshalb ihre Miliz- und Farmbahn mitreisst.
        /// </summary>
        private void InstallWolfSpriteRoute()
        {
            try
            {
                WolfSpriteRoute.Install(_harmony, name => AccessTools.TypeByName(name));
                Logger.LogInfo(
                    "SEDE_RUNTIME_V1|event=wolf_sprite_route|status=active"
                    + "|group=" + WolfSpriteRoute.LionGroup
                    + "|replaced_by=" + WolfSpriteRoute.WolfGroup
                    + "|gm=" + WolfSpriteRoute.GmBodyLion);
            }
            catch (Exception exception)
            {
                Logger.LogError(
                    "SEDE_RUNTIME_V1|event=wolf_sprite_route|status=failed_open"
                    + "|reason=" + exception.GetType().Name
                    + " - lions stay lions: " + exception.Message);
            }
        }

        private void InstallFarmResultPatch()
        {
            // The extender's detour writes our verdict into IsPlacementBlocked
            // and then returns the untouched native result. A measured session
            // showed the engine follows the return value, not the field, so we
            // correct it here.
            Type detours = AccessTools.TypeByName("SHCDESE.Detours.BulkBuildingDetours");
            if (detours == null)
            {
                throw new MissingMemberException(
                    "SHCDESE.Detours.BulkBuildingDetours was not found");
            }
            MethodInfo target = detours.GetMethod(
                "c_game_player_build_placement_validator_hook_impl",
                BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly);
            if (target == null || target.ReturnType != typeof(long))
            {
                throw new MissingMethodException(
                    "Exact placement-validator detour returning long was not found");
            }
            MethodInfo postfix = typeof(FarmPlacementController).GetMethod(
                "ValidatorPostfix",
                BindingFlags.NonPublic | BindingFlags.Static);
            if (postfix == null)
            {
                throw new MissingMethodException("Farm validator postfix is missing");
            }
            _harmony.Patch(target, postfix: new HarmonyMethod(postfix));
        }

        private void InstallDockResultPatch()
        {
            // Zweiter Postfix auf derselben Detour, und er ist noetig, weil der
            // Extender unsere Sicht nur in TileManager.IsPlacementBlocked
            // schreibt und danach den unveraenderten nativen Rueckgabewert
            // zurueckgibt. Dieser hier LIEST den Wert nur - er nimmt ihn nicht
            // per ref entgegen, damit er ihn gar nicht aendern kann.
            //
            // Zwei Postfixe auf einer Methode sind zulaessig, halten aber nur,
            // solange Farm- und Hafenbahn ueber die Mapper getrennt bleiben
            // (70-73 gegen 195-198). Wer sie spaeter zusammenlegt, setzt die
            // funktionierende Farmbahn aufs Spiel.
            Type detours = AccessTools.TypeByName("SHCDESE.Detours.BulkBuildingDetours");
            if (detours == null)
            {
                throw new MissingMemberException(
                    "SHCDESE.Detours.BulkBuildingDetours was not found");
            }
            MethodInfo target = detours.GetMethod(
                "c_game_player_build_placement_validator_hook_impl",
                BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly);
            if (target == null || target.ReturnType != typeof(long))
            {
                throw new MissingMethodException(
                    "Exact placement-validator detour returning long was not found");
            }
            MethodInfo postfix = typeof(DockPlacementController).GetMethod(
                "ValidatorPostfix",
                BindingFlags.NonPublic | BindingFlags.Static);
            if (postfix == null)
            {
                throw new MissingMethodException("Dock validator postfix is missing");
            }
            _harmony.Patch(target, postfix: new HarmonyMethod(postfix));
        }

        private static void AudioInitPostfix()
        {
            StrongholdEuropeRuntimePlugin plugin = _instance;
            if (!ReferenceEquals(plugin, null))
            {
                plugin.TryApplyAudioOverride();
            }
        }

        private static void MusicRoutePrefix(
            SFXManager __instance,
            ref string fullpath,
            float gameVolume,
            bool loop,
            bool followon,
            bool fadePrevious,
            bool restartOnSamePiece)
        {
            StrongholdEuropeRuntimePlugin plugin = _instance;
            if (ReferenceEquals(plugin, null) || !plugin.MusicRouteActive)
            {
                return;
            }
            string replacement;
            if (GeneratedPcmStreamContract.Enabled)
            {
                string vanillaFallback;
                if (MusicRouteRewriter.TryResolvePcmRoute(
                        fullpath,
                        out replacement,
                        out vanillaFallback)
                    || plugin.TryResolvePcmTableRoute(
                        fullpath,
                        out replacement,
                        out vanillaFallback))
                {
                    // CanRewriteTo atomically prepares the procedural clip and
                    // budget lease. A failure restores the untouched Crusader
                    // route before MyAudioManager observes the argument.
                    var originalRoute = new PcmOriginalMusicRoute(
                        vanillaFallback,
                        gameVolume,
                        loop,
                        followon,
                        fadePrevious,
                        restartOnSamePiece,
                        delegate(
                            string path,
                            float restartVolume,
                            bool restartLoop,
                            bool restartFollowon,
                            bool restartFadePrevious,
                            bool restartSamePiece)
                        {
                            if (ReferenceEquals(__instance, null)
                                || __instance == null)
                            {
                                throw new InvalidOperationException(
                                    "Original SFXManager owner no longer exists");
                            }
                            __instance.playMusic(
                                path,
                                restartVolume,
                                restartLoop,
                                restartFollowon,
                                restartFadePrevious,
                                restartSamePiece);
                        });
                    fullpath = PcmAudioStreamingLane.CanRewriteTo(
                            replacement,
                            originalRoute)
                        ? replacement
                        : vanillaFallback;
                }
                return;
            }
            if (MusicRouteRewriter.TryRewrite(fullpath, out replacement))
            {
                fullpath = replacement;
            }
        }

        private bool TryResolvePcmTableRoute(
            string fullpath,
            out string replacement,
            out string vanillaFallback)
        {
            replacement = null;
            vanillaFallback = null;
            RuntimeManifest manifest = _manifest;
            if (manifest == null || string.IsNullOrEmpty(fullpath))
            {
                return false;
            }
            string normalized = fullpath.Replace('/', '\\');
            foreach (AudioTrack track in manifest.Tracks)
            {
                if (!string.Equals(
                        normalized,
                        track.Replacement,
                        StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }
                replacement = track.Replacement;
                vanillaFallback = track.ExpectedOriginal;
                return true;
            }
            return false;
        }

        // Only rewrite once the table override is in force.  Before that the
        // volume entries for the eu_* replacements are not registered yet, and
        // after a rollback the payload must stop being reachable at all.
        private bool MusicRouteActive
        {
            get
            {
                return !_shuttingDown
                    && _audioApplied
                    && !_audioRejected;
            }
        }

        private void ValidateAudioPayload(string audioDirectory)
        {
            if (!Directory.Exists(audioDirectory)
                || Directory.GetDirectories(audioDirectory).Length != 0)
            {
                throw new DirectoryNotFoundException(
                    "Dedicated runtime music directory is missing or contains subdirectories: "
                    + audioDirectory);
            }

            string[] actualFiles = Directory.GetFiles(audioDirectory, "*", SearchOption.TopDirectoryOnly);
            if (actualFiles.Length != _manifest.Tracks.Length)
            {
                throw new InvalidDataException(
                    "Runtime music payload file count mismatch: expected="
                    + _manifest.Tracks.Length + " actual=" + actualFiles.Length);
            }
            HashSet<string> expectedNames = new HashSet<string>(StringComparer.Ordinal);
            foreach (AudioTrack track in _manifest.Tracks)
            {
                expectedNames.Add(track.OutputFile);
            }
            foreach (string actualPath in actualFiles)
            {
                if (!expectedNames.Remove(Path.GetFileName(actualPath)))
                {
                    throw new InvalidDataException(
                        "Unexpected file in runtime music directory: " + Path.GetFileName(actualPath));
                }
            }
            if (expectedNames.Count != 0)
            {
                throw new InvalidDataException("One or more runtime music files are missing");
            }

            foreach (AudioTrack track in _manifest.Tracks)
            {
                WavValidator.Validate(Path.Combine(audioDirectory, track.OutputFile), track);
            }
        }

        private void TryApplyAudioOverride()
        {
            lock (_gate)
            {
                if (_shuttingDown
                    || !_runtimeVerified
                    || _manifest == null
                    || !((_manifest.AudioPayload && _assetProviderRegistered)
                        || (GeneratedPcmStreamContract.Enabled
                            && _pcmAudioStreamingLane != null
                            && _pcmAudioStreamingLane.Ready))
                    || _audioApplied
                    || _audioRejected)
                {
                    return;
                }
                if (SFXManager.instance == null)
                {
                    return;
                }
                try
                {
                    ApplyAudioOverrideTransactional();
                    LogAudioTerminal("active");
                }
                catch (Exception exception)
                {
                    _audioRejected = true;
                    LogAudioTerminal("failed");
                    Logger.LogError(
                        "Music table validation failed closed; no partial table override remains: "
                        + exception);
                }
            }
        }

        private void ApplyAudioOverrideTransactional()
        {
            object manager = SFXManager.instance;
            if (manager == null)
            {
                return;
            }
            Type managerType = manager.GetType();
            if (managerType != typeof(SFXManager))
            {
                throw new InvalidOperationException("SFXManager singleton type is not exact");
            }

            FieldInfo musicField = managerType.GetField(
                "music_filenames",
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            FieldInfo volumeDictionaryField = managerType.GetField(
                "volumeData",
                BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            Type volumeType = managerType.GetNestedType(
                "VolumeData",
                BindingFlags.NonPublic);
            if (musicField == null
                || musicField.FieldType != typeof(string[])
                || volumeDictionaryField == null
                || volumeType == null)
            {
                throw new MissingMemberException("Exact SFXManager music fields were not found");
            }
            FieldInfo volumeNameField = volumeType.GetField(
                "name",
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            FieldInfo volumeValueField = volumeType.GetField(
                "volume",
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            if (volumeNameField == null
                || volumeNameField.FieldType != typeof(string)
                || volumeValueField == null
                || volumeValueField.FieldType != typeof(float))
            {
                throw new MissingMemberException("Exact SFXManager.VolumeData fields were not found");
            }

            string[] music = (string[])musicField.GetValue(manager);
            IDictionary volumeDictionary = volumeDictionaryField.GetValue(manager) as IDictionary;
            if (music == null || music.Length != 132 || volumeDictionary == null)
            {
                throw new InvalidDataException("SFXManager music table/dictionary shape is not exact");
            }

            Dictionary<int, string> originals = new Dictionary<int, string>();
            Dictionary<string, object> volumeObjects =
                new Dictionary<string, object>(StringComparer.Ordinal);
            foreach (AudioTrack track in _manifest.Tracks)
            {
                if (!string.Equals(
                    music[track.Id],
                    track.ExpectedOriginal,
                    StringComparison.Ordinal))
                {
                    throw new InvalidDataException(
                        "Music ID " + track.Id + " original mismatch: expected="
                        + track.ExpectedOriginal + " actual=" + music[track.Id]);
                }
                if (volumeDictionary.Contains(track.Replacement))
                {
                    throw new InvalidDataException(
                        "Music volume key is already owned by another component: "
                        + track.Replacement);
                }
                originals.Add(track.Id, music[track.Id]);
                object volumeObject = Activator.CreateInstance(volumeType, true);
                volumeNameField.SetValue(volumeObject, track.Replacement);
                volumeValueField.SetValue(volumeObject, track.VolumeRaw / 127f);
                volumeObjects.Add(track.Replacement, volumeObject);
            }

            List<string> addedKeys = new List<string>();
            List<int> changedIds = new List<int>();
            try
            {
                foreach (KeyValuePair<string, object> pair in volumeObjects)
                {
                    volumeDictionary.Add(pair.Key, pair.Value);
                    addedKeys.Add(pair.Key);
                }
                foreach (AudioTrack track in _manifest.Tracks)
                {
                    music[track.Id] = track.Replacement;
                    changedIds.Add(track.Id);
                }
            }
            catch
            {
                foreach (int id in changedIds)
                {
                    AudioTrack track = FindTrack(id);
                    if (string.Equals(music[id], track.Replacement, StringComparison.Ordinal))
                    {
                        music[id] = originals[id];
                    }
                }
                foreach (string key in addedKeys)
                {
                    if (volumeDictionary.Contains(key)
                        && RuntimeDecision.ShouldRestoreOwnedReference(
                            volumeDictionary[key],
                            volumeObjects[key]))
                    {
                        volumeDictionary.Remove(key);
                    }
                }
                throw;
            }

            _audioManager = manager;
            _musicFilenamesField = musicField;
            _volumeDataField = volumeDictionaryField;
            _originalMusic = originals;
            _ownedVolumeData = volumeObjects;
            _audioApplied = true;
        }

        private AudioTrack FindTrack(int id)
        {
            foreach (AudioTrack track in _manifest.Tracks)
            {
                if (track.Id == id)
                {
                    return track;
                }
            }
            throw new InvalidOperationException("Runtime track lookup failed for ID " + id);
        }

        /// <summary>
        /// Register every pinned vegetation group whose atlas we actually ship.
        /// </summary>
        /// <remarks>
        /// tree_apple keeps its own dedicated path - it is the proven one and
        /// carries the manifest flag. The remaining groups are additive: a name
        /// the loader does not know, or an atlas we did not build, is simply
        /// skipped, so shipping fewer groups never breaks startup.
        /// </remarks>
        private void CollectFoliageGroups()
        {
            foreach (string name in GeneratedFoliageContract.GroupNames)
            {
                if (string.Equals(name, "tree_apple", StringComparison.Ordinal))
                {
                    continue;
                }
                Enums.GM gmFileId;
                bool dashFormat;
                if (!GameAtlasManagerAPI.TryGetGMEnum(name, out gmFileId, out dashFormat))
                {
                    Logger.LogWarning(
                        "Foliage group is unknown to the loader and is skipped: " + name);
                    continue;
                }
                string atlasJson = Path.Combine(
                    _pluginDirectory, "Override", "Atlas", name, "atlas.json");
                FoliageGroup group = new FoliageGroup(name, (int)gmFileId, atlasJson);
                if (!group.ShipsAtlas)
                {
                    continue;
                }
                _foliageGroups.Add(group);
            }
            if (_foliageGroups.Count > 0)
            {
                _foliagePending = true;
            }
        }

        private void TryApplyFoliageOverride(object loader)
        {
            lock (_gate)
            {
                if (_shuttingDown || !_runtimeVerified || _manifest == null)
                {
                    return;
                }
                ApplyExtraFoliageGroups(loader);
                if (!_manifest.FoliageTreeApple
                    || !_foliagePending
                    || _foliageTerminalLogged
                    || _ownedFoliageMaterial != null)
                {
                    return;
                }
                try
                {
                    if (!ApplyFoliageOverrideTransactional(loader))
                    {
                        // spriteLoader.spritesLoaded becomes true before SHCDE-SE's
                        // GameAtlasManagerAPI has applied registered overrides.  The
                        // vanilla Foliage materials are therefore a normal transient
                        // state, not a validation failure.  Keep every reference
                        // untouched and poll until the exact LoadImage pair appears.
                        return;
                    }
                    _foliagePending = false;
                    LogFoliageTerminal(true);
                }
                catch (Exception exception)
                {
                    _foliagePending = false;
                    Logger.LogError(
                        "tree_apple foliage validation failed closed; materials were not changed: "
                        + exception);
                    LogFoliageTerminal(false);
                }
            }
        }

        /// <summary>
        /// Give every extra vegetation group its Foliage material once the
        /// loader has applied our atlas to it.
        /// </summary>
        /// <remarks>
        /// Each group is independent: one that is not ready yet is retried on
        /// the next tick, and one that throws is dropped without touching the
        /// others. A tree rendered through the wrong shader is a cosmetic
        /// defect - it must never take the session down.
        /// </remarks>
        private void RollbackExtraFoliageGroups()
        {
            if (_foliageGroups.Count == 0)
            {
                return;
            }
            Material[][] materials = null;
            if (_foliageLoader != null && _gmMaterialsField != null)
            {
                try
                {
                    materials = (Material[][])_gmMaterialsField.GetValue(_foliageLoader);
                }
                catch (Exception exception)
                {
                    Logger.LogError(
                        "Foliage material array was unreadable during rollback: " + exception);
                }
            }
            foreach (FoliageGroup group in _foliageGroups)
            {
                try
                {
                    group.Rollback(materials, _applicationQuitting);
                }
                catch (Exception exception)
                {
                    Logger.LogError(
                        "Foliage rollback failed for " + group.Name + ": " + exception);
                }
            }
            _foliageGroups.Clear();
        }

        private void ApplyExtraFoliageGroups(object loader)
        {
            if (_foliageGroups.Count == 0
                || loader == null
                || loader.GetType() != typeof(spriteLoader))
            {
                return;
            }
            FieldInfo materialsField = loader.GetType().GetField(
                "gmMaterials",
                BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            FieldInfo spritesField = loader.GetType().GetField(
                "gmSprites",
                BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            if (materialsField == null
                || materialsField.FieldType != typeof(Material[][])
                || spritesField == null
                || spritesField.FieldType != typeof(Sprite[][]))
            {
                return;
            }
            Material[][] materials = (Material[][])materialsField.GetValue(loader);
            Sprite[][] sprites = (Sprite[][])spritesField.GetValue(loader);
            if (materials == null || sprites == null)
            {
                return;
            }
            for (int index = _foliageGroups.Count - 1; index >= 0; index--)
            {
                FoliageGroup group = _foliageGroups[index];
                if (group.Applied
                    || group.GmIndex < 0
                    || group.GmIndex >= materials.Length
                    || group.GmIndex >= sprites.Length)
                {
                    continue;
                }
                try
                {
                    if (group.TryApply(materials, sprites, MaterialSlotCount))
                    {
                        _foliageLoader = loader;
                        _gmMaterialsField = materialsField;
                        Logger.LogInfo(
                            RuntimeLogContract.FoliageGroupApplied(group.Name));
                    }
                }
                catch (Exception exception)
                {
                    _foliageGroups.RemoveAt(index);
                    Logger.LogError(
                        "Foliage material for " + group.Name
                        + " failed closed and was skipped: " + exception);
                }
            }
        }

        private bool ApplyFoliageOverrideTransactional(object loader)
        {
            if (loader == null || loader.GetType() != typeof(spriteLoader))
            {
                throw new InvalidOperationException("ready spriteLoader instance is not exact");
            }
            FieldInfo materialsField = loader.GetType().GetField(
                "gmMaterials",
                BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            FieldInfo spritesField = loader.GetType().GetField(
                "gmSprites",
                BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            if (materialsField == null || materialsField.FieldType != typeof(Material[][]))
            {
                throw new MissingFieldException("Exact spriteLoader.gmMaterials field was not found");
            }
            if (spritesField == null || spritesField.FieldType != typeof(Sprite[][]))
            {
                throw new MissingFieldException("Exact spriteLoader.gmSprites field was not found");
            }
            Material[][] outer = (Material[][])materialsField.GetValue(loader);
            Sprite[][] spriteOuter = (Sprite[][])spritesField.GetValue(loader);
            if (outer == null
                || outer.Length != 234
                || spriteOuter == null
                || spriteOuter.Length != 234
                || TreeAppleGmIndex >= outer.Length)
            {
                throw new InvalidDataException(
                    "spriteLoader GM material/sprite outer shapes are not exact");
            }
            Material[] current = outer[TreeAppleGmIndex];
            Sprite[] currentSprites = spriteOuter[TreeAppleGmIndex];
            bool allTeamColour = current != null && current.Length == MaterialSlotCount;
            bool allShareMask = allTeamColour;
            Texture teamMask = null;
            if (allTeamColour)
            {
                for (int index = 0; index < current.Length; index++)
                {
                    Material material = current[index];
                    if (IsUnityNull(material)
                        || IsUnityNull(material.shader)
                        || !string.Equals(material.shader.name, TeamColourShader, StringComparison.Ordinal)
                        || !material.HasProperty(TeamMaskProperty))
                    {
                        allTeamColour = false;
                        allShareMask = false;
                        break;
                    }
                    Texture candidateMask = material.GetTexture(TeamMaskProperty);
                    if (IsUnityNull(candidateMask))
                    {
                        allShareMask = false;
                        break;
                    }
                    if (index == 0)
                    {
                        teamMask = candidateMask;
                    }
                    else if (!ReferenceEquals(teamMask, candidateMask))
                    {
                        allShareMask = false;
                        break;
                    }
                }
            }

            Texture2D mainAtlas = null;
            bool allSpritesShareMainAtlas =
                currentSprites != null && currentSprites.Length == TreeAppleSpriteCount;
            if (allSpritesShareMainAtlas)
            {
                for (int index = 0; index < currentSprites.Length; index++)
                {
                    Sprite sprite = currentSprites[index];
                    Texture2D candidate = IsUnityNull(sprite) ? null : sprite.texture;
                    if (IsUnityNull(candidate))
                    {
                        allSpritesShareMainAtlas = false;
                        break;
                    }
                    if (index == 0)
                    {
                        mainAtlas = candidate;
                    }
                    else if (!ReferenceEquals(mainAtlas, candidate))
                    {
                        allSpritesShareMainAtlas = false;
                        break;
                    }
                }
            }
            Texture2D maskAtlas = teamMask as Texture2D;
            bool exactAtlasTextures = allSpritesShareMainAtlas
                && !IsUnityNull(mainAtlas)
                && !IsUnityNull(maskAtlas)
                && !ReferenceEquals(mainAtlas, maskAtlas)
                && string.Equals(
                    mainAtlas.name,
                    TreeAppleAtlasTextureName,
                    StringComparison.Ordinal)
                && string.Equals(
                    maskAtlas.name,
                    TreeAppleMaskTextureName,
                    StringComparison.Ordinal)
                && mainAtlas.width == TreeAppleAtlasWidth
                && mainAtlas.height == TreeAppleAtlasHeight
                && maskAtlas.width == TreeAppleAtlasWidth
                && maskAtlas.height == TreeAppleAtlasHeight
                && mainAtlas.isReadable
                && maskAtlas.isReadable;

            Shader foliage = Shader.Find(FoliageShader);
            bool foliageAvailable = !IsUnityNull(foliage);
            if (!_runtimeVerified
                || _manifest == null
                || !_manifest.FoliageTreeApple
                || !File.Exists(_treeAppleAtlasPath))
            {
                throw new InvalidOperationException(
                    "tree_apple fixed runtime/manifest/path guards changed after initialization");
            }
            if (!RuntimeDecision.ShouldApplyFoliage(
                _runtimeVerified,
                _manifest.FoliageTreeApple,
                File.Exists(_treeAppleAtlasPath),
                current == null ? -1 : current.Length,
                allTeamColour,
                allShareMask,
                foliageAvailable,
                exactAtlasTextures))
            {
                return false;
            }

            Material owned = null;
            try
            {
                owned = new Material(foliage);
                owned.name = "StrongholdEuropeDE tree_apple foliage";
                owned.SetTexture(TeamMaskProperty, maskAtlas);
                Material[] replacement = new Material[MaterialSlotCount];
                for (int index = 0; index < replacement.Length; index++)
                {
                    replacement[index] = owned;
                }
                if (!ReferenceEquals(outer[TreeAppleGmIndex], current))
                {
                    throw new InvalidOperationException("tree_apple material array changed during validation");
                }
                mainAtlas.Apply(false, true);
                maskAtlas.Apply(false, true);
                if (mainAtlas.isReadable || maskAtlas.isReadable)
                {
                    throw new InvalidOperationException(
                        "tree_apple atlas CPU copies remained readable after finalization");
                }
                outer[TreeAppleGmIndex] = replacement;

                _foliageLoader = loader;
                _gmMaterialsField = materialsField;
                _originalFoliageMaterials = current;
                _replacementFoliageMaterials = replacement;
                _ownedFoliageMaterial = owned;
                owned = null;
                return true;
            }
            finally
            {
                if (!IsUnityNull(owned))
                {
                    UnityObject.Destroy(owned);
                }
            }
        }

        private void ShutdownAndRollback(string reason)
        {
            lock (_gate)
            {
                bool preserveFailClosedRuntimeHooks = false;
                if (!RuntimeDecision.TryBeginShutdown(ref _shuttingDown))
                {
                    return;
                }
                Logger.LogWarning("Runtime shutdown requested: " + reason);
                if (_foliagePending && !_foliageTerminalLogged)
                {
                    _foliagePending = false;
                    LogFoliageTerminal(false);
                }
                if (_manifest != null
                    && (_manifest.AudioPayload
                        || GeneratedPcmStreamContract.Enabled)
                    && !_audioTerminalLogged)
                {
                    LogAudioTerminal("failed");
                }
                if (_buildingPlacementGrid != null)
                {
                    try
                    {
                        _buildingPlacementGrid.Rollback();
                    }
                    catch (Exception exception)
                    {
                        Logger.LogError(
                            "Building placement grid rollback encountered an error: "
                            + exception);
                    }
                    _buildingPlacementGrid = null;
                }
                if (_extensionHost != null)
                {
                    try
                    {
                        _extensionHost.RollbackAll();
                    }
                    catch (Exception exception)
                    {
                        Logger.LogError(
                            "Gameplay extension rollback encountered an error: "
                            + exception);
                    }
                    preserveFailClosedRuntimeHooks = _diplomacy != null
                        && _diplomacy.RequiresFailClosedHooks;
                    if (preserveFailClosedRuntimeHooks)
                    {
                        Logger.LogError(
                            "Diplomacy native rollback remains unproven; "
                            + "retaining runtime hooks and save recovery "
                            + "while the game is paused.");
                    }
                    _extensionHost = null;
                    _workerMilitia = null;
                    _diplomacy = null;
                    _fortifications = null;
                }
                if (_assetStreamLane != null)
                {
                    try
                    {
                        _assetStreamLane.Rollback(_applicationQuitting);
                    }
                    catch (Exception exception)
                    {
                        Logger.LogError(
                            "Asset-stream rollback encountered an error: "
                            + exception);
                    }
                    _assetStreamLane = null;
                }
                if (_pcmAudioStreamingLane != null)
                {
                    try
                    {
                        _pcmAudioStreamingLane.Rollback(
                            _applicationQuitting);
                    }
                    catch (Exception exception)
                    {
                        Logger.LogError(
                            "PCM streaming rollback encountered an error: "
                            + exception);
                    }
                    _pcmAudioStreamingLane = null;
                }
                if (_harmony != null)
                {
                    if (_luaStateGuardInstalled)
                    {
                        Logger.LogInfo(
                            ScriptExtenderLuaStateGuardPatch.SummaryEvent());
                        _luaStateGuardInstalled = false;
                    }
                    try
                    {
                        if (!preserveFailClosedRuntimeHooks)
                        {
                            _harmony.UnpatchSelf();
                        }
                    }
                    catch (Exception exception)
                    {
                        Logger.LogError("Failed to remove Harmony patches: " + exception);
                    }
                }
                if (_rosterController != null)
                {
                    try
                    {
                        _rosterController.RollbackOwned(_applicationQuitting);
                    }
                    catch (Exception exception)
                    {
                        Logger.LogError("Roster rollback encountered an error: " + exception);
                    }
                    _rosterController = null;
                }
                if (_farmController != null)
                {
                    // Report before detaching: the counts are the only evidence that
                    // the rule was reached at all during the session.
                    Logger.LogInfo(
                        RuntimeLogContract.FarmPlacementSummary(
                            _farmController.AllowedCount,
                            _farmController.BlockedCount));
                    if (_farmController.Failed && !_farmTerminalLogged)
                    {
                        LogFarmTerminal("failed");
                    }
                    _farmController.Rollback();
                    _farmController = null;
                }
                if (_dockController != null)
                {
                    // Wie bei der Farmregel: erst berichten, dann abhaengen. Die
                    // beiden Zahlen sind der einzige Beleg, dass die Messung die
                    // Hafenkacheln ueberhaupt zu sehen bekam.
                    Logger.LogInfo(
                        RuntimeLogContract.DockPlacementSummary(
                            _dockController.TileCount,
                            _dockController.WaterTileCount,
                            _dockController.BlockedTileCount));
                    if (_dockController.Failed && !_dockTerminalLogged)
                    {
                        LogDockTerminal("failed");
                    }
                    _dockController.Rollback();
                    _dockController = null;
                }
                RollbackAudio();
                UiTextureLoadTexturePatch.LogSummary();
                RollbackExtraFoliageGroups();
                RollbackFoliage();
                if (_assetProviderRegistered)
                {
                    Logger.LogInfo(
                        "The SHCDE-SE audio index is process-lifetime; its unique eu_* entries are now inert because the music table was restored.");
                }
                if (ReferenceEquals(_instance, this))
                {
                    _instance = null;
                }
                GameObject runtimeHostObject = _runtimeHostObject;
                _runtimeHostObject = null;
                _runtimeHost = null;
                if (!IsUnityNull(runtimeHostObject))
                {
                    UnityObject.Destroy(runtimeHostObject);
                }
            }
        }

        private void RollbackAudio()
        {
            if (!_audioApplied || _audioManager == null)
            {
                return;
            }
            try
            {
                string[] music = (string[])_musicFilenamesField.GetValue(_audioManager);
                IDictionary volumeDictionary = _volumeDataField.GetValue(_audioManager) as IDictionary;
                if (music != null)
                {
                    foreach (AudioTrack track in _manifest.Tracks)
                    {
                        string original;
                        if (_originalMusic.TryGetValue(track.Id, out original)
                            && track.Id < music.Length
                            && string.Equals(music[track.Id], track.Replacement, StringComparison.Ordinal))
                        {
                            music[track.Id] = original;
                        }
                    }
                }
                if (volumeDictionary != null)
                {
                    foreach (KeyValuePair<string, object> pair in _ownedVolumeData)
                    {
                        if (volumeDictionary.Contains(pair.Key)
                            && RuntimeDecision.ShouldRestoreOwnedReference(
                                volumeDictionary[pair.Key],
                                pair.Value))
                        {
                            volumeDictionary.Remove(pair.Key);
                        }
                    }
                }
            }
            catch (Exception exception)
            {
                Logger.LogError("Music rollback encountered an error: " + exception);
            }
            finally
            {
                _audioApplied = false;
                _originalMusic = new Dictionary<int, string>();
                _ownedVolumeData = new Dictionary<string, object>(StringComparer.Ordinal);
            }
        }

        private void RollbackFoliage()
        {
            Material owned = _ownedFoliageMaterial;
            if (IsUnityNull(owned))
            {
                return;
            }
            try
            {
                Material[][] outer = _gmMaterialsField.GetValue(_foliageLoader) as Material[][];
                if (outer != null && TreeAppleGmIndex < outer.Length)
                {
                    Material[] current = outer[TreeAppleGmIndex];
                    if (current != null)
                    {
                        int limit = Math.Min(
                            current.Length,
                            _originalFoliageMaterials.Length);
                        for (int index = 0; index < limit; index++)
                        {
                            if (RuntimeDecision.ShouldRestoreOwnedReference(current[index], owned))
                            {
                                current[index] = _originalFoliageMaterials[index];
                            }
                        }
                        bool completelyRestored = current.Length == _originalFoliageMaterials.Length;
                        for (int index = 0; completelyRestored && index < current.Length; index++)
                        {
                            completelyRestored = ReferenceEquals(
                                current[index],
                                _originalFoliageMaterials[index]);
                        }
                        if (ReferenceEquals(current, _replacementFoliageMaterials)
                            && completelyRestored)
                        {
                            outer[TreeAppleGmIndex] = _originalFoliageMaterials;
                        }
                    }
                }
            }
            catch (Exception exception)
            {
                Logger.LogError("tree_apple material rollback encountered an error: " + exception);
            }
            finally
            {
                UnityObject.Destroy(owned);
                _ownedFoliageMaterial = null;
                _replacementFoliageMaterials = null;
                _originalFoliageMaterials = null;
                _foliageLoader = null;
                _gmMaterialsField = null;
            }
        }

        private static bool IsUnityNull(UnityObject value)
        {
            return value == null;
        }

        private void LogRuntimeTerminal(bool initialized)
        {
            if (_runtimeTerminalLogged)
            {
                return;
            }
            _runtimeTerminalLogged = true;
            if (initialized)
            {
                Logger.LogInfo(RuntimeLogContract.Initialized);
            }
            else
            {
                Logger.LogError(RuntimeLogContract.InitializationFailed);
            }
        }

        private void LogAudioTerminal(string status)
        {
            if (_audioTerminalLogged)
            {
                return;
            }
            _audioTerminalLogged = true;
            if (string.Equals(status, "inactive", StringComparison.Ordinal))
            {
                Logger.LogInfo(RuntimeLogContract.AudioInactive);
                Logger.LogInfo(RuntimeLogContract.MusicRouteInactive);
            }
            else if (string.Equals(status, "active", StringComparison.Ordinal))
            {
                Logger.LogInfo(RuntimeLogContract.AudioActive);
                Logger.LogInfo(
                    RuntimeLogContract.MusicRouteActive(
                        MusicRouteRewriter.Count,
                        GeneratedMusicRouteContract.MapSha256));
            }
            else
            {
                // No separate music_route line here: the rewrite is gated on
                // the table override having been applied, so a failed audio
                // lane already states that the route is inert.
                Logger.LogError(RuntimeLogContract.AudioFailed);
            }
        }

        private void LogFarmTerminal(string status)
        {
            if (_farmTerminalLogged)
            {
                return;
            }
            _farmTerminalLogged = true;
            if (string.Equals(status, "inactive", StringComparison.Ordinal))
            {
                Logger.LogInfo(RuntimeLogContract.FarmPlacementInactive);
            }
            else if (string.Equals(status, "active", StringComparison.Ordinal))
            {
                Logger.LogInfo(RuntimeLogContract.FarmPlacementActive);
            }
            else
            {
                Logger.LogError(RuntimeLogContract.FarmPlacementFailed);
            }
        }

        private void LogDockTerminal(string status)
        {
            if (_dockTerminalLogged)
            {
                return;
            }
            _dockTerminalLogged = true;
            if (string.Equals(status, "inactive", StringComparison.Ordinal))
            {
                Logger.LogInfo(RuntimeLogContract.DockPlacementInactive);
            }
            else if (string.Equals(status, "active", StringComparison.Ordinal))
            {
                // Waehlt selbst zwischen mode=measure und mode=enforce - die
                // Aktivzeile MUSS sich aendern, wenn ein Stand den Hafen
                // tatsaechlich abweist.
                Logger.LogInfo(RuntimeLogContract.DockPlacementActiveLine());
            }
            else
            {
                Logger.LogError(RuntimeLogContract.DockPlacementFailed);
            }
        }

        private void LogWorkerMilitiaTerminal(string status)
        {
            if (string.Equals(status, "failed", StringComparison.Ordinal))
            {
                if (_workerMilitiaFailureLogged)
                {
                    return;
                }
                _workerMilitiaFailureLogged = true;
                Logger.LogError(RuntimeLogContract.WorkerMilitiaFailed);
                return;
            }
            if (_workerMilitiaTerminalLogged)
            {
                return;
            }
            _workerMilitiaTerminalLogged = true;
            if (string.Equals(status, "active", StringComparison.Ordinal))
            {
                Logger.LogInfo(RuntimeLogContract.WorkerMilitiaActiveLine());
            }
            else
            {
                Logger.LogInfo(RuntimeLogContract.WorkerMilitiaInactive);
            }
        }

        private void LogDiplomacyTerminal(string status, string reason)
        {
            if (_diplomacyTerminalLogged)
            {
                return;
            }
            _diplomacyTerminalLogged = true;
            string line = "SEDE_RUNTIME_V1|lane=diplomacy|event=feature"
                + "|status=" + status;
            if (!string.IsNullOrEmpty(reason))
            {
                line += "|reason=" + reason.Replace('|', ' ')
                    .Replace('\r', ' ').Replace('\n', ' ');
            }
            if (string.Equals(status, "failed", StringComparison.Ordinal))
            {
                Logger.LogError(line);
            }
            else
            {
                Logger.LogInfo(line);
            }
        }

        private void LogFortificationsTerminal(string status, string reason)
        {
            if (_fortificationsTerminalLogged)
            {
                return;
            }
            _fortificationsTerminalLogged = true;
            string line = "SEDE_RUNTIME_V1|lane=fortifications|event=feature"
                + "|status=" + status;
            if (!string.IsNullOrEmpty(reason))
            {
                line += "|reason=" + reason.Replace('|', ' ')
                    .Replace('\r', ' ').Replace('\n', ' ');
            }
            if (string.Equals(status, "failed", StringComparison.Ordinal))
            {
                Logger.LogError(line);
            }
            else
            {
                Logger.LogInfo(line);
            }
        }

        private ExtensionFeatureSnapshot FindExtensionSnapshot(string id)
        {
            if (_extensionHost == null)
            {
                return null;
            }
            foreach (ExtensionFeatureSnapshot snapshot in _extensionHost.Snapshot())
            {
                if (string.Equals(snapshot.Id, id, StringComparison.Ordinal))
                {
                    return snapshot;
                }
            }
            return null;
        }

        private void LogFoliageTerminal(bool succeeded)
        {
            if (_foliageTerminalLogged)
            {
                return;
            }
            _foliageTerminalLogged = true;
            if (succeeded)
            {
                Logger.LogInfo(RuntimeLogContract.FoliageSucceeded);
            }
            else
            {
                Logger.LogError(RuntimeLogContract.FoliageFailed);
            }
        }

        private void LogFoliageInactive()
        {
            if (_foliageTerminalLogged)
            {
                return;
            }
            _foliageTerminalLogged = true;
            Logger.LogInfo(RuntimeLogContract.FoliageInactive);
        }
    }
}
