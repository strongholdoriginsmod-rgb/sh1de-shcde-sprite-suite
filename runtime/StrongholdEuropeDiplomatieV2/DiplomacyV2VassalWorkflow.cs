#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using CrusaderDE;
using SHCDESE.API;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        // Presentation is session-local; the saved request date never restarts.
        // A restored decision cannot time out invisibly behind another popup.
        private readonly Dictionary<string, int> _v2EqualityPresentedDays =
            new Dictionary<string, int>(StringComparer.Ordinal);
        private readonly Dictionary<string, int> _v2SubmissionPresentedDays =
            new Dictionary<string, int>(StringComparer.Ordinal);

        private sealed class PendingV2FealtyCommand
        {
            internal long Generation;
            internal string Fingerprint;
            internal object Panel;
            internal int Player, Selection;
            internal bool Overview;
            internal Action Execute;
            internal Func<bool> StillCurrent;
            internal string DecisionKey;
            internal DiplomacyPanelCommandLifetime Lifetime;
            internal long QueuedTick;
        }

        // Ein Knopfdruck wartet hoechstens so lange auf einen freien Takt.
        // 10.09.2026: laenger warten heisst in der Praxis "fuer immer", denn
        // solange einer liegt, wird jeder weitere Druck verworfen.
        private const long V2FealtyCommandExpiryTicks = 600;

        private PendingV2FealtyCommand _pendingV2FealtyCommand;
        private readonly Queue<string> _v2FealtyAnswerOrder = new Queue<string>();
        private readonly Dictionary<string, PendingV2FealtyCommand> _v2FealtyAnswers =
            new Dictionary<string, PendingV2FealtyCommand>(StringComparer.Ordinal);

        private void CancelV2FealtyCommand()
        {
            PendingV2FealtyCommand command = _pendingV2FealtyCommand;
            _pendingV2FealtyCommand = null;
            if (command != null && command.Lifetime != null) command.Lifetime.Dispose();
        }

        private void QueueV2FealtyCommand(object panel, int player, Action execute,
            string decisionKey = null, Func<bool> stillCurrent = null)
        {
            // An explicit answer supersedes an unexecuted panel request. Repeated
            // panel clicks neither replace an intent nor generate another roll.
            if (panel != null && _pendingV2FealtyCommand != null) return;
            var command = new PendingV2FealtyCommand
            {
                Generation = _sessionGeneration, Fingerprint = _mapFingerprint,
                Panel = panel, Player = player, Overview = _v2OverviewVisible,
                Selection = panel == null ? 0 : SelectedPlayer(panel), Execute = execute,
                DecisionKey = decisionKey, StillCurrent = stillCurrent, QueuedTick = _featureTicks,
                Lifetime = panel == null ? null : new DiplomacyPanelCommandLifetime(MainViewModel.Instance),
            };
            if (panel == null)
            {
                // One saved offer per coalition, at most seven counterparts.
                // Different rulers' accepted answers must never deduplicate each
                // other. A newer quote for the same ruler supersedes a stale one.
                if (string.IsNullOrEmpty(decisionKey)) throw new ArgumentException("decisionKey");
                CancelV2FealtyCommand();
                if (!_v2FealtyAnswers.ContainsKey(decisionKey)) _v2FealtyAnswerOrder.Enqueue(decisionKey);
                _v2FealtyAnswers[decisionKey] = command;
            }
            else _pendingV2FealtyCommand = command;
            PumpV2FealtyCommand();
        }

        private void RemoveV2FealtyCommand(PendingV2FealtyCommand command)
        {
            if (command.Panel != null) CancelV2FealtyCommand();
            else
            {
                _v2FealtyAnswerOrder.Dequeue();
                _v2FealtyAnswers.Remove(command.DecisionKey);
            }
        }

        private void PumpV2FealtyCommand()
        {
            PendingV2FealtyCommand command = _v2FealtyAnswerOrder.Count > 0
                ? _v2FealtyAnswers[_v2FealtyAnswerOrder.Peek()] : _pendingV2FealtyCommand;
            if (command == null) return;
            if (!_mapActive || _mapDisabled || _mapBootstrapPending
                || command.Generation != _sessionGeneration
                || !string.Equals(command.Fingerprint, _mapFingerprint, StringComparison.Ordinal)
                || command.StillCurrent != null && !command.StillCurrent()
                || command.Panel != null && (command.Lifetime.Cancelled
                    || !ReferenceEquals(command.Panel, CurrentAlliesPanel())
                    || command.Overview != _v2OverviewVisible
                    || SelectedPlayer(command.Panel) != command.Selection
                    || command.Overview && _v2AllianceSelectedPlayer != command.Player))
            { RemoveV2FealtyCommand(command); return; }
            // Ein Knopfdruck, der auf einen belegten Motor trifft, blieb bis
            // zum 10.09.2026 unbegrenzt liegen und blockierte dabei jeden
            // weiteren Druck - im Spiellauf war "Unterwerfung fordern" nach
            // einer haengengebliebenen Guetersendung fuer den Rest der Partie
            // stumm. Eine gegebene Antwort (Panel == null) verfaellt NICHT:
            // eine Zusage bleibt gueltig (Benutzervorgabe 09.09.2026).
            if (command.Panel != null
                && _featureTicks - command.QueuedTick > V2FealtyCommandExpiryTicks)
            {
                Log("vassalage", "status=command_expired|player="
                    + command.Player.ToString(CultureInfo.InvariantCulture));
                RemoveV2FealtyCommand(command);
                return;
            }
            if (_inventoryRestorePending || _nativeTransferProbe != null
                || _pendingPackage != null || _pendingTeamTransition != null) return;
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease)) return;
            using (lease)
            {
                if (command.Lifetime != null && !command.Lifetime.TryClaim())
                { RemoveV2FealtyCommand(command); return; }
                RemoveV2FealtyCommand(command);
                // Model and native reads are protected; ShowMessage/Confirmation
                // only enqueue while this monitor is held. The frame presents later.
                command.Execute();
            }
        }

        private int V2TributeQuoteForPlayer(int vassalPlayer)
        {
            return DiplomacyV2Vassalage.TributeAmountForEconomy(V2EconomicStrengthForPlayer(vassalPlayer));
        }

        private long V2EconomicStrengthForPlayer(int vassalPlayer)
        {
            RequireNativeDiplomacySection();
            GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
            long economy = Math.Max(0, players.GetPlayerGold(vassalPlayer));
            foreach (int good in SendableGoods)
            {
                if (good == DiplomacyV2Tribute.GoldGoodId) continue;
                economy = SaturatingAdd(economy, SaturatingMultiply(
                    Math.Max(0, players.GetGoodAmount(vassalPlayer, (eGoods)good)),
                    _frozenPrices[good]));
            }
            economy = SaturatingAdd(economy, V2ProductionEconomy(new HashSet<int> { vassalPlayer }));
            return economy;
        }

        private void PumpV2TributeReassessments()
        {
            if (!_mapActive || _mapDisabled || _inventoryRestorePending
                || _nativeTransferProbe != null || _pendingPackage != null || _pendingTeamTransition != null) return;
            int day = Math.Max(0, _lastProcessedDay);
            foreach (RelationState relation in _relations.Values)
            {
                DiplomacyV2RelationState state = relation.V2;
                if (state == null || !state.TributeReassessmentPending
                    || !DiplomacyV2Tribute.IsActive(state) || day >= state.TributeNextDueDay) continue;
                IDisposable lease;
                if (!TryEnterNativeInventorySection(out lease)) return;
                using (lease)
                {
                    int payer = DiplomacyV2Vassalage.VassalOf(state);
                    int recipient = DiplomacyV2Vassalage.OverlordOf(state);
                    if (!IsAlivePlayer(payer) || !IsAlivePlayer(recipient)) continue;
                    int previousAmount = state.TributeAmount;
                    long economicStrength = V2EconomicStrengthForPlayer(payer);
                    if (!DiplomacyV2Tribute.TryReassessNextPeriod(state, day, economicStrength)) continue;
                    Log("tribute", "coalition=" + relation.CoalitionId
                        + "|status=reassessed|payer=" + payer.ToString(CultureInfo.InvariantCulture)
                        + "|economy=" + economicStrength.ToString(CultureInfo.InvariantCulture)
                        + "|previous_amount=" + previousAmount.ToString(CultureInfo.InvariantCulture)
                        + "|amount=" + state.TributeAmount.ToString(CultureInfo.InvariantCulture)
                        + "|due=" + state.TributeNextDueDay.ToString(CultureInfo.InvariantCulture));

                }
            }
        }

        private void ResetV2SubmissionPresentation()
        {
            _v2SubmissionPresentedDays.Clear();
            CancelV2FealtyCommand();
            _v2FealtyAnswerOrder.Clear();
            _v2FealtyAnswers.Clear();
        }

        private bool TryV2LordIdentity(int player, out int lord)
        {
            lord = 0;
            if (player < 1 || player > 8 || !IsAlivePlayer(player)) return false;
            try
            {
                // GetAILord reads the AI lineup. Player slots and legacy
                // PrimaryLordId are not evidence of a ruler's identity.
                lord = checked((int)GamePlayerManagerAPI.Instance.GetAILord(player));
                return lord > 0;
            }
            catch { return false; }
        }

        // Caller owns the engine monitor. Identity and contract eligibility are
        // separate from the military conditions for creating a NEW offer.
        private bool V2SubmissionStructurallyEligible(CoalitionState coalition,
            RelationState relation, int day, out int player, out int lord)
        {
            player = 0; lord = 0;
            if (coalition == null || relation == null || relation.V2 == null
                || coalition.Allied
                || coalition.MemberPlayerIds == null || coalition.MemberPlayerIds.Length != 1
                || !IsAlivePlayer(_localPlayer)) return false;
            player = coalition.MemberPlayerIds[0];
            if (player == _localPlayer || !TryV2LordIdentity(player, out lord)
                || DiplomacyV2Submission.EligibilityBlocker(relation, day, lord,
                    coalition.MemberPlayerIds.Length, CanJoinAlliance(coalition.CoalitionId)).HasValue)
                return false;
            return true;
        }

        // Called under the engine lease, before presenting or accepting a quote.
        // False also covers an incomplete observation: no timer or roll is spent.
        private bool ReviewV2SubmissionOffer(CoalitionState coalition, RelationState relation, int day)
        {
            if (!DiplomacyV2Submission.HasOffer(relation.V2)) return false;
            if (relation.V2.SubmissionOfferAccepted) return true; // journal already started
            int player, lord;
            if (!V2SubmissionStructurallyEligible(coalition, relation, day, out player, out lord)
                || relation.V2.SubmissionOfferPlayerId != player || relation.V2.SubmissionOfferLordId != lord)
            { WithdrawV2SubmissionOffer(coalition, relation, day, "structure_changed"); return false; }
            // Zwei verschiedene Lagen, die frueher gleich behandelt wurden:
            //
            // 1. Die Messung ist NICHT VERFUEGBAR (Burgscan noch nicht fertig,
            //    Engine belegt). Dann wird nichts entschieden und nichts
            //    verbraucht - es wird aufgeschoben. Eine Unterwerfung darf nie
            //    auf fehlenden Daten vollzogen werden.
            // 2. Die Messung ist verfuegbar und der Druck ist WEG. Das aendert
            //    am laufenden Angebot nichts mehr (Benutzervorgabe 09.09.2026):
            //    es steht seine sieben Spieltage, auch wenn die Belagerung
            //    zusammenbricht, und dasselbe gilt fuer eine bereits gegebene
            //    Zusage. Erst am Fristende entscheidet der Druck wieder, ob
            //    nachgebessert oder zurueckgezogen wird - ElapseResponseDay.
            //
            // Bis zum 09.09.2026 stand hier zusaetzlich eine Ruecknahme bei zu
            // schwachem Band. Sie mass in JEDEM Takt neu, obwohl der Druck nur
            // einmal je Spieltag aufgebaut wird: eine einzige schwankende
            // Messung nahm ein eben gemachtes Angebot zurueck und loeschte den
            // ueber Tage aufgebauten Druck. Im Spiel belegt mit
            // submission_offered seq=294 und submission_withdrawn seq=296.
            int band;
            if (!TryV2SubmissionPressureBand(player, lord, day, out band)) return false;
            _v2SubmissionVerifiedQuotes[coalition.CoalitionId] = relation.V2.SubmissionOfferCreatedDay;
            return true;
        }

        private void WithdrawV2SubmissionOffer(CoalitionState coalition,
            RelationState relation, int day, string grund)
        {
            bool wasPresented = _v2SubmissionPresentedDays.ContainsKey(coalition.CoalitionId);
            DiplomacyV2Submission.CloseOffer(relation.V2, day, false);
            DiplomacyV2Submission.LosePressure(relation.V2, day);
            CancelDiplomacyDialog("submission:" + coalition.CoalitionId);
            _v2SubmissionPresentedDays.Remove(coalition.CoalitionId);
            _v2SubmissionVerifiedQuotes.Remove(coalition.CoalitionId);
            Log("vassalage", "coalition=" + coalition.CoalitionId
                + "|status=submission_withdrawn|reason=" + Safe(grund)
                + "|pressure_days=" + relation.V2.SubmissionPressureDays.ToString(
                    CultureInfo.InvariantCulture));
            if (wasPresented) ShowMessage(Text(
                "Das Unterwerfungsangebot ist durch die veränderte Lage gegenstandslos geworden. Es entstand keine Lehnspflicht.",
                "The submission offer is no longer valid because the situation has changed. No fealty was established."));
        }

        private bool V2SubmissionTransitionCurrent(CoalitionState coalition,
            RelationState relation, int day)
        {
            int player, lord;
            return DiplomacyV2Submission.CanCommitOffer(relation)
                && V2SubmissionStructurallyEligible(coalition, relation, day, out player, out lord)
                && relation.V2.SubmissionOfferPlayerId == player
                && relation.V2.SubmissionOfferLordId == lord;
        }

        private void PumpV2SubmissionAssessments()
        {
            if (!_mapActive || _mapDisabled || _inventoryRestorePending
                || _nativeTransferProbe != null || _pendingPackage != null || _pendingTeamTransition != null) return;
            NormalizeV2VassalDemands();
            int day = Math.Max(0, _lastProcessedDay);
            long tick = ReadSimulationTick();
            bool reviewQuotes = _v2SubmissionQuoteReviewTick == long.MinValue
                || tick - _v2SubmissionQuoteReviewTick >= 32;
            if (reviewQuotes) _v2SubmissionQuoteReviewTick = tick;
            foreach (CoalitionState coalition in _coalitions.Values.OrderBy(c => c.CoalitionId, StringComparer.Ordinal).ToArray())
            {
                RelationState relation;
                if (!_relations.TryGetValue(coalition.CoalitionId, out relation) || relation.V2 == null) continue;
                DiplomacyV2RelationState state = relation.V2;
                if (state.SubmissionAcceptancePending)
                {
                    AnswerV2SubmissionOffer(coalition.CoalitionId, _sessionGeneration, _mapFingerprint,
                        state.SubmissionOfferPlayerId, state.SubmissionOfferLordId, state.SubmissionOfferTributeAmount,
                        state.SubmissionOfferCreatedDay, state.SubmissionOfferOrigin, true);
                    // An unknown castle/read can defer this answer without
                    // starting native work. It must not starve later saved Yes
                    // decisions or their daily observations after a load.
                    if (_pendingTeamTransition != null || _nativeTransferProbe != null
                        || _pendingPackage != null || _inventoryRestorePending) return;
                    continue;
                }
                if (state.SubmissionLastComparedDay < day
                    || reviewQuotes && DiplomacyV2Submission.HasOffer(state))
                    ProcessV2SubmissionOffer(coalition, relation, day);
            }
        }

        private void ProcessV2SubmissionOffer(CoalitionState coalition,
            RelationState relation, int day)
        {
            // Capture UI ownership before entering the native monitor. This
            // producer runs from the frame pump, so a busy engine is retried
            // during the same day rather than losing a pressure observation.
            int presentedDay;
            bool presented = _v2SubmissionPresentedDays.TryGetValue(coalition.CoalitionId,
                out presentedDay) && day > presentedDay
                && IsDiplomacyDialogPresented("submission:" + coalition.CoalitionId);
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease)) return;
            using (lease) ProcessV2SubmissionOfferUnderLease(coalition, relation, day, presented);
        }

        private void ProcessV2SubmissionOfferUnderLease(CoalitionState coalition,
            RelationState relation, int day, bool presented)
        {
            NormalizeV2ProudLegacyVassal(coalition, relation);
            DiplomacyV2RelationState state = relation.V2;
            if (state == null || state.SubmissionOfferAccepted) return;
            int player, lord;
            bool eligible = V2SubmissionStructurallyEligible(coalition, relation, day, out player, out lord);
            bool open = DiplomacyV2Submission.HasOffer(state);
            if (open && !ReviewV2SubmissionOffer(coalition, relation, day)) return;
            if (open) AskV2SubmissionOffer(coalition, relation);
            if (day <= state.SubmissionLastComparedDay) return;
            int band = 0;
            if (eligible && !TryV2SubmissionPressureBand(player, lord, day, out band)) return;
            bool ready = DiplomacyV2Submission.ObservePressure(state, day, lord, band, eligible);
            if (open)
            {
                DiplomacyV2Submission.DiplomacyV2OfferDayResult ablauf =
                    DiplomacyV2Submission.ElapseResponseDay(state, day, presented,
                        _mapFingerprint, coalition.CoalitionId);
                if (ablauf == DiplomacyV2Submission.DiplomacyV2OfferDayResult.Improved)
                {
                    // Der Druck hielt ueber die Frist hinaus an: der Fuerst
                    // bessert nach. Der alte Dialog zeigt den alten Betrag,
                    // also wird er verworfen und neu vorgelegt.
                    _v2SubmissionPresentedDays.Remove(coalition.CoalitionId);
                    CancelDiplomacyDialog("submission:" + coalition.CoalitionId);
                    _v2SubmissionVerifiedQuotes[coalition.CoalitionId] = state.SubmissionOfferCreatedDay;
                    Log("vassalage", "coalition=" + coalition.CoalitionId
                        + "|status=submission_improved|tribute_gold="
                        + state.SubmissionOfferTributeAmount.ToString(CultureInfo.InvariantCulture)
                        + "|pressure_days=" + state.SubmissionPressureDays.ToString(
                            CultureInfo.InvariantCulture));
                    ShowMessage(Text(
                        "Der anhaltende Druck wirkt: das Unterwerfungsangebot wurde nachgebessert.",
                        "The sustained pressure is working: the submission offer has been improved."));
                    AskV2SubmissionOffer(coalition, relation);
                }
                else if (ablauf == DiplomacyV2Submission.DiplomacyV2OfferDayResult.Withdrawn)
                {
                    _v2SubmissionPresentedDays.Remove(coalition.CoalitionId);
                    _v2SubmissionVerifiedQuotes.Remove(coalition.CoalitionId);
                    CancelDiplomacyDialog("submission:" + coalition.CoalitionId);
                    Log("vassalage", "coalition=" + coalition.CoalitionId + "|status=submission_timed_out");
                    ShowMessage(Text(
                        "Das Unterwerfungsangebot ist vom Tisch. Der Krieg geht weiter.",
                        "The submission offer is off the table. The war continues."));
                }
                return;
            }
            if (!ready || DiplomacyV2Submission.TryAttempt(relation, player, lord,
                    V2TributeQuoteForPlayer(player), day,
                    _mapFingerprint, DiplomacyV2SubmissionOfferOrigin.AiOffer, band)
                    != DiplomacyV2SubmissionAttemptResult.Offered) return;
            PresentV2NewSubmissionOffer(coalition, relation);
        }

        private void PresentV2NewSubmissionOffer(CoalitionState coalition, RelationState relation)
        {
            DiplomacyV2RelationState state = relation.V2;
            _v2SubmissionVerifiedQuotes[coalition.CoalitionId] = state.SubmissionOfferCreatedDay;
            int player = state.SubmissionOfferPlayerId, lord = state.SubmissionOfferLordId;
            int day = state.SubmissionOfferCreatedDay;
            Log("vassalage", "coalition=" + coalition.CoalitionId
                + "|status=submission_offered|player=" + player.ToString(CultureInfo.InvariantCulture)
                + "|lord=" + lord.ToString(CultureInfo.InvariantCulture)
                + "|day=" + day.ToString(CultureInfo.InvariantCulture)
                + "|origin=" + state.SubmissionOfferOrigin.ToString());
            OnDiplomacyPresentationCommitted(DiplomacyPresentationEvent.Create(
                DiplomacyPresentationEventKind.SubmissionOffered, _sessionGeneration,
                day, player, lord, _localPlayer, coalition.CoalitionId,
                state.SubmissionOfferOrigin == DiplomacyV2SubmissionOfferOrigin.PlayerDemand
                    ? "player_demand" : "military_pressure",
                new DiplomacyPresentationReference("submission_offer", startedDay: day,
                    goodId: DiplomacyV2Tribute.GoldGoodId, amount: state.SubmissionOfferTributeAmount,
                    intervalDays: DiplomacyV2Tribute.DefaultIntervalDays, otherPlayerId: _localPlayer)));
            AskV2SubmissionOffer(coalition, relation);
        }

        private bool V2SubmissionDecisionCurrent(string coalitionId, long generation,
            string fingerprint, int player, int lord, int amount, int createdDay,
            DiplomacyV2SubmissionOfferOrigin origin, out RelationState relation)
        {
            relation = null;
            CoalitionState coalition;
            // Popup validity runs on the UI thread WITHOUT the native monitor.
            // Only read managed quote/session data here. The command pump checks
            // live identity, survival and team eligibility under the monitor.
            return _mapActive && !_mapDisabled && generation == _sessionGeneration
                && string.Equals(fingerprint, _mapFingerprint, StringComparison.Ordinal)
                && _relations.TryGetValue(coalitionId, out relation)
                && _coalitions.TryGetValue(coalitionId, out coalition)
                && DiplomacyV2Submission.HasOffer(relation.V2)
                && !relation.V2.SubmissionOfferAccepted
                && relation.V2.SubmissionOfferPlayerId == player
                && relation.V2.SubmissionOfferLordId == lord
                && relation.V2.SubmissionOfferTributeAmount == amount
                && relation.V2.SubmissionOfferCreatedDay == createdDay
                && relation.V2.SubmissionOfferOrigin == origin
                && relation.V2.SubmissionResponseDaysRemaining > 0
                && !relation.Allied && !coalition.Allied
                && coalition.MemberPlayerIds != null && coalition.MemberPlayerIds.Length == 1
                && coalition.MemberPlayerIds[0] == player;
        }

        private void AskV2SubmissionOffer(CoalitionState coalition, RelationState relation)
        {
            DiplomacyV2RelationState state = relation.V2;
            int verifiedQuote;
            if (!DiplomacyV2Submission.HasOffer(state) || state.SubmissionOfferAccepted
                || state.SubmissionAcceptancePending
                || state.SubmissionPressureRuleVersion != DiplomacyV2Submission.CurrentPressureRuleVersion
                || !_v2SubmissionVerifiedQuotes.TryGetValue(coalition.CoalitionId, out verifiedQuote)
                || verifiedQuote != state.SubmissionOfferCreatedDay) return;
            string id = coalition.CoalitionId;
            long generation = _sessionGeneration;
            string fingerprint = _mapFingerprint;
            int player = state.SubmissionOfferPlayerId, lord = state.SubmissionOfferLordId;
            int amount = state.SubmissionOfferTributeAmount;
            int createdDay = state.SubmissionOfferCreatedDay;
            DiplomacyV2SubmissionOfferOrigin origin = state.SubmissionOfferOrigin;
            ShowConfirmation(V2PlayerName(player) + " · " + Text("Unterwerfungsangebot", "Offer of submission"),
                delegate { AnswerV2SubmissionOffer(id, generation, fingerprint, player, lord, amount, createdDay, origin, true); },
                delegate { AnswerV2SubmissionOffer(id, generation, fingerprint, player, lord, amount, createdDay, origin, false); },
                (origin == DiplomacyV2SubmissionOfferOrigin.PlayerDemand
                    ? Text("Forderung angenommen.", "Demand accepted.")
                    : Text("Unterwerfung angeboten.", "Submission offered."))
                    + "\n" + Text("Bei Annahme: Vasall und Bündnis. Bei Ablehnung: weiterhin Krieg.",
                        "Accept: vassal and alliance. Refuse: war continues.")
                    + "\n" + V2FealtyTerms(amount)
                    + "\n" + string.Format(CultureInfo.InvariantCulture,
                        Text("Antwortfrist: {0} Spieltage.", "Response time: {0} game days."),
                        state.SubmissionResponseDaysRemaining),
                delegate
                {
                    if (!_v2SubmissionPresentedDays.ContainsKey(id))
                        _v2SubmissionPresentedDays[id] = Math.Max(0, _lastProcessedDay);
                }, "submission:" + id,
                delegate
                {
                    RelationState current;
                    return V2SubmissionDecisionCurrent(id, generation, fingerprint, player, lord, amount, createdDay, origin, out current);
                });
        }

        private void AnswerV2SubmissionOffer(string id, long generation, string fingerprint,
            int player, int lord, int amount, int createdDay, DiplomacyV2SubmissionOfferOrigin origin,
            bool accepted)
        {
            lock (_gate)
            {
                RelationState relation;
                if (!V2SubmissionDecisionCurrent(id, generation, fingerprint, player, lord, amount, createdDay, origin, out relation)) return;
                if (!accepted)
                {
                    DiplomacyV2Submission.CloseOffer(relation.V2, Math.Max(0, _lastProcessedDay), true);
                    _v2SubmissionPresentedDays.Remove(id);
                    Log("vassalage", "coalition=" + id + "|status=submission_rejected");
                    OnDiplomacyPresentationCommitted(DiplomacyPresentationEvent.Create(
                        DiplomacyPresentationEventKind.SubmissionDeclined, _sessionGeneration,
                        Math.Max(0, _lastProcessedDay), player, lord, _localPlayer, id, "local_rejection",
                        new DiplomacyPresentationReference("submission_offer",
                            goodId: DiplomacyV2Tribute.GoldGoodId, amount: amount,
                            intervalDays: DiplomacyV2Tribute.DefaultIntervalDays, otherPlayerId: _localPlayer)));
                    return;
                }
                if (!DiplomacyV2Submission.TryQueueAcceptance(relation)) return;
                QueueV2FealtyCommand(null, player, delegate
                {
                    RelationState current;
                    if (!V2SubmissionDecisionCurrent(id, generation, fingerprint, player, lord,
                            amount, createdDay, origin, out current)) return;
                    if (!ReviewV2SubmissionOffer(_coalitions[id], current, Math.Max(0, _lastProcessedDay))) return;
                    if (!DiplomacyV2Submission.TryAcceptOffer(current)) return;
                    try { FormAlliance(_coalitions[id], "submission_offer"); }
                    finally { DiplomacyV2Submission.RestoreUncommittedOffer(current, _pendingTeamTransition); }
                }, "submission:" + id, delegate
                {
                    RelationState current;
                    return V2SubmissionDecisionCurrent(id, generation, fingerprint, player, lord,
                        amount, createdDay, origin, out current);
                });
            }
        }

        private bool CommitV2PendingSubmission(CoalitionState coalition, RelationState relation, int day)
        {
            DiplomacyV2RelationState state = relation.V2;
            if (!DiplomacyV2Submission.HasOffer(state) || !state.SubmissionOfferAccepted) return false;
            int player = state.SubmissionOfferPlayerId, amount = state.SubmissionOfferTributeAmount;
            if (!DiplomacyV2Vassalage.Establish(relation, player, _localPlayer, _localPlayer, day)
                || !DiplomacyV2Tribute.Arrange(state, DiplomacyV2Tribute.GoldGoodId,
                    amount, DiplomacyV2Tribute.DefaultIntervalDays, day))
                throw new InvalidOperationException("accepted submission could not establish its quoted contract");
            _v2SubmissionPresentedDays.Remove(coalition.CoalitionId);
            PublishCombatProtectionSnapshot();
            Log("vassalage", "coalition=" + coalition.CoalitionId
                + "|status=submission_accepted|vassal=" + player.ToString(CultureInfo.InvariantCulture)
                + "|tribute_gold=" + amount.ToString(CultureInfo.InvariantCulture));
            ShowMessage(Text(
                "Euer neuer Verbündeter hat Euch Lehnstreue geschworen und entrichtet Euch fortan Tribut.",
                "Your new ally has sworn fealty to you and will pay you tribute from now on."));
            return true;
        }

        private void NormalizeV2ProudLegacyVassal(CoalitionState coalition, RelationState relation)
        {
            // A saved tribute journal must settle against its original contract
            // before that contract is converted. A later ordinary day retries.
            if (_inventoryRestorePending || _nativeTransferProbe != null
                || _pendingTeamTransition != null) return;
            if (!relation.Allied || !DiplomacyV2Vassalage.IsActive(relation.V2)) return;
            int player = DiplomacyV2Vassalage.VassalOf(relation.V2), lord;
            if (player == _localPlayer || !TryV2LordIdentity(player, out lord)
                || !DiplomacyV2Submission.NeverSubmits(lord)) return;
            DiplomacyV2Vassalage.ClearWithoutRelease(relation.V2);
            DiplomacyV2StateMachine.ResumeAllianceMaintenance(relation.V2, Math.Max(0, _lastProcessedDay));
            Log("vassalage", "coalition=" + coalition.CoalitionId
                + "|status=legacy_role_normalized|reason=lord_never_submits|lord="
                + lord.ToString(CultureInfo.InvariantCulture));
            ShowMessage(Text(
                "Eine frühere Lehnspflicht widersprach dem Wesen dieses Herrschers. Ihr seid nun gleichrangige Verbündete; Tribut und Lehnspflichten enden ohne Vertragsbruch.",
                "An earlier fealty contract contradicted this ruler's character. You are now equal allies; tribute and fealty end without a treaty breach."));
        }

        private string V2FealtyTerms(int amount)
        {
            return string.Format(CultureInfo.InvariantCulture, Text(
                "Tribut: {0} {1} in {2} Tagen; danach je Zeitraum an die Wirtschaft angepasst. Bei Goldmangel werden gleichwertige Waren angenommen.",
                "Tribute: {0} {1} in {2} days; adjusted to the economy each following period. Equivalent goods are accepted if gold runs short."),
                amount, GoodName(DiplomacyV2Tribute.GoldGoodId, amount),
                DiplomacyV2Tribute.DefaultIntervalDays);
        }

        private string V2TributeReminder(DiplomacyV2RelationState state, bool localPays)
        {
            return string.Format(CultureInfo.InvariantCulture, Text(
                "Tribut bald fällig: {0} {1} in {2} Tagen ({3}).",
                "Tribute due soon: {0} {1} in {2} days ({3})."),
                state.TributeAmount, GoodName(state.TributeGoodId, state.TributeAmount),
                DiplomacyV2Tribute.WarningLeadDays,
                localPays ? Text("Ihr zahlt", "You pay") : Text("Ihr erhaltet", "You receive"));
        }

        private string V2TributeGraceText(DiplomacyV2RelationState state, int day)
        {
            if (state.TributeMissedCycles > 0)
                return string.Format(CultureInfo.InvariantCulture, Text(
                    "Tribut im Rückstand: {0} {1}. Die Zahlung wird täglich erneut versucht; das Bündnis bleibt bestehen.",
                    "Tribute in arrears: {0} {1}. Payment is retried daily; the alliance remains in force."),
                    state.TributeAmount, GoodName(state.TributeGoodId, state.TributeAmount));
            return string.Format(CultureInfo.InvariantCulture, Text(
                "Tribut noch offen: {0} {1}. Die Zahlung wird täglich erneut versucht; noch {2} Tage Schonfrist.",
                "Tribute remains unpaid: {0} {1}. Payment is retried daily; {2} days of grace remain."),
                state.TributeAmount, GoodName(state.TributeGoodId, state.TributeAmount),
                DiplomacyV2Tribute.DaysUntilGraceDeadline(state, day));
        }

        private bool V2SubjugationCurrent(string coalitionId, long generation,
            string fingerprint, int overlord, int amount, int offerDay)
        {
            CoalitionState coalition;
            RelationState relation;
            return _mapActive && !_mapDisabled && generation == _sessionGeneration
                && string.Equals(fingerprint, _mapFingerprint, StringComparison.Ordinal)
                && _coalitions.TryGetValue(coalitionId, out coalition)
                && _relations.TryGetValue(coalitionId, out relation)
                && relation.Allied && coalition.Allied && relation.V2 != null
                && !DiplomacyV2Vassalage.IsActive(relation.V2)
                && (relation.Demand == null
                    || relation.Demand.V2Purpose != DiplomacyV2DemandPurpose.Ultimatum)
                && coalition.MemberPlayerIds.Contains(overlord)
                && relation.V2.PendingVassalOverlordPlayerId == overlord
                && relation.V2.PendingVassalTributeAmount == amount
                && relation.V2.PendingVassalOfferDay == offerDay;
        }

        private static void ClearV2PendingSubjugation(DiplomacyV2RelationState state)
        {
            DiplomacyV2Vassalage.ClearPendingOffer(state);
        }

        private void DeferV2TreatyStandoffRetry()
        {
            _v2TreatyStandoffDegraded = true;
            _v2StandoffRetryTick = unchecked(ReadSimulationTick()
                + V2IncursionScanIntervalTicks * 2);
            _v2StandoffFaultsPending = Math.Min(1000, _v2StandoffFaultsPending + 1);
        }

        private readonly Dictionary<string, int> _v2TributeTechnicalFaults =
            new Dictionary<string, int>(StringComparer.Ordinal);

        private void NoteV2TributeTechnicalFailure(string coalitionId, string reason)
        {
            int count;
            _v2TributeTechnicalFaults.TryGetValue(coalitionId, out count);
            count = Math.Min(4, count + 1);
            _v2TributeTechnicalFaults[coalitionId] = count;
            if (count <= 3)
            {
                Log("tribute", "coalition=" + Safe(coalitionId)
                    + "|status=deferred|reason=" + Safe(reason)
                    + "|faults=" + count.ToString(CultureInfo.InvariantCulture));
            }
        }

        private bool V2VassalDecisionCurrent(string coalitionId, long generation,
            string fingerprint, out RelationState relation)
        {
            relation = null;
            CoalitionState coalition;
            return _mapActive && !_mapDisabled
                && generation == _sessionGeneration
                && string.Equals(fingerprint, _mapFingerprint, StringComparison.Ordinal)
                && _coalitions.TryGetValue(coalitionId, out coalition)
                && _relations.TryGetValue(coalitionId, out relation)
                && relation.Allied && coalition.Allied
                && DiplomacyV2Vassalage.IsActive(relation.V2);
        }

        private static bool V2VassalContractMatches(DiplomacyV2RelationState state,
            int vassal, int overlord, int sinceDay, int releaseCount)
        {
            return state != null && state.VassalPlayerId == vassal
                && state.VassalOverlordPlayerId == overlord && state.VassalSinceDay == sinceDay
                && state.VassalReleases == releaseCount;
        }

        private bool StageV2VassalAction(string id, long generation, string fingerprint,
            DiplomacyV2VassalActionKind kind, int vassal, int overlord,
            int sinceDay, int requestDay, int amount, int releaseCount)
        {
            lock (_gate)
            {
                RelationState relation;
                if (DiplomacyV2VassalActions.IsSubjugation(kind))
                {
                    if (vassal != _localPlayer || !V2SubjugationCurrent(id, generation,
                            fingerprint, overlord, amount, requestDay)) return false;
                    relation = _relations[id];
                    if (relation.V2.VassalReleases != releaseCount) return false;
                }
                else
                {
                    if (!V2VassalDecisionCurrent(id, generation, fingerprint, out relation)
                        || !V2VassalContractMatches(relation.V2, vassal, overlord, sinceDay, releaseCount)) return false;
                    if (DiplomacyV2VassalActions.IsEquality(kind)
                        && relation.V2.VassalEqualityRequestedDay != requestDay) return false;
                    if (kind == DiplomacyV2VassalActionKind.ClaimEquality
                        && !DiplomacyV2Vassalage.CanRequestEquality(relation.V2, Math.Max(0, _lastProcessedDay))) return false;
                }
                return DiplomacyV2VassalActions.Stage(relation, _localPlayer, kind);
            }
        }

        private void PumpV2VassalActions()
        {
            if (!_mapActive || _mapDisabled || _mapBootstrapPending
                || _inventoryRestorePending || _nativeTransferProbe != null
                || _pendingPackage != null || _pendingTeamTransition != null) return;
            NormalizeV2VassalDemands();
            foreach (string id in _relations.Keys.OrderBy(value => value, StringComparer.Ordinal).ToArray())
            {
                RelationState relation = _relations[id];
                DiplomacyV2RelationState state = relation.V2;
                if (!DiplomacyV2VassalActions.HasPending(state)) continue;
                if (!DiplomacyV2VassalActions.Matches(relation, _localPlayer))
                { DiplomacyV2VassalActions.Clear(state); continue; }
                IDisposable lease;
                if (!TryEnterNativeInventorySection(out lease)) return;
                using (lease)
                {
                    DiplomacyManagedStateMemento before = null;
                    try
                    {
                    if (!IsAlivePlayer(state.PendingVassalActionVassalPlayerId)
                        || !IsAlivePlayer(state.PendingVassalActionOverlordPlayerId))
                    { DiplomacyV2VassalActions.Clear(state); continue; }
                    var kind = state.PendingVassalAction;
                    int day = Math.Max(0, _lastProcessedDay);
                    if (kind == DiplomacyV2VassalActionKind.ClaimEquality
                        && !DiplomacyV2Vassalage.CanRequestEquality(state, day))
                    { DiplomacyV2VassalActions.Clear(state); continue; }
                    before = CaptureManagedStateMemento();
                        int vassal = state.PendingVassalActionVassalPlayerId;
                        int overlord = state.PendingVassalActionOverlordPlayerId;
                        int amount = state.PendingVassalActionQuoteAmount;
                        DiplomacyV2VassalActions.Clear(state);
                        if (kind == DiplomacyV2VassalActionKind.AcceptSubjugation)
                            EstablishV2Vassalage(_coalitions[id], relation, vassal, overlord,
                                day, "alliance_local_vassal", amount);
                        else if (kind == DiplomacyV2VassalActionKind.RefuseSubjugation)
                        {
                            ClearV2PendingSubjugation(state);
                            Log("vassalage", "coalition=" + id + "|status=subjugation_declined");
                            ShowMessage(Text("Ihr habt die Lehnstreue verweigert. Es bleibt ein gewöhnliches Bündnis.",
                                "You refused fealty. It stays an ordinary alliance."));
                        }
                        else if (DiplomacyV2VassalActions.IsEquality(kind))
                            ExecuteV2EqualityDecision(_coalitions[id], relation, day,
                                kind == DiplomacyV2VassalActionKind.GrantEquality);
                        else ExecuteV2VassalRelease(id, relation,
                            kind == DiplomacyV2VassalActionKind.ClaimEquality,
                            vassal == _localPlayer ? overlord : vassal, day);
                    }
                    catch (Exception exception)
                    {
                        if (before != null) RestoreManagedStateMemento(before);
                        NoteV2TributeTechnicalFailure(id, "vassal_action_" + exception.GetType().Name);
                    }
                    finally { PublishCombatProtectionSnapshot(); }
                }
                // A refusal can queue a native break. Preserve that journal's
                // exclusivity before considering another answered contract.
                if (_pendingTeamTransition != null) return;
            }
        }

        private void ExecuteV2VassalRelease(string coalitionId, RelationState current,
            bool localVassal, int selectedPlayer, int day)
        {
            DiplomacyV2Tribute.Clear(current.V2);
            DiplomacyV2Vassalage.Release(current.V2);
            DiplomacyV2StateMachine.RecordVassalReleased(current.V2);
            DiplomacyV2StateMachine.ResumeAllianceMaintenance(current.V2, day);
            PublishCombatProtectionSnapshot();
            Log("vassalage", "coalition=" + coalitionId + "|status=equality_granted|actor="
                + (localVassal ? "local_vassal" : "local_overlord"));
            OnDiplomacyPresentationCommitted(DiplomacyPresentationEvent.Create(
                localVassal ? DiplomacyPresentationEventKind.EqualityGranted : DiplomacyPresentationEventKind.FealtyReleased,
                _sessionGeneration, day, selectedPlayer, null, _localPlayer, coalitionId,
                localVassal ? "local_vassal" : "local_overlord",
                new DiplomacyPresentationReference("fealty", otherPlayerId: _localPlayer)));
            ShowMessage(Text(
                "Ihr seid nun gleichberechtigte Verbündete. Lehnspflicht und Tribut enden; das Bündnis bleibt bestehen.",
                "You are now equal allies. Fealty and tribute end; the alliance remains intact."));
        }

        // Called after the restored map has become active. The FIFO re-presents
        // saved decisions without starting a second request or resetting its date.
        private void RestoreV2PendingDecisions()
        {
            foreach (CoalitionState coalition in _coalitions.Values.OrderBy(
                value => value.CoalitionId, StringComparer.Ordinal))
            {
                RelationState relation;
                if (_relations.TryGetValue(coalition.CoalitionId, out relation))
                {
                    NormalizeV2ProudLegacyVassal(coalition, relation);
                    if (DiplomacyV2Submission.HasOffer(relation.V2)
                        && !relation.V2.SubmissionOfferAccepted)
                        AskV2SubmissionOffer(coalition, relation);
                }
                if (_relations.TryGetValue(coalition.CoalitionId, out relation)
                    && relation.V2 != null && relation.V2.PendingVassalOverlordPlayerId > 0)
                {
                    AskV2Subjugation(coalition, relation,
                        relation.V2.PendingVassalOverlordPlayerId, relation.V2.PendingVassalOfferDay);
                }
                if (_relations.TryGetValue(coalition.CoalitionId, out relation)
                    && relation.Allied
                    && DiplomacyV2Vassalage.CoalitionIsVassal(relation.V2)
                    && DiplomacyV2Vassalage.EqualityRequestOpen(relation.V2))
                {
                    V2AskEqualityRequest(coalition, relation);
                }
            }
        }

        // Legacy saves may group ordinary allies with one named fealty endpoint.
        // Fealty belongs to those two players, never every member of the coalition.
        private bool V2IsFealtyCounterpart(DiplomacyV2RelationState state, int player)
        {
            return player >= 1 && player <= 8 && player != _localPlayer
                && DiplomacyV2Vassalage.IsActive(state)
                && ((DiplomacyV2Vassalage.OverlordOf(state) == _localPlayer
                        && DiplomacyV2Vassalage.VassalOf(state) == player)
                    || (DiplomacyV2Vassalage.VassalOf(state) == _localPlayer
                        && DiplomacyV2Vassalage.OverlordOf(state) == player));
        }

        private bool TryHandleV2VassalPrimary(int selectedPlayer)
        {
            string coalitionId;
            RelationState relation;
            if (!_playerCoalition.TryGetValue(selectedPlayer, out coalitionId)
                || !_relations.TryGetValue(coalitionId, out relation)
                || !relation.Allied
                || !V2IsFealtyCounterpart(relation.V2, selectedPlayer))
            {
                return false;
            }
            if (DiplomacyV2VassalActions.HasPending(relation.V2)) return true;
            bool localVassal = DiplomacyV2Vassalage.VassalOf(relation.V2) == _localPlayer;
            bool localOverlord = DiplomacyV2Vassalage.OverlordOf(relation.V2) == _localPlayer;
            if (!localVassal && !localOverlord)
            {
                return false;
            }
            int day = Math.Max(0, _lastProcessedDay);
            if (localVassal && !DiplomacyV2Vassalage.CanRequestEquality(relation.V2, day))
            {
                ShowMessage(V2VassalPrimaryHint(relation.V2));
                return true;
            }
            if (localOverlord && DiplomacyV2Vassalage.EqualityRequestOpen(relation.V2))
            {
                V2AskEqualityRequest(_coalitions[coalitionId], relation);
                return true;
            }
            long generation = _sessionGeneration;
            string fingerprint = _mapFingerprint;
            int vassal = relation.V2.VassalPlayerId, overlord = relation.V2.VassalOverlordPlayerId;
            int sinceDay = relation.V2.VassalSinceDay, releases = relation.V2.VassalReleases;
            ShowConfirmation(
                V2PlayerName(selectedPlayer) + " · " + (localVassal ? Text("Gleichstellung fordern", "Request equal standing")
                    : Text("Vasallen freilassen", "Release vassal")),
                delegate
                {
                    StageV2VassalAction(coalitionId, generation, fingerprint,
                        localVassal ? DiplomacyV2VassalActionKind.ClaimEquality : DiplomacyV2VassalActionKind.Release,
                        vassal, overlord, sinceDay, -1, 0, releases);
                },
                delegate { },
                localVassal ? Text(
                    "Ihr habt Euch lange genug bewährt und seid dauerhaft stärker als Euer Lehnsherr. Fordert Ihr Gleichstellung, enden Lehnspflicht und Tribut bei fortbestehendem Bündnis.",
                    "You have served long enough and maintained a stronger army than your overlord. Claiming equal standing ends fealty and tribute while preserving the alliance.")
                    : Text(
                    "Wollt Ihr Euren Vasallen freiwillig freilassen? Die Tributzahlungen enden; Ihr bleibt Verbündete.",
                    "Will you voluntarily release your vassal? Tribute payments end; you remain allies."),
                null, "vassal-release:" + coalitionId,
                delegate
                {
                    RelationState current;
                    return V2VassalDecisionCurrent(coalitionId, generation, fingerprint, out current)
                        && !DiplomacyV2VassalActions.HasPending(current.V2)
                        && V2VassalContractMatches(current.V2, vassal, overlord, sinceDay, releases)
                        && V2IsFealtyCounterpart(current.V2, selectedPlayer)
                        && (localVassal
                            ? DiplomacyV2Vassalage.VassalOf(current.V2) == _localPlayer
                            : DiplomacyV2Vassalage.OverlordOf(current.V2) == _localPlayer);
                });
            return true;
        }

        private string V2VassalPrimaryHint(DiplomacyV2RelationState state)
        {
            if (DiplomacyV2Vassalage.VassalOf(state) == _localPlayer)
            {
                return Text("Gleichstellung: mindestens ", "Equal standing: at least ")
                    + DiplomacyV2Vassalage.MinimumTermDays.ToString(CultureInfo.InvariantCulture)
                    + Text(" Tage Lehnstreue und ", " days of fealty and ")
                    + DiplomacyV2Vassalage.RebellionEdgeDays.ToString(CultureInfo.InvariantCulture)
                    + Text(" Tage in Folge militärisch überlegen.", " consecutive days of military superiority.");
            }
            return Text("Vasallen freilassen und das Bündnis bewahren.",
                "Release your vassal while preserving the alliance.");
        }

        private void RefreshV2ExtraFealtyAction(object panel, RelationState relation)
        {
            object button = FindElement(panel, "CrusaderDiplomacyV2Fealty");
            object label = FindElement(panel, "CrusaderDiplomacyV2FealtyLabel");
            DiplomacyV2RelationState state = relation.V2;
            bool counterpart = V2IsFealtyCounterpart(state, SelectedPlayer(panel));
            bool localVassal = counterpart && DiplomacyV2Vassalage.VassalOf(state) == _localPlayer;
            bool localOverlord = counterpart && DiplomacyV2Vassalage.OverlordOf(state) == _localPlayer;
            // Submission is an action between enemies. Fealty names an existing
            // contract only; equal allies have no fictional fealty to manage.
            bool show = state != null && (counterpart || !relation.Allied
                && !DiplomacyV2Vassalage.IsActive(state));
            SetVisibilityIfPresent(button, show);
            SetVisibilityIfPresent(label, show);
            SetVisibilityIfPresent(FindElement(panel, "CrusaderDiplomacyV2Agreement"), true);
            if (!show || button == null || label == null) return;
            bool accepted = state.SubmissionAcceptancePending || state.SubmissionOfferAccepted;
            bool pending = accepted || DiplomacyV2VassalActions.HasPending(state);
            // PrimaryLordId is an appearance/profile identifier, not a verified
            // GetAILord identity. The queued action checks that native identity
            // under the engine lease before any offer can be created.
            bool equalityReady = !localVassal || DiplomacyV2Vassalage.CanRequestEquality(state, Math.Max(0, _lastProcessedDay));
            bool enabled = !pending && equalityReady;
            SetProperty(button, "IsEnabled", enabled);
            SetProperty(button, "ToolTip", counterpart
                ? V2VassalPrimaryHint(state)
                : accepted ? Text("Unterwerfung bestätigt", "Submission accepted")
                : DiplomacyV2Submission.HasOffer(state)
                    ? Text("Unterwerfungsangebot prüfen", "Review submission offer")
                    : Text("Unterwerfung fordern", "Demand submission"));
            SetProperty(label, "Text", localVassal
                ? Text("Gleichstellung fordern", "Request equal standing")
                : localOverlord ? Text("Vasallen freilassen", "Release vassal")
                : accepted ? Text("Unterwerfung bestätigt", "Submission accepted")
                : DiplomacyV2Submission.HasOffer(state)
                    ? Text("Angebot prüfen", "Review offer")
                    : Text("Unterwerfung fordern", "Demand submission"));
            SetNumericProperty(label, "Opacity", enabled ? 1.0 : 0.48);
        }

        private string V2VassalRoleText(DiplomacyV2RelationState state)
        {
            if (!DiplomacyV2Vassalage.IsActive(state)) return string.Empty;
            if (DiplomacyV2Vassalage.VassalOf(state) == _localPlayer)
                return Text("Euer Lehnsherr", "Your overlord");
            if (DiplomacyV2Vassalage.OverlordOf(state) == _localPlayer)
                return Text("Euer Vasall", "Your vassal");
            return Text("Lehnsverhältnis", "Fealty");
        }
    }
}
#endif
