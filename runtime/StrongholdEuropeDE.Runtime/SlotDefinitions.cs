using System;
using System.Collections.Generic;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>An exact enum member and enum layout expected by one slot.</summary>
    internal sealed class PinnedEnumSlot
    {
        private readonly Type _enumType;

        internal PinnedEnumSlot(
            Type enumType,
            string expectedName,
            int expectedValue,
            int expectedMemberCount)
        {
            if (enumType == null)
            {
                throw new ArgumentNullException("enumType");
            }
            if (!enumType.IsEnum)
            {
                throw new ArgumentException("Slot type must be an enum", "enumType");
            }
            SlotContractText.ValidateAtom(expectedName, "expectedName", 128);
            if (expectedValue < 0)
            {
                throw new ArgumentOutOfRangeException("expectedValue");
            }
            if (expectedMemberCount < 1 || expectedMemberCount > 4096)
            {
                throw new ArgumentOutOfRangeException("expectedMemberCount");
            }
            _enumType = enumType;
            ExpectedName = expectedName;
            ExpectedValue = expectedValue;
            ExpectedMemberCount = expectedMemberCount;
        }

        internal string ExpectedName { get; private set; }

        internal int ExpectedValue { get; private set; }

        internal int ExpectedMemberCount { get; private set; }

        internal bool TryVerify(out string failure)
        {
            Array values;
            string actualName;
            try
            {
                values = Enum.GetValues(_enumType);
                actualName = Enum.GetName(
                    _enumType,
                    Enum.ToObject(_enumType, ExpectedValue));
            }
            catch (Exception exception)
            {
                failure = ExpectedName + ": enum verification failed: "
                    + SlotContractText.Describe(exception);
                return false;
            }
            if (values.Length != ExpectedMemberCount)
            {
                failure = ExpectedName + ": enum member count changed; expected "
                    + ExpectedMemberCount + ", actual " + values.Length;
                return false;
            }
            if (!string.Equals(actualName, ExpectedName, StringComparison.Ordinal))
            {
                failure = ExpectedName + ": enum value/name changed at "
                    + ExpectedValue;
                return false;
            }
            try
            {
                object named = Enum.Parse(_enumType, ExpectedName, false);
                if (Convert.ToInt64(named) != ExpectedValue)
                {
                    failure = ExpectedName + ": enum name/value mapping changed";
                    return false;
                }
            }
            catch (Exception exception)
            {
                failure = ExpectedName + ": enum name lookup failed: "
                    + SlotContractText.Describe(exception);
                return false;
            }
            failure = null;
            return true;
        }
    }

    /// <summary>
    /// One pinned extender/API prerequisite shared by every value in a slot.
    /// </summary>
    internal sealed class SlotExtenderContract
    {
        private readonly Action _verify;

        internal SlotExtenderContract(string id, Action verify)
        {
            SlotContractText.ValidateAtom(id, "id", 128);
            _verify = verify ?? throw new ArgumentNullException("verify");
            Id = id;
        }

        internal string Id { get; private set; }

        internal bool TryVerify(out string failure)
        {
            try
            {
                _verify();
            }
            catch (Exception exception)
            {
                failure = Id + ": extender prerequisite failed: "
                    + SlotContractText.Describe(exception);
                return false;
            }
            failure = null;
            return true;
        }
    }

    /// <summary>
    /// Exact dimensions and an optional address/API probe for one mutable
    /// engine table.
    /// </summary>
    internal sealed class SlotTableContract
    {
        private readonly Func<int> _readRows;
        private readonly Func<int> _readColumns;
        private readonly Action _verify;

        internal SlotTableContract(
            string name,
            int expectedRows,
            int expectedColumns,
            Func<int> readRows,
            Func<int> readColumns,
            Action verify)
        {
            SlotContractText.ValidateAtom(name, "name", 96);
            if (expectedRows < 1 || expectedRows > 1000000)
            {
                throw new ArgumentOutOfRangeException("expectedRows");
            }
            if (expectedColumns < 1 || expectedColumns > 1000000)
            {
                throw new ArgumentOutOfRangeException("expectedColumns");
            }
            _readRows = readRows ?? throw new ArgumentNullException("readRows");
            _readColumns = readColumns
                ?? throw new ArgumentNullException("readColumns");
            _verify = verify;
            Name = name;
            ExpectedRows = expectedRows;
            ExpectedColumns = expectedColumns;
        }

        internal string Name { get; private set; }

        internal int ExpectedRows { get; private set; }

        internal int ExpectedColumns { get; private set; }

        internal OwnedSlotValue<T> Cell<T>(
            string semanticName,
            int row,
            int column,
            T expectedOriginal,
            T desired,
            Func<T> read,
            Action<T> write)
        {
            return Cell(
                semanticName,
                row,
                column,
                expectedOriginal,
                desired,
                read,
                write,
                EqualityComparer<T>.Default);
        }

        internal OwnedSlotValue<T> Cell<T>(
            string semanticName,
            int row,
            int column,
            T expectedOriginal,
            T desired,
            Func<T> read,
            Action<T> write,
            IEqualityComparer<T> comparer)
        {
            if (row < 0 || row >= ExpectedRows)
            {
                throw new ArgumentOutOfRangeException("row");
            }
            if (column < 0 || column >= ExpectedColumns)
            {
                throw new ArgumentOutOfRangeException("column");
            }
            return new OwnedSlotValue<T>(
                semanticName,
                this,
                row,
                column,
                expectedOriginal,
                desired,
                read,
                write,
                comparer);
        }

        internal bool TryVerify(out string failure)
        {
            int rows;
            int columns;
            try
            {
                rows = _readRows();
                columns = _readColumns();
            }
            catch (Exception exception)
            {
                failure = Name + ": table dimensions could not be read: "
                    + SlotContractText.Describe(exception);
                return false;
            }
            if (rows != ExpectedRows || columns != ExpectedColumns)
            {
                failure = Name + ": table dimensions changed; expected "
                    + ExpectedRows + "x" + ExpectedColumns + ", actual "
                    + rows + "x" + columns;
                return false;
            }
            if (_verify != null)
            {
                try
                {
                    _verify();
                }
                catch (Exception exception)
                {
                    failure = Name + ": table probe failed: "
                        + SlotContractText.Describe(exception);
                    return false;
                }
            }
            failure = null;
            return true;
        }
    }

    internal interface ISlotValueDefinition
    {
        ExtensionLeaseClaim Claim { get; }

        SlotTableContract Table { get; }

        IOwnedMutation CreateMutation();
    }

    /// <summary>One expected-to-desired table cell with owned rollback.</summary>
    internal sealed class OwnedSlotValue<T> : ISlotValueDefinition
    {
        private readonly Func<T> _read;
        private readonly Action<T> _write;
        private readonly T _expectedOriginal;
        private readonly T _desired;
        private readonly IEqualityComparer<T> _comparer;

        internal OwnedSlotValue(
            string semanticName,
            SlotTableContract table,
            int row,
            int column,
            T expectedOriginal,
            T desired,
            Func<T> read,
            Action<T> write,
            IEqualityComparer<T> comparer)
        {
            SlotContractText.ValidateAtom(semanticName, "semanticName", 128);
            Table = table ?? throw new ArgumentNullException("table");
            _read = read ?? throw new ArgumentNullException("read");
            _write = write ?? throw new ArgumentNullException("write");
            _comparer = comparer ?? throw new ArgumentNullException("comparer");
            _expectedOriginal = expectedOriginal;
            _desired = desired;
            SemanticName = semanticName;
            Claim = ExtensionLeaseClaim.NativeTableCell(table.Name, row, column);
        }

        internal string SemanticName { get; private set; }

        public ExtensionLeaseClaim Claim { get; private set; }

        public SlotTableContract Table { get; private set; }

        public IOwnedMutation CreateMutation()
        {
            return new OwnedValueMutation<T>(
                Claim,
                _read,
                _write,
                _expectedOriginal,
                _desired,
                _comparer);
        }
    }

    /// <summary>
    /// Shared lifecycle for a typed engine-slot definition. Prepare is wholly
    /// read-only; Apply performs one all-or-rollback transaction.
    /// </summary>
    internal abstract class SlotDefinitionBase : IExtensionFeature
    {
        private readonly SlotExtenderContract _extender;
        private readonly PinnedEnumSlot[] _enumSlots;
        private readonly SlotTableContract[] _tables;
        private readonly ISlotValueDefinition[] _values;
        private readonly IReadOnlyList<ExtensionLeaseClaim> _claims;
        private OwnedMutationTransaction _transaction;
        private bool _prepared;

        protected SlotDefinitionBase(
            string id,
            SlotExtenderContract extender,
            IEnumerable<PinnedEnumSlot> enumSlots,
            IEnumerable<ExtensionLeaseClaim> identityAndAdditionalClaims,
            IEnumerable<ISlotValueDefinition> values)
        {
            SlotContractText.ValidateFeatureId(id);
            Id = id;
            _extender = extender ?? throw new ArgumentNullException("extender");
            _enumSlots = FreezeEnums(enumSlots);
            _values = FreezeValues(values);
            _tables = FreezeTables(_values);
            _claims = FreezeClaims(identityAndAdditionalClaims, _values);
        }

        public string Id { get; private set; }

        public IReadOnlyList<ExtensionLeaseClaim> ExclusiveClaims
        {
            get { return _claims; }
        }

        internal OwnedRollbackSummary LastRollback { get; private set; }

        public bool Prepare(out string failure)
        {
            _prepared = false;
            if (!_extender.TryVerify(out failure))
            {
                return false;
            }
            foreach (PinnedEnumSlot slot in _enumSlots)
            {
                if (!slot.TryVerify(out failure))
                {
                    return false;
                }
            }
            foreach (SlotTableContract table in _tables)
            {
                if (!table.TryVerify(out failure))
                {
                    return false;
                }
            }
            var mutations = new IOwnedMutation[_values.Length];
            for (int index = 0; index < _values.Length; index++)
            {
                mutations[index] = _values[index].CreateMutation();
            }
            _transaction = new OwnedMutationTransaction(mutations);
            if (!_transaction.TryPrepare(out failure))
            {
                _transaction = null;
                return false;
            }
            _prepared = true;
            failure = null;
            return true;
        }

        public void Apply()
        {
            if (!_prepared || _transaction == null)
            {
                throw new InvalidOperationException(
                    Id + ": slot definition was not prepared");
            }
            string failure;
            if (!_transaction.TryApply(out failure))
            {
                _prepared = false;
                throw new InvalidOperationException(Id + ": " + failure);
            }
            _prepared = false;
        }

        public void Tick()
        {
            if (_transaction == null
                || _transaction.State != OwnedMutationState.Applied)
            {
                throw new InvalidOperationException(
                    Id + ": slot transaction is not active");
            }
            string failure;
            if (!_transaction.VerifyOwnership(out failure))
            {
                throw new InvalidOperationException(Id + ": " + failure);
            }
        }

        public void RollbackOwned()
        {
            _prepared = false;
            if (_transaction == null)
            {
                LastRollback = new OwnedRollbackSummary();
                return;
            }
            string failure;
            LastRollback = _transaction.RollbackOwned(out failure);
            if (!LastRollback.Succeeded)
            {
                throw new InvalidOperationException(
                    Id + ": " + (failure ?? "slot rollback failed"));
            }
        }

        private static PinnedEnumSlot[] FreezeEnums(
            IEnumerable<PinnedEnumSlot> values)
        {
            if (values == null)
            {
                throw new ArgumentNullException("enumSlots");
            }
            var frozen = new List<PinnedEnumSlot>();
            foreach (PinnedEnumSlot value in values)
            {
                if (value == null)
                {
                    throw new ArgumentException(
                        "Enum slot list contains null",
                        "enumSlots");
                }
                frozen.Add(value);
            }
            if (frozen.Count == 0 || frozen.Count > 128)
            {
                throw new ArgumentOutOfRangeException("enumSlots");
            }
            return frozen.ToArray();
        }

        private static ISlotValueDefinition[] FreezeValues(
            IEnumerable<ISlotValueDefinition> values)
        {
            if (values == null)
            {
                throw new ArgumentNullException("values");
            }
            var frozen = new List<ISlotValueDefinition>();
            foreach (ISlotValueDefinition value in values)
            {
                if (value == null)
                {
                    throw new ArgumentException(
                        "Slot value list contains null",
                        "values");
                }
                frozen.Add(value);
            }
            if (frozen.Count == 0 || frozen.Count > 126)
            {
                throw new ArgumentOutOfRangeException("values");
            }
            return frozen.ToArray();
        }

        private static SlotTableContract[] FreezeTables(
            IEnumerable<ISlotValueDefinition> values)
        {
            var byName = new Dictionary<string, SlotTableContract>(
                StringComparer.Ordinal);
            var ordered = new List<SlotTableContract>();
            foreach (ISlotValueDefinition value in values)
            {
                SlotTableContract existing;
                if (byName.TryGetValue(value.Table.Name, out existing))
                {
                    if (!object.ReferenceEquals(existing, value.Table))
                    {
                        throw new ArgumentException(
                            "Different table contracts use the same name: "
                            + value.Table.Name,
                            "values");
                    }
                    continue;
                }
                byName.Add(value.Table.Name, value.Table);
                ordered.Add(value.Table);
            }
            return ordered.ToArray();
        }

        private static IReadOnlyList<ExtensionLeaseClaim> FreezeClaims(
            IEnumerable<ExtensionLeaseClaim> identityAndAdditionalClaims,
            IEnumerable<ISlotValueDefinition> values)
        {
            if (identityAndAdditionalClaims == null)
            {
                throw new ArgumentNullException("identityAndAdditionalClaims");
            }
            var claims = new List<ExtensionLeaseClaim>();
            foreach (ExtensionLeaseClaim claim in identityAndAdditionalClaims)
            {
                AddClaim(claims, claim);
            }
            foreach (ISlotValueDefinition value in values)
            {
                AddClaim(claims, value.Claim);
            }
            if (claims.Count > 128)
            {
                throw new ArgumentOutOfRangeException(
                    "values",
                    "A slot definition cannot own more than 128 claims");
            }
            return Array.AsReadOnly(claims.ToArray());
        }

        private static void AddClaim(
            ICollection<ExtensionLeaseClaim> claims,
            ExtensionLeaseClaim proposed)
        {
            if (!proposed.IsValid)
            {
                throw new ArgumentException("Slot claim is uninitialized");
            }
            foreach (ExtensionLeaseClaim existing in claims)
            {
                if (proposed.ConflictsWith(existing))
                {
                    throw new ArgumentException(
                        "Slot definition contains overlapping claims "
                        + existing + " and " + proposed);
                }
            }
            claims.Add(proposed);
        }
    }

    /// <summary>
    /// A complete repurposed unit slot: availability, costs, health, speed and
    /// damage share one preflighted owned transaction.
    /// </summary>
    internal sealed class UnitSlotDefinition : SlotDefinitionBase
    {
        internal UnitSlotDefinition(
            string id,
            PinnedEnumSlot unitSlot,
            SlotExtenderContract extender,
            OwnedSlotValue<bool> availability,
            IEnumerable<OwnedSlotValue<int>> costs,
            OwnedSlotValue<uint> health,
            OwnedSlotValue<ushort> speed,
            IEnumerable<OwnedSlotValue<int>> damage,
            IEnumerable<PinnedEnumSlot> referencedUnitSlots,
            IEnumerable<ExtensionLeaseClaim> additionalClaims)
            : base(
                id,
                extender,
                BuildEnums(unitSlot, referencedUnitSlots),
                BuildClaims(unitSlot, additionalClaims),
                BuildValues(availability, costs, health, speed, damage))
        {
            UnitSlot = unitSlot;
        }

        internal PinnedEnumSlot UnitSlot { get; private set; }

        private static IEnumerable<PinnedEnumSlot> BuildEnums(
            PinnedEnumSlot unitSlot,
            IEnumerable<PinnedEnumSlot> referenced)
        {
            if (unitSlot == null)
            {
                throw new ArgumentNullException("unitSlot");
            }
            var values = new List<PinnedEnumSlot> { unitSlot };
            if (referenced != null)
            {
                values.AddRange(referenced);
            }
            return values;
        }

        private static IEnumerable<ExtensionLeaseClaim> BuildClaims(
            PinnedEnumSlot unitSlot,
            IEnumerable<ExtensionLeaseClaim> additional)
        {
            if (unitSlot == null)
            {
                throw new ArgumentNullException("unitSlot");
            }
            var claims = new List<ExtensionLeaseClaim>
            {
                ExtensionLeaseClaim.Unit(unitSlot.ExpectedValue),
            };
            if (additional != null)
            {
                claims.AddRange(additional);
            }
            return claims;
        }

        private static IEnumerable<ISlotValueDefinition> BuildValues(
            OwnedSlotValue<bool> availability,
            IEnumerable<OwnedSlotValue<int>> costs,
            OwnedSlotValue<uint> health,
            OwnedSlotValue<ushort> speed,
            IEnumerable<OwnedSlotValue<int>> damage)
        {
            if (availability == null)
            {
                throw new ArgumentNullException("availability");
            }
            if (health == null)
            {
                throw new ArgumentNullException("health");
            }
            if (speed == null)
            {
                throw new ArgumentNullException("speed");
            }
            var values = new List<ISlotValueDefinition> { availability };
            AddRequired(values, costs, "costs");
            values.Add(health);
            values.Add(speed);
            AddRequired(values, damage, "damage");
            return values;
        }

        private static void AddRequired<T>(
            ICollection<ISlotValueDefinition> destination,
            IEnumerable<OwnedSlotValue<T>> source,
            string parameter)
        {
            if (source == null)
            {
                throw new ArgumentNullException(parameter);
            }
            int count = 0;
            foreach (OwnedSlotValue<T> value in source)
            {
                destination.Add(value);
                count++;
            }
            if (count == 0)
            {
                throw new ArgumentException(
                    "At least one slot value is required",
                    parameter);
            }
        }
    }

    /// <summary>
    /// A complete repurposed building slot: mapper and structure identity,
    /// availability, costs and health share one owned transaction.
    /// </summary>
    internal sealed class BuildingSlotDefinition : SlotDefinitionBase
    {
        internal BuildingSlotDefinition(
            string id,
            PinnedEnumSlot mapperSlot,
            PinnedEnumSlot structureSlot,
            SlotExtenderContract extender,
            OwnedSlotValue<bool> availability,
            IEnumerable<OwnedSlotValue<int>> costs,
            OwnedSlotValue<uint> health,
            IEnumerable<ExtensionLeaseClaim> additionalClaims)
            : base(
                id,
                extender,
                new[]
                {
                    mapperSlot ?? throw new ArgumentNullException("mapperSlot"),
                    structureSlot
                        ?? throw new ArgumentNullException("structureSlot"),
                },
                BuildClaims(mapperSlot, structureSlot, additionalClaims),
                BuildValues(availability, costs, health))
        {
            MapperSlot = mapperSlot;
            StructureSlot = structureSlot;
        }

        internal PinnedEnumSlot MapperSlot { get; private set; }

        internal PinnedEnumSlot StructureSlot { get; private set; }

        private static IEnumerable<ExtensionLeaseClaim> BuildClaims(
            PinnedEnumSlot mapper,
            PinnedEnumSlot structure,
            IEnumerable<ExtensionLeaseClaim> additional)
        {
            if (mapper == null)
            {
                throw new ArgumentNullException("mapperSlot");
            }
            if (structure == null)
            {
                throw new ArgumentNullException("structureSlot");
            }
            var claims = new List<ExtensionLeaseClaim>
            {
                ExtensionLeaseClaim.Mapper(mapper.ExpectedValue),
                ExtensionLeaseClaim.Structure(structure.ExpectedValue),
            };
            if (additional != null)
            {
                claims.AddRange(additional);
            }
            return claims;
        }

        private static IEnumerable<ISlotValueDefinition> BuildValues(
            OwnedSlotValue<bool> availability,
            IEnumerable<OwnedSlotValue<int>> costs,
            OwnedSlotValue<uint> health)
        {
            if (availability == null)
            {
                throw new ArgumentNullException("availability");
            }
            if (costs == null)
            {
                throw new ArgumentNullException("costs");
            }
            if (health == null)
            {
                throw new ArgumentNullException("health");
            }
            var values = new List<ISlotValueDefinition> { availability };
            int count = 0;
            foreach (OwnedSlotValue<int> cost in costs)
            {
                values.Add(cost);
                count++;
            }
            if (count == 0)
            {
                throw new ArgumentException(
                    "At least one building cost is required",
                    "costs");
            }
            values.Add(health);
            return values;
        }
    }

    internal static class SlotContractText
    {
        internal static void ValidateFeatureId(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length > 64)
            {
                throw new ArgumentException("Feature id is not canonical", "value");
            }
            for (int index = 0; index < value.Length; index++)
            {
                char character = value[index];
                bool alpha = character >= 'a' && character <= 'z';
                bool digit = character >= '0' && character <= '9';
                if (!alpha && !digit
                    && (index == 0
                        || (character != '-' && character != '_'
                            && character != '.')))
                {
                    throw new ArgumentException(
                        "Feature id is not canonical",
                        "value");
                }
            }
        }

        internal static void ValidateAtom(
            string value,
            string parameter,
            int maximumLength)
        {
            if (string.IsNullOrEmpty(value)
                || value.Length > maximumLength
                || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            {
                throw new ArgumentException(
                    parameter + " is not canonical",
                    parameter);
            }
            foreach (char character in value)
            {
                if (char.IsControl(character) || character == '|')
                {
                    throw new ArgumentException(
                        parameter + " contains an unsafe character",
                        parameter);
                }
            }
        }

        internal static string Describe(Exception exception)
        {
            string message = exception.Message;
            if (string.IsNullOrEmpty(message))
            {
                message = "unspecified";
            }
            char[] characters = message.ToCharArray();
            for (int index = 0; index < characters.Length; index++)
            {
                if (char.IsControl(characters[index]) || characters[index] == '|')
                {
                    characters[index] = ' ';
                }
            }
            message = new string(characters).Trim();
            if (message.Length == 0)
            {
                message = "unspecified";
            }
            if (message.Length > 256)
            {
                message = message.Substring(0, 256);
            }
            return exception.GetType().Name + ": " + message;
        }
    }
}
