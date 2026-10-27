using System;
using System.Collections.Generic;
using System.Threading;

namespace StrongholdEuropeDE.Runtime
{
    // Pure contracts used by the live adapter, independently executable without
    // a game process. 2026-09-07: global observers must never retarget another
    // thread's operation, and observing a second thread must not flood the log.
    internal static class DiplomacyRuntimeSafety
    {
        internal static bool MatchesResourceCall(
            int ownerThread, int currentThread,
            int expectedPlayer, int player, int expectedGood, int good,
            int expectedAmount, int amount)
        {
            return ownerThread == currentThread
                && expectedPlayer == player
                && expectedGood == good
                && expectedAmount == amount;
        }

        internal static void SaturatingIncrement(ref int value)
        {
            int observed = Volatile.Read(ref value);
            while (observed < int.MaxValue)
            {
                int prior = Interlocked.CompareExchange(
                    ref value, observed + 1, observed);
                if (prior == observed) return;
                observed = prior;
            }
        }

        internal static void RunDayPhases<T>(
            T[] items, Func<T, bool> advanceModel, Action commitDay,
            Action<T, bool> applyEffects)
        {
            var outcomes = new bool[items.Length];
            for (int i = 0; i < items.Length; i++)
                outcomes[i] = advanceModel(items[i]);
            commitDay();
            for (int i = 0; i < items.Length; i++)
                applyEffects(items[i], outcomes[i]);
        }
    }

    // The native popup shares answer delegates between every visual instance.
    // Keep a decision active until its callback completes; queued duplicates
    // cannot restart a deadline or replace the player's current question.
    internal sealed class DiplomacyDialogQueue<T> where T : class
    {
        private sealed class Entry
        {
            internal string Key;
            internal T Item;
            internal bool Routine;
        }

        private readonly LinkedList<Entry> _pending = new LinkedList<Entry>();
        private readonly HashSet<string> _keys = new HashSet<string>(StringComparer.Ordinal);
        private Entry _active;
        internal T Active { get { return _active == null ? null : _active.Item; } }
        internal int Count { get { return _pending.Count + (_active == null ? 0 : 1); } }
        internal bool ContainsKey(string key) { return key != null && _keys.Contains(key); }

        internal bool Enqueue(string key, T item)
        {
            if (item == null) throw new ArgumentNullException("item");
            if (key != null && !_keys.Add(key)) return false;
            _pending.AddLast(new Entry { Key = key, Item = item });
            return true;
        }

        // Plain informational OKs have no pending gameplay decision. Keep a
        // bounded set of recent notices without evicting a choice or active UI.
        internal bool EnqueueRoutine(string key, T item)
        {
            if (item == null) throw new ArgumentNullException("item");
            if (string.IsNullOrEmpty(key)) throw new ArgumentException("A routine notice needs an identity", "key");
            if (_keys.Contains(key)) return false;
            int count = _active != null && _active.Routine ? 1 : 0;
            LinkedListNode<Entry> oldest = null;
            for (LinkedListNode<Entry> node = _pending.First; node != null; node = node.Next)
                if (node.Value.Routine) { count++; if (oldest == null) oldest = node; }
            if (count >= 16 && oldest != null)
            {
                _keys.Remove(oldest.Value.Key);
                _pending.Remove(oldest);
            }
            _keys.Add(key);
            _pending.AddLast(new Entry { Key = key, Item = item, Routine = true });
            return true;
        }

        internal T BeginNext()
        {
            if (_active != null || _pending.Count == 0) return null;
            _active = _pending.First.Value;
            _pending.RemoveFirst();
            return _active.Item;
        }

        internal bool Complete(T item)
        {
            if (_active == null || !ReferenceEquals(_active.Item, item)) return false;
            if (_active.Key != null) _keys.Remove(_active.Key);
            _active = null;
            return true;
        }

        internal void DeferActive()
        {
            if (_active == null) return;
            _pending.AddFirst(_active);
            _active = null;
        }

        internal void CancelPending(string key)
        {
            if (key == null) return;
            LinkedListNode<Entry> node = _pending.First;
            while (node != null)
            {
                LinkedListNode<Entry> next = node.Next;
                if (string.Equals(node.Value.Key, key, StringComparison.Ordinal))
                {
                    _pending.Remove(node);
                    _keys.Remove(key);
                }
                node = next;
            }
        }

        internal void Clear()
        {
            _pending.Clear();
            _keys.Clear();
            _active = null;
        }
    }
}
