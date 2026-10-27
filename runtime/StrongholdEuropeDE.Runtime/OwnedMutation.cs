using System;
using System.Collections.Generic;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>The ownership state of one reversible value mutation.</summary>
    internal enum OwnedMutationState
    {
        Ready = 0,
        Applied = 1,
        Released = 2,
        Failed = 3,
    }

    /// <summary>The result of a conditional ownership-aware rollback.</summary>
    internal enum OwnedRollbackOutcome
    {
        NotApplied = 0,
        Restored = 1,
        OwnershipLost = 2,
        Failed = 3,
    }

    /// <summary>
    /// Non-generic boundary used to combine independently typed mutations.
    /// </summary>
    internal interface IOwnedMutation
    {
        ExtensionLeaseClaim Claim { get; }

        OwnedMutationState State { get; }

        bool TryApply(out string failure);

        bool VerifyOwnership(out string failure);

        OwnedRollbackOutcome RollbackOwned(out string failure);
    }

    /// <summary>
    /// Optional read-only gate run for every transaction item before the first
    /// setter is called.
    /// </summary>
    internal interface IOwnedMutationPreflight
    {
        bool TryPrepare(out string failure);
    }

    /// <summary>
    /// Applies one value and restores its original only while the applied value
    /// is still observable.
    /// </summary>
    /// <remarks>
    /// The read-back checks are intentional. A setter may throw after writing,
    /// silently clamp a value, or race with another mod. In all three cases the
    /// mutation re-reads before deciding whether the original may safely be
    /// restored. A foreign value is never overwritten.
    ///
    /// Instances are one-shot. Reusing an instance would capture a later mod's
    /// value as a new "original" and make ownership ambiguous.
    /// </remarks>
    internal sealed class OwnedValueMutation<T> :
        IOwnedMutation,
        IOwnedMutationPreflight
    {
        private readonly object _gate = new object();
        private readonly ExtensionLeaseClaim _claim;
        private readonly Func<T> _read;
        private readonly Action<T> _write;
        private readonly T _owned;
        private readonly IEqualityComparer<T> _comparer;
        private readonly bool _hasExpectedOriginal;
        private readonly T _expectedOriginal;
        private T _original;
        private bool _captured;
        private bool _transitioning;
        private OwnedMutationState _state;
        private string _failure;

        internal OwnedValueMutation(
            ExtensionLeaseClaim claim,
            Func<T> read,
            Action<T> write,
            T owned)
            : this(
                claim,
                read,
                write,
                false,
                default(T),
                owned,
                EqualityComparer<T>.Default)
        {
        }

        internal OwnedValueMutation(
            ExtensionLeaseClaim claim,
            Func<T> read,
            Action<T> write,
            T owned,
            IEqualityComparer<T> comparer)
            : this(
                claim,
                read,
                write,
                false,
                default(T),
                owned,
                comparer)
        {
        }

        internal OwnedValueMutation(
            ExtensionLeaseClaim claim,
            Func<T> read,
            Action<T> write,
            T expectedOriginal,
            T owned)
            : this(
                claim,
                read,
                write,
                true,
                expectedOriginal,
                owned,
                EqualityComparer<T>.Default)
        {
        }

        internal OwnedValueMutation(
            ExtensionLeaseClaim claim,
            Func<T> read,
            Action<T> write,
            T expectedOriginal,
            T owned,
            IEqualityComparer<T> comparer)
            : this(
                claim,
                read,
                write,
                true,
                expectedOriginal,
                owned,
                comparer)
        {
        }

        private OwnedValueMutation(
            ExtensionLeaseClaim claim,
            Func<T> read,
            Action<T> write,
            bool hasExpectedOriginal,
            T expectedOriginal,
            T owned,
            IEqualityComparer<T> comparer)
        {
            if (!claim.IsValid)
            {
                throw new ArgumentException(
                    "Mutation claim is uninitialized",
                    "claim");
            }
            if (read == null)
            {
                throw new ArgumentNullException("read");
            }
            if (write == null)
            {
                throw new ArgumentNullException("write");
            }
            if (comparer == null)
            {
                throw new ArgumentNullException("comparer");
            }
            _claim = claim;
            _read = read;
            _write = write;
            _hasExpectedOriginal = hasExpectedOriginal;
            _expectedOriginal = expectedOriginal;
            _owned = owned;
            _comparer = comparer;
            _state = OwnedMutationState.Ready;
        }

        public ExtensionLeaseClaim Claim
        {
            get { return _claim; }
        }

        public OwnedMutationState State
        {
            get
            {
                lock (_gate)
                {
                    return _state;
                }
            }
        }

        internal string Failure
        {
            get
            {
                lock (_gate)
                {
                    return _failure;
                }
            }
        }

        public bool TryPrepare(out string failure)
        {
            lock (_gate)
            {
                BeginTransition();
                try
                {
                    if (_state != OwnedMutationState.Ready)
                    {
                        failure = Claim + ": mutation is not ready";
                        return false;
                    }
                    T current;
                    try
                    {
                        current = _read();
                    }
                    catch (Exception exception)
                    {
                        failure = Claim + ": preflight read failed: "
                            + Describe(exception);
                        return false;
                    }
                    if (_hasExpectedOriginal
                        && !_comparer.Equals(current, _expectedOriginal))
                    {
                        failure = Claim
                            + ": expected original differs; foreign state was preserved";
                        return false;
                    }
                    failure = null;
                    return true;
                }
                finally
                {
                    _transitioning = false;
                }
            }
        }

        public bool TryApply(out string failure)
        {
            lock (_gate)
            {
                BeginTransition();
                try
                {
                    if (_state != OwnedMutationState.Ready)
                    {
                        failure = Claim + ": mutation is not ready";
                        return false;
                    }

                    try
                    {
                        _original = _read();
                        _captured = true;
                    }
                    catch (Exception exception)
                    {
                        return FailReleased(
                            "original read failed: " + Describe(exception),
                            out failure);
                    }
                    if (_hasExpectedOriginal
                        && !_comparer.Equals(_original, _expectedOriginal))
                    {
                        return FailReleased(
                            "expected original differs; foreign state was preserved",
                            out failure);
                    }

                    T beforeWrite;
                    try
                    {
                        beforeWrite = _read();
                    }
                    catch (Exception exception)
                    {
                        return FailReleased(
                            "pre-write read failed: " + Describe(exception),
                            out failure);
                    }
                    if (!_comparer.Equals(beforeWrite, _original))
                    {
                        return FailReleased(
                            "value changed before write; current value was preserved",
                            out failure);
                    }

                    try
                    {
                        _write(_owned);
                    }
                    catch (Exception exception)
                    {
                        string recovery = RecoverAfterApplyFailure();
                        string message = "write failed: " + Describe(exception)
                            + "; " + recovery;
                        if (_state != OwnedMutationState.Failed)
                        {
                            _state = OwnedMutationState.Released;
                        }
                        _failure = Claim + ": " + message;
                        failure = _failure;
                        return false;
                    }

                    T current;
                    try
                    {
                        current = _read();
                    }
                    catch (Exception exception)
                    {
                        string recovery = RecoverAfterApplyFailure();
                        string message = "apply read-back failed: "
                            + Describe(exception) + "; " + recovery;
                        if (_state != OwnedMutationState.Failed)
                        {
                            _state = OwnedMutationState.Released;
                        }
                        _failure = Claim + ": " + message;
                        failure = _failure;
                        return false;
                    }
                    if (!_comparer.Equals(current, _owned))
                    {
                        _state = OwnedMutationState.Released;
                        _failure = Claim
                            + ": apply read-back differs; current value is preserved";
                        failure = _failure;
                        return false;
                    }

                    _state = OwnedMutationState.Applied;
                    _failure = null;
                    failure = null;
                    return true;
                }
                finally
                {
                    _transitioning = false;
                }
            }
        }

        public bool VerifyOwnership(out string failure)
        {
            lock (_gate)
            {
                BeginTransition();
                try
                {
                    if (_state != OwnedMutationState.Applied)
                    {
                        failure = Claim + ": mutation is not applied";
                        return false;
                    }
                    try
                    {
                        T current = _read();
                        if (!_comparer.Equals(current, _owned))
                        {
                            failure = Claim + ": ownership was lost";
                            return false;
                        }
                    }
                    catch (Exception exception)
                    {
                        failure = Claim + ": ownership read failed: "
                            + Describe(exception);
                        return false;
                    }
                    failure = null;
                    return true;
                }
                finally
                {
                    _transitioning = false;
                }
            }
        }

        public OwnedRollbackOutcome RollbackOwned(out string failure)
        {
            lock (_gate)
            {
                BeginTransition();
                try
                {
                    if (_state == OwnedMutationState.Ready)
                    {
                        _state = OwnedMutationState.Released;
                        failure = null;
                        return OwnedRollbackOutcome.NotApplied;
                    }
                    if (_state == OwnedMutationState.Released)
                    {
                        failure = null;
                        return OwnedRollbackOutcome.NotApplied;
                    }
                    if (_state == OwnedMutationState.Failed)
                    {
                        failure = _failure ?? (Claim + ": mutation failed");
                        return OwnedRollbackOutcome.Failed;
                    }

                    T current;
                    try
                    {
                        current = _read();
                    }
                    catch (Exception exception)
                    {
                        return FailRollback(
                            "rollback read failed: " + Describe(exception),
                            out failure);
                    }
                    if (!_comparer.Equals(current, _owned))
                    {
                        _state = OwnedMutationState.Released;
                        _failure = null;
                        failure = Claim
                            + ": ownership was lost; foreign value was preserved";
                        return OwnedRollbackOutcome.OwnershipLost;
                    }

                    try
                    {
                        _write(_original);
                    }
                    catch (Exception exception)
                    {
                        return ClassifyRollbackWriteFailure(exception, out failure);
                    }

                    try
                    {
                        current = _read();
                    }
                    catch (Exception exception)
                    {
                        return FailRollback(
                            "rollback read-back failed: " + Describe(exception),
                            out failure);
                    }
                    if (_comparer.Equals(current, _original))
                    {
                        _state = OwnedMutationState.Released;
                        _failure = null;
                        failure = null;
                        return OwnedRollbackOutcome.Restored;
                    }
                    if (!_comparer.Equals(current, _owned))
                    {
                        _state = OwnedMutationState.Released;
                        _failure = null;
                        failure = Claim
                            + ": rollback read-back changed externally; value was preserved";
                        return OwnedRollbackOutcome.OwnershipLost;
                    }
                    return FailRollback(
                        "rollback write did not change the owned value",
                        out failure);
                }
                finally
                {
                    _transitioning = false;
                }
            }
        }

        private string RecoverAfterApplyFailure()
        {
            if (!_captured)
            {
                return "no original was captured";
            }
            T current;
            try
            {
                current = _read();
            }
            catch (Exception exception)
            {
                _state = OwnedMutationState.Failed;
                return "recovery read failed: " + Describe(exception);
            }
            if (_comparer.Equals(current, _original))
            {
                return "original remained observable";
            }
            if (!_comparer.Equals(current, _owned))
            {
                return "ownership was lost; foreign value was preserved";
            }
            try
            {
                _write(_original);
                current = _read();
            }
            catch (Exception exception)
            {
                _state = OwnedMutationState.Failed;
                return "recovery restore failed: " + Describe(exception);
            }
            if (_comparer.Equals(current, _original))
            {
                return "owned value was restored";
            }
            if (!_comparer.Equals(current, _owned))
            {
                return "recovery lost ownership; foreign value was preserved";
            }
            _state = OwnedMutationState.Failed;
            return "recovery restore did not change the owned value";
        }

        private OwnedRollbackOutcome ClassifyRollbackWriteFailure(
            Exception cause,
            out string failure)
        {
            T current;
            try
            {
                current = _read();
            }
            catch (Exception readException)
            {
                return FailRollback(
                    "rollback write failed: " + Describe(cause)
                    + "; read-back failed: " + Describe(readException),
                    out failure);
            }
            if (_comparer.Equals(current, _original))
            {
                _state = OwnedMutationState.Released;
                _failure = null;
                failure = null;
                return OwnedRollbackOutcome.Restored;
            }
            if (!_comparer.Equals(current, _owned))
            {
                _state = OwnedMutationState.Released;
                _failure = null;
                failure = Claim
                    + ": rollback write failed after ownership changed; foreign value was preserved";
                return OwnedRollbackOutcome.OwnershipLost;
            }
            return FailRollback(
                "rollback write failed: " + Describe(cause),
                out failure);
        }

        private bool FailReleased(string message, out string failure)
        {
            _state = OwnedMutationState.Released;
            _failure = Claim + ": " + message;
            failure = _failure;
            return false;
        }

        private OwnedRollbackOutcome FailRollback(
            string message,
            out string failure)
        {
            _state = OwnedMutationState.Failed;
            _failure = Claim + ": " + message;
            failure = _failure;
            return OwnedRollbackOutcome.Failed;
        }

        private void BeginTransition()
        {
            if (_transitioning)
            {
                throw new InvalidOperationException(
                    "Owned mutation transitions must not be re-entered");
            }
            _transitioning = true;
        }

        private static string Describe(Exception exception)
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

    /// <summary>Counts every outcome of a transaction rollback.</summary>
    internal struct OwnedRollbackSummary
    {
        internal int NotApplied;
        internal int Restored;
        internal int OwnershipLost;
        internal int Failed;

        internal bool Succeeded
        {
            get { return Failed == 0; }
        }
    }

    /// <summary>
    /// Applies differently typed owned mutations in order and rolls them back
    /// in reverse order when any later mutation fails.
    /// </summary>
    internal sealed class OwnedMutationTransaction
    {
        private readonly object _gate = new object();
        private readonly IOwnedMutation[] _mutations;
        private readonly IReadOnlyList<ExtensionLeaseClaim> _claims;
        private readonly List<IOwnedMutation> _applied =
            new List<IOwnedMutation>();
        private bool _transitioning;
        private OwnedMutationState _state;
        private string _failure;

        internal OwnedMutationTransaction(params IOwnedMutation[] mutations)
        {
            if (mutations == null)
            {
                throw new ArgumentNullException("mutations");
            }
            if (mutations.Length == 0 || mutations.Length > 128)
            {
                throw new ArgumentOutOfRangeException(
                    "mutations",
                    "A mutation transaction requires between 1 and 128 entries");
            }
            var claims = new List<ExtensionLeaseClaim>();
            var claimArray = new ExtensionLeaseClaim[mutations.Length];
            _mutations = new IOwnedMutation[mutations.Length];
            for (int index = 0; index < mutations.Length; index++)
            {
                IOwnedMutation mutation = mutations[index];
                if (mutation == null)
                {
                    throw new ArgumentException(
                        "Mutation transaction contains null",
                        "mutations");
                }
                ExtensionLeaseClaim conflict = default(ExtensionLeaseClaim);
                bool overlaps = false;
                foreach (ExtensionLeaseClaim existing in claims)
                {
                    if (mutation.Claim.ConflictsWith(existing))
                    {
                        conflict = existing;
                        overlaps = true;
                        break;
                    }
                }
                if (overlaps)
                {
                    throw new ArgumentException(
                        "Mutation transaction contains overlapping claims "
                        + conflict + " and " + mutation.Claim,
                        "mutations");
                }
                claims.Add(mutation.Claim);
                _mutations[index] = mutation;
                claimArray[index] = mutation.Claim;
            }
            _claims = Array.AsReadOnly(claimArray);
            _state = OwnedMutationState.Ready;
        }

        /// <summary>
        /// Frozen claims suitable for an extension feature's
        /// <c>ExclusiveClaims</c> property.
        /// </summary>
        internal IReadOnlyList<ExtensionLeaseClaim> Claims
        {
            get { return _claims; }
        }

        internal OwnedMutationState State
        {
            get
            {
                lock (_gate)
                {
                    return _state;
                }
            }
        }

        internal bool TryPrepare(out string failure)
        {
            lock (_gate)
            {
                BeginTransition();
                try
                {
                    if (_state != OwnedMutationState.Ready)
                    {
                        failure = "mutation transaction is not ready";
                        return false;
                    }
                    return PreflightAll(out failure);
                }
                finally
                {
                    _transitioning = false;
                }
            }
        }

        internal bool TryApply(out string failure)
        {
            lock (_gate)
            {
                BeginTransition();
                try
                {
                    if (_state != OwnedMutationState.Ready)
                    {
                        failure = "mutation transaction is not ready";
                        return false;
                    }
                    string preflightFailure;
                    if (!PreflightAll(out preflightFailure))
                    {
                        _state = OwnedMutationState.Released;
                        _failure = "transaction preflight failed: "
                            + preflightFailure;
                        failure = _failure;
                        return false;
                    }
                    foreach (IOwnedMutation mutation in _mutations)
                    {
                        string itemFailure;
                        bool applied;
                        try
                        {
                            applied = mutation.TryApply(out itemFailure);
                        }
                        catch (Exception exception)
                        {
                            applied = false;
                            itemFailure = "mutation threw: "
                                + DescribeException(exception);
                        }
                        if (!applied)
                        {
                            // The failed item goes first so a custom mutation
                            // which threw after writing gets one conditional
                            // cleanup attempt before earlier items roll back.
                            _applied.Add(mutation);
                            OwnedRollbackSummary cleanup = RollbackApplied();
                            _state = cleanup.Succeeded
                                ? OwnedMutationState.Released
                                : OwnedMutationState.Failed;
                            _failure = "transaction apply failed at "
                                + mutation.Claim + ": " + itemFailure;
                            if (!cleanup.Succeeded)
                            {
                                _failure += "; rollback failures=" + cleanup.Failed;
                            }
                            failure = _failure;
                            return false;
                        }
                        _applied.Add(mutation);
                    }
                    _state = OwnedMutationState.Applied;
                    _failure = null;
                    failure = null;
                    return true;
                }
                finally
                {
                    _transitioning = false;
                }
            }
        }

        internal bool VerifyOwnership(out string failure)
        {
            lock (_gate)
            {
                BeginTransition();
                try
                {
                    if (_state != OwnedMutationState.Applied)
                    {
                        failure = "mutation transaction is not applied";
                        return false;
                    }
                    foreach (IOwnedMutation mutation in _applied)
                    {
                        string itemFailure;
                        bool owned;
                        try
                        {
                            owned = mutation.VerifyOwnership(out itemFailure);
                        }
                        catch (Exception exception)
                        {
                            owned = false;
                            itemFailure = mutation.Claim
                                + ": ownership verification threw: "
                                + DescribeException(exception);
                        }
                        if (!owned)
                        {
                            failure = itemFailure;
                            return false;
                        }
                    }
                    failure = null;
                    return true;
                }
                finally
                {
                    _transitioning = false;
                }
            }
        }

        internal OwnedRollbackSummary RollbackOwned(out string failure)
        {
            lock (_gate)
            {
                BeginTransition();
                try
                {
                    if (_state != OwnedMutationState.Applied)
                    {
                        if (_state == OwnedMutationState.Ready)
                        {
                            _state = OwnedMutationState.Released;
                        }
                        failure = _state == OwnedMutationState.Failed
                            ? _failure
                            : null;
                        return new OwnedRollbackSummary();
                    }
                    OwnedRollbackSummary summary = RollbackApplied();
                    _state = summary.Succeeded
                        ? OwnedMutationState.Released
                        : OwnedMutationState.Failed;
                    _failure = summary.Succeeded
                        ? null
                        : "mutation transaction rollback failures=" + summary.Failed;
                    failure = _failure;
                    return summary;
                }
                finally
                {
                    _transitioning = false;
                }
            }
        }

        private OwnedRollbackSummary RollbackApplied()
        {
            var summary = new OwnedRollbackSummary();
            for (int index = _applied.Count - 1; index >= 0; index--)
            {
                string ignored;
                OwnedRollbackOutcome outcome;
                try
                {
                    outcome = _applied[index].RollbackOwned(out ignored);
                }
                catch
                {
                    // Continue with earlier mutations. One broken custom item
                    // must not strand every resource applied before it.
                    outcome = OwnedRollbackOutcome.Failed;
                }
                if (outcome == OwnedRollbackOutcome.Restored)
                {
                    summary.Restored++;
                }
                else if (outcome == OwnedRollbackOutcome.OwnershipLost)
                {
                    summary.OwnershipLost++;
                }
                else if (outcome == OwnedRollbackOutcome.Failed)
                {
                    summary.Failed++;
                }
                else
                {
                    summary.NotApplied++;
                }
            }
            _applied.Clear();
            return summary;
        }

        private bool PreflightAll(out string failure)
        {
            foreach (IOwnedMutation mutation in _mutations)
            {
                var preflight = mutation as IOwnedMutationPreflight;
                if (preflight == null)
                {
                    continue;
                }
                string itemFailure;
                bool prepared;
                try
                {
                    prepared = preflight.TryPrepare(out itemFailure);
                }
                catch (Exception exception)
                {
                    prepared = false;
                    itemFailure = mutation.Claim + ": preflight threw: "
                        + DescribeException(exception);
                }
                if (!prepared)
                {
                    failure = itemFailure;
                    return false;
                }
            }
            failure = null;
            return true;
        }

        private static string DescribeException(Exception exception)
        {
            string value = exception.GetType().Name + ": " + exception.Message;
            char[] characters = value.ToCharArray();
            for (int index = 0; index < characters.Length; index++)
            {
                if (char.IsControl(characters[index]) || characters[index] == '|')
                {
                    characters[index] = ' ';
                }
            }
            value = new string(characters).Trim();
            if (value.Length == 0)
            {
                return "unspecified";
            }
            return value.Length <= 256 ? value : value.Substring(0, 256);
        }

        private void BeginTransition()
        {
            if (_transitioning)
            {
                throw new InvalidOperationException(
                    "Mutation transaction transitions must not be re-entered");
            }
            _transitioning = true;
        }
    }
}
