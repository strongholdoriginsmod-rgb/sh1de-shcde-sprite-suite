using System;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Threading;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Makes the engine's own selection-class census count a militia worker,
    /// which is what the command cursor and the native command path depend on.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Measured on the pinned CrusaderDE.dll (sha 20c4157b..., the same build
    /// <c>WorkerMilitiaFeature.Prepare</c> already attests) on 2026-08-27.
    /// </para>
    /// <para>
    /// The input manager keeps 35 counters at manager+0x564, one per
    /// commandable unit class. RVA 0x196F90 rebuilds them from scratch on
    /// every input tick: it zeroes the block, walks the unit array and, for
    /// each unit that is alive (+0x88 == 2), unblocked (+0x29C == 0), owned by
    /// the local player (+0x92) and selected (+0x30 != 0), dispatches on the
    /// unit type through a jump table:
    /// </para>
    /// <code>
    /// 0x19707B  movsx eax,word [r10-0x212]          ; r_UnitChimp
    /// 0x197083  add   eax,0xFFFFFFFB                ; index = type - 5
    /// 0x197086  cmp   eax,0x50                      ; 81 entries, types 5..85
    /// 0x197089  ja    default
    /// 0x197091  movzx eax,byte [rbx+rax+0x1972F4]   ; case index (rbx = base)
    /// 0x197099  mov   edx,[rbx+rax*4+0x197268]      ; case target
    /// </code>
    /// <para>
    /// The case table maps only soldiers, siege equipment and the Arab roster
    /// to a counter. CHIMP_TYPE_HUNTER (6) resolves to the default case and
    /// increments nothing; CHIMP_TYPE_WOODCUTTER (3) does not even survive the
    /// range check, because the window starts at type 5. So with a militia
    /// worker selected all 35 counters stay zero, and every predicate the
    /// cursor logic asks answers "nothing commandable is selected".
    /// </para>
    /// <para>
    /// What those predicates actually ask, resolved 2026-08-29 by following
    /// each counter offset back through the case table to its unit type. The
    /// earlier labels were guesses and one of them was plainly wrong:
    /// <list type="bullet">
    /// <item>0x190940 - any of ARCHER, SPEARMAN, MACEMAN, PIKEMAN, ENGINEER,
    /// ARAB_SLAVE, SAPPER, DEMOLISHER, SKIRMISHER, EUNUCH. Not "any fighting
    /// class" - knight and swordsman are absent.</item>
    /// <item>0x1954C0 - any ranged class (ARCHER, XBOWMAN, ARAB_BOW, SLINGER,
    /// the engines, the mounted archers). This label was right.</item>
    /// <item>0x1955A0 - ONLY ARAB_ASSASIN (73) selected. It was documented as
    /// "only archers" for two weeks; counter index 22 is the assassin, not the
    /// archer, and the archer is index 0.</item>
    /// <item>0x1955E0 - the ENGINEER class (counter index 7).</item>
    /// <item>0x195850 - a heavy or mounted class is selected (knight,
    /// ladderman, ram, trebuchet, catapult, shield, horseman, arab ballista,
    /// heavy camel, camel lancer, siege tower).</item>
    /// </list>
    /// This is why the donors below are the right ones: a hunter counted as
    /// ARCHER passes "ranged" and "task-capable" and fails "assassin" and
    /// "heavy"; a woodcutter counted as MACEMAN passes "task-capable" and
    /// fails the rest. Both are what those two workers should be.
    /// </para>
    /// <para>
    /// The census is only half the gate. See
    /// NativeCommandTargetFallbackRva below for the second, stack-local class
    /// list at 0x18C1A0 that no census patch can reach.
    /// </para>
    /// <para>
    /// This class widens that window to type 3 and relocates the case table,
    /// so a woodcutter and a hunter resolve to a real class. The relocation is
    /// what makes it honest: the two new entries are appended in free space
    /// rather than stolen from neighbouring data, and the original table is
    /// left untouched byte for byte.
    /// </para>
    /// <para>
    /// Six bytes of code change in total, plus an 83-byte table written into
    /// the zero padding behind .text. Nothing here is speculative: every
    /// address is verified against its expected instruction bytes before a
    /// single byte is written, the donor case indices are read out of the
    /// engine's own table instead of being hard-coded, and any mismatch fails
    /// closed with the reason in the log.
    /// </para>
    /// <para>
    /// The patch only ever changes what the census sees for units that are
    /// <em>selected and owned by the local player</em>. A woodcutter cannot be
    /// selected without this mod, so on an unmodded selection it is inert.
    /// </para>
    /// </remarks>
    internal sealed class WorkerMilitiaCommandClass
    {
        // --- pinned code sites ------------------------------------------------
        // Whole instructions are pinned, not just the bytes that change, so a
        // shifted or recompiled engine can never be patched by accident.
        private static int NativeCensusFunctionRva { get { return WorkerMilitiaNativeLayout.Current.CensusFunctionRva; } }
        private static int NativeCensusWindowBaseRva { get { return WorkerMilitiaNativeLayout.Current.CensusWindowBaseRva; } }
        private static int NativeCensusWindowLimitRva { get { return WorkerMilitiaNativeLayout.Current.CensusWindowLimitRva; } }
        private static int NativeCensusCaseLookupRva { get { return WorkerMilitiaNativeLayout.Current.CensusCaseLookupRva; } }

        private static readonly byte[] ExpectedWindowBase =
            { 0x83, 0xC0, 0xFB };                       // add eax,-5
        private static readonly byte[] ExpectedWindowLimit =
            { 0x83, 0xF8, 0x50 };                       // cmp eax,0x50
        // movzx eax,byte [rbx+rax+<case table RVA>]; the disp32 is the
        // build's own table address (2.7: 0x1972F4, 2.80: 0x198524).
        private static byte[] ExpectedCaseLookup
        {
            get
            {
                int table = NativeCensusCaseTableRva;
                return new byte[]
                {
                    0x0F, 0xB6, 0x84, 0x03,
                    (byte)table, (byte)(table >> 8),
                    (byte)(table >> 16), (byte)(table >> 24),
                };
            }
        }

        // Offsets of the three bytes that actually change.
        private const int WindowBaseImmediateOffset = 2;
        private const int WindowLimitImmediateOffset = 2;
        private const int CaseLookupDisplacementOffset = 4;

        // --- pinned data tables -----------------------------------------------
        private static int NativeCensusCaseTableRva { get { return WorkerMilitiaNativeLayout.Current.CensusCaseTableRva; } }
        private static int NativeCensusJumpTableRva { get { return WorkerMilitiaNativeLayout.Current.CensusJumpTableRva; } }
        private const int NativeCensusJumpTableEntries = 35;
        private const int NativeCensusCounterBase = 0x564;
        private const int NativeCensusCounterCount = 35;

        // Type window. The engine covers 5..85; the militia needs 3..85.
        private const int OriginalWindowFirstType = 5;
        private const int OriginalWindowLastType = 85;
        private const int ExtendedWindowFirstType = 3;
        private const int OriginalCaseTableLength =
            OriginalWindowLastType - OriginalWindowFirstType + 1;   // 81
        private const int ExtendedCaseTableLength =
            OriginalWindowLastType - ExtendedWindowFirstType + 1;   // 83

        // --- unit types (pinned separately in WorkerMilitiaFeature.Prepare) ----
        private const int TypeWoodcutter = 3;
        private const int TypeFletcher = 4;
        private const int TypeHunter = 6;
        // Donor classes. The hunter carries a bow, so it counts as the archer
        // class; the woodcutter fights with an axe in reach, so it counts as
        // the maceman class. Both are plain fighting classes without a special
        // ability (unlike ladderman, engineer or the siege entries), and both
        // are part of the counter set the cursor logic's broadest predicate at
        // RVA 0x190940 tests.
        private const int DonorTypeForHunter = 22;      // CHIMP_TYPE_ARCHER
        private const int DonorTypeForWoodcutter = 26;  // CHIMP_TYPE_MACEMAN

        // How a case target is recognised as "this one counts".
        //
        // There are two encodings, and telling them apart matters more than it
        // looks. The first class - the archer counter at manager+0x564 - is
        // incremented through r9, which the function loads once up front; every
        // other class is a direct displacement off rcx. The default case, the
        // one a militia worker currently lands in, increments the loop register
        // instead and shares its first two bytes with the r9 form. A decoder
        // that only looks at "41 FF" therefore reports the default case as the
        // archer class - which is exactly the wrong way round.
        private static int NativeCensusCounterRegisterLoadRva { get { return WorkerMilitiaNativeLayout.Current.CensusCounterRegisterLoadRva; } }
        private static readonly byte[] ExpectedCounterRegisterLoad =
            { 0x4C, 0x8D, 0x89, 0x64, 0x05, 0x00, 0x00 };  // lea r9,[rcx+0x564]
        private static readonly byte[] CountedCaseThroughRegister =
            { 0x41, 0xFF, 0x01 };                          // inc dword [r9]
        private static readonly byte[] CountedCaseByDisplacement =
            { 0xFF, 0x81 };                                // inc dword [rcx+d32]
        private const int MaxCaseTargetPrologue = 6;

        // Cave slices are 16-byte aligned so the trampoline starts aligned
        // and the two regions can never overlap.
        private const int CaveAlignment = 16;

        // ---------------------------------------------------------------
        // The SECOND place the engine keeps "which classes may be commanded".
        //
        // 0x18C1A0 answers "which unit is the player commanding right now?".
        // It builds its own table on its OWN STACK - firstSelectedOfType[type]
        // at [rsp + type*4] - by walking the unit array (alive +0x6E4 == 2,
        // unblocked +0x8F8 == 0, owned +0x6EE, selected +0x68C, type +0x6E6),
        // and then asks a hard-wired chain of 36 checks for types
        // 5, 22..30, 37..41, 55, 58..61, 70..85 - exactly the census window.
        // Hunter (6) and woodcutter (3) are absent, so the chain falls through
        // to 0x18C409 "mov eax,-1".
        //
        // That -1 is what actually kills the command cursor: the caller at
        // 0x8E137 does "test eax,eax / jle", takes the no-unit branch, and
        // 0x8E3EA writes -10 ("not possible"). Relocating the census table
        // alone can never fix it, because this list does not read the census.
        //
        // The fallback instruction is B8 FF FF FF FF - five bytes, exactly the
        // size of a jmp rel32. The trampoline appends the two militia slots
        // AFTER every original check, so a real soldier still always wins and
        // no existing priority moves.
        private static int NativeCommandTargetFallbackRva { get { return WorkerMilitiaNativeLayout.Current.CommandTargetFallbackRva; } }
        private static int NativeCommandTargetExitRva { get { return WorkerMilitiaNativeLayout.Current.CommandTargetExitRva; } }

        // mov eax,0xFFFFFFFF
        private static readonly byte[] ExpectedCommandTargetFallback =
            new byte[] { 0xB8, 0xFF, 0xFF, 0xFF, 0xFF };

        // mov rcx,[rbp+0x70] - the shared epilogue, verified but never written.
        private static readonly byte[] ExpectedCommandTargetExit =
            new byte[] { 0x48, 0x8B, 0x4D, 0x70 };

        private const int CommandTargetTrampolineLength = 26;

        // The census table is padded to a 16-byte boundary so the trampoline
        // starts aligned and the two regions can never overlap.
        private const int RelocatedCaseTableReserve =
            ((ExtendedCaseTableLength + CaveAlignment - 1) / CaveAlignment)
            * CaveAlignment;
        private const int TotalCaveReserve =
            RelocatedCaseTableReserve + CommandTargetTrampolineLength;

        private const uint PageExecuteReadWrite = 0x40;

        private readonly Action<string> _info;
        private readonly Action<string> _warning;

        private long _moduleBase;
        private bool _applied;
        private bool _indeterminate;
        private bool _nativeExecutionStateIndeterminate;
        private int _caveRva;
        private int _applyThreadId;
        private byte[] _originalWindowBase;
        private byte[] _originalWindowLimit;
        private byte[] _originalCaseLookup;
        private byte[] _originalCave;
        private int _targetCaveRva;
        private byte[] _originalCommandTargetFallback;
        private byte[] _appliedCommandTargetFallback;
        private byte[] _originalTargetCave;
        private byte[] _appliedTargetCave;
        private byte[] _appliedWindowBase;
        private byte[] _appliedWindowLimit;
        private byte[] _appliedCaseLookup;
        private byte[] _appliedCave;
        private string _evidence;

        internal WorkerMilitiaCommandClass(
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

        /// <summary>
        /// One line describing what was measured and written, for the log and
        /// for the feature's own evidence output.
        /// </summary>
        internal string Evidence
        {
            get { return _evidence ?? "not applied"; }
        }

        /// <summary>
        /// Verifies every pinned site and, only if all of them match, widens
        /// the census window and relocates its case table.
        /// </summary>
        /// <remarks>
        /// Must be called on the thread that runs <c>EngineInterface.run</c>.
        /// The census executes inside that native call, so patching from the
        /// same thread means the engine can never observe the half-written
        /// state between the table write and the two immediates. Calling this
        /// from a worker thread would be a data race on executable memory and
        /// is refused.
        /// </remarks>
        internal bool TryApply(IntPtr moduleBase, out string reason)
        {
            reason = null;
            if (_applied)
            {
                return true;
            }
            if (_indeterminate || _nativeExecutionStateIndeterminate)
            {
                reason = "a previous native patch restore has no complete readback";
                return false;
            }
            if (moduleBase == IntPtr.Zero)
            {
                reason = "native module base is unavailable";
                return false;
            }
            _moduleBase = moduleBase.ToInt64();

            byte[] windowBase = Read(NativeCensusWindowBaseRva, ExpectedWindowBase.Length);
            byte[] windowLimit = Read(NativeCensusWindowLimitRva, ExpectedWindowLimit.Length);
            byte[] caseLookup = Read(NativeCensusCaseLookupRva, ExpectedCaseLookup.Length);
            byte[] counterLoad = Read(
                NativeCensusCounterRegisterLoadRva,
                ExpectedCounterRegisterLoad.Length);
            if (!SequenceEquals(windowBase, ExpectedWindowBase)
                || !SequenceEquals(windowLimit, ExpectedWindowLimit)
                || !SequenceEquals(caseLookup, ExpectedCaseLookup)
                || !SequenceEquals(counterLoad, ExpectedCounterRegisterLoad))
            {
                reason =
                    "pinned selection-class census code changed (base="
                    + Hex(windowBase)
                    + " limit=" + Hex(windowLimit)
                    + " lookup=" + Hex(caseLookup)
                    + " counter_load=" + Hex(counterLoad) + ")";
                return false;
            }

            // The command-target chain is the second half of the fix. Both
            // anchors are verified before anything is written: the fallback we
            // replace, and the shared epilogue we jump back to. If either has
            // moved, the whole transaction refuses rather than patching one of
            // the two places - a half-taught engine is worse than none.
            byte[] targetFallback = Read(
                NativeCommandTargetFallbackRva,
                ExpectedCommandTargetFallback.Length);
            byte[] targetExit = Read(
                NativeCommandTargetExitRva,
                ExpectedCommandTargetExit.Length);
            if (!SequenceEquals(targetFallback, ExpectedCommandTargetFallback)
                || !SequenceEquals(targetExit, ExpectedCommandTargetExit))
            {
                reason =
                    "pinned command-target chain changed (fallback="
                    + Hex(targetFallback)
                    + " exit=" + Hex(targetExit) + ")";
                return false;
            }

            byte[] cases = Read(NativeCensusCaseTableRva, OriginalCaseTableLength);

            int hunterCase = cases[TypeHunter - OriginalWindowFirstType];
            int archerCase = cases[DonorTypeForHunter - OriginalWindowFirstType];
            int macemanCase = cases[DonorTypeForWoodcutter - OriginalWindowFirstType];
            int fletcherCase = hunterCase;   // the same uncounted default case

            int archerCounter;
            int macemanCounter;
            int hunterCounter;
            if (!TryReadCaseCounter(archerCase, out archerCounter)
                || !TryReadCaseCounter(macemanCase, out macemanCounter))
            {
                reason =
                    "donor classes do not resolve to a counter (archer_case="
                    + archerCase.ToString(CultureInfo.InvariantCulture)
                    + " maceman_case="
                    + macemanCase.ToString(CultureInfo.InvariantCulture) + ")";
                return false;
            }
            if (archerCounter == macemanCounter)
            {
                reason = "the two donor classes share one counter";
                return false;
            }
            // The whole point of the patch is that the militia types are
            // uncounted today. If a future build already counts them, patching
            // would double-count instead of fixing anything.
            if (TryReadCaseCounter(hunterCase, out hunterCounter))
            {
                reason =
                    "the engine already counts hunters (case="
                    + hunterCase.ToString(CultureInfo.InvariantCulture)
                    + " counter=+0x"
                    + hunterCounter.ToString("X", CultureInfo.InvariantCulture)
                    + ")";
                return false;
            }

            int caveRva;
            if (!TryResolveCave(TotalCaveReserve, out caveRva, out reason))
            {
                return false;
            }
            int targetCaveRva = caveRva + RelocatedCaseTableReserve;

            byte[] extended = BuildExtendedCaseTable(
                cases,
                (byte)archerCase,
                (byte)macemanCase,
                (byte)fletcherCase);

            byte[] caveOriginal = Read(caveRva, ExtendedCaseTableLength);
            byte[] targetCaveOriginal = Read(
                targetCaveRva,
                CommandTargetTrampolineLength);
            if (!SequenceEquals(
                    caveOriginal,
                    new byte[ExtendedCaseTableLength])
                || !SequenceEquals(
                    targetCaveOriginal,
                    new byte[CommandTargetTrampolineLength]))
            {
                reason = "the relocation cave changed after its free-space proof";
                return false;
            }

            // Beide Bauschritte liegen VOR dem Schreib-Fangblock. Ein Wurf
            // hier entkaeme aus TryApply nach Apply() und beendete die Miliz
            // fuer die Sitzung - obwohl TryApply genau fuer diesen Fall ein
            // 'reason' fuehrt und der Aufrufer damit sauber degradiert.
            byte[] trampoline;
            byte[] targetHook;
            try
            {
                trampoline = BuildCommandTargetTrampoline(targetCaveRva);
                targetHook = BuildCommandTargetHook(targetCaveRva);
            }
            catch (Exception exception)
            {
                reason = "the command-target trampoline could not be assembled ("
                    + exception.GetType().Name + ": " + exception.Message + ")";
                return false;
            }

            byte[] lookup = (byte[])caseLookup.Clone();
            WriteInt32(lookup, CaseLookupDisplacementOffset, caveRva);
            byte[] limit = (byte[])windowLimit.Clone();
            limit[WindowLimitImmediateOffset] =
                (byte)(ExtendedCaseTableLength - 1);
            byte[] windowStart = (byte[])windowBase.Clone();
            windowStart[WindowBaseImmediateOffset] =
                unchecked((byte)(sbyte)(-ExtendedWindowFirstType));

            _originalWindowBase = windowBase;
            _originalWindowLimit = windowLimit;
            _originalCaseLookup = caseLookup;
            _originalCave = caveOriginal;
            _originalCommandTargetFallback = targetFallback;
            _appliedCommandTargetFallback = targetHook;
            _originalTargetCave = targetCaveOriginal;
            _appliedTargetCave = trampoline;
            _targetCaveRva = targetCaveRva;
            _appliedWindowBase = windowStart;
            _appliedWindowLimit = limit;
            _appliedCaseLookup = lookup;
            _appliedCave = extended;
            _caveRva = caveRva;
            _applyThreadId = Thread.CurrentThread.ManagedThreadId;

            // Every write can fail - VirtualProtect can refuse. A half-written
            // patch would be worse than none, and an exception escaping here
            // would take the whole feature down with it: TryApply is called
            // from Apply(), where a throw aborts the militia entirely. So the
            // sequence rolls itself back and reports instead.
            try
            {
                // Order matters only in theory - see the remark above - but the
                // table is still written first, so that at no point does a live
                // displacement point at an unwritten table.
                Write(caveRva, _appliedCave);
                WriteCode(NativeCensusCaseLookupRva, _appliedCaseLookup);
                WriteCode(NativeCensusWindowLimitRva, _appliedWindowLimit);
                WriteCode(NativeCensusWindowBaseRva, _appliedWindowBase);

                // Same rule for the second site: the trampoline exists before
                // anything can jump into it.
                WriteCode(_targetCaveRva, _appliedTargetCave);
                WriteCode(
                    NativeCommandTargetFallbackRva,
                    _appliedCommandTargetFallback);

                // VirtualProtect/Marshal.Copy returning normally is not yet
                // proof that the native process owns the exact transaction we
                // intended.  Verify all four sites before publishing
                // _applied.  A mismatch is handled like any other partial
                // write: every original byte is restored and read back, or
                // ownership remains indeterminate and no later lease may run.
                if (!SequenceEquals(
                        Read(caveRva, _appliedCave.Length),
                        _appliedCave)
                    || !SequenceEquals(
                        Read(
                            NativeCensusCaseLookupRva,
                            _appliedCaseLookup.Length),
                        _appliedCaseLookup)
                    || !SequenceEquals(
                        Read(
                            NativeCensusWindowLimitRva,
                            _appliedWindowLimit.Length),
                        _appliedWindowLimit)
                    || !SequenceEquals(
                        Read(
                            NativeCensusWindowBaseRva,
                            _appliedWindowBase.Length),
                        _appliedWindowBase)
                    || !SequenceEquals(
                        Read(_targetCaveRva, _appliedTargetCave.Length),
                        _appliedTargetCave)
                    || !SequenceEquals(
                        Read(
                            NativeCommandTargetFallbackRva,
                            _appliedCommandTargetFallback.Length),
                        _appliedCommandTargetFallback))
                {
                    throw new InvalidOperationException(
                        "native selection-class patch readback disagrees");
                }
            }
            catch (Exception exception)
            {
                reason =
                    "a native write was refused ("
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
            _evidence =
                "thread=" + Thread.CurrentThread.ManagedThreadId.ToString(
                    CultureInfo.InvariantCulture)
                + " window=" + ExtendedWindowFirstType.ToString(CultureInfo.InvariantCulture)
                + ".." + OriginalWindowLastType.ToString(CultureInfo.InvariantCulture)
                + " table=0x" + caveRva.ToString("X", CultureInfo.InvariantCulture)
                + " woodcutter_case=" + macemanCase.ToString(CultureInfo.InvariantCulture)
                + "(+0x" + macemanCounter.ToString("X", CultureInfo.InvariantCulture) + ")"
                + " hunter_case=" + archerCase.ToString(CultureInfo.InvariantCulture)
                + "(+0x" + archerCounter.ToString("X", CultureInfo.InvariantCulture) + ")"
                + " target_hook=0x" + NativeCommandTargetFallbackRva.ToString(
                    "X", CultureInfo.InvariantCulture)
                + " target_trampoline=0x" + targetCaveRva.ToString(
                    "X", CultureInfo.InvariantCulture);
            _info(
                "Worker militia taught both native class lists to accept its "
                + "workers: " + _evidence
                + ". The census now counts them, and the command-target chain "
                + "at 0x18C1A0 returns them as a last resort instead of -1, so "
                + "the engine draws the command cursor itself. Real soldiers "
                + "keep every original priority; the original case table is "
                + "untouched and all eleven changed code bytes are restored on "
                + "rollback.");
            return true;
        }

        /// <summary>
        /// Restores only bytes still proven to be either this exact patch or
        /// their exact originals. The complete preflight happens before the
        /// first write, so another extension's drift is never overwritten.
        /// </summary>
        private bool RollBackPartialWrite(out string reason)
        {
            var sites = new[]
            {
                new WorkerMilitiaOwnedPatchSite(
                    "window base",
                    NativeCensusWindowBaseRva,
                    true,
                    _originalWindowBase,
                    _appliedWindowBase),
                new WorkerMilitiaOwnedPatchSite(
                    "window limit",
                    NativeCensusWindowLimitRva,
                    true,
                    _originalWindowLimit,
                    _appliedWindowLimit),
                new WorkerMilitiaOwnedPatchSite(
                    "case lookup",
                    NativeCensusCaseLookupRva,
                    true,
                    _originalCaseLookup,
                    _appliedCaseLookup),
                new WorkerMilitiaOwnedPatchSite(
                    "command-target fallback",
                    NativeCommandTargetFallbackRva,
                    true,
                    _originalCommandTargetFallback,
                    _appliedCommandTargetFallback),
                new WorkerMilitiaOwnedPatchSite(
                    "relocated table",
                    _caveRva,
                    false,
                    _originalCave,
                    _appliedCave),
                // Listed after its hook on purpose: the jmp is removed before
                // the code it points at is cleared, never the other way round.
                new WorkerMilitiaOwnedPatchSite(
                    "command-target trampoline",
                    _targetCaveRva,
                    true,
                    _originalTargetCave,
                    _appliedTargetCave),
            };
            bool restored = WorkerMilitiaOwnedPatchRestore.TryRestore(
                sites,
                Read,
                (rva, value, executable) =>
                {
                    if (executable)
                    {
                        WriteCode(rva, value);
                    }
                    else
                    {
                        Write(rva, value);
                    }
                },
                () => _nativeExecutionStateIndeterminate,
                out reason);
            if (!restored)
            {
                _indeterminate = true;
                _applied = true;
                return false;
            }

            ClearOwnedPatchState();
            return true;
        }

        private void ClearOwnedPatchState()
        {
            _applied = false;
            _indeterminate = false;
            _originalWindowBase = null;
            _originalWindowLimit = null;
            _originalCaseLookup = null;
            _originalCave = null;
            _originalCommandTargetFallback = null;
            _appliedCommandTargetFallback = null;
            _originalTargetCave = null;
            _appliedTargetCave = null;
            _targetCaveRva = 0;
            _appliedWindowBase = null;
            _appliedWindowLimit = null;
            _appliedCaseLookup = null;
            _appliedCave = null;
            _caveRva = 0;
            _applyThreadId = 0;
            _evidence = "reverted";
        }

        /// <summary>
        /// Puts the three pinned instructions back and clears the relocated
        /// table. Idempotent, and safe to call when nothing was applied.
        /// </summary>
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
                reason = "native selection-class revert changed engine thread "
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
                    "Worker militia restored the native selection-class census ("
                    + why + ") and verified every owned byte by readback.");
                return true;
            }
            _warning(
                "Worker militia could not prove restoration of the native "
                + "selection-class census (" + why + "): "
                + (reason ?? "unknown readback failure") + ". Original-byte "
                + "ownership is retained for a later retry.");
            return false;
        }

        /// <summary>
        /// Reads one selected-class counter, for evidence lines. Index 0 is the
        /// archer class at manager+0x564.
        /// </summary>
        internal static int ReadClassCounter(
            long moduleBase,
            int managerRva,
            int counterOffset)
        {
            return Marshal.ReadInt32(new IntPtr(
                moduleBase + managerRva + counterOffset));
        }

        /// <summary>
        /// Builds the relocated case table: the engine's own 81 entries move up
        /// by two, the woodcutter and the fletcher slots appear in front, and
        /// the hunter entry is redirected from the uncounted default case to
        /// the archer class.
        /// </summary>
        private static byte[] BuildExtendedCaseTable(
            byte[] original,
            byte archerCase,
            byte macemanCase,
            byte defaultCase)
        {
            var extended = new byte[ExtendedCaseTableLength];
            int shift = OriginalWindowFirstType - ExtendedWindowFirstType;  // 2
            for (int i = 0; i < original.Length; i++)
            {
                extended[i + shift] = original[i];
            }
            extended[TypeWoodcutter - ExtendedWindowFirstType] = macemanCase;
            // The fletcher is not militia and stays uncounted; the slot only
            // exists because the window is contiguous.
            extended[TypeFletcher - ExtendedWindowFirstType] = defaultCase;
            extended[TypeHunter - ExtendedWindowFirstType] = archerCase;
            return extended;
        }

        /// <summary>
        /// Resolves a case index to the counter it increments, by decoding its
        /// jump-table target. Only "inc dword [rcx+disp32]" with a
        /// displacement inside the 35-counter block counts; the default case
        /// increments the loop register instead and is rejected here, which is
        /// exactly the distinction the patch relies on.
        /// </summary>
        private bool TryReadCaseCounter(int caseIndex, out int counterOffset)
        {
            counterOffset = 0;
            if (caseIndex < 0 || caseIndex >= NativeCensusJumpTableEntries)
            {
                return false;
            }
            int target = Marshal.ReadInt32(new IntPtr(
                _moduleBase + NativeCensusJumpTableRva + (caseIndex * 4)));
            // Every case body of this switch lies between the function's own
            // entry and the two tables that follow it. Bounding the target
            // keeps a wrong read inside the function instead of dereferencing
            // an arbitrary address.
            if (target < NativeCensusFunctionRva
                || target >= NativeCensusJumpTableRva - MaxCaseTargetPrologue)
            {
                return false;
            }
            byte[] head = Read(target, MaxCaseTargetPrologue);
            if (StartsWith(head, CountedCaseThroughRegister))
            {
                // Only meaningful because the pinned "lea r9,[rcx+0x564]" was
                // verified in TryApply; without it this form says nothing.
                counterOffset = NativeCensusCounterBase;
                return true;
            }
            if (!StartsWith(head, CountedCaseByDisplacement))
            {
                return false;
            }
            int offset = BitConverter.ToInt32(
                head,
                CountedCaseByDisplacement.Length);
            if (offset < NativeCensusCounterBase
                || offset >= NativeCensusCounterBase
                    + (NativeCensusCounterCount * 4)
                || ((offset - NativeCensusCounterBase) % 4) != 0)
            {
                return false;
            }
            counterOffset = offset;
            return true;
        }

        /// <summary>
        /// Finds the zero padding between the end of .text and the start of
        /// the next section. The section table is read from the mapped PE
        /// headers rather than hard-coded, and the region is required to be
        /// entirely zero before it is used, so a build whose padding is
        /// occupied refuses instead of overwriting something.
        /// </summary>
        /// <summary>
        /// The relocated census table and its trampoline live in the private
        /// arena page (see <see cref="WorkerMilitiaNativeArena"/>): the .text
        /// padding of 2.80 is too small for the militia's three caves.
        /// </summary>
        private bool TryResolveCave(int length, out int rva, out string reason)
        {
            if (length > WorkerMilitiaNativeArena.CommandClassLength)
            {
                rva = 0;
                reason = "command-class cave exceeds its arena slice";
                return false;
            }
            if (!WorkerMilitiaNativeArena.TryGetSliceRva(
                    new IntPtr(_moduleBase),
                    WorkerMilitiaNativeArena.CommandClassOffset,
                    length,
                    out rva,
                    out reason))
            {
                return false;
            }
            byte[] existing = Read(rva, length);
            for (int b = 0; b < existing.Length; b++)
            {
                if (existing[b] != 0)
                {
                    reason = "the arena slice is not empty";
                    return false;
                }
            }
            return true;
        }

        /// <summary>
        /// Builds the 26-byte trampoline that appends the two militia slots to
        /// the command-target priority chain.
        /// </summary>
        /// <remarks>
        /// Reached by jmp, so rsp is exactly what 0x18C1A0's body used: the
        /// per-type table still sits at [rsp + type*4]. No stack adjustment is
        /// needed, and none is made - a trampoline that touched rsp would
        /// corrupt the epilogue's canary check at 0x18C40E.
        ///
        ///     8B 44 24 18   mov eax,[rsp+0x18]   ; hunter     (6 * 4)
        ///     85 C0         test eax,eax
        ///     75 0D         jne done
        ///     8B 44 24 0C   mov eax,[rsp+0x0C]   ; woodcutter (3 * 4)
        ///     85 C0         test eax,eax
        ///     75 05         jne done
        ///     B8 FF FF FF FF  mov eax,-1         ; the original fallback
        ///  done:
        ///     E9 rel32      jmp 0x18C40E         ; the shared epilogue
        /// </remarks>
        private static byte[] BuildCommandTargetTrampoline(int caveRva)
        {
            var code = new byte[CommandTargetTrampolineLength];
            int at = 0;

            // mov eax,[rsp + hunter*4]
            code[at++] = 0x8B;
            code[at++] = 0x44;
            code[at++] = 0x24;
            code[at++] = checked((byte)(TypeHunter * 4));
            code[at++] = 0x85;
            code[at++] = 0xC0;
            code[at++] = 0x75;
            int firstBranchOperand = at++;

            // mov eax,[rsp + woodcutter*4]
            code[at++] = 0x8B;
            code[at++] = 0x44;
            code[at++] = 0x24;
            code[at++] = checked((byte)(TypeWoodcutter * 4));
            code[at++] = 0x85;
            code[at++] = 0xC0;
            code[at++] = 0x75;
            int secondBranchOperand = at++;

            // mov eax,-1
            code[at++] = 0xB8;
            code[at++] = 0xFF;
            code[at++] = 0xFF;
            code[at++] = 0xFF;
            code[at++] = 0xFF;

            int done = at;
            code[firstBranchOperand] =
                checked((byte)(done - (firstBranchOperand + 1)));
            code[secondBranchOperand] =
                checked((byte)(done - (secondBranchOperand + 1)));

            // jmp 0x18C40E
            code[at++] = 0xE9;
            WriteInt32(
                code,
                at,
                NativeCommandTargetExitRva - (caveRva + at + 4));
            at += 4;

            if (at != CommandTargetTrampolineLength)
            {
                throw new InvalidOperationException(
                    "Worker militia command-target trampoline is "
                    + at.ToString(CultureInfo.InvariantCulture)
                    + " bytes, not "
                    + CommandTargetTrampolineLength.ToString(
                        CultureInfo.InvariantCulture));
            }
            return code;
        }

        /// <summary>The five-byte jmp that replaces the -1 fallback.</summary>
        private static byte[] BuildCommandTargetHook(int caveRva)
        {
            var hook = new byte[5];
            hook[0] = 0xE9;
            WriteInt32(
                hook,
                1,
                caveRva - (NativeCommandTargetFallbackRva + hook.Length));
            return hook;
        }

        private byte[] Read(int rva, int length)
        {
            var buffer = new byte[length];
            Marshal.Copy(new IntPtr(_moduleBase + rva), buffer, 0, length);
            return buffer;
        }

        private void Write(int rva, byte[] value)
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
                    "Worker militia could not unprotect native memory at RVA 0x"
                    + rva.ToString("X", CultureInfo.InvariantCulture));
            }
            try
            {
                Marshal.Copy(value, 0, address, value.Length);
            }
            finally
            {
                uint ignored;
                bool protectionRestored = VirtualProtect(
                    address,
                    new UIntPtr((uint)value.Length),
                    previous,
                    out ignored);
                if (!protectionRestored)
                {
                    protectionRestored = VirtualProtect(
                        address,
                        new UIntPtr((uint)value.Length),
                        previous,
                        out ignored);
                }
                if (!protectionRestored)
                {
                    _nativeExecutionStateIndeterminate = true;
                    throw new InvalidOperationException(
                        "Worker militia could not restore native page protection "
                        + "at RVA 0x"
                        + rva.ToString("X", CultureInfo.InvariantCulture));
                }
            }
        }

        private void WriteCode(int rva, byte[] value)
        {
            Write(rva, value);
            bool flushed = FlushInstructionCache(
                    GetCurrentProcess(),
                    new IntPtr(_moduleBase + rva),
                    new UIntPtr((uint)value.Length))
                || FlushInstructionCache(
                    GetCurrentProcess(),
                    new IntPtr(_moduleBase + rva),
                    new UIntPtr((uint)value.Length));
            if (!flushed)
            {
                _nativeExecutionStateIndeterminate = true;
                throw new InvalidOperationException(
                    "Worker militia could not flush native instructions at RVA 0x"
                    + rva.ToString("X", CultureInfo.InvariantCulture));
            }
        }

        private static void WriteInt32(byte[] buffer, int offset, int value)
        {
            byte[] encoded = BitConverter.GetBytes(value);
            for (int i = 0; i < encoded.Length; i++)
            {
                buffer[offset + i] = encoded[i];
            }
        }

        private static bool StartsWith(byte[] value, byte[] prefix)
        {
            if (value == null || prefix == null || value.Length < prefix.Length)
            {
                return false;
            }
            for (int i = 0; i < prefix.Length; i++)
            {
                if (value[i] != prefix[i])
                {
                    return false;
                }
            }
            return true;
        }

        private static bool SequenceEquals(byte[] left, byte[] right)
        {
            if (left == null || right == null || left.Length != right.Length)
            {
                return false;
            }
            for (int i = 0; i < left.Length; i++)
            {
                if (left[i] != right[i])
                {
                    return false;
                }
            }
            return true;
        }

        private static string Hex(byte[] value)
        {
            if (value == null)
            {
                return "none";
            }
            var text = new char[value.Length * 2];
            const string Digits = "0123456789ABCDEF";
            for (int i = 0; i < value.Length; i++)
            {
                text[i * 2] = Digits[value[i] >> 4];
                text[(i * 2) + 1] = Digits[value[i] & 0xF];
            }
            return new string(text);
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
