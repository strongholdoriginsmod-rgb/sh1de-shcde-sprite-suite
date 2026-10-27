using System;
using System.Collections.Generic;
using System.Globalization;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// An exclusive native resource owned by one gameplay extension.
    /// </summary>
    /// <remarks>
    /// Crusader cannot grow new <c>eMappers</c>, <c>eStructs</c> or
    /// <c>eChimps</c> values. A feature which looks new to the player therefore
    /// repurposes an existing engine slot. Claims make that otherwise implicit
    /// ownership explicit and reject two features which would overwrite the
    /// same slot, hook, UI element or native table cell.
    /// </remarks>
    internal struct ExtensionLeaseClaim : IEquatable<ExtensionLeaseClaim>
    {
        private readonly string _domain;
        private readonly string _key;
        private readonly string _nativeTable;
        private readonly long _nativeRow;
        private readonly long _nativeColumn;
        private readonly bool _ownsNativeRow;

        private ExtensionLeaseClaim(string domain, string key)
            : this(domain, key, null, -1L, -1L, false)
        {
        }

        private ExtensionLeaseClaim(
            string domain,
            string key,
            string nativeTable,
            long nativeRow,
            long nativeColumn,
            bool ownsNativeRow)
        {
            ValidateAtom(domain, "claim domain", 32);
            ValidateAtom(key, "claim key", 192);
            _domain = domain;
            _key = key;
            _nativeTable = nativeTable;
            _nativeRow = nativeRow;
            _nativeColumn = nativeColumn;
            _ownsNativeRow = ownsNativeRow;
        }

        internal string Domain
        {
            get { return _domain; }
        }

        internal string Key
        {
            get { return _key; }
        }

        internal bool IsValid
        {
            get { return Domain != null && Key != null; }
        }

        internal static ExtensionLeaseClaim Mapper(int value)
        {
            return Numeric("mapper", value);
        }

        internal static ExtensionLeaseClaim Structure(int value)
        {
            return Numeric("structure", value);
        }

        internal static ExtensionLeaseClaim Unit(int value)
        {
            return Numeric("unit", value);
        }

        internal static ExtensionLeaseClaim Hook(string fullyQualifiedName)
        {
            return new ExtensionLeaseClaim("hook", fullyQualifiedName);
        }

        internal static ExtensionLeaseClaim UiElement(
            string xamlResource,
            string elementName)
        {
            ValidateAtom(xamlResource, "XAML resource", 128);
            ValidateAtom(elementName, "XAML element", 64);
            return new ExtensionLeaseClaim(
                "ui",
                xamlResource + "#" + elementName);
        }

        internal static ExtensionLeaseClaim NativeTableCell(
            string table,
            long row,
            long column)
        {
            ValidateAtom(table, "native table", 96);
            if (row < 0L)
            {
                throw new ArgumentOutOfRangeException(
                    "row",
                    "Native table rows must not be negative");
            }
            if (column < 0L)
            {
                throw new ArgumentOutOfRangeException(
                    "column",
                    "Native table columns must not be negative");
            }
            return new ExtensionLeaseClaim(
                "native-table",
                table + "[" + row.ToString(CultureInfo.InvariantCulture)
                + "," + column.ToString(CultureInfo.InvariantCulture) + "]",
                table,
                row,
                column,
                false);
        }

        internal static ExtensionLeaseClaim NativeTableRow(string table, long row)
        {
            ValidateAtom(table, "native table", 96);
            if (row < 0L)
            {
                throw new ArgumentOutOfRangeException(
                    "row",
                    "Native table rows must not be negative");
            }
            return new ExtensionLeaseClaim(
                "native-table-row",
                table + "[" + row.ToString(CultureInfo.InvariantCulture) + ",*]",
                table,
                row,
                -1L,
                true);
        }

        /// <summary>
        /// Whether two claims overlap, including a complete native row and one
        /// of its cells. Equality alone cannot express that relationship.
        /// </summary>
        internal bool ConflictsWith(ExtensionLeaseClaim other)
        {
            if (Equals(other))
            {
                return true;
            }
            if (_nativeTable == null || other._nativeTable == null
                || !string.Equals(
                    _nativeTable,
                    other._nativeTable,
                    StringComparison.Ordinal)
                || _nativeRow != other._nativeRow)
            {
                return false;
            }
            return _ownsNativeRow
                || other._ownsNativeRow
                || _nativeColumn == other._nativeColumn;
        }

        public bool Equals(ExtensionLeaseClaim other)
        {
            return string.Equals(Domain, other.Domain, StringComparison.Ordinal)
                && string.Equals(Key, other.Key, StringComparison.Ordinal);
        }

        public override bool Equals(object value)
        {
            if (!(value is ExtensionLeaseClaim))
            {
                return false;
            }
            return Equals((ExtensionLeaseClaim)value);
        }

        public override int GetHashCode()
        {
            unchecked
            {
                return ((Domain == null ? 0 : Domain.GetHashCode()) * 397)
                    ^ (Key == null ? 0 : Key.GetHashCode());
            }
        }

        public override string ToString()
        {
            return Domain + ":" + Key;
        }

        private static ExtensionLeaseClaim Numeric(string domain, int value)
        {
            if (value < 0)
            {
                throw new ArgumentOutOfRangeException(
                    "value",
                    "Engine slot values must not be negative");
            }
            return new ExtensionLeaseClaim(
                domain,
                value.ToString(CultureInfo.InvariantCulture));
        }

        private static void ValidateAtom(string value, string label, int maximumLength)
        {
            if (string.IsNullOrEmpty(value)
                || value.Length > maximumLength
                || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            {
                throw new ArgumentException(label + " is not canonical", label);
            }
            foreach (char character in value)
            {
                if (char.IsControl(character) || character == '|')
                {
                    throw new ArgumentException(label + " contains an unsafe character", label);
                }
            }
        }
    }

    internal enum ExtensionFeatureState
    {
        Registered = 0,
        Active = 1,
        Stopped = 2,
        Failed = 3,
    }

    /// <summary>A single independently fail-closed gameplay extension.</summary>
    internal interface IExtensionFeature
    {
        string Id { get; }

        IReadOnlyList<ExtensionLeaseClaim> ExclusiveClaims { get; }

        /// <summary>
        /// Inspect every prerequisite without mutating game state.
        /// </summary>
        bool Prepare(out string failure);

        /// <summary>Apply the feature. Partial application may throw.</summary>
        void Apply();

        /// <summary>Optional per-frame or per-map maintenance.</summary>
        void Tick();

        /// <summary>
        /// Restore only state still owned by this feature. Must be idempotent.
        /// </summary>
        void RollbackOwned();
    }

    internal sealed class ExtensionFeatureSnapshot
    {
        internal ExtensionFeatureSnapshot(
            string id,
            ExtensionFeatureState state,
            string failure,
            int claimCount)
        {
            Id = id;
            State = state;
            Failure = failure;
            ClaimCount = claimCount;
        }

        internal string Id { get; private set; }

        internal ExtensionFeatureState State { get; private set; }

        internal string Failure { get; private set; }

        internal int ClaimCount { get; private set; }
    }

    /// <summary>
    /// Lifecycle and ownership boundary for deep gameplay extensions.
    /// </summary>
    /// <remarks>
    /// Registration is mutation-free and freezes all claims before anything is
    /// applied. Activation is per feature: a broken unit extension cannot turn
    /// off an unrelated building or UI extension. A partial apply and a tick
    /// failure both trigger immediate ownership-aware rollback. Global shutdown
    /// rolls active features back in reverse activation order.
    /// </remarks>
    internal sealed class ExtensionFeatureHost
    {
        private sealed class Record
        {
            internal IExtensionFeature Feature;
            internal string Id;
            internal ExtensionLeaseClaim[] Claims;
            internal ExtensionFeatureState State;
            internal string Failure;
            internal long ActivationOrder;
        }

        private readonly List<Record> _records = new List<Record>();
        private readonly Dictionary<string, Record> _byId =
            new Dictionary<string, Record>(StringComparer.Ordinal);
        private bool _transitioning;
        private long _nextActivationOrder;

        internal bool TryRegister(IExtensionFeature feature, out string failure)
        {
            if (_transitioning)
            {
                failure = "extension lifecycle transition is already running";
                return false;
            }
            if (feature == null)
            {
                failure = "feature is null";
                return false;
            }

            string id;
            IReadOnlyList<ExtensionLeaseClaim> proposedClaims;
            try
            {
                id = feature.Id;
                proposedClaims = feature.ExclusiveClaims;
            }
            catch (Exception exception)
            {
                failure = "feature metadata failed: " + Describe(exception);
                return false;
            }
            if (!IsCanonicalId(id))
            {
                failure = "feature id is not canonical";
                return false;
            }
            if (_byId.ContainsKey(id))
            {
                failure = "feature id is already registered: " + id;
                return false;
            }
            if (proposedClaims == null)
            {
                failure = id + ": exclusive claims are null";
                return false;
            }

            int proposedClaimCount;
            try
            {
                proposedClaimCount = proposedClaims.Count;
            }
            catch (Exception exception)
            {
                failure = id + ": claim metadata failed: " + Describe(exception);
                return false;
            }
            if (proposedClaimCount > 128)
            {
                failure = id + ": more than 128 exclusive claims are not supported";
                return false;
            }

            var claims = new ExtensionLeaseClaim[proposedClaimCount];
            var local = new List<ExtensionLeaseClaim>();
            for (int index = 0; index < proposedClaimCount; index++)
            {
                ExtensionLeaseClaim claim;
                try
                {
                    claim = proposedClaims[index];
                }
                catch (Exception exception)
                {
                    failure = id + ": claim " + index + " failed: " + Describe(exception);
                    return false;
                }
                if (!claim.IsValid)
                {
                    failure = id + ": claim " + index + " is uninitialized";
                    return false;
                }
                ExtensionLeaseClaim localConflict;
                if (TryFindConflict(local, claim, out localConflict))
                {
                    failure = id + ": overlapping claims "
                        + localConflict + " and " + claim;
                    return false;
                }
                local.Add(claim);
                string owner;
                ExtensionLeaseClaim ownedClaim;
                if (TryFindOwner(claim, out ownedClaim, out owner))
                {
                    failure = id + ": claim " + claim + " overlaps "
                        + ownedClaim + " owned by " + owner;
                    return false;
                }
                claims[index] = claim;
            }

            var record = new Record
            {
                Feature = feature,
                Id = id,
                Claims = claims,
                State = ExtensionFeatureState.Registered,
            };
            _records.Add(record);
            _byId.Add(id, record);
            failure = null;
            return true;
        }

        private bool TryFindOwner(
            ExtensionLeaseClaim proposed,
            out ExtensionLeaseClaim ownedClaim,
            out string owner)
        {
            foreach (Record record in _records)
            {
                foreach (ExtensionLeaseClaim existing in record.Claims)
                {
                    if (proposed.ConflictsWith(existing))
                    {
                        ownedClaim = existing;
                        owner = record.Id;
                        return true;
                    }
                }
            }
            ownedClaim = default(ExtensionLeaseClaim);
            owner = null;
            return false;
        }

        private static bool TryFindConflict(
            IEnumerable<ExtensionLeaseClaim> existing,
            ExtensionLeaseClaim proposed,
            out ExtensionLeaseClaim conflict)
        {
            foreach (ExtensionLeaseClaim claim in existing)
            {
                if (proposed.ConflictsWith(claim))
                {
                    conflict = claim;
                    return true;
                }
            }
            conflict = default(ExtensionLeaseClaim);
            return false;
        }

        internal void ActivateAll()
        {
            BeginTransition();
            try
            {
                foreach (Record record in _records)
                {
                    if (record.State == ExtensionFeatureState.Registered
                        || record.State == ExtensionFeatureState.Stopped)
                    {
                        Activate(record);
                    }
                }
            }
            finally
            {
                _transitioning = false;
            }
        }

        internal void TickAll()
        {
            BeginTransition();
            try
            {
                foreach (Record record in _records)
                {
                    if (record.State != ExtensionFeatureState.Active)
                    {
                        continue;
                    }
                    try
                    {
                        record.Feature.Tick();
                    }
                    catch (Exception exception)
                    {
                        FailAndRollback(record, "tick", exception);
                    }
                }
            }
            finally
            {
                _transitioning = false;
            }
        }

        internal void RollbackAll()
        {
            BeginTransition();
            try
            {
                var active = new List<Record>();
                foreach (Record record in _records)
                {
                    if (record.State == ExtensionFeatureState.Active)
                    {
                        active.Add(record);
                    }
                }
                active.Sort((left, right) =>
                    right.ActivationOrder.CompareTo(left.ActivationOrder));
                foreach (Record record in active)
                {
                    try
                    {
                        record.Feature.RollbackOwned();
                        record.State = ExtensionFeatureState.Stopped;
                        record.Failure = null;
                    }
                    catch (Exception exception)
                    {
                        record.State = ExtensionFeatureState.Failed;
                        record.Failure = "rollback failed: " + Describe(exception);
                    }
                }
            }
            finally
            {
                _transitioning = false;
            }
        }

        internal ExtensionFeatureSnapshot[] Snapshot()
        {
            var values = new ExtensionFeatureSnapshot[_records.Count];
            for (int index = 0; index < _records.Count; index++)
            {
                Record record = _records[index];
                values[index] = new ExtensionFeatureSnapshot(
                    record.Id,
                    record.State,
                    record.Failure,
                    record.Claims.Length);
            }
            return values;
        }

        private void Activate(Record record)
        {
            string preflightFailure;
            try
            {
                if (!record.Feature.Prepare(out preflightFailure))
                {
                    record.State = ExtensionFeatureState.Failed;
                    record.Failure = string.IsNullOrWhiteSpace(preflightFailure)
                        ? "prepare refused without a reason"
                        : "prepare refused: " + SafeText(preflightFailure);
                    return;
                }
            }
            catch (Exception exception)
            {
                record.State = ExtensionFeatureState.Failed;
                record.Failure = "prepare failed: " + Describe(exception);
                return;
            }

            try
            {
                record.Feature.Apply();
                record.State = ExtensionFeatureState.Active;
                record.Failure = null;
                record.ActivationOrder = ++_nextActivationOrder;
            }
            catch (Exception exception)
            {
                FailAndRollback(record, "apply", exception);
            }
        }

        private static void FailAndRollback(
            Record record,
            string stage,
            Exception cause)
        {
            string failure = stage + " failed: " + Describe(cause);
            try
            {
                record.Feature.RollbackOwned();
            }
            catch (Exception rollback)
            {
                failure += "; rollback failed: " + Describe(rollback);
            }
            record.State = ExtensionFeatureState.Failed;
            record.Failure = failure;
        }

        private void BeginTransition()
        {
            if (_transitioning)
            {
                throw new InvalidOperationException(
                    "Extension lifecycle transitions must not be re-entered");
            }
            _transitioning = true;
        }

        private static bool IsCanonicalId(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length > 64)
            {
                return false;
            }
            for (int index = 0; index < value.Length; index++)
            {
                char character = value[index];
                bool alpha = character >= 'a' && character <= 'z';
                bool digit = character >= '0' && character <= '9';
                if (!alpha && !digit
                    && (index == 0
                        || (character != '-' && character != '_' && character != '.')))
                {
                    return false;
                }
            }
            return true;
        }

        private static string Describe(Exception exception)
        {
            return exception.GetType().Name + ": " + SafeText(exception.Message);
        }

        private static string SafeText(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "unspecified";
            }
            var characters = value.ToCharArray();
            for (int index = 0; index < characters.Length; index++)
            {
                if (char.IsControl(characters[index]) || characters[index] == '|')
                {
                    characters[index] = ' ';
                }
            }
            string safe = new string(characters).Trim();
            if (safe.Length == 0)
            {
                return "unspecified";
            }
            return safe.Length <= 256 ? safe : safe.Substring(0, 256);
        }
    }
}
