using System;
using System.Collections.Generic;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>Pure damage-row policy, kept separate from native mutation.</summary>
    internal static class WorkerMilitiaDamagePlan
    {
        internal static int[] FromMacemanRow(
            IReadOnlyList<int> macemanDamage,
            int divisor)
        {
            if (macemanDamage == null || macemanDamage.Count == 0)
            {
                throw new ArgumentException(
                    "Maceman damage row is empty",
                    "macemanDamage");
            }
            if (divisor < 2 || divisor > 16)
            {
                throw new ArgumentOutOfRangeException(
                    "divisor",
                    "Militia damage divisor must be within 2..16");
            }
            var result = new int[macemanDamage.Count];
            for (int index = 0; index < result.Length; index++)
            {
                int source = macemanDamage[index];
                if (source < 0)
                {
                    throw new InvalidOperationException(
                        "Maceman damage is negative at column " + index);
                }
                result[index] = source == 0 ? 0 : Math.Max(1, source / divisor);
                if (result[index] > source)
                {
                    throw new InvalidOperationException(
                        "Derived militia damage exceeds maceman damage at column "
                        + index);
                }
            }
            return result;
        }
    }
}
