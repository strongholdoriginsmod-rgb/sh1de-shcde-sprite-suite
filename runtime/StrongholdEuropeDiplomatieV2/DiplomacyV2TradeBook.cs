#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;

namespace StrongholdEuropeDE.Runtime
{
    // Session-owned authoritative journal; never a process-global list or
    // client-local queue. Exact per-offer IDs survive save/load and prevent
    // duplicate accept, counter, delivery or delayed AI answers.
    internal sealed class DiplomacyV2TradeBook
    {
        private readonly List<DiplomacyV2TradeQuote> _offers =
            new List<DiplomacyV2TradeQuote>();

        internal string MapFingerprint;
        internal long NextSequence = 1L;
        internal long LastSimulationTick = -1L;
        internal int LastAutonomousDay = -1;
        internal bool NativeRecoveryPending;
        internal long RecoveryOfferId;
        internal DiplomacyV2TradeNativeJournal NativeJournal;

        internal IReadOnlyList<DiplomacyV2TradeQuote> Offers
        {
            get { return _offers; }
        }

        internal DiplomacyV2TradeBook Clone()
        {
            var clone = new DiplomacyV2TradeBook
            {
                MapFingerprint = MapFingerprint,
                NextSequence = NextSequence,
                LastSimulationTick = LastSimulationTick,
                LastAutonomousDay = LastAutonomousDay,
                NativeRecoveryPending = NativeRecoveryPending,
                RecoveryOfferId = RecoveryOfferId,
                NativeJournal = NativeJournal == null ? null : NativeJournal.Clone(),
            };
            clone._offers.AddRange(_offers.Select(q => q.Clone()));
            return clone;
        }

        internal void StartNewMap(string fingerprint)
        {
            if (string.IsNullOrWhiteSpace(fingerprint) || fingerprint.Length > 256)
                throw new InvalidOperationException("trade map fingerprint is invalid");
            MapFingerprint = fingerprint;
            NextSequence = 1L;
            LastSimulationTick = -1L;
            LastAutonomousDay = -1;
            NativeRecoveryPending = false;
            RecoveryOfferId = 0L;
            NativeJournal = null;
            _offers.Clear();
        }

        internal void Validate(int saveDay)
        {
            if (string.IsNullOrWhiteSpace(MapFingerprint)
                || MapFingerprint.Length > 256 || NextSequence < 1
                || LastSimulationTick < -1 || LastAutonomousDay > saveDay
                || LastAutonomousDay < -1 || saveDay < 0
                || _offers.Count > DiplomacyV2TradeRules.MaximumRecordedOffers
                || (NativeRecoveryPending == (RecoveryOfferId == 0L)))
                throw new InvalidDataException("invalid persisted trade ledger");
            var seen = new HashSet<long>();
            foreach (DiplomacyV2TradeQuote quote in _offers)
            {
                if (DiplomacyV2TradeRules.ValidateQuote(quote) != null
                    || !string.Equals(quote.MapFingerprint,MapFingerprint,
                        StringComparison.Ordinal)
                    || quote.Id >= NextSequence || !seen.Add(quote.Id)
                    || quote.CreatedDay > saveDay
                    || quote.SettledDay > saveDay
                    || quote.CreatedDay > quote.SettledDay
                        && quote.SettledDay != -1)
                    throw new InvalidDataException("invalid persisted trade quote");
            }
            if (_offers.Count(q => q.AwaitingReply
                || q.Phase == DiplomacyV2TradePhase.Accepted
                || q.Phase == DiplomacyV2TradePhase.Settling
                || q.Phase == DiplomacyV2TradePhase.RecoveryRequired)
                > DiplomacyV2TradeRules.MaximumOpenOffers)
                throw new InvalidDataException("too many unresolved offers");
            if (NativeRecoveryPending && _offers.All(q => q.Id != RecoveryOfferId
                || q.Phase != DiplomacyV2TradePhase.RecoveryRequired))
                throw new InvalidDataException("trade recovery has no live journal");
            if (NativeJournal != null)
            {
                NativeJournal.Validate();
                if (_offers.All(q=>q.Id != NativeJournal.OfferId ||
                        (q.Phase!=DiplomacyV2TradePhase.Settling
                         && q.Phase!=DiplomacyV2TradePhase.RecoveryRequired)))
                    throw new InvalidDataException("native trade journal does not belong to a settling quote");
                if (NativeRecoveryPending && NativeJournal.OfferId!=RecoveryOfferId)
                    throw new InvalidDataException("trade recovery identity does not match its journal");
            }
            else if (NativeRecoveryPending || _offers.Any(q=>q.Phase==DiplomacyV2TradePhase.Settling))
                throw new InvalidDataException("unverified native trade requires a recovery journal");
        }

        internal DiplomacyV2TradeQuote Find(long sequence)
        {
            return _offers.FirstOrDefault(value => value.Id == sequence);
        }

        private void MakeSpace()
        {
            if (_offers.Count(q => !q.IsFinal)
                >= DiplomacyV2TradeRules.MaximumOpenOffers)
                throw new InvalidOperationException("trade offer limit reached");
            if (_offers.Count < DiplomacyV2TradeRules.MaximumRecordedOffers)
                return;
            DiplomacyV2TradeQuote oldest = _offers.Where(q => q.IsFinal)
                .OrderBy(q => q.Id).FirstOrDefault();
            if (oldest == null)
                throw new InvalidOperationException("trade history is full");
            _offers.Remove(oldest);
        }

        internal DiplomacyV2TradeQuote Submit(
            IDiplomacyV2TradeWorld world, int from, int to,
            int fromGood, int fromAmount, int toGood, int toAmount,
            int gameDay, int lifetimeDays, long parentId = 0,
            int counterRound = 0, int initialActor = 0)
        {
            if (world == null) throw new ArgumentNullException("world");
            if (NativeRecoveryPending)
                throw new InvalidOperationException("trade recovery is not complete");
            if (gameDay < 0 || lifetimeDays < 1
                || lifetimeDays > DiplomacyV2TradeRules.MaximumOfferLifetimeDays
                || gameDay > int.MaxValue - lifetimeDays
                || NextSequence == long.MaxValue)
                throw new InvalidOperationException("trade validity or sequence exhausted");
            if (!world.IsAlive(from) || !world.IsAlive(to)
                || !world.CanTrade(from,to,gameDay))
                throw new InvalidOperationException("no current trade treaty");
            MakeSpace();
            var item = new DiplomacyV2TradeQuote
            {
                Id = NextSequence, ParentId = parentId,
                OriginPlayer = initialActor <= 0 ? from : initialActor,
                FromPlayer = from, ToPlayer = to,
                FromGood = fromGood, ToGood = toGood,
                FromAmount = fromAmount, ToAmount = toAmount,
                CreatedDay = gameDay, ExpiresDay = gameDay + lifetimeDays,
                Revision = counterRound, Phase = DiplomacyV2TradePhase.Pending,
                MapFingerprint = MapFingerprint,
            };
            item.ResponseTicksRemaining = DiplomacyV2TradeRules.AiAnswerDelayTicks(item);
            string error = DiplomacyV2TradeRules.ValidateQuote(item);
            if (error != null)
                throw new InvalidOperationException(error);
            // Mandatory check at submission, not just later at settlement.
            // A sender cannot promise goods that do not exist or exceed reserve.
            int senderStock, senderReserve, recipientRoom;
            if (!world.TryReadStock(from,fromGood,out senderStock)
                || !world.TryReadStorageRoom(to,fromGood,out recipientRoom))
                throw new InvalidOperationException("offer has unverified stock or capacity");
            senderReserve = world.SafetyReserve(from,fromGood);
            if (senderReserve < 0 || senderStock - (long)fromAmount < senderReserve
                || recipientRoom < fromAmount)
                throw new InvalidOperationException("offer exceeds stock, reserve or capacity");
            // An offer cannot claim another ruler has resources that are not
            // actually there. Both legs are checked at submission AND again
            // on acceptance, even though production can change between them.
            int otherStock,ourRoom;
            if (!world.TryReadStock(to,toGood,out otherStock)
                || !world.TryReadStorageRoom(from,toGood,out ourRoom))
                throw new InvalidOperationException("counterpart stock/capacity cannot be verified");
            int otherReserve=world.SafetyReserve(to,toGood);
            if (otherReserve<0 || otherStock-(long)toAmount<otherReserve
                || ourRoom<toAmount)
                throw new InvalidOperationException("counterpart lacks stock, reserve or storage capacity");
            _offers.Add(item);
            NextSequence++;
            return item.Clone();
        }

        internal DiplomacyV2TradeQuote Counter(
            IDiplomacyV2TradeWorld world, long offerId, int replyingPlayer,
            int newFromAmount, int newToAmount, int day, int lifetimeDays)
        {
            DiplomacyV2TradeQuote source = Find(offerId);
            if (source == null || !source.AwaitingReply
                || source.ToPlayer != replyingPlayer || day >= source.ExpiresDay
                || source.Revision >= DiplomacyV2TradeRules.MaximumCounterRounds)
                throw new InvalidOperationException("cannot counter stale or foreign offer");
            DiplomacyV2TradeQuote next = Submit(
                world, source.ToPlayer, source.FromPlayer,
                source.ToGood, newFromAmount, source.FromGood, newToAmount,
                day, lifetimeDays, source.Id, source.Revision + 1,
                source.OriginPlayer);
            source.Phase = DiplomacyV2TradePhase.Countered;
            source.RecipientDecision = "countered";
            return next;
        }

        internal bool Reply(long id, int actor, bool accepted,
            IDiplomacyV2TradeWorld world, int day, bool humanConfirmed)
        {
            DiplomacyV2TradeQuote item = Find(id);
            if (item == null || !item.AwaitingReply
                || item.ToPlayer != actor || day < item.CreatedDay
                || day >= item.ExpiresDay || NativeRecoveryPending
                || !world.IsAlive(item.FromPlayer) || !world.IsAlive(item.ToPlayer)
                || !world.CanTrade(item.FromPlayer,item.ToPlayer,day)
                || (world.IsHuman(actor) && !humanConfirmed))
                return false;
            // A signed human answer is owned by the receiving player. The
            // caller checks the authenticated local/network player ID.
            item.Phase = accepted
                ? DiplomacyV2TradePhase.Accepted
                : DiplomacyV2TradePhase.Declined;
            item.RecipientDecision = accepted ? "accepted" : "declined";
            return true;
        }

        internal void Expire(int day, IDiplomacyV2TradeWorld world)
        {
            foreach (DiplomacyV2TradeQuote item in _offers)
            {
                if (item.AwaitingReply || item.Phase == DiplomacyV2TradePhase.Accepted)
                {
                    if (day >= item.ExpiresDay || !world.IsAlive(item.FromPlayer)
                        || !world.IsAlive(item.ToPlayer)
                        || !world.CanTrade(item.FromPlayer,item.ToPlayer,day))
                    {
                        item.Phase = DiplomacyV2TradePhase.Expired;
                        item.RecipientDecision = "invalidated";
                    }
                }
            }
        }

        internal DiplomacyV2TradeQuote[] Tick(long simulationTick,
            int day, IDiplomacyV2TradeWorld world)
        {
            if (world == null) throw new ArgumentNullException("world");
            Expire(day,world);
            if (LastSimulationTick < 0 || simulationTick < LastSimulationTick)
            {
                LastSimulationTick = simulationTick;
                return Array.Empty<DiplomacyV2TradeQuote>();
            }
            if (simulationTick == LastSimulationTick)
                return Array.Empty<DiplomacyV2TradeQuote>();
            long delta = Math.Min(DiplomacyV2TradeRules.MaximumPendingTicks,
                simulationTick - LastSimulationTick);
            LastSimulationTick = simulationTick;
            var due = new List<DiplomacyV2TradeQuote>();
            foreach (DiplomacyV2TradeQuote item in _offers.OrderBy(q => q.Id))
            {
                if (!item.AwaitingReply || world.IsHuman(item.ToPlayer))
                    continue;
                item.ResponseTicksRemaining = (int)Math.Max(0L,
                    item.ResponseTicksRemaining - delta);
                if (item.ResponseTicksRemaining == 0)
                    due.Add(item.Clone());
            }
            return due.ToArray();
        }

        internal bool MarkSettling(long offerId, int day, IDiplomacyV2NativeTradePort world)
        {
            DiplomacyV2TradeQuote quote = Find(offerId);
            string failure;
            if (NativeRecoveryPending || NativeJournal != null
                || !world.IsEngineSectionHeld
                || !DiplomacyV2TradeRules.CanSettle(quote,world,day,out failure))
                return false;
            // Build the complete 4-cell, four-step recovery snapshot BEFORE
            // any native inventory mutation, within the same engine lock.
            DiplomacyV2TradeNativeJournal snapshot =
                DiplomacyV2TradeNativeJournal.Create(quote,world,day);
            NativeJournal = snapshot;
            quote.Phase = DiplomacyV2TradePhase.Settling;
            return true;
        }

        internal void MarkCompleted(long offerId, int day)
        {
            DiplomacyV2TradeQuote quote = Find(offerId);
            if (quote == null || quote.Phase != DiplomacyV2TradePhase.Settling
                || NativeRecoveryPending)
                throw new InvalidOperationException("trade completion lacks a native settlement");
            quote.Phase = DiplomacyV2TradePhase.Completed;
            quote.SettledDay = day;
            quote.Failure = null;
            NativeJournal = null;
        }

        internal void MarkRecovery(long offerId, string failure)
        {
            DiplomacyV2TradeQuote quote = Find(offerId);
            if (quote == null || quote.Phase != DiplomacyV2TradePhase.Settling)
                throw new InvalidOperationException("cannot journal unknown trade");
            quote.Phase = DiplomacyV2TradePhase.RecoveryRequired;
            quote.Failure = (failure ?? "unverified_native_rollback")
                .Substring(0,Math.Min(256,(failure ?? "unverified_native_rollback").Length));
            NativeRecoveryPending = true;
            RecoveryOfferId = offerId;
        }

        internal void MarkRollbackComplete(long offerId)
        {
            if (!NativeRecoveryPending || RecoveryOfferId != offerId)
                throw new InvalidOperationException("unowned trade rollback");
            DiplomacyV2TradeQuote quote = Find(offerId);
            if (quote == null || quote.Phase != DiplomacyV2TradePhase.RecoveryRequired)
                throw new InvalidOperationException("trade recovery not present");
            quote.Phase = DiplomacyV2TradePhase.Cancelled;
            NativeRecoveryPending = false;
            RecoveryOfferId = 0L;
            NativeJournal = null;
        }

        internal static void Write(BinaryWriter writer,DiplomacyV2TradeBook book,
            int saveDay,string mapFingerprint)
        {
            if (book == null) book = new DiplomacyV2TradeBook
            {
                MapFingerprint = mapFingerprint,
            };
            book.Validate(saveDay);
            if (!string.Equals(book.MapFingerprint,mapFingerprint,StringComparison.Ordinal))
                throw new InvalidDataException("trade map fingerprint changed");
            writer.Write(1); // trade wire format v1, within diplomacy schema 14+
            writer.Write(book.MapFingerprint);
            writer.Write(book.NextSequence);
            writer.Write(book.LastSimulationTick);
            writer.Write(book.LastAutonomousDay);
            writer.Write(book.NativeRecoveryPending);
            writer.Write(book.RecoveryOfferId);
            writer.Write(book._offers.Count);
            foreach (DiplomacyV2TradeQuote q in book._offers.OrderBy(x=>x.Id))
            {
                writer.Write(q.Id); writer.Write(q.ParentId);
                writer.Write(q.OriginPlayer); writer.Write(q.FromPlayer);
                writer.Write(q.ToPlayer); writer.Write(q.FromGood);
                writer.Write(q.FromAmount); writer.Write(q.ToGood);
                writer.Write(q.ToAmount); writer.Write(q.CreatedDay);
                writer.Write(q.ExpiresDay); writer.Write(q.ResponseTicksRemaining);
                writer.Write(q.Revision); writer.Write((int)q.Phase);
                writer.Write(q.MapFingerprint);
                writer.Write(q.RecipientDecision??"");
                writer.Write(q.Failure??"");
                writer.Write(q.SettledDay);
            }
            DiplomacyV2TradeNativeJournal.Write(writer,book.NativeJournal);
        }

        internal static DiplomacyV2TradeBook Read(BinaryReader reader,
            int saveDay,string mapFingerprint)
        {
            if (reader.ReadInt32()!=1)
                throw new InvalidDataException("trade journal wire version unsupported");
            var book=new DiplomacyV2TradeBook();
            book.MapFingerprint=reader.ReadString();
            book.NextSequence=reader.ReadInt64();
            book.LastSimulationTick=reader.ReadInt64();
            book.LastAutonomousDay=reader.ReadInt32();
            book.NativeRecoveryPending=reader.ReadBoolean();
            book.RecoveryOfferId=reader.ReadInt64();
            int count=reader.ReadInt32();
            if (count<0 || count>DiplomacyV2TradeRules.MaximumRecordedOffers)
                throw new InvalidDataException("trade journal exceeds offer bound");
            for(int i=0;i<count;i++)
            {
                var q=new DiplomacyV2TradeQuote
                {
                    Id=reader.ReadInt64(),ParentId=reader.ReadInt64(),
                    OriginPlayer=reader.ReadInt32(),FromPlayer=reader.ReadInt32(),
                    ToPlayer=reader.ReadInt32(),FromGood=reader.ReadInt32(),
                    FromAmount=reader.ReadInt32(),ToGood=reader.ReadInt32(),
                    ToAmount=reader.ReadInt32(),CreatedDay=reader.ReadInt32(),
                    ExpiresDay=reader.ReadInt32(),ResponseTicksRemaining=reader.ReadInt32(),
                    Revision=reader.ReadInt32(),
                    Phase=(DiplomacyV2TradePhase)reader.ReadInt32(),
                    MapFingerprint=reader.ReadString(),
                    RecipientDecision=reader.ReadString(),Failure=reader.ReadString(),
                    SettledDay=reader.ReadInt32(),
                };
                book._offers.Add(q);
            }
            book.NativeJournal=DiplomacyV2TradeNativeJournal.Read(reader);
            book.Validate(saveDay);
            if (!string.Equals(book.MapFingerprint,mapFingerprint,StringComparison.Ordinal))
                throw new InvalidDataException("trade journal has foreign map fingerprint");
            return book;
        }
    }
}
#endif
