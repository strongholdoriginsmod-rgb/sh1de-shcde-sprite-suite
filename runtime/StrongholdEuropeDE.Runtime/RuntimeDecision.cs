using System;
using System.IO;

namespace StrongholdEuropeDE.Runtime
{
    internal static class RuntimeDecision
    {
        internal static bool ShouldActivateAudio(
            bool supportedRuntime,
            bool manifestValid,
            bool payloadDeclared,
            bool payloadValid)
        {
            return supportedRuntime && manifestValid && payloadDeclared && payloadValid;
        }

        internal static bool ShouldApplyFoliage(
            bool supportedRuntime,
            bool featureEnabled,
            bool atlasExists,
            int materialSlotCount,
            bool everySlotUsesTeamColour,
            bool everySlotSharesTeamMask,
            bool foliageShaderAvailable,
            bool exactOverrideTexturesReady)
        {
            return supportedRuntime
                && featureEnabled
                && atlasExists
                && materialSlotCount == 7
                && everySlotUsesTeamColour
                && everySlotSharesTeamMask
                && foliageShaderAvailable
                && exactOverrideTexturesReady;
        }

        internal static bool ShouldRestoreOwnedReference(object current, object owned)
        {
            return ReferenceEquals(current, owned);
        }

        internal static bool SupportsPinnedRosterLocale(string locale)
        {
            return string.Equals(locale, "dede", StringComparison.Ordinal);
        }

        internal static bool TryBeginShutdown(ref bool shuttingDown)
        {
            if (shuttingDown)
            {
                return false;
            }
            shuttingDown = true;
            return true;
        }

        internal static bool LoadedAssemblyPathsMatch(
            string expectedPath,
            bool allowPathlessUnityLoad,
            string assemblyLocation,
            string moduleFullyQualifiedName)
        {
            string normalizedExpected;
            try
            {
                normalizedExpected = Path.GetFullPath(expectedPath);
            }
            catch (Exception exception) when (
                exception is ArgumentException
                || exception is NotSupportedException
                || exception is PathTooLongException)
            {
                return false;
            }

            bool sawPhysicalPath = false;
            if (!PhysicalPathMatches(
                    normalizedExpected,
                    assemblyLocation,
                    ref sawPhysicalPath)
                || !PhysicalPathMatches(
                    normalizedExpected,
                    moduleFullyQualifiedName,
                    ref sawPhysicalPath))
            {
                return false;
            }
            return sawPhysicalPath || allowPathlessUnityLoad;
        }

        private static bool PhysicalPathMatches(
            string expectedPath,
            string candidate,
            ref bool sawPhysicalPath)
        {
            if (string.IsNullOrWhiteSpace(candidate) || !Path.IsPathRooted(candidate))
            {
                return true;
            }

            string normalized;
            try
            {
                normalized = Path.GetFullPath(candidate);
            }
            catch (Exception exception) when (
                exception is ArgumentException
                || exception is NotSupportedException
                || exception is PathTooLongException)
            {
                return false;
            }
            sawPhysicalPath = true;
            return string.Equals(
                expectedPath,
                normalized,
                StringComparison.OrdinalIgnoreCase);
        }
    }
}
