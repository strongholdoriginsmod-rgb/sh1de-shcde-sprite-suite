using System;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Durability relative to the native normal wall. A ratio of 3/2 means
    /// 150 percent durability, so incoming damage is multiplied by 2/3.
    /// </summary>
    internal readonly struct FortificationDurabilityRatio :
        IEquatable<FortificationDurabilityRatio>
    {
        internal FortificationDurabilityRatio(int numerator, int denominator)
        {
            if (numerator <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(numerator));
            }
            if (denominator <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(denominator));
            }
            if (GreatestCommonDivisor(numerator, denominator) != 1)
            {
                throw new ArgumentException(
                    "Durability ratios must be stored in lowest terms.");
            }
            Numerator = numerator;
            Denominator = denominator;
        }

        internal int Numerator { get; }
        internal int Denominator { get; }

        public bool Equals(FortificationDurabilityRatio other)
        {
            return Numerator == other.Numerator
                && Denominator == other.Denominator;
        }

        public override bool Equals(object obj)
        {
            return obj is FortificationDurabilityRatio other && Equals(other);
        }

        public override int GetHashCode()
        {
            unchecked
            {
                return (Numerator * 397) ^ Denominator;
            }
        }

        private static int GreatestCommonDivisor(int left, int right)
        {
            while (right != 0)
            {
                int remainder = left % right;
                left = right;
                right = remainder;
            }
            return left;
        }
    }

    internal readonly struct FortificationDamageResult
    {
        internal FortificationDamageResult(int scaledDamage, int remainder)
        {
            ScaledDamage = scaledDamage;
            Remainder = remainder;
        }

        internal int ScaledDamage { get; }
        internal int Remainder { get; }
    }

    internal static class FortificationDamageScaler
    {
        /// <summary>
        /// Scales one non-negative native damage amount with exact integer
        /// arithmetic. The remainder is carried in units of the ratio's
        /// numerator, making a sequence equivalent to scaling its total once.
        /// </summary>
        internal static FortificationDamageResult ScaleIncomingDamage(
            int incomingDamage,
            FortificationDurabilityRatio durability,
            int remainder)
        {
            if (incomingDamage < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(incomingDamage));
            }
            ValidateRemainder(durability, remainder);

            long dividend = checked(
                ((long)incomingDamage * durability.Denominator) + remainder);
            long scaled = dividend / durability.Numerator;
            int nextRemainder = checked((int)(
                dividend % durability.Numerator));
            if (scaled > int.MaxValue)
            {
                throw new OverflowException(
                    "Scaled fortification damage exceeds Int32.MaxValue.");
            }
            return new FortificationDamageResult(
                checked((int)scaled),
                nextRemainder);
        }

        internal static FortificationDamageResult ScaleIncomingDamage(
            FortificationVariantDefinition variant,
            int incomingDamage,
            int remainder)
        {
            if (variant == null)
            {
                throw new ArgumentNullException(nameof(variant));
            }
            return ScaleIncomingDamage(
                incomingDamage,
                variant.Durability,
                remainder);
        }

        internal static void ValidateRemainder(
            FortificationDurabilityRatio durability,
            int remainder)
        {
            if (durability.Numerator <= 0 || durability.Denominator <= 0)
            {
                throw new ArgumentException(
                    "Durability ratio is uninitialized or invalid.",
                    nameof(durability));
            }
            if (remainder < 0 || remainder >= durability.Numerator)
            {
                throw new ArgumentOutOfRangeException(
                    nameof(remainder),
                    "Damage remainder must be smaller than the durability "
                    + "numerator.");
            }
        }
    }
}
