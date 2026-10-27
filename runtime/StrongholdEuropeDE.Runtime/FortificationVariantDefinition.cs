using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;

namespace StrongholdEuropeDE.Runtime
{
    internal enum FortificationVariantRole : byte
    {
        AdditionalWall = 1,
        NativeBattlementsInvariant = 2,
        Gatehouse = 3,
        StairVariant = 4,
        TowerVariant = 5,
    }

    /// <summary>
    /// Immutable, API-independent definition of one V1 fortification choice.
    /// Mapper route numbers are data only; this type deliberately knows no
    /// Script Extender or game API names.
    /// </summary>
    internal sealed class FortificationVariantDefinition
    {
        private readonly ReadOnlyCollection<int> _mapperRouteIds;

        internal FortificationVariantDefinition(
            byte saveCode,
            string id,
            FortificationVariantRole role,
            IEnumerable<int> mapperRouteIds,
            FortificationCost cost,
            FortificationDurabilityRatio durability,
            bool walkable,
            bool enabledByDefault,
            bool visibleByDefault,
            bool requiresMeasurement,
            bool usesNativeEconomy)
        {
            if (!IsSafeId(id))
            {
                throw new ArgumentException(
                    "Fortification id must be lowercase snake_case ASCII.",
                    nameof(id));
            }
            if (!Enum.IsDefined(typeof(FortificationVariantRole), role))
            {
                throw new ArgumentOutOfRangeException(nameof(role));
            }
            if (mapperRouteIds == null)
            {
                throw new ArgumentNullException(nameof(mapperRouteIds));
            }

            var routes = new List<int>();
            var seenRoutes = new HashSet<int>();
            foreach (int route in mapperRouteIds)
            {
                if (route < 0 || !seenRoutes.Add(route))
                {
                    throw new ArgumentException(
                        "Mapper routes must be non-negative and unique.",
                        nameof(mapperRouteIds));
                }
                routes.Add(route);
            }
            if (routes.Count == 0)
            {
                throw new ArgumentException(
                    "At least one mapper route is required.",
                    nameof(mapperRouteIds));
            }
            FortificationDamageScaler.ValidateRemainder(durability, 0);

            bool nativeInvariant =
                role == FortificationVariantRole.NativeBattlementsInvariant;
            if (nativeInvariant)
            {
                if (saveCode != 0
                    || !usesNativeEconomy
                    || !cost.IsFree
                    || !enabledByDefault
                    || !visibleByDefault
                    || requiresMeasurement
                    || routes.Count != 1)
                {
                    throw new ArgumentException(
                        "The native battlements invariant must remain native, "
                        + "visible, enabled, and non-persisted.");
                }
            }
            else if (saveCode == 0 || usesNativeEconomy || cost.IsFree)
            {
                throw new ArgumentException(
                    "Persisted fortification variants require a stable save "
                    + "code and an explicit non-zero quarter-goods cost.");
            }

            if (role == FortificationVariantRole.AdditionalWall
                && (requiresMeasurement
                    || !enabledByDefault
                    || !visibleByDefault
                    || routes.Count > 2))
            {
                throw new ArgumentException(
                    "V1 additional walls must be immediately available and "
                    + "use one or two mapper routes.");
            }
            if (role == FortificationVariantRole.Gatehouse
                && (!requiresMeasurement
                    || enabledByDefault
                    || visibleByDefault
                    || routes.Count != 4
                    || walkable))
            {
                throw new ArgumentException(
                    "The V1 gatehouse must have four routes and remain hidden "
                    + "and disabled until its measurement gate passes.");
            }
            bool isolatedMeasuredVariant =
                role == FortificationVariantRole.StairVariant
                || role == FortificationVariantRole.TowerVariant;
            if (isolatedMeasuredVariant
                && (!requiresMeasurement
                    || enabledByDefault
                    || visibleByDefault
                    || routes.Count != 1
                    || !walkable))
            {
                throw new ArgumentException(
                    "Unverified stair/platform variants must use one route "
                    + "and remain hidden and disabled until measured.");
            }

            SaveCode = saveCode;
            Id = id;
            Role = role;
            _mapperRouteIds = routes.AsReadOnly();
            Cost = cost;
            Durability = durability;
            Walkable = walkable;
            EnabledByDefault = enabledByDefault;
            VisibleByDefault = visibleByDefault;
            RequiresMeasurement = requiresMeasurement;
            UsesNativeEconomy = usesNativeEconomy;
        }

        internal byte SaveCode { get; }
        internal string Id { get; }
        internal FortificationVariantRole Role { get; }
        internal IReadOnlyList<int> MapperRouteIds => _mapperRouteIds;
        internal FortificationCost Cost { get; }
        internal FortificationDurabilityRatio Durability { get; }
        internal bool Walkable { get; }
        internal bool EnabledByDefault { get; }
        internal bool VisibleByDefault { get; }
        internal bool RequiresMeasurement { get; }
        internal bool UsesNativeEconomy { get; }

        internal bool IsPersisted =>
            Role != FortificationVariantRole.NativeBattlementsInvariant;

        internal bool MustRemainAvailable =>
            Role == FortificationVariantRole.NativeBattlementsInvariant;

        internal bool IsAvailable(bool measurementPassed)
        {
            if (MustRemainAvailable)
            {
                return true;
            }
            if (RequiresMeasurement)
            {
                return measurementPassed;
            }
            return EnabledByDefault;
        }

        internal int MapperRouteForIndex(int routeIndex)
        {
            if (routeIndex < 0 || routeIndex >= _mapperRouteIds.Count)
            {
                throw new ArgumentOutOfRangeException(nameof(routeIndex));
            }
            return _mapperRouteIds[routeIndex];
        }

        private static bool IsSafeId(string value)
        {
            if (string.IsNullOrEmpty(value)
                || value.Length > 64
                || value[0] < 'a'
                || value[0] > 'z')
            {
                return false;
            }
            for (int index = 1; index < value.Length; index++)
            {
                char character = value[index];
                bool accepted = (character >= 'a' && character <= 'z')
                    || (character >= '0' && character <= '9')
                    || character == '_';
                if (!accepted)
                {
                    return false;
                }
            }
            return true;
        }
    }
}
