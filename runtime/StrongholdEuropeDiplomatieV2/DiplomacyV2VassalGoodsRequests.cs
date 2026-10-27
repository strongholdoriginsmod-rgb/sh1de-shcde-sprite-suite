#if DIPLOMACY_V2
using System;
using System.Threading;
using CrusaderDE;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.Player;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        private IDisposable _v2VassalRequestSubscription;
        private long _v2VassalRequestBlockedPairs;
        private readonly int[] _v2VassalRequestCancelGood = new int[9];
        private readonly int[] _v2VassalRequestCancelAmount = new int[9];

        private static long V2GoodsRequestPairBit(int requester, int requestedPlayer)
        {
            return requester >= 1 && requester <= 8 && requestedPlayer >= 1
                && requestedPlayer <= 8 && requester != requestedPlayer
                ? 1L << ((requester - 1) * 8 + requestedPlayer - 1) : 0L;
        }

        // Managed model only; callers own _gate. This is personal fealty, never
        // the entire coalition. A named vassal cannot request from any player;
        // an ordinary coalition neighbour is not treated as that vassal.
        private bool V2VassalRequestForbidden(int requester, int requestedPlayer)
        {
            if (V2GoodsRequestPairBit(requester, requestedPlayer) == 0) return false;
            foreach (RelationState relation in _relations.Values)
                if (relation.Allied && DiplomacyV2Vassalage.IsActive(relation.V2)
                    && DiplomacyV2Vassalage.VassalOf(relation.V2) == requester)
                    return true;
            return false;
        }

        private bool V2CanRequestGoodsFrom(int player)
        {
            return player >= 1 && player <= 8 && player != _localPlayer
                && !V2VassalRequestForbidden(_localPlayer, player);
        }

        private void PublishV2VassalRequestSnapshot()
        {
            long pairs = 0;
            if (_mapActive && !_mapDisabled && !_mapBootstrapPending)
                foreach (RelationState relation in _relations.Values)
                    if (relation.Allied && DiplomacyV2Vassalage.IsActive(relation.V2))
                        for (int requested = 1; requested <= 8; requested++)
                            pairs |= V2GoodsRequestPairBit(
                                DiplomacyV2Vassalage.VassalOf(relation.V2), requested);
            Volatile.Write(ref _v2VassalRequestBlockedPairs, pairs);
        }

        private void OnV2NativeGoodsRequest(PlayerAIRequestGoodsEventArgs request)
        {
            if (request == null || request.Phase != EventHookPhase.Pre) return;
            // COPY 1.45 names are misleading here: Ally_RequestGoods1064 ->
            // packet71/kind1 -> D7870 places the REQUESTED player in Source and
            // the REQUESTER in Target. Do not reuse the received-goods roles.
            long pair = V2GoodsRequestPairBit(request.TargetPlayerId, request.SourcePlayerId);
            if ((Volatile.Read(ref _v2VassalRequestBlockedPairs) & pair) != 0)
                request.SkipOriginalFunction = true;
            // No model lock/native read/log/UI on the simulation callback.
        }

        private void ResetV2VassalGoodsRequests()
        {
            Volatile.Write(ref _v2VassalRequestBlockedPairs, 0L);
            Array.Clear(_v2VassalRequestCancelGood, 0, _v2VassalRequestCancelGood.Length);
            Array.Clear(_v2VassalRequestCancelAmount, 0, _v2VassalRequestCancelAmount.Length);
        }

        private void PumpV2VassalGoodsRequests()
        {
            if (!_mapActive || _mapDisabled || _mapBootstrapPending
                || _inventoryRestorePending || _nativeTransferProbe != null
                || _pendingPackage != null || _pendingTeamTransition != null) return;
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease)) return;
            using (lease)
            {
                // The native HUD's last complete PlayState exposes incoming
                // requests to local. Original CancelGoods1062 -> packet71/kind3
                // -> D7400 zeros exactly these type/amount fields and updates
                // request cooldown; return0 means queued, not failure.
                var state = GameData.Instance == null ? null : GameData.Instance.lastGameState;
                if (state == null || state.skirmish_player_requesting_type == null
                    || state.skirmish_player_requesting_amount == null) return;
                for (int requester = 1; requester <= 8; requester++)
                {
                    if (requester >= state.skirmish_player_requesting_type.Length
                        || requester >= state.skirmish_player_requesting_amount.Length) continue;
                    int good = state.skirmish_player_requesting_type[requester];
                    int amount = state.skirmish_player_requesting_amount[requester];
                    if (!V2VassalRequestForbidden(requester, _localPlayer) || good <= 0 || amount <= 0)
                    {
                        _v2VassalRequestCancelGood[requester] = 0;
                        _v2VassalRequestCancelAmount[requester] = 0;
                        continue;
                    }
                    if (_v2VassalRequestCancelGood[requester] == good
                        && _v2VassalRequestCancelAmount[requester] == amount) continue;
                    // Claim before dispatch: a foreign callback can throw after
                    // native accepted the packet. Never emit it each frame. A
                    // map/load reset permits cleanup of a persisted old request.
                    _v2VassalRequestCancelGood[requester] = good;
                    _v2VassalRequestCancelAmount[requester] = amount;
                    try { EngineInterface.GameAction(Enums.GameActionCommand.Ally_CancelGoodsReq, requester, 0, 0); }
                    catch { /* The next native snapshot, not return0, attests consumption. */ }
                }
            }
        }
    }
}
#endif
