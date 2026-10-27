using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Lock-free, epoch-tagged handoff used by sprite getter prefixes. A worker
    /// performs only bounded managed-memory operations: an admission counter,
    /// one epoch-slot CAS and, for the first request of a GM in an epoch, one
    /// ConcurrentQueue enqueue.
    /// </summary>
    internal sealed class AssetStreamOffMainRequestQueue
    {
        private readonly long[] _queuedEpochs;
        private readonly ConcurrentQueue<Request> _requests =
            new ConcurrentQueue<Request>();
        private long _acceptingEpoch;
        private int _inFlightEnqueues;

#if ASSET_STREAM_HARNESS
        internal Action AfterAdmissionForTest { get; set; }
#endif

        internal AssetStreamOffMainRequestQueue(int gmCapacity)
        {
            if (gmCapacity < 1)
            {
                throw new ArgumentOutOfRangeException("gmCapacity");
            }
            _queuedEpochs = new long[gmCapacity];
        }

        internal void OpenEpoch(long epoch)
        {
            if (epoch <= 0)
            {
                throw new ArgumentOutOfRangeException("epoch");
            }
            long previous = Interlocked.CompareExchange(
                ref _acceptingEpoch,
                epoch,
                0);
            if (previous != 0)
            {
                throw new InvalidOperationException(
                    "An off-main request epoch is already open");
            }
        }

        internal bool TryEnqueue(int gm, long epoch)
        {
            if (gm < 0 || gm >= _queuedEpochs.Length || epoch <= 0)
            {
                return false;
            }
            if (Volatile.Read(ref _acceptingEpoch) != epoch)
            {
                return false;
            }
            Interlocked.Increment(ref _inFlightEnqueues);
            try
            {
                // The epoch closer first stops admission, then waits for every
                // writer that passed this second check. Consequently an
                // accepted CAS is either in its returned drain or was already
                // dequeued by the main pump; it cannot disappear between maps.
                if (Volatile.Read(ref _acceptingEpoch) != epoch)
                {
                    return false;
                }
#if ASSET_STREAM_HARNESS
                Action barrier = AfterAdmissionForTest;
                if (barrier != null)
                {
                    barrier();
                }
#endif
                while (true)
                {
                    long observed = Volatile.Read(ref _queuedEpochs[gm]);
                    // Epochs are strictly increasing. A delayed getter from an
                    // old map must not move this slot backwards: doing so would
                    // let a later getter enqueue the current epoch twice.
                    if (observed >= epoch)
                    {
                        return false;
                    }
                    if (Interlocked.CompareExchange(
                            ref _queuedEpochs[gm],
                            epoch,
                            observed) == observed)
                    {
                        _requests.Enqueue(new Request(gm, epoch));
                        return true;
                    }
                }
            }
            finally
            {
                Interlocked.Decrement(ref _inFlightEnqueues);
            }
        }

        internal IList<int> CloseEpochAndDrain(long epoch)
        {
            if (epoch <= 0)
            {
                throw new ArgumentOutOfRangeException("epoch");
            }
            long previous = Interlocked.CompareExchange(
                ref _acceptingEpoch,
                0,
                epoch);
            if (previous != epoch)
            {
                return new int[0];
            }
            var spin = new SpinWait();
            while (Volatile.Read(ref _inFlightEnqueues) != 0)
            {
                spin.SpinOnce();
            }
            var accepted = new List<int>();
            Request request;
            while (_requests.TryDequeue(out request))
            {
                if (request.Epoch == epoch)
                {
                    accepted.Add(request.Gm);
                }
                else if (request.Epoch > epoch)
                {
                    throw new InvalidOperationException(
                        "A future off-main request crossed a closed epoch");
                }
                // Older requests are stale leftovers and are discarded while
                // no producer can append to this closed queue.
            }
            return accepted;
        }

        internal bool TryDequeue(long activeEpoch, out int gm)
        {
            gm = -1;
            Request request;
            while (_requests.TryDequeue(out request))
            {
                if (request.Epoch == activeEpoch)
                {
                    gm = request.Gm;
                    return true;
                }
            }
            return false;
        }

        internal int ApproximateCount
        {
            get { return _requests.Count; }
        }

        private struct Request
        {
            internal Request(int gm, long epoch)
            {
                Gm = gm;
                Epoch = epoch;
            }

            internal int Gm { get; private set; }

            internal long Epoch { get; private set; }
        }
    }
}
