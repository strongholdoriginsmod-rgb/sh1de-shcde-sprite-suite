using System;
using System.Collections.Generic;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Dependency-free startup sweep shared verbatim by the production patch
    /// and its executable harness. Only leases proven free by all three
    /// ownership views are removed and released.
    /// </summary>
    internal static class ScriptExtenderScanBufferScratchSweep<TLease>
        where TLease : class
    {
        internal static int ReleaseProvablyFree(
            IList<TLease> scratchPool,
            Func<TLease, bool> isLeased,
            Func<TLease, bool> hasOwner,
            Func<TLease, bool> isActive,
            Action<TLease> release)
        {
            if (scratchPool == null
                || isLeased == null
                || hasOwner == null
                || isActive == null
                || release == null)
            {
                throw new ArgumentNullException(
                    "Startup scratch sweep dependency is unavailable");
            }

            int released = 0;
            for (int index = scratchPool.Count - 1; index >= 0; index--)
            {
                TLease lease = scratchPool[index];
                if (lease == null)
                {
                    continue;
                }

                bool leased = isLeased(lease);
                bool owned = hasOwner(lease);
                bool active = isActive(lease);
                if (leased || owned || active)
                {
                    continue;
                }

                scratchPool.RemoveAt(index);
                release(lease);
                released = checked(released + 1);
            }
            return released;
        }
    }
}
