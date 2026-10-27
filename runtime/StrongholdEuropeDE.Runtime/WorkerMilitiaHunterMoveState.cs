using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Threading;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Adds the missing soldier move state (0x65) to the native hunter FSM.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The native tribe ground-order executor at RVA 0x11A3C0 writes state
    /// 0x65 before it calls the per-unit path writer at 0x194FC0. Woodcutters
    /// implement that state at 0x12D4E4. Hunters do not: their final state
    /// comparison is 0x6E and every unknown state falls through 0x130253,
    /// which clears the state and the path context.
    /// </para>
    /// <para>
    /// This transaction replaces the final six-byte comparison with a jump to
    /// verified zero padding. The cave preserves the original 0x6E and default
    /// branches and handles only 0x65. While a path is active it writes the
    /// exact locomotion pair used by the hunter's own long-distance state-1
    /// branch: control 1 and speed 1. On arrival it performs the same state,
    /// timer and path cleanup used by native worker/soldier move states.
    /// No sprite row, material group or learned animation value is written.
    /// </para>
    /// <para>
    /// Both changed regions are identity-checked, written cave-first, read
    /// back, and restored hook-first. Apply and revert are restricted to the
    /// one EngineInterface.run thread recorded by the owner.
    /// </para>
    /// </remarks>
    internal sealed class WorkerMilitiaHunterMoveState
    {
        internal const int NativeMoveState = 0x65;

        private static int HunterUpdateRegisterSetupRva { get { return WorkerMilitiaNativeLayout.Current.HunterUpdateRegisterSetupRva; } }
        private static int HunterFinalStateDispatchRva { get { return WorkerMilitiaNativeLayout.Current.HunterFinalStateDispatchRva; } }
        private static int HunterState6EBodyRva { get { return WorkerMilitiaNativeLayout.Current.HunterState6EBodyRva; } }
        private static int HunterUnknownStateBodyRva { get { return WorkerMilitiaNativeLayout.Current.HunterUnknownStateBodyRva; } }
        private static int HunterUpdateEpilogueRva { get { return WorkerMilitiaNativeLayout.Current.HunterUpdateEpilogueRva; } }
        private static int MovementArrivalPredicateRva { get { return WorkerMilitiaNativeLayout.Current.MovementArrivalPredicateRva; } }
        private static int MovementContextClearRva { get { return WorkerMilitiaNativeLayout.Current.MovementContextClearRva; } }

        // The cave is the hunter slice of the private arena page
        // (WorkerMilitiaNativeArena); its RVA is fixed at the first apply.
        internal const int CaveLength = WorkerMilitiaNativeArena.HunterMoveStateLength;
        private int _caveRva;

        private int CaveRva
        {
            get { return _caveRva; }
        }

        private static readonly byte[] ExpectedFinalStateDispatch =
        {
            0x66, 0x83, 0xFE, 0x6E, // final state comparison
            0x75, 0x70,             // short branch to native default
        };

        // Whole instructions from current-unit id through the state load.
        // They prove the cave's register contract:
        // rbx=unit id, r13=manager, rdi=unit*0x490, ebp=0,
        // r12=&r_AIState and si=current state.
        private static byte[] ExpectedHunterRegisterSetup
        {
            get
            {
                WorkerMilitiaNativeLayout layout = WorkerMilitiaNativeLayout.Current;
                int site = HunterUpdateRegisterSetupRva;
                var code = new byte[]
                {
                    // movsxd rbx,[rip+current context unit id]
                    0x48, 0x63, 0x1D, 0, 0, 0, 0,
                    // lea r13,[rip+unit manager]
                    0x4C, 0x8D, 0x2D, 0, 0, 0, 0,
                    0x48, 0x69, 0xFB, 0x90, 0x04, 0x00, 0x00,
                    0x33, 0xED,
                    0x4D, 0x8D, 0xA5, 0x18, 0x09, 0x00, 0x00,
                    0x4C, 0x03, 0xE7,
                    0xB8, 0x07, 0x00, 0x00, 0x00,
                    0x4E, 0x8D, 0x34, 0x2F,
                    0x4D, 0x0F, 0xBF, 0xBE, 0x90, 0x09, 0x00, 0x00,
                    0x66, 0x42, 0x89, 0xAC, 0x2F, 0x16, 0x09, 0x00, 0x00,
                    0x66, 0x42, 0x89, 0x84, 0x2F, 0x58, 0x09, 0x00, 0x00,
                    0x41, 0x0F, 0xB7, 0x34, 0x24,
                };
                PutInt32(code, 3, layout.CurrentContextUnitIdRva - (site + 7));
                PutInt32(code, 10, layout.UnitManagerRva - (site + 14));
                return code;
            }
        }

        private static byte[] ExpectedUnknownStateBody
        {
            get
            {
                var code = new byte[]
                {
                    0x66, 0x41, 0x89, 0x2C, 0x24, // mov [r12],bp
                    0x8B, 0xD3,                   // mov edx,ebx
                    0x49, 0x8B, 0xCD,             // mov rcx,r13
                    0xE8, 0, 0, 0, 0,             // native context-clear call
                };
                PutInt32(
                    code,
                    11,
                    MovementContextClearRva - (HunterUnknownStateBodyRva + 15));
                return code;
            }
        }

        private static void PutInt32(byte[] code, int offset, int value)
        {
            code[offset] = (byte)value;
            code[offset + 1] = (byte)(value >> 8);
            code[offset + 2] = (byte)(value >> 16);
            code[offset + 3] = (byte)(value >> 24);
        }

        private static readonly byte[] ExpectedUpdateEpilogue =
        {
            0x48, 0x8B, 0x5C, 0x24, 0x70,
            0x48, 0x8B, 0x6C, 0x24, 0x78,
        };

        private static readonly byte[] ExpectedArrivalPredicateHead =
        {
            0x48, 0x63, 0xC2,
            0x48, 0x69, 0xD0, 0x90, 0x04, 0x00, 0x00,
            0x66, 0x83, 0xBC, 0x0A, 0x4E, 0x07, 0x00, 0x00, 0x00,
        };

        private static readonly byte[] ExpectedContextClearHead =
        {
            0x48, 0x63, 0xC2,
            0x48, 0x69, 0xD0, 0x90, 0x04, 0x00, 0x00,
            0x33, 0xC0,
            0x89, 0x84, 0x0A, 0x52, 0x07, 0x00, 0x00,
        };

        private const uint PageExecuteReadWrite = 0x40;

        private readonly Action<string> _info;
        private readonly Action<string> _warning;

        private long _moduleBase;
        private int _applyThreadId;
        private bool _applied;
        private bool _indeterminate;
        private bool _nativeExecutionStateIndeterminate;
        private byte[] _originalDispatch;
        private byte[] _appliedDispatch;
        private byte[] _originalCave;
        private byte[] _appliedCave;
        private string _evidence;

        internal WorkerMilitiaHunterMoveState(
            Action<string> info,
            Action<string> warning)
        {
            _info = info ?? throw new ArgumentNullException("info");
            _warning = warning ?? throw new ArgumentNullException("warning");
        }

        internal bool IsApplied
        {
            get { return _applied; }
        }

        internal bool IsIndeterminate
        {
            get { return _indeterminate; }
        }

        internal string Evidence
        {
            get { return _evidence ?? "not applied"; }
        }

        internal bool TryApply(
            IntPtr moduleBase,
            int nativeRunThreadId,
            out string reason)
        {
            reason = null;
            if (_applied)
            {
                return true;
            }
            if (_indeterminate || _nativeExecutionStateIndeterminate)
            {
                reason = "a previous hunter move-state restore is indeterminate";
                return false;
            }
            int currentThreadId = Thread.CurrentThread.ManagedThreadId;
            if (nativeRunThreadId <= 0 || currentThreadId != nativeRunThreadId)
            {
                reason = "hunter move-state apply changed native-run thread";
                return false;
            }
            if (moduleBase == IntPtr.Zero)
            {
                reason = "native module base is unavailable";
                return false;
            }
            if (WorkerMilitiaNativeLayout.Current == null)
            {
                reason = "CrusaderDE.dll is not a known militia build";
                return false;
            }
            _moduleBase = moduleBase.ToInt64();

            byte[] dispatch = Read(
                HunterFinalStateDispatchRva,
                ExpectedFinalStateDispatch.Length);
            byte[] registerSetup = Read(
                HunterUpdateRegisterSetupRva,
                ExpectedHunterRegisterSetup.Length);
            byte[] unknownState = Read(
                HunterUnknownStateBodyRva,
                ExpectedUnknownStateBody.Length);
            byte[] epilogue = Read(
                HunterUpdateEpilogueRva,
                ExpectedUpdateEpilogue.Length);
            byte[] arrival = Read(
                MovementArrivalPredicateRva,
                ExpectedArrivalPredicateHead.Length);
            byte[] clear = Read(
                MovementContextClearRva,
                ExpectedContextClearHead.Length);
            if (!SequenceEquals(dispatch, ExpectedFinalStateDispatch)
                || !SequenceEquals(registerSetup, ExpectedHunterRegisterSetup)
                || !SequenceEquals(unknownState, ExpectedUnknownStateBody)
                || !SequenceEquals(epilogue, ExpectedUpdateEpilogue)
                || !SequenceEquals(arrival, ExpectedArrivalPredicateHead)
                || !SequenceEquals(clear, ExpectedContextClearHead))
            {
                reason = "pinned hunter move-state code changed (dispatch="
                    + Hex(dispatch) + " setup=" + Hex(registerSetup)
                    + " default=" + Hex(unknownState)
                    + " epilogue=" + Hex(epilogue)
                    + " arrival=" + Hex(arrival)
                    + " clear=" + Hex(clear) + ")";
                return false;
            }

            int caveRva;
            if (!WorkerMilitiaNativeArena.TryGetSliceRva(
                    moduleBase,
                    WorkerMilitiaNativeArena.HunterMoveStateOffset,
                    CaveLength,
                    out caveRva,
                    out reason))
            {
                return false;
            }
            _caveRva = caveRva;
            byte[] caveOriginal = Read(CaveRva, CaveLength);
            if (!SequenceEquals(caveOriginal, new byte[CaveLength]))
            {
                reason = "the dedicated hunter move-state cave is not free";
                return false;
            }

            byte[] cave;
            byte[] hook;
            try
            {
                cave = BuildCave();
                hook = BuildHook();
            }
            catch (Exception exception)
            {
                reason = "hunter move-state code could not be assembled ("
                    + exception.GetType().Name + ": " + exception.Message + ")";
                return false;
            }

            _originalDispatch = dispatch;
            _appliedDispatch = hook;
            _originalCave = caveOriginal;
            _appliedCave = cave;
            _applyThreadId = currentThreadId;

            try
            {
                // The code exists before the live dispatch can reach it.
                WriteCode(CaveRva, _appliedCave);
                WriteCode(HunterFinalStateDispatchRva, _appliedDispatch);
                if (!SequenceEquals(
                        Read(CaveRva, _appliedCave.Length),
                        _appliedCave)
                    || !SequenceEquals(
                        Read(
                            HunterFinalStateDispatchRva,
                            _appliedDispatch.Length),
                        _appliedDispatch))
                {
                    throw new InvalidOperationException(
                        "hunter move-state patch readback disagrees");
                }
            }
            catch (Exception exception)
            {
                reason = "hunter move-state native write was refused ("
                    + exception.GetType().Name + ": " + exception.Message + ")";
                if (!RollBackPartialWrite(out string rollbackReason))
                {
                    reason += "; rollback is indeterminate: " + rollbackReason;
                }
                else
                {
                    reason += "; every owned byte was restored and read back";
                }
                return false;
            }

            _applied = true;
            _indeterminate = false;
            _evidence = "thread="
                + currentThreadId.ToString(CultureInfo.InvariantCulture)
                + " dispatch=0x"
                + HunterFinalStateDispatchRva.ToString(
                    "X", CultureInfo.InvariantCulture)
                + " cave=0x" + CaveRva.ToString("X", CultureInfo.InvariantCulture)
                + " state=0x65 locomotion=1 speed=1 arrival=0x"
                + MovementArrivalPredicateRva.ToString(
                    "X", CultureInfo.InvariantCulture);
            _info(
                "Worker militia installed the native hunter move-state branch: "
                + _evidence + ". State 0x6E and every original default state "
                + "retain their exact destinations; no sprite field is written.");
            return true;
        }

        internal bool TryRevert(string why, out string reason)
        {
            reason = null;
            if (!_applied && !_indeterminate)
            {
                return true;
            }
            int currentThreadId = Thread.CurrentThread.ManagedThreadId;
            if (_applyThreadId <= 0 || currentThreadId != _applyThreadId)
            {
                reason = "hunter move-state revert changed native-run thread "
                    + "(applied="
                    + _applyThreadId.ToString(CultureInfo.InvariantCulture)
                    + " current="
                    + currentThreadId.ToString(CultureInfo.InvariantCulture)
                    + ")";
                return false;
            }
            if (RollBackPartialWrite(out reason))
            {
                _info(
                    "Worker militia restored the native hunter move-state "
                    + "dispatch (" + why + ") and verified both regions.");
                return true;
            }
            _warning(
                "Worker militia could not prove restoration of the hunter "
                + "move-state patch (" + why + "): "
                + (reason ?? "unknown readback failure") + ".");
            return false;
        }

        private bool RollBackPartialWrite(out string reason)
        {
            var sites = new List<WorkerMilitiaOwnedPatchSite>
            {
                // Remove the only entrance before clearing its destination.
                new WorkerMilitiaOwnedPatchSite(
                    "hunter move-state dispatch",
                    HunterFinalStateDispatchRva,
                    true,
                    _originalDispatch,
                    _appliedDispatch),
                new WorkerMilitiaOwnedPatchSite(
                    "hunter move-state cave",
                    CaveRva,
                    true,
                    _originalCave,
                    _appliedCave),
            };
            bool restored = WorkerMilitiaOwnedPatchRestore.TryRestore(
                sites,
                Read,
                (rva, value, executable) => WriteCode(rva, value),
                () => _nativeExecutionStateIndeterminate,
                out reason);
            if (!restored)
            {
                _indeterminate = true;
                _applied = true;
                return false;
            }
            ClearOwnedState();
            return true;
        }

        private void ClearOwnedState()
        {
            _applied = false;
            _indeterminate = false;
            _applyThreadId = 0;
            _originalDispatch = null;
            _appliedDispatch = null;
            _originalCave = null;
            _appliedCave = null;
            _evidence = "reverted";
        }

        private byte[] BuildHook()
        {
            var hook = new byte[ExpectedFinalStateDispatch.Length];
            hook[0] = 0xE9;
            WriteRelative32(
                hook,
                1,
                HunterFinalStateDispatchRva + 5,
                CaveRva);
            hook[5] = 0x90;
            return hook;
        }

        private byte[] BuildCave()
        {
            // Assembled and independently decoded with Iced x64. Local short
            // branches land at offsets 0x66 (state 6E), 0x6B (default) and
            // 0x61 (path still active). rel32 operands are filled below.
            var code = new byte[]
            {
                0x66, 0x83, 0xFE, 0x6E, 0x74, 0x60,
                0x66, 0x83, 0xFE, 0x65, 0x75, 0x5F,
                0x42, 0xC7, 0x84, 0x2F, 0x88, 0x06, 0x00, 0x00,
                0x10, 0x00, 0x00, 0x00,
                0xBE, 0x01, 0x00, 0x00, 0x00,
                0x42, 0x89, 0xB4, 0x2F, 0x60, 0x06, 0x00, 0x00,
                0x66, 0x42, 0x89, 0xB4, 0x2F, 0xA4, 0x09, 0x00, 0x00,
                0x66, 0x42, 0x89, 0xAC, 0x2F, 0x16, 0x09, 0x00, 0x00,
                0x89, 0xDA,
                0x4C, 0x89, 0xE9,
                0xE8, 0x00, 0x00, 0x00, 0x00,
                0x85, 0xC0,
                0x74, 0x1C,
                0x66, 0x41, 0x89, 0x2C, 0x24,
                0x42, 0x89, 0xAC, 0x2F, 0x08, 0x09, 0x00, 0x00,
                0x89, 0xDA,
                0x4C, 0x89, 0xE9,
                0xE8, 0x00, 0x00, 0x00, 0x00,
                0xE9, 0x00, 0x00, 0x00, 0x00,
                0xE9, 0x00, 0x00, 0x00, 0x00,
                0xE9, 0x00, 0x00, 0x00, 0x00,
                0xE9, 0x00, 0x00, 0x00, 0x00,
            };
            if (code.Length != CaveLength)
            {
                throw new InvalidOperationException(
                    "hunter move-state cave length changed to "
                    + code.Length.ToString(CultureInfo.InvariantCulture));
            }

            WriteRelative32(
                code,
                0x3D,
                CaveRva + 0x41,
                MovementArrivalPredicateRva);
            WriteRelative32(
                code,
                0x58,
                CaveRva + 0x5C,
                MovementContextClearRva);
            WriteRelative32(
                code,
                0x5D,
                CaveRva + 0x61,
                HunterUpdateEpilogueRva);
            WriteRelative32(
                code,
                0x62,
                CaveRva + 0x66,
                HunterUpdateEpilogueRva);
            WriteRelative32(
                code,
                0x67,
                CaveRva + 0x6B,
                HunterState6EBodyRva);
            WriteRelative32(
                code,
                0x6C,
                CaveRva + 0x70,
                HunterUnknownStateBodyRva);
            return code;
        }

        private byte[] Read(int rva, int length)
        {
            var value = new byte[length];
            Marshal.Copy(new IntPtr(_moduleBase + rva), value, 0, length);
            return value;
        }

        private void WriteCode(int rva, byte[] value)
        {
            var address = new IntPtr(_moduleBase + rva);
            uint previous;
            if (!VirtualProtect(
                    address,
                    new UIntPtr((uint)value.Length),
                    PageExecuteReadWrite,
                    out previous))
            {
                throw new InvalidOperationException(
                    "could not unprotect hunter move-state RVA 0x"
                    + rva.ToString("X", CultureInfo.InvariantCulture));
            }
            try
            {
                Marshal.Copy(value, 0, address, value.Length);
            }
            finally
            {
                uint ignored;
                bool restored = VirtualProtect(
                        address,
                        new UIntPtr((uint)value.Length),
                        previous,
                        out ignored)
                    || VirtualProtect(
                        address,
                        new UIntPtr((uint)value.Length),
                        previous,
                        out ignored);
                if (!restored)
                {
                    _nativeExecutionStateIndeterminate = true;
                    throw new InvalidOperationException(
                        "could not restore hunter move-state page protection "
                        + "at RVA 0x"
                        + rva.ToString("X", CultureInfo.InvariantCulture));
                }
            }
            bool flushed = FlushInstructionCache(
                    GetCurrentProcess(),
                    address,
                    new UIntPtr((uint)value.Length))
                || FlushInstructionCache(
                    GetCurrentProcess(),
                    address,
                    new UIntPtr((uint)value.Length));
            if (!flushed)
            {
                _nativeExecutionStateIndeterminate = true;
                throw new InvalidOperationException(
                    "could not flush hunter move-state instructions at RVA 0x"
                    + rva.ToString("X", CultureInfo.InvariantCulture));
            }
        }

        private static void WriteRelative32(
            byte[] buffer,
            int operandOffset,
            int sourceNextRva,
            int targetRva)
        {
            long displacement = (long)targetRva - sourceNextRva;
            if (displacement < int.MinValue || displacement > int.MaxValue)
            {
                throw new InvalidOperationException(
                    "hunter move-state branch exceeds rel32 range");
            }
            byte[] encoded = BitConverter.GetBytes((int)displacement);
            Array.Copy(encoded, 0, buffer, operandOffset, encoded.Length);
        }

        private static bool SequenceEquals(byte[] left, byte[] right)
        {
            if (left == null || right == null || left.Length != right.Length)
            {
                return false;
            }
            for (int index = 0; index < left.Length; index++)
            {
                if (left[index] != right[index])
                {
                    return false;
                }
            }
            return true;
        }

        private static string Hex(byte[] value)
        {
            return value == null
                ? "none"
                : BitConverter.ToString(value).Replace("-", string.Empty);
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool VirtualProtect(
            IntPtr address,
            UIntPtr size,
            uint newProtect,
            out uint oldProtect);

        [DllImport("kernel32.dll")]
        private static extern IntPtr GetCurrentProcess();

        [DllImport("kernel32.dll")]
        private static extern bool FlushInstructionCache(
            IntPtr process,
            IntPtr address,
            UIntPtr size);
    }
}
