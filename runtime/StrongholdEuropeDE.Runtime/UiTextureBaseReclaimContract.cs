using System;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Dependency-free guard for the provider state required before built-in
    /// NoesisXaml texture fields may be rewired. The transaction deliberately
    /// preserves the reference count and URI so Noesis owns its full lifetime.
    /// </summary>
    internal static class UiTextureBaseReclaimContract
    {
        internal static bool TryValidateProviderState(
            int providerRefs,
            bool providerPointsAtOwnedOverride,
            out string failure)
        {
            failure = null;
            if (providerRefs < 1)
            {
                failure = "Noesis provider has no live reference";
                return false;
            }
            if (!providerPointsAtOwnedOverride)
            {
                failure = "Noesis provider does not point at the owned BC7 override";
                return false;
            }
            return true;
        }
    }
}
