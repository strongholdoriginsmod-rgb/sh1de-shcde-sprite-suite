using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Frozen V1 catalog. Save codes, ids, costs, ratios, and mapper routes are
    /// persistence contracts and must never be renumbered in place.
    /// </summary>
    internal static class FortificationVariantCatalog
    {
        internal const int CatalogVersion = 1;

        private static readonly ReadOnlyCollection<FortificationVariantDefinition>
            Definitions;
        private static readonly ReadOnlyCollection<FortificationVariantDefinition>
            WallDefinitions;
        private static readonly Dictionary<string, FortificationVariantDefinition>
            ById;
        private static readonly Dictionary<byte, FortificationVariantDefinition>
            PersistedBySaveCode;

        static FortificationVariantCatalog()
        {
            var definitions = new List<FortificationVariantDefinition>
            {
                Wall(
                    1,
                    "pointed_palisade",
                    new[] { 46 },
                    woodQuarters: 1,
                    stoneQuarters: 0,
                    durabilityNumerator: 1,
                    durabilityDenominator: 2,
                    walkable: false),
                Wall(
                    2,
                    "platform_palisade",
                    new[] { 25 },
                    woodQuarters: 2,
                    stoneQuarters: 0,
                    durabilityNumerator: 7,
                    durabilityDenominator: 10,
                    walkable: true),
                Wall(
                    3,
                    "low_stone_wall",
                    new[] { 46 },
                    woodQuarters: 0,
                    stoneQuarters: 1,
                    durabilityNumerator: 2,
                    durabilityDenominator: 3,
                    walkable: false),
                Wall(
                    4,
                    "normal_stone_wall",
                    new[] { 25 },
                    woodQuarters: 0,
                    stoneQuarters: 2,
                    durabilityNumerator: 1,
                    durabilityDenominator: 1,
                    walkable: true),
                Wall(
                    5,
                    "extra_high_stone_wall",
                    new[] { 25 },
                    woodQuarters: 0,
                    stoneQuarters: 3,
                    durabilityNumerator: 3,
                    durabilityDenominator: 2,
                    walkable: true),
                Wall(
                    6,
                    "stone_wall_wood_spikes",
                    new[] { 25 },
                    woodQuarters: 1,
                    stoneQuarters: 2,
                    durabilityNumerator: 11,
                    durabilityDenominator: 10,
                    walkable: true),
                Wall(
                    7,
                    "palisade_battlements",
                    new[] { 25, 26 },
                    woodQuarters: 2,
                    stoneQuarters: 1,
                    durabilityNumerator: 17,
                    durabilityDenominator: 20,
                    walkable: true),
                new FortificationVariantDefinition(
                    0,
                    "native_battlements",
                    FortificationVariantRole.NativeBattlementsInvariant,
                    new[] { 26 },
                    FortificationCost.Free,
                    new FortificationDurabilityRatio(1, 1),
                    walkable: false,
                    enabledByDefault: true,
                    visibleByDefault: true,
                    requiresMeasurement: false,
                    usesNativeEconomy: true),
                new FortificationVariantDefinition(
                    8,
                    "wooden_gatehouse",
                    FortificationVariantRole.Gatehouse,
                    new[] { 140, 141, 142, 143 },
                    new FortificationCost(
                        woodQuarters: 40,
                        stoneQuarters: 0),
                    new FortificationDurabilityRatio(13, 20),
                    walkable: false,
                    enabledByDefault: false,
                    visibleByDefault: false,
                    requiresMeasurement: true,
                    usesNativeEconomy: false),
                // 2026-09-04: the wooden stairs left the native mapper-27 probe.
                // The SH1 stair frames (tile_castle 1552..1567) are wall tiles
                // with a ramp face, so the variant is drawn on the wall line
                // like every other wall kind; save code 9 is unchanged and was
                // never persisted while the probe stayed shut.
                Wall(
                    9,
                    "wooden_stairs",
                    new[] { 25 },
                    woodQuarters: 4,
                    stoneQuarters: 0,
                    durabilityNumerator: 1,
                    durabilityDenominator: 1,
                    walkable: true),
                new FortificationVariantDefinition(
                    10,
                    "wooden_platform",
                    FortificationVariantRole.TowerVariant,
                    new[] { 110 },
                    new FortificationCost(
                        woodQuarters: 40,
                        stoneQuarters: 0),
                    new FortificationDurabilityRatio(1, 1),
                    walkable: true,
                    enabledByDefault: false,
                    visibleByDefault: false,
                    requiresMeasurement: true,
                    usesNativeEconomy: false),
            };

            ValidateFixedV1(definitions);
            Definitions = definitions.AsReadOnly();
            WallDefinitions = definitions
                .Where(value =>
                    value.Role == FortificationVariantRole.AdditionalWall)
                .ToList()
                .AsReadOnly();
            ById = definitions.ToDictionary(
                value => value.Id,
                StringComparer.Ordinal);
            PersistedBySaveCode = definitions
                .Where(value => value.IsPersisted)
                .ToDictionary(value => value.SaveCode);
        }

        internal static IReadOnlyList<FortificationVariantDefinition> All =>
            Definitions;

        internal static IReadOnlyList<FortificationVariantDefinition>
            AdditionalWalls => WallDefinitions;

        internal static FortificationVariantDefinition NativeBattlements =>
            GetRequired("native_battlements");

        internal static FortificationVariantDefinition WoodenGatehouse =>
            GetRequired("wooden_gatehouse");

        internal static FortificationVariantDefinition WoodenStairs =>
            GetRequired("wooden_stairs");

        internal static FortificationVariantDefinition WoodenPlatform =>
            GetRequired("wooden_platform");

        internal static bool TryGet(
            string id,
            out FortificationVariantDefinition definition)
        {
            if (id == null)
            {
                definition = null;
                return false;
            }
            return ById.TryGetValue(id, out definition);
        }

        internal static FortificationVariantDefinition GetRequired(string id)
        {
            FortificationVariantDefinition definition;
            if (!TryGet(id, out definition))
            {
                throw new KeyNotFoundException(
                    "Unknown fortification variant: " + id);
            }
            return definition;
        }

        internal static bool TryGetPersisted(
            byte saveCode,
            out FortificationVariantDefinition definition)
        {
            return PersistedBySaveCode.TryGetValue(saveCode, out definition);
        }

        private static FortificationVariantDefinition Wall(
            byte saveCode,
            string id,
            int[] mapperRoutes,
            long woodQuarters,
            long stoneQuarters,
            int durabilityNumerator,
            int durabilityDenominator,
            bool walkable)
        {
            return new FortificationVariantDefinition(
                saveCode,
                id,
                FortificationVariantRole.AdditionalWall,
                mapperRoutes,
                new FortificationCost(woodQuarters, stoneQuarters),
                new FortificationDurabilityRatio(
                    durabilityNumerator,
                    durabilityDenominator),
                walkable,
                enabledByDefault: true,
                visibleByDefault: true,
                requiresMeasurement: false,
                usesNativeEconomy: false);
        }

        private static void ValidateFixedV1(
            IReadOnlyList<FortificationVariantDefinition> definitions)
        {
            string[] expectedWalls =
            {
                "pointed_palisade",
                "platform_palisade",
                "low_stone_wall",
                "normal_stone_wall",
                "extra_high_stone_wall",
                "stone_wall_wood_spikes",
                "palisade_battlements",
            };
            if (definitions.Count != 11)
            {
                throw new InvalidOperationException(
                    "The V1 fortification catalog must contain eleven entries.");
            }
            for (int index = 0; index < expectedWalls.Length; index++)
            {
                FortificationVariantDefinition definition = definitions[index];
                if (definition.Id != expectedWalls[index]
                    || definition.SaveCode != index + 1
                    || definition.Role
                        != FortificationVariantRole.AdditionalWall)
                {
                    throw new InvalidOperationException(
                        "The V1 wall catalog order or save code changed.");
                }
            }

            FortificationVariantDefinition native = definitions[7];
            if (native.Id != "native_battlements"
                || native.SaveCode != 0
                || native.MapperRouteIds.Count != 1
                || native.MapperRouteIds[0] != 26
                || !native.MustRemainAvailable)
            {
                throw new InvalidOperationException(
                    "Native battlements availability is a fixed V1 invariant.");
            }

            FortificationVariantDefinition gate = definitions[8];
            if (gate.Id != "wooden_gatehouse"
                || gate.SaveCode != 8
                || gate.Role != FortificationVariantRole.Gatehouse
                || gate.IsAvailable(measurementPassed: false)
                || !gate.IsAvailable(measurementPassed: true))
            {
                throw new InvalidOperationException(
                    "The wooden gatehouse measurement gate changed.");
            }

            // The stairs keep save code 9 but are a wall kind since 2026-09-04;
            // their mapper route is the normal wall base (25) and the ramp is
            // painted by the sprite catalog, not by native mapper 27.
            FortificationVariantDefinition stairs = definitions[9];
            if (stairs.Id != "wooden_stairs"
                || stairs.SaveCode != 9
                || stairs.Role != FortificationVariantRole.AdditionalWall
                || stairs.MapperRouteIds.Count != 1
                || stairs.MapperRouteIds[0] != 25
                || stairs.Cost.WoodQuarters != 4
                || stairs.Cost.StoneQuarters != 0
                || !stairs.Walkable
                || !stairs.IsAvailable(measurementPassed: false))
            {
                throw new InvalidOperationException(
                    "The wooden stairs wall contract changed.");
            }

            FortificationVariantDefinition platform = definitions[10];
            if (platform.Id != "wooden_platform"
                || platform.SaveCode != 10
                || platform.Role != FortificationVariantRole.TowerVariant
                || platform.MapperRouteIds.Count != 1
                || platform.MapperRouteIds[0] != 110
                || platform.Cost.WoodQuarters != 40
                || platform.Cost.StoneQuarters != 0
                || platform.IsAvailable(measurementPassed: false)
                || !platform.IsAvailable(measurementPassed: true))
            {
                throw new InvalidOperationException(
                    "The wooden platform measurement contract changed.");
            }

            var ids = new HashSet<string>(StringComparer.Ordinal);
            var saveCodes = new HashSet<byte>();
            foreach (FortificationVariantDefinition definition in definitions)
            {
                if (!ids.Add(definition.Id)
                    || (definition.IsPersisted
                        && !saveCodes.Add(definition.SaveCode)))
                {
                    throw new InvalidOperationException(
                        "Fortification ids and persisted save codes must be unique.");
                }
            }
        }
    }
}
