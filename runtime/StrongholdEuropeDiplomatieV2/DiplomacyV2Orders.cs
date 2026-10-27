#if DIPLOMACY_V2
using System;
using System.Globalization;
using System.Reflection;
using System.Threading;
using CrusaderDE;
using HarmonyLib;
using SHCDESE.API;
using SHCDESE.Interop;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        // The original HUD calls this exact four-argument GameAction overload.
        // Preserve its actual opcode (Attack0..5 is 1..6, Defend is 11), not a
        // reconstructed enemy-list index. One latest order per lord matches
        // Vanilla's single current order and bounds pending input to eight.
        private sealed class V2AllyOrder
        {
            internal int Opcode, Consulted, Target, Requester;
            internal long Generation, Epoch;
            internal bool? Accepted;
            internal bool SupplyVoice;
            internal int LordId;
            internal int RequestedDay, DispatchedDay = -1;
            internal int ResponseDaysRemaining = 3, LastVisibleDay = -1;
            internal bool ObservedActive;
            internal int EndedDay = -1;
            internal long DispatchedTick, ReplySequence;
            internal bool NativeDecision;
        }

        // A timeout ends waiting, never invents a native answer. SE 1.45 exposes
        // no packet id in either evaluator event; replies below describe the
        // actual native decision, not a guessed acknowledgement of this input.
        private const long V2AllyReplyWaitTicks = 256;
        private readonly V2AllyOrder[] _v2AllyOrders = new V2AllyOrder[9];
        private readonly V2AllyOrder[] _v2AllyInFlight = new V2AllyOrder[9];
        private readonly V2AllyOrder[] _v2AllyReplies = new V2AllyOrder[9];
        private readonly V2AllyOrder[] _v2AllyVoices = new V2AllyOrder[9];
        private readonly V2AllyOrder[] _v2AllyOrderStatus = new V2AllyOrder[9];
        private long _v2AllyReplySequence;
        // Only prevents interception of our own managed GameAction replay.
        // Native evaluators normally run later on the simulation thread.
        [ThreadStatic] private static V2AllyOrder _v2DispatchingAllyOrder;
        private MethodInfo _v2AllyGameActionTarget;
        private bool _v2AllyGameActionPatched;

        private bool PrepareV2AllyOrders(out string failure)
        {
            _v2AllyGameActionTarget = typeof(EngineInterface).GetMethod("GameAction",
                BindingFlags.Public | BindingFlags.Static, null,
                new[] { typeof(Enums.GameActionCommand), typeof(int), typeof(int), typeof(int) }, null);
            failure = _v2AllyGameActionTarget != null
                && _v2AllyGameActionTarget.ReturnType == typeof(int)
                ? null : "pinned EngineInterface.GameAction command signature is unavailable";
            return failure == null;
        }

        private void ApplyV2AllyOrders()
        {
            _harmony.Patch(_v2AllyGameActionTarget, prefix: new HarmonyMethod(
                typeof(DiplomacyFeature).GetMethod("V2AllyGameActionPrefix",
                    BindingFlags.NonPublic | BindingFlags.Static)));
            _v2AllyGameActionPatched = true;
        }

        private void RollbackV2AllyOrders()
        {
            if (_v2AllyGameActionPatched && _v2AllyGameActionTarget != null)
                _harmony.Unpatch(_v2AllyGameActionTarget, HarmonyPatchType.Prefix, _harmony.Id);
            _v2AllyGameActionPatched = false;
            ClearV2AllyOrders();
        }

        private void ClearV2AllyOrders()
        {
            for (int player = 1; player <= 8; player++)
            {
                Interlocked.Exchange(ref _v2AllyOrders[player], null);
                Interlocked.Exchange(ref _v2AllyInFlight[player], null);
                Interlocked.Exchange(ref _v2AllyReplies[player], null);
                _v2AllyVoices[player] = null;
                _v2AllyOrderStatus[player] = null;
            }
        }

        private static bool V2AllyGameActionPrefix(Enums.GameActionCommand __0,
            int __1, int __2, int __3, ref int __result)
        {
            if (__0 != Enums.GameActionCommand.Ally_Orders
                || _v2DispatchingAllyOrder != null) return true;
            DiplomacyFeature owner = Volatile.Read(ref _activeOwner);
            if (owner == null || !Volatile.Read(ref owner._mapActive)
                || Volatile.Read(ref owner._mapDisabled) || __2 < 1 || __2 > 8
                || !((__1 >= 1 && __1 <= 6) || __1 == 10 || __1 == 11)) return true;
            owner.NoteLane(LaneUiPanel);
            // This is the managed, human HUD command boundary, before its
            // blocking native monitor. A busy engine never consumes the click.
            var order = new V2AllyOrder
            {
                Opcode = __1, Consulted = __2, Target = __3,
                Requester = Volatile.Read(ref owner._localPlayer),
                Generation = Volatile.Read(ref owner._sessionGeneration),
                Epoch = Volatile.Read(ref owner._mapEpoch),
                RequestedDay = Math.Max(0, Volatile.Read(ref owner._lastProcessedDay)),
            };
            Interlocked.Exchange(ref owner._v2AllyOrders[__2], order);
            __result = 0; // The original Ally_Orders wrapper returns zero too.
            return false;
        }

        private string V2AllyOrderStatusText(int player)
        {
            if (player < 1 || player > 8 || !_mapActive || _mapDisabled) return "";
            V2AllyOrder pending = Volatile.Read(ref _v2AllyOrders[player])
                ?? Volatile.Read(ref _v2AllyInFlight[player]);
            if (V2AllyOrderIsCurrent(pending, player))
                return V2AllyOrderDescription(pending) + " · "
                    + Text("wartet", "waiting") + V2AllyOrderDay(pending.RequestedDay);
            V2AllyOrder reply = _v2AllyOrderStatus[player];
            if (V2AllyOrderIsCurrent(reply, player) && reply.ResponseDaysRemaining > 0)
            {
                string status = reply.EndedDay >= 0
                    ? Text("nicht mehr aktiv", "no longer active")
                    : reply.Opcode == 10 && reply.Accepted == true
                        ? Text("zurückgenommen", "withdrawn")
                        : reply.Accepted == true ? Text("angenommen", "accepted")
                        : reply.Accepted == false ? Text("abgelehnt", "declined")
                        : Text("nicht bestätigt", "unconfirmed");
                return V2AllyOrderDescription(reply) + " · " + status
                    + V2AllyOrderDay(reply.EndedDay >= 0 ? reply.EndedDay : reply.DispatchedDay);
            }
            // After load there is no remembered native acknowledgement. Only
            // Vanilla's current order is displayed, without invented age/reply.
            int kind, target;
            if (!IsCoalitionAllied(player) || !TryReadV2NativeAllyOrder(player, out kind, out target)) return "";
            return kind == 1
                ? V2AllyAttackDescription(player, target) + " · " + Text("aktiv", "active")
                : kind == 2
                    ? string.Format(CultureInfo.InvariantCulture,
                        Text("{0}: Verteidigung", "{0}: Defence"), V2PlayerName(player))
                        + " · " + Text("aktiv", "active")
                    : "";
        }

        private bool V2AllyOrderIsCurrent(V2AllyOrder order, int player)
        {
            return order != null && order.Consulted == player
                && order.Requester == _localPlayer && order.Generation == _sessionGeneration
                && order.Epoch == _mapEpoch;
        }

        private string V2AllyAttackDescription(int consulted, int target)
        {
            return string.Format(CultureInfo.InvariantCulture,
                Text("{0}: Angriff auf {1}", "{0}: Attack on {1}"),
                V2PlayerName(consulted), V2PlayerName(target));
        }

        private string V2AllyOrderDescription(V2AllyOrder order)
        {
            if (order.Opcode == 10) return string.Format(CultureInfo.InvariantCulture,
                Text("{0}: Rücknahme", "{0}: Withdrawal"), V2PlayerName(order.Consulted));
            if (order.Opcode == 11) return string.Format(CultureInfo.InvariantCulture,
                Text("{0}: Verteidigung für {1}", "{0}: Defence for {1}"),
                V2PlayerName(order.Consulted), V2PlayerName(order.Requester));
            return V2AllyAttackDescription(order.Consulted, order.Target);
        }

        private string V2AllyOrderDay(int day)
        {
            return string.Format(CultureInfo.InvariantCulture,
                Text(" · Tag {0}", " · Day {0}"), Math.Max(0, day));
        }

        // Called only for the actual visible details/selected overview footer,
        // never for hidden rows or when goods status covers the order feedback.
        // Distinct visible days count once; hidden gaps are never caught up.
        private void NoteV2AllyOrderStatusShown(int player)
        {
            if (player < 1 || player > 8 || !_mapActive || _mapDisabled) return;
            if (V2AllyOrderIsCurrent(Volatile.Read(ref _v2AllyOrders[player]), player)
                || V2AllyOrderIsCurrent(Volatile.Read(ref _v2AllyInFlight[player]), player)) return;
            V2AllyOrder reply = _v2AllyOrderStatus[player];
            if (!V2AllyOrderIsCurrent(reply, player) || reply.ResponseDaysRemaining <= 0) return;
            int day = Math.Max(0, _lastProcessedDay);
            if (reply.LastVisibleDay >= 0 && day > reply.LastVisibleDay)
                reply.ResponseDaysRemaining--;
            reply.LastVisibleDay = day;
        }

        private bool TryReadV2NativeAllyOrder(int player, out int kind, out int target)
        {
            kind = 0; target = 0;
            if (player < 1 || player > 8) return false;
            GameData game = GameData.Instance;
            EngineInterface.PlayState live = game == null ? null : game.lastGameState;
            short[] orders = live == null ? null : live.skirmish_order;
            if (orders == null || player >= orders.Length) return false;
            kind = orders[player];
            if (kind == 1)
            {
                short[] targets = live.skirmish_order_player;
                if (targets == null || player >= targets.Length) return false;
                target = targets[player];
                if (target < 1 || target > 8) return false;
            }
            return kind >= 0 && kind <= 2;
        }

        private void ObserveV2AllyOrderStatus(int player)
        {
            V2AllyOrder reply = _v2AllyOrderStatus[player];
            if (!V2AllyOrderIsCurrent(reply, player) || reply.Accepted != true
                || reply.Opcode == 10 || reply.EndedDay >= 0) return;
            int kind, target;
            if (!TryReadV2NativeAllyOrder(player, out kind, out target)) return;
            bool matches = reply.Opcode == 11 ? kind == 2
                : kind == 1 && target == reply.Target;
            if (matches) reply.ObservedActive = true;
            else if (reply.ObservedActive)
            {
                // A matching order was observed before it disappeared/changed.
                // This proves inactivity, never victory or successful fulfilment.
                reply.EndedDay = Math.Max(0, _lastProcessedDay);
                reply.ResponseDaysRemaining = 3;
                reply.LastVisibleDay = -1;
            }
        }

        private void PumpV2AllyOrders()
        {
            for (int player = 1; player <= 8; player++)
            {
                V2AllyOrder inflight = Volatile.Read(ref _v2AllyInFlight[player]);
                if (inflight != null)
                {
                    if (!V2AllyOrderIsCurrent(inflight, player) || !_mapActive || _mapDisabled)
                        Interlocked.CompareExchange(ref _v2AllyInFlight[player], null, inflight);
                    else if (ReadSimulationTick() - inflight.DispatchedTick >= V2AllyReplyWaitTicks)
                    {
                        Interlocked.CompareExchange(ref _v2AllyInFlight[player], null, inflight);
                        // Do not overwrite a real decision already waiting in
                        // the mailbox just because this frame was delayed.
                        if (Volatile.Read(ref _v2AllyReplies[player]) == null)
                            PublishV2AllyOrderReply(inflight);
                    }
                    else continue;
                }
                V2AllyOrder order = Volatile.Read(ref _v2AllyOrders[player]);
                if (order == null) continue;
                if (!_mapActive || _mapDisabled || order.Generation != _sessionGeneration
                    || order.Epoch != _mapEpoch || order.Requester != _localPlayer)
                { Interlocked.CompareExchange(ref _v2AllyOrders[player], null, order); continue; }
                if (_pendingTeamTransition != null || _inventoryRestorePending) continue;
                IDisposable lease;
                if (!TryEnterNativeInventorySection(out lease)) break;
                using (lease)
                {
                    if (!ReferenceEquals(Interlocked.CompareExchange(
                            ref _v2AllyOrders[player], null, order), order)) continue;
                    order.DispatchedDay = Math.Max(0, _lastProcessedDay);
                    order.DispatchedTick = ReadSimulationTick();
                    try
                    {
                        if (!IsAlivePlayer(order.Consulted)
                            || !IsCoalitionAllied(order.Consulted)
                            || (order.Opcode >= 1 && order.Opcode <= 6
                                && (order.Target < 1 || order.Target > 8 || !IsAlivePlayer(order.Target))))
                        { order.Accepted = false; PublishV2AllyOrderReply(order); }
                        else
                        {
                            order.LordId = (int)GamePlayerManagerAPI.Instance.GetAILord(order.Consulted);
                            if (order.Opcode >= 1 && order.Opcode <= 6)
                                AuthorizeV2AllyAttack(order);
                            if (order.Opcode != 10)
                                Volatile.Write(ref _v2AllyInFlight[player], order);
                            _v2DispatchingAllyOrder = order;
                            EngineInterface.GameAction(Enums.GameActionCommand.Ally_Orders,
                                order.Opcode, order.Consulted, order.Target);
                            // Withdrawal has no evaluator acknowledgement.
                            // A queued command's return zero proves no success.
                            if (order.Opcode == 10) PublishV2AllyOrderReply(order);
                        }
                    }
                    catch (Exception exception)
                    {
                        // A command failure must not disable diplomacy. Unknown
                        // native completion is reported as unknown, never replayed.
                        order.Accepted = null;
                        Interlocked.CompareExchange(ref _v2AllyInFlight[player], null, order);
                        PublishV2AllyOrderReply(order);
                        V2NoteVassalOrderFault("dispatch", exception);
                    }
                    finally { _v2DispatchingAllyOrder = null; }
                }
            }
            if (!CanPresentDiplomacyUi) return;
            for (int player = 1; player <= 8; player++)
            {
                V2AllyOrder reply = Interlocked.Exchange(ref _v2AllyReplies[player], null);
                if (reply == null)
                {
                    ObserveV2AllyOrderStatus(player);
                    continue;
                }
                if (!V2AllyOrderIsCurrent(reply, player) || !_mapActive || _mapDisabled
                    || (reply.NativeDecision && !IsCoalitionAllied(player))) continue;
                V2AllyOrder inflight = Volatile.Read(ref _v2AllyInFlight[player]);
                if (inflight != null && reply.NativeDecision
                    && (inflight.Opcode == 11) == (reply.Opcode == 11)
                    && (reply.Opcode == 11 || inflight.Target == reply.Target))
                    Interlocked.CompareExchange(ref _v2AllyInFlight[player], null, inflight);
                _v2AllyOrderStatus[player] = reply;
                ObserveV2AllyOrderStatus(player);
                Log("ally_order", "consulted=" + player.ToString(CultureInfo.InvariantCulture)
                    + "|target=" + reply.Target.ToString(CultureInfo.InvariantCulture)
                    + "|requester=" + reply.Requester.ToString(CultureInfo.InvariantCulture)
                    + "|kind=" + (reply.Opcode == 11 ? "defend" : reply.Opcode == 10 ? "withdraw" : "attack")
                    + "|origin=" + (reply.NativeDecision ? "native_evaluation" : "managed_dispatch")
                    + "|day=" + reply.DispatchedDay.ToString(CultureInfo.InvariantCulture)
                    + "|status=" + (reply.Accepted.HasValue
                        ? (reply.Accepted.Value ? "accepted" : "declined") : "unconfirmed"));
                if (reply.SupplyVoice && reply.Accepted.HasValue)
                    _v2AllyVoices[player] = reply;
            }
            for (int player = 1; player <= 8; player++)
            {
                V2AllyOrder voice = _v2AllyVoices[player];
                if (voice != null && PlayV2AllyOrderReply(voice))
                    _v2AllyVoices[player] = null;
            }
        }

        private bool PlayV2AllyOrderReply(V2AllyOrder reply)
        {
            // Original SFXManager catalogue: SK_WILL_ATTACK_ENEMY,
            // SK_WILL_SEND_TROOPS, SK_CANT_ATTACK, SK_CANT_HELP. Only our
            // PreSkip path needs replacement audio; ordinary native evaluation
            // already emits its own answer before Post.
            bool defend = reply.Opcode == 11;
            string tag = reply.Accepted == true
                ? (defend ? "SK_WILL_SEND_TROOPS" : "SK_WILL_ATTACK_ENEMY")
                : (defend ? "SK_CANT_HELP" : "SK_CANT_ATTACK");
            string stem = reply.Accepted == true
                ? (defend ? "helpsent" : "willattack")
                : (defend ? "nohelp" : "noattack");
            // The callback is independent of a previous managed dispatch; use
            // the actual current AI identity, never a UI personality number.
            int lord;
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease)) return false;
            try
            {
                using (lease)
                {
                    if (!V2AllyOrderIsCurrent(reply, reply.Consulted)
                        || !IsAlivePlayer(reply.Consulted)) return true;
                    lord = (int)GamePlayerManagerAPI.Instance.GetAILord(reply.Consulted);
                }
            }
            catch (Exception exception) { V2NoteVassalOrderFault("reply_identity", exception); return true; }
            string path = lord >= (int)AILords.SK_X1 && lord <= (int)AILords.SK_X8
                ? "*" + reply.Consulted.ToString(CultureInfo.InvariantCulture) + "*" + tag
                : "fx\\speech\\" + (lord >= 0 && lord < StandardLordSpeechPrefixes.Length
                    ? StandardLordSpeechPrefixes[lord] : "all") + "_" + stem + "_01.wav";
            try { if (SFXManager.instance != null) SFXManager.instance.playSpeech(1, path, 1f); }
            catch (Exception exception) { V2NoteVassalOrderFault("reply", exception); }
            return true;
        }

        private void PublishV2AllyOrderReply(V2AllyOrder reply)
        {
            if (reply.ReplySequence == 0)
                reply.ReplySequence = Interlocked.Increment(ref _v2AllyReplySequence);
            for (;;)
            {
                V2AllyOrder previous = Volatile.Read(ref _v2AllyReplies[reply.Consulted]);
                if (previous != null && previous.ReplySequence >= reply.ReplySequence) return;
                if (ReferenceEquals(Interlocked.CompareExchange(
                        ref _v2AllyReplies[reply.Consulted], reply, previous), previous)) return;
            }
        }

        private void NoteV2AllyOrderDecision(bool defend, int consulted, int requester,
            int target, bool accepted, bool supplyVoice)
        {
            if (consulted < 1 || consulted > 8 || requester != Volatile.Read(ref _localPlayer)
                || !Volatile.Read(ref _mapActive) || Volatile.Read(ref _mapDisabled)
                || (!defend && (target < 1 || target > 8))) return;
            int day = Math.Max(0, Volatile.Read(ref _lastProcessedDay));
            PublishV2AllyOrderReply(new V2AllyOrder
            {
                Opcode = defend ? 11 : 1, Consulted = consulted, Requester = requester,
                Target = defend ? requester : target, NativeDecision = true,
                Accepted = accepted, SupplyVoice = supplyVoice,
                RequestedDay = day, DispatchedDay = day,
                Generation = Volatile.Read(ref _sessionGeneration), Epoch = Volatile.Read(ref _mapEpoch),
            });
        }

        private void AuthorizeV2AllyAttack(V2AllyOrder order)
        {
            int consulted = order.Consulted, requester = order.Requester, target = order.Target;
            if (requester != _localPlayer || !IsCoalitionAllied(consulted)
                || !IsAlivePlayer(target)) return;
            string coalitionId;
            RelationState relation;
            if (!_playerCoalition.TryGetValue(target, out coalitionId)
                || !_relations.TryGetValue(coalitionId, out relation) || relation.Allied
                || !V2TreatyProtectsPlayers(requester, target)) return;
            DiplomacyV2StateMachine.BreakAgreementByPlayer(relation,
                Math.Max(0, _lastProcessedDay), _coalitions[coalitionId].Target,
                DiplomacyV2BreachKind.TreacherousAttack, _rules);
            _v2PendingAgreementSafety.Remove(coalitionId);
            QueueV2BreachNotice(coalitionId, target, "command=ally_attack|consulted="
                + consulted.ToString(CultureInfo.InvariantCulture)
                + "|target_player=" + target.ToString(CultureInfo.InvariantCulture));
            RefreshV2TreatyZones(Math.Max(0, _lastProcessedDay));
            // The caller can immediately issue native orders/damage after its
            // evaluator returns. Publish the committed relation before that.
            PublishCombatProtectionSnapshot();
        }
    }
}
#endif
