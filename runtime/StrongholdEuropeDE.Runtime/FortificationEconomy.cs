using System;

namespace StrongholdEuropeDE.Runtime
{
    internal enum FortificationEconomyContext : byte
    {
        Gameplay = 0,
        MapEditor = 1,
    }

    internal enum FortificationResource : byte
    {
        Wood = 1,
        Stone = 2,
    }

    /// <summary>
    /// A cost expressed exclusively in quarter goods. No floating-point value
    /// crosses this boundary: 1 means one quarter of one native good.
    /// </summary>
    internal readonly struct FortificationCost : IEquatable<FortificationCost>
    {
        internal FortificationCost(long woodQuarters, long stoneQuarters)
        {
            if (woodQuarters < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(woodQuarters));
            }
            if (stoneQuarters < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(stoneQuarters));
            }
            WoodQuarters = woodQuarters;
            StoneQuarters = stoneQuarters;
        }

        internal static FortificationCost Free =>
            new FortificationCost(0, 0);

        internal long WoodQuarters { get; }
        internal long StoneQuarters { get; }
        internal bool IsFree => WoodQuarters == 0 && StoneQuarters == 0;

        internal FortificationCost Multiply(int quantity)
        {
            if (quantity < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(quantity));
            }
            return new FortificationCost(
                checked(WoodQuarters * quantity),
                checked(StoneQuarters * quantity));
        }

        public bool Equals(FortificationCost other)
        {
            return WoodQuarters == other.WoodQuarters
                && StoneQuarters == other.StoneQuarters;
        }

        public override bool Equals(object obj)
        {
            return obj is FortificationCost other && Equals(other);
        }

        public override int GetHashCode()
        {
            unchecked
            {
                return (WoodQuarters.GetHashCode() * 397)
                    ^ StoneQuarters.GetHashCode();
            }
        }
    }

    /// <summary>
    /// Native inventory as whole goods. Fractional value is never represented
    /// here; it lives only in the prepaid-credit state below.
    /// </summary>
    internal readonly struct FortificationGoodsBalance :
        IEquatable<FortificationGoodsBalance>
    {
        internal FortificationGoodsBalance(long woodGoods, long stoneGoods)
        {
            if (woodGoods < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(woodGoods));
            }
            if (stoneGoods < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(stoneGoods));
            }
            WoodGoods = woodGoods;
            StoneGoods = stoneGoods;
        }

        internal long WoodGoods { get; }
        internal long StoneGoods { get; }

        public bool Equals(FortificationGoodsBalance other)
        {
            return WoodGoods == other.WoodGoods
                && StoneGoods == other.StoneGoods;
        }

        public override bool Equals(object obj)
        {
            return obj is FortificationGoodsBalance other && Equals(other);
        }

        public override int GetHashCode()
        {
            unchecked
            {
                return (WoodGoods.GetHashCode() * 397)
                    ^ StoneGoods.GetHashCode();
            }
        }
    }

    /// <summary>
    /// Prepaid fractional goods. Each resource is canonical in the range 0..3.
    /// The first quarter-cost placement debits one whole good and leaves three
    /// prepaid quarters; the next three consume that credit without a debit.
    /// </summary>
    internal readonly struct FortificationCreditBalance :
        IEquatable<FortificationCreditBalance>
    {
        internal FortificationCreditBalance(
            int woodQuarters,
            int stoneQuarters)
        {
            ValidateCredit(woodQuarters, nameof(woodQuarters));
            ValidateCredit(stoneQuarters, nameof(stoneQuarters));
            WoodQuarters = woodQuarters;
            StoneQuarters = stoneQuarters;
        }

        internal int WoodQuarters { get; }
        internal int StoneQuarters { get; }

        internal int ForResource(FortificationResource resource)
        {
            ValidateResource(resource, nameof(resource));
            return resource == FortificationResource.Wood
                ? WoodQuarters
                : StoneQuarters;
        }

        internal FortificationCreditBalance WithResource(
            FortificationResource resource,
            int creditQuarters)
        {
            ValidateResource(resource, nameof(resource));
            ValidateCredit(creditQuarters, nameof(creditQuarters));
            return resource == FortificationResource.Wood
                ? new FortificationCreditBalance(
                    creditQuarters,
                    StoneQuarters)
                : new FortificationCreditBalance(
                    WoodQuarters,
                    creditQuarters);
        }

        public bool Equals(FortificationCreditBalance other)
        {
            return WoodQuarters == other.WoodQuarters
                && StoneQuarters == other.StoneQuarters;
        }

        public override bool Equals(object obj)
        {
            return obj is FortificationCreditBalance other && Equals(other);
        }

        public override int GetHashCode()
        {
            return (WoodQuarters * 397) ^ StoneQuarters;
        }

        internal static void ValidateCredit(int value, string parameterName)
        {
            if (value < 0 || value > 3)
            {
                throw new ArgumentOutOfRangeException(
                    parameterName,
                    "Prepaid fortification credit must be in 0..3 quarters.");
            }
        }

        internal static void ValidateResource(
            FortificationResource resource,
            string parameterName)
        {
            if (resource != FortificationResource.Wood
                && resource != FortificationResource.Stone)
            {
                throw new ArgumentOutOfRangeException(parameterName);
            }
        }
    }

    internal readonly struct FortificationEconomyCreditRecord
    {
        internal FortificationEconomyCreditRecord(
            int playerId,
            FortificationResource resource,
            int creditQuarters)
        {
            if (playerId < 1 || playerId > 8)
            {
                throw new ArgumentOutOfRangeException(nameof(playerId));
            }
            FortificationCreditBalance.ValidateResource(
                resource,
                nameof(resource));
            FortificationCreditBalance.ValidateCredit(
                creditQuarters,
                nameof(creditQuarters));
            PlayerId = playerId;
            Resource = resource;
            CreditQuarters = creditQuarters;
        }

        internal int PlayerId { get; }
        internal FortificationResource Resource { get; }
        internal int CreditQuarters { get; }

        internal int StableKey =>
            (PlayerId << 8) | (int)Resource;
    }

    internal readonly struct FortificationPurchaseQuote
    {
        internal FortificationPurchaseQuote(
            FortificationCost totalCost,
            bool affordable,
            FortificationGoodsBalance goodsBefore,
            FortificationGoodsBalance nativeDebit,
            FortificationGoodsBalance goodsAfter,
            FortificationCreditBalance creditBefore,
            FortificationCreditBalance creditAfter,
            long missingWoodGoods,
            long missingStoneGoods)
        {
            TotalCost = totalCost;
            Affordable = affordable;
            GoodsBefore = goodsBefore;
            NativeDebit = nativeDebit;
            GoodsAfter = goodsAfter;
            CreditBefore = creditBefore;
            CreditAfter = creditAfter;
            MissingWoodGoods = missingWoodGoods;
            MissingStoneGoods = missingStoneGoods;
        }

        internal FortificationCost TotalCost { get; }
        internal bool Affordable { get; }
        internal FortificationGoodsBalance GoodsBefore { get; }
        internal FortificationGoodsBalance NativeDebit { get; }
        internal FortificationGoodsBalance GoodsAfter { get; }
        internal FortificationCreditBalance CreditBefore { get; }
        internal FortificationCreditBalance CreditAfter { get; }
        internal long MissingWoodGoods { get; }
        internal long MissingStoneGoods { get; }
    }

    internal static class FortificationEconomy
    {
        internal static FortificationPurchaseQuote Quote(
            FortificationVariantDefinition variant,
            FortificationGoodsBalance nativeGoods,
            FortificationCreditBalance prepaidCredit,
            int quantity,
            FortificationEconomyContext context)
        {
            if (variant == null)
            {
                throw new ArgumentNullException(nameof(variant));
            }
            if (quantity < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(quantity));
            }
            if (!Enum.IsDefined(typeof(FortificationEconomyContext), context))
            {
                throw new ArgumentOutOfRangeException(nameof(context));
            }
            if (variant.UsesNativeEconomy)
            {
                throw new InvalidOperationException(
                    "Native battlements retain the game's native economy.");
            }

            if (context == FortificationEconomyContext.MapEditor)
            {
                return new FortificationPurchaseQuote(
                    FortificationCost.Free,
                    affordable: true,
                    nativeGoods,
                    new FortificationGoodsBalance(0, 0),
                    nativeGoods,
                    prepaidCredit,
                    prepaidCredit,
                    missingWoodGoods: 0,
                    missingStoneGoods: 0);
            }

            FortificationCost total = variant.Cost.Multiply(quantity);
            ResourcePlan wood = PlanResource(
                total.WoodQuarters,
                nativeGoods.WoodGoods,
                prepaidCredit.WoodQuarters);
            ResourcePlan stone = PlanResource(
                total.StoneQuarters,
                nativeGoods.StoneGoods,
                prepaidCredit.StoneQuarters);
            bool affordable = wood.MissingGoods == 0
                && stone.MissingGoods == 0;
            FortificationGoodsBalance debit = new FortificationGoodsBalance(
                wood.NativeDebit,
                stone.NativeDebit);
            FortificationGoodsBalance goodsAfter = affordable
                ? new FortificationGoodsBalance(
                    nativeGoods.WoodGoods - wood.NativeDebit,
                    nativeGoods.StoneGoods - stone.NativeDebit)
                : nativeGoods;
            FortificationCreditBalance creditAfter = affordable
                ? new FortificationCreditBalance(
                    wood.CreditAfter,
                    stone.CreditAfter)
                : prepaidCredit;
            return new FortificationPurchaseQuote(
                total,
                affordable,
                nativeGoods,
                debit,
                goodsAfter,
                prepaidCredit,
                creditAfter,
                wood.MissingGoods,
                stone.MissingGoods);
        }

        internal static bool TryPurchase(
            FortificationVariantDefinition variant,
            FortificationGoodsBalance nativeGoods,
            FortificationCreditBalance prepaidCredit,
            int quantity,
            FortificationEconomyContext context,
            out FortificationGoodsBalance goodsAfter,
            out FortificationCreditBalance creditAfter,
            out FortificationGoodsBalance nativeDebit)
        {
            FortificationPurchaseQuote quote = Quote(
                variant,
                nativeGoods,
                prepaidCredit,
                quantity,
                context);
            goodsAfter = quote.GoodsAfter;
            creditAfter = quote.CreditAfter;
            nativeDebit = quote.NativeDebit;
            return quote.Affordable;
        }

        private static ResourcePlan PlanResource(
            long costQuarters,
            long nativeGoods,
            int prepaidCredit)
        {
            long creditConsumed = Math.Min(costQuarters, prepaidCredit);
            long uncoveredQuarters = costQuarters - creditConsumed;
            long nativeDebit = uncoveredQuarters / 4;
            if ((uncoveredQuarters % 4) != 0)
            {
                nativeDebit = checked(nativeDebit + 1);
            }
            long missingGoods = Math.Max(0, nativeDebit - nativeGoods);
            long creditAfter = uncoveredQuarters == 0
                ? prepaidCredit - creditConsumed
                : (4 - (uncoveredQuarters % 4)) % 4;
            if (creditAfter < 0 || creditAfter > 3)
            {
                throw new InvalidOperationException(
                    "Quarter-goods purchase produced non-canonical credit.");
            }
            return new ResourcePlan(
                nativeDebit,
                checked((int)creditAfter),
                missingGoods);
        }

        private readonly struct ResourcePlan
        {
            internal ResourcePlan(
                long nativeDebit,
                int creditAfter,
                long missingGoods)
            {
                NativeDebit = nativeDebit;
                CreditAfter = creditAfter;
                MissingGoods = missingGoods;
            }

            internal long NativeDebit { get; }
            internal int CreditAfter { get; }
            internal long MissingGoods { get; }
        }
    }
}
