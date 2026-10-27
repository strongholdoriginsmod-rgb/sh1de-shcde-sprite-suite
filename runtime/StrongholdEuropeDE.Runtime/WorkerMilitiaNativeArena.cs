using System;
using System.Globalization;
using System.Runtime.InteropServices;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// One private executable page near CrusaderDE.dll for the militia's
    /// relocated census table, its command-target trampoline and the hunter
    /// move-state cave.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Why not the padding behind .text any more: 2.7 left 708 bytes there,
    /// 2.80 leaves 144 (0x209F6C..0x20A000), and the militia needs 240. Both
    /// DLLs contain no int3 run of 112 bytes or more (measured 2026-09-28).
    /// A private page also cannot collide with another mod using the same
    /// padding.
    /// </para>
    /// <para>
    /// Placement: the first free 64 KiB granule above the mapped image whose
    /// page lies below ImageBase+0x7FFF0000. The census lookup addresses the
    /// table as [ImageBase + rax + disp32] with a sign-extended disp32, and
    /// the hooks jump there with rel32, so both limits are met by that window.
    /// </para>
    /// <para>
    /// Lifetime: allocated once per process, never freed. A patch is reverted
    /// by restoring the original engine bytes; a thread that had already
    /// entered the cave still returns through valid code. Freeing the page
    /// could turn such a late return into an access violation.
    /// </para>
    /// <para>
    /// Layout (offsets into the page): 0x000 census table (83 bytes, reserve
    /// 96) followed by the 26-byte command-target trampoline; 0x080 hunter
    /// move-state cave (112 bytes). Everything else stays zero.
    /// </para>
    /// </remarks>
    internal static class WorkerMilitiaNativeArena
    {
        internal const int CommandClassOffset = 0x000;
        internal const int CommandClassLength = 0x080;
        internal const int HunterMoveStateOffset = 0x080;
        internal const int HunterMoveStateLength = 0x070;
        private const int PageSize = 0x1000;
        private const long Granularity = 0x10000;
        private const long MaximumRvaEnd = 0x7FFF0000;

        private const int DosHeaderLfaNewOffset = 0x3C;
        private const uint PeSignature = 0x00004550;
        private const int OptionalHeaderOffset = 24;
        private const int OptionalHeaderSizeOfImageOffset = 56;

        private const uint MemReserve = 0x2000;
        private const uint MemCommit = 0x1000;
        private const uint MemFree = 0x10000;
        private const uint PageExecuteRead = 0x20;
        private const uint PageReadWrite = 0x04;

        private static readonly object Gate = new object();
        private static long _moduleBase;
        private static long _pageAddress;

        /// <summary>
        /// RVA (relative to <paramref name="moduleBase"/>) of the requested
        /// slice of the arena, allocating the page on first use.
        /// </summary>
        internal static bool TryGetSliceRva(
            IntPtr moduleBase,
            int offset,
            int length,
            out int rva,
            out string reason)
        {
            rva = 0;
            reason = null;
            if (moduleBase == IntPtr.Zero)
            {
                reason = "native module base is unavailable";
                return false;
            }
            if (offset < 0 || length <= 0 || offset + length > PageSize)
            {
                reason = "arena slice is outside the page";
                return false;
            }
            lock (Gate)
            {
                long module = moduleBase.ToInt64();
                if (_pageAddress != 0 && _moduleBase != module)
                {
                    reason = "arena belongs to a different module mapping";
                    return false;
                }
                if (_pageAddress == 0 && !TryAllocate(module, out reason))
                {
                    return false;
                }
                rva = checked((int)(_pageAddress - module + offset));
                return true;
            }
        }

        internal static string Describe()
        {
            lock (Gate)
            {
                return _pageAddress == 0
                    ? "unallocated"
                    : "rva=0x" + (_pageAddress - _moduleBase).ToString(
                        "X", CultureInfo.InvariantCulture);
            }
        }

        private static bool TryAllocate(long module, out string reason)
        {
            reason = null;
            int lfaNew = Marshal.ReadInt32(new IntPtr(module + DosHeaderLfaNewOffset));
            if (lfaNew <= 0 || lfaNew > 0x1000
                || unchecked((uint)Marshal.ReadInt32(new IntPtr(module + lfaNew)))
                    != PeSignature)
            {
                reason = "mapped image carries no PE header";
                return false;
            }
            long sizeOfImage = unchecked((uint)Marshal.ReadInt32(new IntPtr(
                module + lfaNew + OptionalHeaderOffset
                + OptionalHeaderSizeOfImageOffset)));
            if (sizeOfImage <= 0 || sizeOfImage > 0x40000000)
            {
                reason = "SizeOfImage is implausible";
                return false;
            }
            long candidate = ((module + sizeOfImage + Granularity - 1) / Granularity)
                * Granularity;
            long limit = module + MaximumRvaEnd - PageSize;
            var info = new MemoryBasicInformation();
            int infoSize = Marshal.SizeOf(typeof(MemoryBasicInformation));
            while (candidate <= limit)
            {
                if (VirtualQuery(new IntPtr(candidate), out info, new UIntPtr((uint)infoSize))
                        == UIntPtr.Zero)
                {
                    break;
                }
                long regionEnd = info.BaseAddress.ToInt64() + (long)info.RegionSize.ToUInt64();
                if (info.State == MemFree)
                {
                    IntPtr page = VirtualAlloc(
                        new IntPtr(candidate),
                        new UIntPtr(PageSize),
                        MemReserve | MemCommit,
                        PageReadWrite);
                    if (page != IntPtr.Zero && page.ToInt64() == candidate)
                    {
                        uint previous;
                        if (!VirtualProtect(page, new UIntPtr(PageSize), PageExecuteRead, out previous))
                        {
                            // Stays allocated (never freed by design) but unused.
                            reason = "arena page could not be made executable";
                            return false;
                        }
                        _moduleBase = module;
                        _pageAddress = candidate;
                        return true;
                    }
                }
                long next = ((regionEnd + Granularity - 1) / Granularity) * Granularity;
                candidate = next > candidate ? next : candidate + Granularity;
            }
            reason = "no free page within 2 GiB above the engine image";
            return false;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct MemoryBasicInformation
        {
            internal IntPtr BaseAddress;
            internal IntPtr AllocationBase;
            internal uint AllocationProtect;
            internal UIntPtr RegionSize;
            internal uint State;
            internal uint Protect;
            internal uint Type;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr VirtualAlloc(
            IntPtr address,
            UIntPtr size,
            uint allocationType,
            uint protect);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool VirtualProtect(
            IntPtr address,
            UIntPtr size,
            uint newProtect,
            out uint oldProtect);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern UIntPtr VirtualQuery(
            IntPtr address,
            out MemoryBasicInformation buffer,
            UIntPtr length);
    }
}
