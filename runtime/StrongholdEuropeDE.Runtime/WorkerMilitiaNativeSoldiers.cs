using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using CrusaderDE;
using HarmonyLib;
using R3;
using SHCDESE.API;
using SHCDESE.API.Components.SaveData;
using SHCDESE.API.Components.Timer;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.MapLoader;
using SHCDESE.EventAPI.Tribes;
using SHCDESE.EventAPI.Units;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Worker militia as native soldiers: a mobilized hunter IS an archer and
    /// a mobilized woodcutter IS a maceman for the engine, until it goes back
    /// to work.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Why (user decision 2026-09-28): selection, troop panel, formations,
    /// walls and towers, attacking a target in range, walking/shooting
    /// animation are all things the engine already does for soldiers.
    /// </para>
    /// <para>
    /// Mechanism (CrusaderDE.dll 2.80, measured 2026-09-28): 0x195C70(unit
    /// manager, id) turns a LIVING unit into the type stored in +0x2C6 with the
    /// AI start state in +0x2C8 and runs the per-type initialiser 0x19A1A0.
    /// Unit id, global id, owner, position and employer (+0x394) are kept. The
    /// per-unit tick reaches it through alive state 4; the engine also calls it
    /// directly outside the tick (0x6F60C, 0x6D82A). The militia calls it
    /// directly, so a worker is a soldier in the same frame in which the
    /// player's order click reaches the engine: the order is then a native
    /// soldier order (formation, walls, attack) and nothing has to be replayed.
    /// Without a proven layout the militia falls back to alive state 4 and
    /// the first order click only mobilizes.
    /// </para>
    /// <para>
    /// Triggers (user feedback 2026-09-28): work is interrupted only by a move
    /// or attack order to selected workers, or by an enemy soldier in sight.
    /// Selecting alone changes nothing. A militiaman goes back to work by
    /// itself when no enemy is near and it stands idle, or at once with the
    /// troop panel's disband button.
    /// </para>
    /// <para>
    /// Job slot (measured 2026-09-28): a hut counts its worker only while slot
    /// id, slot global id and the worker's employer field +0x394 agree
    /// (0xC9500); otherwise its recount (0xC9850) frees the slot and the hut
    /// hires a peasant. Coming back, the militiaman reclaims its slot the way
    /// the engine assigns one (0xB6280); a replacement hired meanwhile goes
    /// back to the peasants.
    /// </para>
    /// <para>
    /// Unit ids: SE's span starts at unit 1 (GameUnitManagerAPI:
    /// GameUnitArray + sizeof(GameUnit)); span[i] is native unit i + 1. All
    /// ids here are native ids (tribes, damage events and the engine use them).
    /// </para>
    /// <para>
    /// Threads: everything that writes a unit runs in a prefix of
    /// EngineInterface.TroopSelection, which run() calls under
    /// EngineInterface.threadLock right before DLL_RunTick. The projectile
    /// hook is a raw SE context hook (raising any managed exception there kills
    /// the game): it reads one byte array and nothing else.
    /// </para>
    /// </remarks>
    internal sealed class WorkerMilitiaNativeSoldiers : IExtensionFeature
    {
        internal const string FeatureId = "unit.worker_militia";
        private const string SaveDataIdentifier =
            "StrongholdEuropeDE.WorkerMilitia.Native.v1";
        private const int SaveVersion = 1;

        private const short AliveTransformPending = 4;
        private const ushort StartAiState = 0;
        private const ushort SelectableMarker = 1;
        private const int MaxUnitId = 10000;
        private const int FirstPlayer = 1;
        private const int LastPlayer = 8;
        private const int UnitStride = 0x490;
        private const int UnitArrayOffset = 0x65C;
        private const int TransformTimeoutRuns = 400;
        private const int MaxFieldDiagnostics = 8;
        private const int MaxHutSlots = 4;

        // Raw unit fields without an SE name (offsets inside GameUnit).
        private const int UnitSlotIndexOffset = 0x392;
        private const int UnitEmployerOffset = 0x394;
        // Raw hut fields (offsets inside GameBuilding).
        private const int HutWorkersRequiredOffset = 0x198;
        private const int HutWorkerIdOffset = 0x19E;
        private const int HutWorkerGlobalIdOffset = 0x1A8;

        // Distances in local tiles (world position / 8, SE ToLocalPosition).
        // 2026-09-28: the first build used 54 for the hunter, i.e. half the
        // map; every hunter on the map turned soldier as soon as an enemy
        // walked in anywhere. Sight is now a few screens' worth of tiles.
        internal const int HunterSightTiles = 14;
        internal const int WoodcutterSightTiles = 8;
        internal const int HunterPursuitTiles = 20;
        internal const int WoodcutterPursuitTiles = 12;
        // Back to work: no enemy within pursuit range for QuietRelease game
        // milliseconds AND not moved for the idle time.
        internal const int QuietReleaseMilliseconds = 10000;
        internal const int OrderedIdleReleaseMilliseconds = 20000;
        internal const int ThreatIdleReleaseMilliseconds = 4000;
        internal const int RemobilizeCooldownMilliseconds = 6000;
        private const int ScanIntervalMilliseconds = 250;

        private static readonly object OwnerGate = new object();
        private static WorkerMilitiaNativeSoldiers _owner;

        // Read without a lock from the projectile context hook. Index = native
        // unit id, 1 = damage of this unit is scaled.
        private static readonly byte[] ScaledAttackers = new byte[MaxUnitId + 1];

        private readonly Harmony _harmony;
        private readonly Action<string> _info;
        private readonly Action<string> _warning;
        private readonly Action<string> _error;
        private readonly object _gate = new object();
        private readonly Dictionary<int, Militiaman> _militia =
            new Dictionary<int, Militiaman>();
        private readonly Dictionary<int, GameTimeStamp> _cooldown =
            new Dictionary<int, GameTimeStamp>();
        private readonly List<Militiaman> _restoredFromSave =
            new List<Militiaman>();
        private readonly HashSet<string> _evidence =
            new HashSet<string>(StringComparer.Ordinal);
        private readonly List<int> _tribeMembers = new List<int>();
        private readonly List<int> _pendingDissolveTribes = new List<int>();
        private readonly List<Threat> _threats = new List<Threat>(256);
        private readonly List<int> _gesture = new List<int>();
        private readonly List<int> _scratch = new List<int>();
        private readonly List<int> _boxCandidates = new List<int>();

        private MethodInfo _selectionTarget;
        private MethodInfo _canPlaceTarget;
        private IDisposable _mapStartSubscription;
        private IDisposable _mapUnloadSubscription;
        private IDisposable _meleeSubscription;
        private IDisposable _projectileSubscription;
        private IDisposable _tribeTargetSubscription;
        private OwnedValueMutation<bool> _hunterHutAvailability;
        private NativeTransformUnit _nativeTransform;
        private NativeUnitSelectionMarkerClear _nativeMarkerClear;
        private NativePlayerSelectionClear _nativePlayerSelectionClear;
        private WorkerMilitiaTroopPanel _troopPanel;
        private WorkerMilitiaAppearance _appearance;
        private Action<int> _deselect;
        private int _deselectPlayer;
        private IntPtr _unitManager;
        private object _engineLock;
        private bool _directVerified;
        private bool _saveHandlerRegistered;
        private bool _patched;
        private bool _prepared;
        private volatile bool _mapActive;
        private int _lastScanTick;
        private int _bypassDissolveTribe;
        private int _runCounter;
        private int _fieldDiagnostics;
        private bool _gestureOpen;

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        private delegate int NativeTransformUnit(IntPtr unitManager, int unitId);

        // 0x186B80(manager, id): clears the box marker +0x30, manager+0x20--.
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        private delegate void NativeUnitSelectionMarkerClear(IntPtr unitManager, int unitId);

        // 0x19A530(manager, player, id, 0): takes one unit out of the player
        // selection (+0xAE, selection tribe, player counter).
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        private delegate void NativePlayerSelectionClear(IntPtr unitManager, int player, int unitId, int mode);

        private enum Phase
        {
            Mobilizing,
            Active,
            Demobilizing,
        }

        private sealed class Militiaman
        {
            internal int UnitId;
            internal uint GlobalId;
            internal eChimps WorkerType;
            internal eChimps TargetType;
            internal ushort WorkLink;
            internal uint WorkerMaxHealth;
            internal uint Health;
            internal bool Ordered;
            internal bool DisbandRequested;
            internal Phase Phase;
            internal int PhaseStartRun;
            internal GameTimeStamp LastThreat;
            internal GameTimeStamp LastMoved;
            internal ushort LastTileX;
            internal ushort LastTileY;
        }

        private struct Threat
        {
            internal int X;
            internal int Y;
        }

        internal WorkerMilitiaNativeSoldiers(
            Harmony harmony,
            Action<string> info,
            Action<string> warning,
            Action<string> error)
        {
            _harmony = harmony ?? throw new ArgumentNullException("harmony");
            _info = info ?? throw new ArgumentNullException("info");
            _warning = warning ?? throw new ArgumentNullException("warning");
            _error = error ?? throw new ArgumentNullException("error");
        }

        public string Id
        {
            get { return FeatureId; }
        }

        public IReadOnlyList<ExtensionLeaseClaim> ExclusiveClaims
        {
            get
            {
                return new[]
                {
                    ExtensionLeaseClaim.Unit((int)eChimps.CHIMP_TYPE_HUNTER),
                    ExtensionLeaseClaim.Unit((int)eChimps.CHIMP_TYPE_WOODCUTTER),
                    ExtensionLeaseClaim.Hook("EngineInterface.TroopSelection"),
                    ExtensionLeaseClaim.Hook(
                        "SHCDESE.EventAPI.UnitR3EventHooks.OnUnitTakeProjectileDamageEx"),
                    ExtensionLeaseClaim.Hook(
                        "SHCDESE.EventAPI.UnitR3EventHooks.OnUnitTakeMeleeDamage"),
                    ExtensionLeaseClaim.Hook(
                        "SHCDESE.EventAPI.TribeR3EventHooks.OnTribeIssueOrderWithTarget"),
                    ExtensionLeaseClaim.Mapper((int)eMappers.MAPPER_HUNTER),
                    ExtensionLeaseClaim.Hook("CrusaderDE.MainViewModel.CanPlaceMapper"),
                };
            }
        }

        public bool Prepare(out string failure)
        {
            if (!Field("r_AliveState", 0x88)
                || !Field("r_UnitChimp", 0x8A)
                || !Field("r_ControllableForPlayerId", 0x92)
                || !Field("r_GlobalId", 0x94)
                || !Field("r_UnitSelected", 0xAE)
                || !Field("r_CurrentWorldPositionX", 0xB2)
                || !Field("r_CurrentWorldPositionY", 0xB4)
                || !Field("N0000019A", 0x29C)
                || !Field("N000000A7", 0x2A0)
                || !Field("r_AIState", 0x2BC)
                || !Field("r_TransformIntoUnitOfType", 0x2C6)
                || !Field("N000000AC", 0x2C8)
                || !Field("r_CurrentHealthPercentage", 0x2D0)
                || !Field("r_LinkedProductionBuildingId", 0x334)
                || !Field("r_CurrentHealth", 0x3C4)
                || !Field("r_MaxHealth", 0x3C8)
                || !Field("r_HealthBarBlocks", 0x34)
                || Marshal.SizeOf(typeof(GameUnit)) != UnitStride
                || !BuildingField("r_AliveState", 0xD0)
                || !BuildingField("r_PlayerIdOwner", 0xD6)
                || !BuildingField("r_TotalWorkersRequired", HutWorkersRequiredOffset)
                || !BuildingField("r_WorkerId_1", HutWorkerIdOffset))
            {
                failure = "GameUnit/GameBuilding layout differs from the measured militia fields";
                return false;
            }
            if ((int)eChimps.CHIMP_TYPE_WOODCUTTER != 3
                || (int)eChimps.CHIMP_TYPE_HUNTER != 6
                || (int)eChimps.CHIMP_TYPE_ARCHER != 22
                || (int)eChimps.CHIMP_TYPE_MACEMAN != 26
                || (int)eChimps.CHIMP_TYPE_PEASANT != 1)
            {
                failure = "eChimps numbering changed";
                return false;
            }
            try
            {
                _selectionTarget = typeof(EngineInterface).GetMethod(
                    "TroopSelection",
                    BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly,
                    null,
                    new[]
                    {
                        typeof(int), typeof(bool), typeof(bool), typeof(int[]),
                        typeof(bool), typeof(bool), typeof(int[]), typeof(int),
                        typeof(int), typeof(bool), typeof(int[]),
                    },
                    null);
                _canPlaceTarget = typeof(MainViewModel).GetMethod(
                    "CanPlaceMapper",
                    BindingFlags.Public | BindingFlags.Instance
                        | BindingFlags.DeclaredOnly,
                    null,
                    new[] { typeof(object) },
                    null);
                FieldInfo lockField = typeof(EngineInterface).GetField(
                    "threadLock",
                    BindingFlags.NonPublic | BindingFlags.Static);
                _engineLock = lockField == null ? null : lockField.GetValue(null);
            }
            catch (Exception exception)
            {
                failure = "managed targets unavailable: " + exception.Message;
                return false;
            }
            if (_selectionTarget == null || _canPlaceTarget == null || _engineLock == null)
            {
                failure = "EngineInterface.TroopSelection, threadLock or CanPlaceMapper not found";
                return false;
            }
            PrepareDirectTransform();
            var panel = new WorkerMilitiaTroopPanel(_harmony, _info, _warning);
            string panelFailure;
            if (panel.Prepare(out panelFailure))
            {
                _troopPanel = panel;
            }
            else
            {
                _warning("Worker militia troop panel group disabled: " + panelFailure);
            }
            var appearance = new WorkerMilitiaAppearance(_harmony, _info);
            string appearanceFailure;
            if (appearance.Prepare(out appearanceFailure))
            {
                _appearance = appearance;
            }
            else
            {
                _warning("Worker militia worker look disabled: " + appearanceFailure);
            }
            _prepared = true;
            failure = null;
            return true;
        }

        private void PrepareDirectTransform()
        {
            // A proven engine (sha256 pinned per build) gets the direct call;
            // anything else runs the engine's own alive-state-4 path.
            WorkerMilitiaNativeLayout layout = WorkerMilitiaNativeLayout.Current;
            if (layout == null || layout.TransformUnitRva == 0)
            {
                LogOnce("direct_off", "SEDE_RUNTIME_V1|event=worker_militia_direct|status=unavailable"
                    + "|engine=" + WorkerMilitiaNativeLayout.DescribeCurrent());
                return;
            }
            IntPtr module = FindNativeModuleBase();
            if (module == IntPtr.Zero)
            {
                return;
            }
            _unitManager = new IntPtr(module.ToInt64() + layout.UnitManagerRva);
            _nativeTransform = (NativeTransformUnit)Marshal.GetDelegateForFunctionPointer(
                new IntPtr(module.ToInt64() + layout.TransformUnitRva),
                typeof(NativeTransformUnit));
            if (layout.UnitSelectionMarkerClearRva != 0 && layout.PlayerSelectionClearRva != 0)
            {
                _nativeMarkerClear = (NativeUnitSelectionMarkerClear)Marshal.GetDelegateForFunctionPointer(
                    new IntPtr(module.ToInt64() + layout.UnitSelectionMarkerClearRva),
                    typeof(NativeUnitSelectionMarkerClear));
                _nativePlayerSelectionClear = (NativePlayerSelectionClear)Marshal.GetDelegateForFunctionPointer(
                    new IntPtr(module.ToInt64() + layout.PlayerSelectionClearRva),
                    typeof(NativePlayerSelectionClear));
                _deselect = DeselectOne;
            }
        }

        private void DeselectOne(int unitId)
        {
            // Same pair the engine's per-type deselect runs per matching unit.
            _nativeMarkerClear(_unitManager, unitId);
            _nativePlayerSelectionClear(_unitManager, _deselectPlayer, unitId, 0);
        }

        private static IntPtr FindNativeModuleBase()
        {
            try
            {
                using (Process process = Process.GetCurrentProcess())
                {
                    foreach (ProcessModule module in process.Modules)
                    {
                        if (string.Equals(module.ModuleName, "CrusaderDE.dll",
                                StringComparison.OrdinalIgnoreCase))
                        {
                            return module.BaseAddress;
                        }
                    }
                }
            }
            catch (Exception)
            {
            }
            return IntPtr.Zero;
        }

        private static bool Field(string name, int offset)
        {
            FieldInfo field = typeof(GameUnit).GetField(
                name,
                BindingFlags.Public | BindingFlags.Instance);
            return field != null
                && Marshal.OffsetOf(typeof(GameUnit), name).ToInt32() == offset;
        }

        private static bool BuildingField(string name, int offset)
        {
            FieldInfo field = typeof(GameBuilding).GetField(
                name,
                BindingFlags.Public | BindingFlags.Instance);
            return field != null
                && Marshal.OffsetOf(typeof(GameBuilding), name).ToInt32() == offset;
        }

        public void Apply()
        {
            if (!_prepared)
            {
                throw new InvalidOperationException("militia was not prepared");
            }
            lock (OwnerGate)
            {
                if (_owner != null)
                {
                    throw new InvalidOperationException("militia already owns the hooks");
                }
                _owner = this;
            }
            try
            {
                _harmony.Patch(
                    _selectionTarget,
                    prefix: new HarmonyMethod(typeof(WorkerMilitiaNativeSoldiers)
                        .GetMethod("TroopSelectionPrefix", BindingFlags.NonPublic | BindingFlags.Static)));
                _harmony.Patch(
                    _canPlaceTarget,
                    postfix: new HarmonyMethod(typeof(WorkerMilitiaNativeSoldiers)
                        .GetMethod("HunterHutCanPlacePostfix", BindingFlags.NonPublic | BindingFlags.Static)));
                _patched = true;
                if (!ModSaveDataAPI.Instance.RegisterModDataHandler(
                        SaveDataIdentifier,
                        SaveMilitia,
                        LoadMilitia))
                {
                    throw new InvalidOperationException(
                        "militia save-data identifier is already registered");
                }
                _saveHandlerRegistered = true;
                _mapStartSubscription = ObservableSubscribeExtensions.Subscribe(
                    MapLoaderR3EventHooks.OnStartMap.Observable, OnStartMap);
                _mapUnloadSubscription = ObservableSubscribeExtensions.Subscribe(
                    MapLoaderR3EventHooks.OnUnloadMap.Observable, OnUnloadMap);
                _meleeSubscription = ObservableSubscribeExtensions.Subscribe(
                    UnitR3EventHooks.OnUnitTakeMeleeDamage.Observable, OnMeleeDamage);
                _projectileSubscription = ObservableSubscribeExtensions.Subscribe(
                    UnitR3EventHooks.OnUnitTakeProjectileDamageEx.Observable,
                    OnProjectileDamage);
                _tribeTargetSubscription = ObservableSubscribeExtensions.Subscribe(
                    TribeR3EventHooks.OnTribeIssueOrderWithTarget.Observable,
                    OnTribeTargetOrder);
            }
            catch
            {
                RollbackOwned();
                throw;
            }
            if (_troopPanel != null)
            {
                try
                {
                    _troopPanel.Apply();
                }
                catch (Exception exception)
                {
                    // The panel group is comfort; the militia works without it.
                    _warning("Worker militia troop panel group disabled: "
                        + exception.GetType().Name + ": " + exception.Message);
                    _troopPanel.Rollback();
                    _troopPanel = null;
                }
            }
            if (_appearance != null)
            {
                try
                {
                    _appearance.Apply();
                }
                catch (Exception exception)
                {
                    // Looks are comfort too: the militia fights as it looks.
                    _warning("Worker militia worker look disabled: "
                        + exception.GetType().Name + ": " + exception.Message);
                    _appearance.Rollback();
                    _appearance = null;
                }
            }
            _info("SEDE_RUNTIME_V1|event=worker_militia|status=active|model=native_soldier_v2"
                + "|hunter=" + eChimps.CHIMP_TYPE_ARCHER
                + "|woodcutter=" + eChimps.CHIMP_TYPE_MACEMAN
                + "|trigger=order_or_enemy_in_sight"
                + "|direct=" + (_nativeTransform != null ? "engine_" + WorkerMilitiaNativeLayout.DescribeCurrent() : "off")
                + "|divisor=" + GeneratedWorkerMilitiaContract.DamageDivisor.ToString(CultureInfo.InvariantCulture)
                + "|hunter_sight=" + HunterSightTiles.ToString(CultureInfo.InvariantCulture)
                + "|woodcutter_sight=" + WoodcutterSightTiles.ToString(CultureInfo.InvariantCulture)
                + "|quiet_release_ms=" + QuietReleaseMilliseconds.ToString(CultureInfo.InvariantCulture));
        }

        public void Tick()
        {
        }

        public void RollbackOwned()
        {
            Dispose(ref _mapStartSubscription);
            Dispose(ref _mapUnloadSubscription);
            Dispose(ref _meleeSubscription);
            Dispose(ref _projectileSubscription);
            Dispose(ref _tribeTargetSubscription);
            if (_saveHandlerRegistered)
            {
                ModSaveDataAPI.Instance.UnregisterModDataHandler(SaveDataIdentifier);
                _saveHandlerRegistered = false;
            }
            if (_patched)
            {
                _harmony.Unpatch(_selectionTarget, HarmonyPatchType.Prefix, _harmony.Id);
                _harmony.Unpatch(_canPlaceTarget, HarmonyPatchType.Postfix, _harmony.Id);
                _patched = false;
            }
            RollbackHunterHut();
            if (_troopPanel != null)
            {
                _troopPanel.Rollback();
                _troopPanel = null;
            }
            if (_appearance != null)
            {
                _appearance.Rollback();
                _appearance = null;
            }
            lock (_gate)
            {
                _mapActive = false;
                _militia.Clear();
                _cooldown.Clear();
                Array.Clear(ScaledAttackers, 0, ScaledAttackers.Length);
                Array.Clear(WorkerMilitiaTroopPanel.MilitiaKind, 0, WorkerMilitiaTroopPanel.MilitiaKind.Length);
            }
            lock (OwnerGate)
            {
                if (ReferenceEquals(_owner, this))
                {
                    _owner = null;
                }
            }
        }

        private static void Dispose(ref IDisposable subscription)
        {
            IDisposable current = subscription;
            subscription = null;
            if (current != null)
            {
                current.Dispose();
            }
        }

        // ------------------------------------------------------------------
        // Map lifecycle
        // ------------------------------------------------------------------

        private void OnStartMap(MapStartEventArgs e)
        {
            if (e == null || e.Phase != EventHookPhase.Post)
            {
                return;
            }
            bool allowed;
            try
            {
                bool networked = GameNetworkAPI.IsNetworkedEnvironment();
                bool localHost = true;
                int otherHumans = -1;
                if (networked)
                {
                    localHost = GameNetworkAPI.IsLocalHost();
                    otherHumans = 0;
                    var players = GameNetworkAPI.GetPlayers();
                    if (players != null)
                    {
                        foreach (var player in players)
                        {
                            if (player != null && !player.kicked && !player.skirmishAI
                                && !player.isSelf && player.steamID > 1000UL)
                            {
                                otherHumans++;
                            }
                        }
                    }
                }
                allowed = RuntimeSessionScopeDecision.AllowsLocalMutation(
                    networked, localHost, otherHumans);
            }
            catch (Exception exception)
            {
                allowed = false;
                _warning("Worker militia could not read the session roster and stays "
                    + "off for this map: " + exception.GetType().Name);
            }
            lock (_gate)
            {
                _militia.Clear();
                _cooldown.Clear();
                _gesture.Clear();
                _boxCandidates.Clear();
                _gestureOpen = false;
                Array.Clear(ScaledAttackers, 0, ScaledAttackers.Length);
                Array.Clear(WorkerMilitiaTroopPanel.MilitiaKind, 0, WorkerMilitiaTroopPanel.MilitiaKind.Length);
                _pendingDissolveTribes.Clear();
                _fieldDiagnostics = 0;
                _mapActive = allowed;
            }
            if (allowed)
            {
                ApplyHunterHut();
            }
            _info("SEDE_RUNTIME_V1|event=worker_militia_scope|status="
                + (allowed ? "offline" : "suppressed")
                + "|restored_from_save=" + _restoredFromSave.Count.ToString(CultureInfo.InvariantCulture));
        }

        private void OnUnloadMap(MapUnloadEventArgs e)
        {
            lock (_gate)
            {
                _mapActive = false;
                _militia.Clear();
                _cooldown.Clear();
                _restoredFromSave.Clear();
                Array.Clear(ScaledAttackers, 0, ScaledAttackers.Length);
                Array.Clear(WorkerMilitiaTroopPanel.MilitiaKind, 0, WorkerMilitiaTroopPanel.MilitiaKind.Length);
            }
            RollbackHunterHut();
        }

        // ------------------------------------------------------------------
        // Engine boundary: EngineInterface.TroopSelection runs inside run()
        // under threadLock, right before DLL_RunTick, with this frame's click.
        // ------------------------------------------------------------------

        private static void TroopSelectionPrefix(
            int mouseState,
            bool rightDown,
            bool rightUp,
            int[] selectedChimps,
            bool selection_on,
            int[] underCursorChimps)
        {
            WorkerMilitiaNativeSoldiers owner = _owner;
            if (owner == null || !owner._mapActive)
            {
                return;
            }
            try
            {
                owner.OnEngineBoundary(
                    mouseState, rightDown, rightUp, selectedChimps, selection_on, underCursorChimps);
            }
            catch (Exception exception)
            {
                // Never through native frames. One failed boundary is logged;
                // the next one starts clean.
                if (owner._evidence.Add("boundary_exception." + exception.GetType().Name))
                {
                    owner._error("Worker militia boundary skipped after "
                        + exception.GetType().Name + ": " + exception.Message);
                }
            }
        }

        private void OnEngineBoundary(
            int mouseState,
            bool rightDown,
            bool rightUp,
            int[] selectedChimps,
            bool selectionOn,
            int[] underCursorChimps)
        {
            if (!Monitor.IsEntered(_engineLock))
            {
                // Only run() calls TroopSelection; anything else is not the
                // engine frame this feature was measured against.
                LogOnce("boundary_without_engine_lock",
                    "Worker militia skipped a TroopSelection call outside the engine lock.");
                return;
            }
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            if (units == null)
            {
                return;
            }
            Span<GameUnit> array = units.GetUnitsAsSpan();
            int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
            if (localPlayer < FirstPlayer || localPlayer > LastPlayer)
            {
                return;
            }
            lock (_gate)
            {
                _runCounter++;
                VerifyDirectTransformLocked(array);
                AdoptRestoredMilitiaLocked(array);
                CompleteTransformationsLocked(array);
                ReissuePendingDissolvesLocked();
                if (_troopPanel != null)
                {
                    _deselectPlayer = localPlayer;
                    _troopPanel.ApplyRequests(array, localPlayer, _directVerified ? _deselect : null);
                }
                AuditBoxLocked(array, localPlayer, selectedChimps);
                OnClickLocked(array, localPlayer, mouseState, rightDown, rightUp, selectionOn, underCursorChimps);
                int now = Environment.TickCount;
                if (unchecked(now - _lastScanTick) < ScanIntervalMilliseconds)
                {
                    return;
                }
                _lastScanTick = now;
                ScanLocked(array, localPlayer);
            }
        }

        private static ref GameUnit Unit(Span<GameUnit> array, int id)
        {
            return ref array[id - 1];
        }

        private static int UnitLimit(Span<GameUnit> array)
        {
            return Math.Min(array.Length, MaxUnitId);
        }

        private unsafe void VerifyDirectTransformLocked(Span<GameUnit> array)
        {
            if (_nativeTransform == null || _directVerified)
            {
                return;
            }
            // The pinned unit manager must be the array SE hands out: unit 1
            // sits at manager + 0x65C + 0x490.
            fixed (GameUnit* first = &array[0])
            {
                long expected = _unitManager.ToInt64() + UnitArrayOffset + UnitStride;
                if ((long)first != expected)
                {
                    _nativeTransform = null;
                    _warning("Worker militia direct transform disabled: unit manager mismatch");
                    return;
                }
            }
            _directVerified = true;
        }

        // ------------------------------------------------------------------
        // Trigger 1: a move/attack order click with own workers selected.
        // ------------------------------------------------------------------

        private void OnClickLocked(
            Span<GameUnit> array,
            int localPlayer,
            int mouseState,
            bool rightDown,
            bool rightUp,
            bool selectionOn,
            int[] underCursorChimps)
        {
            bool classic = ConfigSettings.Settings_SH1RTSControls;
            bool command;
            if (!classic)
            {
                // Modern scheme: right click orders.
                command = rightDown || rightUp;
            }
            else
            {
                // Stronghold scheme: a left click orders, unless it picks an
                // own unit or opens a box (undone below).
                command = mouseState == 1 && !selectionOn
                    && !CursorOverOwnUnit(array, localPlayer, underCursorChimps);
                if (mouseState == 1)
                {
                    _gesture.Clear();
                    _gestureOpen = true;
                }
                else if (_gestureOpen && selectionOn)
                {
                    // The press became a box: it was never an order.
                    UndoGestureLocked(array);
                    _gestureOpen = false;
                }
                else if (mouseState == 0 || mouseState == 3)
                {
                    _gestureOpen = false;
                }
            }
            if (!command)
            {
                return;
            }
            int limit = UnitLimit(array);
            for (int id = 1; id <= limit; id++)
            {
                ref GameUnit unit = ref Unit(array, id);
                if (unit.r_UnitSelected != localPlayer
                    || unit.r_AliveState != AliveState.IsAlive
                    || unit.r_ControllableForPlayerId != localPlayer
                    || _militia.ContainsKey(id))
                {
                    continue;
                }
                eChimps type = unit.r_UnitChimp;
                if (type != eChimps.CHIMP_TYPE_HUNTER && type != eChimps.CHIMP_TYPE_WOODCUTTER)
                {
                    continue;
                }
                MobilizeLocked(ref unit, id, true);
                if (classic)
                {
                    _gesture.Add(id);
                }
            }
        }

        private static bool CursorOverOwnUnit(Span<GameUnit> array, int localPlayer, int[] underCursor)
        {
            if (underCursor == null)
            {
                return false;
            }
            foreach (int id in underCursor)
            {
                if (id > 0 && id <= array.Length
                    && Unit(array, id).r_ControllableForPlayerId == localPlayer)
                {
                    return true;
                }
            }
            return false;
        }

        private void UndoGestureLocked(Span<GameUnit> array)
        {
            foreach (int id in _gesture)
            {
                Militiaman member;
                if (_militia.TryGetValue(id, out member) && member.Phase == Phase.Active)
                {
                    DemobilizeLocked(ref Unit(array, id), member, "click_was_box");
                }
            }
            _gesture.Clear();
        }

        // ------------------------------------------------------------------
        // Trigger 2: an enemy soldier in sight of a worker outside its hut.
        // ------------------------------------------------------------------

        private void ScanLocked(Span<GameUnit> array, int localPlayer)
        {
            CollectThreatsLocked(array, localPlayer);
            int limit = UnitLimit(array);
            for (int id = 1; id <= limit; id++)
            {
                ref GameUnit unit = ref Unit(array, id);
                if (unit.r_AliveState != AliveState.IsAlive
                    || unit.r_ControllableForPlayerId != localPlayer)
                {
                    continue;
                }
                eChimps type = unit.r_UnitChimp;
                Militiaman member;
                if (_militia.TryGetValue(id, out member))
                {
                    if (member.GlobalId != unit.r_GlobalId)
                    {
                        ForgetLocked(member, "slot_reused");
                        continue;
                    }
                    if (member.Phase == Phase.Active)
                    {
                        MaintainActiveLocked(ref unit, member);
                    }
                    continue;
                }
                if (type != eChimps.CHIMP_TYPE_HUNTER
                    && type != eChimps.CHIMP_TYPE_WOODCUTTER)
                {
                    continue;
                }
                // Box selection (0x19043E) needs +0x2A0 != 0; soldiers set it
                // themselves, workers never do.
                if (unit.N000000A7 == 0)
                {
                    unit.N000000A7 = SelectableMarker;
                }
                // A worker inside its hut (+0x29C set) sees nothing.
                if (unit.N0000019A != 0 || InCooldownLocked(id))
                {
                    continue;
                }
                if (ThreatWithinLocked(ref unit, SightTiles(type)))
                {
                    MobilizeLocked(ref unit, id, false);
                }
            }
        }

        private bool InCooldownLocked(int id)
        {
            GameTimeStamp since;
            if (!_cooldown.TryGetValue(id, out since))
            {
                return false;
            }
            if (GameTimeManagerAPI.Instance.HasMillisecondsElapsed(since, RemobilizeCooldownMilliseconds))
            {
                _cooldown.Remove(id);
                return false;
            }
            return true;
        }

        private void CollectThreatsLocked(Span<GameUnit> array, int localPlayer)
        {
            _threats.Clear();
            GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
            int localTeam = players.GetPlayerTeam(localPlayer);
            int limit = UnitLimit(array);
            for (int id = 1; id <= limit; id++)
            {
                ref GameUnit unit = ref Unit(array, id);
                int owner = unit.r_ControllableForPlayerId;
                if (unit.r_AliveState != AliveState.IsAlive
                    || owner < FirstPlayer || owner > LastPlayer
                    || owner == localPlayer
                    || !IsCombatant(unit.r_UnitChimp))
                {
                    continue;
                }
                int team = players.GetPlayerTeam(owner);
                // Team 0 is "no team": two players without a team are enemies.
                if (localTeam > 0 && team == localTeam)
                {
                    continue;
                }
                _threats.Add(new Threat
                {
                    X = LocalTile(unit.r_CurrentWorldPositionX),
                    Y = LocalTile(unit.r_CurrentWorldPositionY),
                });
            }
        }

        /// <summary>
        /// Units that fight. Monks, healers, laddermen, engineers, siege
        /// engines, traders and animals do not make a worker drop its tools.
        /// </summary>
        internal static bool IsCombatant(eChimps type)
        {
            int t = (int)type;
            return (t >= (int)eChimps.CHIMP_TYPE_ARCHER && t <= (int)eChimps.CHIMP_TYPE_KNIGHT)
                || type == eChimps.CHIMP_TYPE_LORD
                || type == eChimps.CHIMP_TYPE_WAR_DOG
                || (t >= (int)eChimps.CHIMP_TYPE_ARAB_BOW && t <= (int)eChimps.CHIMP_TYPE_BEDOUIN_CAMEL_LANCER)
                || (t >= (int)eChimps.CHIMP_TYPE_BEDOUIN_EUNUCH && t <= (int)eChimps.CHIMP_TYPE_BEDOUIN_DEMOLISHER);
        }

        private static int LocalTile(ushort world)
        {
            return unchecked((short)world) / GeneratedWorkerMilitiaContract.WorldTilesPerLocalTile;
        }

        private bool ThreatWithinLocked(ref GameUnit unit, int radius)
        {
            int x = LocalTile(unit.r_CurrentWorldPositionX);
            int y = LocalTile(unit.r_CurrentWorldPositionY);
            long limit = (long)radius * radius;
            for (int i = 0; i < _threats.Count; i++)
            {
                long dx = _threats[i].X - x;
                long dy = _threats[i].Y - y;
                if (dx * dx + dy * dy <= limit)
                {
                    return true;
                }
            }
            return false;
        }

        private static int SightTiles(eChimps workerType)
        {
            return workerType == eChimps.CHIMP_TYPE_HUNTER ? HunterSightTiles : WoodcutterSightTiles;
        }

        private static int PursuitTiles(eChimps workerType)
        {
            return workerType == eChimps.CHIMP_TYPE_HUNTER ? HunterPursuitTiles : WoodcutterPursuitTiles;
        }

        private static eChimps SoldierFor(eChimps workerType)
        {
            return workerType == eChimps.CHIMP_TYPE_HUNTER
                ? eChimps.CHIMP_TYPE_ARCHER
                : eChimps.CHIMP_TYPE_MACEMAN;
        }

        // ------------------------------------------------------------------
        // Mobilize / demobilize
        // ------------------------------------------------------------------

        private unsafe void MobilizeLocked(ref GameUnit unit, int id, bool ordered)
        {
            eChimps workerType = unit.r_UnitChimp;
            ushort employer;
            fixed (GameUnit* raw = &unit)
            {
                employer = *(ushort*)((byte*)raw + UnitEmployerOffset);
            }
            GameTimeStamp now = GameTimeManagerAPI.Instance.CaptureTimeStamp();
            var member = new Militiaman
            {
                UnitId = id,
                GlobalId = unit.r_GlobalId,
                WorkerType = workerType,
                TargetType = SoldierFor(workerType),
                WorkLink = employer != 0 ? employer : unit.r_LinkedProductionBuildingId,
                WorkerMaxHealth = unit.r_MaxHealth,
                Health = unit.r_CurrentHealth,
                Ordered = ordered,
                Phase = Phase.Mobilizing,
                PhaseStartRun = _runCounter,
                LastThreat = now,
                LastMoved = now,
                LastTileX = unit.r_CurrentTilePositionX,
                LastTileY = unit.r_CurrentTilePositionY,
            };
            _militia[id] = member;
            bool direct = Transform(ref unit, id, member.TargetType);
            _info("SEDE_RUNTIME_V1|event=worker_militia_mobilize|unit=" + id.ToString(CultureInfo.InvariantCulture)
                + "|worker=" + workerType + "|as=" + member.TargetType
                + "|trigger=" + (ordered ? "order" : "enemy_in_sight")
                + "|path=" + (direct ? "direct" : "alive_state_4")
                + "|work_link=" + member.WorkLink.ToString(CultureInfo.InvariantCulture)
                + "|health=" + member.Health.ToString(CultureInfo.InvariantCulture)
                + "/" + member.WorkerMaxHealth.ToString(CultureInfo.InvariantCulture));
            if (direct)
            {
                FinishOrForgetLocked(ref unit, member);
            }
        }

        private void DemobilizeLocked(ref GameUnit unit, Militiaman member, string reason)
        {
            member.Health = unit.r_CurrentHealth;
            bool homeless = !WorkplaceStillOwns(member, unit.r_ControllableForPlayerId);
            member.TargetType = homeless ? eChimps.CHIMP_TYPE_PEASANT : member.WorkerType;
            member.Phase = Phase.Demobilizing;
            member.PhaseStartRun = _runCounter;
            ScaledAttackers[member.UnitId] = 0;
            ClearKind(ref unit, member.UnitId);
            if (!member.Ordered)
            {
                _cooldown[member.UnitId] = GameTimeManagerAPI.Instance.CaptureTimeStamp();
            }
            bool direct = Transform(ref unit, member.UnitId, member.TargetType);
            _info("SEDE_RUNTIME_V1|event=worker_militia_demobilize|unit=" + member.UnitId.ToString(CultureInfo.InvariantCulture)
                + "|to=" + member.TargetType + "|reason=" + reason
                + "|homeless=" + (homeless ? "true" : "false")
                + "|path=" + (direct ? "direct" : "alive_state_4"));
            if (direct)
            {
                FinishOrForgetLocked(ref unit, member);
            }
        }

        /// <summary>
        /// Turns the unit into <paramref name="type"/>. True when the engine did
        /// it synchronously (direct call); false when it was requested through
        /// alive state 4 for the next unit tick.
        /// </summary>
        private bool Transform(ref GameUnit unit, int id, eChimps type)
        {
            unit.r_TransformIntoUnitOfType = type;
            // Low word of +0x2C8 is the AI start state 0x195C70 copies to
            // r_AIState; the high word (+0x2CA) is written by 0x195C70 itself.
            unit.N000000AC = (unit.N000000AC & 0xFFFF0000u) | StartAiState;
            if (_nativeTransform != null && _directVerified)
            {
                _nativeTransform(_unitManager, id);
                return true;
            }
            unit.r_AliveState = (AliveState)AliveTransformPending;
            return false;
        }

        private void FinishOrForgetLocked(ref GameUnit unit, Militiaman member)
        {
            if (unit.r_AliveState == AliveState.IsAlive && unit.r_UnitChimp == member.TargetType)
            {
                List<Militiaman> done = null;
                FinishTransformLocked(ref unit, member, ref done);
                if (done != null)
                {
                    ForgetLocked(member, "resolved");
                }
                return;
            }
            LogOnce("direct_mismatch", "Worker militia direct transform left unit "
                + member.UnitId.ToString(CultureInfo.InvariantCulture) + " as " + unit.r_UnitChimp
                + " alive=" + unit.r_AliveState + " (wanted " + member.TargetType + ")");
            ForgetLocked(member, "direct_mismatch");
        }

        private static bool WorkplaceStillOwns(Militiaman member, int owner)
        {
            if (member.WorkLink == 0)
            {
                return false;
            }
            try
            {
                GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                if (!buildings.TryGetBuildingByIdEx(member.WorkLink, out var pointer))
                {
                    return false;
                }
                ref GameBuilding building = ref pointer.AsRef();
                return building.r_AliveState == AliveState.IsAlive
                    && building.r_PlayerIdOwner == owner;
            }
            catch (Exception)
            {
                return false;
            }
        }

        private void CompleteTransformationsLocked(Span<GameUnit> array)
        {
            if (_militia.Count == 0)
            {
                return;
            }
            List<Militiaman> done = null;
            foreach (Militiaman member in _militia.Values)
            {
                if (member.Phase == Phase.Active)
                {
                    continue;
                }
                if (member.UnitId <= 0 || member.UnitId > array.Length)
                {
                    (done ?? (done = new List<Militiaman>())).Add(member);
                    continue;
                }
                ref GameUnit unit = ref Unit(array, member.UnitId);
                if (unit.r_GlobalId != member.GlobalId
                    || unit.r_AliveState == AliveState.MarkedForDeletion
                    || unit.r_AliveState == AliveState.None)
                {
                    (done ?? (done = new List<Militiaman>())).Add(member);
                    continue;
                }
                if (unit.r_AliveState == AliveState.IsAlive
                    && unit.r_UnitChimp == member.TargetType)
                {
                    FinishTransformLocked(ref unit, member, ref done);
                    continue;
                }
                if (_runCounter - member.PhaseStartRun > TransformTimeoutRuns)
                {
                    if (_evidence.Add("transform_timeout." + member.Phase))
                    {
                        _warning("Worker militia transformation did not complete: unit="
                            + member.UnitId.ToString(CultureInfo.InvariantCulture)
                            + " phase=" + member.Phase + " alive=" + unit.r_AliveState
                            + " type=" + unit.r_UnitChimp + " target=" + member.TargetType);
                    }
                    (done ?? (done = new List<Militiaman>())).Add(member);
                }
            }
            if (done != null)
            {
                foreach (Militiaman member in done)
                {
                    ForgetLocked(member, "resolved");
                }
            }
        }

        private void FinishTransformLocked(
            ref GameUnit unit,
            Militiaman member,
            ref List<Militiaman> done)
        {
            // 0x19A1A0 sets full health of the NEW type. A militiaman keeps the
            // body of the worker: same maximum, same wounds, both directions.
            uint max = member.Phase == Phase.Mobilizing
                ? member.WorkerMaxHealth
                : unit.r_MaxHealth;
            if (max == 0)
            {
                max = unit.r_MaxHealth;
            }
            uint health = Math.Min(member.Health, max);
            if (health == 0)
            {
                health = 1;
            }
            unit.r_MaxHealth = max;
            unit.r_CurrentHealth = health;
            ushort percent = (ushort)Math.Min(100u, health * 100u / Math.Max(1u, max));
            unit.r_CurrentHealthPercentage = percent;
            unit.r_HealthBarBlocks = (uint)(percent / 5);
            if (member.Phase == Phase.Mobilizing)
            {
                member.Phase = Phase.Active;
                ScaledAttackers[member.UnitId] = 1;
                MarkKind(ref unit, member);
                LogOnce("transform_done.mobilize." + member.WorkerType,
                    "SEDE_RUNTIME_V1|event=worker_militia_transformed|direction=to_soldier|unit="
                    + member.UnitId.ToString(CultureInfo.InvariantCulture)
                    + "|type=" + unit.r_UnitChimp + "|ai=" + unit.r_AIState.ToString(CultureInfo.InvariantCulture)
                    + "|health=" + health.ToString(CultureInfo.InvariantCulture) + "/" + max.ToString(CultureInfo.InvariantCulture)
                    + "|runs=" + (_runCounter - member.PhaseStartRun).ToString(CultureInfo.InvariantCulture));
                return;
            }
            string job = member.TargetType == member.WorkerType
                ? ReclaimJobLocked(ref unit, member)
                : "peasant";
            LogOnce("transform_done.demobilize." + member.TargetType + "." + job,
                "SEDE_RUNTIME_V1|event=worker_militia_transformed|direction=to_" + member.TargetType
                + "|unit=" + member.UnitId.ToString(CultureInfo.InvariantCulture)
                + "|ai=" + unit.r_AIState.ToString(CultureInfo.InvariantCulture)
                + "|job=" + job
                + "|work_link=" + member.WorkLink.ToString(CultureInfo.InvariantCulture)
                + "|health=" + health.ToString(CultureInfo.InvariantCulture) + "/" + max.ToString(CultureInfo.InvariantCulture));
            (done ?? (done = new List<Militiaman>())).Add(member);
        }

        /// <summary>
        /// Puts the returning worker back into its hut's job slot, the way
        /// 0xB6280 assigns one: slot id, slot global id, unit slot index
        /// (+0x392) and employer (+0x394). A replacement the hut hired in the
        /// meantime goes back to the peasants through the engine's own orphan
        /// path (0x1503D2: +0x04=1, +0x2C=0x10, type 1, start 0, employer 0,
        /// alive 4). The engine's fresh-worker path (0x183E84) starts a worker
        /// in AI state 0 with +0x334 cleared; the returner does the same.
        /// </summary>
        private unsafe string ReclaimJobLocked(ref GameUnit unit, Militiaman member)
        {
            GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
            if (!buildings.TryGetBuildingByIdEx(member.WorkLink, out var pointer))
            {
                return "no_hut";
            }
            byte* hut = (byte*)pointer.Pointer;
            int required = *(short*)(hut + HutWorkersRequiredOffset);
            if (required <= 0 || required > MaxHutSlots)
            {
                return "hut_without_slots";
            }
            Span<GameUnit> array = GameUnitManagerAPI.Instance.GetUnitsAsSpan();
            int free = -1;
            int replaced = -1;
            for (int i = 0; i < required; i++)
            {
                int slotUnit = *(short*)(hut + HutWorkerIdOffset + 2 * i);
                uint slotGlobal = *(uint*)(hut + HutWorkerGlobalIdOffset + 4 * i);
                if (slotUnit == member.UnitId && slotGlobal == member.GlobalId)
                {
                    AssignSlot(ref unit, hut, member, i);
                    return "slot_kept";
                }
                if (slotUnit <= 0 || slotUnit > array.Length
                    || !SlotHolds(ref Unit(array, slotUnit), member.WorkLink, slotGlobal))
                {
                    if (free < 0)
                    {
                        free = i;
                    }
                    continue;
                }
                if (replaced < 0 && !_militia.ContainsKey(slotUnit)
                    && Unit(array, slotUnit).r_UnitChimp == member.WorkerType)
                {
                    replaced = i;
                }
            }
            if (free >= 0)
            {
                AssignSlot(ref unit, hut, member, free);
                return "slot_free";
            }
            if (replaced >= 0)
            {
                int other = *(short*)(hut + HutWorkerIdOffset + 2 * replaced);
                ref GameUnit replacement = ref Unit(array, other);
                AssignSlot(ref unit, hut, member, replaced);
                SendToPeasants(ref replacement);
                _info("SEDE_RUNTIME_V1|event=worker_militia_job_reclaimed|unit="
                    + member.UnitId.ToString(CultureInfo.InvariantCulture)
                    + "|hut=" + member.WorkLink.ToString(CultureInfo.InvariantCulture)
                    + "|replacement=" + other.ToString(CultureInfo.InvariantCulture));
                return "slot_reclaimed";
            }
            SendToPeasants(ref unit);
            return "hut_full";
        }

        private static unsafe bool SlotHolds(ref GameUnit unit, ushort hutId, uint slotGlobal)
        {
            // 0xC9500: alive not 0/3, employer == hut, global id == slot's.
            AliveState alive = unit.r_AliveState;
            ushort employer;
            fixed (GameUnit* raw = &unit)
            {
                employer = *(ushort*)((byte*)raw + UnitEmployerOffset);
            }
            return alive != AliveState.None
                && (short)alive != 3
                && employer == hutId
                && unit.r_GlobalId == slotGlobal;
        }

        private static unsafe void AssignSlot(ref GameUnit unit, byte* hut, Militiaman member, int slot)
        {
            *(short*)(hut + HutWorkerIdOffset + 2 * slot) = (short)member.UnitId;
            *(uint*)(hut + HutWorkerGlobalIdOffset + 4 * slot) = member.GlobalId;
            fixed (GameUnit* raw = &unit)
            {
                *(ushort*)((byte*)raw + UnitSlotIndexOffset) = (ushort)slot;
                *(ushort*)((byte*)raw + UnitEmployerOffset) = member.WorkLink;
            }
            unit.r_LinkedProductionBuildingId = 0;
            unit.r_AIState = StartAiState;
        }

        private static unsafe void SendToPeasants(ref GameUnit unit)
        {
            fixed (GameUnit* raw = &unit)
            {
                byte* p = (byte*)raw;
                *(int*)(p + 0x04) = 1;
                *(int*)(p + 0x2C) = 0x10;
                *(ushort*)(p + UnitEmployerOffset) = 0;
            }
            unit.r_TransformIntoUnitOfType = eChimps.CHIMP_TYPE_PEASANT;
            unit.N000000AC = unit.N000000AC & 0xFFFF0000u;
            unit.r_AliveState = (AliveState)AliveTransformPending;
        }

        private void MarkKind(ref GameUnit unit, Militiaman member)
        {
            WorkerMilitiaTroopPanel.MilitiaKind[member.UnitId] =
                member.WorkerType == eChimps.CHIMP_TYPE_HUNTER
                    ? WorkerMilitiaTroopPanel.KindHunter
                    : WorkerMilitiaTroopPanel.KindWoodcutter;
            if (unit.r_UnitSelected != 0 && _troopPanel != null)
            {
                _troopPanel.RefreshPanel();
            }
        }

        private void ClearKind(ref GameUnit unit, int id)
        {
            WorkerMilitiaTroopPanel.MilitiaKind[id] = WorkerMilitiaTroopPanel.KindNone;
            if (unit.r_UnitSelected != 0 && _troopPanel != null)
            {
                _troopPanel.RefreshPanel();
            }
        }

        private void MaintainActiveLocked(ref GameUnit unit, Militiaman member)
        {
            if (unit.r_UnitChimp != member.TargetType)
            {
                // Something else transformed the unit (native disband into a
                // peasant, a scenario script): it is not ours any more.
                ForgetLocked(member, "type_changed_to_" + unit.r_UnitChimp);
                return;
            }
            GameTimeManagerAPI time = GameTimeManagerAPI.Instance;
            if (ThreatWithinLocked(ref unit, PursuitTiles(member.WorkerType)))
            {
                member.LastThreat = time.CaptureTimeStamp();
            }
            if (unit.r_CurrentTilePositionX != member.LastTileX
                || unit.r_CurrentTilePositionY != member.LastTileY)
            {
                member.LastTileX = unit.r_CurrentTilePositionX;
                member.LastTileY = unit.r_CurrentTilePositionY;
                member.LastMoved = time.CaptureTimeStamp();
            }
            if (member.DisbandRequested)
            {
                DemobilizeLocked(ref unit, member, "disband");
                return;
            }
            int idle = member.Ordered ? OrderedIdleReleaseMilliseconds : ThreatIdleReleaseMilliseconds;
            if (time.HasMillisecondsElapsed(member.LastThreat, QuietReleaseMilliseconds)
                && time.HasMillisecondsElapsed(member.LastMoved, idle))
            {
                DemobilizeLocked(ref unit, member, member.Ordered ? "order_done_quiet" : "threat_gone");
            }
        }

        private void ForgetLocked(Militiaman member, string reason)
        {
            _militia.Remove(member.UnitId);
            if (member.UnitId > 0 && member.UnitId <= MaxUnitId)
            {
                ScaledAttackers[member.UnitId] = 0;
                WorkerMilitiaTroopPanel.MilitiaKind[member.UnitId] = WorkerMilitiaTroopPanel.KindNone;
            }
            if (reason != "resolved")
            {
                LogOnce("forget." + reason, "SEDE_RUNTIME_V1|event=worker_militia_forget|unit="
                    + member.UnitId.ToString(CultureInfo.InvariantCulture) + "|reason=" + reason);
            }
        }

        // ------------------------------------------------------------------
        // Disband button: back to work instead of to the keep.
        // ------------------------------------------------------------------

        private void OnTribeTargetOrder(TribeIssueOrderWithTargetEventArgs e)
        {
            try
            {
                if (e == null || e.Phase != EventHookPhase.Pre
                    || e.AICommand != TribeAICommand.UnitDissolve
                    || !_mapActive)
                {
                    return;
                }
                lock (_gate)
                {
                    if (e.TribeId == _bypassDissolveTribe || _militia.Count == 0)
                    {
                        return;
                    }
                    _tribeMembers.Clear();
                    GameTribeManagerAPI.Instance.GetUnits(e.TribeId, _tribeMembers);
                    int ours = 0;
                    foreach (int id in _tribeMembers)
                    {
                        Militiaman member;
                        if (_militia.TryGetValue(id, out member)
                            && member.Phase == Phase.Active)
                        {
                            member.DisbandRequested = true;
                            ours++;
                        }
                    }
                    if (ours == 0)
                    {
                        return;
                    }
                    e.SkipOriginalFunction = true;
                    e.ReturnValue = 1;
                    if (ours < _tribeMembers.Count)
                    {
                        // Mixed: real soldiers still disband, after our men
                        // left the group (next engine boundary).
                        _pendingDissolveTribes.Add(e.TribeId);
                    }
                    _info("SEDE_RUNTIME_V1|event=worker_militia_disband|tribe="
                        + e.TribeId.ToString(CultureInfo.InvariantCulture)
                        + "|militia=" + ours.ToString(CultureInfo.InvariantCulture)
                        + "|others=" + (_tribeMembers.Count - ours).ToString(CultureInfo.InvariantCulture));
                }
            }
            catch (Exception exception)
            {
                LogOnce("disband_exception", "Worker militia disband interception skipped: "
                    + exception.GetType().Name);
            }
        }

        private void ReissuePendingDissolvesLocked()
        {
            if (_pendingDissolveTribes.Count == 0)
            {
                return;
            }
            GameTribeManagerAPI tribes = GameTribeManagerAPI.Instance;
            foreach (int tribe in _pendingDissolveTribes)
            {
                _tribeMembers.Clear();
                if (!tribes.GetUnits(tribe, _tribeMembers))
                {
                    continue;
                }
                foreach (int id in _tribeMembers)
                {
                    if (_militia.ContainsKey(id))
                    {
                        tribes.UnassignUnit(tribe, id);
                    }
                }
                _bypassDissolveTribe = tribe;
                try
                {
                    tribes.Dissolve(tribe);
                }
                finally
                {
                    _bypassDissolveTribe = 0;
                }
            }
            _pendingDissolveTribes.Clear();
        }

        // ------------------------------------------------------------------
        // Damage: militia hits weaker than the soldier it runs as.
        // ------------------------------------------------------------------

        private void OnMeleeDamage(UnitTakeDamageByMeleeEventArgs e)
        {
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            int attacker = e.AttackingUnitId;
            if (attacker > 0 && attacker < MaxUnitId && ScaledAttackers[attacker] != 0
                && e.Damage > 0)
            {
                e.Damage = Math.Max(1, e.Damage / GeneratedWorkerMilitiaContract.DamageDivisor);
            }
        }

        // Raw SE context hook: no lock, no allocation, nothing that can throw.
        private void OnProjectileDamage(UnitTakeDamageByProjectileExEventArgs e)
        {
            if (e == null)
            {
                return;
            }
            int attacker = e.AttackingUnitId;
            if (attacker > 0 && attacker < MaxUnitId && ScaledAttackers[attacker] != 0
                && e.Damage > 0)
            {
                int scaled = e.Damage / GeneratedWorkerMilitiaContract.DamageDivisor;
                e.Damage = scaled < 1 ? 1 : scaled;
            }
        }

        // ------------------------------------------------------------------
        // Save / load: a saved militiaman is still an archer or maceman.
        // ------------------------------------------------------------------

        private byte[] SaveMilitia(SaveContext context)
        {
            lock (_gate)
            {
                if (context == null || !context.IsSaveFile || _militia.Count == 0)
                {
                    return null;
                }
                using (var stream = new MemoryStream())
                using (var writer = new BinaryWriter(stream))
                {
                    writer.Write(SaveVersion);
                    writer.Write(_militia.Count);
                    foreach (Militiaman member in _militia.Values)
                    {
                        writer.Write(member.UnitId);
                        writer.Write(member.GlobalId);
                        writer.Write((int)member.WorkerType);
                        writer.Write((int)member.TargetType);
                        writer.Write(member.WorkLink);
                        writer.Write(member.WorkerMaxHealth);
                        writer.Write(member.Ordered);
                        writer.Write((int)member.Phase);
                    }
                    writer.Flush();
                    return stream.ToArray();
                }
            }
        }

        private void LoadMilitia(byte[] data, LoadContext context)
        {
            lock (_gate)
            {
                _restoredFromSave.Clear();
                if (data == null || context == null || !context.IsSaveFile)
                {
                    return;
                }
                try
                {
                    using (var reader = new BinaryReader(new MemoryStream(data)))
                    {
                        if (reader.ReadInt32() != SaveVersion)
                        {
                            return;
                        }
                        int count = reader.ReadInt32();
                        for (int i = 0; i < count && i < MaxUnitId; i++)
                        {
                            _restoredFromSave.Add(new Militiaman
                            {
                                UnitId = reader.ReadInt32(),
                                GlobalId = reader.ReadUInt32(),
                                WorkerType = (eChimps)reader.ReadInt32(),
                                TargetType = (eChimps)reader.ReadInt32(),
                                WorkLink = reader.ReadUInt16(),
                                WorkerMaxHealth = reader.ReadUInt32(),
                                Ordered = reader.ReadBoolean(),
                                Phase = (Phase)reader.ReadInt32(),
                            });
                        }
                    }
                }
                catch (Exception exception)
                {
                    _restoredFromSave.Clear();
                    _warning("Worker militia save data was unreadable and is ignored: "
                        + exception.GetType().Name);
                }
            }
        }

        private void AdoptRestoredMilitiaLocked(Span<GameUnit> array)
        {
            if (_restoredFromSave.Count == 0)
            {
                return;
            }
            GameTimeStamp now = GameTimeManagerAPI.Instance.CaptureTimeStamp();
            foreach (Militiaman member in _restoredFromSave)
            {
                if (member.UnitId <= 0 || member.UnitId > array.Length)
                {
                    continue;
                }
                ref GameUnit unit = ref Unit(array, member.UnitId);
                if (unit.r_GlobalId != member.GlobalId
                    || unit.r_AliveState != AliveState.IsAlive)
                {
                    continue;
                }
                // Whatever phase was saved, the unit on the map decides now.
                if (unit.r_UnitChimp == SoldierFor(member.WorkerType))
                {
                    member.TargetType = unit.r_UnitChimp;
                    member.Phase = Phase.Active;
                    member.LastThreat = now;
                    member.LastMoved = now;
                    member.LastTileX = unit.r_CurrentTilePositionX;
                    member.LastTileY = unit.r_CurrentTilePositionY;
                    _militia[member.UnitId] = member;
                    ScaledAttackers[member.UnitId] = 1;
                    MarkKind(ref unit, member);
                }
            }
            _info("SEDE_RUNTIME_V1|event=worker_militia_restored|saved="
                + _restoredFromSave.Count.ToString(CultureInfo.InvariantCulture)
                + "|adopted=" + _militia.Count.ToString(CultureInfo.InvariantCulture));
            _restoredFromSave.Clear();
        }

        // ------------------------------------------------------------------
        // Hunter hut in the build menu (unchanged Europe feature).
        // ------------------------------------------------------------------

        private void ApplyHunterHut()
        {
            if (_hunterHutAvailability != null)
            {
                return;
            }
            try
            {
                GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
                var mutation = new OwnedValueMutation<bool>(
                    ExtensionLeaseClaim.Mapper((int)eMappers.MAPPER_HUNTER),
                    () => players.GetBuildingAvailability(eMappers.MAPPER_HUNTER),
                    value => players.SetBuildingAvailability(eMappers.MAPPER_HUNTER, value),
                    true);
                string failure;
                if (mutation.TryApply(out failure))
                {
                    _hunterHutAvailability = mutation;
                }
                else
                {
                    LogOnce("hunter_hut", "Worker militia could not enable the hunter hut: " + failure);
                }
            }
            catch (Exception exception)
            {
                LogOnce("hunter_hut_exception", "Worker militia hunter hut skipped: "
                    + exception.GetType().Name);
            }
        }

        private void RollbackHunterHut()
        {
            OwnedValueMutation<bool> mutation = _hunterHutAvailability;
            _hunterHutAvailability = null;
            if (mutation == null)
            {
                return;
            }
            try
            {
                string failure;
                mutation.RollbackOwned(out failure);
            }
            catch (Exception exception)
            {
                LogOnce("hunter_hut_rollback", "Worker militia hunter hut rollback skipped: "
                    + exception.GetType().Name);
            }
        }

        private static void HunterHutCanPlacePostfix(object parameter, ref bool __result)
        {
            if (!string.Equals(parameter as string, "STRUCT_HUNTERS_HUT", StringComparison.Ordinal))
            {
                return;
            }
            WorkerMilitiaNativeSoldiers owner = _owner;
            try
            {
                if (owner != null && owner._mapActive
                    && GamePlayerManagerAPI.Instance.GetBuildingAvailability(eMappers.MAPPER_HUNTER))
                {
                    __result = true;
                }
            }
            catch (Exception)
            {
            }
        }

        // ------------------------------------------------------------------
        // Evidence: why a box did or did not pick up a worker.
        // ------------------------------------------------------------------

        private unsafe void AuditBoxLocked(Span<GameUnit> array, int localPlayer, int[] boxList)
        {
            // Frame n: the managed box list arrives (GameMap.grabTroopsOnScreen
            // takes every chimp in the rectangle; 0x19043E filters). Frame n+1:
            // compare with who the engine marked selected.
            if (_boxCandidates.Count > 0 && _fieldDiagnostics < MaxFieldDiagnostics)
            {
                int selected = 0, inside = 0, busy6D = 0, marker = 0, blocked354 = 0, init = 0;
                foreach (int id in _boxCandidates)
                {
                    ref GameUnit unit = ref Unit(array, id);
                    if (unit.r_UnitSelected == localPlayer)
                    {
                        selected++;
                        continue;
                    }
                    fixed (GameUnit* raw = &unit)
                    {
                        byte* p = (byte*)raw;
                        if (unit.N0000019A != 0) inside++;
                        else if (unit.r_AIState == 0x6D) busy6D++;
                        else if (unit.N000000A7 == 0) marker++;
                        else if (*(ushort*)(p + 0x354) != 0) blocked354++;
                        else if (*(ushort*)(p + 0xAC) != 0) init++;
                    }
                }
                _fieldDiagnostics++;
                _info("SEDE_RUNTIME_V1|event=worker_militia_box_audit|workers_in_box="
                    + _boxCandidates.Count.ToString(CultureInfo.InvariantCulture)
                    + "|selected=" + selected.ToString(CultureInfo.InvariantCulture)
                    + "|inside_hut=" + inside.ToString(CultureInfo.InvariantCulture)
                    + "|ai_6D=" + busy6D.ToString(CultureInfo.InvariantCulture)
                    + "|no_marker=" + marker.ToString(CultureInfo.InvariantCulture)
                    + "|f354=" + blocked354.ToString(CultureInfo.InvariantCulture)
                    + "|init=" + init.ToString(CultureInfo.InvariantCulture));
            }
            _boxCandidates.Clear();
            if (boxList == null || boxList.Length == 0 || _fieldDiagnostics >= MaxFieldDiagnostics)
            {
                return;
            }
            foreach (int id in boxList)
            {
                if (id <= 0 || id > array.Length)
                {
                    continue;
                }
                ref GameUnit unit = ref Unit(array, id);
                eChimps type = unit.r_UnitChimp;
                if (unit.r_ControllableForPlayerId == localPlayer
                    && (type == eChimps.CHIMP_TYPE_HUNTER || type == eChimps.CHIMP_TYPE_WOODCUTTER))
                {
                    _boxCandidates.Add(id);
                }
            }
        }

        private void LogOnce(string key, string message)
        {
            if (_evidence.Add(key))
            {
                _info(message);
            }
        }
    }
}
