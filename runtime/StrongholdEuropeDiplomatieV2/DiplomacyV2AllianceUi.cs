#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using CrusaderDE;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        private int _v2AllianceSelectedPlayer;
        private long _v2AllianceUiGeneration = -1;

        // These are the same name sources used by the native Allies panel.
        // computer_register identifies the displayed computer profile, not a slot.
        private string V2PlayerName(int player)
        {
            if (player < 1 || player > 8) return Text("Unbekannter Herrscher", "Unknown ruler");
            GameData game = GameData.Instance;
            EngineInterface.PlayState live = game == null ? null : game.lastGameState;
            string name = V2PlayerBaseName(live, player);
            // Use the session roster, including defeated rulers: the surviving
            // names must not lose their disambiguator when a namesake dies.
            bool duplicate = _roster.Any(other => other != player && other >= 1 && other <= 8
                && string.Equals(name, V2PlayerBaseName(live, other), StringComparison.OrdinalIgnoreCase));
            return duplicate ? name + " · " + string.Format(CultureInfo.InvariantCulture,
                Text("Spieler {0}", "Player {0}"), player) : name;
        }

        private string V2PlayerBaseName(EngineInterface.PlayState live, int player)
        {
            string name = live == null ? null : live.is_skirmish_player(player)
                ? OnScreenText.getComputerName(live.computer_register[player], live.computer_names[player])
                : Platform_Multiplayer.Instance.getPlayerName(player);
            return string.IsNullOrWhiteSpace(name)
                ? Text("Unbekannter Herrscher", "Unknown ruler") : name.Trim();
        }

        private bool TryV2AllianceMember(int player, out CoalitionState coalition,
            out RelationState relation)
        {
            coalition = null; relation = null;
            string id;
            return player != _localPlayer && player >= 1 && player <= 8
                && _mapActive && !_mapDisabled && IsAlivePlayer(player)
                && _playerCoalition.TryGetValue(player, out id)
                && _coalitions.TryGetValue(id, out coalition)
                && _relations.TryGetValue(id, out relation)
                && relation.Allied && relation.V2 != null
                && coalition.MemberPlayerIds.Contains(player);
        }

        private bool V2SelectAllianceMember(object panel, int player)
        {
            CoalitionState coalition; RelationState relation;
            if (!TryV2AllianceMember(player, out coalition, out relation)) return false;
            int slot = _visiblePlayers.IndexOf(player);
            if (slot < 0) return false;
            _v2AllianceSelectedPlayer = player;
            _v2AllianceUiGeneration = _sessionGeneration;
            _selectedVisibleIndex = slot;
            _currentAllyField.SetValue(panel, slot);
            _updateAlliesTarget.Invoke(panel, null);
            return true;
        }

        private void V2OpenAllianceOverview(object panel, int selectedPlayer)
        {
            _v2OverviewVisible = true;
            if (V2SelectAllianceMember(panel, selectedPlayer)
                || V2SelectAllianceMember(panel, _v2AllianceSelectedPlayer)) return;
            foreach (int player in _visiblePlayers)
                if (V2SelectAllianceMember(panel, player)) return;
        }

        private void RefreshV2AllianceManagement(object panel)
        {
            try { RefreshV2AllianceManagementCore(panel); }
            catch (Exception exception) { DegradeUiRefresh("alliance_refresh", panel, exception); }
        }

        private object V2AllianceUiElement(object panel, string name)
        {
            object element = FindElement(panel, name);
            if (element == null) throw new MissingMemberException("Alliance view control is missing: " + name);
            return element;
        }

        private void SetV2AllianceText(object panel, string name, string text)
        {
            object element = V2AllianceUiElement(panel, name);
            SetProperty(element, "Text", text);
            SetProperty(element, "ToolTip", text);
        }

        private void RefreshV2AllianceManagementCore(object panel)
        {
            int[] members = _coalitions.Values.SelectMany(c => c.MemberPlayerIds)
                .Distinct().OrderBy(p => p).Where(p =>
                {
                    CoalitionState c; RelationState r;
                    return TryV2AllianceMember(p, out c, out r);
                }).ToArray();
            if (_v2AllianceUiGeneration != _sessionGeneration
                || !members.Contains(_v2AllianceSelectedPlayer))
            {
                _v2AllianceSelectedPlayer = members.FirstOrDefault();
                _v2AllianceUiGeneration = _sessionGeneration;
            }
            int day = Math.Max(0, _lastProcessedDay);
            SetV2AllianceText(panel, "CrusaderDiplomacyV2Ruler", Text("Euer Bündnis", "Your alliance"));
            SetV2AllianceText(panel, "CrusaderDiplomacyV2OverviewTitle",
                string.Format(CultureInfo.InvariantCulture,
                    Text("Verbündete: {0} · Vasallen: {1}", "Allies: {0} · Vassals: {1}"),
                    members.Length, members.Count(p =>
                    {
                        CoalitionState c; RelationState r;
                        return TryV2AllianceMember(p, out c, out r)
                            && V2IsFealtyCounterpart(r.V2, p)
                            && DiplomacyV2Vassalage.OverlordOf(r.V2) == _localPlayer;
                    })));
            SetV2AllianceText(panel, "CrusaderDiplomacyV2OverviewHeader", Text("Herrscher", "Ruler"));
            SetV2AllianceText(panel, "CrusaderDiplomacyV2AllianceRoleHeader", Text("Rolle", "Role"));
            SetV2AllianceText(panel, "CrusaderDiplomacyV2AllianceDutyHeader", Text("Pflichten und Befehle", "Obligations and orders"));
            for (int row = 0; row < V2OverviewRowCount; row++)
            {
                string suffix = (row + 1).ToString(CultureInfo.InvariantCulture);
                object button = V2AllianceUiElement(panel, "CrusaderDiplomacyV2AllianceMember" + suffix);
                bool present = row < members.Length;
                SetVisibilityIfPresent(V2AllianceUiElement(panel, "CrusaderDiplomacyV2AllianceRow" + suffix), present);
                if (!present) continue;
                int player = members[row];
                CoalitionState coalition; RelationState relation;
                if (!TryV2AllianceMember(player, out coalition, out relation)) continue;
                string role = V2IsFealtyCounterpart(relation.V2, player)
                    ? V2VassalRoleText(relation.V2) : Text("Verbündeter", "Ally");
                string duty = V2AllianceObligation(relation, day, player);
                string orderStatus = V2AllyOrderStatusText(player);
                if (!string.IsNullOrEmpty(orderStatus)) duty = orderStatus + " · " + duty;
                if (button != null)
                {
                    SetProperty(button, "IsEnabled", true);
                    SetProperty(button, "IsChecked", player == _v2AllianceSelectedPlayer);
                    SetProperty(button, "CommandParameter", "Diplomacy:AllianceSelect:"
                        + player.ToString(CultureInfo.InvariantCulture) + ":"
                        + _sessionGeneration.ToString(CultureInfo.InvariantCulture));
                    SetProperty(button, "ToolTip", V2PlayerName(player) + " · " + role + " · " + duty);
                }
                SetV2AllianceText(panel, "CrusaderDiplomacyV2OverviewRow" + suffix, V2PlayerName(player));
                SetV2AllianceText(panel, "CrusaderDiplomacyV2AllianceRole" + suffix, role);
                SetV2AllianceText(panel, "CrusaderDiplomacyV2AllianceDuty" + suffix, duty);
                int order = GameData.Instance.lastGameState.skirmish_order[player];
                SetProperty(V2AllianceUiElement(panel, "CrusaderDiplomacyV2AllianceOrder" + suffix), "Source",
                    order == 1 ? GetAlliesGoodsIcon(-3) : order == 2 ? GetAlliesGoodsIcon(-4) : null);
            }
            CoalitionState selectedCoalition; RelationState selectedRelation;
            bool selected = TryV2AllianceMember(_v2AllianceSelectedPlayer,
                out selectedCoalition, out selectedRelation);
            Dictionary<int, int> selectedStock = selected
                ? V2DemandStockSnapshot(selectedRelation.Demand) : null;
            bool demandReady = selected && V2CanFulfilDemand(selectedRelation.Demand, selectedStock);
            string summary = HasPendingGoodsCommand ? PendingGoodsCommandStatusText() : selected
                ? V2PlayerName(_v2AllianceSelectedPlayer) + " · " + V2AllianceObligation(selectedRelation, day, _v2AllianceSelectedPlayer)
                : Text("Noch keine Verbündeten. Waffenruhe und Handel begründen kein Bündnis.",
                    "No allies yet. A truce or trade pact does not establish an alliance.");
            if (!HasPendingGoodsCommand)
            {
                MainViewModel visibleView = MainViewModel.Instance;
                bool overviewVisible = _v2OverviewVisible && visibleView != null && visibleView.AlliesPanelVisible
                    && visibleView.Allies_MainViewVis;
                string goodsOutcome = V2ShownGoodsOutcome(selected ? _v2AllianceSelectedPlayer : 0, overviewVisible);
                if (!string.IsNullOrEmpty(goodsOutcome)) summary = goodsOutcome + " · " + summary;
                else if (selected)
                {
                    if (overviewVisible) NoteV2AllyOrderStatusShown(_v2AllianceSelectedPlayer);
                    string orderStatus = V2AllyOrderStatusText(_v2AllianceSelectedPlayer);
                    if (!string.IsNullOrEmpty(orderStatus)) summary = orderStatus + " · " + summary;
                }
            }
            if (selected && V2IsFealtyCounterpart(selectedRelation.V2, _v2AllianceSelectedPlayer))
                summary += " · " + V2TributeLedgerText(selectedRelation.V2);
            SetV2AllianceText(panel, "CrusaderDiplomacyV2OverviewFooter", summary);
            object footer = V2AllianceUiElement(panel, "CrusaderDiplomacyV2OverviewFooter");
            if (footer != null) SetProperty(footer, "ToolTip", summary);
            // 09.09.2026: "Decline" kam dazu - eine Forderung muss ablehnbar sein.
            // Der Knopf erscheint nur, solange eine offene Forderung da ist.
            string[] actions = { "Send", "RequestGoods", "Fulfill", "Orders", "Fealty", "Break", "Decline" };
            string[] labels = { Text("Güter senden", "Send goods"), Text("Güter erbitten", "Request goods"), Text("Forderung erfüllen", "Fulfil demand"),
                Text("Befehle", "Orders"), Text("Lehnsverhältnis", "Fealty"), Text("Bündnis lösen", "End alliance"),
                Text("Forderung ablehnen", "Decline demand") };
            if (selected && V2IsFealtyCounterpart(selectedRelation.V2, _v2AllianceSelectedPlayer))
            {
                bool localOverlord = DiplomacyV2Vassalage.OverlordOf(selectedRelation.V2) == _localPlayer;
                labels[1] = localOverlord ? Text("Güter anfordern", "Request supplies") : labels[1];
                labels[4] = localOverlord ? Text("Vasallen freilassen", "Release vassal")
                    : Text("Gleichstellung fordern", "Request equal standing");
            }
            for (int index = 0; index < actions.Length; index++)
            {
                object action = V2AllianceUiElement(panel, "CrusaderDiplomacyV2Alliance" + actions[index]);
                object label = V2AllianceUiElement(panel, "CrusaderDiplomacyV2Alliance" + actions[index] + "Label");
                bool enabled = selected && !HasPendingGoodsCommand
                    && (actions[index] != "Fulfill" || demandReady)
                    && (actions[index] != "RequestGoods" || V2CanRequestGoodsFrom(_v2AllianceSelectedPlayer))
                    && (actions[index] != "Fealty" || !DiplomacyV2VassalActions.HasPending(selectedRelation.V2)
                        && (DiplomacyV2Vassalage.VassalOf(selectedRelation.V2) != _localPlayer
                            || DiplomacyV2Vassalage.CanRequestEquality(selectedRelation.V2, day)));
                if (actions[index] == "Decline")
                    enabled = selected && !HasPendingGoodsCommand && selectedRelation.Demand != null;
                // Ablehnen zeigt sich nur bei offener Forderung: ein Knopf ohne
                // Gegenstand verwirrt mehr, als er nuetzt.
                bool show = (actions[index] != "Fealty" || selected
                    && V2IsFealtyCounterpart(selectedRelation.V2, _v2AllianceSelectedPlayer))
                    && (actions[index] != "Decline" || selected && selectedRelation.Demand != null);
                SetVisibilityIfPresent(action, show);
                SetVisibilityIfPresent(label, show);
                if (action != null)
                {
                    SetProperty(action, "IsEnabled", enabled);
                    SetProperty(action, "ToolTip", selected && actions[index] == "Fulfill"
                        && selectedRelation.Demand != null ? V2DemandText(selectedRelation.Demand)
                        : selected && actions[index] == "RequestGoods" && !V2CanRequestGoodsFrom(_v2AllianceSelectedPlayer)
                            ? Text("Als Vasall könnt Ihr keine Güter fordern.",
                                "As a vassal, you cannot request goods.")
                        : selected && actions[index] == "Fealty" ? V2VassalPrimaryHint(selectedRelation.V2) : labels[index]);
                    SetProperty(action, "CommandParameter", "Diplomacy:AllianceAction:" + actions[index]
                        + ":" + _v2AllianceSelectedPlayer.ToString(CultureInfo.InvariantCulture)
                        + ":" + _sessionGeneration.ToString(CultureInfo.InvariantCulture));
                }
                if (label != null)
                {
                    SetProperty(label, "Text", labels[index]);
                    SetNumericProperty(label, "Opacity", enabled ? 1.0 : 0.48);
                }
            }
        }

        private string V2ShownGoodsOutcome(int player, bool visible)
        {
            string outcome = V2GoodsOutcomeText(player);
            if (string.IsNullOrEmpty(outcome) && player != 0)
            {
                player = 0;
                outcome = V2GoodsOutcomeText(0);
            }
            if (visible && !string.IsNullOrEmpty(outcome))
            {
                NoteV2GoodsOutcomeShown(player);
                return V2GoodsOutcomeText(player);
            }
            return outcome;
        }

        private string V2AllianceObligation(RelationState relation, int day, int player)
        {
            DiplomacyV2RelationState state = relation.V2;
            var obligations = new List<string>();
            if (relation.Demand != null) obligations.Add(V2DemandText(relation.Demand));
            if (V2IsFealtyCounterpart(state, player) && DiplomacyV2Tribute.IsActive(state))
            {
                string direction = DiplomacyV2Vassalage.VassalOf(state) == _localPlayer
                    ? Text("Ihr zahlt", "You pay") : Text("Ihr erhaltet", "You receive");
                string due = state.TributeMissedCycles > 0
                    ? Text("Rückstand; täglicher Zahlungsversuch", "Arrears; daily payment retry")
                    : DiplomacyV2Tribute.IsDue(state, day)
                    ? V2GraceText(DiplomacyV2Tribute.DaysUntilGraceDeadline(state, day))
                    : V2DurationText(DiplomacyV2Tribute.DaysUntilDue(state, day));
                obligations.Add(direction + " " + state.TributeAmount.ToString(CultureInfo.InvariantCulture)
                    + " " + GoodName(state.TributeGoodId, state.TributeAmount)
                    + (state.TributeGoodId == DiplomacyV2Tribute.GoldGoodId
                        ? " · " + Text("Waren statt Gold", "Goods accepted") : "")
                    + " · " + due);
            }
            if (state.RestitutionOutstandingValue > 0m)
                obligations.Add(Text("Wiedergutmachung offen", "restitution due"));
            return obligations.Count == 0 ? Text("Keine offene Pflicht", "No obligation due")
                : string.Join(" · ", obligations);
        }

        private string V2TributeLedgerText(DiplomacyV2RelationState state)
        {
            if (state == null || !DiplomacyV2Tribute.IsActive(state)) return string.Empty;
            return string.Format(CultureInfo.InvariantCulture,
                Text("Alle {0} Tage · Zahlungen: {1} · Rückstände: {2} · Offen: {3}",
                    "Every {0} days · Payments: {1} · Arrears: {2} · Open: {3}"),
                state.TributeIntervalDays, state.TributePaidCycles, state.TributeDefaults, state.TributeMissedCycles);
        }

        /// <summary>
        /// Weist die offene Forderung des ausgewaehlten Mitglieds zurueck.
        /// </summary>
        /// <remarks>
        /// Benutzervorgabe 09.09.2026: dieselbe Wirkung wie eine verstrichene
        /// Frist. Ein Ultimatum beendet damit das Buendnis, deshalb fragt es
        /// vorher nach - ein Fehlklick soll keine lange gepflegte Allianz
        /// zerstoeren. Die gewoehnliche Forderung geht ohne Rueckfrage.
        /// </remarks>
        private void V2HandleDeclineDemand(object panel, int player)
        {
            // KEIN RequireNativeDiplomacySection: das ist der Klickweg, und der
            // UI-Faden haelt den Motor-Monitor nie (V2PlayerName wirft sogar,
            // wenn er gehalten wird). Der Aufruf stand hier bis 10.09.2026 und
            // haette jeden Druck auf den Knopf mit einer Ausnahme beendet.
            // Abgelehnt wird ausschliesslich im Modell, unter _gate aus
            // HandleButton - nativer Zustand wird dabei nicht angefasst.
            CoalitionState coalition; RelationState relation;
            if (!TryV2AllianceMember(player, out coalition, out relation)
                || relation.Demand == null) return;
            // Benutzervorgabe 10.09.2026: eine abgelehnte Bitte kostet Ansehen,
            // aber niemals das Buendnis - auch dann nicht, wenn es die zweite
            // Mahnung ist. Deshalb gibt es hier keinen Sonderweg und keine
            // Rueckfrage mehr; wer ablehnt, weiss was er tut.
            V2DeclineDemandNow(coalition, relation, player);
        }

        /// <summary>
        /// Eine Forderung ablehnen, ohne dass ein Buendnis bestehen muss.
        /// </summary>
        /// <remarks>
        /// 10.09.2026: `V2HandleDeclineDemand` geht ueber `TryV2AllianceMember`
        /// und findet damit nur Verbuendete. Bedingungen aus einer Verhandlung
        /// (Courtship/TradeProof/AllianceTerms) stellt aber ein Fuerst, mit dem
        /// noch gar kein Buendnis besteht - genau die waren unablehnbar. Dieser
        /// Weg kommt aus der Detailansicht und nimmt jeden Fuersten, zu dem eine
        /// Beziehung gefuehrt wird.
        /// </remarks>
        private void V2HandleDeclineDemandForPlayer(int player)
        {
            string id; RelationState relation; CoalitionState coalition;
            if (!_playerCoalition.TryGetValue(player, out id)
                || !_relations.TryGetValue(id, out relation)
                || !_coalitions.TryGetValue(id, out coalition)
                || relation.V2 == null || relation.Demand == null) return;
            V2DeclineDemandNow(coalition, relation, player);
        }

        private void V2DeclineDemandNow(CoalitionState coalition, RelationState relation, int player)
        {
            int day = Math.Max(0, _lastProcessedDay);
            bool ultimatum = DiplomacyV2StateMachine.DemandIsUltimatum(relation);
            // Der Zielwert entsteht erst in der Koalitionsbewertung des Taktes.
            // Direkt nach dem Laden eines Spielstands steht die gespeicherte
            // Forderung schon da, der Zielwert aber noch auf 0 - und
            // SyncGoodwill wirft darauf. Ein Klick in genau diesem Augenblick
            // ist kein Spielerfehler, also wird hier aufgerundet statt geworfen:
            // Goodwill setzt der naechste Takt ohnehin neu.
            int target = Math.Max(1, coalition.Target);
            if (!DiplomacyV2StateMachine.DeclineDemand(relation, day, target)) return;
            Log("demand", "coalition=" + coalition.CoalitionId
                + "|status=declined|player=" + player.ToString(CultureInfo.InvariantCulture)
                + "|ultimatum=" + BoolText(ultimatum));
            CancelPendingGoodsCommand("demand_declined");
            ShowMessage(V2PlayerName(player) + ": " + Text(
                "Die Forderung wurde zurückgewiesen.",
                "The demand has been rejected."));
        }

        private bool TryHandleV2AllianceUiCommand(object panel, string command)
        {
            if (!command.StartsWith("Diplomacy:Alliance", StringComparison.Ordinal)) return false;
            // The target and map generation travel with the displayed control.
            // A dead/reordered member or a stale control cannot retarget an action.
            if (!_v2OverviewVisible || !ReferenceEquals(panel, CurrentAlliesPanel())) return true;
            string[] parts = command.Split(':');
            bool select = parts.Length == 4 && parts[1] == "AllianceSelect";
            bool action = parts.Length == 5 && parts[1] == "AllianceAction";
            if (!select && !action) return true;
            int player; long generation;
            if (!int.TryParse(parts[parts.Length - 2], NumberStyles.None, CultureInfo.InvariantCulture, out player)
                || !long.TryParse(parts[parts.Length - 1], NumberStyles.None, CultureInfo.InvariantCulture, out generation)
                || generation != _sessionGeneration) return true;
            CoalitionState coalition; RelationState relation;
            if (!TryV2AllianceMember(player, out coalition, out relation)) return true;
            if (select)
            {
                CancelPendingGoodsCommand("alliance_selection");
                if (!V2SelectAllianceMember(panel, player)) return true;
                RefreshV2AllianceManagement(panel);
                return true;
            }
            if (player != _v2AllianceSelectedPlayer) return true;
            string actionName = parts[2];
            if (actionName == "Fulfill")
            {
                if (relation.Demand != null) QueueGoodsCommand(panel, player, 0, 0, relation.Demand);
            }
            else if (actionName == "Decline") V2HandleDeclineDemand(panel, player);
            else if (actionName == "Fealty") V2HandleFealtyAction(player);
            else if (actionName == "Break") ConfirmPlayerBreakOne(player);
            else if (actionName == "RequestGoods")
            {
                if (!V2CanRequestGoodsFrom(player)) return true;
                BeginV2GoodsRequest(panel, player, true);
                return true;
            }
            else if (actionName == "Send" || actionName == "Orders")
            {
                int slot = _visiblePlayers.IndexOf(player);
                if (slot < 0) return true;
                CancelPendingGoodsCommand("alliance_action");
                _pendingGoodsTarget = 0;
                _selectedVisibleIndex = slot;
                _currentAllyField.SetValue(panel, slot);
                _v2OverviewVisible = false;
                _updateAlliesTarget.Invoke(panel, null);
                RefreshVanillaDiplomacyUi(panel);
                _buttonTarget.Invoke(panel, new object[] { actionName });
                return true;
            }
            RefreshV2AllianceManagement(panel);
            return true;
        }

        private void V2HandleFealtyAction(int player)
        {
            string id; RelationState relation;
            if (!_playerCoalition.TryGetValue(player, out id) || !_relations.TryGetValue(id, out relation)) return;
            string stamp = V2FealtyActionStamp(relation);
            QueueV2FealtyCommand(CurrentAlliesPanel(), player,
                delegate { V2HandleFealtyActionNow(player); }, null, delegate
                {
                    string currentId; RelationState current;
                    return _playerCoalition.TryGetValue(player, out currentId) && currentId == id
                        && _relations.TryGetValue(id, out current) && V2FealtyActionStamp(current) == stamp;
                });
        }

        private static string V2FealtyActionStamp(RelationState relation)
        {
            DiplomacyV2RelationState s = relation.V2;
            if (s == null) return string.Empty;
            // Stable action identity, not reference identity: a journal rollback
            // may clone the same contract without changing the user's request.
            return string.Join(":", new[] { relation.Allied.ToString(), s.Agreement.ToString(),
                s.VassalRole.ToString(), DiplomacyV2Vassalage.VassalOf(s).ToString(CultureInfo.InvariantCulture),
                DiplomacyV2Vassalage.OverlordOf(s).ToString(CultureInfo.InvariantCulture),
                s.SubmissionOfferPlayerId.ToString(CultureInfo.InvariantCulture),
                s.SubmissionOfferCreatedDay.ToString(CultureInfo.InvariantCulture),
                s.SubmissionOfferOrigin.ToString(), s.SubmissionOfferAccepted.ToString(),
                s.SubmissionOfferTributeAmount.ToString(CultureInfo.InvariantCulture) });
        }

        private void V2HandleFealtyActionNow(int player)
        {
            RequireNativeDiplomacySection();
            if (!IsAlivePlayer(_localPlayer) || !IsAlivePlayer(player)) return;
            if (TryHandleV2VassalPrimary(player)) return;
            string id; RelationState relation; CoalitionState coalition;
            if (!_playerCoalition.TryGetValue(player, out id)
                || !_relations.TryGetValue(id, out relation)
                || !_coalitions.TryGetValue(id, out coalition) || relation.V2 == null) return;
            if (DiplomacyV2Vassalage.IsActive(relation.V2)
                && !V2IsFealtyCounterpart(relation.V2, player))
            {
                ShowMessage(V2PlayerName(player) + " · " + string.Format(CultureInfo.InvariantCulture,
                    Text("Dieser Bündnispartner ist an diesem Lehnsverhältnis nicht beteiligt. Vasall: {0}; Lehnsherr: {1}.",
                        "This ally is not a party to this fealty. Vassal: {0}; overlord: {1}."),
                    V2PlayerName(DiplomacyV2Vassalage.VassalOf(relation.V2)),
                    V2PlayerName(DiplomacyV2Vassalage.OverlordOf(relation.V2))));
                return;
            }
            int day = Math.Max(0, _lastProcessedDay);
            if (DiplomacyV2Submission.HasOffer(relation.V2))
            {
                if (ReviewV2SubmissionOffer(coalition, relation, day))
                    AskV2SubmissionOffer(coalition, relation);
                return;
            }
            int lord;
            TryV2LordIdentity(player, out lord);
            int band = 0;
            if (lord != 0 && !TryV2SubmissionPressureBand(player, lord, day, out band))
            {
                ShowMessage(V2PlayerName(player) + ": " + Text("Die militärische Lage wird noch geprüft.",
                    "The military situation is still being assessed."));
                return;
            }
            DiplomacyV2SubmissionAssessment assessment = DiplomacyV2Submission.Assess(
                relation, day, lord, coalition.MemberPlayerIds.Length, CanJoinAlliance(id),
                band, DiplomacyV2SubmissionOfferOrigin.PlayerDemand);
            if (assessment.Availability == DiplomacyV2SubmissionAvailability.OfferPending)
            {
                AskV2SubmissionOffer(coalition, relation);
                return;
            }
            if (!assessment.CanAttempt)
            {
                ShowMessage(V2PlayerName(player) + ": "
                    + V2FealtyAvailabilityText(assessment.Availability, relation, day));
                return;
            }
            DiplomacyV2SubmissionAttemptResult result = DiplomacyV2Submission.TryAttempt(
                relation, player, lord, V2TributeQuoteForPlayer(player), day, _mapFingerprint,
                DiplomacyV2SubmissionOfferOrigin.PlayerDemand, band);
            if (result == DiplomacyV2SubmissionAttemptResult.Offered)
                PresentV2NewSubmissionOffer(coalition, relation);
            else if (result == DiplomacyV2SubmissionAttemptResult.Refused)
            {
                Log("vassalage", "coalition=" + id + "|status=submission_demand_refused|lord="
                    + lord.ToString(CultureInfo.InvariantCulture));
                ShowMessage(V2PlayerName(player) + ": "
                    + Text("Forderung abgelehnt.", "Demand refused.")
                    + " " + Text("Eine erneute Forderung ist möglich — ", "You may demand submission again — ")
                    + V2DurationText(relation.V2.SubmissionNextDemandDay - day));
            }
        }

        private string V2FealtyAvailabilityText(DiplomacyV2SubmissionAvailability availability,
            RelationState relation, int day)
        {
            switch (availability)
            {
                case DiplomacyV2SubmissionAvailability.ActiveFealty:
                    return V2VassalRoleText(relation.V2);
                case DiplomacyV2SubmissionAvailability.OfferCommitting:
                    return Text("Die angenommene Unterwerfung wird noch vollzogen.", "The accepted submission is still being completed.");
                case DiplomacyV2SubmissionAvailability.OtherDecisionPending:
                    return Text("Zuerst muss das bereits offene Angebot entschieden werden.", "The existing offer must be resolved first.");
                case DiplomacyV2SubmissionAvailability.CoalitionHasMultipleMembers:
                    return Text("Dieser Fürst gehört einem gemeinsamen KI-Team an. Einzelne Teammitglieder können sich nicht unterwerfen.",
                        "This ruler belongs to a shared AI team. Individual team members cannot submit.");
                case DiplomacyV2SubmissionAvailability.EqualAlliance:
                    return Text("Ihr seid gleichberechtigte Verbündete. Ein Bündnis begründet keine Lehnspflicht.",
                        "You are equal allies. An alliance does not create fealty.");
                case DiplomacyV2SubmissionAvailability.ActiveTreaty:
                    return Text("Das laufende Abkommen verhindert ein Unterwerfungsangebot.", "The current agreement prevents a submission offer.");
                case DiplomacyV2SubmissionAvailability.NegotiationPending:
                    return Text("Eine offene Forderung muss zunächst erfüllt oder beendet werden.", "An outstanding demand must first be fulfilled or ended.");
                case DiplomacyV2SubmissionAvailability.RelationshipBlocked:
                    return Text("Gespräche ausgesetzt — ", "Talks suspended — ")
                        + V2DurationText(relation.RelationshipBlockedUntilDay - day);
                case DiplomacyV2SubmissionAvailability.LordUnknown:
                    return Text("Die Identität dieses Herrschers ist noch nicht verfügbar.", "This ruler's identity is not available yet.");
                case DiplomacyV2SubmissionAvailability.LordNeverSubmits:
                    return Text("Unterwerfung ausgeschlossen.", "Will never submit.");
                case DiplomacyV2SubmissionAvailability.LordNotEligible:
                    return Text("Für diesen Herrscher ist keine Unterwerfungsentscheidung verfügbar.",
                        "A submission decision is not available for this ruler.");
                case DiplomacyV2SubmissionAvailability.NoRemainingOpponent:
                    return Text("Ein weiterer lebender Gegner muss verbleiben.", "Another living enemy must remain.");
                case DiplomacyV2SubmissionAvailability.OfferCooldown:
                    return Text("Eine erneute Forderung ist möglich — ", "You may demand submission again — ")
                        + V2DurationText(relation.V2.SubmissionNextDemandDay - day);
                case DiplomacyV2SubmissionAvailability.AwaitingDailyAssessment:
                    return Text("Die aktuelle Lage wird beim nächsten diplomatischen Tageswechsel bewertet.",
                        "The current situation will be assessed at the next diplomatic day change.");
                case DiplomacyV2SubmissionAvailability.PressureNotEstablished:
                    return Text("Militärisch nicht ausreichend unterlegen.", "Insufficient military disadvantage.");
                case DiplomacyV2SubmissionAvailability.PressureDeveloping:
                    return Text("Hält dem Druck noch stand.", "Still resisting the pressure.");
                case DiplomacyV2SubmissionAvailability.AwaitingOffer:
                    return Text("Die erforderlichen Drucktage sind beobachtet; die Angebotsprüfung steht noch aus.",
                        "The required days of pressure have been observed; the offer assessment is pending.");
                default:
                    return Text("Derzeit liegt kein Unterwerfungsangebot vor.", "There is currently no submission offer.");
            }
        }
    }
}
#endif
