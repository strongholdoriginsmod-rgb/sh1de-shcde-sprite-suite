#if DIPLOMACY_V2
using System;
using System.Globalization;
using CrusaderDE;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        // A request is a cancellable UI intent, not a goods transfer or a demand
        // payment. Vanilla owns any request after its command is dispatched.
        private sealed class V2GoodsRequest
        {
            internal object Panel;
            internal long Generation, Epoch;
            internal string Fingerprint, Coalition;
            internal int LocalPlayer, Target, Good, Amount;
            internal bool ReturnToOverview, Confirmed;
            internal DiplomacyPanelCommandLifetime Lifetime;
        }

        private sealed class V2GoodsRequestInvocation
        {
            internal DiplomacyFeature Owner;
            internal object Panel;
            internal string Command;
            internal bool PermitOriginal = true;
            internal bool DeferExit;
        }

        private V2GoodsRequest _v2GoodsRequest;
        [ThreadStatic] private static V2GoodsRequestInvocation _v2GoodsRequestInvocation;

        private void ResetV2GoodsRequests()
        {
            V2GoodsRequest request = _v2GoodsRequest;
            _v2GoodsRequest = null;
            if (request != null) request.Lifetime.Dispose();
        }

        private void InvokeV2OriginalGoodsButton(object panel, string command, bool deferExit = false)
        {
            V2GoodsRequestInvocation previous = _v2GoodsRequestInvocation;
            _v2GoodsRequestInvocation = new V2GoodsRequestInvocation
            {
                Owner = this, Panel = panel, Command = command, DeferExit = deferExit,
            };
            try { _buttonTarget.Invoke(panel, new object[] { command }); }
            finally { _v2GoodsRequestInvocation = previous; }
        }

        private void BeginV2GoodsRequest(object panel, int target, bool returnToOverview)
        {
            ResetV2GoodsRequests();
            if (!CanPresentDiplomacyUi || !_mapActive || _mapDisabled || _mapBootstrapPending
                || panel == null || !ReferenceEquals(panel, CurrentAlliesPanel())
                || target < 1 || target > 8 || target == _localPlayer
                || !V2CanRequestGoodsFrom(target)
                || !MainViewModel.Instance.AlliesPanelVisible || !IsCoalitionAllied(target)) return;
            int slot = _visiblePlayers.IndexOf(target);
            if (slot < 0) return;
            CancelPendingGoodsCommand("request_goods");
            _pendingGoodsTarget = 0;
            _selectedVisibleIndex = slot;
            _currentAllyField.SetValue(panel, slot);
            _v2OverviewVisible = false;
            _updateAlliesTarget.Invoke(panel, null);
            if (SelectedPlayer(panel) != target) return;
            MainViewModel view = MainViewModel.Instance;
            view.Allies_OrdersViewVis = false;
            // COPY HUD.Request does NOT clear this flag, while ConfirmGoods
            // dispatches solely from it. Normalize it before the original call.
            view.Allies_SendGoodsViewVis = false;
            view.Allies_NoAlliesViewVis = false;
            InvokeV2OriginalGoodsButton(panel, "Request");
            _v2GoodsRequest = new V2GoodsRequest
            {
                Panel = panel, Generation = _sessionGeneration, Epoch = _mapEpoch,
                Fingerprint = _mapFingerprint, Coalition = _playerCoalition[target],
                LocalPlayer = _localPlayer, Target = target, ReturnToOverview = returnToOverview,
                Lifetime = new DiplomacyPanelCommandLifetime(view),
            };
            RefreshVanillaDiplomacyUi(panel);
        }

        // Return value says whether this helper decided the command. The out
        // value has HandleButton's convention: true consumes; false runs native.
        // The one-use original permit is bound to this owner, thread and panel.
        private bool TryHandleV2GoodsRequestCommand(object panel, string param, out bool handledReturn)
        {
            handledReturn = true;
            if (string.IsNullOrEmpty(param)) return false;
            V2GoodsRequestInvocation invocation = _v2GoodsRequestInvocation;
            if (invocation != null && ReferenceEquals(invocation.Owner, this)
                && ReferenceEquals(invocation.Panel, panel))
            {
                if (invocation.PermitOriginal && invocation.Command == param)
                {
                    invocation.PermitOriginal = false;
                    handledReturn = false;
                    return true;
                }
                // COPY ConfirmGoods calls Exit immediately after GameAction.
                // Suppress only that recursive UI operation while native owns
                // the monitor; navigation runs after its release below.
                if (invocation.DeferExit && param == "Exit") return true;
                if (param == "ConfirmGoods") return true;
            }

            if (!_mapActive || _mapDisabled || _mapBootstrapPending)
            { ResetV2GoodsRequests(); return false; }

            V2GoodsRequest request = _v2GoodsRequest;
            if (request == null)
                return param == "ConfirmGoods" && MainViewModel.Instance != null
                    && MainViewModel.Instance.Allies_RequestGoodsViewVis;
            // A delayed callback from a replaced HUD cannot confirm, cancel or
            // retarget the currently displayed request's selection.
            if (!ReferenceEquals(panel, request.Panel)) return true;

            if (param == "Back")
            {
                ResetV2GoodsRequests();
                ReturnFromV2GoodsRequest(request);
                return true;
            }
            if (param == "Exit" || param == "Send" || param == "Orders" || param == "Request"
                || param.StartsWith("Diplomacy:", StringComparison.Ordinal)
                || (param.Length == 1 && param[0] >= '0' && param[0] <= '5'))
            {
                ResetV2GoodsRequests();
                return false;
            }
            if (!V2GoodsRequestCurrent(request))
            {
                ResetV2GoodsRequests();
                return param == "ConfirmGoods" || param == "CancelGoods";
            }
            if (param == "ConfirmGoods")
            {
                if (!request.Confirmed)
                {
                    int good = (int)_selectedGoodsField.GetValue(panel);
                    int amount = (int)_selectedGoodsAmountField.GetValue(panel);
                    if (!IsSendableGood(good) || amount <= 0) return true;
                    request.Good = good;
                    request.Amount = amount;
                    request.Confirmed = true;
                }
                PumpV2GoodsRequests();
                return true;
            }
            if (param == "CancelGoods")
            {
                request.Confirmed = false;
                request.Good = request.Amount = 0;
                return false;
            }
            if (request.Confirmed && (param.StartsWith("G", StringComparison.Ordinal)
                || param.StartsWith("X", StringComparison.Ordinal)))
            {
                PresentV2GoodsRequestWaiting(request);
                return true;
            }
            return false;
        }

        private bool V2GoodsRequestCurrent(V2GoodsRequest request)
        {
            try
            {
                string coalition;
                MainViewModel view = MainViewModel.Instance;
                return _mapActive && !_mapDisabled && !_mapBootstrapPending
                    && request.Generation == _sessionGeneration && request.Epoch == _mapEpoch
                    && string.Equals(request.Fingerprint, _mapFingerprint, StringComparison.Ordinal)
                    && request.LocalPlayer == _localPlayer && !request.Lifetime.Cancelled
                    && ReferenceEquals(request.Panel, CurrentAlliesPanel())
                    && !_v2OverviewVisible && SelectedPlayer(request.Panel) == request.Target
                    && _playerCoalition.TryGetValue(request.Target, out coalition)
                    && coalition == request.Coalition && IsCoalitionAllied(request.Target)
                    && V2CanRequestGoodsFrom(request.Target)
                    && view != null && view.Allies_GoodsViewVis && view.Allies_RequestGoodsViewVis
                    && !view.Allies_SendGoodsViewVis;
            }
            catch (Exception exception)
            {
                DegradeUiRefresh("goods_request_selection", request.Panel, exception);
                return false;
            }
        }

        private void PumpV2GoodsRequests()
        {
            V2GoodsRequest request = _v2GoodsRequest;
            if (request == null) return;
            if (!V2GoodsRequestCurrent(request)) { ResetV2GoodsRequests(); return; }
            if (!request.Confirmed || !CanPresentDiplomacyUi) return;
            if (_inventoryRestorePending || _nativeTransferProbe != null
                || _pendingPackage != null || _pendingTeamTransition != null)
            { PresentV2GoodsRequestWaiting(request); return; }

            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease))
            { PresentV2GoodsRequestWaiting(request); return; }
            bool claimed = false;
            try
            {
                using (lease)
                {
                    // These are fresh native liveness/team reads. The checked
                    // panel roster supplies the same target as original Confirm.
                    if (!V2GoodsRequestCurrent(request) || !V2CanRequestGoodsFrom(request.Target)
                        || !IsAlivePlayer(request.LocalPlayer)
                        || !IsAlivePlayer(request.Target)
                        || _teamPort.GetTeam(request.LocalPlayer) != _teamPort.GetTeam(request.Target)
                        || !IsSendableGood(request.Good) || request.Amount <= 0)
                    { ResetV2GoodsRequests(); return; }
                    if (!request.Lifetime.TryClaim()) { ResetV2GoodsRequests(); return; }
                    claimed = true;
                    _v2GoodsRequest = null;
                    _pendingGoodsTarget = 0;
                    // Restore only captured private fields, never later mutable
                    // selector values. No inventory read, debit or mod journal.
                    _selectedGoodsField.SetValue(request.Panel, request.Good);
                    _selectedGoodsAmountField.SetValue(request.Panel, request.Amount);
                    InvokeV2OriginalGoodsButton(request.Panel, "ConfirmGoods", true);
                }
            }
            catch (Exception exception)
            {
                // Native may already have accepted the request before a foreign
                // callback throws. Never retry a claimed command in that case.
                ResetV2GoodsRequests();
                DegradeUiRefresh("goods_request_dispatch", request.Panel, exception);
            }
            finally
            {
                if (claimed) ReturnFromV2GoodsRequest(request);
            }
        }

        private void PresentV2GoodsRequestWaiting(V2GoodsRequest request)
        {
            if (!CanPresentDiplomacyUi || !V2GoodsRequestCurrent(request)) return;
            try
            {
                MainViewModel.Instance.Allies_GoodConfirmVis = false;
                MainViewModel.Instance.AlliesGoods_Info = request.Amount.ToString(CultureInfo.InvariantCulture)
                    + " " + GoodName(request.Good, request.Amount) + ": "
                    + Text("Die Bitte wartet auf das Spiel. Zurück oder Schließen bricht sie ab.",
                        "The request is waiting for the game. Back or Close cancels it.");
            }
            catch (Exception exception)
            { DegradeUiRefresh("goods_request_pending", request.Panel, exception); }
        }

        private void ReturnFromV2GoodsRequest(V2GoodsRequest request)
        {
            if (!CanPresentDiplomacyUi || !_mapActive || _mapDisabled || _mapBootstrapPending
                || request.Generation != _sessionGeneration
                || request.Epoch != _mapEpoch || !string.Equals(request.Fingerprint, _mapFingerprint,
                    StringComparison.Ordinal) || !ReferenceEquals(request.Panel, CurrentAlliesPanel())
                || MainViewModel.Instance == null || !MainViewModel.Instance.AlliesPanelVisible) return;
            try
            {
                InvokeV2OriginalGoodsButton(request.Panel, "Back");
                if (request.ReturnToOverview) V2OpenAllianceOverview(request.Panel, request.Target);
                RefreshVanillaDiplomacyUi(request.Panel);
            }
            catch (Exception exception)
            { DegradeUiRefresh("goods_request_return", request.Panel, exception); }
        }
    }
}
#endif
