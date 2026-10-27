#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;
using CrusaderDE;
using HarmonyLib;
using SHCDESE.API;
using SHCDESE.EventAPI.Tribes;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        private sealed class V2TreatyIntentTarget
        {
            internal readonly string CoalitionId;
            internal readonly DiplomacyV2AgreementKind Agreement;
            internal readonly int UntilDay, BrokenAgreements, ManualTreatyEnds;
            internal readonly long Generation, Epoch;
            internal readonly int Local;
            internal V2TreatyIntentTarget(RelationState relation, long generation, long epoch, int local)
            {
                CoalitionId = relation.CoalitionId;
                Agreement = relation.V2.Agreement; UntilDay = relation.V2.AgreementUntilDay;
                BrokenAgreements = relation.V2.BrokenAgreements; ManualTreatyEnds = relation.V2.ManualTreatyEnds;
                Generation = generation; Epoch = epoch; Local = local;
            }
            internal bool Matches(RelationState relation)
            {
                // A failed goods ledger restores deep relation copies. Object
                // identity is therefore not the identity of this agreement.
                return relation != null && relation.CoalitionId == CoalitionId && relation.V2 != null
                    && relation.V2.Agreement == Agreement && relation.V2.AgreementUntilDay == UntilDay
                    && relation.V2.BrokenAgreements == BrokenAgreements
                    && relation.V2.ManualTreatyEnds == ManualTreatyEnds;
            }
        }
        private sealed class V2HumanWarIntent
        {
            internal V2TreatyIntentTarget Treaty;
            internal int TargetPlayer, UnitId, BuildingId, TileId, X, Y;
            internal uint TargetGlobalId;
            internal readonly Dictionary<int, uint> SelectedTribes = new Dictionary<int, uint>();
        }
        private sealed class V2HumanCommandFrame
        {
            internal int[] UnderCursor;
            internal V2HumanWarIntent Intent;
            internal readonly HashSet<int> AllowedTribes = new HashSet<int>();
        }
        private V2TreatyIntentTarget[] _v2TreatyIntentTargets = new V2TreatyIntentTarget[9];
        private readonly V2HumanWarIntent[] _v2HumanWarIntents = new V2HumanWarIntent[9];
        [ThreadStatic] private static V2HumanCommandFrame _v2HumanCommandFrame;
        private MethodInfo _v2TroopSelectionTarget, _v2PreDllActionsTarget, _v2RunTarget;

        private bool PrepareV2HumanOrders(out string failure)
        {
            _v2TroopSelectionTarget = typeof(EngineInterface).GetMethod("TroopSelection",
                BindingFlags.Public | BindingFlags.Static, null,
                new[] { typeof(int), typeof(bool), typeof(bool), typeof(int[]), typeof(bool),
                    typeof(bool), typeof(int[]), typeof(int), typeof(int), typeof(bool), typeof(int[]) }, null);
            _v2PreDllActionsTarget = typeof(EditorDirector).GetMethod("preDLLCallActions",
                BindingFlags.Public | BindingFlags.Instance, null,
                new[] { typeof(int).MakeByRefType(), typeof(int).MakeByRefType() }, null);
            _v2RunTarget = typeof(EngineInterface).GetMethod("run",
                BindingFlags.Public | BindingFlags.Static, null, new[] { typeof(bool) }, null);
            failure = _v2TroopSelectionTarget != null && _v2TroopSelectionTarget.ReturnType == typeof(void)
                && _v2PreDllActionsTarget != null && _v2PreDllActionsTarget.ReturnType == typeof(void)
                && _v2RunTarget != null && _v2RunTarget.ReturnType == typeof(int)
                ? null : "pinned managed human-order signatures are unavailable";
            return failure == null;
        }

        private void ApplyV2HumanOrders()
        {
            BindingFlags flags = BindingFlags.NonPublic | BindingFlags.Static;
            _harmony.Patch(_v2TroopSelectionTarget, prefix: new HarmonyMethod(
                typeof(DiplomacyFeature).GetMethod("V2TroopSelectionPrefix", flags)));
            _harmony.Patch(_v2PreDllActionsTarget, postfix: new HarmonyMethod(
                typeof(DiplomacyFeature).GetMethod("V2PreDllActionsPostfix", flags)));
            _harmony.Patch(_v2RunTarget, prefix: new HarmonyMethod(
                typeof(DiplomacyFeature).GetMethod("V2RunBegin", flags)), finalizer: new HarmonyMethod(
                typeof(DiplomacyFeature).GetMethod("V2RunEnd", flags)));
        }

        private void RollbackV2HumanOrders()
        {
            // Unpatch by our owner even if a later patch failed during Apply.
            if (_v2TroopSelectionTarget != null) _harmony.Unpatch(_v2TroopSelectionTarget, HarmonyPatchType.Prefix, _harmony.Id);
            if (_v2PreDllActionsTarget != null) _harmony.Unpatch(_v2PreDllActionsTarget, HarmonyPatchType.Postfix, _harmony.Id);
            if (_v2RunTarget != null)
            {
                _harmony.Unpatch(_v2RunTarget, HarmonyPatchType.Prefix, _harmony.Id);
                _harmony.Unpatch(_v2RunTarget, HarmonyPatchType.Finalizer, _harmony.Id);
            }
            ClearV2HumanOrders();
        }

        private void ClearV2HumanOrders()
        {
            Volatile.Write(ref _v2TreatyIntentTargets, new V2TreatyIntentTarget[9]);
            for (int player = 1; player <= 8; player++) Interlocked.Exchange(ref _v2HumanWarIntents[player], null);
            _v2HumanCommandFrame = null;
        }

        private void PublishV2TreatyIntentSnapshot()
        {
            var targets = new V2TreatyIntentTarget[9];
            if (_mapActive && !_mapDisabled)
                foreach (KeyValuePair<int, string> pair in _playerCoalition)
                {
                    RelationState relation;
                    if (pair.Key >= 1 && pair.Key <= 8 && _relations.TryGetValue(pair.Value, out relation)
                        && relation.V2 != null && DiplomacyV2CombatRules.TreatyProtects(relation.Allied,
                            relation.V2.Agreement, relation.V2.AgreementUntilDay, Math.Max(0, _lastProcessedDay)))
                        targets[pair.Key] = new V2TreatyIntentTarget(relation, _sessionGeneration, _mapEpoch, _localPlayer);
                }
            Volatile.Write(ref _v2TreatyIntentTargets, targets);
        }

        private static void V2RunBegin() { _v2HumanCommandFrame = null; }
        private static Exception V2RunEnd(Exception __exception)
        { _v2HumanCommandFrame = null; return __exception; }

        private static void V2TroopSelectionPrefix(int __0, bool __2, bool __4,
            bool __5, int[] __6)
        {
            _v2HumanCommandFrame = null;
            // COPY native 8F596..8F5AE: SH1 mode consumes left-up (3),
            // DE mode consumes right-up. A selection rectangle is not attack.
            if ((ConfigSettings.Settings_SH1RTSControls ? __0 != 3 : !__2) || __4 || __5) return;
            DiplomacyFeature owner = Volatile.Read(ref _activeOwner);
            if (owner == null || !Volatile.Read(ref owner._mapActive) || Volatile.Read(ref owner._mapDisabled)) return;
            owner.NoteLane(LaneInput);
            _v2HumanCommandFrame = new V2HumanCommandFrame
            { UnderCursor = __6 == null ? new int[0] : (int[])__6.Clone() };
        }

        private static void V2PreDllActionsPostfix(ref int __0, ref int __1)
        {
            V2HumanCommandFrame frame = _v2HumanCommandFrame;
            if (frame == null) return;
            DiplomacyFeature owner = Volatile.Read(ref _activeOwner);
            if (owner == null || !IsNativeDiplomacySectionHeld) return;
            owner.NoteLane(LaneInput);
            try { owner.CaptureV2HumanWarIntent(frame, __0, __1); }
            catch { _v2HumanCommandFrame = null; } // Never throw through the engine frame.
        }

        private unsafe void CaptureV2HumanWarIntent(V2HumanCommandFrame frame, int x, int y)
        {
            GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
            if (!tiles.IsTileInsideMapBounds(x, y)) return;
            V2TreatyIntentTarget[] targets = Volatile.Read(ref _v2TreatyIntentTargets);
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            int owner = 0, unitId = 0, buildingId = 0;
            uint globalId = 0;
            // Vanilla sorted these exact IDs by cursor depth (GameMap4048..4136).
            foreach (int candidate in frame.UnderCursor)
            {
                GameUnit* unit;
                if (!units.IsValidId(candidate) || !units.TryGetUnitById(candidate, out unit)
                    || unit == null || unit->r_AliveState != AliveState.IsAlive) continue;
                owner = units.GetOwner(candidate); unitId = candidate; globalId = unit->r_GlobalId;
                break;
            }
            int tileId = tiles.GetTileId(x, y);
            if (!tiles.IsValidTileId(tileId)) return;
            if (unitId == 0)
            {
                buildingId = tiles.GetTileBuildingId(tileId);
                GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                GameBuilding* building;
                if (buildingId > 0 && buildings.IsValidId(buildingId)
                    && buildings.TryGetBuildingById(buildingId, out building) && building != null
                    && building->r_AliveState == AliveState.IsAlive)
                { owner = building->r_PlayerIdOwner; globalId = building->r_GlobalId; }
                else if ((tiles.GetTilePropertyFlag(tileId) & TilePropertyFlag.IsWall) != 0)
                { buildingId = 0; owner = tiles.GetTilePlayerOwnerId(tileId); }
            }
            if (owner < 1 || owner > 8 || targets[owner] == null) return;
            V2TreatyIntentTarget treaty = targets[owner];
            var intent = new V2HumanWarIntent
            { Treaty = treaty, TargetPlayer = owner, UnitId = unitId, BuildingId = buildingId,
                TargetGlobalId = globalId, TileId = tileId, X = x, Y = y };
            // SE 2.9.0 renamed the UInt16 selection-owner field at 0xAE.
            bool selected = false;
            GameTribeManagerAPI tribes = GameTribeManagerAPI.Instance;
            foreach (int id in units.GetAllAliveUnits())
            {
                GameUnit* unit;
                if (!units.IsValidId(id) || !units.TryGetUnitById(id, out unit) || unit == null
                    || unit->r_AliveState != AliveState.IsAlive || units.GetOwner(id) != treaty.Local
                    || unit->r_ControllableForPlayerId != treaty.Local || unit->r_UnitSelected != treaty.Local
                    || !IsCombatUnit(units.GetType(id))) continue;
                selected = true;
                int tribeId = unit->r_TribeId;
                GameTribe* tribe;
                if (tribeId > 0 && tribes.IsValidId(tribeId) && tribes.TryGetTribeById(tribeId, out tribe)
                    && tribe != null && tribe->r_PlayerIdOwner == treaty.Local)
                    intent.SelectedTribes[tribeId] = tribe->r_GlobalId;
            }
            if (!selected) return;
            frame.Intent = intent;
            Interlocked.Exchange(ref _v2HumanWarIntents[owner], intent);
            // Most commands commit before RunTick. Under contention only this
            // captured native command is allowed; the managed event is drained
            // by Frame or Save before taking the persistent model snapshot.
            if (!Monitor.TryEnter(_gate)) return;
            try { PumpV2HumanWarIntents(); }
            finally { Monitor.Exit(_gate); }
        }

        private void PumpV2HumanWarIntents(bool publishProtection = true)
        {
            bool changed = false;
            for (int player = 1; player <= 8; player++)
            {
                V2HumanWarIntent intent = Interlocked.Exchange(ref _v2HumanWarIntents[player], null);
                if (intent == null) continue;
                V2TreatyIntentTarget treaty = intent.Treaty;
                string coalitionId;
                RelationState relation;
                if (!_mapActive || _mapDisabled || treaty.Generation != _sessionGeneration || treaty.Epoch != _mapEpoch
                    || treaty.Local != _localPlayer || !_playerCoalition.TryGetValue(player, out coalitionId)
                    || coalitionId != treaty.CoalitionId || !_relations.TryGetValue(coalitionId, out relation)
                    || !treaty.Matches(relation)
                    || relation.V2 == null || !DiplomacyV2CombatRules.TreatyProtects(relation.Allied,
                        relation.V2.Agreement, relation.V2.AgreementUntilDay, Math.Max(0, _lastProcessedDay))) continue;
                DiplomacyV2StateMachine.BreakAgreementByPlayer(relation, Math.Max(0, _lastProcessedDay),
                    _coalitions[coalitionId].Target, DiplomacyV2BreachKind.TreacherousAttack, _rules);
                _v2PendingAgreementSafety.Remove(coalitionId);
                QueueV2BreachNotice(coalitionId, player, "command=human_release|target_player=" + player);
                changed = true;
            }
            if (changed && publishProtection) PublishCombatProtectionSnapshot();
        }

        private unsafe bool AllowV2CapturedHumanTribeOrder(TribeIssueOrderWithTargetEventArgs e)
        {
            V2HumanCommandFrame frame = _v2HumanCommandFrame;
            V2HumanWarIntent intent = frame == null ? null : frame.Intent;
            if (intent == null || intent.Treaty.Generation != Volatile.Read(ref _sessionGeneration)
                || intent.Treaty.Epoch != Volatile.Read(ref _mapEpoch) || Volatile.Read(ref _mapDisabled)
                || !Volatile.Read(ref _mapActive) || intent.Treaty.Local != Volatile.Read(ref _localPlayer)
                || !IsNativeDiplomacySectionHeld || frame.AllowedTribes.Contains(e.TribeId)) return false;
            uint expected;
            GameTribe* tribe;
            if (!intent.SelectedTribes.TryGetValue(e.TribeId, out expected)
                || !GameTribeManagerAPI.Instance.TryGetTribeById(e.TribeId, out tribe) || tribe == null
                || tribe->r_GlobalId != expected || tribe->r_PlayerIdOwner != intent.Treaty.Local) return false;
            bool matches = intent.UnitId > 0
                ? e.AICommand == TribeAICommand.AttackUnit && e.TargetValue1 == intent.UnitId
                    && unchecked((uint)e.TargetValue2) == intent.TargetGlobalId
                : intent.BuildingId > 0
                    ? (e.AICommand == TribeAICommand.AttackBuilding || e.AICommand == TribeAICommand.ForceAttackBuilding
                        || e.AICommand == TribeAICommand.BuildTunnel) && e.TargetValue1 == intent.BuildingId
                        && unchecked((uint)e.TargetValue2) == intent.TargetGlobalId
                    : (e.AICommand == TribeAICommand.AttackWallTileId || e.AICommand == TribeAICommand.AttachLadderToWall)
                        && e.TargetValue1 == intent.TileId;
            matches |= (e.AICommand == TribeAICommand.AttackTilePosition || e.AICommand == TribeAICommand.ThrowLava)
                && e.TargetValue1 == intent.X && e.TargetValue2 == intent.Y;
            if (!matches) return false;
            frame.AllowedTribes.Add(e.TribeId);
            return true;
        }
    }
}
#endif
