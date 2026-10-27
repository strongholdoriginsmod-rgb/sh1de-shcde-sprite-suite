#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace StrongholdEuropeDE.Runtime
{
    internal interface IDiplomacyV2NativeTradePort : IDiplomacyV2TradeWorld
    {
        // Exactly one authoritative engine monitor must be held during all
        // preflight, four mutations, readbacks, and in-place compensation.
        bool IsEngineSectionHeld { get; }
        void ChangeAmount(int player, int goodId, int signedDelta);
    }

    internal sealed class DiplomacyV2TradeWrite
    {
        internal int Player, Good, Delta, Before, Expected;
        internal bool Attempted, Observed;

        internal DiplomacyV2TradeWrite Clone()
        {
            return (DiplomacyV2TradeWrite)MemberwiseClone();
        }
    }

    // A save callback can run between ANY two native writes, including
    // while a Harmony observer is processing a single write. Persist the
    // attempted flag before mutation; never assume a returned void API call
    // is a successful credit. Subsequent loads reconcile exact cells only.
    internal sealed class DiplomacyV2TradeNativeJournal
    {
        internal long OfferId;
        internal int StartedDay;
        internal bool RollbackPending;
        internal readonly List<DiplomacyV2TradeWrite> Writes =
            new List<DiplomacyV2TradeWrite>(4);

        internal DiplomacyV2TradeNativeJournal Clone()
        {
            var clone = new DiplomacyV2TradeNativeJournal
            {
                OfferId = OfferId, StartedDay = StartedDay,
                RollbackPending = RollbackPending,
            };
            clone.Writes.AddRange(Writes.Select(w=>w.Clone()));
            return clone;
        }

        internal void Validate()
        {
            if (OfferId < 1 || StartedDay < 0 || Writes.Count != 4)
                throw new InvalidDataException("trade native journal identity or leg count invalid");
            var cells = new HashSet<string>(StringComparer.Ordinal);
            foreach (var write in Writes)
            {
                if (write.Player < 1 || write.Player > 8
                    || !DiplomacyV2TradeRules.IsAllowedGood(write.Good)
                    || write.Delta == 0
                    || Math.Abs((long)write.Delta) > DiplomacyV2TradeRules.MaximumGoodAmount
                    || write.Before < 0
                    || (long)write.Before + write.Delta != write.Expected
                    || write.Expected < 0
                    || (write.Observed && !write.Attempted)
                    || !cells.Add(write.Player + "/" + write.Good))
                    throw new InvalidDataException("trade native journal has invalid or repeated inventory cell");
            }
            if (Writes.Sum(w => (long)w.Delta) != 0)
                throw new InvalidDataException("trade must conserve total goods per commodity");
            // Actual conservation is per good, not across unrelated prices.
            foreach (int good in Writes.Select(w=>w.Good).Distinct())
            {
                if (Writes.Where(w=>w.Good==good).Sum(w=>(long)w.Delta)!=0)
                    throw new InvalidDataException("trade must conserve each good independently");
            }
        }

        internal static DiplomacyV2TradeNativeJournal Create(
            DiplomacyV2TradeQuote quote, IDiplomacyV2NativeTradePort port,
            int day)
        {
            if (!port.IsEngineSectionHeld)
                throw new InvalidOperationException("trade requires engine inventory monitor");
            string reason;
            if (!DiplomacyV2TradeRules.CanSettle(quote,port,day,out reason))
                throw new InvalidOperationException(reason);
            var journal = new DiplomacyV2TradeNativeJournal
            {
                OfferId=quote.Id,StartedDay=day,
            };
            AddPair(journal,port,quote.FromPlayer,quote.ToPlayer,
                quote.FromGood,quote.FromAmount);
            AddPair(journal,port,quote.ToPlayer,quote.FromPlayer,
                quote.ToGood,quote.ToAmount);
            journal.Validate();
            return journal;
        }

        private static void AddPair(DiplomacyV2TradeNativeJournal journal,
            IDiplomacyV2NativeTradePort port,int source,int target,
            int good,int amount)
        {
            int sender,recipient;
            if (!port.TryReadStock(source,good,out sender)
                || !port.TryReadStock(target,good,out recipient)
                || sender < amount || recipient > int.MaxValue-amount)
                throw new InvalidOperationException("real trade snapshot is unavailable");
            journal.Writes.Add(new DiplomacyV2TradeWrite
            {
                Player=source,Good=good,Delta=-amount,Before=sender,
                Expected=sender-amount,
            });
            journal.Writes.Add(new DiplomacyV2TradeWrite
            {
                Player=target,Good=good,Delta=amount,Before=recipient,
                Expected=recipient+amount,
            });
        }

        internal static void Apply(DiplomacyV2TradeNativeJournal journal,
            IDiplomacyV2NativeTradePort port)
        {
            journal.Validate();
            if (!port.IsEngineSectionHeld)
                throw new InvalidOperationException("native monitor missing");
            if (journal.RollbackPending || journal.Writes.Any(w=>w.Attempted))
                throw new InvalidOperationException("trade journal cannot replay a partial transaction");
            foreach (DiplomacyV2TradeWrite write in journal.Writes)
            {
                int actual;
                if (!port.TryReadStock(write.Player,write.Good,out actual)
                    || actual!=write.Before)
                    throw new InvalidOperationException("trade pre-write state changed");
                // This flag must precede the native API call and must survive
                // exceptions thrown by external hooked plugins.
                write.Attempted=true;
                port.ChangeAmount(write.Player,write.Good,write.Delta);
                write.Observed=true;
                if (!port.TryReadStock(write.Player,write.Good,out actual)
                    || actual!=write.Expected)
                    throw new InvalidOperationException("native trade credit/debit mismatch");
            }
        }

        internal bool FullyApplied(IDiplomacyV2NativeTradePort port)
        {
            if (!port.IsEngineSectionHeld || RollbackPending) return false;
            Validate();
            foreach (DiplomacyV2TradeWrite step in Writes)
            {
                int actual;
                if (!step.Attempted || !step.Observed
                    || !port.TryReadStock(step.Player,step.Good,out actual)
                    || actual!=step.Expected)
                    return false;
            }
            return true;
        }

        internal bool TryRollback(IDiplomacyV2NativeTradePort port,
            out string reason)
        {
            reason=null;
            if (!port.IsEngineSectionHeld)
            {
                reason="native_monitor_busy";
                return false;
            }
            RollbackPending=true;
            for(int index=Writes.Count-1;index>=0;index--)
            {
                DiplomacyV2TradeWrite step=Writes[index];
                if (!step.Attempted) continue;
                int actual;
                if (!port.TryReadStock(step.Player,step.Good,out actual))
                {
                    reason="native_rollback_read_unavailable";
                    return false;
                }
                // After a save/load another mod or the economy may own a new
                // value. Never write it back to an unrelated old stock total.
                if (actual==step.Before)
                {
                    step.Attempted=false;step.Observed=false;
                    continue;
                }
                if (actual!=step.Expected)
                {
                    reason="foreign_stock_mutation_not_owned";
                    return false;
                }
                try
                {
                    port.ChangeAmount(step.Player,step.Good,-step.Delta);
                }
                catch(Exception e)
                {
                    reason="native_rollback_"+e.GetType().Name;
                    return false;
                }
                if (!port.TryReadStock(step.Player,step.Good,out actual)
                    || actual!=step.Before)
                {
                    reason="native_rollback_readback_mismatch";
                    return false;
                }
                step.Attempted=false;
                step.Observed=false;
            }
            return true;
        }

        internal static void Write(BinaryWriter writer,
            DiplomacyV2TradeNativeJournal journal)
        {
            writer.Write(journal!=null);
            if (journal==null)return;
            journal.Validate();
            writer.Write(journal.OfferId);
            writer.Write(journal.StartedDay);
            writer.Write(journal.RollbackPending);
            foreach(var leg in journal.Writes)
            {
                writer.Write(leg.Player);writer.Write(leg.Good);
                writer.Write(leg.Delta);writer.Write(leg.Before);
                writer.Write(leg.Expected);writer.Write(leg.Attempted);
                writer.Write(leg.Observed);
            }
        }

        internal static DiplomacyV2TradeNativeJournal Read(BinaryReader reader)
        {
            if (!reader.ReadBoolean())return null;
            var j=new DiplomacyV2TradeNativeJournal
            {
                OfferId=reader.ReadInt64(),
                StartedDay=reader.ReadInt32(),
                RollbackPending=reader.ReadBoolean(),
            };
            for(int i=0;i<4;i++)
                j.Writes.Add(new DiplomacyV2TradeWrite
                {
                    Player=reader.ReadInt32(),Good=reader.ReadInt32(),
                    Delta=reader.ReadInt32(),Before=reader.ReadInt32(),
                    Expected=reader.ReadInt32(),Attempted=reader.ReadBoolean(),
                    Observed=reader.ReadBoolean(),
                });
            j.Validate();
            return j;
        }
    }
}
#endif
