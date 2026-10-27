using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;

namespace StrongholdEuropeDE.Runtime
{
    internal enum ScriptExtenderScanBufferTrackedMemoryState
    {
        Untracked,
        Active,
        Cleared,
        Aborted,
    }

    internal enum ScriptExtenderScanBufferCommitResult
    {
        Untracked,
        RetainedFailure,
        Released,
        AlreadyTerminal,
    }

    /// <summary>
    /// Per-constructor state carried through Harmony's __state channel.
    /// Parent links form a thread-local stack in the runtime caller.
    /// </summary>
    internal sealed class ScriptExtenderScanBufferInvocationFrame<TLease>
        where TLease : class
    {
        internal ScriptExtenderScanBufferInvocationFrame(
            ScriptExtenderScanBufferInvocationFrame<TLease> parent)
        {
            Parent = parent;
        }

        internal ScriptExtenderScanBufferInvocationFrame<TLease> Parent
        {
            get;
            private set;
        }

        internal TLease Lease { get; set; }
        internal object BoundOwner { get; set; }
        internal bool Closed { get; set; }
        internal bool Completed { get; set; }
    }

    /// <summary>
    /// Dependency-free lifetime state machine shared by the production patch
    /// and its executable harness. Callers provide the concrete memory-clear
    /// and lease-release operations; this class owns exact frame/owner state
    /// and guarantees a successful release transition occurs at most once.
    /// </summary>
    internal sealed class ScriptExtenderScanBufferLeaseMachine<TLease>
        where TLease : class
    {
        private readonly Dictionary<object, TransactionRecord> _transactions =
            new Dictionary<object, TransactionRecord>(
                ReferenceComparer.Instance);
        private int _activeCount;

        internal int ActiveCount
        {
            get { return _activeCount; }
        }

        internal ScriptExtenderScanBufferInvocationFrame<TLease> Push(
            ref ScriptExtenderScanBufferInvocationFrame<TLease> current)
        {
            var frame = new ScriptExtenderScanBufferInvocationFrame<TLease>(
                current);
            current = frame;
            return frame;
        }

        internal void AttachLease(
            ScriptExtenderScanBufferInvocationFrame<TLease> current,
            TLease lease)
        {
            if (current == null
                || current.Closed
                || current.Completed
                || current.Lease != null
                || lease == null)
            {
                throw new InvalidOperationException(
                    "Constructor invocation cannot accept this scan lease");
            }
            current.Lease = lease;
        }

        internal void Pop(
            ref ScriptExtenderScanBufferInvocationFrame<TLease> current,
            ScriptExtenderScanBufferInvocationFrame<TLease> expected)
        {
            if (expected == null
                || expected.Closed
                || expected.Completed
                || !ReferenceEquals(current, expected))
            {
                throw new InvalidOperationException(
                    "Constructor invocation stack order changed");
            }
            current = expected.Parent;
            expected.Closed = true;
        }

        internal void Bind(
            ScriptExtenderScanBufferInvocationFrame<TLease> frame,
            object owner)
        {
            if (frame == null
                || !frame.Closed
                || frame.Completed
                || frame.Lease == null
                || frame.BoundOwner != null
                || owner == null
                || _transactions.ContainsKey(owner))
            {
                throw new InvalidOperationException(
                    "Constructor lease cannot be bound to this owner");
            }
            _transactions.Add(
                owner,
                new TransactionRecord(
                    frame.Lease,
                    ScriptExtenderScanBufferTrackedMemoryState.Active));
            frame.BoundOwner = owner;
            _activeCount = checked(_activeCount + 1);
        }

        internal void CompleteFrame(
            ScriptExtenderScanBufferInvocationFrame<TLease> frame)
        {
            RequireOpenCompletion(frame);
            if (frame.Lease != null)
            {
                TransactionRecord record;
                if (frame.BoundOwner == null
                    || !_transactions.TryGetValue(
                        frame.BoundOwner,
                        out record)
                    || (record.State
                            == ScriptExtenderScanBufferTrackedMemoryState.Active
                        ? !ReferenceEquals(record.Lease, frame.Lease)
                        : record.Lease != null))
                {
                    throw new InvalidOperationException(
                        "Completed constructor lease is not actively bound");
                }
            }
            else if (frame.BoundOwner != null)
            {
                throw new InvalidOperationException(
                    "Constructor owner exists without a lease");
            }
            CompleteUnchecked(frame);
        }

        internal void AbortFrame(
            ScriptExtenderScanBufferInvocationFrame<TLease> frame,
            object instance,
            Action<object> clearMemory,
            Action<TLease, object, bool> releaseLease)
        {
            RequireOpenCompletion(frame);
            if (frame.Lease == null)
            {
                if (frame.BoundOwner != null)
                {
                    throw new InvalidOperationException(
                        "Aborted constructor owner exists without a lease");
                }
                CompleteUnchecked(frame);
                return;
            }
            if (instance == null
                || clearMemory == null
                || releaseLease == null)
            {
                throw new ArgumentNullException(
                    "Failed constructor cleanup dependency is unavailable");
            }

            TransactionRecord record = null;
            if (frame.BoundOwner != null)
            {
                if (!ReferenceEquals(frame.BoundOwner, instance)
                    || !_transactions.TryGetValue(instance, out record))
                {
                    throw new InvalidOperationException(
                        "Aborted constructor owner changed");
                }
                if (record.State
                    != ScriptExtenderScanBufferTrackedMemoryState.Active)
                {
                    if (record.Lease != null)
                    {
                        throw new InvalidOperationException(
                            "Terminal constructor owner retained a lease");
                    }
                    CompleteUnchecked(frame);
                    return;
                }
                if (!ReferenceEquals(record.Lease, frame.Lease))
                {
                    throw new InvalidOperationException(
                        "Aborted constructor lease changed");
                }
                if (_activeCount <= 0)
                {
                    throw new InvalidOperationException(
                        "Active constructor lease count changed");
                }
            }

            clearMemory(instance);
            releaseLease(frame.Lease, frame.BoundOwner, true);
            if (record != null)
            {
                record.Lease = null;
                record.State =
                    ScriptExtenderScanBufferTrackedMemoryState.Aborted;
                _activeCount--;
            }
            CompleteUnchecked(frame);
        }

        internal ScriptExtenderScanBufferCommitResult Commit(
            object owner,
            bool commitSucceeded,
            Action<object> clearMemory,
            Action<TLease, object, bool> releaseLease)
        {
            TransactionRecord record;
            if (owner == null || !_transactions.TryGetValue(owner, out record))
            {
                return ScriptExtenderScanBufferCommitResult.Untracked;
            }
            if (record.State
                != ScriptExtenderScanBufferTrackedMemoryState.Active)
            {
                    return ScriptExtenderScanBufferCommitResult.AlreadyTerminal;
            }
            if (!commitSucceeded)
            {
                return ScriptExtenderScanBufferCommitResult.RetainedFailure;
            }
            if (clearMemory == null || releaseLease == null)
            {
                throw new ArgumentNullException(
                    "Commit cleanup dependency is unavailable");
            }
            if (_activeCount <= 0)
            {
                throw new InvalidOperationException(
                    "Active commit lease count changed");
            }

            clearMemory(owner);
            releaseLease(record.Lease, owner, false);
            record.Lease = null;
            record.State = ScriptExtenderScanBufferTrackedMemoryState.Cleared;
            _activeCount--;
            return ScriptExtenderScanBufferCommitResult.Released;
        }

        internal ScriptExtenderScanBufferTrackedMemoryState GetState(
            object owner)
        {
            TransactionRecord record;
            return owner != null
                && _transactions.TryGetValue(owner, out record)
                    ? record.State
                    : ScriptExtenderScanBufferTrackedMemoryState.Untracked;
        }

        internal bool ContainsActiveLease(TLease lease)
        {
            if (lease == null)
            {
                return false;
            }
            foreach (TransactionRecord record in _transactions.Values)
            {
                if (record.State
                        == ScriptExtenderScanBufferTrackedMemoryState.Active
                    && ReferenceEquals(record.Lease, lease))
                {
                    return true;
                }
            }
            return false;
        }

        internal bool AllActive(
            Func<object, TLease, bool> predicate)
        {
            if (predicate == null)
            {
                throw new ArgumentNullException("predicate");
            }
            int visited = 0;
            foreach (KeyValuePair<object, TransactionRecord> pair
                in _transactions)
            {
                if (pair.Value.State
                    != ScriptExtenderScanBufferTrackedMemoryState.Active)
                {
                    continue;
                }
                visited++;
                if (!predicate(pair.Key, pair.Value.Lease))
                {
                    return false;
                }
            }
            return visited == _activeCount;
        }

        private static void RequireOpenCompletion(
            ScriptExtenderScanBufferInvocationFrame<TLease> frame)
        {
            if (frame == null || !frame.Closed || frame.Completed)
            {
                throw new InvalidOperationException(
                    "Constructor invocation cannot complete twice");
            }
        }

        private static void CompleteUnchecked(
            ScriptExtenderScanBufferInvocationFrame<TLease> frame)
        {
            frame.Lease = null;
            frame.BoundOwner = null;
            frame.Completed = true;
        }

        private sealed class TransactionRecord
        {
            internal TransactionRecord(
                TLease lease,
                ScriptExtenderScanBufferTrackedMemoryState state)
            {
                Lease = lease;
                State = state;
            }

            internal TLease Lease;
            internal ScriptExtenderScanBufferTrackedMemoryState State;
        }

        private sealed class ReferenceComparer : IEqualityComparer<object>
        {
            internal static readonly ReferenceComparer Instance =
                new ReferenceComparer();

            public new bool Equals(object left, object right)
            {
                return ReferenceEquals(left, right);
            }

            public int GetHashCode(object value)
            {
                return RuntimeHelpers.GetHashCode(value);
            }
        }
    }
}
