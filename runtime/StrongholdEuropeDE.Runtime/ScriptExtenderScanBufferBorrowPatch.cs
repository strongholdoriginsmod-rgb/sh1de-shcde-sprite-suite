using System;
using System.Buffers;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.InteropServices;
using System.Threading;
using BepInEx;
using HarmonyLib;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Runs before SHCDE-SE and removes the eager 137 MiB ToArray allocation
    /// from Zhuqiaomon's ReadOnlySpan HookTransaction constructor.
    /// </summary>
    /// <remarks>
    /// SHCDE-SE supplies progressive views over CrusaderDE.dll. Each one is
    /// frozen into reusable unmanaged storage at the same instant as the old
    /// ToArray call. Fixes subscribes later and deliberately receives the one
    /// original CrusaderLibrary.LibrarySnapshot, which it can share directly.
    /// </remarks>
    [BepInPlugin(
        ScriptExtenderScanBufferBorrowPatch.PluginId,
        "Stronghold Europe DE Early Scan Buffer Patch",
        "0.2.0")]
    public sealed class StrongholdEuropeEarlyMemoryPlugin : BaseUnityPlugin
    {
        private void Awake()
        {
            if (ScriptExtenderGeneration.UsesRedBird)
            {
                // Zhuqiaomon's HookTransaction._memory does not exist in
                // RedBird; there is nothing to borrow. See ScriptExtenderGeneration.
                Logger.LogInfo(
                    "SEDE_RUNTIME_V1|event=script_extender_scan_buffers"
                    + "|status=not_applicable|reason=redbird_generation");
                return;
            }
            ScriptExtenderScanBufferBorrowPatch.TryInstall(
                message => Logger.LogInfo(message),
                message => Logger.LogWarning(message));
        }
    }

    internal static class ScriptExtenderScanBufferBorrowPatch
    {
        internal const string PluginId = "0000strongholdeuropede.scanbuffers";
        internal const int ExpectedModuleBytes = 0x08902000;
        internal const int ExpectedNativeTransactions =
            ScriptExtenderScanBufferTopologyDecision.ExpectedNativeTransactions;
        internal const int MaximumAttestedSnapshotTransactions =
            ScriptExtenderScanBufferTopologyDecision
                .ExpectedFixesSnapshotTransactions;
        internal const int MaximumAttestedUnmanagedScratchBuffers = 2;
        internal const int MaximumAttestedTransactions =
            ExpectedNativeTransactions + MaximumAttestedSnapshotTransactions;
        internal const long MaximumAttestedPreventedBytes =
            (long)MaximumAttestedTransactions * ExpectedModuleBytes;
        internal const long MaximumAttestedScratchBytes =
            (long)MaximumAttestedUnmanagedScratchBuffers * ExpectedModuleBytes;
        internal const long MaximumAttestedSteadyScratchBytes =
            ExpectedModuleBytes;

        private const string GameModuleName = "CrusaderDE.dll";
        private const string TransactionTypeName =
            "Zhuqiaomon.Hooks.Transaction.HookTransaction";
        private const string CrusaderLibraryTypeName =
            "SHCDESE.API.LowLevel.CrusaderLibrary";

        private static readonly object Gate = new object();
        private static readonly List<UnmanagedSnapshotMemoryManager>
            ScratchPool = new List<UnmanagedSnapshotMemoryManager>();
        private static readonly ScriptExtenderScanBufferLeaseMachine<
            UnmanagedSnapshotMemoryManager> LeaseMachine =
                new ScriptExtenderScanBufferLeaseMachine<
                    UnmanagedSnapshotMemoryManager>();
        [ThreadStatic]
        private static ScriptExtenderScanBufferInvocationFrame<
            UnmanagedSnapshotMemoryManager> _constructorFrame;
        private static FieldInfo _transactionMemoryField;
        private static FieldInfo _snapshotField;
        private static object _crusaderLibrary;
        private static Action<string> _information;
        private static Action<string> _warning;
        private static int _installState;
        private static int _nativeTransactions;
        private static int _snapshotTransactions;
        private static int _fallbackTransactions;
        private static int _constructorInvocations;
        // 0 = collecting startup transactions, 1 = attested/finalized,
        // -1 = startup path aborted. Both terminal states release later free
        // scratch immediately instead of leaving it rooted in the static pool.
        private static int _startupDisposition;

        internal static bool Installed => Volatile.Read(ref _installState) == 2;
        internal static int NativeTransactions =>
            Volatile.Read(ref _nativeTransactions);
        internal static int SnapshotTransactions =>
            Volatile.Read(ref _snapshotTransactions);
        internal static int FallbackTransactions =>
            Volatile.Read(ref _fallbackTransactions);

        internal static ScriptExtenderScanBufferTrackedMemoryState
            GetTrackedMemoryState(object transaction)
        {
            lock (Gate)
            {
                return LeaseMachine.GetState(transaction);
            }
        }

        internal static bool TryFinalizeStartup(
            out int residentScratchBytes,
            out int peakScratchBytes)
        {
            residentScratchBytes = 0;
            peakScratchBytes = 0;
            lock (Gate)
            {
                if (Volatile.Read(ref _startupDisposition) != 0)
                {
                    TrimProvablyFreeScratchUnderLock();
                    return false;
                }
                ScriptExtenderScanBufferTopology topology =
                    ScriptExtenderScanBufferTopologyDecision.Evaluate(
                        Installed,
                        NativeTransactions,
                        SnapshotTransactions,
                        FallbackTransactions,
                        ScratchPool.Count,
                        LeaseMachine.ActiveCount,
                        Volatile.Read(ref _constructorInvocations) != 0
                            || _constructorFrame != null);
                if (!topology.Accepted)
                {
                    AbortStartupUnderLock();
                    return false;
                }
                if (!StartupOwnershipMatchesTopologyUnderLock(
                        topology.RetainedScratchBuffers))
                {
                    AbortStartupUnderLock();
                    return false;
                }
                peakScratchBytes = checked(
                    ScratchPool.Count * ExpectedModuleBytes);

                TrimProvablyFreeScratchUnderLock();
                if (ScratchPool.Count != topology.RetainedScratchBuffers
                    || !StartupOwnershipMatchesTopologyUnderLock(
                        topology.RetainedScratchBuffers))
                {
                    AbortStartupUnderLock();
                    return false;
                }
                for (int index = 0; index < ScratchPool.Count; index++)
                {
                    if (!ScratchPool[index].Leased)
                    {
                        AbortStartupUnderLock();
                        return false;
                    }
                }
                residentScratchBytes = checked(
                    topology.RetainedScratchBuffers * ExpectedModuleBytes);
                Volatile.Write(ref _startupDisposition, 1);
                return true;
            }
        }

        internal static void ReleaseProvablyFreeScratch()
        {
            lock (Gate)
            {
                AbortStartupUnderLock();
            }
        }

        internal static void TryInstall(
            Action<string> information,
            Action<string> warning)
        {
            if (Interlocked.CompareExchange(ref _installState, 1, 0) != 0)
            {
                return;
            }

            _information = information;
            _warning = warning;
            Harmony harmony = null;
            try
            {
                RuntimeBuildGuard.VerifyEarlyLoadedAssembly(
                    typeof(ReadOnlyMemory<byte>).Assembly,
                    "system_memory");
                RuntimeBuildGuard.VerifyEarlyLoadedAssembly(
                    typeof(BaseUnityPlugin).Assembly,
                    "bepinex_core");
                RuntimeBuildGuard.VerifyEarlyLoadedAssembly(
                    typeof(Harmony).Assembly,
                    "harmony");

                string zhuqiaomonPath =
                    RuntimeBuildGuard.GetVerifiedPrerequisitePath(
                        "zhuqiaomon");
                Assembly zhuqiaomon = FindOrLoadUniqueAssembly(
                    "Zhuqiaomon",
                    zhuqiaomonPath);
                RuntimeBuildGuard.VerifyEarlyLoadedAssembly(
                    zhuqiaomon,
                    "zhuqiaomon");

                ConstructorInfo constructor = RequireSpanConstructor(
                    zhuqiaomon);
                MethodInfo commit = RequireCommitMethod(
                    constructor.DeclaringType);
                _transactionMemoryField = constructor.DeclaringType.GetField(
                    "_memory",
                    BindingFlags.Instance | BindingFlags.NonPublic);
                if (_transactionMemoryField == null
                    || _transactionMemoryField.FieldType
                        != typeof(ReadOnlyMemory<byte>))
                {
                    throw new InvalidDataException(
                        "Pinned HookTransaction memory field changed");
                }

                MethodInfo transpiler = RequireOwnMethod(
                    "TranspileSpanConstructor");
                MethodInfo constructorPrefix = RequireOwnMethod(
                    "SpanConstructorPrefix");
                MethodInfo constructorPostfix = RequireOwnMethod(
                    "SpanConstructorPostfix");
                MethodInfo constructorFinalizer = RequireOwnMethod(
                    "SpanConstructorFinalizer");
                MethodInfo commitFinalizer = RequireOwnMethod(
                    "CommitFinalizer");
                if (transpiler == null)
                {
                    throw new MissingMethodException(
                        "Early scan-buffer transpiler is unavailable");
                }

                harmony = new Harmony(PluginId);
                // Patch Commit first. If constructor patching then fails, this
                // finalizer sees no lease and is a harmless no-op. The catch
                // path removes both patches before SHCDE-SE gets control.
                harmony.Patch(
                    commit,
                    finalizer: new HarmonyMethod(commitFinalizer));
                harmony.Patch(
                    constructor,
                    prefix: new HarmonyMethod(constructorPrefix),
                    postfix: new HarmonyMethod(constructorPostfix),
                    transpiler: new HarmonyMethod(transpiler),
                    finalizer: new HarmonyMethod(constructorFinalizer),
                    ilmanipulator: null);
                Volatile.Write(ref _installState, 2);
                Emit(
                    _information,
                    "SEDE_EARLY_V1|event=scan_buffer_ctor_patch"
                    + "|status=installed"
                    + "|target=zhuqiaomon_hooktransaction_span_ctor");
            }
            catch (Exception exception)
            {
                if (harmony != null)
                {
                    try
                    {
                        harmony.UnpatchSelf();
                    }
                    catch
                    {
                    }
                }
                Volatile.Write(ref _installState, 3);
                Emit(
                    _warning,
                    "SEDE_EARLY_V1|event=scan_buffer_ctor_patch"
                    + "|status=original_copy_path"
                    + "|reason=" + Token(exception.GetType().Name));
            }
        }

        private static MethodInfo RequireOwnMethod(string name)
        {
            MethodInfo method = typeof(
                ScriptExtenderScanBufferBorrowPatch).GetMethod(
                    name,
                    BindingFlags.Static | BindingFlags.NonPublic);
            if (method == null)
            {
                throw new MissingMethodException(
                    "Early scan-buffer method is unavailable: " + name);
            }
            return method;
        }

        private static IEnumerable<CodeInstruction> TranspileSpanConstructor(
            IEnumerable<CodeInstruction> instructions)
        {
            var rewritten = new List<CodeInstruction>(instructions);
            MethodInfo borrow = typeof(
                ScriptExtenderScanBufferBorrowPatch).GetMethod(
                    "BorrowScanMemory",
                    BindingFlags.Static | BindingFlags.NonPublic);
            if (borrow == null)
            {
                throw new MissingMethodException(
                    "Early scan-buffer borrow helper is unavailable");
            }

            int match = -1;
            int matches = 0;
            for (int index = 1; index + 2 < rewritten.Count; index++)
            {
                if (!IsLoadArgumentAddress(rewritten[index - 1])
                    || !IsReadOnlySpanToArray(rewritten[index])
                    || !IsByteArrayAsMemory(rewritten[index + 1])
                    || !IsMemoryToReadOnlyMemory(rewritten[index + 2]))
                {
                    continue;
                }
                match = index;
                matches++;
            }
            if (matches != 1)
            {
                throw new InvalidDataException(
                    "Pinned HookTransaction conversion sequence matched "
                    + matches.ToString()
                    + " times instead of exactly once");
            }

            rewritten[match].opcode = OpCodes.Call;
            rewritten[match].operand = borrow;
            rewritten[match + 1].opcode = OpCodes.Nop;
            rewritten[match + 1].operand = null;
            rewritten[match + 2].opcode = OpCodes.Nop;
            rewritten[match + 2].operand = null;
            return rewritten;
        }

        private static void SpanConstructorPrefix(
            out ScriptExtenderScanBufferInvocationFrame<
                UnmanagedSnapshotMemoryManager> __state)
        {
            __state = LeaseMachine.Push(
                ref _constructorFrame);
            Interlocked.Increment(ref _constructorInvocations);
        }

        private static void SpanConstructorPostfix(
            object __instance,
            ScriptExtenderScanBufferInvocationFrame<
                UnmanagedSnapshotMemoryManager> __state)
        {
            PopConstructorFrame(__state);
            UnmanagedSnapshotMemoryManager manager = __state.Lease;
            if (manager == null)
            {
                return;
            }

            lock (Gate)
            {
                if (!manager.Leased
                    || manager.Owner != null
                    || __instance == null
                    || LeaseMachine.ContainsActiveLease(manager))
                {
                    throw new InvalidDataException(
                        "Scan snapshot lease ownership changed");
                }
                LeaseMachine.Bind(__state, __instance);
                manager.Owner = __instance;
            }
        }

        private static Exception SpanConstructorFinalizer(
            object __instance,
            ScriptExtenderScanBufferInvocationFrame<
                UnmanagedSnapshotMemoryManager> __state,
            Exception __exception)
        {
            try
            {
                if (__state != null && !__state.Closed)
                {
                    PopConstructorFrame(__state);
                }
                if (__exception == null)
                {
                    lock (Gate)
                    {
                        LeaseMachine.CompleteFrame(__state);
                    }
                    return null;
                }
                AbortConstructorLease(__state, __instance);
            }
            catch (Exception exception)
            {
                // The constructor's own failure remains authoritative. If an
                // ownership proof changed, keep the allocation resident rather
                // than risk freeing memory referenced by another invocation.
                Emit(
                    _warning,
                    "SEDE_EARLY_V1|event=scan_buffer_ctor_cleanup"
                    + "|status=retained"
                    + "|reason=" + Token(exception.GetType().Name));
                if (__exception == null)
                {
                    return exception;
                }
            }
            return __exception;
        }

        private static void PopConstructorFrame(
            ScriptExtenderScanBufferInvocationFrame<
                UnmanagedSnapshotMemoryManager> frame)
        {
            LeaseMachine.Pop(
                ref _constructorFrame,
                frame);
            if (Interlocked.Decrement(ref _constructorInvocations) < 0)
            {
                Interlocked.Exchange(ref _constructorInvocations, 0);
                throw new InvalidDataException(
                    "Constructor invocation count became negative");
            }
        }

        private static void AbortConstructorLease(
            ScriptExtenderScanBufferInvocationFrame<
                UnmanagedSnapshotMemoryManager> frame,
            object instance)
        {
            if (frame == null)
            {
                return;
            }
            lock (Gate)
            {
                LeaseMachine.AbortFrame(
                    frame,
                    instance,
                    ClearTransactionMemoryReference,
                    ReleaseLeaseUnderLock);
            }
        }

        private static Exception CommitFinalizer(
            object __instance,
            Exception __exception)
        {
            try
            {
                ReleaseCommittedLease(
                    __instance,
                    __exception == null);
            }
            catch (Exception exception)
            {
                // Never replace Zhuqiaomon's own exception or change a
                // successful Commit into a failure. A lease that could not be
                // verified stays resident and is never reused.
                Emit(
                    _warning,
                    "SEDE_EARLY_V1|event=scan_buffer_lease"
                    + "|status=retained"
                    + "|reason=" + Token(exception.GetType().Name));
            }
            return __exception;
        }

        private static void ReleaseCommittedLease(
            object transaction,
            bool commitSucceeded)
        {
            lock (Gate)
            {
                LeaseMachine.Commit(
                    transaction,
                    commitSucceeded,
                    ClearTransactionMemoryReference,
                    ReleaseLeaseUnderLock);
            }
        }

        private static void ClearTransactionMemoryReference(object transaction)
        {
            if (transaction == null || _transactionMemoryField == null)
            {
                throw new InvalidDataException(
                    "Scan snapshot memory field is unavailable");
            }
            _transactionMemoryField.SetValue(
                transaction,
                default(ReadOnlyMemory<byte>));
            object boxed = _transactionMemoryField.GetValue(transaction);
            if (!(boxed is ReadOnlyMemory<byte>)
                || !((ReadOnlyMemory<byte>)boxed).IsEmpty)
            {
                throw new InvalidDataException(
                    "Scan snapshot reference was not cleared");
            }
        }

        private static void ReleaseLeaseUnderLock(
            UnmanagedSnapshotMemoryManager manager,
            object owner,
            bool forceFree)
        {
            if (manager == null
                || !manager.Leased
                || manager.Released
                || !ReferenceEquals(manager.Owner, owner)
                || !ScratchPool.Contains(manager))
            {
                throw new InvalidDataException(
                    "Scan snapshot lease release contract changed");
            }
            manager.Owner = null;
            manager.Leased = false;
            if (forceFree || Volatile.Read(ref _startupDisposition) != 0)
            {
                ScratchPool.Remove(manager);
                manager.ReleaseAllocation();
            }
        }

        private static bool IsLoadArgumentAddress(CodeInstruction instruction)
        {
            return instruction.opcode == OpCodes.Ldarga
                || instruction.opcode == OpCodes.Ldarga_S;
        }

        private static bool IsReadOnlySpanToArray(CodeInstruction instruction)
        {
            MethodInfo method = instruction.operand as MethodInfo;
            return instruction.opcode == OpCodes.Call
                && method != null
                && string.Equals(method.Name, "ToArray", StringComparison.Ordinal)
                && IsClosedByteGeneric(method.DeclaringType, "System.ReadOnlySpan`1")
                && method.GetParameters().Length == 0
                && method.ReturnType == typeof(byte[]);
        }

        private static bool IsByteArrayAsMemory(CodeInstruction instruction)
        {
            MethodInfo method = instruction.operand as MethodInfo;
            if (instruction.opcode != OpCodes.Call
                || method == null
                || !string.Equals(method.Name, "AsMemory", StringComparison.Ordinal)
                || !string.Equals(
                    method.DeclaringType == null
                        ? string.Empty
                        : method.DeclaringType.FullName,
                    "System.MemoryExtensions",
                    StringComparison.Ordinal))
            {
                return false;
            }
            ParameterInfo[] parameters = method.GetParameters();
            return parameters.Length == 1
                && parameters[0].ParameterType == typeof(byte[])
                && IsClosedByteGeneric(method.ReturnType, "System.Memory`1");
        }

        private static bool IsMemoryToReadOnlyMemory(
            CodeInstruction instruction)
        {
            MethodInfo method = instruction.operand as MethodInfo;
            if (instruction.opcode != OpCodes.Call
                || method == null
                || !string.Equals(
                    method.Name,
                    "op_Implicit",
                    StringComparison.Ordinal)
                || !IsClosedByteGeneric(
                    method.DeclaringType,
                    "System.Memory`1")
                || !IsClosedByteGeneric(
                    method.ReturnType,
                    "System.ReadOnlyMemory`1"))
            {
                return false;
            }
            ParameterInfo[] parameters = method.GetParameters();
            return parameters.Length == 1
                && IsClosedByteGeneric(
                    parameters[0].ParameterType,
                    "System.Memory`1");
        }

        private static bool IsClosedByteGeneric(Type type, string definition)
        {
            return type != null
                && type.IsGenericType
                && string.Equals(
                    type.GetGenericTypeDefinition().FullName,
                    definition,
                    StringComparison.Ordinal)
                && type.GetGenericArguments().Length == 1
                && type.GetGenericArguments()[0] == typeof(byte);
        }

        private static unsafe ReadOnlyMemory<byte> BorrowScanMemory(
            ref ReadOnlySpan<byte> memory)
        {
            try
            {
                if (memory.Length == ExpectedModuleBytes)
                {
                    fixed (byte* source = memory)
                    {
                        IntPtr module = GetModuleHandleW(GameModuleName);
                        if (module != IntPtr.Zero
                            && source == (byte*)module.ToPointer())
                        {
                            ScriptExtenderScanBufferInvocationFrame<
                                UnmanagedSnapshotMemoryManager> frame =
                                    _constructorFrame;
                            if (frame == null || frame.Closed)
                            {
                                throw new InvalidOperationException(
                                    "Native scan has no constructor frame");
                            }
                            UnmanagedSnapshotMemoryManager manager;
                            lock (Gate)
                            {
                                manager = AcquireScratchUnderLock();
                                try
                                {
                                    memory.CopyTo(manager.GetSpan());
                                    LeaseMachine.AttachLease(frame, manager);
                                }
                                catch
                                {
                                    ReleaseProvablyUnownedScratchUnderLock(
                                        manager);
                                    throw;
                                }
                            }
                            Interlocked.Increment(
                                ref _nativeTransactions);
                            return manager.Memory;
                        }

                        byte[] snapshot = GetAttestedLibrarySnapshot();
                        if (snapshot != null)
                        {
                            fixed (byte* snapshotPointer = snapshot)
                            {
                                if (source == snapshotPointer)
                                {
                                    Interlocked.Increment(
                                        ref _snapshotTransactions);
                                    return new ReadOnlyMemory<byte>(snapshot);
                                }
                            }
                        }
                    }
                }
            }
            catch (Exception exception)
            {
                Emit(
                    _warning,
                    "SEDE_EARLY_V1|event=scan_buffer_borrow"
                    + "|status=fallback_copy"
                    + "|reason=" + Token(exception.GetType().Name));
            }

            Interlocked.Increment(ref _fallbackTransactions);
            return new ReadOnlyMemory<byte>(memory.ToArray());
        }

        private static UnmanagedSnapshotMemoryManager AcquireScratchUnderLock()
        {
            foreach (UnmanagedSnapshotMemoryManager candidate in ScratchPool)
            {
                if (!candidate.Leased && !candidate.Released)
                {
                    candidate.Leased = true;
                    return candidate;
                }
            }

            var created = new UnmanagedSnapshotMemoryManager(
                ExpectedModuleBytes);
            created.Leased = true;
            ScratchPool.Add(created);
            return created;
        }

        private static void TrimProvablyFreeScratchUnderLock()
        {
            ScriptExtenderScanBufferScratchSweep<
                UnmanagedSnapshotMemoryManager>.ReleaseProvablyFree(
                    ScratchPool,
                    manager => manager.Leased,
                    manager => manager.Owner != null,
                    manager => LeaseMachine.ContainsActiveLease(manager),
                    manager => manager.ReleaseAllocation());
        }

        private static void AbortStartupUnderLock()
        {
            Volatile.Write(ref _startupDisposition, -1);
            TrimProvablyFreeScratchUnderLock();
        }

        private static void ReleaseProvablyUnownedScratchUnderLock(
            UnmanagedSnapshotMemoryManager manager)
        {
            if (manager == null
                || !manager.Leased
                || manager.Owner != null
                || LeaseMachine.ContainsActiveLease(manager)
                || !ScratchPool.Contains(manager))
            {
                throw new InvalidDataException(
                    "Scratch allocation is not provably unowned");
            }
            manager.Leased = false;
            ScratchPool.Remove(manager);
            manager.ReleaseAllocation();
        }

        private static bool StartupOwnershipMatchesTopologyUnderLock(
            int expectedActiveLeases)
        {
            if (LeaseMachine.ActiveCount != expectedActiveLeases)
            {
                return false;
            }
            if (!LeaseMachine.AllActive(
                delegate(
                    object owner,
                    UnmanagedSnapshotMemoryManager manager)
                {
                    return owner != null
                        && manager != null
                        && ScratchPool.Contains(manager)
                        && manager.Leased
                        && !manager.Released
                        && ReferenceEquals(manager.Owner, owner);
                }))
            {
                return false;
            }
            foreach (UnmanagedSnapshotMemoryManager manager in ScratchPool)
            {
                if (manager == null)
                {
                    return false;
                }
                bool activelyOwned =
                    LeaseMachine.ContainsActiveLease(manager);
                if (manager.Released
                    || manager.Leased != activelyOwned
                    || (!activelyOwned && manager.Owner != null))
                {
                    return false;
                }
            }
            return true;
        }

        private static byte[] GetAttestedLibrarySnapshot()
        {
            lock (Gate)
            {
                if (_snapshotField == null || _crusaderLibrary == null)
                {
                    Assembly shcdese = FindUniqueLoadedAssembly("SHCDESE");
                    if (shcdese == null)
                    {
                        return null;
                    }
                    RuntimeBuildGuard.VerifyEarlyLoadedAssembly(
                        shcdese,
                        "shcdese");
                    Type libraryType = shcdese.GetType(
                        CrusaderLibraryTypeName,
                        true,
                        false);
                    PropertyInfo instanceProperty = libraryType.GetProperty(
                        "Instance",
                        BindingFlags.Static | BindingFlags.Public);
                    FieldInfo snapshotField = libraryType.GetField(
                        "LibrarySnapshot",
                        BindingFlags.Instance | BindingFlags.NonPublic);
                    if (instanceProperty == null
                        || instanceProperty.PropertyType != libraryType
                        || snapshotField == null
                        || snapshotField.FieldType != typeof(byte[]))
                    {
                        throw new InvalidDataException(
                            "Pinned CrusaderLibrary snapshot contract changed");
                    }
                    object library = instanceProperty.GetValue(null, null);
                    if (library == null)
                    {
                        throw new InvalidOperationException(
                            "CrusaderLibrary instance is unavailable");
                    }
                    _snapshotField = snapshotField;
                    _crusaderLibrary = library;
                }

                byte[] snapshot =
                    _snapshotField.GetValue(_crusaderLibrary) as byte[];
                if (snapshot == null
                    || snapshot.Length != ExpectedModuleBytes)
                {
                    return null;
                }
                return snapshot;
            }
        }

        private static ConstructorInfo RequireSpanConstructor(
            Assembly zhuqiaomon)
        {
            Type transaction = zhuqiaomon.GetType(
                TransactionTypeName,
                true,
                false);
            ConstructorInfo match = null;
            foreach (ConstructorInfo candidate in transaction.GetConstructors(
                BindingFlags.Instance | BindingFlags.Public))
            {
                ParameterInfo[] parameters = candidate.GetParameters();
                if (parameters.Length != 4
                    || parameters[0].ParameterType
                        != typeof(ReadOnlySpan<byte>)
                    || parameters[1].ParameterType != typeof(ulong)
                    || !string.Equals(
                        parameters[2].ParameterType.FullName,
                        "Microsoft.Extensions.Logging.ILoggerFactory",
                        StringComparison.Ordinal)
                    || !string.Equals(
                        parameters[3].ParameterType.FullName,
                        "Zhuqiaomon.Hooks.Transaction.TransactionFailureMode",
                        StringComparison.Ordinal))
                {
                    continue;
                }
                if (match != null)
                {
                    throw new AmbiguousMatchException(
                        "Multiple pinned HookTransaction span constructors found");
                }
                match = candidate;
            }
            if (match == null)
            {
                throw new MissingMethodException(
                    "Pinned HookTransaction span constructor is unavailable");
            }
            return match;
        }

        private static MethodInfo RequireCommitMethod(Type transaction)
        {
            MethodInfo match = null;
            foreach (MethodInfo candidate in transaction.GetMethods(
                BindingFlags.Instance | BindingFlags.Public))
            {
                if (!string.Equals(
                        candidate.Name,
                        "Commit",
                        StringComparison.Ordinal)
                    || candidate.ReturnType != typeof(void)
                    || candidate.GetParameters().Length != 0)
                {
                    continue;
                }
                if (match != null)
                {
                    throw new AmbiguousMatchException(
                        "Multiple pinned HookTransaction Commit methods found");
                }
                match = candidate;
            }
            if (match == null)
            {
                throw new MissingMethodException(
                    "Pinned HookTransaction Commit method is unavailable");
            }
            return match;
        }

        private static Assembly FindOrLoadUniqueAssembly(
            string assemblyName,
            string exactPath)
        {
            Assembly match = FindUniqueLoadedAssembly(assemblyName);
            if (match != null)
            {
                return match;
            }
            return Assembly.LoadFrom(exactPath);
        }

        private static Assembly FindUniqueLoadedAssembly(string assemblyName)
        {
            Assembly match = null;
            foreach (Assembly candidate in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (!string.Equals(
                    candidate.GetName().Name,
                    assemblyName,
                    StringComparison.Ordinal))
                {
                    continue;
                }
                if (match != null && !ReferenceEquals(match, candidate))
                {
                    throw new InvalidDataException(
                        "Multiple loaded assemblies named " + assemblyName);
                }
                match = candidate;
            }
            return match;
        }

        private static string Token(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "unknown";
            }
            return value.Replace('|', '_').Replace('=', '_');
        }

        private static void Emit(Action<string> sink, string message)
        {
            if (sink != null)
            {
                sink(message);
            }
        }

        [DllImport(
            "kernel32.dll",
            EntryPoint = "GetModuleHandleW",
            CharSet = CharSet.Unicode,
            SetLastError = true)]
        private static extern IntPtr GetModuleHandleW(string moduleName);

        private sealed unsafe class UnmanagedSnapshotMemoryManager
            : MemoryManager<byte>
        {
            private IntPtr _allocation;
            private readonly int _length;

            internal bool Leased;
            internal object Owner;

            internal UnmanagedSnapshotMemoryManager(int length)
            {
                if (length != ExpectedModuleBytes)
                {
                    throw new ArgumentOutOfRangeException("length");
                }
                IntPtr allocation = Marshal.AllocHGlobal(length);
                if (allocation == IntPtr.Zero)
                {
                    throw new OutOfMemoryException(
                        "Unable to reserve the scan snapshot buffer");
                }
                _allocation = allocation;
                _length = length;
            }

            internal bool Released => _allocation == IntPtr.Zero;

            public override Span<byte> GetSpan()
            {
                IntPtr allocation = _allocation;
                if (allocation == IntPtr.Zero)
                {
                    throw new ObjectDisposedException(
                        "UnmanagedSnapshotMemoryManager");
                }
                return new Span<byte>(allocation.ToPointer(), _length);
            }

            public override MemoryHandle Pin(int elementIndex = 0)
            {
                if ((uint)elementIndex > (uint)_length)
                {
                    throw new ArgumentOutOfRangeException("elementIndex");
                }
                IntPtr allocation = _allocation;
                if (allocation == IntPtr.Zero)
                {
                    throw new ObjectDisposedException(
                        "UnmanagedSnapshotMemoryManager");
                }
                return new MemoryHandle(
                    (byte*)allocation.ToPointer() + elementIndex);
            }

            public override void Unpin()
            {
            }

            protected override void Dispose(bool disposing)
            {
                ReleaseAllocation();
            }

            internal void ReleaseAllocation()
            {
                IntPtr allocation = Interlocked.Exchange(
                    ref _allocation,
                    IntPtr.Zero);
                if (allocation != IntPtr.Zero)
                {
                    Marshal.FreeHGlobal(allocation);
                }
            }
        }

    }
}
