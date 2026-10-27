using System;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Installs the owned loader prefix before its URI bridge and rolls the
    /// shared Harmony owner back if either step fails. Kept dependency-free so
    /// the production ordering and rollback contract can run in the harness.
    /// </summary>
    internal static class UiTexturePatchTransaction
    {
        internal static void Apply(
            Action installOwnedLoader,
            Action installUriBridge,
            Action rollbackOwner)
        {
            if (installOwnedLoader == null)
            {
                throw new ArgumentNullException("installOwnedLoader");
            }
            if (installUriBridge == null)
            {
                throw new ArgumentNullException("installUriBridge");
            }
            if (rollbackOwner == null)
            {
                throw new ArgumentNullException("rollbackOwner");
            }

            try
            {
                installOwnedLoader();
                installUriBridge();
            }
            catch
            {
                try
                {
                    rollbackOwner();
                }
                catch
                {
                    // The original installation failure remains authoritative.
                    // Callers must also clear their prefix state so any patch
                    // that Harmony could not remove becomes an inert pass-through.
                }
                throw;
            }
        }
    }
}
