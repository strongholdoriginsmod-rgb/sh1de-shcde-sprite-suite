#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    // One verified offer per decision. A trade is not a gift and an accepted
    // quote is NEVER the same thing as a completed native stock transfer.
    internal enum DiplomacyV2TradePhase
    {
        Pending = 1, Countered = 2, Accepted = 3, Declined = 4,
        Expired = 5, Settling = 6, Completed = 7, RecoveryRequired = 8,
        Cancelled = 9,
    }

    internal sealed class DiplomacyV2TradeQuote
    {
        internal long Id;
        internal long ParentId;
        internal int OriginPlayer;
        internal int FromPlayer;
        internal int ToPlayer;
        internal int FromGood;
        internal int FromAmount;
        internal int ToGood;
        internal int ToAmount;
        internal int CreatedDay;
        internal int ExpiresDay;
        internal int ResponseTicksRemaining;
        internal int Revision;
        internal DiplomacyV2TradePhase Phase;
        internal string MapFingerprint;
        internal string RecipientDecision;
        internal string Failure;
        internal int SettledDay = -1;

        internal DiplomacyV2TradeQuote Clone()
        {
            return (DiplomacyV2TradeQuote)MemberwiseClone();
        }

        internal bool AwaitingReply
        {
            get { return Phase == DiplomacyV2TradePhase.Pending; }
        }

        internal bool IsFinal
        {
            get
            {
                return Phase == DiplomacyV2TradePhase.Completed
                    || Phase == DiplomacyV2TradePhase.Cancelled
                    || Phase == DiplomacyV2TradePhase.Countered
                    || Phase == DiplomacyV2TradePhase.Declined
                    || Phase == DiplomacyV2TradePhase.Expired;
            }
        }
    }

    internal interface IDiplomacyV2TradeWorld
    {
        bool IsAlive(int player);
        bool IsHuman(int player);
        // Called at creation, response and immediately before native writes.
        bool CanTrade(int playerA, int playerB, int gameDay);
        bool TryReadStock(int player, int goodId, out int amount);
        // Return false when the engine cannot prove real recipient headroom.
        bool TryReadStorageRoom(int player, int goodId, out int room);
        int SafetyReserve(int player, int goodId);
        int MarketUnitValue(int goodId);
    }

    internal static class DiplomacyV2TradeRules
    {
        internal const int MaximumGoodAmount = 50000;
        internal const int MaximumMarketUnitValue = 100000;
        internal const int MaximumOfferLifetimeDays = 8;
        internal const int MaximumCounterRounds = 3;
        internal const int MaximumOpenOffers = 24;
        internal const int MaximumRecordedOffers = 64;
        internal const int MaximumPendingTicks = 2400;
        internal const int GoldGoodId = 15;

        internal static readonly int[] Goods =
        {
            2, 3, 4, 6, 7, 9, 10, 11, 12, 13, 14, 15,
            16, 17, 18, 19, 20, 21, 22, 23, 24,
        };

        internal static bool IsAllowedGood(int goodId)
        {
            return Array.BinarySearch(Goods, goodId) >= 0;
        }

        internal static bool CanTrade(RelationState relation, int day,
            bool atWar, bool partiesAlive)
        {
            if (relation == null || relation.V2 == null || atWar
                || !partiesAlive || day < 0) return false;
            DiplomacyV2RelationState v2 = relation.V2;
            // War cancels trade; a truce alone does not grant trade rights.
            if (v2.Stage == DiplomacyV2NegotiationStage.Hostile
                || v2.Stage == DiplomacyV2NegotiationStage.Blocked)
                return false;
            if (relation.Allied && v2.Agreement == DiplomacyV2AgreementKind.Alliance)
                return true;
            return v2.Agreement == DiplomacyV2AgreementKind.TradePact
                && v2.AgreementUntilDay > day;
        }

        internal static string ValidateQuote(DiplomacyV2TradeQuote q)
        {
            if (q == null || q.Id < 1 || q.ParentId < 0
                || q.ParentId >= q.Id
                || q.OriginPlayer < 1 || q.OriginPlayer > 8
                || q.FromPlayer < 1 || q.FromPlayer > 8
                || q.ToPlayer < 1 || q.ToPlayer > 8
                || q.FromPlayer == q.ToPlayer
                || (q.OriginPlayer != q.FromPlayer && q.OriginPlayer != q.ToPlayer)
                || !IsAllowedGood(q.FromGood) || !IsAllowedGood(q.ToGood)
                || q.FromGood == q.ToGood
                || q.FromAmount < 1 || q.FromAmount > MaximumGoodAmount
                || q.ToAmount < 1 || q.ToAmount > MaximumGoodAmount
                || q.CreatedDay < 0 || q.ExpiresDay <= q.CreatedDay
                || (long)q.ExpiresDay - q.CreatedDay > MaximumOfferLifetimeDays
                || q.ResponseTicksRemaining < 0
                || q.ResponseTicksRemaining > MaximumPendingTicks
                || q.Revision < 0 || q.Revision > MaximumCounterRounds
                || string.IsNullOrWhiteSpace(q.MapFingerprint)
                || q.MapFingerprint.Length > 256
                || !Enum.IsDefined(typeof(DiplomacyV2TradePhase), q.Phase)
                || (q.Failure != null && q.Failure.Length > 256)
                || (q.RecipientDecision != null && q.RecipientDecision.Length > 40))
                return "invalid trade identity, quantity, validity or phase";
            return null;
        }

        internal static bool CanSettle(DiplomacyV2TradeQuote q,
            IDiplomacyV2TradeWorld world, int gameDay, out string failure)
        {
            failure = null;
            string invalid = ValidateQuote(q);
            if (invalid != null || q.Phase != DiplomacyV2TradePhase.Accepted)
            {
                failure = invalid ?? "not accepted";
                return false;
            }
            if (gameDay < q.CreatedDay || gameDay >= q.ExpiresDay
                || !world.IsAlive(q.FromPlayer) || !world.IsAlive(q.ToPlayer)
                || !world.CanTrade(q.FromPlayer,q.ToPlayer,gameDay))
            {
                failure = "expired, dead or no longer entitled to trade";
                return false;
            }
            foreach (var leg in new[]
            {
                new { Seller=q.FromPlayer, Buyer=q.ToPlayer, Good=q.FromGood, Amount=q.FromAmount },
                new { Seller=q.ToPlayer, Buyer=q.FromPlayer, Good=q.ToGood, Amount=q.ToAmount },
            })
            {
                int stock, room;
                if (!world.TryReadStock(leg.Seller,leg.Good,out stock)
                    || !world.TryReadStorageRoom(leg.Buyer,leg.Good,out room))
                {
                    failure = "unverified original stock or storage capacity";
                    return false;
                }
                int reserve = world.SafetyReserve(leg.Seller,leg.Good);
                if (reserve < 0 || stock < leg.Amount
                    || (long)stock - leg.Amount < reserve || room < leg.Amount)
                {
                    failure = "insufficient real stock, strategic reserve or recipient capacity";
                    return false;
                }
            }
            return true;
        }

        // Stable simulation-only decision: never use Random(), wall time,
        // machine hash seed, UI frame count or network arrival order.
        internal static uint StableRoll(string key, long sequence, int day)
        {
            uint result = 2166136261U;
            string data = key + ":" + sequence.ToString(CultureInfo.InvariantCulture)
                + ":" + day.ToString(CultureInfo.InvariantCulture);
            foreach (byte part in Encoding.UTF8.GetBytes(data))
                result = unchecked((result ^ part) * 16777619U);
            return result;
        }

        internal static int AiAnswerDelayTicks(DiplomacyV2TradeQuote offer)
        {
            return 80 + (int)(StableRoll(offer.MapFingerprint,offer.Id,
                offer.CreatedDay) % 401U);
        }

        internal static bool AiAccepts(DiplomacyV2TradeQuote q,
            IDiplomacyV2TradeWorld world, DiplomacyV2RelationState relationship,
            int gameDay)
        {
            int incomeStock, requestedStock, receiveRoom;
            if (!world.TryReadStock(q.ToPlayer,q.FromGood,out incomeStock)
                || !world.TryReadStock(q.ToPlayer,q.ToGood,out requestedStock)
                || !world.TryReadStorageRoom(q.ToPlayer,q.FromGood,out receiveRoom)
                || receiveRoom < q.FromAmount
                || requestedStock < q.ToAmount
                || requestedStock - q.ToAmount
                    < world.SafetyReserve(q.ToPlayer,q.ToGood))
                return false;
            int receiveValue = world.MarketUnitValue(q.FromGood);
            int giveValue = world.MarketUnitValue(q.ToGood);
            if (receiveValue < 1 || giveValue < 1
                || receiveValue > MaximumMarketUnitValue
                || giveValue > MaximumMarketUnitValue)
                return false;

            long benefit = (long)receiveValue * q.FromAmount;
            long cost = (long)giveValue * q.ToAmount;
            // Requested weapon/food below safety reserve is genuinely useful;
            // trading away one's own reserve is ruled out above.
            if (incomeStock < world.SafetyReserve(q.ToPlayer,q.FromGood))
                benefit = benefit * 3L / 2L;
            if (requestedStock > world.SafetyReserve(q.ToPlayer,q.ToGood) * 3L)
                cost = cost * 9L / 10L;
            long thresholdPercent = 100L;
            if (relationship != null)
            {
                if (relationship.Personality == DiplomacyV2PersonalityKind.Mercantile)
                    thresholdPercent = 120L;
                else if (relationship.Personality == DiplomacyV2PersonalityKind.Wary)
                    thresholdPercent = 115L;
                else if (relationship.Personality == DiplomacyV2PersonalityKind.Loyal)
                    thresholdPercent = 90L;
            }
            // Vassals accept tight bargains exceptionally often ONLY AFTER
            // hard inventory/capacity/strategic feasibility passes.
            bool directVassal = relationship != null
                && relationship.VassalPlayerId == q.ToPlayer
                && relationship.VassalOverlordPlayerId == q.FromPlayer;
            if (directVassal)
            {
                if (benefit <= 0L) return false;
                uint roll = StableRoll(q.MapFingerprint,q.Id,q.CreatedDay);
                return roll % 10000U < (uint)(9750L
                    + Math.Min(200L, (long)Math.Max(0m, relationship.Trust) * 2L));
            }
            // Personality and trust affect borderline proposals, never conjure
            // goods. Deterministic noise only in the economically useful band.
            if (benefit * 100L < cost * thresholdPercent * 80L / 100L)
                return false;
            if (benefit * 100L >= cost * thresholdPercent * 115L / 100L)
                return true;
            int chance = (int)Math.Max(10m, Math.Min(90m,
                35m + (relationship==null?50m:relationship.Trust) / 3m
                + (relationship==null?50m:relationship.Reliability) / 5m
                - (relationship==null?0m:relationship.Grudge) / 5m));
            return StableRoll(q.MapFingerprint,q.Id,gameDay) % 100U
                < (uint)chance;
        }
    }
}
#endif
