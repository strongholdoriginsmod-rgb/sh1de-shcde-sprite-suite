using System;
using System.Linq;

namespace StrongholdEuropeDE.Runtime
{
    // 2026-09-08: shared by the live resource adapter and fault-injection tests.
    // A refund is authorized by a recorded write, never by an old stock total
    // alone. An interrupted refund retains the last proven checkpoint.
    internal static class DiplomacyTransferRecovery
    {
#if DIPLOMACY_V2
        internal static DiplomacySaveV1 RecoverySnapshot(DiplomacySaveV1 coherentSeed,
            DiplomacyPendingTransfer single, DiplomacyPendingPackage package, DiplomacyRules rules)
        {
            if (coherentSeed == null || (single == null && package == null))
                throw new InvalidOperationException("inventory recovery needs a coherent model and journal");
            var recovery = DiplomacySaveV2Codec.Deserialize(
                DiplomacySaveV2Codec.Serialize(coherentSeed, rules), rules);
            recovery.PendingTransfer = Copy(single);
            recovery.PendingPackage = Copy(package);
            recovery.PendingTeamTransition = null;
            if (recovery.PendingTransfer != null) recovery.PendingTransfer.RollbackPending = true;
            if (recovery.PendingPackage != null) recovery.PendingPackage.RollbackPending = true;
            return recovery;
        }
#endif

        internal static DiplomacyTransferProgress Copy(DiplomacyTransferProgress p)
        {
            return p == null ? null : new DiplomacyTransferProgress
            {
                SenderTouched = p.SenderTouched, RecipientTouched = p.RecipientTouched,
                SenderObserved = p.SenderObserved, RecipientObserved = p.RecipientObserved,
                SenderAfter = p.SenderAfter, RecipientAfter = p.RecipientAfter,
            };
        }

        internal static DiplomacyPendingTransfer Copy(DiplomacyPendingTransfer t)
        {
            return t == null ? null : new DiplomacyPendingTransfer
            {
                SenderPlayer = t.SenderPlayer, TargetPlayer = t.TargetPlayer,
                GoodId = t.GoodId, Amount = t.Amount, SenderBefore = t.SenderBefore,
                RecipientBefore = t.RecipientBefore, AlliedNativeTransfer = t.AlliedNativeTransfer,
                Purpose = t.Purpose, DirectAtomicTransfer = t.DirectAtomicTransfer,
                GameDay = t.GameDay, RollbackPending = t.RollbackPending, Progress = Copy(t.Progress),
            };
        }

        internal static DiplomacyPendingPackage Copy(DiplomacyPendingPackage p)
        {
            return p == null ? null : new DiplomacyPendingPackage
            {
                SenderPlayer = p.SenderPlayer, TargetPlayer = p.TargetPlayer,
                GameDay = p.GameDay, RollbackPending = p.RollbackPending,
                Lines = p.Lines.Select(Copy).ToList(),
            };
        }

        internal static void ApplyLine(DiplomacyPendingTransfer t,
            Func<int, int, int> read, Action<int, int, int> change)
        {
            if (t.Progress == null) t.Progress = new DiplomacyTransferProgress();
            if (t.RollbackPending || t.Progress.SenderTouched || t.Progress.RecipientTouched)
                throw new InvalidOperationException("transfer line was already attempted");
            // Recheck the sender immediately before touching him: preflight may
            // precede production, taxes or another mod's inventory operation.
            // Der Empfaenger wird hier NICHT mehr geprueft (10.09.2026): sein
            // Lager gehoert einer laufenden Wirtschaft und darf sich zwischen
            // Vorpruefung und Buchung bewegen, ohne dass die Sendung deshalb
            // falsch waere. Siehe DiplomacyTransferReceipt.IsSenderDebitConfirmed.
            if (read(t.SenderPlayer, t.GoodId) != t.SenderBefore)
                throw new InvalidOperationException("transfer inventory changed after preflight");
            t.Progress.SenderTouched = true;
            try { change(t.SenderPlayer, t.GoodId, -t.Amount); }
            finally { Observe(t, true, read); }
            if (t.Progress.SenderAfter != t.SenderBefore - t.Amount)
                throw new InvalidOperationException("transfer sender debit mismatch");
            t.Progress.RecipientTouched = true;
            try { change(t.TargetPlayer, t.GoodId, t.Amount); }
            finally { Observe(t, false, read); }
            // Kein Abgleich der Gutschrift mehr: der Empfaengerbestand ist
            // keine verlaessliche Groesse, solange dort produziert und
            // verbraucht wird. Observe prueft weiterhin auf negative Bestaende.
        }

        internal static void Observe(DiplomacyPendingTransfer t, bool sender,
            Func<int, int, int> read)
        {
            int amount = read(sender ? t.SenderPlayer : t.TargetPlayer, t.GoodId);
            if (amount < 0) throw new InvalidOperationException("negative inventory readback");
            if (sender) { t.Progress.SenderAfter = amount; t.Progress.SenderObserved = true; }
            else { t.Progress.RecipientAfter = amount; t.Progress.RecipientObserved = true; }
        }

        internal static bool HasCompletedNativeWrites(DiplomacyPendingTransfer t)
        {
            DiplomacyTransferProgress p = t.Progress;
            return !t.RollbackPending && p != null
                && p.SenderTouched && p.RecipientTouched && p.SenderObserved && p.RecipientObserved
                && p.SenderAfter == t.SenderBefore - t.Amount;
        }

        internal static bool IsFullyApplied(DiplomacyPendingPackage p, Func<int, int, int> read)
        {
            if (p.RollbackPending) return false;
            foreach (DiplomacyPendingTransfer t in p.Lines)
            {
                // Exact readbacks are durable proof of the mod's own writes.
                // Later production/consumption cannot revoke a completed gift.
                if (HasCompletedNativeWrites(t)) continue;
                if (t.Progress != null && (!t.Progress.SenderTouched || !t.Progress.RecipientTouched)) return false;
                // Nur die Senderseite, wie in IsSenderDebitConfirmed und
                // ApplyLine (10.09.2026). Sonst widerspraechen sich die drei
                // Pruefungen: eine Sendung gilt als gebucht, aber dasselbe
                // Paket gilt als nicht angewendet, weil der Empfaenger
                // inzwischen produziert oder verbraucht hat.
                if (read(t.SenderPlayer, t.GoodId) != t.SenderBefore - t.Amount)
                    return false;
            }
            return true;
        }

        internal static void CommitPackage(DiplomacyPendingPackage p,
            Action<DiplomacyPendingTransfer> commit, Action restoreManaged)
        {
            if (p.RollbackPending) throw new InvalidOperationException("rollback cannot grant deliveries");
            try
            {
                foreach (DiplomacyPendingTransfer line in p.Lines) commit(line);
            }
            catch
            {
                restoreManaged();
                p.RollbackPending = true;
                throw;
            }
        }

        internal static bool Rollback(DiplomacyPendingPackage p,
            Func<int, int, int> read, Func<int, int, int, bool> restore)
        {
            p.RollbackPending = true;
            bool complete = true;
            for (int i = p.Lines.Count - 1; i >= 0; i--)
                complete = Rollback(p.Lines[i], read, restore) && complete;
            return complete;
        }

        internal static bool Rollback(DiplomacyPendingTransfer t,
            Func<int, int, int> read, Func<int, int, int, bool> restore)
        {
            t.RollbackPending = true;
            bool recipient = RollbackSide(t, false, read, restore);
            bool sender = RollbackSide(t, true, read, restore);
            return recipient && sender;
        }

        private static bool RollbackSide(DiplomacyPendingTransfer t, bool sender,
            Func<int, int, int> read, Func<int, int, int, bool> restore)
        {
            DiplomacyTransferProgress p = t.Progress;
            if (p != null && !(sender ? p.SenderTouched : p.RecipientTouched)) return true;
            int player = sender ? t.SenderPlayer : t.TargetPlayer;
            int before = sender ? t.SenderBefore : t.RecipientBefore;
            int fullAfter = sender ? before - t.Amount : before + t.Amount;
            int current;
            try { current = read(player, t.GoodId); } catch { return false; }
            if (current == before) return true;
            // Do not adopt unrelated changes, even if a later refund would fit.
            if (current < Math.Min(before, fullAfter) || current > Math.Max(before, fullAfter)) return false;
            bool observed = p != null && (sender ? p.SenderObserved : p.RecipientObserved);
            int expected = observed ? (sender ? p.SenderAfter : p.RecipientAfter) : fullAfter;
            if (current != expected) return false;
            try { restore(player, t.GoodId, before); } catch { }
            int after;
            try { after = read(player, t.GoodId); } catch { return false; }
            // Readback, not an API return value, establishes refund progress.
            if (p != null && after >= Math.Min(current, before) && after <= Math.Max(current, before))
            {
                if (sender) { p.SenderAfter = after; p.SenderObserved = true; }
                else { p.RecipientAfter = after; p.RecipientObserved = true; }
            }
            return after == before;
        }
    }
}
