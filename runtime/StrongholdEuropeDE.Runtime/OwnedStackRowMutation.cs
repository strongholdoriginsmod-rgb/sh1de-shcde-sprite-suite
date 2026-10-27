using System;
using System.Collections.Generic;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed class StackRowRollbackSummary
    {
        internal int Restored { get; set; }

        internal int OwnershipLost { get; set; }

        internal int Failed { get; set; }

        internal bool Succeeded
        {
            get { return Failed == 0; }
        }
    }

    /// <summary>
    /// Owns one row pushed onto an extender-managed native-table stack.
    /// </summary>
    /// <remarks>
    /// A row is applied left-to-right and unwound right-to-left. Rollback pops
    /// a cell only while the value we pushed is still visible. This preserves
    /// a later mod's value and avoids the global <c>ClearOverrides</c> operation,
    /// which would erase unrelated mods along with ours.
    /// </remarks>
    internal sealed class OwnedStackRowMutation<T>
    {
        private readonly ExtensionLeaseClaim _claim;
        private readonly Func<int, T> _get;
        private readonly Action<int, T> _push;
        private readonly Func<int, T> _pop;
        private readonly T[] _owned;
        private readonly T[] _previous;
        private readonly bool[] _pushed;
        private readonly IEqualityComparer<T> _equality;
        private bool _applyAttempted;
        private bool _released;

        internal OwnedStackRowMutation(
            ExtensionLeaseClaim claim,
            Func<int, T> get,
            Action<int, T> push,
            Func<int, T> pop,
            IReadOnlyList<T> owned,
            IEqualityComparer<T> equality = null)
        {
            if (!claim.IsValid)
            {
                throw new ArgumentException("Stack-row claim is uninitialized", "claim");
            }
            if (!string.Equals(
                    claim.Domain,
                    "native-table-row",
                    StringComparison.Ordinal))
            {
                throw new ArgumentException(
                    "Stack-row mutation requires a native-table-row claim",
                    "claim");
            }
            if (get == null)
            {
                throw new ArgumentNullException("get");
            }
            if (push == null)
            {
                throw new ArgumentNullException("push");
            }
            if (pop == null)
            {
                throw new ArgumentNullException("pop");
            }
            if (owned == null || owned.Count == 0 || owned.Count > 1024)
            {
                throw new ArgumentException(
                    "Stack-row values must contain 1..1024 cells",
                    "owned");
            }
            _claim = claim;
            _get = get;
            _push = push;
            _pop = pop;
            _owned = new T[owned.Count];
            for (int index = 0; index < owned.Count; index++)
            {
                _owned[index] = owned[index];
            }
            _previous = new T[_owned.Length];
            _pushed = new bool[_owned.Length];
            _equality = equality ?? EqualityComparer<T>.Default;
        }

        internal ExtensionLeaseClaim Claim
        {
            get { return _claim; }
        }

        internal int Count
        {
            get { return _owned.Length; }
        }

        internal bool TryApply(out string failure)
        {
            if (_applyAttempted)
            {
                failure = "stack row is one-shot";
                return false;
            }
            _applyAttempted = true;
            for (int column = 0; column < _owned.Length; column++)
            {
                try
                {
                    _previous[column] = _get(column);
                    _push(column, _owned[column]);
                    T observed = _get(column);
                    if (!_equality.Equals(observed, _owned[column]))
                    {
                        failure = "stack row read-back differs at column " + column;
                        StackRowRollbackSummary ignored;
                        string rollbackFailure;
                        RollbackOwned(out ignored, out rollbackFailure);
                        if (!string.IsNullOrEmpty(rollbackFailure))
                        {
                            failure += "; " + rollbackFailure;
                        }
                        return false;
                    }
                    _pushed[column] = true;
                }
                catch (Exception exception)
                {
                    // A push may throw after changing the cell. Re-read before
                    // deciding that it is ours and therefore safe to pop.
                    try
                    {
                        _pushed[column] = _equality.Equals(
                            _get(column),
                            _owned[column]);
                    }
                    catch
                    {
                        _pushed[column] = false;
                    }
                    failure = "stack row apply failed at column " + column
                        + ": " + Describe(exception);
                    StackRowRollbackSummary ignored;
                    string rollbackFailure;
                    RollbackOwned(out ignored, out rollbackFailure);
                    if (!string.IsNullOrEmpty(rollbackFailure))
                    {
                        failure += "; " + rollbackFailure;
                    }
                    return false;
                }
            }
            failure = null;
            return true;
        }

        internal bool RollbackOwned(
            out StackRowRollbackSummary summary,
            out string failure)
        {
            summary = new StackRowRollbackSummary();
            if (_released)
            {
                failure = null;
                return true;
            }
            _released = true;
            var failures = new List<string>();
            for (int column = _pushed.Length - 1; column >= 0; column--)
            {
                if (!_pushed[column])
                {
                    continue;
                }
                try
                {
                    T current = _get(column);
                    if (!_equality.Equals(current, _owned[column]))
                    {
                        summary.OwnershipLost++;
                        continue;
                    }
                    T revealed = _pop(column);
                    T observed = _get(column);
                    if (!_equality.Equals(revealed, _previous[column])
                        || !_equality.Equals(observed, _previous[column]))
                    {
                        summary.Failed++;
                        failures.Add("column " + column + " did not reveal its predecessor");
                        continue;
                    }
                    summary.Restored++;
                }
                catch (Exception exception)
                {
                    summary.Failed++;
                    failures.Add("column " + column + ": " + Describe(exception));
                }
            }
            failure = failures.Count == 0 ? null : string.Join("; ", failures);
            return summary.Succeeded;
        }

        private static string Describe(Exception exception)
        {
            return exception.GetType().Name + ": " + exception.Message;
        }
    }
}
