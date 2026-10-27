using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>The one production resource policy; values are not configurable.</summary>
    internal sealed class AssetStreamResourcePolicy
    {
        private AssetStreamResourcePolicy(
            string kind,
            long additionalGmResidentBytes,
            long uiResidentBytes,
            long audioStreamBytes,
            long processPrivateCeilingBytes,
            long globalCommitReserveBytes,
            long minimumFreePhysicalBytes,
            long peakAdmissionBytes)
        {
            Kind = kind;
            AdditionalGmResidentBytes = additionalGmResidentBytes;
            UiResidentBytes = uiResidentBytes;
            AudioStreamBytes = audioStreamBytes;
            ProcessPrivateCeilingBytes = processPrivateCeilingBytes;
            GlobalCommitReserveBytes = globalCommitReserveBytes;
            MinimumFreePhysicalBytes = minimumFreePhysicalBytes;
            PeakAdmissionBytes = peakAdmissionBytes;
        }

        internal string Kind { get; private set; }
        internal long AdditionalGmResidentBytes { get; private set; }
        internal long UiResidentBytes { get; private set; }
        internal long AudioStreamBytes { get; private set; }
        internal long ProcessPrivateCeilingBytes { get; private set; }
        internal long GlobalCommitReserveBytes { get; private set; }
        internal long MinimumFreePhysicalBytes { get; private set; }
        internal long PeakAdmissionBytes { get; private set; }

        internal static AssetStreamResourcePolicy Windows24GbIgpuSafeV1()
        {
            return new AssetStreamResourcePolicy(
                AssetStreamContract.ResourcePolicyKind,
                3L * 1024 * 1024 * 1024,
                1L * 1024 * 1024 * 1024,
                16L * 1024 * 1024,
                16L * 1024 * 1024 * 1024,
                8L * 1024 * 1024 * 1024,
                4L * 1024 * 1024 * 1024,
                2L * 1024 * 1024 * 1024);
        }

        internal static AssetStreamResourcePolicy Windows24GbIgpuBc7TwelveGibProcessPrivateV5()
        {
            return new AssetStreamResourcePolicy(
                AssetStreamBc7Contract.ResourcePolicyKind,
                3221225472L,
                1073741824L,
                16777216L,
                12884901888L,
                4294967296L,
                268435456L,
                2147483648L);
        }
    }

    internal static class AssetStreamAccounting
    {
        internal const long AlignmentBytes = 64L * 1024 * 1024;
        internal const long Bc7ResidentAlignmentBytes = 4L * 1024 * 1024;
        internal const long UploadFixedOverheadBytes = 256L * 1024 * 1024;

        internal static long AlignUp(long value)
        {
            if (value < 0) throw new ArgumentOutOfRangeException("value");
            if (value == 0) return 0;
            long quotient = value / AlignmentBytes;
            if (value % AlignmentBytes != 0) quotient = checked(quotient + 1);
            return checked(quotient * AlignmentBytes);
        }

        internal static long AlignUp(long value, long alignmentBytes)
        {
            if (value < 0) throw new ArgumentOutOfRangeException("value");
            if (alignmentBytes < 1)
                throw new ArgumentOutOfRangeException("alignmentBytes");
            if (value == 0) return 0;
            long quotient = value / alignmentBytes;
            if (value % alignmentBytes != 0)
            {
                quotient = checked(quotient + 1);
            }
            return checked(quotient * alignmentBytes);
        }

        internal static long CalculateResidentChargeBytes(long rawRgbaBytes)
        {
            if (rawRgbaBytes < 1) throw new ArgumentOutOfRangeException("rawRgbaBytes");
            long eighth = rawRgbaBytes / 8;
            if (rawRgbaBytes % 8 != 0) eighth = checked(eighth + 1);
            return AlignUp(checked(rawRgbaBytes + eighth));
        }

        internal static long CalculateBc7ResidentChargeBytes(long gpuBytes)
        {
            if (gpuBytes < 1) throw new ArgumentOutOfRangeException("gpuBytes");
            long eighth = gpuBytes / 8;
            if (gpuBytes % 8 != 0) eighth = checked(eighth + 1);
            return AlignUp(
                checked(gpuBytes + eighth),
                Bc7ResidentAlignmentBytes);
        }

        internal static long CalculateTextureGpuBytes(
            int width,
            int height,
            int blockWidth,
            int blockHeight,
            int blockBytes)
        {
            if (width < 1) throw new ArgumentOutOfRangeException("width");
            if (height < 1) throw new ArgumentOutOfRangeException("height");
            if (blockWidth < 1) throw new ArgumentOutOfRangeException("blockWidth");
            if (blockHeight < 1) throw new ArgumentOutOfRangeException("blockHeight");
            if (blockBytes < 1) throw new ArgumentOutOfRangeException("blockBytes");
            long blocksWide = checked(((long)width + blockWidth - 1) / blockWidth);
            long blocksHigh = checked(((long)height + blockHeight - 1) / blockHeight);
            return checked(checked(blocksWide * blocksHigh) * blockBytes);
        }

        internal static long CalculatePeakAdmissionBytes(
            long residentChargeBytes,
            long bundleFileBytes)
        {
            if (residentChargeBytes < 1)
                throw new ArgumentOutOfRangeException("residentChargeBytes");
            if (bundleFileBytes < 1)
                throw new ArgumentOutOfRangeException("bundleFileBytes");
            return checked(
                checked(2 * residentChargeBytes)
                + AlignUp(bundleFileBytes)
                + UploadFixedOverheadBytes);
        }
    }

    internal sealed class AssetStreamMemorySnapshot
    {
        internal AssetStreamMemorySnapshot(
            long? processPrivateBytes,
            long? globalAvailableCommitBytes,
            long? availablePhysicalBytes,
            string detail)
        {
            ProcessPrivateBytes = PositiveOrNull(
                processPrivateBytes,
                "processPrivateBytes");
            GlobalAvailableCommitBytes = NonNegativeOrNull(
                globalAvailableCommitBytes,
                "globalAvailableCommitBytes");
            AvailablePhysicalBytes = NonNegativeOrNull(
                availablePhysicalBytes,
                "availablePhysicalBytes");
            Detail = AssetStreamText.Sanitize(detail, 256);
        }

        internal long? ProcessPrivateBytes { get; private set; }
        internal long? GlobalAvailableCommitBytes { get; private set; }
        internal long? AvailablePhysicalBytes { get; private set; }
        internal string Detail { get; private set; }

        internal static AssetStreamMemorySnapshot Unavailable(string detail)
        {
            return new AssetStreamMemorySnapshot(null, null, null, detail);
        }

        private static long? NonNegativeOrNull(long? value, string name)
        {
            if (value.HasValue && value.Value < 0)
                throw new ArgumentOutOfRangeException(name);
            return value;
        }

        private static long? PositiveOrNull(long? value, string name)
        {
            if (value.HasValue && value.Value <= 0)
                throw new ArgumentOutOfRangeException(name);
            return value;
        }
    }

    internal interface IAssetStreamMemoryProbe
    {
        AssetStreamMemorySnapshot Capture();
    }

    internal interface IWindowsAssetStreamMemoryApi
    {
        bool TryCapture(
            out ulong processPrivateUsage,
            out ulong availableCommitBytes,
            out ulong availablePhysicalBytes,
            out string detail);
    }

    internal sealed class WindowsAssetStreamMemoryProbe : IAssetStreamMemoryProbe
    {
        private readonly IWindowsAssetStreamMemoryApi memoryApi;

        internal WindowsAssetStreamMemoryProbe()
            : this(new WindowsAssetStreamMemoryApi())
        {
        }

        internal WindowsAssetStreamMemoryProbe(
            IWindowsAssetStreamMemoryApi memoryApiValue)
        {
            memoryApi = memoryApiValue
                ?? throw new ArgumentNullException("memoryApiValue");
        }

        public AssetStreamMemorySnapshot Capture()
        {
            try
            {
                ulong processPrivateUsage;
                ulong availableCommitBytes;
                ulong availablePhysicalBytes;
                string detail;
                if (!memoryApi.TryCapture(
                        out processPrivateUsage,
                        out availableCommitBytes,
                        out availablePhysicalBytes,
                        out detail))
                {
                    return AssetStreamMemorySnapshot.Unavailable(
                        string.IsNullOrEmpty(detail)
                            ? "native Windows memory query failed"
                            : detail);
                }

                long? processPrivate = PositiveUnsignedToSigned(
                    processPrivateUsage);
                long? availableCommit = UnsignedToSigned(availableCommitBytes);
                long? availablePhysical = UnsignedToSigned(
                    availablePhysicalBytes);
                if (!processPrivate.HasValue
                    || !availableCommit.HasValue
                    || !availablePhysical.HasValue)
                {
                    return AssetStreamMemorySnapshot.Unavailable(
                        "native Windows memory counters were zero or exceeded Int64");
                }
                return new AssetStreamMemorySnapshot(
                    processPrivate,
                    availableCommit,
                    availablePhysical,
                    string.Empty);
            }
            catch (Exception exception)
            {
                return AssetStreamMemorySnapshot.Unavailable(
                    exception.GetType().Name + ": " + exception.Message);
            }
        }

        private static long? PositiveUnsignedToSigned(ulong value)
        {
            return value == 0 || value > long.MaxValue
                ? (long?)null
                : checked((long)value);
        }

        private static long? UnsignedToSigned(ulong value)
        {
            return value > long.MaxValue ? (long?)null : checked((long)value);
        }
    }

    internal sealed class WindowsAssetStreamMemoryApi
        : IWindowsAssetStreamMemoryApi
    {
        internal const int ExpectedX64ProcessMemoryCountersExBytes = 80;
        internal const int ExpectedMemoryStatusExBytes = 64;

        internal static int ProcessMemoryCountersExSizeBytes
        {
            get
            {
                return Marshal.SizeOf(typeof(ProcessMemoryCountersEx));
            }
        }

        internal static int MemoryStatusExSizeBytes
        {
            get { return Marshal.SizeOf(typeof(MemoryStatusEx)); }
        }

        public bool TryCapture(
            out ulong processPrivateUsage,
            out ulong availableCommitBytes,
            out ulong availablePhysicalBytes,
            out string detail)
        {
            processPrivateUsage = 0;
            availableCommitBytes = 0;
            availablePhysicalBytes = 0;
            detail = string.Empty;
            if (IntPtr.Size != 8)
            {
                detail = "asset streaming requires a Windows x64 process";
                return false;
            }
            int processSize = ProcessMemoryCountersExSizeBytes;
            int statusSize = MemoryStatusExSizeBytes;
            if (processSize != ExpectedX64ProcessMemoryCountersExBytes
                || statusSize != ExpectedMemoryStatusExBytes)
            {
                detail = "native memory counter layout mismatch: process="
                    + processSize + " status=" + statusSize;
                return false;
            }

            var processCounters = new ProcessMemoryCountersEx();
            processCounters.Size = checked((uint)processSize);
            if (!GetProcessMemoryInfo(
                    GetCurrentProcess(),
                    ref processCounters,
                    processCounters.Size))
            {
                detail = "GetProcessMemoryInfo failed: "
                    + Marshal.GetLastWin32Error();
                return false;
            }

            var status = new MemoryStatusEx();
            status.Length = checked((uint)statusSize);
            if (!GlobalMemoryStatusEx(ref status))
            {
                detail = "GlobalMemoryStatusEx failed: "
                    + Marshal.GetLastWin32Error();
                return false;
            }

            processPrivateUsage = processCounters.PrivateUsage.ToUInt64();
            availableCommitBytes = checked(
                status.AvailablePageFile
                + PagefileGrowthHeadroomBytes(status));
            availablePhysicalBytes = status.AvailablePhysical;
            return true;
        }

        // Windows grows a pagefile that has an explicit maximum on demand, so
        // the commit a load can still obtain is AvailablePageFile plus the
        // growth the configured maximum still permits. Measured 2026-09-02 on
        // the 24 GiB target machine: 6.6 GiB free commit while idle, initial
        // pagefile 16 GiB with a 32 GiB maximum. Every 4 GiB reserve check
        // failed - 108 of 114 UI textures and all GM groups were refused -
        // although 15 GiB of guaranteed growth was still available. System
        // managed or unparsable entries contribute nothing, which keeps the
        // previous fail-closed behaviour for them.
        private static long _pagefileMaximumBytes = -1;

        private static ulong PagefileGrowthHeadroomBytes(MemoryStatusEx status)
        {
            long maximum = System.Threading.Volatile.Read(
                ref _pagefileMaximumBytes);
            if (maximum < 0)
            {
                maximum = ReadConfiguredPagefileMaximumBytes();
                System.Threading.Volatile.Write(
                    ref _pagefileMaximumBytes, maximum);
            }
            if (maximum <= 0 || status.TotalPageFile <= status.TotalPhysical)
            {
                return 0;
            }
            // The commit limit is physical memory plus the current pagefile
            // sizes; their difference is what the pagefiles occupy today.
            ulong current = status.TotalPageFile - status.TotalPhysical;
            ulong configured = (ulong)maximum;
            return configured > current ? configured - current : 0UL;
        }

        private static long ReadConfiguredPagefileMaximumBytes()
        {
            try
            {
                using (Microsoft.Win32.RegistryKey key =
                    Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                        @"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management",
                        false))
                {
                    if (key == null)
                    {
                        return 0;
                    }
                    object raw = key.GetValue("PagingFiles");
                    string[] entries = raw as string[];
                    if (entries == null)
                    {
                        string single = raw as string;
                        entries = single == null ? null : new[] { single };
                    }
                    if (entries == null)
                    {
                        return 0;
                    }
                    long total = 0;
                    foreach (string entry in entries)
                    {
                        // "C:\pagefile.sys 16384 32768" in MB. "?:\pagefile.sys"
                        // or "... 0 0" means system managed: unknown maximum.
                        if (string.IsNullOrEmpty(entry))
                        {
                            continue;
                        }
                        string[] parts = entry.Trim().Split(' ');
                        if (parts.Length < 3)
                        {
                            continue;
                        }
                        long maximumMb;
                        if (!long.TryParse(
                                parts[parts.Length - 1],
                                System.Globalization.NumberStyles.Integer,
                                System.Globalization.CultureInfo.InvariantCulture,
                                out maximumMb)
                            || maximumMb <= 0)
                        {
                            continue;
                        }
                        total = checked(total + maximumMb * 1024L * 1024L);
                    }
                    return total;
                }
            }
            catch (Exception)
            {
                return 0;
            }
        }

        [DllImport("kernel32.dll")]
        private static extern IntPtr GetCurrentProcess();

        [DllImport("psapi.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetProcessMemoryInfo(
            IntPtr process,
            ref ProcessMemoryCountersEx counters,
            uint size);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GlobalMemoryStatusEx(ref MemoryStatusEx buffer);

        [StructLayout(LayoutKind.Sequential)]
        private struct ProcessMemoryCountersEx
        {
            internal uint Size;
            internal uint PageFaultCount;
            internal UIntPtr PeakWorkingSetSize;
            internal UIntPtr WorkingSetSize;
            internal UIntPtr QuotaPeakPagedPoolUsage;
            internal UIntPtr QuotaPagedPoolUsage;
            internal UIntPtr QuotaPeakNonPagedPoolUsage;
            internal UIntPtr QuotaNonPagedPoolUsage;
            internal UIntPtr PagefileUsage;
            internal UIntPtr PeakPagefileUsage;
            internal UIntPtr PrivateUsage;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct MemoryStatusEx
        {
            internal uint Length;
            internal uint MemoryLoad;
            internal ulong TotalPhysical;
            internal ulong AvailablePhysical;
            internal ulong TotalPageFile;
            internal ulong AvailablePageFile;
            internal ulong TotalVirtual;
            internal ulong AvailableVirtual;
            internal ulong AvailableExtendedVirtual;
        }
    }

    internal sealed class AssetStreamExternalUsageSnapshot
    {
        internal AssetStreamExternalUsageSnapshot(
            long? uiResidentBytes,
            long? audioStreamBytes,
            string detail)
        {
            if (uiResidentBytes.HasValue && uiResidentBytes.Value < 0)
                throw new ArgumentOutOfRangeException("uiResidentBytes");
            if (audioStreamBytes.HasValue && audioStreamBytes.Value < 0)
                throw new ArgumentOutOfRangeException("audioStreamBytes");
            UiResidentBytes = uiResidentBytes;
            AudioStreamBytes = audioStreamBytes;
            Detail = AssetStreamText.Sanitize(detail, 256);
        }

        internal long? UiResidentBytes { get; private set; }
        internal long? AudioStreamBytes { get; private set; }
        internal string Detail { get; private set; }
    }

    /// <summary>
    /// Integration must explicitly account non-GM UI and streaming audio; a
    /// silent zero default is intentionally not provided.
    /// </summary>
    internal interface IAssetStreamExternalUsageProbe
    {
        AssetStreamExternalUsageSnapshot Capture();
    }

    internal enum AssetStreamAdmissionFailure
    {
        None = 0,
        LoadAlreadyInFlight = 1,
        UiBudgetExceeded = 2,
        AudioBudgetExceeded = 3,
        GmBudgetExceeded = 4,
        PeakBudgetExceeded = 5,
        MetricUnavailable = 6,
        ProcessPrivateCeiling = 7,
        GlobalCommitReserve = 8,
        MinimumFreePhysical = 9,
        AccountingMismatch = 10,
        ReservationStateInvalid = 11,
    }

    internal static class AssetStreamAdmissionReasonContract
    {
        internal static string ToToken(AssetStreamAdmissionFailure failure)
        {
            switch (failure)
            {
                case AssetStreamAdmissionFailure.None: return "admitted";
                case AssetStreamAdmissionFailure.LoadAlreadyInFlight:
                    return "load_already_in_flight";
                case AssetStreamAdmissionFailure.UiBudgetExceeded:
                    return "ui_budget_exceeded";
                case AssetStreamAdmissionFailure.AudioBudgetExceeded:
                    return "audio_budget_exceeded";
                case AssetStreamAdmissionFailure.GmBudgetExceeded:
                    return "gm_budget_exceeded";
                case AssetStreamAdmissionFailure.PeakBudgetExceeded:
                    return "peak_budget_exceeded";
                case AssetStreamAdmissionFailure.MetricUnavailable:
                    return "metric_unavailable";
                case AssetStreamAdmissionFailure.ProcessPrivateCeiling:
                    return "process_private_ceiling";
                case AssetStreamAdmissionFailure.GlobalCommitReserve:
                    return "global_commit_reserve";
                case AssetStreamAdmissionFailure.MinimumFreePhysical:
                    return "minimum_free_physical";
                case AssetStreamAdmissionFailure.AccountingMismatch:
                    return "accounting_mismatch";
                case AssetStreamAdmissionFailure.ReservationStateInvalid:
                    return "reservation_state_invalid";
                default:
                    throw new ArgumentOutOfRangeException("failure");
            }
        }
    }

    internal struct AssetStreamAdmissionDecision
    {
        internal AssetStreamAdmissionDecision(
            bool allowed,
            AssetStreamAdmissionFailure failure,
            long residentChargeBytes,
            long peakAdmissionBytes,
            string detail)
        {
            Allowed = allowed;
            Failure = failure;
            ResidentChargeBytes = residentChargeBytes;
            PeakAdmissionBytes = peakAdmissionBytes;
            Detail = AssetStreamText.Sanitize(detail, 256);
        }

        internal bool Allowed { get; private set; }
        internal AssetStreamAdmissionFailure Failure { get; private set; }
        internal string ReasonToken
        {
            get { return AssetStreamAdmissionReasonContract.ToToken(Failure); }
        }
        internal long ResidentChargeBytes { get; private set; }
        internal long PeakAdmissionBytes { get; private set; }
        internal string Detail { get; private set; }
    }

    internal sealed class AssetStreamBudgetSnapshot
    {
        internal AssetStreamBudgetSnapshot(
            long committedGmResidentBytes,
            bool loadInFlight,
            string inFlightGroup)
        {
            CommittedGmResidentBytes = committedGmResidentBytes;
            LoadInFlight = loadInFlight;
            InFlightGroup = inFlightGroup ?? string.Empty;
        }

        internal long CommittedGmResidentBytes { get; private set; }
        internal bool LoadInFlight { get; private set; }
        internal string InFlightGroup { get; private set; }
    }

    internal sealed class AssetStreamResourceTelemetry
    {
        internal AssetStreamResourceTelemetry(
            long committedGmBytes,
            long? uiBytes,
            long? audioBytes,
            long? privateBytes,
            long? availableCommitBytes,
            long? availablePhysicalBytes,
            string detail)
        {
            CommittedGmBytes = committedGmBytes;
            UiBytes = uiBytes;
            AudioBytes = audioBytes;
            PrivateBytes = privateBytes.HasValue && privateBytes.Value > 0
                ? privateBytes
                : null;
            AvailableCommitBytes = availableCommitBytes;
            AvailablePhysicalBytes = availablePhysicalBytes;
            Detail = AssetStreamText.Sanitize(detail, 256);
        }

        internal long CommittedGmBytes { get; private set; }
        internal long? UiBytes { get; private set; }
        internal long? AudioBytes { get; private set; }
        internal long? PrivateBytes { get; private set; }
        internal long? AvailableCommitBytes { get; private set; }
        internal long? AvailablePhysicalBytes { get; private set; }
        internal string Detail { get; private set; }

        internal bool Complete
        {
            get
            {
                return UiBytes.HasValue
                    && AudioBytes.HasValue
                    && PrivateBytes.HasValue
                    && PrivateBytes.Value > 0
                    && AvailableCommitBytes.HasValue
                    && AvailablePhysicalBytes.HasValue;
            }
        }
    }

    internal sealed class AssetStreamBudgetReservation
    {
        private readonly AssetStreamBudgetLedger owner;
        private readonly long sequence;

        internal AssetStreamBudgetReservation(
            AssetStreamBudgetLedger ownerValue,
            string groupId,
            long sequenceValue,
            long charge,
            long peak,
            AssetStreamResourceTelemetry preStageTelemetry)
        {
            owner = ownerValue;
            GroupId = groupId;
            sequence = sequenceValue;
            ResidentChargeBytes = charge;
            PeakAdmissionBytes = peak;
            PreStageTelemetry = preStageTelemetry;
        }

        internal string GroupId { get; private set; }
        internal long ResidentChargeBytes { get; private set; }
        internal long PeakAdmissionBytes { get; private set; }
        internal AssetStreamResourceTelemetry PreStageTelemetry { get; private set; }
        internal AssetStreamResourceTelemetry AfterStageTelemetry { get; private set; }

        internal void SetAfterStageTelemetry(AssetStreamResourceTelemetry value)
        {
            AfterStageTelemetry = value;
        }

        internal bool TryConfirmBeforeCommit(out AssetStreamAdmissionDecision decision)
        {
            return owner.TryConfirmBeforeCommit(this, sequence, out decision);
        }

        internal void Commit() { owner.Commit(this, sequence); }
        internal void Cancel() { owner.Cancel(this, sequence); }
        internal void Release() { owner.Release(this, sequence); }
        internal void RetainAsLeak() { owner.RetainAsLeak(this, sequence); }
    }

    /// <summary>
    /// Serial one-group ledger. Admission is performed before staging and must
    /// be confirmed using a fresh pair of probes after staging, before publish.
    /// </summary>
    internal sealed class AssetStreamBudgetLedger
    {
        private readonly object gate = new object();
        private readonly AssetStreamResourcePolicy policy;
        private readonly IAssetStreamMemoryProbe memoryProbe;
        private readonly IAssetStreamExternalUsageProbe usageProbe;
        private readonly Dictionary<string, Allocation> allocations =
            new Dictionary<string, Allocation>(StringComparer.Ordinal);
        private long committedGmBytes;
        private long sequence;
        private string inFlightGroup;

        internal AssetStreamBudgetLedger(
            AssetStreamResourcePolicy policyValue,
            IAssetStreamMemoryProbe memoryProbeValue,
            IAssetStreamExternalUsageProbe usageProbeValue)
        {
            policy = policyValue ?? throw new ArgumentNullException("policyValue");
            memoryProbe = memoryProbeValue ?? throw new ArgumentNullException("memoryProbeValue");
            usageProbe = usageProbeValue ?? throw new ArgumentNullException("usageProbeValue");
            if (!string.Equals(policy.Kind, AssetStreamContract.ResourcePolicyKind, StringComparison.Ordinal)
                && !string.Equals(
                    policy.Kind,
                    AssetStreamBc7Contract.ResourcePolicyKind,
                    StringComparison.Ordinal))
                throw new ArgumentException("Unsupported resource policy", "policyValue");
        }

        internal bool TryReserve(
            AssetStreamGroupManifest group,
            out AssetStreamBudgetReservation reservation,
            out AssetStreamAdmissionDecision decision)
        {
            if (group == null) throw new ArgumentNullException("group");
            reservation = null;
            lock (gate)
            {
                long charge;
                long peak;
                if (!TryExactAccounting(group, out charge, out peak, out decision))
                    return false;
                if (allocations.ContainsKey(group.Group))
                {
                    decision = Reject(
                        AssetStreamAdmissionFailure.ReservationStateInvalid,
                        charge, peak, "group already owns a budget allocation");
                    return false;
                }
                AssetStreamResourceTelemetry telemetry;
                decision = Decide(
                    charge,
                    peak,
                    inFlightGroup != null,
                    out telemetry);
                if (!decision.Allowed) return false;
                long next = checked(++sequence);
                allocations.Add(group.Group, new Allocation(next, charge, peak));
                inFlightGroup = group.Group;
                reservation = new AssetStreamBudgetReservation(
                    this, group.Group, next, charge, peak, telemetry);
                return true;
            }
        }

        internal AssetStreamBudgetSnapshot Snapshot()
        {
            lock (gate)
            {
                return new AssetStreamBudgetSnapshot(
                    committedGmBytes,
                    inFlightGroup != null,
                    inFlightGroup);
            }
        }

        internal AssetStreamResourceTelemetry CaptureTelemetry()
        {
            long committed;
            lock (gate)
            {
                committed = committedGmBytes;
            }
            AssetStreamExternalUsageSnapshot usage = null;
            AssetStreamMemorySnapshot memory = null;
            string detail = "captured";
            try
            {
                usage = usageProbe.Capture();
            }
            catch (Exception exception)
            {
                detail = "usage_probe_" + exception.GetType().Name;
            }
            try
            {
                memory = memoryProbe.Capture();
            }
            catch (Exception exception)
            {
                detail = detail == "captured"
                    ? "memory_probe_" + exception.GetType().Name
                    : detail + "+memory_probe_" + exception.GetType().Name;
            }
            return new AssetStreamResourceTelemetry(
                committed,
                usage == null ? null : usage.UiResidentBytes,
                usage == null ? null : usage.AudioStreamBytes,
                memory == null ? null : memory.ProcessPrivateBytes,
                memory == null ? null : memory.GlobalAvailableCommitBytes,
                memory == null ? null : memory.AvailablePhysicalBytes,
                detail);
        }

        internal bool TryConfirmBeforeCommit(
            AssetStreamBudgetReservation reservation,
            long expectedSequence,
            out AssetStreamAdmissionDecision decision)
        {
            lock (gate)
            {
                Allocation allocation = RequireAllocation(reservation, expectedSequence);
                if (allocation.State != AllocationState.Reserved
                    || !string.Equals(inFlightGroup, reservation.GroupId, StringComparison.Ordinal))
                {
                    decision = Reject(
                        AssetStreamAdmissionFailure.ReservationStateInvalid,
                        allocation.Charge, allocation.Peak,
                        "reservation is not awaiting its second admission");
                    return false;
                }
                // The active reservation is the candidate, not a competing load.
                AssetStreamResourceTelemetry telemetry;
                decision = Decide(
                    allocation.Charge,
                    allocation.Peak,
                    false,
                    out telemetry);
                reservation.SetAfterStageTelemetry(telemetry);
                if (!decision.Allowed) return false;
                allocation.State = AllocationState.Confirmed;
                return true;
            }
        }

        internal void Commit(AssetStreamBudgetReservation reservation, long expectedSequence)
        {
            lock (gate)
            {
                Allocation allocation = RequireAllocation(reservation, expectedSequence);
                if (allocation.State != AllocationState.Confirmed)
                    throw new InvalidOperationException(
                        "Budget commit requires the post-staging admission");
                committedGmBytes = checked(committedGmBytes + allocation.Charge);
                allocation.State = AllocationState.Committed;
                inFlightGroup = null;
            }
        }

        internal void Cancel(AssetStreamBudgetReservation reservation, long expectedSequence)
        {
            lock (gate)
            {
                Allocation allocation = RequireAllocation(reservation, expectedSequence);
                if (allocation.State == AllocationState.Committed
                    || allocation.State == AllocationState.Leaked)
                    throw new InvalidOperationException("Committed allocation cannot be cancelled");
                allocations.Remove(reservation.GroupId);
                if (string.Equals(inFlightGroup, reservation.GroupId, StringComparison.Ordinal))
                    inFlightGroup = null;
            }
        }

        internal void Release(AssetStreamBudgetReservation reservation, long expectedSequence)
        {
            lock (gate)
            {
                Allocation allocation = RequireAllocation(reservation, expectedSequence);
                if (allocation.State != AllocationState.Committed)
                    throw new InvalidOperationException("Only a committed allocation can be released");
                committedGmBytes = checked(committedGmBytes - allocation.Charge);
                allocations.Remove(reservation.GroupId);
            }
        }

        internal void RetainAsLeak(AssetStreamBudgetReservation reservation, long expectedSequence)
        {
            lock (gate)
            {
                Allocation allocation = RequireAllocation(reservation, expectedSequence);
                if (allocation.State == AllocationState.Committed
                    || allocation.State == AllocationState.Leaked)
                    return;
                committedGmBytes = checked(committedGmBytes + allocation.Charge);
                allocation.State = AllocationState.Leaked;
                if (string.Equals(inFlightGroup, reservation.GroupId, StringComparison.Ordinal))
                    inFlightGroup = null;
            }
        }

        private AssetStreamAdmissionDecision Decide(
            long charge,
            long peak,
            bool competingLoad,
            out AssetStreamResourceTelemetry telemetry)
        {
            AssetStreamExternalUsageSnapshot usage;
            telemetry = null;
            if (competingLoad)
                return Reject(AssetStreamAdmissionFailure.LoadAlreadyInFlight, charge, peak,
                    "another group load is already in flight");
            try { usage = usageProbe.Capture(); }
            catch (Exception exception)
            {
                return Reject(AssetStreamAdmissionFailure.MetricUnavailable, charge, peak,
                    "external usage probe failed: " + exception.GetType().Name);
            }
            if (usage == null || !usage.UiResidentBytes.HasValue
                || !usage.AudioStreamBytes.HasValue)
                return Reject(AssetStreamAdmissionFailure.MetricUnavailable, charge, peak,
                    usage == null ? "external usage probe returned null" : usage.Detail);
            if (usage.UiResidentBytes.Value > policy.UiResidentBytes)
                return Reject(AssetStreamAdmissionFailure.UiBudgetExceeded, charge, peak,
                    "UI resident budget exceeded");
            if (usage.AudioStreamBytes.Value > policy.AudioStreamBytes)
                return Reject(AssetStreamAdmissionFailure.AudioBudgetExceeded, charge, peak,
                    "audio stream budget exceeded");
            if (checked(committedGmBytes + charge) > policy.AdditionalGmResidentBytes)
                return Reject(AssetStreamAdmissionFailure.GmBudgetExceeded, charge, peak,
                    "additional GM resident budget exceeded");
            if (peak > policy.PeakAdmissionBytes)
                return Reject(AssetStreamAdmissionFailure.PeakBudgetExceeded, charge, peak,
                    "one-group peak budget exceeded");
            AssetStreamMemorySnapshot memory;
            try { memory = memoryProbe.Capture(); }
            catch (Exception exception)
            {
                return Reject(AssetStreamAdmissionFailure.MetricUnavailable, charge, peak,
                    "memory probe failed: " + exception.GetType().Name);
            }
            if (memory == null || !memory.ProcessPrivateBytes.HasValue
                || memory.ProcessPrivateBytes.Value <= 0
                || !memory.GlobalAvailableCommitBytes.HasValue
                || !memory.AvailablePhysicalBytes.HasValue)
                return Reject(AssetStreamAdmissionFailure.MetricUnavailable, charge, peak,
                    memory == null ? "memory probe returned null" : memory.Detail);
            telemetry = new AssetStreamResourceTelemetry(
                committedGmBytes,
                usage.UiResidentBytes,
                usage.AudioStreamBytes,
                memory.ProcessPrivateBytes,
                memory.GlobalAvailableCommitBytes,
                memory.AvailablePhysicalBytes,
                "admission probe captured");
            if (memory.ProcessPrivateBytes.Value
                > policy.ProcessPrivateCeilingBytes - peak)
                return Reject(AssetStreamAdmissionFailure.ProcessPrivateCeiling, charge, peak,
                    "process private ceiling would be exceeded");
            if (memory.GlobalAvailableCommitBytes.Value
                < checked(policy.GlobalCommitReserveBytes + peak))
                return Reject(AssetStreamAdmissionFailure.GlobalCommitReserve, charge, peak,
                    "global commit reserve would be crossed");
            bool commitFirstPhysicalFloor = string.Equals(
                policy.Kind,
                AssetStreamBc7Contract.ResourcePolicyKind,
                StringComparison.Ordinal);
            long requiredPhysicalBytes = commitFirstPhysicalFloor
                ? policy.MinimumFreePhysicalBytes
                : checked(policy.MinimumFreePhysicalBytes + peak);
            if (memory.AvailablePhysicalBytes.Value < requiredPhysicalBytes)
                return Reject(AssetStreamAdmissionFailure.MinimumFreePhysical, charge, peak,
                    "minimum free physical memory would be crossed");
            return new AssetStreamAdmissionDecision(
                true, AssetStreamAdmissionFailure.None, charge, peak, "admitted");
        }

        private bool TryExactAccounting(
            AssetStreamGroupManifest group,
            out long charge,
            out long peak,
            out AssetStreamAdmissionDecision decision)
        {
            try
            {
                string expectedPolicy = group.PipelineVersion
                    == AssetStreamPipelineVersion.Bc7VisualEquivalenceV2
                        ? AssetStreamBc7Contract.ResourcePolicyKind
                        : AssetStreamContract.ResourcePolicyKind;
                if (!string.Equals(policy.Kind, expectedPolicy, StringComparison.Ordinal))
                {
                    charge = 0;
                    peak = 0;
                    decision = Reject(
                        AssetStreamAdmissionFailure.AccountingMismatch,
                        0,
                        0,
                        "resource policy does not match manifest generation");
                    return false;
                }
                charge = group.PipelineVersion
                    == AssetStreamPipelineVersion.Bc7VisualEquivalenceV2
                        ? AssetStreamAccounting.CalculateBc7ResidentChargeBytes(
                            group.GpuBytes)
                        : AssetStreamAccounting.CalculateResidentChargeBytes(
                            group.RawRgbaBytes);
                peak = AssetStreamAccounting.CalculatePeakAdmissionBytes(
                    charge, group.BundleSizeBytes);
                if (charge != group.ResidentChargeBytes
                    || peak != group.PredictedLoadPeakBytes)
                {
                    decision = Reject(
                        AssetStreamAdmissionFailure.AccountingMismatch,
                        charge,
                        peak,
                        "index resident charge or predicted peak does not match exact accounting");
                    return false;
                }
                decision = new AssetStreamAdmissionDecision(
                    true, AssetStreamAdmissionFailure.None, charge, peak, "accounting verified");
                return true;
            }
            catch (OverflowException)
            {
                charge = 0;
                peak = 0;
                decision = Reject(
                    AssetStreamAdmissionFailure.AccountingMismatch,
                    0, 0, "signed 64-bit accounting overflow");
                return false;
            }
            catch (ArgumentOutOfRangeException)
            {
                charge = 0;
                peak = 0;
                decision = Reject(
                    AssetStreamAdmissionFailure.AccountingMismatch,
                    0, 0, "invalid raw or bundle byte count");
                return false;
            }
        }

        private Allocation RequireAllocation(
            AssetStreamBudgetReservation reservation,
            long expectedSequence)
        {
            if (reservation == null) throw new ArgumentNullException("reservation");
            Allocation allocation;
            if (!allocations.TryGetValue(reservation.GroupId, out allocation)
                || allocation.Sequence != expectedSequence)
                throw new InvalidOperationException("Budget reservation is stale");
            return allocation;
        }

        private static AssetStreamAdmissionDecision Reject(
            AssetStreamAdmissionFailure failure,
            long charge,
            long peak,
            string detail)
        {
            return new AssetStreamAdmissionDecision(false, failure, charge, peak, detail);
        }

        private enum AllocationState { Reserved = 0, Confirmed = 1, Committed = 2, Leaked = 3 }

        private sealed class Allocation
        {
            internal Allocation(long sequence, long charge, long peak)
            {
                Sequence = sequence;
                Charge = charge;
                Peak = peak;
                State = AllocationState.Reserved;
            }
            internal long Sequence { get; private set; }
            internal long Charge { get; private set; }
            internal long Peak { get; private set; }
            internal AllocationState State { get; set; }
        }
    }

    internal static class AssetStreamText
    {
        internal static string Sanitize(string value, int maximumLength)
        {
            if (string.IsNullOrEmpty(value)) return string.Empty;
            var characters = new char[Math.Min(value.Length, maximumLength)];
            int count = 0;
            for (int index = 0; index < value.Length && count < characters.Length; index++)
            {
                char character = value[index];
                characters[count++] = char.IsControl(character) ? ' ' : character;
            }
            return new string(characters, 0, count);
        }
    }
}
