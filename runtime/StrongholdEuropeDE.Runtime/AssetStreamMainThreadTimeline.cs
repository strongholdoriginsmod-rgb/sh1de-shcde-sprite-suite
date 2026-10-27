using System;
using System.Collections.Generic;
using System.Threading;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Serializes the cold getter-result handoff with epoch completion. A worker
    /// may run the controller's queue-only path, but it must publish the result
    /// while holding this timeline. The main thread holds the same timeline
    /// while draining results and closing an epoch, so a completed getter can
    /// neither mutate bookkeeping nor appear after that epoch's summary.
    /// </summary>
    internal sealed class AssetStreamMainThreadTimeline
    {
        private readonly object _gate = new object();
        private readonly Queue<AssetStreamEnsureResult> _results =
            new Queue<AssetStreamEnsureResult>();
        private readonly HashSet<EpochGroupKey> _queued =
            new HashSet<EpochGroupKey>();

        internal void Execute(Action action)
        {
            if (action == null)
            {
                throw new ArgumentNullException("action");
            }
            lock (_gate)
            {
                action();
            }
        }

        internal T Execute<T>(Func<T> action)
        {
            if (action == null)
            {
                throw new ArgumentNullException("action");
            }
            lock (_gate)
            {
                return action();
            }
        }

        /// <summary>
        /// Non-blocking probe used by the dependency-free barrier harness. It
        /// also documents that lifecycle completion may never overtake a worker
        /// that is between controller result and result publication.
        /// </summary>
        internal bool TryExecute(Action action)
        {
            if (action == null)
            {
                throw new ArgumentNullException("action");
            }
            if (!Monitor.TryEnter(_gate))
            {
                return false;
            }
            try
            {
                action();
                return true;
            }
            finally
            {
                Monitor.Exit(_gate);
            }
        }

        internal bool HasQueuedResultLocked(long epoch, string groupId)
        {
            RequireEntered();
            if (string.IsNullOrEmpty(groupId))
            {
                return false;
            }
            return _queued.Contains(new EpochGroupKey(epoch, groupId));
        }

        internal bool EnqueueResultLocked(AssetStreamEnsureResult result)
        {
            RequireEntered();
            if (string.IsNullOrEmpty(result.GroupId))
            {
                return false;
            }
            var key = new EpochGroupKey(result.Epoch, result.GroupId);
            if (!_queued.Add(key))
            {
                return false;
            }
            _results.Enqueue(result);
            return true;
        }

        internal bool TryPublishCurrentResultLocked(
            AssetStreamEnsureResult result,
            bool mapActive,
            long activeEpoch,
            Action<AssetStreamEnsureResult> publishFastState)
        {
            RequireEntered();
            if (!mapActive
                || result.Epoch != activeEpoch
                || string.IsNullOrEmpty(result.GroupId))
            {
                return false;
            }
            var key = new EpochGroupKey(result.Epoch, result.GroupId);
            if (_queued.Contains(key))
            {
                return false;
            }
            if (publishFastState != null)
            {
                publishFastState(result);
            }
            _queued.Add(key);
            _results.Enqueue(result);
            return true;
        }

        internal int DrainResultsLocked(Action<AssetStreamEnsureResult> consume)
        {
            RequireEntered();
            if (consume == null)
            {
                throw new ArgumentNullException("consume");
            }
            int drained = 0;
            while (_results.Count != 0)
            {
                AssetStreamEnsureResult result = _results.Dequeue();
                _queued.Remove(new EpochGroupKey(result.Epoch, result.GroupId));
                consume(result);
                drained++;
            }
            return drained;
        }

        internal int PendingResultCount
        {
            get
            {
                lock (_gate)
                {
                    return _results.Count;
                }
            }
        }

        internal void RequireEntered()
        {
            if (!Monitor.IsEntered(_gate))
            {
                throw new InvalidOperationException(
                    "Asset-stream result publication requires the epoch timeline");
            }
        }

        private struct EpochGroupKey : IEquatable<EpochGroupKey>
        {
            private readonly long _epoch;
            private readonly string _groupId;

            internal EpochGroupKey(long epoch, string groupId)
            {
                _epoch = epoch;
                _groupId = groupId;
            }

            public bool Equals(EpochGroupKey other)
            {
                return _epoch == other._epoch
                    && string.Equals(_groupId, other._groupId,
                        StringComparison.Ordinal);
            }

            public override bool Equals(object obj)
            {
                return obj is EpochGroupKey && Equals((EpochGroupKey)obj);
            }

            public override int GetHashCode()
            {
                unchecked
                {
                    return (_epoch.GetHashCode() * 397)
                        ^ StringComparer.Ordinal.GetHashCode(_groupId);
                }
            }
        }
    }

    /// <summary>
    /// Controller diagnostics are produced on both controller entry paths. This
    /// sink stores them without invoking the logger; the lane drains it only on
    /// the captured Unity main thread and at explicit timeline boundaries.
    /// </summary>
    internal sealed class AssetStreamQueuedEventSink : IAssetStreamEventSink
    {
        private readonly object _gate = new object();
        private readonly Queue<AssetStreamEvent> _events =
            new Queue<AssetStreamEvent>();
        private readonly IAssetStreamEventSink _downstream;

        internal AssetStreamQueuedEventSink(IAssetStreamEventSink downstream)
        {
            _downstream = downstream ?? NullAssetStreamEventSink.Instance;
        }

        public void Emit(AssetStreamEvent value)
        {
            if (value == null)
            {
                return;
            }
            lock (_gate)
            {
                _events.Enqueue(value);
            }
        }

        internal int Drain()
        {
            AssetStreamEvent[] batch;
            lock (_gate)
            {
                if (_events.Count == 0)
                {
                    return 0;
                }
                batch = _events.ToArray();
                _events.Clear();
            }
            for (int index = 0; index < batch.Length; index++)
            {
                try
                {
                    _downstream.Emit(batch[index]);
                }
                catch
                {
                    // Observability never participates in ownership transitions.
                }
            }
            return batch.Length;
        }

        internal int PendingCount
        {
            get
            {
                lock (_gate)
                {
                    return _events.Count;
                }
            }
        }
    }
}
