using System;
using System.Threading;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using HarmonyLib;
using R3;
using SHCDESE.API;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.Buildings;
using SHCDESE.EventAPI.Player;
using SHCDESE.EventAPI.Projectiles;
using SHCDESE.EventAPI.Tribes;
using SHCDESE.EventAPI.Units;
using SHCDESE.Interop;
#if DIPLOMACY_V2
using DiplomacyPolicy = StrongholdEuropeDE.Runtime.DiplomacyV2StateMachine;
#else
using DiplomacyPolicy = StrongholdEuropeDE.Runtime.DiplomacyStateMachine;
#endif
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Owns the native relationship boundary. Diplomacy state is committed
    /// on the Unity frame under the engine monitor after the complete team partition has
    /// been written and read back. The event guards close the native combat
    /// paths that can still carry an order, projectile, or damage event from
    /// the old relationship across that boundary.
    /// </summary>
    internal sealed partial class DiplomacyFeature
    {
        // Fire positions are expressed in the engine's fine-grained world
        // coordinates (eight world positions per map tile). The extra tile
        // accounts for a unit's occupied tile instead of treating it as a
        // dimensionless point at its reported world position.
        private const int FireUnitFootprintPaddingWorld = 8;
        private const int GroundFireProjectileRiskRadiusWorld = 16;
        private const int WorldPositionsPerLocalTile = 8;

        private IDisposable _diplomacyTribeOrderSubscription;
        private IDisposable _diplomacyProjectileSpawnSubscription;
        private IDisposable _diplomacySpawnFireSubscription;
        private IDisposable _diplomacyMeleeDamageSubscription;
        private IDisposable _diplomacyProjectileDamageSubscription;
        private IDisposable _diplomacyBuildingDamageSubscription;
        private IDisposable _diplomacyAiAttackSubscription;
#if DIPLOMACY_V2
        private IDisposable _diplomacyAiDefendSubscription;
#endif
        private IDisposable _diplomacyReceivedGoodsSubscription;
#if DIPLOMACY_V2
        private IDisposable _diplomacyTribeMoveSubscription;
#endif
        private MethodInfo _gameOverTarget;
        private bool _gameOverPatchApplied;

        private DiplomacyPendingTeamTransition _pendingTeamTransition;
        private long _pendingTransitionGeneration;
        private string _pendingTransitionFingerprint;
        private Dictionary<int, int> _transitionGuardPartition;
        private Dictionary<int, int> _transitionVerificationPartition;
        private long _transitionVerificationStartedTick;
        private int _transitionBlockedCombatEvents;
        private Exception _combatSafetyFault;
        private bool _rollbackGuardActive;
        private Dictionary<int, int> _rollbackGuardBeforePartition;
        private Dictionary<int, int> _rollbackGuardAfterPartition;
        private CombatProtectionSnapshot _combatProtectionSnapshot =
            CombatProtectionSnapshot.Empty;
        private int _combatSnapshotBlocks;
        private int _combatSnapshotFaults;

        // Called only while _gate is held. Native readers use the completed
        // immutable object and never observe a partially written matrix.
        private void PublishCombatProtectionSnapshot()
        {
#if DIPLOMACY_V2
            PublishV2TreatyIntentSnapshot();
            PublishV2VassalRequestSnapshot();
#endif
            if (!CombatGuardOperational())
            {
                Volatile.Write(ref _combatProtectionSnapshot,
                    CombatProtectionSnapshot.Empty);
                return;
            }
            int members = 0;
            int[] rows = new int[9];
            foreach (int player in _roster)
            {
                if (player >= 1 && player <= 8)
                    members |= 1 << player;
            }
            try
            {
                IDisposable nativeLease;
                bool canReadNative = TryEnterNativeInventorySection(out nativeLease);
                using (nativeLease)
                {
                    CombatProtectionSnapshot previous = Volatile.Read(
                        ref _combatProtectionSnapshot);
                    for (int first = 1; first <= 8; first++)
                    {
                        for (int second = first + 1; second <= 8; second++)
                        {
                            if ((members & (1 << first)) == 0
                                || (members & (1 << second)) == 0)
                                continue;
                            bool protect = canReadNative
                                ? NativePlayersAreAllied(first, second)
                                : CombatProtectionWithoutNativeRead(previous, first, second);
                            // Until a queued transition commits, both complete
                            // partitions remain protected, including a breakup.
                            if (_pendingTeamTransition != null)
                                protect |= PartitionAllies(
                                    _pendingTeamTransition.ExpectedPartition,
                                    first, second) || PartitionAllies(
                                    _pendingTeamTransition.TargetPartition,
                                    first, second);
                            if (protect)
                            {
                                rows[first] |= 1 << second;
                                rows[second] |= 1 << first;
                            }
                        }
                    }
                }
            }
            catch
            {
                // A transient native read failure must not publish an empty
                // matrix over a half-written team partition.
                for (int player = 1; player <= 8; player++)
                    rows[player] = members & ~(1 << player);
                Interlocked.Increment(ref _combatSnapshotFaults);
            }
            Volatile.Write(ref _combatProtectionSnapshot,
                new CombatProtectionSnapshot(_sessionGeneration, members, rows));
        }

        // Busy publication is managed-only. Keep known protection, but also add
        // newly committed alliances/treaties: the previous enemy snapshot alone
        // is insufficient after an enemy-to-ally transition. The next normal
        // frame publication replaces this conservative union with fresh teams.
        private bool CombatProtectionWithoutNativeRead(
            CombatProtectionSnapshot previous, int first, int second)
        {
            if (previous == null || previous.Session != _sessionGeneration
                || !previous.Contains(first) || !previous.Contains(second)
                || previous.Protects(first, second))
                return true;
            if (_rollbackGuardActive
                && (_rollbackGuardBeforePartition == null
                    || _rollbackGuardAfterPartition == null
                    || PartitionAllies(_rollbackGuardBeforePartition, first, second)
                    || PartitionAllies(_rollbackGuardAfterPartition, first, second)))
                return true;
            if (PartitionAllies(_transitionGuardPartition, first, second)
                || PartitionAllies(_transitionVerificationPartition, first, second))
                return true;
#if DIPLOMACY_V2
            if (V2TreatyProtectsPlayers(first, second)) return true;
#endif
            string firstCoalition;
            string secondCoalition;
            _playerCoalition.TryGetValue(first, out firstCoalition);
            _playerCoalition.TryGetValue(second, out secondCoalition);
            if (firstCoalition != null && firstCoalition == secondCoalition)
                return true;
            RelationState firstRelation;
            RelationState secondRelation;
            bool firstInBloc = first == _localPlayer
                || firstCoalition != null
                    && _relations.TryGetValue(firstCoalition, out firstRelation)
                    && firstRelation.Allied;
            bool secondInBloc = second == _localPlayer
                || secondCoalition != null
                    && _relations.TryGetValue(secondCoalition, out secondRelation)
                    && secondRelation.Allied;
            return firstInBloc && secondInBloc;
        }

        private bool PrepareCombatSafety(out string failure)
        {
            Type scenarios = typeof(GameData).GetNestedType(
                "Scenarios",
                BindingFlags.Public | BindingFlags.NonPublic);
            _gameOverTarget = scenarios == null
                ? null
                : scenarios.GetMethod(
                    "setGameOverState",
                    BindingFlags.Public | BindingFlags.Instance,
                    null,
                    new[] { typeof(int), typeof(int), typeof(int) },
                    null);
            MethodInfo gameOverPrefix = typeof(DiplomacyFeature).GetMethod(
                "DiplomacyGameOverPrefix",
                BindingFlags.NonPublic | BindingFlags.Static);
            if (_gameOverTarget == null
                || _gameOverTarget.ReturnType != typeof(void)
                || gameOverPrefix == null
                || TribeR3EventHooks.OnTribeIssueOrderWithTarget.Observable == null
                || ProjectileR3EventHooks.OnProjectileSpawn.Observable == null
                || ProjectileR3EventHooks.OnSpawnFire.Observable == null
                || UnitR3EventHooks.OnUnitTakeMeleeDamage.Observable == null
                || UnitR3EventHooks.OnUnitTakeProjectileDamage.Observable == null
                || BuildingR3EventHooks.OnBuildingTileTakeDamage.Observable == null
                || PlayerR3EventHooks.OnPlayerAIEvaluateAttackOrder.Observable == null
#if DIPLOMACY_V2
                || PlayerR3EventHooks.OnPlayerAIRequestGoods.Observable == null
                || PlayerR3EventHooks.OnPlayerAIEvaluateDefendOrder.Observable
                    == null
#endif
                || PlayerR3EventHooks.OnPlayerAIRequestReceivedGoods.Observable == null
                || PlayerR3EventHooks.OnPlayerAddResource.Observable == null
                || PlayerR3EventHooks.OnPlayerSubtractResource.Observable == null
#if DIPLOMACY_V2
                || TribeR3EventHooks.OnTribeIssueOrderMoveHere.Observable == null
                || BuildingR3EventHooks.OnBuildingSpawn.Observable == null
                || BuildingR3EventHooks.OnBuildWall.Observable == null
                || BuildingR3EventHooks.OnBuildingDelete.Observable == null
                || BuildingR3EventHooks.OnWallBulldoze.Observable == null
#endif
                )
            {
                failure = "pinned native diplomacy safety surface is unavailable";
                return false;
            }
#if DIPLOMACY_V2
            if (!PrepareV2AllyOrders(out failure)) return false;
            if (!PrepareV2HumanOrders(out failure)) return false;
#endif
            failure = null;
            return true;
        }

        private void ApplyCombatSafety()
        {
#if DIPLOMACY_V2
            ApplyNativeTruceAdmission();
            ApplyV2AllyOrders();
            ApplyV2HumanOrders();
            ApplyV2CastleBoundaryEvents();
            _v2VassalRequestSubscription = ObservableSubscribeExtensions.Subscribe(
                PlayerR3EventHooks.OnPlayerAIRequestGoods.Observable, OnV2NativeGoodsRequest);
#endif
            MethodInfo prefix = typeof(DiplomacyFeature).GetMethod(
                "DiplomacyGameOverPrefix",
                BindingFlags.NonPublic | BindingFlags.Static);
            _harmony.Patch(
                _gameOverTarget,
                prefix: new HarmonyMethod(prefix));
            _gameOverPatchApplied = true;
            _diplomacyTribeOrderSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    TribeR3EventHooks.OnTribeIssueOrderWithTarget.Observable,
                    OnDiplomacyTribeOrder);
#if DIPLOMACY_V2
            _diplomacyTribeMoveSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    TribeR3EventHooks.OnTribeIssueOrderMoveHere.Observable,
                    OnV2TribeMoveOrder);
#endif
            _diplomacyProjectileSpawnSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    ProjectileR3EventHooks.OnProjectileSpawn.Observable,
                    OnDiplomacyProjectileSpawn);
            _diplomacySpawnFireSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    ProjectileR3EventHooks.OnSpawnFire.Observable,
                    OnDiplomacySpawnFire);
            _diplomacyMeleeDamageSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    UnitR3EventHooks.OnUnitTakeMeleeDamage.Observable,
                    OnDiplomacyMeleeDamage);
            _diplomacyProjectileDamageSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    UnitR3EventHooks.OnUnitTakeProjectileDamage.Observable,
                    OnDiplomacyProjectileDamage);
            _diplomacyBuildingDamageSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    BuildingR3EventHooks.OnBuildingTileTakeDamage.Observable,
                    OnDiplomacyBuildingDamage);
            _diplomacyAiAttackSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    PlayerR3EventHooks.OnPlayerAIEvaluateAttackOrder.Observable,
                    OnDiplomacyAiAttackEvaluation);
#if DIPLOMACY_V2
            // Der Verteidigungshaken traegt nur den Befehlshebel; einen
            // Buendnisschutz braucht er nicht, weil Verteidigen niemandem
            // schadet (07.09.2026).
            _diplomacyAiDefendSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    PlayerR3EventHooks.OnPlayerAIEvaluateDefendOrder.Observable,
                    OnDiplomacyAiDefendEvaluation);
#endif
            _diplomacyReceivedGoodsSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    PlayerR3EventHooks.OnPlayerAIRequestReceivedGoods.Observable,
                    OnDiplomacyReceivedGoods);
        }

        private void RollbackCombatSafety()
        {
#if DIPLOMACY_V2
            RollbackNativeTruceAdmission();
            RollbackV2AllyOrders();
            RollbackV2HumanOrders();
            RollbackV2CastleBoundaryEvents();
            Dispose(ref _v2VassalRequestSubscription);
            Dispose(ref _diplomacyTribeMoveSubscription);
#endif
            Dispose(ref _diplomacyReceivedGoodsSubscription);
#if DIPLOMACY_V2
            Dispose(ref _diplomacyAiDefendSubscription);
#endif
            Dispose(ref _diplomacyAiAttackSubscription);
            Dispose(ref _diplomacyBuildingDamageSubscription);
            Dispose(ref _diplomacyProjectileDamageSubscription);
            Dispose(ref _diplomacyMeleeDamageSubscription);
            Dispose(ref _diplomacySpawnFireSubscription);
            Dispose(ref _diplomacyProjectileSpawnSubscription);
            Dispose(ref _diplomacyTribeOrderSubscription);
            if (_gameOverPatchApplied && _gameOverTarget != null)
            {
                _gameOverPatchApplied = false;
                _harmony.Unpatch(
                    _gameOverTarget,
                    HarmonyPatchType.Prefix,
                    _harmony.Id);
            }
            ResetCombatSafetyMapState();
        }

#if DIPLOMACY_V2
#endif

        private static bool DiplomacyGameOverPrefix(int __0)
        {
            DiplomacyFeature owner;
            lock (OwnerGate)
            {
                owner = _activeOwner;
            }
            return owner == null || owner.AllowGameOverDuringTransition(__0);
        }

        private bool AllowGameOverDuringTransition(int state)
        {
            lock (_gate)
            {
                if (state != 1)
                {
                    return true;
                }
                if (_rollbackGuardActive)
                {
                    Log(
                        "team_transaction",
                        "status=premature_victory_suppressed"
                        + "|reason=rollback_guard");
                    return false;
                }
                if (!_mapActive || _mapDisabled)
                {
                    return true;
                }
                Dictionary<int, int> partition;
                try
                {
                    DiplomacyPendingTeamTransition pending =
                        _pendingTeamTransition;
                    if (pending != null)
                    {
                        bool expectedHostile = HostileCoalitionRemains(
                            pending.ExpectedPartition);
                        bool targetHostile = HostileCoalitionRemains(
                            pending.TargetPartition);
                        if (!expectedHostile && !targetHostile)
                        {
                            return true;
                        }
                        Log(
                            "team_transaction",
                            "status=premature_victory_suppressed"
                            + "|partition=pending_expected_and_target"
                            + "|expected_hostile=" + BoolText(expectedHostile)
                            + "|target_hostile=" + BoolText(targetHostile));
                        return false;
                    }
                    partition = _transitionGuardPartition
                        ?? _transitionVerificationPartition
                        ?? CurrentSavedPartition();
                    if (!HostileCoalitionRemains(partition))
                    {
                        return true;
                    }
                }
                catch (Exception exception)
                {
                    CaptureCombatSafetyFault(
                        "victory partition guard",
                        exception);
                    Log(
                        "team_transaction",
                        "status=premature_victory_suppressed"
                        + "|reason=partition_unavailable");
                    return false;
                }
                Log(
                    "team_transaction",
                    "status=premature_victory_suppressed|partition="
                    + PartitionText(partition));
                return false;
            }
        }

        private void QueueTeamTransition(
            DiplomacyTeamTransitionKind kind,
            string coalitionId,
            int gameDay,
            string reason,
            Dictionary<int, int> targetPartition)
        {
            bool transferBusy = _nativeTransferProbe != null
                && !_transferBookkeepingInProgress;
            if (_pendingTeamTransition != null || transferBusy)
            {
                Log(
                    "team_transaction",
                    "status=rejected|reason="
                    + (_pendingTeamTransition != null
                        ? "transition_busy"
                        : "transfer_busy")
                    + "|kind="
                    + kind.ToString());
                if (kind != DiplomacyTeamTransitionKind.AiBreak)
                {
                    ShowMessage(Text(
                        "Eine Beziehungsänderung wird noch abgeschlossen.",
                        "A relationship change is still being completed."));
                }
                return;
            }
            Dictionary<int, int> expected = CurrentSavedPartition();
            ValidateRuntimePartition(expected, true);
            ValidateRuntimePartition(targetPartition, false);
            _pendingTeamTransition = new DiplomacyPendingTeamTransition
            {
                Kind = kind,
                CoalitionId = coalitionId,
                GameDay = gameDay,
                Reason = string.IsNullOrEmpty(reason) ? "unspecified" : reason,
                ExpectedPartition = new Dictionary<int, int>(expected),
                TargetPartition = new Dictionary<int, int>(targetPartition),
            };
            _pendingTransitionGeneration = _sessionGeneration;
            _pendingTransitionFingerprint = _mapFingerprint;
            _transitionGuardPartition = new Dictionary<int, int>(
                targetPartition);
            PublishCombatProtectionSnapshot();
            Log(
                "team_transaction",
                "status=queued|kind=" + kind.ToString()
                + "|coalition=" + Safe(coalitionId ?? "all")
                + "|target=" + PartitionText(targetPartition));
        }

        /// <summary>
        /// Teamuebergaenge - seit dem 07.09.2026 die einzige Spur.
        /// </summary>
        /// <remarks>
        /// Frueher lief das waehrend laufender Simulation im Takt des
        /// Extenders, damit kein Simulationsfaden eine halb geschriebene
        /// Partition sieht. Dieser Takt ist ein roher CPU-Kontexthaken, und
        /// dort beendet schon das AUSLOESEN einer verwalteten Ausnahme den
        /// Prozess (gemessen: ntdll+0x123CA7, movaps auf einen
        /// unausgerichteten CONTEXT aus RaiseException). Genau hier wird aber
        /// bewusst geworfen: <see cref="ThrowCombatSafetyFault"/> und drei
        /// Stellen in <see cref="ProcessPendingTeamTransition"/>.
        ///
        /// Seit F01 (08.09.2026) bleibt die atomare native Zusicherung durch
        /// EngineInterface.threadLock erhalten. Der Unity-Faden erwirbt ihn
        /// ausschliesslich nicht blockierend und verschiebt bei Belegung.
        /// </remarks>
        /// <summary>
        /// Hoechste Wartezeit eines Kampfwaechters auf die Sperre.
        /// </summary>
        /// <remarks>
        /// Warum ueberhaupt eine Grenze (07.09.2026, nach einem Aufhaenger):
        /// die Waechter laufen auf dem Simulationsfaden, das Unity-Bild auf
        /// einem anderen - gemessen, nicht vermutet
        /// (`lane_identity ... same_thread=false`). Wartet ein Waechter
        /// unbegrenzt, steht die Simulation, sobald das Bild die Sperre
        /// laenger haelt. Genau so hat sich das Spiel um 12:08 aufgehaengt,
        /// mitten in der erstmaligen Erzeugung des Geschossverwalters.
        ///
        /// Fuenf Millisekunden decken jede gewoehnliche Haltezeit ab. Reicht
        /// es nicht, bleibt dieser eine Schadensfall ungeprueft. Ein
        /// ausgelassener Schuss ist billiger als ein stehendes Spiel.
        /// </remarks>
        private const int CombatGateWaitMilliseconds = 5;

        // Wie oft ein Waechter die Sperre nicht bekommen hat. Bleibt die Zahl
        // bei 0, hat der Schutz nie ausgesetzt.
        private int _combatGateSkips;

        /// <summary>
        /// Betritt die Sperre fuer einen Kampfwaechter - begrenzt.
        /// </summary>
        private bool TryEnterCombatGate()
        {
            if (Monitor.TryEnter(_gate, CombatGateWaitMilliseconds))
            {
                return true;
            }
            Interlocked.Increment(ref _combatGateSkips);
            return false;
        }

        private bool ContendedCombatMustBeBlocked(
            Func<CombatProtectionSnapshot, bool> evaluate)
        {
            CombatProtectionSnapshot snapshot =
                Volatile.Read(ref _combatProtectionSnapshot);
            if (!snapshot.AnyProtection) return false;
            bool blocked;
            try
            {
                blocked = evaluate(snapshot);
            }
            catch
            {
                // Do not throw through a native detour and do not disable
                // the map for an expired unit/projectile lookup.
                Interlocked.Increment(ref _combatSnapshotFaults);
                blocked = true;
            }
            if (blocked) Interlocked.Increment(ref _combatSnapshotBlocks);
            return blocked;
        }

        private void ApplyContendedCombatProtection(
            TribeIssueOrderWithTargetEventArgs e)
        {
            if (!IsAttackCommand(e.AICommand)) return;
            if (!ContendedCombatMustBeBlocked(snapshot =>
            {
                int source = TribeOwner(e.TribeId);
                int target;
                if (TryAttackOrderTargetOwner(e, out target)
                    && snapshot.Protects(source, target)) return true;
                return (e.AICommand == TribeAICommand.AttackTilePosition
                        || e.AICommand == TribeAICommand.ThrowLava)
                    && ContendedProtectedAssetNear(snapshot, source,
                        checked(e.TargetValue1 * WorldPositionsPerLocalTile),
                        checked(e.TargetValue2 * WorldPositionsPerLocalTile),
                        GroundFireProjectileRiskRadiusWorld);
            })) return;
            e.SkipOriginalFunction = true;
            e.ReturnValue = 0;
        }

        private void ApplyContendedCombatProtection(ProjectileSpawnEventArgs e)
        {
            if (!ContendedCombatMustBeBlocked(snapshot =>
            {
                int source = e.PlayerSourceId;
                if (!snapshot.Contains(source)) source = e.UnitPlayerSourceId;
                if (!snapshot.Contains(source) && e.SourceUnitId > 0)
                    source = UnitOwner(e.SourceUnitId);
                int target = e.AttackedUnitId > 0
                    ? UnitOwner(e.AttackedUnitId)
                    : WorldTileOwner(e.TargetWorldTileX, e.TargetWorldTileY);
                return snapshot.Protects(source, target)
                    || IsGroundFireProjectile(e.ProjectileType)
                    && ContendedProtectedAssetNear(snapshot, source,
                        e.TargetWorldTileX, e.TargetWorldTileY,
                        GroundFireProjectileRiskRadiusWorld);
            })) return;
            e.SkipOriginalFunction = true;
            e.ReturnValue = 0;
        }

        private void ApplyContendedCombatProtection(SpawnFireEventArgs e)
        {
            if (!ContendedCombatMustBeBlocked(snapshot =>
                snapshot.Protects(e.SourcePlayerId,
                    WorldTileOwner(e.WorldTileX, e.WorldTileY))
                || ContendedProtectedAssetNear(snapshot, e.SourcePlayerId,
                    e.WorldTileX, e.WorldTileY, FireRiskRadius(e.SpreadRadius))))
                return;
            e.SkipOriginalFunction = true;
            e.ReturnValue = 0;
        }

        private void ApplyContendedCombatProtection(UnitTakeDamageByMeleeEventArgs e)
        {
            if (!ContendedCombatMustBeBlocked(snapshot => snapshot.Protects(
                UnitOwner(e.AttackingUnitId), UnitOwner(e.DamagedUnitId)))) return;
            e.SkipOriginalFunction = true;
            e.ReturnValue = 0;
        }

        private void ApplyContendedCombatProtection(UnitTakeDamageByProjectileEventArgs e)
        {
            if (!ContendedCombatMustBeBlocked(snapshot => snapshot.Protects(
                ProjectileOwner(e.ProjectileId, snapshot),
                UnitOwner(e.AttackedUnitId)))) return;
            e.SkipOriginalFunction = true;
            e.ReturnValue = 0;
        }

        private void ApplyContendedCombatProtection(BuildingTileTakeDamageEventArgs e)
        {
            if (ContendedCombatMustBeBlocked(snapshot => snapshot.Protects(
                e.PlayerIdSource, TileOwnerById(e.TileId)))) e.Damage = 0;
        }

        private void ApplyContendedCombatProtection(PlayerAIEvaluateAttackOrder e)
        {
            if (!ContendedCombatMustBeBlocked(snapshot => snapshot.Protects(
                e.TargetPlayerId, e.ContextPlayerId))) return;
            e.SkipOriginalFunction = true;
            e.ReturnValue = false;
        }

        // Only engine-owned identities/positions are read here. No mutable
        // diplomacy dictionary, no shared scratch list, no sort and no _gate.
        private bool ContendedProtectedAssetNear(CombatProtectionSnapshot snapshot,
            int source, int worldX, int worldY, int radius)
        {
            if (!snapshot.HasProtectionFor(source)) return false;
            int limit = checked(GameTileManagerAPI.MAX_WIDTH * WorldPositionsPerLocalTile);
            if (worldX < 0 || worldY < 0 || worldX >= limit || worldY >= limit)
                return false;
            int bounded = Math.Max(0, Math.Min(radius, limit));
            long square = (long)bounded * bounded;
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            var ids = new List<int>();
            units.GetAllUnits(ids, AliveState.IsAlive);
            foreach (int id in ids)
            {
                if (!snapshot.Protects(source, UnitOwner(id))) continue;
                UnmanagedVector2<ushort> position = units.GetCurrentWorldTilePosition(id);
                long dx = (long)position.X - worldX;
                long dy = (long)position.Y - worldY;
                if (dx * dx + dy * dy <= square) return true;
            }
            int firstX = Math.Max(0, worldX - bounded) / WorldPositionsPerLocalTile;
            int lastX = Math.Min(limit - 1, worldX + bounded) / WorldPositionsPerLocalTile;
            int firstY = Math.Max(0, worldY - bounded) / WorldPositionsPerLocalTile;
            int lastY = Math.Min(limit - 1, worldY + bounded) / WorldPositionsPerLocalTile;
            for (int x = firstX; x <= lastX; x++)
                for (int y = firstY; y <= lastY; y++)
                {
                    if (!snapshot.Protects(source, TileOwner(x, y))) continue;
                    long lowX = (long)x * WorldPositionsPerLocalTile;
                    long lowY = (long)y * WorldPositionsPerLocalTile;
                    long highX = lowX + WorldPositionsPerLocalTile - 1;
                    long highY = lowY + WorldPositionsPerLocalTile - 1;
                    long dx = worldX < lowX ? lowX - worldX : worldX > highX ? worldX - highX : 0;
                    long dy = worldY < lowY ? lowY - worldY : worldY > highY ? worldY - highY : 0;
                    if (dx * dx + dy * dy <= square) return true;
                }
            return false;
        }

        private bool ProcessTeamTransitionFrame()
        {
            ThrowCombatSafetyFault();
            if (_transitionVerificationPartition == null && _pendingTeamTransition == null)
                return true;
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease)) return false;
            using (lease)
            {
                VerifyCommittedTransition();
                return ProcessPendingTeamTransition("runtime_frame");
            }
        }

        private void ThrowCombatSafetyFault()
        {
            if (_combatSafetyFault != null)
            {
                Exception failure = _combatSafetyFault;
                _combatSafetyFault = null;
                throw new InvalidOperationException(
                    "native diplomacy combat guard failed",
                    failure);
            }
        }

        private bool ProcessPendingTeamTransition(string executionLane)
        {
            DiplomacyPendingTeamTransition transition =
                _pendingTeamTransition;
            if (transition == null
                || _nativeTransferProbe != null)
            {
                return true;
            }
            if (_pendingTransitionGeneration != _sessionGeneration
                || !string.Equals(
                    _pendingTransitionFingerprint,
                    _mapFingerprint,
                    StringComparison.Ordinal))
            {
                // A delayed request is obsolete after a lifecycle change.
                // Never replay its old player IDs into the new map.
                _pendingTeamTransition = null;
                _pendingTransitionGeneration = 0;
                _pendingTransitionFingerprint = null;
                _transitionGuardPartition = null;
                PublishCombatProtectionSnapshot();
                Log("team_transaction",
                    "status=cancelled|reason=stale_session");
                return true;
            }
            // _gate protects the journal, not the engine's team array. Keep
            // preconditions, every team write, quarantine and rollback atomic
            // with DLL_RunTick; busy means retain the same pending operation.
            IDisposable nativeLease;
            if (!TryEnterNativeInventorySection(out nativeLease)) return false;
            using (nativeLease)
            {
            bool expectedMatches =
                LivePartitionMatches(transition.ExpectedPartition);
            bool targetAlreadyApplied = !expectedMatches
                && LivePartitionMatches(transition.TargetPartition);
            if (!expectedMatches && !targetAlreadyApplied)
            {
                throw new InvalidOperationException(
                    "native team partition changed before diplomacy commit");
            }

            BeginStableSaveSection(
                "team_transition",
                transition.ExpectedPartition);
            bool nativeMutatedByFeature = false;
            DiplomacyManagedStateMemento managedMemento =
                CaptureManagedStateMemento();
            _transitionGuardPartition = new Dictionary<int, int>(
                transition.TargetPartition);
            PublishCombatProtectionSnapshot();
            try
            {
                string cancellationReason =
                    ObsoleteFormAllianceReason(transition)
                    ?? ValidateTransitionPrecondition(transition);
                if (cancellationReason != null)
                {
                    bool cancellationTargetWasApplied =
                        targetAlreadyApplied;
                    if (targetAlreadyApplied)
                    {
                        TeamTransactionResult cancellationRollback =
                            DiplomacyTeamTransaction.RestoreExpected(
                                _teamPort,
                                transition.ExpectedPartition);
                        if (!cancellationRollback.Applied)
                        {
                            throw new InvalidOperationException(
                                "obsolete alliance target could not be rolled "
                                + "back: " + cancellationRollback.Failure);
                        }
                        nativeMutatedByFeature = true;
                        RecordExpectedPartitionOwnership(
                            transition.ExpectedPartition);
                        // Expected is once again the stable native baseline;
                        // a later managed/UI failure must not attempt to undo
                        // this successful safety rollback back to Target.
                        nativeMutatedByFeature = false;
                        targetAlreadyApplied = false;
                    }
                    if (!LivePartitionMatches(
                        transition.ExpectedPartition))
                    {
                        throw new InvalidOperationException(
                            "obsolete alliance rollback changed after readback");
                    }
                    CancelObsoleteTeamTransition(
                        transition,
                        cancellationReason,
                        cancellationTargetWasApplied);
                    return true;
                }
                if (!targetAlreadyApplied)
                {
                    if (!ApplyTeamPartition(
                        transition.TargetPartition,
                        executionLane + "_" + transition.Kind.ToString()))
                    {
                        throw new InvalidOperationException(
                            "native team transaction was rejected");
                    }
                    nativeMutatedByFeature = true;
                }
                int stoppedTribes = QuarantineAlliedTribes(
                    transition.TargetPartition);
                int deletedProjectiles = QuarantineAlliedProjectiles(
                    transition.TargetPartition);
                int clearedBuildingFires =
                    QuarantineAlliedBuildingFires(
                        transition.TargetPartition);
                int clearedAiTargets = QuarantineAlliedAiTargets(
                    transition.TargetPartition);
                if (!LivePartitionMatches(transition.TargetPartition))
                {
                    throw new InvalidOperationException(
                        "native team transaction readback changed during quarantine");
                }
                CommitTransitionState(transition);
                _pendingTeamTransition = null;
                _pendingTransitionGeneration = 0;
                _pendingTransitionFingerprint = null;
                _transitionVerificationPartition =
                    new Dictionary<int, int>(transition.TargetPartition);
                _transitionVerificationStartedTick = ReadSimulationTick();
                QueueNextExpiredUltimatum(transition.GameDay);
                Log(
                    "team_transaction",
                    "status=native_commit|kind=" + transition.Kind.ToString()
                    + "|journal_state=" + (targetAlreadyApplied
                        ? "target_applied"
                        : "expected")
                    + "|tribes_stopped=" + stoppedTribes.ToString(
                        CultureInfo.InvariantCulture)
                    + "|projectiles_deleted=" + deletedProjectiles.ToString(
                        CultureInfo.InvariantCulture)
                    + "|building_fires_cleared="
                    + clearedBuildingFires.ToString(
                        CultureInfo.InvariantCulture)
                    + "|ai_targets_cleared=" + clearedAiTargets.ToString(
                        CultureInfo.InvariantCulture)
                    + "|combat_events_blocked="
                    + _transitionBlockedCombatEvents.ToString(
                        CultureInfo.InvariantCulture));
                _transitionBlockedCombatEvents = 0;
            }
            catch (Exception exception)
            {
                string rollbackFailure = null;
                string managedRollbackFailure = null;
                try
                {
                    RestoreManagedStateMemento(managedMemento);
                }
                catch (Exception managedException)
                {
                    managedRollbackFailure = managedException.GetType().Name
                        + ":" + Safe(managedException.Message);
                }
                if (nativeMutatedByFeature || targetAlreadyApplied)
                {
                    TeamTransactionResult rollback =
                        DiplomacyTeamTransaction.RestoreExpected(
                            _teamPort,
                            transition.ExpectedPartition);
                    if (rollback.Applied)
                    {
                        RebuildTeamOwnership(
                            transition.ExpectedPartition);
                    }
                    else
                    {
                        rollbackFailure = rollback.Failure;
                        foreach (KeyValuePair<int, int> expected
                            in transition.ExpectedPartition)
                        {
                            if (targetAlreadyApplied
                                && !_ownedOriginalTeams.ContainsKey(
                                    expected.Key))
                            {
                                _ownedOriginalTeams[expected.Key] =
                                    expected.Value;
                            }
                            int current;
                            try
                            {
                                current = _teamPort.GetTeam(expected.Key);
                            }
                            catch (Exception readException)
                            {
                                rollbackFailure += "; ownership_read="
                                    + readException.GetType().Name;
                                continue;
                            }
                            int target = transition.TargetPartition[
                                expected.Key];
                            if (current == expected.Value
                                || current == target)
                            {
                                _ownedAssignedTeams[expected.Key] = current;
                            }
                        }
                    }
                }
                throw new InvalidOperationException(
                    "diplomacy team transition failed"
                    + (rollbackFailure == null
                        ? string.Empty
                        : "; rollback=" + rollbackFailure)
                    + (managedRollbackFailure == null
                        ? string.Empty
                        : "; managed_rollback="
                            + managedRollbackFailure),
                    exception);
            }
            finally
            {
                _transitionGuardPartition = _pendingTeamTransition == null
                    ? null
                    : new Dictionary<int, int>(
                        _pendingTeamTransition.TargetPartition);
                EndStableSaveSection();
                PublishCombatProtectionSnapshot();
            }
            return true;
            }
        }

        private string ObsoleteFormAllianceReason(
            DiplomacyPendingTeamTransition transition)
        {
            if (transition == null
                || transition.Kind
                    != DiplomacyTeamTransitionKind.FormAlliance)
            {
                return null;
            }
            CoalitionState coalition;
            RelationState relation;
            if (string.IsNullOrEmpty(transition.CoalitionId)
                || !_coalitions.TryGetValue(
                    transition.CoalitionId,
                    out coalition)
                || !_relations.TryGetValue(
                    transition.CoalitionId,
                    out relation)
                || relation.Allied
                || coalition.Allied)
            {
                return null;
            }
            if (!coalition.MemberPlayerIds.Any(IsAlivePlayer))
            {
                return "coalition_defeated";
            }
            return CanJoinAlliance(transition.CoalitionId)
                ? null
                : "last_hostile_coalition";
        }

        private void CancelObsoleteFormAlliance(
            DiplomacyPendingTeamTransition transition,
            string reason,
            bool targetWasApplied)
        {
            RelationState relation = _relations[transition.CoalitionId];
            relation.PendingOffer = false;
            relation.PendingOfferIssuedDay = -1;
            if (relation.Demand != null
                && !relation.Demand.IsUltimatum)
            {
                relation.Demand = null;
            }
            _pendingTeamTransition = null;
            _pendingTransitionGeneration = 0;
            _pendingTransitionFingerprint = null;
            _transitionVerificationPartition =
                new Dictionary<int, int>(transition.ExpectedPartition);
            _transitionVerificationStartedTick = ReadSimulationTick();
            CancelBlockedEnemyDemands();
            ShowMessage(string.Equals(
                    reason,
                    "coalition_defeated",
                    StringComparison.Ordinal)
                ? Text(
                    "Bündnis nicht möglich: Die Koalition wurde besiegt.",
                    "Alliance unavailable: the coalition was defeated.")
                : Text(
                    "Bündnis nicht möglich: Ein feindlicher KI-Verbund muss verbleiben.",
                    "Alliance unavailable: one hostile AI coalition must remain."));
            Log(
                "team_transaction",
                "status=cancelled|kind=FormAlliance|reason=" + reason
                + "|target_was_applied=" + BoolText(targetWasApplied)
                + "|partition="
                + PartitionText(transition.ExpectedPartition));
        }

        private void CancelObsoleteTeamTransition(
            DiplomacyPendingTeamTransition transition,
            string reason,
            bool targetWasApplied)
        {
#if DIPLOMACY_V2
            RelationState submissionRelation;
            if (transition.Reason == "submission_offer"
                && !string.IsNullOrEmpty(transition.CoalitionId)
                && _relations.TryGetValue(transition.CoalitionId, out submissionRelation)
                && submissionRelation.V2 != null)
                DiplomacyV2Submission.CloseOffer(submissionRelation.V2,
                    Math.Max(0, _lastProcessedDay), false);
#endif
            if (transition.Kind == DiplomacyTeamTransitionKind.FormAlliance
                && (reason == "coalition_defeated"
                    || reason == "last_hostile_coalition"))
            {
                CancelObsoleteFormAlliance(transition, reason, targetWasApplied);
                return;
            }
            // Ordinary state changes invalidate a queued choice; they do not
            // invalidate the map. Native rollback has already been verified
            // by the caller before this managed request is forgotten.
            _pendingTeamTransition = null;
            _pendingTransitionGeneration = 0;
            _pendingTransitionFingerprint = null;
            _transitionVerificationPartition =
                new Dictionary<int, int>(transition.ExpectedPartition);
            _transitionVerificationStartedTick = ReadSimulationTick();
            Log("team_transaction",
                "status=cancelled|kind=" + transition.Kind.ToString()
                + "|reason=" + reason
                + "|target_was_applied=" + BoolText(targetWasApplied));
        }

        private void RecordExpectedPartitionOwnership(
            IReadOnlyDictionary<int, int> expectedPartition)
        {
            RebuildTeamOwnership(expectedPartition);
        }

        private bool DrainTeamTransitionsAtDayBoundary(string executionLane)
        {
            int processed = 0;
            int limit = Math.Max(1, _coalitions.Count + 1);
            while (_pendingTeamTransition != null)
            {
                DiplomacyPendingTeamTransition before =
                    _pendingTeamTransition;
                if (!ProcessPendingTeamTransition(executionLane)) return false;
                processed++;
                if (ReferenceEquals(before, _pendingTeamTransition)
                    || processed > limit)
                {
                    throw new InvalidOperationException(
                        "diplomacy team transition queue did not drain");
                }
            }
            return true;
        }

        private void QueueNextExpiredUltimatum(int gameDay)
        {
            if (_pendingTeamTransition != null)
            {
                return;
            }
            CoalitionState expired = _coalitions.Values
                .Where(coalition =>
                {
                    RelationState relation =
                        _relations[coalition.CoalitionId];
                    return relation.Allied
                        && relation.Demand != null
                        && relation.Demand.IsUltimatum
                        && !relation.Demand.Complete
                        && gameDay >= relation.Demand.ExpiresDay;
                })
                .OrderBy(
                    coalition => coalition.CoalitionId,
                    StringComparer.Ordinal)
                .FirstOrDefault();
            if (expired != null)
            {
                BreakCoalition(
                    expired,
                    gameDay,
                    "ultimatum_expired_queued");
            }
        }

        private void VerifyCommittedTransition()
        {
            if (_transitionVerificationPartition == null)
            {
                return;
            }
            if (!LivePartitionMatches(_transitionVerificationPartition))
            {
                throw new InvalidOperationException(
                    "native team partition did not survive the commit tick");
            }
            if (ReadSimulationTick() <= _transitionVerificationStartedTick)
            {
                return;
            }
            foreach (CoalitionState coalition in _coalitions.Values)
            {
                bool nativeAllied = PartitionAllies(
                    _transitionVerificationPartition,
                    _localPlayer,
                    coalition.MemberPlayerIds[0]);
                if (_relations[coalition.CoalitionId].Allied != nativeAllied
                    || coalition.Allied != nativeAllied)
                {
                    throw new InvalidOperationException(
                        "managed diplomacy state differs from native teams");
                }
            }
            Log(
                "team_transaction",
                "status=verified|partition="
                + PartitionText(_transitionVerificationPartition));
            _transitionVerificationPartition = null;
            _transitionVerificationStartedTick = 0;
        }

        private string ValidateTransitionPrecondition(
            DiplomacyPendingTeamTransition transition)
        {
            if (transition.Kind == DiplomacyTeamTransitionKind.PlayerBreakAll)
            {
                if (transition.CoalitionId != null)
                {
                    return "player_break_names_coalition";
                }
                if (!_relations.Values.Any(relation => relation.Allied))
                {
                    return "alliance_already_ended";
                }
                return null;
            }
            CoalitionState coalition;
            RelationState relation;
            if (string.IsNullOrEmpty(transition.CoalitionId)
                || !_coalitions.TryGetValue(
                    transition.CoalitionId,
                    out coalition)
                || !_relations.TryGetValue(
                    transition.CoalitionId,
                    out relation))
            {
                return "coalition_unavailable";
            }
            if (transition.Kind == DiplomacyTeamTransitionKind.FormAlliance)
            {
#if DIPLOMACY_V2
                bool relationshipReady = transition.Reason == "submission_offer"
                    ? V2SubmissionTransitionCurrent(coalition, relation, transition.GameDay)
                    : relation.PendingOffer
                        || DiplomacyPolicy.CanFormAlliance(relation, coalition.Target);
#else
                bool relationshipReady = relation.PendingOffer
                    || relation.Goodwill >= coalition.Target
                    || relation.Demand != null
                        && !relation.Demand.IsUltimatum
                        && relation.Demand.Complete;
#endif
                if (relation.Allied || coalition.Allied
                    || !CanJoinAlliance(coalition.CoalitionId)
                    || !relationshipReady)
                {
                    return "alliance_precondition_changed";
                }
                return null;
            }
#if DIPLOMACY_V2
            if (transition.Kind == DiplomacyTeamTransitionKind.PlayerBreakOne)
            {
                if (!relation.Allied || !coalition.Allied)
                {
                    return "alliance_already_ended";
                }
                return null;
            }
#endif
            if (transition.Kind == DiplomacyTeamTransitionKind.AiBreak)
            {
                if (!relation.Allied || !coalition.Allied)
                {
                    return "alliance_already_ended";
                }
#if DIPLOMACY_V2
                // These obligations produce AiBreak without an ultimatum.
                // The old demand-only check disabled diplomacy after either
                // legitimate breach (engine audit E3, 07.09.2026).
                DiplomacyV2BreachKind breach = transition.Reason
                        == TributeDefaultReason
                    ? DiplomacyV2BreachKind.TributeDefault
                    : transition.Reason == VassalRebellionReason
                        ? DiplomacyV2BreachKind.VassalRebellion
                        : DiplomacyV2BreachKind.FailedSupportUltimatum;
                return DiplomacyV2StateMachine.CanCommitAllianceBreak(
                        relation, transition.GameDay, breach)
                    ? null : "alliance_break_no_longer_applicable";
#else
                if (relation.Demand == null
                    || !relation.Demand.IsUltimatum
                    || relation.Demand.Complete
                    || transition.GameDay < relation.Demand.ExpiresDay)
                {
                    return "ultimatum_no_longer_applicable";
                }
#endif
            }
            return null;
        }

#if DIPLOMACY_V2
        private void CommitV2PlayerBreakOne(
            DiplomacyPendingTeamTransition transition)
        {
            CoalitionState coalition = _coalitions[transition.CoalitionId];
            RefreshCoalition(coalition);
            DiplomacyPolicy.BreakAlliance(
                _relations[transition.CoalitionId],
                transition.GameDay,
                coalition.Target,
                DiplomacyV2BreachKind.PlayerAllianceAbandonment,
                _rules);
            coalition.Allied = false;
            int observersChanged = 0;
            foreach (CoalitionState observer in _coalitions.Values.OrderBy(
                value => value.CoalitionId,
                StringComparer.Ordinal))
            {
                if (string.Equals(
                        observer.CoalitionId,
                        transition.CoalitionId,
                        StringComparison.Ordinal)
                    || !observer.MemberPlayerIds.Any(IsAlivePlayer)
                    || _relations[observer.CoalitionId].Allied)
                {
                    continue;
                }
                DiplomacyPolicy.RecordObservedAllianceAbandonment(
                    _relations[observer.CoalitionId],
                    transition.GameDay,
                    observer.Target,
                    1);
                observersChanged++;
            }
            ShowMessage(Text(
                "Das gewählte Bündnis wurde aufgehoben. Andere feindliche Fürsten misstrauen Euch nun stärker.",
                "The selected alliance has ended. Other hostile lords now distrust you more."));
            Log(
                "break",
                "coalition=" + coalition.CoalitionId
                + "|actor=player|status=complete"
                + "|observers=" + observersChanged.ToString(
                    CultureInfo.InvariantCulture));
        }
#endif

        private void CommitTransitionState(
            DiplomacyPendingTeamTransition transition)
        {
            if (transition.Kind == DiplomacyTeamTransitionKind.FormAlliance)
            {
                CoalitionState coalition =
                    _coalitions[transition.CoalitionId];
                RefreshCoalition(coalition);
                DiplomacyPolicy.BeginAlliance(
                    _relations[transition.CoalitionId],
                    transition.GameDay,
                    false,
                    _rules);
                coalition.Allied = true;
                CancelBlockedEnemyDemands();
                if (!string.Equals(
                        transition.Reason,
                        "spontaneous_offer",
                        StringComparison.Ordinal))
                {
                    PlayCoalitionSpeech(
                        coalition,
                        "SK_ADD_PLAYER",
                        "add_player");
                }
                ShowMessage(Text(
                    "Das Bündnis wurde geschlossen.",
                    "The alliance has been formed."));
                Log(
                    "alliance",
                    "coalition=" + coalition.CoalitionId
                    + "|status=formed|reason=" + Safe(transition.Reason));
#if DIPLOMACY_V2
                // Hier und nur hier entsteht ein Lehnsverhaeltnis: im
                // Augenblick des Buendnisschlusses, aus dem Kraefteverhaeltnis
                // (Befund D, 07.09.2026). Der Aufruf steht NACH der Meldung
                // ueber das Buendnis, damit der Spieler die Reihenfolge
                // erlebt, in der es geschieht.
                if (!CommitV2PendingSubmission(coalition,
                        _relations[transition.CoalitionId], transition.GameDay))
                    EvaluateV2VassalageOnAlliance(
                        coalition,
                        _relations[transition.CoalitionId],
                        transition.GameDay);
#endif
                return;
            }
            if (transition.Kind == DiplomacyTeamTransitionKind.AiBreak)
            {
                CoalitionState coalition =
                    _coalitions[transition.CoalitionId];
                RefreshCoalition(coalition);
#if DIPLOMACY_V2
                // Die Bruchart reist im Grund mit - der Uebergang wird im
                // V1-Format gespeichert, ein eigenes Feld waere eine
                // Formataenderung (07.09.2026).
                bool auflehnung = string.Equals(
                    transition.Reason,
                    VassalRebellionReason,
                    StringComparison.Ordinal);
                bool tributverzug = string.Equals(
                    transition.Reason,
                    TributeDefaultReason,
                    StringComparison.Ordinal);
                DiplomacyPolicy.BreakAlliance(
                    _relations[transition.CoalitionId],
                    transition.GameDay,
                    coalition.Target,
                    auflehnung
                        ? DiplomacyV2BreachKind.VassalRebellion
                        : tributverzug
                            ? DiplomacyV2BreachKind.TributeDefault
                            : DiplomacyV2BreachKind.FailedSupportUltimatum,
                    _rules);
#else
                DiplomacyPolicy.BreakAlliance(
                    _relations[transition.CoalitionId],
                    transition.GameDay,
                    _rules);
#endif
                coalition.Allied = false;
                PlayCoalitionSpeech(
                    coalition,
                    "SK_KICK_PLAYER",
                    "kick_player");
#if DIPLOMACY_V2
                ShowMessage(auflehnung
                    ? Text(
                        "Euer Vasall hat sich losgesagt. Er ist Euch nun feind.",
                        "Your vassal has broken away. He is your enemy now.")
                    : tributverzug
                        ? Text(
                            "Der Tribut blieb zweimal aus. Das Bündnis ist beendet.",
                            "The tribute went unpaid twice. The alliance has ended.")
                        : Text(
                            "Der Gegner hat das Bündnis aufgehoben.",
                            "The opponent has ended the alliance."));
#else
                ShowMessage(Text(
                    "Der Gegner hat das Bündnis aufgehoben.",
                    "The opponent has ended the alliance."));
#endif
                Log(
                    "break",
                    "coalition=" + coalition.CoalitionId
                    + "|actor=ai|reason=" + Safe(transition.Reason));
                return;
            }
#if DIPLOMACY_V2
            if (transition.Kind == DiplomacyTeamTransitionKind.PlayerBreakOne)
            {
                CommitV2PlayerBreakOne(transition);
                return;
            }
#endif
#if DIPLOMACY_V2
            HashSet<string> abandonedCoalitions = new HashSet<string>(
                _relations.Values
                    .Where(relation => relation.Allied)
                    .Select(relation => relation.CoalitionId),
                StringComparer.Ordinal);
#endif
            foreach (CoalitionState coalition in _coalitions.Values)
            {
                RefreshCoalition(coalition);
#if DIPLOMACY_V2
                // Treaties are independent from native alliances in V2.
                // Ending all alliances must only penalise coalitions that
                // were actually allied, not unrelated trade partners.
                if (!_relations[coalition.CoalitionId].Allied)
                {
                    continue;
                }
#endif
#if DIPLOMACY_V2
                DiplomacyPolicy.BreakAlliance(
                    _relations[coalition.CoalitionId],
                    transition.GameDay,
                    coalition.Target,
                    DiplomacyV2BreachKind.PlayerAllianceAbandonment,
                    _rules);
#else
                DiplomacyPolicy.BreakAlliance(
                    _relations[coalition.CoalitionId],
                    transition.GameDay,
                    _rules);
#endif
                coalition.Allied = false;
            }
#if DIPLOMACY_V2
            int abandonedCount = abandonedCoalitions.Count;
            foreach (CoalitionState observer in _coalitions.Values.OrderBy(
                value => value.CoalitionId,
                StringComparer.Ordinal))
            {
                if (abandonedCoalitions.Contains(observer.CoalitionId)
                    || !observer.MemberPlayerIds.Any(IsAlivePlayer))
                {
                    continue;
                }
                DiplomacyPolicy.RecordObservedAllianceAbandonment(
                    _relations[observer.CoalitionId],
                    transition.GameDay,
                    observer.Target,
                    abandonedCount);
            }
            ShowMessage(Text(
                "Alle Bündnisse wurden aufgehoben. Die übrigen Fürsten misstrauen Euch nun stärker.",
                "All alliances have been ended. The remaining lords now distrust you more."));
            Log("break", "actor=player|status=complete|alliances="
                + abandonedCoalitions.Count.ToString(
                    CultureInfo.InvariantCulture));
#else
            ShowMessage(Text(
                "Alle Bündnisse wurden aufgehoben.",
                "All alliances have been ended."));
            Log("break", "actor=player|status=complete");
#endif
        }

        private void ValidateRuntimePartition(
            IDictionary<int, int> partition,
            bool allowTeamZero)
        {
            if (partition == null
                || !new HashSet<int>(partition.Keys).SetEquals(_roster))
            {
                throw new InvalidOperationException(
                    "team partition does not cover the exact roster");
            }
            foreach (int team in partition.Values)
            {
                if (team < (allowTeamZero ? 0 : 1) || team > 8)
                {
                    throw new InvalidOperationException(
                        "team partition contains an invalid native team");
                }
            }
        }

        private bool LivePartitionMatches(
            IDictionary<int, int> partition)
        {
            RequireNativeDiplomacySection();
            return partition != null && partition.All(entry =>
                _teamPort.GetTeam(entry.Key) == entry.Value);
        }

        private bool HostileCoalitionRemains(
            IDictionary<int, int> partition)
        {
            return _coalitions.Values.Any(coalition =>
                coalition.MemberPlayerIds.Any(playerId =>
                    IsAlivePlayer(playerId)
                    && !PartitionAllies(
                        partition,
                        _localPlayer,
                        playerId)));
        }

        private static bool PartitionAllies(
            IDictionary<int, int> partition,
            int first,
            int second)
        {
            int firstTeam;
            int secondTeam;
            return first != second
                && partition != null
                && partition.TryGetValue(first, out firstTeam)
                && partition.TryGetValue(second, out secondTeam)
                && firstTeam > 0
                && secondTeam > 0
                && firstTeam == secondTeam;
        }

        private bool NativePlayersAreAllied(int first, int second)
        {
            if (first <= 0 || second <= 0 || first == second
                || !_roster.Contains(first) || !_roster.Contains(second))
            {
                return false;
            }
#if DIPLOMACY_V2
            if (V2TreatyProtectsPlayers(first, second))
            {
                return true;
            }
#endif
            if (_rollbackGuardActive)
            {
                if (_rollbackGuardBeforePartition == null
                    || _rollbackGuardAfterPartition == null)
                {
                    // A failed native snapshot is not permission to let a
                    // combat event cross a half-written relationship graph.
                    return true;
                }
                return PartitionAllies(
                        _rollbackGuardBeforePartition,
                        first,
                        second)
                    || PartitionAllies(
                        _rollbackGuardAfterPartition,
                        first,
                        second);
            }
            IDictionary<int, int> partition =
                _transitionGuardPartition
                ?? _transitionVerificationPartition;
            if (partition != null)
            {
                return PartitionAllies(partition, first, second);
            }
            int firstTeam = _teamPort.GetTeam(first);
            int secondTeam = _teamPort.GetTeam(second);
            return firstTeam > 0
                && secondTeam > 0
                && firstTeam == secondTeam;
        }

        private bool CombatGuardOperational()
        {
            return (_rollbackGuardActive
                    || _mapActive && !_mapDisabled)
                && _roster.Count > 1;
        }

        /// <summary>
        /// Ob <see cref="NativePlayersAreAllied"/> fuer irgendein Paar der
        /// Aufstellung wahr sein kann.
        /// </summary>
        /// <remarks>
        /// Dieselben Quellen, aus denen NativePlayersAreAllied sein Urteil
        /// zieht: laufende Rueckroll-/Uebergangspartitionen, gemeldete
        /// Buendnisse, aktive V2-Pakte und native KI-Teams (eine Koalition mit
        /// mehr als einem Mitglied teilt sich ein Team). Ist keine davon
        /// vorhanden, ist jede Umkreissuche vergeblich und darf entfallen.
        /// Absichtlich konservativ: im Zweifel wird gesucht.
        /// </remarks>
        private bool AnyProtectedPairPossible()
        {
            if (_rollbackGuardActive
                || _transitionGuardPartition != null
                || _transitionVerificationPartition != null)
            {
                return true;
            }
            foreach (RelationState relation in _relations.Values)
            {
                if (relation.Allied)
                {
                    return true;
                }
#if DIPLOMACY_V2
                if (V2HasBreakableAgreement(relation))
                {
                    return true;
                }
#endif
            }
            foreach (CoalitionState coalition in _coalitions.Values)
            {
                if (coalition.MemberPlayerIds != null
                    && coalition.MemberPlayerIds.Length > 1)
                {
                    return true;
                }
            }
            return false;
        }

        private Dictionary<int, int> ArmTeamRollbackGuard(
            out string snapshotFailure)
        {
            RequireNativeDiplomacySection();
            _rollbackGuardActive = true;
            _rollbackGuardBeforePartition = null;
            _rollbackGuardAfterPartition = null;
            PublishCombatProtectionSnapshot();
            try
            {
                Dictionary<int, int> before = CurrentSavedPartition();
                var after = new Dictionary<int, int>(before);
                foreach (KeyValuePair<int, int> assigned
                    in _ownedAssignedTeams)
                {
                    int original;
                    int current;
                    if (_ownedOriginalTeams.TryGetValue(
                            assigned.Key,
                            out original)
                        && before.TryGetValue(
                            assigned.Key,
                            out current)
                        && current == assigned.Value)
                    {
                        after[assigned.Key] = original;
                    }
                }
                _rollbackGuardBeforePartition = before;
                _rollbackGuardAfterPartition = after;
                PublishCombatProtectionSnapshot();
                snapshotFailure = null;
                return after;
            }
            catch (Exception exception)
            {
                snapshotFailure = exception.GetType().Name
                    + ":" + Safe(exception.Message);
                return null;
            }
        }

        private void RecordBlockedCombat(string path, int source, int target)
        {
            // Keep both eight-message budgets closed at the counter limit.
            DiplomacyRuntimeSafety.SaturatingIncrement(ref _transitionBlockedCombatEvents);
            if (_transitionBlockedCombatEvents <= 8)
            {
                Log(
                    "combat_guard",
                    "status=blocked|path=" + path
                    + "|source=" + source.ToString(CultureInfo.InvariantCulture)
                    + "|target=" + target.ToString(CultureInfo.InvariantCulture));
            }
        }

        private void CaptureCombatSafetyFault(string stage, Exception exception)
        {
            if (_combatSafetyFault == null)
            {
                _combatSafetyFault = new InvalidOperationException(stage, exception);
                Log(
                    "combat_guard",
                    "status=fault_staged|stage=" + Safe(stage)
                    + "|reason=" + Safe(
                        exception.GetType().Name + ":" + exception.Message));
            }
        }

        private void OnDiplomacyTribeOrder(
            TribeIssueOrderWithTargetEventArgs e)
        {

            NoteLane(LaneNative);
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
#if DIPLOMACY_V2
            // Only the matching order in the current human RunTick can use
            // this allowance, never an autonomous damage/targeting callback.
            try { if (AllowV2CapturedHumanTribeOrder(e)) return; }
            catch { } // A failed optional input attribution keeps protection.
#endif
            if (!TryEnterCombatGate())
            {
                ApplyContendedCombatProtection(e);
                return;
            }
            try
            {
                if (!CombatGuardOperational())
                {
                    return;
                }
                bool attackCommand = IsAttackCommand(e.AICommand);
                if (!attackCommand)
                {
                    return;
                }
                try
                {
                    int source = TribeOwner(e.TribeId);
                    int target;
                    bool targetResolved =
                        TryAttackOrderTargetOwner(e, out target);
#if DIPLOMACY_V2
                    if (!targetResolved && source > 0)
                    {
                        targetResolved =
                            V2TryResolveProtectedGroundAttackTarget(
                                source,
                                e.AICommand,
                                e.TargetValue1,
                                e.TargetValue2,
                                out target);
                    }
#endif
                    if (source <= 0 || !targetResolved)
                    {
                        return;
                    }
                    if (NativePlayersAreAllied(source, target))
                    {
                        e.SkipOriginalFunction = true;
                        e.ReturnValue = 0;
                        RecordBlockedCombat("tribe_order", source, target);
                    }
#if DIPLOMACY_V2
                    else
                    {
                        V2RecordUnprotectedHostileAct(source, target);
                    }
#endif
                }
                catch (Exception exception)
                {
                    e.SkipOriginalFunction = true;
                    e.ReturnValue = 0;
                    CaptureCombatSafetyFault("tribe attack-order guard", exception);
                }
            }
            finally
            {
                Monitor.Exit(_gate);
            }
        }

        private void OnDiplomacyProjectileSpawn(ProjectileSpawnEventArgs e)
        {

            NoteLane(LaneNative);
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            if (!TryEnterCombatGate())
            {
                ApplyContendedCombatProtection(e);
                return;
            }
            try
            {
                if (!CombatGuardOperational())
                {
                    return;
                }
                try
                {
                    int source = ProjectileEventSourceOwner(e);
                    int target = e.AttackedUnitId > 0
                        ? UnitOwner(e.AttackedUnitId)
                        : WorldTileOwner(
                            e.TargetWorldTileX,
                            e.TargetWorldTileY);
                    if (NativePlayersAreAllied(source, target))
                    {
                        e.SkipOriginalFunction = true;
                        e.ReturnValue = 0;
                        RecordBlockedCombat("projectile_spawn", source, target);
                    }
#if DIPLOMACY_V2
                    else
                    {
                        int diplomaticTarget = target;
                        int nearbyTreatyTarget;
                        if (IsGroundFireProjectile(e.ProjectileType)
                            && V2TryFindDiplomaticCounterpartNearWorldTarget(
                                source,
                                e.TargetWorldTileX,
                                e.TargetWorldTileY,
                                GroundFireProjectileRiskRadiusWorld,
                                true,
                                out nearbyTreatyTarget))
                        {
                            diplomaticTarget = nearbyTreatyTarget;
                        }
                        // Fire projectiles can target neutral ground beside
                        // units. Resolve that indirect target before allowing
                        // the projectile to cross a truce boundary; waiting
                        // for the later fire event leaves a native impact
                        // window that need not exist.
                        if (NativePlayersAreAllied(
                                source,
                                diplomaticTarget))
                        {
                            e.SkipOriginalFunction = true;
                            e.ReturnValue = 0;
                            RecordBlockedCombat(
                                "projectile_spawn_near_treaty",
                                source,
                                diplomaticTarget);
                            return;
                        }
                        if (diplomaticTarget > 0)
                        {
                            V2RecordUnprotectedHostileAct(
                                source,
                                diplomaticTarget);
                        }
                        else if (IsGroundFireProjectile(e.ProjectileType))
                        {
                            V2AttributeHostileActNearWorldTarget(
                                source,
                                e.TargetWorldTileX,
                                e.TargetWorldTileY,
                                GroundFireProjectileRiskRadiusWorld);
                        }
                    }
#endif
                }
                catch (Exception exception)
                {
                    e.SkipOriginalFunction = true;
                    e.ReturnValue = 0;
                    CaptureCombatSafetyFault("projectile spawn guard", exception);
                }
            }
            finally
            {
                Monitor.Exit(_gate);
            }
        }

        private void OnDiplomacySpawnFire(SpawnFireEventArgs e)
        {

            NoteLane(LaneNative);
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            if (!TryEnterCombatGate())
            {
                ApplyContendedCombatProtection(e);
                return;
            }
            try
            {
                if (!CombatGuardOperational())
                {
                    return;
                }
                try
                {
                    int target = WorldTileOwner(
                        e.WorldTileX,
                        e.WorldTileY);
                    bool alliedTile = NativePlayersAreAllied(
                        e.SourcePlayerId,
                        target);
                    int alliedAssetOwner = 0;
                    bool alliedAssetInSpread = false;
                    // Beide Umkreissuchen zaehlen jede lebende Einheit der
                    // Karte auf und sortieren sie - je Feuerereignis. Gibt es
                    // gar kein geschuetztes Paar (kein Buendnis, kein Pakt,
                    // keine laufende Teamaenderung, keine KI-Teams), koennen
                    // sie nichts finden; dann bleibt der Brandpfeil-Hagel
                    // einer Belagerung ohne diesen Preis.
                    if (!alliedTile && AnyProtectedPairPossible())
                    {
                        int riskRadius = FireRiskRadius(e.SpreadRadius);
                        alliedAssetInSpread =
                            TryFindAlliedUnitNearWorldTarget(
                                e.SourcePlayerId,
                                e.WorldTileX,
                                e.WorldTileY,
                                riskRadius,
                                null,
                                out alliedAssetOwner)
                            || TryFindAlliedOwnedTileNearWorldTarget(
                                e.SourcePlayerId,
                                e.WorldTileX,
                                e.WorldTileY,
                                riskRadius,
                                null,
                                out alliedAssetOwner);
                    }
                    if (alliedTile || alliedAssetInSpread)
                    {
                        e.SkipOriginalFunction = true;
                        e.ReturnValue = 0;
                        RecordBlockedCombat(
                            "spawn_fire",
                            e.SourcePlayerId,
                            alliedTile ? target : alliedAssetOwner);
                    }
#if DIPLOMACY_V2
                    else if (target > 0)
                    {
                        V2RecordUnprotectedHostileAct(
                            e.SourcePlayerId,
                            target);
                    }
                    else
                    {
                        V2AttributeHostileActNearWorldTarget(
                            e.SourcePlayerId,
                            e.WorldTileX,
                            e.WorldTileY,
                            FireRiskRadius(e.SpreadRadius));
                    }
#endif
                }
                catch (Exception exception)
                {
                    e.SkipOriginalFunction = true;
                    e.ReturnValue = 0;
                    CaptureCombatSafetyFault("fire spawn guard", exception);
                }
            }
            finally
            {
                Monitor.Exit(_gate);
            }
        }

        private void OnDiplomacyMeleeDamage(
            UnitTakeDamageByMeleeEventArgs e)
        {

            NoteLane(LaneNative);
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            // Messung (07.09.2026): ist der Stapel eines gewoehnlichen Detours
            // ebenso verschoben wie der eines Kontexthakens? Nur
            // Feldschreibvorgaenge, siehe NoteDetourLane.
            NoteDetourLane("melee_damage");
            if (!TryEnterCombatGate())
            {
                ApplyContendedCombatProtection(e);
                return;
            }
            try
            {
                if (!CombatGuardOperational())
                {
                    return;
                }
                try
                {
                    int source = UnitOwner(e.AttackingUnitId);
                    int target = UnitOwner(e.DamagedUnitId);
                    if (NativePlayersAreAllied(source, target))
                    {
                        e.SkipOriginalFunction = true;
                        e.ReturnValue = 0;
                        RecordBlockedCombat("melee_damage", source, target);
                    }
#if DIPLOMACY_V2
                    else
                    {
                        V2RecordUnprotectedHostileAct(source, target);
                    }
#endif
                }
                catch (Exception exception)
                {
                    e.SkipOriginalFunction = true;
                    e.ReturnValue = 0;
                    CaptureCombatSafetyFault("melee damage guard", exception);
                }
            }
            finally
            {
                Monitor.Exit(_gate);
            }
        }

        private void OnDiplomacyProjectileDamage(
            UnitTakeDamageByProjectileEventArgs e)
        {

            NoteLane(LaneNative);
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            if (!TryEnterCombatGate())
            {
                ApplyContendedCombatProtection(e);
                return;
            }
            try
            {
                if (!CombatGuardOperational())
                {
                    return;
                }
                try
                {
                    int source = ProjectileOwner(e.ProjectileId);
                    int target = UnitOwner(e.AttackedUnitId);
                    if (NativePlayersAreAllied(source, target))
                    {
                        e.SkipOriginalFunction = true;
                        e.ReturnValue = 0;
                        RecordBlockedCombat("projectile_damage", source, target);
                    }
#if DIPLOMACY_V2
                    else
                    {
                        V2RecordUnprotectedHostileAct(source, target);
                    }
#endif
                }
                catch (Exception exception)
                {
                    e.SkipOriginalFunction = true;
                    e.ReturnValue = 0;
                    CaptureCombatSafetyFault(
                        "projectile damage guard",
                        exception);
                }
            }
            finally
            {
                Monitor.Exit(_gate);
            }
        }


        private void OnDiplomacyBuildingDamage(
            BuildingTileTakeDamageEventArgs e)
        {


            NoteLane(LaneNative);
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            if (!TryEnterCombatGate())
            {
                ApplyContendedCombatProtection(e);
                return;
            }
            try
            {
                if (!CombatGuardOperational())
                {
                    return;
                }
                try
                {
                    int target = TileOwnerById(e.TileId);
                    if (NativePlayersAreAllied(e.PlayerIdSource, target))
                    {
                        e.Damage = 0;
                        RecordBlockedCombat(
                            "building_damage",
                            e.PlayerIdSource,
                            target);
                    }
#if DIPLOMACY_V2
                    else
                    {
                        V2RecordUnprotectedHostileAct(
                            e.PlayerIdSource,
                            target);
                    }
#endif
                }
                catch (Exception exception)
                {
                    e.Damage = 0;
                    CaptureCombatSafetyFault(
                        "building damage guard",
                        exception);
                }
            }
            finally
            {
                Monitor.Exit(_gate);
            }
        }

#if DIPLOMACY_V2
        // The original evaluator emits speech before Post. Force only a
        // willing vassal in Pre, then supply the corresponding original reply
        // outside the engine monitor after the native caller commits its order.
        private void OnDiplomacyAiDefendEvaluation(PlayerAIEvaluateDefendOrder e)
        {
            NoteLane(LaneNative);
            if (e == null) return;
            if (e.Phase == EventHookPhase.Post)
            {
                NoteV2AllyOrderDecision(true, e.TargetPlayerId, e.SourcePlayerId,
                    e.SourcePlayerId, e.ReturnValue, false);
                return;
            }
            if (e.Phase != EventHookPhase.Pre || !TryEnterCombatGate()) return;
            try
            {
                if (V2VassalOrderBias("defend", e.TargetPlayerId,
                        e.SourcePlayerId, e.SourcePlayerId, false))
                {
                    e.ReturnValue = true;
                    e.SkipOriginalFunction = true;
                    NoteV2AllyOrderDecision(true, e.TargetPlayerId, e.SourcePlayerId,
                        e.SourcePlayerId, true, true);
                }
            }
            catch (Exception exception) { V2NoteVassalOrderFault("defend", exception); }
            finally { Monitor.Exit(_gate); }
        }

#endif

        private void OnDiplomacyAiAttackEvaluation(
            PlayerAIEvaluateAttackOrder e)
        {

            NoteLane(LaneNative);
            if (e == null)
            {
                return;
            }
#if DIPLOMACY_V2
            if (e.Phase == EventHookPhase.Post)
            {
                NoteV2AllyOrderDecision(false, e.TargetPlayerId, e.SourcePlayerId,
                    e.ContextPlayerId, e.ReturnValue, false);
                return;
            }
#endif
            if (e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            if (!TryEnterCombatGate())
            {
                ApplyContendedCombatProtection(e);
#if DIPLOMACY_V2
                if (e.SkipOriginalFunction)
                    NoteV2AllyOrderDecision(false, e.TargetPlayerId, e.SourcePlayerId,
                        e.ContextPlayerId, e.ReturnValue, true);
#endif
                return;
            }
            try
            {
                if (!CombatGuardOperational())
                {
                    return;
                }
                try
                {
                    if (NativePlayersAreAllied(
                        e.TargetPlayerId,
                        e.ContextPlayerId))
                    {
#if DIPLOMACY_V2
                        NoteV2AllyOrderDecision(false, e.TargetPlayerId, e.SourcePlayerId,
                            e.ContextPlayerId, false, true);
#endif
                        e.ReturnValue = false;
                        e.SkipOriginalFunction = true;
                        RecordBlockedCombat(
                            "ai_attack_evaluation",
                            e.TargetPlayerId,
                            e.ContextPlayerId);
                        // Native 2.80 RVA D771E calls the evaluator with
                        // Target=consulted, Context=intended enemy,
                        // Source=requester; verified against SE 1.45.
                        if (_transitionBlockedCombatEvents <= 8)
                        {
                            Log(
                                "combat_guard",
                                "status=blocked_detail"
                                + "|path=ai_attack_evaluation"
                                + "|source=" + e.SourcePlayerId.ToString(
                                    CultureInfo.InvariantCulture)
                                + "|target=" + e.TargetPlayerId.ToString(
                                    CultureInfo.InvariantCulture)
                                + "|context=" + e.ContextPlayerId.ToString(
                                    CultureInfo.InvariantCulture)
                                + "|local=" + _localPlayer.ToString(
                                    CultureInfo.InvariantCulture));
                        }
                    }
#if DIPLOMACY_V2
                    else
                    {
                        try
                        {
                            if (V2VassalOrderBias("attack", e.TargetPlayerId,
                                    e.SourcePlayerId, e.ContextPlayerId, false))
                            {
                                e.ReturnValue = true;
                                e.SkipOriginalFunction = true;
                                NoteV2AllyOrderDecision(false, e.TargetPlayerId, e.SourcePlayerId,
                                    e.ContextPlayerId, true, true);
                            }
                        }
                        catch (Exception exception) { V2NoteVassalOrderFault("attack", exception); }
                    }
#endif
                }
                catch (Exception exception)
                {
                    e.ReturnValue = false;
                    e.SkipOriginalFunction = true;
                    CaptureCombatSafetyFault(
                        "AI attack evaluation guard",
                        exception);
                }
            }
            finally
            {
                Monitor.Exit(_gate);
            }
        }

        private void OnDiplomacyReceivedGoods(
            PlayerAIRequestReceivedGoodsEventArg e)
        {

            NoteLane(LaneNative);
            if (e == null || e.Phase != EventHookPhase.Post)
            {
                return;
            }
            if (!TryEnterCombatGate())
            {
                return;
            }
            try
            {
                NativeTransferProbe probe = _nativeTransferProbe;
                if (!CombatGuardOperational()
                    || probe == null
                    || e.SourcePlayerId != _localPlayer
                    || e.TargetPlayerId != probe.TargetPlayer
                    || (int)e.Good != probe.GoodId
                    || e.Amount != probe.Amount)
                {
                    return;
                }
                // The direct fallback owns both inventory writes itself. A
                // synchronous goods event in the middle of that mutation is
                // deliberately ignored; its exact two-sided readback is
                // verified from the subsequent tick/frame lane.
                if (probe.DirectAtomicTransfer)
                {
                    return;
                }
                probe.CompletionObserved = true;
                probe.CompletionReturnHint = e.ReturnValue;
                probe.StartedTick = checked(
                    ReadSimulationTick() - NativeTransferVerificationTicks);
                try
                {
                    int senderAfter;
                    int recipientAfter;
                    if (!TryReadTransferAmount(
                            _localPlayer,
                            probe.GoodId,
                            out senderAfter)
                        || !TryReadTransferAmount(
                            probe.TargetPlayer,
                            probe.GoodId,
                            out recipientAfter))
                    {
                        return;
                    }
                    probe.CompletionSenderAmount = senderAfter;
                    probe.CompletionRecipientAmount = recipientAfter;
                    probe.CompletionPostInventoryExact =
                        DiplomacyTransferReceipt.IsSenderDebitConfirmed(
                            probe.SenderBefore,
                            probe.RecipientBefore,
                            probe.Amount,
                            senderAfter,
                            recipientAfter);
                    if (probe.CompletionPostInventoryExact)
                    {
                        // SHCDESE 1.44 maps only native return value 1 to
                        // success. SHC:DE 2.80 returns another value after an
                        // exact transfer, so repair the mutable Post result for
                        // the native caller only after the inventory receipt
                        // has independently proved completion.
                        e.ReturnValue = true;
                    }
                }
                catch (Exception exception)
                {
                    // Never throw through the Script Extender's native event
                    // frame. The normal verification lane will safely abort
                    // an observation whose synchronous inventory proof is
                    // missing.
                    Log(
                        "transfer",
                        "status=native_post_read_failed|reason="
                        + exception.GetType().Name);
                }
            }
            finally
            {
                Monitor.Exit(_gate);
            }
        }

        private static bool IsAttackCommand(TribeAICommand command)
        {
            switch (command)
            {
                case TribeAICommand.AttackUnit:
                case TribeAICommand.AttackTilePosition:
                case TribeAICommand.AttackBuilding:
                case TribeAICommand.ThrowLava:
                case TribeAICommand.BuildTunnel:
                case TribeAICommand.AttackWallTileId:
                case TribeAICommand.AttachLadderToWall:
                case TribeAICommand.Unknown33:
                case TribeAICommand.ForceAttackBuilding:
                    return true;
                default:
                    return false;
            }
        }

        private bool TryAttackOrderTargetOwner(
            TribeIssueOrderWithTargetEventArgs e,
            out int owner)
        {
            owner = 0;
            switch (e.AICommand)
            {
                case TribeAICommand.AttackUnit:
                case TribeAICommand.Unknown33:
                    owner = UnitOwner(e.TargetValue1);
                    break;
                case TribeAICommand.AttackBuilding:
                case TribeAICommand.BuildTunnel:
                case TribeAICommand.ForceAttackBuilding:
                    owner = BuildingOwner(e.TargetValue1);
                    break;
                case TribeAICommand.AttackWallTileId:
                case TribeAICommand.AttachLadderToWall:
                    owner = TileOwnerById(e.TargetValue1);
                    break;
                case TribeAICommand.AttackTilePosition:
                case TribeAICommand.ThrowLava:
                    owner = TileOwner(e.TargetValue1, e.TargetValue2);
                    break;
            }
            return owner > 0;
        }

        private int ProjectileEventSourceOwner(ProjectileSpawnEventArgs e)
        {
            int owner = e.PlayerSourceId;
            if (!_roster.Contains(owner))
            {
                owner = e.UnitPlayerSourceId;
            }
            if (!_roster.Contains(owner) && e.SourceUnitId > 0)
            {
                owner = UnitOwner(e.SourceUnitId);
            }
            return owner;
        }

        private int UnitOwner(int unitId)
        {
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            if (units == null || !units.IsValidId(unitId))
            {
                return 0;
            }
            int owner = units.GetOwner(unitId);
            return owner > 0 && owner <= 8 ? owner : 0;
        }

        private int BuildingOwner(int buildingId)
        {
            GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
            if (buildings == null || !buildings.IsValidId(buildingId))
            {
                return 0;
            }
            int owner = buildings.GetOwner(buildingId);
            return owner > 0 && owner <= 8 ? owner : 0;
        }

        private unsafe int TribeOwner(int tribeId)
        {
            GameTribeManagerAPI tribes = GameTribeManagerAPI.Instance;
            GameTribe* tribe;
            if (tribes == null
                || !tribes.IsValidId(tribeId)
                || !tribes.TryGetTribeById(tribeId, out tribe)
                || tribe == null
                || tribe->r_AliveState != AliveState.IsAlive)
            {
                return 0;
            }
            int owner = tribe->r_PlayerIdOwner;
            return owner > 0 && owner <= 8 ? owner : 0;
        }

        private unsafe int ProjectileOwner(int projectileId,
            CombatProtectionSnapshot snapshot = null)
        {
            GameProjectileManagerAPI projectiles =
                GameProjectileManagerAPI.Instance;
            GameProjectile* projectile;
            if (projectiles == null
                || !projectiles.IsValidId(projectileId)
                || !projectiles.TryGetProjectileById(projectileId, out projectile)
                || projectile == null)
            {
                return 0;
            }
            int owner = (int)projectile->r_PlayerSourceId;
            if (!(snapshot == null ? _roster.Contains(owner) : snapshot.Contains(owner))
                && projectile->r_SourceUnitId > 0)
            {
                owner = UnitOwner(projectile->r_SourceUnitId);
            }
            return owner;
        }

        private int TileOwner(int tileX, int tileY)
        {
            if (!GameTileManagerAPI.Instance.IsTileInsideMapBounds(tileX, tileY))
            {
                return 0;
            }
            return TileOwnerById(
                GameTileManagerAPI.Instance.GetTileId(tileX, tileY));
        }

        private int WorldTileOwner(int worldTileX, int worldTileY)
        {
            int worldLimit = checked(
                GameTileManagerAPI.MAX_WIDTH * WorldPositionsPerLocalTile);
            if (worldTileX < 0 || worldTileX >= worldLimit
                || worldTileY < 0 || worldTileY >= worldLimit)
            {
                return 0;
            }
            return TileOwner(
                worldTileX / WorldPositionsPerLocalTile,
                worldTileY / WorldPositionsPerLocalTile);
        }

        private int TileOwnerById(int tileId)
        {
            GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
            if (tileId < 0 || !tiles.IsValidTileId(tileId))
            {
                return 0;
            }
            int owner = tiles.GetTilePlayerOwnerId(tileId);
            if (owner <= 0)
            {
                int buildingId = tiles.GetTileBuildingId(tileId);
                if (buildingId > 0)
                {
                    owner = BuildingOwner(buildingId);
                }
            }
            return owner > 0 && owner <= 8 ? owner : 0;
        }

        private static int FireRiskRadius(int spreadRadius)
        {
            long radius = Math.Max(0, (long)spreadRadius)
                + FireUnitFootprintPaddingWorld;
            long worldLimit = checked(
                (long)GameTileManagerAPI.MAX_WIDTH * WorldPositionsPerLocalTile);
            return (int)Math.Min(radius, worldLimit);
        }

        private bool TryFindAlliedUnitNearWorldTarget(
            int sourcePlayer,
            int worldTileX,
            int worldTileY,
            int riskRadius,
            IDictionary<int, int> targetPartition,
            out int alliedUnitOwner)
        {
            alliedUnitOwner = 0;
            int worldLimit = checked(
                GameTileManagerAPI.MAX_WIDTH * WorldPositionsPerLocalTile);
            if (!_roster.Contains(sourcePlayer)
                || worldTileX < 0
                || worldTileX >= worldLimit
                || worldTileY < 0
                || worldTileY >= worldLimit)
            {
                return false;
            }

            int boundedRadius = Math.Max(
                0,
                Math.Min(riskRadius, worldLimit));
            long squaredRadius = (long)boundedRadius * boundedRadius;
            var unitIds = new List<int>();
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            units.GetAllUnits(unitIds, AliveState.IsAlive);
            unitIds.Sort();
            foreach (int unitId in unitIds)
            {
                int owner = UnitOwner(unitId);
                bool allied = targetPartition == null
                    ? NativePlayersAreAllied(sourcePlayer, owner)
                    : PartitionAllies(
                        targetPartition,
                        sourcePlayer,
                        owner);
                if (!allied)
                {
                    continue;
                }

                UnmanagedVector2<ushort> position =
                    units.GetCurrentWorldTilePosition(unitId);
                long deltaX = (long)position.X - worldTileX;
                long deltaY = (long)position.Y - worldTileY;
                if (deltaX * deltaX + deltaY * deltaY
                    > squaredRadius)
                {
                    continue;
                }
                alliedUnitOwner = owner;
                return true;
            }
            return false;
        }

        private bool TryFindAlliedOwnedTileNearWorldTarget(
            int sourcePlayer,
            int worldTileX,
            int worldTileY,
            int riskRadius,
            IDictionary<int, int> targetPartition,
            out int alliedTileOwner)
        {
            alliedTileOwner = 0;
            int worldLimit = checked(
                GameTileManagerAPI.MAX_WIDTH * WorldPositionsPerLocalTile);
            if (!_roster.Contains(sourcePlayer)
                || worldTileX < 0
                || worldTileX >= worldLimit
                || worldTileY < 0
                || worldTileY >= worldLimit)
            {
                return false;
            }

            int boundedRadius = Math.Max(
                0,
                Math.Min(riskRadius, worldLimit));
            long squaredRadius = (long)boundedRadius * boundedRadius;
            int minimumTileX = Math.Max(
                0,
                worldTileX - boundedRadius) / WorldPositionsPerLocalTile;
            int maximumTileX = Math.Min(
                worldLimit - 1,
                worldTileX + boundedRadius) / WorldPositionsPerLocalTile;
            int minimumTileY = Math.Max(
                0,
                worldTileY - boundedRadius) / WorldPositionsPerLocalTile;
            int maximumTileY = Math.Min(
                worldLimit - 1,
                worldTileY + boundedRadius) / WorldPositionsPerLocalTile;
            for (int tileY = minimumTileY; tileY <= maximumTileY; tileY++)
            {
                for (int tileX = minimumTileX; tileX <= maximumTileX; tileX++)
                {
                    int owner = TileOwner(tileX, tileY);
                    bool allied = targetPartition == null
                        ? NativePlayersAreAllied(sourcePlayer, owner)
                        : PartitionAllies(
                            targetPartition,
                            sourcePlayer,
                            owner);
                    if (!allied)
                    {
                        continue;
                    }

                    long tileMinimumWorldX =
                        (long)tileX * WorldPositionsPerLocalTile;
                    long tileMaximumWorldX = tileMinimumWorldX
                        + WorldPositionsPerLocalTile - 1;
                    long tileMinimumWorldY =
                        (long)tileY * WorldPositionsPerLocalTile;
                    long tileMaximumWorldY = tileMinimumWorldY
                        + WorldPositionsPerLocalTile - 1;
                    long deltaX = worldTileX < tileMinimumWorldX
                        ? tileMinimumWorldX - worldTileX
                        : worldTileX > tileMaximumWorldX
                            ? worldTileX - tileMaximumWorldX
                            : 0L;
                    long deltaY = worldTileY < tileMinimumWorldY
                        ? tileMinimumWorldY - worldTileY
                        : worldTileY > tileMaximumWorldY
                            ? worldTileY - tileMaximumWorldY
                            : 0L;
                    if (deltaX * deltaX + deltaY * deltaY
                        > squaredRadius)
                    {
                        continue;
                    }
                    alliedTileOwner = owner;
                    return true;
                }
            }
            return false;
        }

        private static bool IsGroundFireProjectile(
            ProjectileType projectileType)
        {
            switch (projectileType)
            {
                case ProjectileType.EngineerLava:
                case ProjectileType.StaticFire:
                case ProjectileType.RockChipsFire1:
                case ProjectileType.GrenadierGrenade:
                    return true;
                default:
                    return false;
            }
        }

        private unsafe int QuarantineAlliedTribes(
            IDictionary<int, int> targetPartition)
        {
            RequireNativeDiplomacySection();
            var tribeIds = new List<int>();
            GameTribeManagerAPI tribes = GameTribeManagerAPI.Instance;
            tribes.GetAllTribes(tribeIds, AliveState.IsAlive);
            int stopped = 0;
            foreach (int tribeId in tribeIds)
            {
                GameTribe* tribe;
                if (!tribes.TryGetTribeById(tribeId, out tribe)
                    || tribe == null)
                {
                    continue;
                }
                int source = tribe->r_PlayerIdOwner;
                uint globalId = tribe->r_GlobalId;
                int target = tribe->r_AttackTargetOwnerPlayerId > 0
                    ? (int)tribe->r_AttackTargetOwnerPlayerId
                    : UnitOwner(tribe->r_AttackTargetUnitId);
                if (!PartitionAllies(targetPartition, source, target))
                {
                    continue;
                }
                if (!tribes.Stop(tribeId))
                {
                    GameTribe* current;
                    if (!tribes.TryGetTribeById(tribeId, out current) || current == null
                        || !NativeDiplomacyIdentityMatches(source, globalId,
                            current->r_PlayerIdOwner, current->r_GlobalId))
                        continue;
                    throw new InvalidOperationException(
                        "failed to stop allied tribe "
                        + tribeId.ToString(CultureInfo.InvariantCulture));
                }
                stopped++;
            }
            return stopped;
        }

        private unsafe int QuarantineAlliedProjectiles(
            IDictionary<int, int> targetPartition)
        {
            RequireNativeDiplomacySection();
            var projectileIds = new List<int>();
            GameProjectileManagerAPI projectiles =
                GameProjectileManagerAPI.Instance;
            projectiles.GetAllProjectiles(
                projectileIds,
                AliveState.IsAlive);
            int deleted = 0;
            foreach (int projectileId in projectileIds)
            {
                GameProjectile* projectile;
                if (!projectiles.TryGetProjectileById(
                        projectileId,
                        out projectile)
                    || projectile == null)
                {
                    continue;
                }
                int source = (int)projectile->r_PlayerSourceId;
                uint globalId = projectile->r_GlobalId;
                if (!_roster.Contains(source)
                    && projectile->r_SourceUnitId > 0)
                {
                    source = UnitOwner(projectile->r_SourceUnitId);
                }
                int target = projectile->r_TargetUnidId > 0
                    ? UnitOwner(projectile->r_TargetUnidId)
                    : WorldTileOwner(
                        projectile->r_TargetWorldTileX,
                        projectile->r_TargetWorldTileY);
                int alliedAssetOwner = 0;
                bool alliedGroundTarget = false;
                if (projectile->r_TargetUnidId == 0
                    && IsGroundFireProjectile(
                        projectile->r_ProjectileType))
                {
                    alliedGroundTarget =
                        TryFindAlliedUnitNearWorldTarget(
                            source,
                            projectile->r_TargetWorldTileX,
                            projectile->r_TargetWorldTileY,
                            GroundFireProjectileRiskRadiusWorld,
                            targetPartition,
                            out alliedAssetOwner)
                        || TryFindAlliedOwnedTileNearWorldTarget(
                            source,
                            projectile->r_TargetWorldTileX,
                            projectile->r_TargetWorldTileY,
                            GroundFireProjectileRiskRadiusWorld,
                            targetPartition,
                            out alliedAssetOwner);
                }
                if (!PartitionAllies(targetPartition, source, target)
                    && !alliedGroundTarget)
                {
                    continue;
                }
                if (!projectiles.DeleteProjectileSafe(projectileId))
                {
                    GameProjectile* current;
                    if (!projectiles.TryGetProjectileById(projectileId, out current)
                        || current == null || current->r_GlobalId != globalId)
                        continue;
                    throw new InvalidOperationException(
                        "failed to delete allied projectile "
                        + projectileId.ToString(CultureInfo.InvariantCulture));
                }
                deleted++;
            }
            return deleted;
        }

        private unsafe int QuarantineAlliedBuildingFires(
            IDictionary<int, int> targetPartition)
        {
            RequireNativeDiplomacySection();
            var buildingIds = new List<int>();
            GameBuildingManagerAPI buildings =
                GameBuildingManagerAPI.Instance;
            buildings.GetAllBuildings(buildingIds, AliveState.IsAlive);
            buildingIds.Sort();
            int cleared = 0;
            foreach (int buildingId in buildingIds)
            {
                GameBuilding* building;
                if (!buildings.TryGetBuildingById(
                        buildingId,
                        out building)
                    || building == null
                    || building->r_OnFireTicks == 0)
                {
                    continue;
                }
                int source = building->r_CausedFireByPlayer;
                int target = building->r_PlayerIdOwner;
                uint globalId = building->r_GlobalId;
                if (!PartitionAllies(
                    targetPartition,
                    source,
                    target))
                {
                    continue;
                }

                buildings.SetOnFireTicks(buildingId, 0);
                GameBuilding* readback;
                if (!buildings.TryGetBuildingById(
                        buildingId,
                        out readback)
                    || readback == null
                    || !NativeDiplomacyIdentityMatches(target, globalId,
                        readback->r_PlayerIdOwner, readback->r_GlobalId))
                {
                    // A synchronous hook may remove the object. Its old slot
                    // no longer owns a fire that this quarantine must clear.
                    continue;
                }
                if (readback->r_OnFireTicks != 0
                    || buildings.GetOnFireTicks(buildingId) != 0)
                {
                    throw new InvalidOperationException(
                        "failed to extinguish allied-caused building fire "
                        + buildingId.ToString(
                            CultureInfo.InvariantCulture));
                }
                cleared++;
            }
            return cleared;
        }

        private unsafe int QuarantineAlliedAiTargets(
            IDictionary<int, int> targetPartition)
        {
            RequireNativeDiplomacySection();
            int cleared = 0;
            foreach (int sourcePlayer in _roster)
            {
                if (sourcePlayer == _localPlayer
                    || !IsAlivePlayer(sourcePlayer)
                    || !GameData.Instance.lastGameState.is_skirmish_player(
                        sourcePlayer))
                {
                    continue;
                }
                GamePlayerResources* resources;
                if (!GamePlayerManagerAPI.Instance
                    .TryGetPlayerResourcesById(
                        sourcePlayer,
                        out resources)
                    || resources == null)
                {
                    throw new InvalidOperationException(
                        "AI diplomacy target resources are unavailable for player "
                        + sourcePlayer.ToString(CultureInfo.InvariantCulture));
                }
                uint rawTarget = SeInteropFieldAliases.SiegeTarget(resources);
                if (rawTarget < 1 || rawTarget > 8
                    || !PartitionAllies(
                        targetPartition,
                        sourcePlayer,
                        (int)rawTarget))
                {
                    continue;
                }
                SeInteropFieldAliases.SiegeTarget(resources) = 0;
                if (SeInteropFieldAliases.SiegeTarget(resources) != 0)
                {
                    throw new InvalidOperationException(
                        "AI diplomacy target clear was rejected for player "
                        + sourcePlayer.ToString(CultureInfo.InvariantCulture));
                }
                cleared++;
            }
            return cleared;
        }

        private static DiplomacyPendingTeamTransition
            CopyPendingTeamTransition(
                DiplomacyPendingTeamTransition source)
        {
            if (source == null)
            {
                return null;
            }
            return new DiplomacyPendingTeamTransition
            {
                Kind = source.Kind,
                CoalitionId = source.CoalitionId,
                GameDay = source.GameDay,
                Reason = source.Reason,
                ExpectedPartition = new Dictionary<int, int>(
                    source.ExpectedPartition),
                TargetPartition = new Dictionary<int, int>(
                    source.TargetPartition),
            };
        }

        private void ResetCombatSafetyMapState(
            bool preserveRollbackGuard = false)
        {
#if DIPLOMACY_V2
            ClearV2AllyOrders();
            ClearV2HumanOrders();
            ClearV2CastleBoundaries();
            ResetV2VassalGoodsRequests();
            // Reset discards the native operation below. Retaining its accepted
            // quote would orphan consent and make the next recovery save fail.
            foreach (RelationState relation in _relations.Values)
                DiplomacyV2Submission.CancelAcceptedTeamTransition(
                    relation.V2, _lastProcessedDay);
#endif
            _pendingTeamTransition = null;
            _pendingTransitionGeneration = 0;
            _pendingTransitionFingerprint = null;
            _transitionGuardPartition = null;
            _transitionVerificationPartition = null;
            _transitionVerificationStartedTick = 0;
            _transitionBlockedCombatEvents = 0;
            _combatSafetyFault = null;
            if (!preserveRollbackGuard)
            {
                _rollbackGuardActive = false;
                _rollbackGuardBeforePartition = null;
                _rollbackGuardAfterPartition = null;
            }
            if (preserveRollbackGuard)
                PublishCombatProtectionSnapshot();
            else
                Volatile.Write(ref _combatProtectionSnapshot,
                    CombatProtectionSnapshot.Empty);
        }
        // No native/API dependencies: exercised as the actual production type
        // by the two-thread stress harness. Arrays are cloned and never exposed.
        internal sealed class CombatProtectionSnapshot
        {
            internal static readonly CombatProtectionSnapshot Empty =
                new CombatProtectionSnapshot(0, 0, new int[9]);
            private readonly int[] _rows;
            internal readonly long Session;
            private readonly int _members;

            internal CombatProtectionSnapshot(long session, int members, int[] rows)
            {
                Session = session;
                _members = members & 0x1FE;
                _rows = new int[9];
                if (rows != null)
                    Array.Copy(rows, _rows, Math.Min(rows.Length, _rows.Length));
            }

            internal bool Contains(int player)
            {
                return player >= 1 && player <= 8
                    && (_members & (1 << player)) != 0;
            }

            internal bool Protects(int first, int second)
            {
                return first != second && Contains(first) && Contains(second)
                    && (_rows[first] & (1 << second)) != 0;
            }

            internal bool HasProtectionFor(int player)
            {
                return Contains(player) && (_rows[player] & _members) != 0;
            }

            internal bool AnyProtection
            {
                get
                {
                    for (int player = 1; player <= 8; player++)
                        if (HasProtectionFor(player)) return true;
                    return false;
                }
            }
        }
    }
}
