using System;
using System.Linq;
using CrusaderDE;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        private string DiplomacyCoalitionNames(CoalitionState coalition)
        {
            return string.Join(", ", coalition.MemberPlayerIds.OrderBy(p => p).Select(player =>
            {
#if DIPLOMACY_V2
                return V2PlayerName(player);
#else
                EngineInterface.PlayState live = GameData.Instance.lastGameState;
                string name = live.is_skirmish_player(player)
                    ? OnScreenText.getComputerName(live.computer_register[player], live.computer_names[player])
                    : Platform_Multiplayer.Instance.getPlayerName(player);
                return string.IsNullOrWhiteSpace(name) ? Text("Herrscher", "Ruler") : name.Trim();
#endif
            }));
        }

#if DIPLOMACY_V2
        private sealed class RelationshipDecisionQuote
        {
            internal string CoalitionId, Fingerprint, Contract, Names;
            internal int LocalPlayer, TargetPlayer;
            internal long Generation;
            internal DiplomacyV2RelationshipDecisionKind Kind;
            internal string Key { get { return Kind == DiplomacyV2RelationshipDecisionKind.AcceptAllianceOffer
                ? "alliance_offer:" + CoalitionId
                : "relationship:" + CoalitionId + ":" + Kind + ":" + Contract; } }
        }

        private RelationshipDecisionQuote CaptureRelationshipDecision(string id, int player,
            DiplomacyV2RelationshipDecisionKind kind)
        {
            CoalitionState coalition; RelationState relation;
            if (!_mapActive || _mapDisabled || !_coalitions.TryGetValue(id, out coalition)
                || !_relations.TryGetValue(id, out relation) || DiplomacyV2RelationshipDecisions.HasPending(relation.V2)
                || !DiplomacyV2RelationshipDecisions.Eligible(relation, kind, Math.Max(0, _lastProcessedDay))) return null;
            string stamp = DiplomacyV2RelationshipDecisions.Contract(relation, coalition, _localPlayer, player, kind);
            if (stamp == null) return null;
            return new RelationshipDecisionQuote { CoalitionId = id, TargetPlayer = player, LocalPlayer = _localPlayer,
                Generation = _sessionGeneration, Fingerprint = _mapFingerprint, Contract = stamp, Kind = kind,
                Names = DiplomacyCoalitionNames(coalition) };
        }

        private bool IsCurrentRelationshipDecision(RelationshipDecisionQuote quote)
        {
            CoalitionState coalition; RelationState relation;
            return quote != null && _mapActive && !_mapDisabled && !_mapBootstrapPending
                && quote.Generation == _sessionGeneration && quote.LocalPlayer == _localPlayer
                && string.Equals(quote.Fingerprint, _mapFingerprint, StringComparison.Ordinal)
                && _coalitions.TryGetValue(quote.CoalitionId, out coalition)
                && _relations.TryGetValue(quote.CoalitionId, out relation)
                && !DiplomacyV2RelationshipDecisions.HasPending(relation.V2)
                && IsAlivePlayer(quote.LocalPlayer) && IsAlivePlayer(quote.TargetPlayer)
                && (quote.Kind != DiplomacyV2RelationshipDecisionKind.AcceptAllianceOffer
                    || CanJoinAlliance(quote.CoalitionId))
                && DiplomacyV2RelationshipDecisions.Eligible(relation, quote.Kind, Math.Max(0, _lastProcessedDay))
                && string.Equals(quote.Contract,
                    DiplomacyV2RelationshipDecisions.Contract(relation, coalition, _localPlayer, quote.TargetPlayer, quote.Kind),
                    StringComparison.Ordinal);
        }

        private void StageRelationshipDecision(RelationshipDecisionQuote quote, bool accepted = true)
        {
            lock (_gate)
            {
                if (!IsCurrentRelationshipDecision(quote)) return;
                var kind = quote.Kind;
                if (kind == DiplomacyV2RelationshipDecisionKind.AcceptAllianceOffer && !accepted)
                    kind = DiplomacyV2RelationshipDecisionKind.RejectAllianceOffer;
                RelationState relation = _relations[quote.CoalitionId];
                if (!DiplomacyV2RelationshipDecisions.Stage(relation, _coalitions[quote.CoalitionId],
                    _localPlayer, quote.TargetPlayer, Math.Max(0, _lastProcessedDay), kind, quote.Contract)) return;
                // A later rollback-only rescue save must retain an answer made
                // while its older inventory base was waiting for completion.
                CopyRelationshipDecisionToInventoryBase(relation);
            }
        }

        private void CopyRelationshipDecisionToInventoryBase(RelationState live)
        {
            if (_inventoryRecoveryBaseState == null) return;
            RelationState before = _inventoryRecoveryBaseState.Relations.FirstOrDefault(r => r.CoalitionId == live.CoalitionId);
            if (before == null || before.V2 == null) return;
            DiplomacyV2RelationshipDecisions.CopyPendingDecision(live.V2, before.V2);
        }

        private void PumpPendingRelationshipDecisions()
        {
            if (!_mapActive || _mapDisabled || _mapBootstrapPending || _inventoryRestorePending
                || _nativeTransferProbe != null || _pendingPackage != null || _pendingTeamTransition != null) return;
            foreach (string id in _relations.Keys.OrderBy(x => x, StringComparer.Ordinal).ToArray())
            {
                RelationState relation = _relations[id]; CoalitionState coalition = _coalitions[id];
                if (!DiplomacyV2RelationshipDecisions.HasPending(relation.V2)) continue;
                if (!DiplomacyV2RelationshipDecisions.Matches(relation, coalition, _localPlayer, Math.Max(0, _lastProcessedDay)))
                { DiplomacyV2RelationshipDecisions.Clear(relation.V2); continue; }
                IDisposable lease;
                if (!TryEnterNativeInventorySection(out lease)) return;
                using (lease)
                {
                    DiplomacyManagedStateMemento before = null;
                    try
                    {
                        int player = relation.V2.PendingRelationshipDecisionPlayerId;
                        if (!IsAlivePlayer(_localPlayer) || !IsAlivePlayer(player))
                        { DiplomacyV2RelationshipDecisions.Clear(relation.V2); continue; }
                        var kind = relation.V2.PendingRelationshipDecision;
                        before = CaptureManagedStateMemento();
                        DiplomacyV2RelationshipDecisions.Clear(relation.V2);
                        switch (kind)
                        {
                            case DiplomacyV2RelationshipDecisionKind.EndAlliance:
                                PlayerBreakOne(id);
                                if (_pendingTeamTransition == null || _pendingTeamTransition.CoalitionId != id
                                    || _pendingTeamTransition.Kind != DiplomacyTeamTransitionKind.PlayerBreakOne)
                                    throw new InvalidOperationException("Alliance end was not journaled");
                                break;
                            case DiplomacyV2RelationshipDecisionKind.EndAgreement:
                                ExecuteBoundAgreementEnd(coalition, relation);
                                break;
                            case DiplomacyV2RelationshipDecisionKind.AcceptAllianceOffer:
                            case DiplomacyV2RelationshipDecisionKind.RejectAllianceOffer:
                                ResolveSpontaneousOffer(id, _sessionGeneration, _mapFingerprint,
                                    kind == DiplomacyV2RelationshipDecisionKind.AcceptAllianceOffer);
                                if (relation.PendingOffer && _pendingTeamTransition == null)
                                    throw new InvalidOperationException("Alliance answer was not committed");
                                break;
                        }
                    }
                    catch (Exception exception)
                    {
                        if (before != null) RestoreManagedStateMemento(before);
                        try { Log("relationship_decision", "status=deferred|reason=" + Safe(exception.GetType().Name)); }
                        catch { }
                    }
                    finally { PublishCombatProtectionSnapshot(); }
                }
                if (_pendingTeamTransition != null) return;
            }
        }

        private void ExecuteBoundAgreementEnd(CoalitionState coalition, RelationState relation)
        {
            DiplomacyV2StateMachine.BreakAgreementByPlayer(relation,
                Math.Max(0, _lastProcessedDay), coalition.Target, _rules);
            ShowMessage(DiplomacyCoalitionNames(coalition) + " · " + Text(
                "Das Abkommen wurde aufgekündigt. Vertrauen und Ansehen sind beschädigt.",
                "The agreement was ended. Trust and standing have suffered."));
            Log("agreement", "coalition=" + coalition.CoalitionId + "|status=broken|actor=player");
        }
#endif
    }
}
