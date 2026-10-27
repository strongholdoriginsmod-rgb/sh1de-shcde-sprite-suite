#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        private bool TryReadV2PackageAmounts(int targetPlayer, V2DemandPackageLine[] lines,
            out List<string> missing, out bool boundsValid)
        {
            missing = new List<string>();
            boundsValid = true;
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease)) return false;
            using (lease)
            {
                foreach (V2DemandPackageLine line in lines)
                {
                    if (!TryReadTransferAmount(_localPlayer, line.GoodId, out line.SenderBefore)
                        || !TryReadTransferAmount(targetPlayer, line.GoodId, out line.RecipientBefore)
                        || line.RecipientBefore > int.MaxValue - line.Amount)
                    { boundsValid = false; return true; }
                }
            }
            foreach (V2DemandPackageLine line in lines)
                if (line.SenderBefore < line.Amount)
                {
                    int shortfall = line.Amount - line.SenderBefore;
                    missing.Add(shortfall.ToString(CultureInfo.InvariantCulture)
                        + " " + GoodName(line.GoodId, shortfall));
                }
            return true;
        }

        private void ExecuteV2DemandPackage(int targetPlayer, RelationState relation,
            V2DemandPackageLine[] lines)
        {
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease)) return;
            Exception nativeFailure = null;
            using (lease)
            {
            try
            {
            _inventoryRecoveryBaseState = CaptureInventoryRecoveryBaseState();
            _pendingPackage = new DiplomacyPendingPackage
            {
                SenderPlayer = _localPlayer, TargetPlayer = targetPlayer,
                GameDay = _lastProcessedDay,
                Lines = lines.Select(line => new DiplomacyPendingTransfer
                {
                    SenderPlayer = _localPlayer, TargetPlayer = targetPlayer,
                    GoodId = line.GoodId, Amount = line.Amount,
                    SenderBefore = line.SenderBefore, RecipientBefore = line.RecipientBefore,
                    AlliedNativeTransfer = relation.Allied,
                    Purpose = DiplomacyTransferPurpose.Gift, DirectAtomicTransfer = true,
                    GameDay = _lastProcessedDay, Progress = new DiplomacyTransferProgress(),
                }).ToList(),
            };
                // The coherent model is unchanged throughout the native phase.
                // SaveData captures the live, progressively updated journal.
                foreach (DiplomacyPendingTransfer line in _pendingPackage.Lines)
                    DiplomacyTransferRecovery.ApplyLine(line, GoodAmount, ChangeTransferAmount);
            }
            catch (Exception exception)
            {
                nativeFailure = exception;
                // Keep the same engine lease through native failure and its
                // immediate refund; simulation cannot consume a half-package.
                AbortV2PendingPackage();
            }
            }
            try
            {
                if (nativeFailure != null) throw nativeFailure;
                CommitV2PendingPackage();
                Log("demand_package", "coalition=" + relation.CoalitionId
                    + "|status=complete|items=" + lines.Length.ToString(CultureInfo.InvariantCulture));
            }
            catch (Exception exception)
            {
                string failure = AbortV2PendingPackage();
                Log("demand_package", "coalition=" + relation.CoalitionId
                    + "|status=" + (failure == null ? "rolled_back" : "rollback_pending")
                    + "|reason=" + Safe(exception.Message));
                if (failure == "native_inventory_busy") _goodsTransfersUnavailable = true;
                else if (failure != null) DisableGoodsTransfers("v2_package_rollback_pending");
                else ShowMessage(Text("Das Güterpaket wurde vollständig zurückgenommen.",
                    "The goods package was rolled back in full."));
            }
        }

        private void CommitV2PendingPackage()
        {
            DiplomacyPendingPackage package = _pendingPackage;
            if (package == null || package.RollbackPending)
                throw new InvalidOperationException("package has no commit intent");
            DiplomacyManagedStateMemento memento = CaptureManagedStateMemento();
            bool stable = false;
            try
            {
                // Native inventories are complete; a save during any managed
                // ledger line must retain the old model and the entire journal.
                BeginStableSaveSection("package_bookkeeping", null);
                stable = true;
                DiplomacyTransferRecovery.CommitPackage(package,
                    line => CompleteTransfer(package.TargetPlayer, line.GoodId,
                        line.Amount, "demand_package"),
                    () => RestoreManagedStateMemento(memento));
                _pendingPackage = null;
                _inventoryRecoveryBaseState = null;
                _goodsTransfersUnavailable = false;
            }
            catch
            {
                package.RollbackPending = true;
                throw;
            }
            finally
            {
                if (stable) EndStableSaveSection();
                PublishCombatProtectionSnapshot();
            }
            ClearV2GoodsOutcome(package.TargetPlayer);
        }

        private string AbortV2PendingPackage()
        {
            DiplomacyPendingPackage package = _pendingPackage;
            if (package == null) return null;
            package.RollbackPending = true;
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease)) return "native_inventory_busy";
            bool restored;
            using (lease)
                restored = DiplomacyTransferRecovery.Rollback(package, GoodAmount, RestoreGoodAmount);
            if (!restored) return "package_rollback_pending";
            _pendingPackage = null;
            if (_nativeTransferProbe == null)
            {
                _inventoryRecoveryBaseState = null;
                _goodsTransfersUnavailable = false;
            }
            return null;
        }

        private void RestoreV2PendingPackage(DiplomacyPendingPackage saved)
        {
            if (saved == null) return;
            _pendingPackage = DiplomacyTransferRecovery.Copy(saved);
            bool fullyApplied = !_pendingPackage.RollbackPending
                && _pendingPackage.Lines.All(DiplomacyTransferRecovery.HasCompletedNativeWrites);
            if (!fullyApplied)
            {
                IDisposable lease;
                if (!TryEnterNativeInventorySection(out lease))
                {
                    // Preserve commit intent while simulation owns the monitor.
                    // A later frame will classify the saved inventory pair.
                    _goodsTransfersUnavailable = true;
                    _inventoryRestorePending = true;
                    return;
                }
                try { using (lease) fullyApplied = DiplomacyTransferRecovery.IsFullyApplied(_pendingPackage, GoodAmount); }
                catch { }
            }
            _inventoryRestorePending = false;
            if (fullyApplied)
            {
                try { CommitV2PendingPackage(); return; }
                catch (Exception exception)
                { Log("demand_package", "status=restore_commit_failed|reason=" + Safe(exception.Message)); }
            }
            string failure = AbortV2PendingPackage();
            if (failure == "native_inventory_busy") _goodsTransfersUnavailable = true;
            else if (failure != null) DisableGoodsTransfers(failure);
            Log("demand_package", "status=" + (failure == null ? "save_rollback_complete" : "save_rollback_pending"));
        }

        private void RetryV2PackageRecovery()
        {
            if (_pendingPackage == null
                || _featureTicks < _inventoryRecoveryRetryTick) return;
            _inventoryRecoveryRetryTick = _featureTicks + 60;
            if (!_pendingPackage.RollbackPending)
            {
                RestoreV2PendingPackage(_pendingPackage);
                return;
            }
            if (AbortV2PendingPackage() == null)
                Log("demand_package", "status=deferred_rollback_complete");
        }
    }
}
#endif
