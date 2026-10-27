using System;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Exact v2 transient model for opening one verified BC7 AssetBundle and
    /// retaining its single Texture2D. No decoded RGBA surface is admitted.
    /// </summary>
    internal static class UiTextureTransientAdmission
    {
        internal const long AlignmentBytes = 4L * 1024L * 1024L;
        internal const long FixedOverheadBytes = 64L * 1024L * 1024L;
        internal const long MaximumTransientPeakBytes =
            2L * 1024L * 1024L * 1024L;
        // Must track the GM resource policy's process_private_ceiling_bytes,
        // currently windows_24gb_igpu_bc7_12gib_process_private_v5. V3 shipped
        // 16 GiB here and in the GM policy; V4 corrected the GM side only,
        // which left this lane admitting long after the GM lane had started
        // denying. Change both together or the drift returns.
        internal const long ProcessPrivateCeilingBytes =
            12L * 1024L * 1024L * 1024L;
        internal const long GlobalCommitReserveBytes =
            4L * 1024L * 1024L * 1024L;
        internal const long MinimumFreePhysicalBytes =
            256L * 1024L * 1024L;

        internal static bool TryCalculatePeakBytes(
            long gpuBytes,
            long bundleBytes,
            out long peakBytes)
        {
            peakBytes = 0;
            if (gpuBytes < 1 || bundleBytes < 1)
            {
                return false;
            }
            try
            {
                long raw = checked(
                    checked(2L * gpuBytes)
                    + bundleBytes
                    + FixedOverheadBytes);
                peakBytes = AlignUp(raw);
                return peakBytes > 0
                    && peakBytes <= MaximumTransientPeakBytes;
            }
            catch (OverflowException)
            {
                peakBytes = 0;
                return false;
            }
        }

        internal static bool TryAdmit(
            long peakBytes,
            long? processPrivateBytes,
            long? globalAvailableCommitBytes,
            long? availablePhysicalBytes,
            out string failure)
        {
            failure = null;
            if (peakBytes < 1 || peakBytes > MaximumTransientPeakBytes)
            {
                failure = "transient peak is outside the 2 GiB v2 limit";
                return false;
            }
            if (!processPrivateBytes.HasValue
                || !globalAvailableCommitBytes.HasValue
                || !availablePhysicalBytes.HasValue)
            {
                failure = "required Windows memory metric is unavailable";
                return false;
            }
            long privateBytes = processPrivateBytes.Value;
            long commitBytes = globalAvailableCommitBytes.Value;
            long physicalBytes = availablePhysicalBytes.Value;
            if (privateBytes < 0 || commitBytes < 0 || physicalBytes < 0)
            {
                failure = "required Windows memory metric is negative";
                return false;
            }
            if (privateBytes > ProcessPrivateCeilingBytes - peakBytes)
            {
                failure = "process private ceiling of "
                    + (ProcessPrivateCeilingBytes / (1024L * 1024L * 1024L))
                        .ToString(System.Globalization.CultureInfo.InvariantCulture)
                    + " GiB would be exceeded";
                return false;
            }
            if (commitBytes < GlobalCommitReserveBytes + peakBytes)
            {
                failure = "global commit reserve of "
                    + (GlobalCommitReserveBytes / (1024L * 1024L * 1024L))
                        .ToString(System.Globalization.CultureInfo.InvariantCulture)
                    + " GiB would be crossed";
                return false;
            }
            if (physicalBytes < MinimumFreePhysicalBytes)
            {
                failure = "256 MiB absolute free physical floor would be crossed";
                return false;
            }
            return true;
        }

        private static long AlignUp(long value)
        {
            long quotient = value / AlignmentBytes;
            if (value % AlignmentBytes != 0)
            {
                quotient = checked(quotient + 1L);
            }
            return checked(quotient * AlignmentBytes);
        }
    }

    internal sealed class UiTextureBudgetSnapshot
    {
        internal UiTextureBudgetSnapshot(
            long maximumBytes,
            long reservedBytes,
            long committedBytes,
            int committedTextureCount)
        {
            MaximumBytes = maximumBytes;
            ReservedBytes = reservedBytes;
            CommittedBytes = committedBytes;
            CommittedTextureCount = committedTextureCount;
        }

        internal long MaximumBytes { get; private set; }
        internal long ReservedBytes { get; private set; }
        internal long CommittedBytes { get; private set; }
        internal int CommittedTextureCount { get; private set; }
    }

    /// <summary>
    /// Process-lifetime accounting for the conservative BC7 residency charge
    /// emitted by the builder. Successful charges intentionally have no
    /// release API because native Noesis references are not observable here.
    /// </summary>
    internal sealed class UiTextureBudgetLedger
    {
        internal const long MaximumProcessResidentBytes =
            1024L * 1024L * 1024L;

        private static readonly UiTextureBudgetLedger ProcessLedgerValue =
            new UiTextureBudgetLedger(MaximumProcessResidentBytes);

        private readonly object _gate = new object();
        private readonly long _maximumBytes;
        private long _reservedBytes;
        private long _committedBytes;
        private int _committedTextureCount;
        private long _nextReservationId;

        internal UiTextureBudgetLedger(long maximumBytes)
        {
            if (maximumBytes < 1
                || maximumBytes > MaximumProcessResidentBytes)
            {
                throw new ArgumentOutOfRangeException("maximumBytes");
            }
            _maximumBytes = maximumBytes;
        }

        internal static UiTextureBudgetLedger Process
        {
            get { return ProcessLedgerValue; }
        }

        internal bool TryReserve(
            long expectedResidentBytes,
            out UiTextureBudgetReservation reservation,
            out string failure)
        {
            reservation = null;
            failure = null;
            if (expectedResidentBytes < 1
                || expectedResidentBytes > MaximumProcessResidentBytes)
            {
                failure = "requested resident bytes are outside the process limit";
                return false;
            }
            lock (_gate)
            {
                if (_nextReservationId == long.MaxValue)
                {
                    failure = "UI texture reservation id space is exhausted";
                    return false;
                }
                long occupied;
                if (!TryAdd(_committedBytes, _reservedBytes, out occupied)
                    || !Fits(occupied, expectedResidentBytes, _maximumBytes))
                {
                    failure = "1 GiB process UI BC7 budget would be exceeded";
                    return false;
                }
                long id = _nextReservationId + 1L;
                var created = new UiTextureBudgetReservation(
                    this,
                    id,
                    expectedResidentBytes);
                _reservedBytes = checked(_reservedBytes + expectedResidentBytes);
                _nextReservationId = id;
                reservation = created;
                return true;
            }
        }

        internal UiTextureBudgetSnapshot Snapshot()
        {
            lock (_gate)
            {
                return new UiTextureBudgetSnapshot(
                    _maximumBytes,
                    _reservedBytes,
                    _committedBytes,
                    _committedTextureCount);
            }
        }

        internal void Commit(UiTextureBudgetReservation reservation)
        {
            lock (_gate)
            {
                RequireActiveReservation(reservation);
                _reservedBytes = checked(_reservedBytes - reservation.Bytes);
                _committedBytes = checked(
                    _committedBytes + reservation.Bytes);
                _committedTextureCount = checked(_committedTextureCount + 1);
                reservation.State = UiTextureBudgetReservationState.Committed;
            }
        }

        internal void Cancel(UiTextureBudgetReservation reservation)
        {
            lock (_gate)
            {
                if (reservation == null
                    || !ReferenceEquals(reservation.Ledger, this))
                {
                    throw new ArgumentException(
                        "Reservation belongs to a different UI texture ledger",
                        "reservation");
                }
                if (reservation.State == UiTextureBudgetReservationState.Canceled)
                {
                    return;
                }
                if (reservation.State == UiTextureBudgetReservationState.Committed)
                {
                    throw new InvalidOperationException(
                        "Committed process-lifetime UI texture bytes cannot be released");
                }
                _reservedBytes = checked(_reservedBytes - reservation.Bytes);
                reservation.State = UiTextureBudgetReservationState.Canceled;
            }
        }

        private void RequireActiveReservation(
            UiTextureBudgetReservation reservation)
        {
            if (reservation == null
                || !ReferenceEquals(reservation.Ledger, this)
                || reservation.Id < 1
                || reservation.State != UiTextureBudgetReservationState.Active)
            {
                throw new InvalidOperationException(
                    "UI texture budget reservation is not active in this ledger");
            }
        }

        private static bool TryAdd(long left, long right, out long result)
        {
            result = 0;
            if (left < 0 || right < 0 || left > long.MaxValue - right)
            {
                return false;
            }
            result = left + right;
            return true;
        }

        private static bool Fits(long occupied, long requested, long maximum)
        {
            return occupied >= 0
                && requested >= 0
                && occupied <= maximum
                && requested <= maximum - occupied;
        }
    }

    internal enum UiTextureBudgetReservationState
    {
        Active = 0,
        Committed = 1,
        Canceled = 2,
    }

    internal sealed class UiTextureBudgetReservation : IDisposable
    {
        internal UiTextureBudgetReservation(
            UiTextureBudgetLedger ledger,
            long id,
            long bytes)
        {
            Ledger = ledger;
            Id = id;
            Bytes = bytes;
            State = UiTextureBudgetReservationState.Active;
        }

        internal UiTextureBudgetLedger Ledger { get; private set; }
        internal long Id { get; private set; }
        internal long Bytes { get; private set; }
        internal UiTextureBudgetReservationState State { get; set; }

        internal void Commit()
        {
            Ledger.Commit(this);
        }

        internal void Cancel()
        {
            Ledger.Cancel(this);
        }

        public void Dispose()
        {
            if (State == UiTextureBudgetReservationState.Active)
            {
                Ledger.Cancel(this);
            }
        }
    }
}
