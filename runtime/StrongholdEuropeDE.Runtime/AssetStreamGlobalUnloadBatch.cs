using System;
using System.Collections.Generic;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Dependency-free coordinator for one process-global unused-assets scan.
    /// Participants queued before a scan starts share that scan; participants
    /// arriving while it is in flight form the next batch.
    /// </summary>
    internal sealed class AssetStreamGlobalUnloadBatch<T>
        where T : class
    {
        private readonly object _gate = new object();
        private readonly List<T> _waiting = new List<T>();
        private readonly List<T> _active = new List<T>();
        private bool _inFlight;

        internal bool Enqueue(T participant)
        {
            if (participant == null)
            {
                throw new ArgumentNullException("participant");
            }
            lock (_gate)
            {
                if (ContainsReference(_waiting, participant)
                    || ContainsReference(_active, participant))
                {
                    return false;
                }
                _waiting.Add(participant);
                return true;
            }
        }

        internal bool TryBegin(out IList<T> participants)
        {
            lock (_gate)
            {
                if (_inFlight || _waiting.Count == 0)
                {
                    participants = null;
                    return false;
                }
                _active.AddRange(_waiting);
                _waiting.Clear();
                _inFlight = true;
                participants = new List<T>(_active);
                return true;
            }
        }

        internal IList<T> Complete()
        {
            lock (_gate)
            {
                if (!_inFlight)
                {
                    throw new InvalidOperationException(
                        "No global unused-assets batch is in flight");
                }
                var completed = new List<T>(_active);
                _active.Clear();
                _inFlight = false;
                return completed;
            }
        }

        internal void AbortStart()
        {
            lock (_gate)
            {
                if (!_inFlight)
                {
                    return;
                }
                // Preserve original FIFO order when the Unity call itself
                // throws or returns no operation. Ownership remains retained
                // and a later LateUpdate can retry the same batch.
                _waiting.InsertRange(0, _active);
                _active.Clear();
                _inFlight = false;
            }
        }

        internal bool HasPending
        {
            get
            {
                lock (_gate)
                {
                    return _inFlight || _waiting.Count != 0;
                }
            }
        }

        internal int WaitingCount
        {
            get { lock (_gate) { return _waiting.Count; } }
        }

        internal int ActiveCount
        {
            get { lock (_gate) { return _active.Count; } }
        }

        private static bool ContainsReference(IList<T> values, T candidate)
        {
            for (int index = 0; index < values.Count; index++)
            {
                if (ReferenceEquals(values[index], candidate))
                {
                    return true;
                }
            }
            return false;
        }
    }

    internal interface IAssetStreamGlobalUnloadParticipant
    {
        bool GlobalUnloadCompleted { get; set; }
    }
}
