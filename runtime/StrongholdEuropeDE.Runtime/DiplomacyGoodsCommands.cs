using System;
using System.ComponentModel;
using System.Threading;
using CrusaderDE;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        // COPY MainViewModel.AlliesPanelVisible notifies PropertyChanged on every
        // visibility transition (27564-27577). Escape and right-click bypass the
        // button callback, so polling visibility alone misses hide -> reopen.
        // The notification only arbitrates waiting/cancelled/claimed; it never
        // takes _gate or calls a native API. A claimed transaction owns its own
        // journal and no longer depends on the panel remaining open.
        private sealed class DiplomacyPanelCommandLifetime : IDisposable
        {
            private readonly MainViewModel _viewModel;
            private int _state; // 0 waiting, 1 cancelled, 2 claimed
            private int _subscribed;

            internal DiplomacyPanelCommandLifetime(MainViewModel viewModel)
            {
                _viewModel = viewModel;
                if (viewModel == null) { _state = 1; return; }
                Volatile.Write(ref _subscribed, 1);
                viewModel.PropertyChanged += OnPropertyChanged;
                ObserveVisibility();
            }

            internal bool Cancelled
            {
                get { ObserveVisibility(); return Volatile.Read(ref _state) == 1; }
            }

            internal bool TryClaim()
            {
                if (Cancelled || Interlocked.CompareExchange(ref _state, 2, 0) != 0)
                    return false;
                Detach();
                return true;
            }

            private void OnPropertyChanged(object sender, PropertyChangedEventArgs args)
            {
                if (ReferenceEquals(sender, _viewModel)
                    && (args == null || string.IsNullOrEmpty(args.PropertyName)
                        || args.PropertyName == "AlliesPanelVisible"))
                    ObserveVisibility();
            }

            private void ObserveVisibility()
            {
                if (Volatile.Read(ref _state) == 0
                    && (_viewModel == null
                        || !ReferenceEquals(_viewModel, MainViewModel.Instance)
                        || !_viewModel.AlliesPanelVisible))
                    Dispose();
            }

            private void Detach()
            {
                if (Interlocked.Exchange(ref _subscribed, 0) != 0)
                    _viewModel.PropertyChanged -= OnPropertyChanged;
            }

            public void Dispose()
            {
                Interlocked.CompareExchange(ref _state, 1, 0);
                Detach();
            }
        }

        // A confirmed click is not yet an inventory transaction. Keep its exact
        // operands until the engine can accept it; only then does the existing
        // persisted transfer journal take ownership. Never replay a UI click or
        // read a later panel selection to reconstruct the command (08.09.2026).
        private sealed class PendingGoodsCommand
        {
            internal readonly object Panel;
            internal readonly long Generation;
            internal readonly string Fingerprint;
            internal readonly int LocalPlayer, TargetPlayer, SelectionPlayer, GoodId, Amount;
            internal readonly bool Allied;
            internal readonly RelationState Relation;
            internal readonly GoodsDemand Demand, DemandQuote;
            internal readonly DiplomacyPanelCommandLifetime Lifetime;

            internal PendingGoodsCommand(object panel, long generation, string fingerprint,
                int localPlayer, int targetPlayer, int selectionPlayer, int goodId, int amount,
                RelationState relation, GoodsDemand demand)
            {
                Panel = panel; Generation = generation; Fingerprint = fingerprint;
                LocalPlayer = localPlayer; TargetPlayer = targetPlayer;
                SelectionPlayer = selectionPlayer;
                GoodId = goodId; Amount = amount; Relation = relation;
                Allied = relation.Allied; Demand = demand; DemandQuote = CopyDemand(demand);
                Lifetime = new DiplomacyPanelCommandLifetime(MainViewModel.Instance);
            }
        }

        private PendingGoodsCommand _pendingGoodsCommand;
        private bool HasPendingGoodsCommand { get { return _pendingGoodsCommand != null; } }

        private string PendingGoodsCommandStatusText()
        {
            return Text("Die Sendung wartet auf das Spiel. Zurück oder Schließen bricht sie ab.",
                "The transfer is waiting for the game. Back or Close cancels it.");
        }

        private void CancelPendingGoodsCommand(string reason)
        {
            _pendingGoodsTarget = 0;
            if (_pendingGoodsCommand == null) return;
            _pendingGoodsCommand.Lifetime.Dispose();
            _pendingGoodsCommand = null;
            Log("transfer", "status=command_cancelled|reason=" + Safe(reason));
        }

        private void QueueGoodsCommand(object panel, int target, int good, int amount,
            GoodsDemand demand = null)
        {
            // Repeated clicks cannot replace an accepted quote or add a second
            // debit. Back/Exit/selection change explicitly withdraw it instead.
            if (_pendingGoodsCommand != null) { PresentPendingGoodsCommand(); return; }
            string coalitionId;
            RelationState relation;
            if (!_playerCoalition.TryGetValue(target, out coalitionId)
                || !_relations.TryGetValue(coalitionId, out relation)) return;
            int selectionPlayer = SelectedPlayer(panel);
            if (demand == null && selectionPlayer != target)
            { CancelPendingGoodsCommand("stale_goods_selection"); return; }
            _pendingGoodsCommand = new PendingGoodsCommand(panel, _sessionGeneration,
                _mapFingerprint, _localPlayer, target, selectionPlayer, good, amount, relation, demand);
            Log("transfer", "status=command_queued|target=" + target);
            PumpPendingGoodsCommand();
        }

        private static bool SameGoodsDemandQuote(GoodsDemand current, GoodsDemand quote)
        {
            if (current == null || quote == null || current.Complete
                || current.IssuedDay != quote.IssuedDay || current.ExpiresDay != quote.ExpiresDay
                || current.IsUltimatum != quote.IsUltimatum
                || current.Items == null || quote.Items == null
                || current.Items.Length != quote.Items.Length) return false;
#if DIPLOMACY_V2
            if (current.V2Purpose != quote.V2Purpose || current.V2Urgency != quote.V2Urgency) return false;
#endif
            for (int index = 0; index < current.Items.Length; index++)
            {
                DemandItem left = current.Items[index], right = quote.Items[index];
                if (left == null || right == null || left.GoodId != right.GoodId
                    || left.UnitValue != right.UnitValue || left.RequiredAmount != right.RequiredAmount
                    || left.DeliveredAmount != right.DeliveredAmount) return false;
            }
            return true;
        }

        private bool IsGoodsCommandSelectionCurrent(PendingGoodsCommand command)
        {
            try
            {
                return !command.Lifetime.Cancelled
                    && ReferenceEquals(command.Panel, CurrentAlliesPanel())
                    // The overview can submit its explicitly selected ally
                    // without moving the native portrait selection. Bind both
                    // identities separately; a later selection still cancels.
                    && SelectedPlayer(command.Panel) == command.SelectionPlayer;
            }
            catch (Exception exception)
            {
                DegradeUiRefresh("goods_command_selection", command.Panel, exception);
                return false;
            }
        }

        private void PumpPendingGoodsCommand()
        {
            PendingGoodsCommand command = _pendingGoodsCommand;
            if (command == null) return;
            if (command.Lifetime.Cancelled)
            {
                CancelPendingGoodsCommand("panel_closed");
                return;
            }
            string coalitionId;
            RelationState relation;
            if (!_mapActive || _mapDisabled || _mapBootstrapPending
                || command.Generation != _sessionGeneration
                || !string.Equals(command.Fingerprint, _mapFingerprint, StringComparison.Ordinal)
                || command.LocalPlayer != _localPlayer)
            {
                // Explicit navigation and a replaced map/panel are silent.
                CancelPendingGoodsCommand("selection_or_session_changed");
                return;
            }
            if (!IsGoodsCommandSelectionCurrent(command))
            {
#if DIPLOMACY_V2
                // Explicit selection buttons already cancelled the command.
                // A still-open same panel changing its roster automatically
                // (for example after defeat) must not silently discard work.
                if (!command.Lifetime.Cancelled && ReferenceEquals(command.Panel, CurrentAlliesPanel()))
                    RecordV2GoodsOutcome(command.TargetPlayer,
                        _visiblePlayers.Contains(command.TargetPlayer) ? "reconfirm" : "party_gone", true);
#endif
                CancelPendingGoodsCommand("selection_or_session_changed");
                return;
            }
            if (!_playerCoalition.TryGetValue(command.TargetPlayer, out coalitionId)
                || !_relations.TryGetValue(coalitionId, out relation)
                || !ReferenceEquals(command.Relation, relation)
                || command.Allied != relation.Allied
                || (command.Demand != null && (!ReferenceEquals(command.Demand, relation.Demand)
                    || !SameGoodsDemandQuote(relation.Demand, command.DemandQuote))))
            {
#if DIPLOMACY_V2
                RecordV2GoodsCommandCancellation(command);
#endif
                CancelPendingGoodsCommand("selection_or_quote_changed");
#if DIPLOMACY_V2
                PresentV2GoodsCommandOutcome(command);
#endif
                return;
            }
            if (_inventoryRestorePending || _nativeTransferProbe != null
                || _pendingPackage != null || _pendingTeamTransition != null)
            { PresentPendingGoodsCommand(); return; }

            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease))
            { PresentPendingGoodsCommand(); return; }
            bool claimed = false;
            bool partyGone = false;
            try
            {
                using (lease)
                {
                    if (!command.Lifetime.TryClaim())
                    {
                        CancelPendingGoodsCommand("panel_closed");
                        return;
                    }
                    claimed = true;
                    // Claim exactly once, before any native write. Failure after
                    // this point belongs to the normal recovery journal, not to
                    // the UI retry mechanism.
                    _pendingGoodsCommand = null;
                    _pendingGoodsTarget = 0;
                    if (!IsAlivePlayer(command.LocalPlayer) || !IsAlivePlayer(command.TargetPlayer))
                    {
#if DIPLOMACY_V2
                        partyGone = true;
                        RecordV2GoodsOutcome(command.TargetPlayer, "party_gone", true);
#endif
                        Log("transfer", "status=command_cancelled|reason=party_gone");
                        return;
                    }
#if DIPLOMACY_V2
                    if (command.Demand != null)
                    {
                        // One outer lease spans the existing separate stock
                        // check and package execution; nested leases are reentrant.
                        FulfillV2DemandPackage(command.TargetPlayer);
                        return;
                    }
#endif
                    if (command.Allied)
                    {
                        if (StartAlliedNativeTransferProbe(command.TargetPlayer, command.GoodId, command.Amount))
                            EngineInterface.GameAction(Enums.GameActionCommand.Ally_SendGoods,
                                command.TargetPlayer, command.GoodId, command.Amount);
                    }
                    else StartTransfer(command.TargetPlayer, command.GoodId, command.Amount);
                }
            }
            finally
            {
                // Native UI methods must run after the monitor is released.
                try
                {
                    if (claimed && CanPresentDiplomacyUi
                        && ReferenceEquals(command.Panel, CurrentAlliesPanel()))
                    {
                        if (command.Demand == null && !partyGone)
                            _buttonTarget.Invoke(command.Panel, new object[] { "Exit" });
                        else RefreshVanillaDiplomacyUi(command.Panel);
#if DIPLOMACY_V2
                        if (partyGone) PresentV2GoodsCommandOutcome(command);
#endif
                    }
                }
                catch (Exception exception)
                { DegradeUiRefresh("goods_command_refresh", command.Panel, exception); }
            }
        }

        private void PresentPendingGoodsCommand()
        {
            PendingGoodsCommand command = _pendingGoodsCommand;
            if (command == null || command.Lifetime.Cancelled
                || command.Demand != null || !CanPresentDiplomacyUi) return;
            try
            {
                if (MainViewModel.Instance == null
                    || !ReferenceEquals(command.Panel, CurrentAlliesPanel())) return;
                // Original HUD_AlliesPanel.UpdateGoods uses these exact properties.
                // Refresh each waiting frame since another goods selection can make
                // Vanilla enable Confirm again; the command itself still deduplicates.
                MainViewModel.Instance.Allies_GoodConfirmVis = false;
                MainViewModel.Instance.AlliesGoods_Info = command.Amount.ToString(
                    System.Globalization.CultureInfo.InvariantCulture) + " "
                    + GoodName(command.GoodId, command.Amount) + ": " + PendingGoodsCommandStatusText();
            }
            catch (Exception exception)
            { DegradeUiRefresh("goods_command_pending", command.Panel, exception); }
        }

#if DIPLOMACY_V2
        private sealed class V2GoodsOutcome
        {
            internal int Player, Day, LastVisibleDay = -1, VisibleDaysRemaining = 3;
            internal long Generation, Sequence;
            internal string Fingerprint, Reason;
            internal bool CancelledOrder;
        }

        // Presentation only: one latest result per possible player, never an
        // unbounded OK-dialog stream. Saves contain the actual model, not these
        // transient UI messages. A hidden lookup cannot consume visible days.
        private readonly V2GoodsOutcome[] _v2GoodsOutcomes = new V2GoodsOutcome[9];
        private long _v2GoodsOutcomeSequence;
        private const int V2GoodsOutcomeMaximumAgeDays = 14;

        private void ResetV2GoodsOutcomes()
        {
            Array.Clear(_v2GoodsOutcomes, 0, _v2GoodsOutcomes.Length);
            _v2GoodsOutcomeSequence = 0;
        }

        private void ClearV2GoodsOutcome(int player)
        {
            if (player >= 1 && player <= 8) _v2GoodsOutcomes[player] = null;
        }

        private void RecordV2GoodsOutcome(int player, string reason, bool cancelledOrder)
        {
            if (!_mapActive || _mapDisabled || player < 1 || player > 8) return;
            int day = Math.Max(0, _lastProcessedDay);
            V2GoodsOutcome current = _v2GoodsOutcomes[player];
            // Re-running the same day effect does not renew its display time.
            if (current != null && current.Generation == _sessionGeneration
                && current.Fingerprint == _mapFingerprint && current.Day == day
                && current.Reason == reason && current.CancelledOrder == cancelledOrder) return;
            if (_v2GoodsOutcomeSequence < long.MaxValue) _v2GoodsOutcomeSequence++;
            _v2GoodsOutcomes[player] = new V2GoodsOutcome
            {
                Player = player, Reason = reason, CancelledOrder = cancelledOrder,
                Day = day, Generation = _sessionGeneration, Fingerprint = _mapFingerprint,
                Sequence = _v2GoodsOutcomeSequence,
            };
        }

        private bool V2GoodsOutcomeCurrent(V2GoodsOutcome outcome)
        {
            int day = Math.Max(0, _lastProcessedDay);
            bool current = outcome != null && _mapActive && !_mapDisabled
                && outcome.Generation == _sessionGeneration
                && string.Equals(outcome.Fingerprint, _mapFingerprint, StringComparison.Ordinal)
                && outcome.VisibleDaysRemaining > 0 && day >= outcome.Day
                && (long)day - outcome.Day < V2GoodsOutcomeMaximumAgeDays;
            if (!current || outcome.CancelledOrder) return current;
            string coalition; RelationState relation;
            return !_playerCoalition.TryGetValue(outcome.Player, out coalition)
                || !_relations.TryGetValue(coalition, out relation) || relation.Demand == null;
        }

        private V2GoodsOutcome FindV2GoodsOutcome(int player)
        {
            if (player >= 1 && player <= 8)
                return V2GoodsOutcomeCurrent(_v2GoodsOutcomes[player]) ? _v2GoodsOutcomes[player] : null;
            if (player != 0) return null;
            V2GoodsOutcome last = null;
            for (int target = 1; target <= 8; target++)
            {
                V2GoodsOutcome candidate = _v2GoodsOutcomes[target];
                if (!V2GoodsOutcomeCurrent(candidate) || !candidate.CancelledOrder
                    || candidate.Reason != "party_gone" && _visiblePlayers.Contains(target)) continue;
                if (last == null || candidate.Sequence > last.Sequence) last = candidate;
            }
            return last;
        }

        private string V2GoodsOutcomeText(int player)
        {
            V2GoodsOutcome outcome = FindV2GoodsOutcome(player);
            if (outcome == null) return string.Empty;
            string reason;
            switch (outcome.Reason)
            {
                case "party_gone": reason = Text("eine Vertragspartei ist ausgefallen", "a party is no longer available"); break;
                case "relationship_changed": reason = Text("das Bündnis hat sich geändert", "the alliance has changed"); break;
                case "demand_fulfilled": reason = Text("die Forderung ist bereits erfüllt", "the demand is already fulfilled"); break;
                case "demand_partial": reason = Text("die Forderung wurde inzwischen teilweise erfüllt", "the demand has since been partly fulfilled"); break;
                case "demand_expired": reason = Text("die Forderung ist abgelaufen", "the demand has expired"); break;
                case "demand_withdrawn": reason = Text("die Forderung ist nicht mehr offen", "the demand is no longer open"); break;
                case "demand_changed": reason = Text("die Forderung hat sich geändert", "the demand has changed"); break;
                default: reason = Text("der Auftrag muss erneut bestätigt werden", "the order needs to be confirmed again"); break;
            }
            string message = outcome.CancelledOrder
                ? string.Format(System.Globalization.CultureInfo.InvariantCulture,
                    Text("Sendung an {0} abgebrochen: {1}. Dieser Auftrag wurde nicht ausgeführt.",
                        "Transfer to {0} cancelled: {1}. This order was not executed."), V2PlayerName(outcome.Player), reason)
                : string.Format(System.Globalization.CultureInfo.InvariantCulture,
                    Text("Forderung von {0} abgelaufen.", "Demand from {0} expired."), V2PlayerName(outcome.Player));
            if (!outcome.CancelledOrder)
            {
                string coalition; RelationState relation;
                if (_playerCoalition.TryGetValue(outcome.Player, out coalition)
                    && _relations.TryGetValue(coalition, out relation))
                {
                    int remaining = Math.Max(0, relation.RelationshipBlockedUntilDay - Math.Max(0, _lastProcessedDay));
                    if (remaining > 0) message += " " + string.Format(System.Globalization.CultureInfo.InvariantCulture,
                        Text("Kontaktpause: noch {0} Tage.", "Contact pause: {0} days remaining."), remaining);
                }
            }
            return message;
        }

        private void NoteV2GoodsOutcomeShown(int player)
        {
            V2GoodsOutcome outcome = FindV2GoodsOutcome(player);
            if (outcome == null) return;
            int day = Math.Max(0, _lastProcessedDay);
            if (outcome.LastVisibleDay >= 0 && day > outcome.LastVisibleDay)
                outcome.VisibleDaysRemaining--;
            outcome.LastVisibleDay = day;
        }

        private void RecordV2GoodsCommandCancellation(PendingGoodsCommand command)
        {
            string coalition;
            RelationState current;
            string reason = "reconfirm";
            if (!_playerCoalition.TryGetValue(command.TargetPlayer, out coalition)
                || !_relations.TryGetValue(coalition, out current)) reason = "party_gone";
            else if (command.Allied != current.Allied) reason = "relationship_changed";
            else if (command.Demand != null)
            {
                GoodsDemand demand = current.Demand;
                if (demand != null && demand.Complete || command.Demand.Complete) reason = "demand_fulfilled";
                else if (command.DemandQuote != null && _lastProcessedDay >= command.DemandQuote.ExpiresDay)
                    reason = "demand_expired";
                else if (demand == null) reason = "demand_withdrawn";
                else if (!SameGoodsDemandQuote(demand, command.DemandQuote))
                {
                    reason = "demand_changed";
                    GoodsDemand quote = command.DemandQuote;
                    if (quote != null && demand.IssuedDay == quote.IssuedDay && demand.ExpiresDay == quote.ExpiresDay
                        && demand.Items != null && quote.Items != null && demand.Items.Length == quote.Items.Length)
                        for (int index = 0; index < demand.Items.Length; index++)
                        {
                            DemandItem now = demand.Items[index], before = quote.Items[index];
                            if (now != null && before != null && now.GoodId == before.GoodId
                                && now.RequiredAmount == before.RequiredAmount && now.DeliveredAmount > before.DeliveredAmount)
                            { reason = "demand_partial"; break; }
                        }
                }
            }
            RecordV2GoodsOutcome(command.TargetPlayer, reason, true);
        }

        private void PresentV2GoodsCommandOutcome(PendingGoodsCommand command)
        {
            if (command.Demand != null || !CanPresentDiplomacyUi
                || !ReferenceEquals(command.Panel, CurrentAlliesPanel())) return;
            try
            {
                MainViewModel view = MainViewModel.Instance;
                if (view == null || !view.AlliesPanelVisible || !view.Allies_SendGoodsViewVis
                    || SelectedPlayer(command.Panel) != command.SelectionPlayer) return;
                NoteV2GoodsOutcomeShown(command.TargetPlayer);
                view.AlliesGoods_Info = V2GoodsOutcomeText(command.TargetPlayer);
                view.Allies_GoodConfirmVis = false;
            }
            catch (Exception exception)
            { DegradeUiRefresh("goods_command_outcome", command.Panel, exception); }
        }
#endif
    }
}
