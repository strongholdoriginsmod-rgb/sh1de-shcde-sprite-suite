using System;
using System.Collections.Generic;
using System.Reflection;
using SHCDESE.API;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>An expected vanilla value and the value owned by this mod.</summary>
    internal struct SlotValueChange<T>
    {
        internal SlotValueChange(T expectedOriginal, T desired)
        {
            ExpectedOriginal = expectedOriginal;
            Desired = desired;
        }

        internal T ExpectedOriginal;
        internal T Desired;
    }

    internal sealed class ExtenderMeleeDamageChange
    {
        internal ExtenderMeleeDamageChange(
            eChimps target,
            string expectedTargetName,
            int expectedTargetValue,
            SlotValueChange<int> damage)
        {
            if ((int)target != expectedTargetValue
                || target == eChimps.CHIMP_NUM_TYPES)
            {
                throw new ArgumentException(
                    "Melee target does not match its pinned value",
                    "target");
            }
            if (damage.ExpectedOriginal < 0 || damage.Desired < 0)
            {
                throw new ArgumentOutOfRangeException("damage");
            }
            Target = target;
            ExpectedTargetName = expectedTargetName;
            ExpectedTargetValue = expectedTargetValue;
            Damage = damage;
        }

        internal eChimps Target { get; private set; }

        internal string ExpectedTargetName { get; private set; }

        internal int ExpectedTargetValue { get; private set; }

        internal SlotValueChange<int> Damage { get; private set; }
    }

    internal sealed class ExtenderUnitSlotValues
    {
        internal ExtenderUnitSlotValues(
            SlotValueChange<bool> availability,
            SlotValueChange<int> goldCost,
            SlotValueChange<uint> health,
            SlotValueChange<ushort> speed,
            IEnumerable<ExtenderMeleeDamageChange> meleeDamage)
        {
            if (goldCost.ExpectedOriginal < 0 || goldCost.Desired < 0)
            {
                throw new ArgumentOutOfRangeException("goldCost");
            }
            if (health.ExpectedOriginal == 0U || health.Desired == 0U)
            {
                throw new ArgumentOutOfRangeException("health");
            }
            if (speed.ExpectedOriginal > 6 || speed.Desired > 6)
            {
                throw new ArgumentOutOfRangeException("speed");
            }
            if (meleeDamage == null)
            {
                throw new ArgumentNullException("meleeDamage");
            }
            var frozen = new List<ExtenderMeleeDamageChange>();
            foreach (ExtenderMeleeDamageChange value in meleeDamage)
            {
                if (value == null)
                {
                    throw new ArgumentException(
                        "Melee damage list contains null",
                        "meleeDamage");
                }
                frozen.Add(value);
            }
            if (frozen.Count == 0 || frozen.Count > 120)
            {
                throw new ArgumentOutOfRangeException("meleeDamage");
            }
            Availability = availability;
            GoldCost = goldCost;
            Health = health;
            Speed = speed;
            MeleeDamage = frozen.AsReadOnly();
        }

        internal SlotValueChange<bool> Availability { get; private set; }

        internal SlotValueChange<int> GoldCost { get; private set; }

        internal SlotValueChange<uint> Health { get; private set; }

        internal SlotValueChange<ushort> Speed { get; private set; }

        internal IReadOnlyList<ExtenderMeleeDamageChange> MeleeDamage
        {
            get;
            private set;
        }
    }

    internal sealed class ExtenderBuildingSlotValues
    {
        internal ExtenderBuildingSlotValues(
            SlotValueChange<bool> availability,
            SlotValueChange<int> wood,
            SlotValueChange<int> stone,
            SlotValueChange<int> iron,
            SlotValueChange<int> pitch,
            SlotValueChange<int> gold,
            SlotValueChange<uint> health)
        {
            ValidateCost(wood, "wood");
            ValidateCost(stone, "stone");
            ValidateCost(iron, "iron");
            ValidateCost(pitch, "pitch");
            ValidateCost(gold, "gold");
            if (health.ExpectedOriginal == 0U || health.Desired == 0U)
            {
                throw new ArgumentOutOfRangeException("health");
            }
            Availability = availability;
            Wood = wood;
            Stone = stone;
            Iron = iron;
            Pitch = pitch;
            Gold = gold;
            Health = health;
        }

        internal SlotValueChange<bool> Availability { get; private set; }

        internal SlotValueChange<int> Wood { get; private set; }

        internal SlotValueChange<int> Stone { get; private set; }

        internal SlotValueChange<int> Iron { get; private set; }

        internal SlotValueChange<int> Pitch { get; private set; }

        internal SlotValueChange<int> Gold { get; private set; }

        internal SlotValueChange<uint> Health { get; private set; }

        private static void ValidateCost(
            SlotValueChange<int> value,
            string parameter)
        {
            if (value.ExpectedOriginal < 0 || value.Desired < 0)
            {
                throw new ArgumentOutOfRangeException(parameter);
            }
        }
    }

    /// <summary>
    /// Binds typed slot contracts to the exact APIs of pinned SHCDE-SE 1.39.
    /// No caller has to repeat enum, table-size or singleton checks.
    /// </summary>
    internal static class ExtenderSlotDefinitionFactory
    {
        // SetUnitGoldCost writes both the dictionary and this fixed array.
        private const int SafeUnitGoldRows = 30;

        // GameData.game_data_txt contains five visual cost cells for structs
        // 0..108. The dock at 109 needs the separate guarded NativeTable path.
        private const int SafeBuildingCostRows = 109;

        internal static UnitSlotDefinition CreateUnit(
            string id,
            eChimps unit,
            string expectedUnitName,
            int expectedUnitValue,
            int expectedUnitEnumCount,
            ExtenderUnitSlotValues values,
            IEnumerable<ExtensionLeaseClaim> additionalClaims)
        {
            if (values == null)
            {
                throw new ArgumentNullException("values");
            }
            if ((int)unit != expectedUnitValue
                || unit == eChimps.CHIMP_NUM_TYPES)
            {
                throw new ArgumentException(
                    "Unit does not match its pinned value",
                    "unit");
            }
            var unitSlot = new PinnedEnumSlot(
                typeof(eChimps),
                expectedUnitName,
                expectedUnitValue,
                expectedUnitEnumCount);
            var extender = new SlotExtenderContract(
                "SHCDE-SE 1.39 unit APIs",
                VerifyUnitExtender);
            var availabilityTable = EnumTable(
                "GamePlayerManagerAPI.UnitAvailability",
                typeof(eChimps),
                expectedUnitEnumCount);
            var goldTable = new SlotTableContract(
                "GameUnitManagerAPI.GoldCosts",
                SafeUnitGoldRows,
                1,
                () => ReadPrivateArrayLength(
                    GameUnitManagerAPI.Instance,
                    "_unitsGoldCostsArray"),
                () => 1,
                null);
            var healthTable = PrivateArrayTable(
                "GameUnitManagerAPI.HealthDefaults",
                () => GameUnitManagerAPI.Instance,
                "_healthDefaultsArray",
                expectedUnitEnumCount);
            var speedTable = PrivateArrayTable(
                "GameUnitManagerAPI.SpeedDefaults",
                () => GameUnitManagerAPI.Instance,
                "_speedDefaultsArray",
                expectedUnitEnumCount);
            var meleeTable = new SlotTableContract(
                "GameUnitManagerAPI.MeleeDamageLookupTable",
                expectedUnitEnumCount,
                expectedUnitEnumCount,
                ReadMeleeRows,
                ReadMeleeColumns,
                VerifyMeleeTable);

            OwnedSlotValue<bool> availability = availabilityTable.Cell(
                "unit availability",
                expectedUnitValue,
                0,
                values.Availability.ExpectedOriginal,
                values.Availability.Desired,
                () => GamePlayerManagerAPI.Instance.IsUnitAllowed(unit),
                value => GamePlayerManagerAPI.Instance.SetIsUnitAllowed(unit, value));
            OwnedSlotValue<int> gold = goldTable.Cell(
                "unit gold cost",
                expectedUnitValue,
                0,
                values.GoldCost.ExpectedOriginal,
                values.GoldCost.Desired,
                () => GameUnitManagerAPI.Instance.GetUnitGoldCost(unit),
                value => GameUnitManagerAPI.Instance.SetUnitGoldCost(unit, value));
            OwnedSlotValue<uint> health = healthTable.Cell(
                "unit health",
                expectedUnitValue,
                0,
                values.Health.ExpectedOriginal,
                values.Health.Desired,
                () => GameUnitManagerAPI.Instance.GetDefaultHealth(unit),
                value => GameUnitManagerAPI.Instance.SetDefaultHealth(unit, value));
            OwnedSlotValue<ushort> speed = speedTable.Cell(
                "unit speed",
                expectedUnitValue,
                0,
                values.Speed.ExpectedOriginal,
                values.Speed.Desired,
                () => GameUnitManagerAPI.Instance.GetDefaultSpeed(unit),
                value => GameUnitManagerAPI.Instance.SetDefaultSpeed(unit, value));

            var damage = new List<OwnedSlotValue<int>>();
            var targets = new List<PinnedEnumSlot>();
            foreach (ExtenderMeleeDamageChange change in values.MeleeDamage)
            {
                targets.Add(new PinnedEnumSlot(
                    typeof(eChimps),
                    change.ExpectedTargetName,
                    change.ExpectedTargetValue,
                    expectedUnitEnumCount));
                eChimps target = change.Target;
                SlotValueChange<int> targetDamage = change.Damage;
                damage.Add(meleeTable.Cell(
                    "melee damage to " + change.ExpectedTargetName,
                    expectedUnitValue,
                    change.ExpectedTargetValue,
                    targetDamage.ExpectedOriginal,
                    targetDamage.Desired,
                    () => GameUnitManagerAPI.Instance.GetMeleeDamageFromTo(
                        unit,
                        target),
                    value => GameUnitManagerAPI.Instance.SetMeleeDamageFromTo(
                        unit,
                        target,
                        value)));
            }

            return new UnitSlotDefinition(
                id,
                unitSlot,
                extender,
                availability,
                new[] { gold },
                health,
                speed,
                damage,
                targets,
                additionalClaims);
        }

        internal static BuildingSlotDefinition CreateBuilding(
            string id,
            eMappers mapper,
            string expectedMapperName,
            int expectedMapperValue,
            int expectedMapperEnumCount,
            eStructs structure,
            string expectedStructureName,
            int expectedStructureValue,
            int expectedStructureEnumCount,
            ExtenderBuildingSlotValues values,
            IEnumerable<ExtensionLeaseClaim> additionalClaims)
        {
            if (values == null)
            {
                throw new ArgumentNullException("values");
            }
            if ((int)mapper != expectedMapperValue)
            {
                throw new ArgumentException(
                    "Mapper does not match its pinned value",
                    "mapper");
            }
            if ((int)structure != expectedStructureValue)
            {
                throw new ArgumentException(
                    "Structure does not match its pinned value",
                    "structure");
            }
            var mapperSlot = new PinnedEnumSlot(
                typeof(eMappers),
                expectedMapperName,
                expectedMapperValue,
                expectedMapperEnumCount);
            var structureSlot = new PinnedEnumSlot(
                typeof(eStructs),
                expectedStructureName,
                expectedStructureValue,
                expectedStructureEnumCount);
            var extender = new SlotExtenderContract(
                "SHCDE-SE 1.39 building APIs",
                VerifyBuildingExtender);
            var availabilityTable = EnumTable(
                "GamePlayerManagerAPI.BuildingAvailability",
                typeof(eMappers),
                expectedMapperEnumCount);
            var costTable = new SlotTableContract(
                "GameBuildingManagerAPI.LiveCosts",
                SafeBuildingCostRows,
                5,
                ReadGameDataCostRows,
                () => 5,
                null);
            var healthTable = PrivateArrayTable(
                "GameBuildingManagerAPI.HealthDefaults",
                () => GameBuildingManagerAPI.Instance,
                "_buildingHealthDefaultsArray",
                expectedStructureEnumCount);

            OwnedSlotValue<bool> availability = availabilityTable.Cell(
                "building availability",
                expectedMapperValue,
                0,
                values.Availability.ExpectedOriginal,
                values.Availability.Desired,
                () => GamePlayerManagerAPI.Instance.GetBuildingAvailability(mapper),
                value => GamePlayerManagerAPI.Instance.SetBuildingAvailability(
                    mapper,
                    value));
            var costs = new[]
            {
                costTable.Cell(
                    "building wood cost", expectedStructureValue, 0,
                    values.Wood.ExpectedOriginal, values.Wood.Desired,
                    () => GameBuildingManagerAPI.Instance.GetWoodCost(structure),
                    value => GameBuildingManagerAPI.Instance.SetWoodCost(
                        structure,
                        value)),
                costTable.Cell(
                    "building stone cost", expectedStructureValue, 1,
                    values.Stone.ExpectedOriginal, values.Stone.Desired,
                    () => GameBuildingManagerAPI.Instance.GetStoneCost(structure),
                    value => GameBuildingManagerAPI.Instance.SetStoneCost(
                        structure,
                        value)),
                costTable.Cell(
                    "building iron cost", expectedStructureValue, 2,
                    values.Iron.ExpectedOriginal, values.Iron.Desired,
                    () => GameBuildingManagerAPI.Instance.GetIronIngotCost(structure),
                    value => GameBuildingManagerAPI.Instance.SetIronIngotCost(
                        structure,
                        value)),
                costTable.Cell(
                    "building pitch cost", expectedStructureValue, 3,
                    values.Pitch.ExpectedOriginal, values.Pitch.Desired,
                    () => GameBuildingManagerAPI.Instance.GetRawPitchCost(structure),
                    value => GameBuildingManagerAPI.Instance.SetRawPitchCost(
                        structure,
                        value)),
                costTable.Cell(
                    "building gold cost", expectedStructureValue, 4,
                    values.Gold.ExpectedOriginal, values.Gold.Desired,
                    () => GameBuildingManagerAPI.Instance.GetGoldCost(structure),
                    value => GameBuildingManagerAPI.Instance.SetGoldCost(
                        structure,
                        value)),
            };
            OwnedSlotValue<uint> health = healthTable.Cell(
                "building health",
                expectedStructureValue,
                0,
                values.Health.ExpectedOriginal,
                values.Health.Desired,
                () => checked((uint)GameBuildingManagerAPI.Instance.GetDefaultHealth(
                    structure)),
                value => GameBuildingManagerAPI.Instance.SetDefaultHealth(
                    structure,
                    value));

            return new BuildingSlotDefinition(
                id,
                mapperSlot,
                structureSlot,
                extender,
                availability,
                costs,
                health,
                additionalClaims);
        }

        private static SlotTableContract EnumTable(
            string name,
            Type enumType,
            int expectedRows)
        {
            return new SlotTableContract(
                name,
                expectedRows,
                1,
                () => Enum.GetValues(enumType).Length,
                () => 1,
                null);
        }

        private static SlotTableContract PrivateArrayTable(
            string name,
            Func<object> instance,
            string fieldName,
            int expectedRows)
        {
            return new SlotTableContract(
                name,
                expectedRows,
                1,
                () => ReadPrivateArrayLength(instance(), fieldName),
                () => 1,
                null);
        }

        private static void VerifyUnitExtender()
        {
            RuntimeBuildGuard.VerifyCoreReportingDrift();
            if (GameUnitManagerAPI.Instance == null
                || GamePlayerManagerAPI.Instance == null)
            {
                throw new InvalidOperationException(
                    "Unit or player API is unavailable");
            }
        }

        private static void VerifyBuildingExtender()
        {
            RuntimeBuildGuard.VerifyCoreReportingDrift();
            if (GameBuildingManagerAPI.Instance == null
                || GamePlayerManagerAPI.Instance == null)
            {
                throw new InvalidOperationException(
                    "Building or player API is unavailable");
            }
            if (ReadGameDataCostRows() != SafeBuildingCostRows)
            {
                throw new InvalidOperationException(
                    "Unity building cost mirror length changed");
            }
        }

        private static void VerifyMeleeTable()
        {
            // Use the supported getter instead of taking a compile-time
            // dependency on the extender's internal matrix implementation.
            GameUnitManagerAPI.Instance.GetMeleeDamageFromTo(
                eChimps.CHIMP_TYPE_NULL,
                eChimps.CHIMP_TYPE_NULL);
        }

        private static int ReadMeleeRows()
        {
            int total;
            int width;
            ReadMeleeDimensions(out total, out width);
            if (width <= 0 || total % width != 0)
            {
                throw new InvalidOperationException(
                    "Melee damage matrix dimensions are malformed");
            }
            return total / width;
        }

        private static int ReadMeleeColumns()
        {
            int total;
            int width;
            ReadMeleeDimensions(out total, out width);
            return width;
        }

        private static void ReadMeleeDimensions(out int total, out int width)
        {
            PropertyInfo property = typeof(GameUnitManagerAPI).GetProperty(
                "MeleeDamageLookupTable",
                BindingFlags.Instance | BindingFlags.Public);
            object matrix = property == null
                ? null
                : property.GetValue(GameUnitManagerAPI.Instance, null);
            if (matrix == null)
            {
                throw new MissingMemberException(
                    typeof(GameUnitManagerAPI).FullName,
                    "MeleeDamageLookupTable");
            }
            FieldInfo widthField = matrix.GetType().GetField(
                "_width",
                BindingFlags.Instance | BindingFlags.NonPublic);
            FieldInfo backingField = matrix.GetType().GetField(
                "_backingArray",
                BindingFlags.Instance | BindingFlags.NonPublic);
            if (widthField == null || backingField == null)
            {
                throw new MissingFieldException(
                    matrix.GetType().FullName,
                    "_width/_backingArray");
            }
            object backing = backingField.GetValue(matrix);
            width = Convert.ToInt32(widthField.GetValue(matrix));
            total = ReadLength(backing);
        }

        private static int ReadPrivateArrayLength(object instance, string fieldName)
        {
            if (instance == null)
            {
                throw new InvalidOperationException(
                    "Extender API instance is unavailable");
            }
            FieldInfo field = instance.GetType().GetField(
                fieldName,
                BindingFlags.Instance | BindingFlags.NonPublic);
            if (field == null)
            {
                throw new MissingFieldException(
                    instance.GetType().FullName,
                    fieldName);
            }
            return ReadLength(field.GetValue(instance));
        }

        private static int ReadLength(object value)
        {
            if (value == null)
            {
                throw new InvalidOperationException(
                    "Extender table instance is unavailable");
            }
            FieldInfo length = value.GetType().GetField(
                "Length",
                BindingFlags.Instance | BindingFlags.Public);
            if (length == null)
            {
                PropertyInfo property = value.GetType().GetProperty(
                    "Length",
                    BindingFlags.Instance | BindingFlags.Public);
                if (property == null)
                {
                    throw new MissingMemberException(
                        value.GetType().FullName,
                        "Length");
                }
                return Convert.ToInt32(property.GetValue(value, null));
            }
            return Convert.ToInt32(length.GetValue(value));
        }

        private static int ReadGameDataCostRows()
        {
            FieldInfo field = typeof(GameData).GetField(
                "game_data_txt",
                BindingFlags.Static | BindingFlags.NonPublic);
            if (field == null || field.FieldType != typeof(int[]))
            {
                throw new MissingFieldException(
                    typeof(GameData).FullName,
                    "game_data_txt");
            }
            var values = field.GetValue(null) as int[];
            if (values == null || values.Length % 5 != 0)
            {
                throw new InvalidOperationException(
                    "Unity building cost mirror is unavailable or malformed");
            }
            return values.Length / 5;
        }
    }
}
