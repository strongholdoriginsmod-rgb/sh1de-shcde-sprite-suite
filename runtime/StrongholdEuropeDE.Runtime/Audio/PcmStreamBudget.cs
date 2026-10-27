using System;
using System.Collections.Generic;
using System.Threading;

namespace StrongholdEuropeDE.Runtime.Audio
{
    internal struct PcmStreamBudgetSnapshot
    {
        internal PcmStreamBudgetSnapshot(int activeStreams, long bufferBytes, long generation)
            : this()
        {
            ActiveStreams = activeStreams;
            BufferBytes = bufferBytes;
            Generation = generation;
        }

        internal int ActiveStreams { get; private set; }

        internal long BufferBytes { get; private set; }

        internal long Generation { get; private set; }
    }

    internal sealed class PcmStreamBudgetReservation : IDisposable
    {
        private PcmStreamBudgetLedger _owner;
        private readonly long _bytes;
        private int _released;

        internal PcmStreamBudgetReservation(PcmStreamBudgetLedger owner, long bytes)
        {
            _owner = owner;
            _bytes = bytes;
        }

        internal long Bytes
        {
            get { return _bytes; }
        }

        public void Dispose()
        {
            if (Interlocked.Exchange(ref _released, 1) != 0)
            {
                return;
            }
            PcmStreamBudgetLedger owner = Interlocked.Exchange(ref _owner, null);
            if (owner != null)
            {
                owner.Release(_bytes);
            }
        }
    }

    /// <summary>
    /// Counts every managed per-stream PCM byte buffer before it is allocated.
    /// The production instance is fixed at two streams and sixteen MiB.
    /// </summary>
    internal sealed class PcmStreamBudgetLedger
    {
        private readonly object _gate = new object();
        private readonly int _maximumActiveStreams;
        private readonly long _maximumBufferBytes;
        private int _activeStreams;
        private long _bufferBytes;
        private long _generation = 1;

        internal PcmStreamBudgetLedger(int maximumActiveStreams, long maximumBufferBytes)
        {
            if (maximumActiveStreams <= 0
                || maximumActiveStreams > PcmStreamingLimits.MaximumActiveStreams)
            {
                throw new ArgumentOutOfRangeException("maximumActiveStreams");
            }
            if (maximumBufferBytes <= 0
                || maximumBufferBytes > PcmStreamingLimits.MaximumBufferBytes)
            {
                throw new ArgumentOutOfRangeException("maximumBufferBytes");
            }
            _maximumActiveStreams = maximumActiveStreams;
            _maximumBufferBytes = maximumBufferBytes;
        }

        internal bool CanReserve(long bufferBytes)
        {
            lock (_gate)
            {
                return CanReserveLocked(bufferBytes);
            }
        }

        internal bool TryReserve(
            long bufferBytes,
            out PcmStreamBudgetReservation reservation)
        {
            reservation = null;
            lock (_gate)
            {
                if (!CanReserveLocked(bufferBytes))
                {
                    return false;
                }
                _activeStreams++;
                _bufferBytes = checked(_bufferBytes + bufferBytes);
                AdvanceGenerationLocked();
                reservation = new PcmStreamBudgetReservation(this, bufferBytes);
                return true;
            }
        }

        internal PcmStreamBudgetSnapshot Snapshot()
        {
            lock (_gate)
            {
                return new PcmStreamBudgetSnapshot(
                    _activeStreams,
                    _bufferBytes,
                    _generation);
            }
        }

        private bool CanReserveLocked(long bufferBytes)
        {
            return bufferBytes > 0
                && bufferBytes <= _maximumBufferBytes
                && _activeStreams < _maximumActiveStreams
                && _bufferBytes <= _maximumBufferBytes - bufferBytes;
        }

        internal void Release(long bufferBytes)
        {
            lock (_gate)
            {
                if (_activeStreams <= 0
                    || bufferBytes <= 0
                    || bufferBytes > _bufferBytes)
                {
                    return;
                }
                _activeStreams--;
                _bufferBytes -= bufferBytes;
                AdvanceGenerationLocked();
            }
        }

        private void AdvanceGenerationLocked()
        {
            _generation = _generation == long.MaxValue ? 1 : _generation + 1;
        }
    }

    /// <summary>
    /// Permanent decode/I/O failures never retry. Budget refusal is sticky only
    /// while the ledger generation is unchanged, so one request cannot spin in
    /// a frame but may be reconsidered after another stream closes.
    /// </summary>
    internal sealed class PcmStreamFailureRegistry
    {
        private readonly object _gate = new object();
        private readonly HashSet<string> _permanent =
            new HashSet<string>(StringComparer.Ordinal);
        private readonly Dictionary<string, long> _budgetGeneration =
            new Dictionary<string, long>(StringComparer.Ordinal);

        internal bool MarkPermanent(string request)
        {
            lock (_gate)
            {
                _budgetGeneration.Remove(request);
                return _permanent.Add(request);
            }
        }

        internal bool IsPermanent(string request)
        {
            lock (_gate)
            {
                return _permanent.Contains(request);
            }
        }

        internal void MarkBudgetDenied(string request, long generation)
        {
            lock (_gate)
            {
                if (!_permanent.Contains(request))
                {
                    _budgetGeneration[request] = generation;
                }
            }
        }

        internal bool IsBudgetDenied(string request, long currentGeneration)
        {
            lock (_gate)
            {
                long deniedGeneration;
                return _budgetGeneration.TryGetValue(request, out deniedGeneration)
                    && deniedGeneration == currentGeneration;
            }
        }
    }
}
