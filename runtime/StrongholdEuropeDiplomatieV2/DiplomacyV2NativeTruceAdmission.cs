using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using SHCDESE.API.LowLevel;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        // RedBird is resolved only after the exact engine image has matched.
        // The main plugin therefore remains loadable with other SE versions.
        private const string TruceEngineSha256 =
            "1e6d4c2e10cc35a7b8082a7e2bcd8bb20680ebeda803d9b943257b948145cb2b";
        private const int TrucePairFilterRva = 0x186700;
        // Exact pinned engine unwind range [0x186700, 0x186915). The
        // corresponding PE range has no base relocations.
        private const int TrucePairFilterBodyLength = 0x215;
        private const string TrucePairFilterBodySha256 =
            "532d42df8531f62f5d9f638969f557bd5927346a332ea8d46b78c7173f3573e5";
        private const int NativeUnitStride = 0x490;
        private const int NativeUnitArrayOffset = 0x65c;
        private const int MaximumNativeUnitId = 9999;
        private static readonly byte[] TrucePairFilterEntry = {
            0x48, 0x89, 0x5c, 0x24, 0x08, 0x48, 0x63, 0xc2,
            0x48, 0x8b, 0xd9, 0x4c, 0x69, 0xd8, 0x90, 0x04,
            0x00, 0x00, 0x4c, 0x03, 0xd9, 0x45, 0x0f, 0xb7
        };
        // Gate only this optional detour on the loaded hook implementation.
        // Identical RedBird binaries may be used by a later SE release;
        // the rest of DIPLOMACY has no SE-version gate here.
        private static readonly string[] TruceHookAssemblyNames = {
            "RedBird.Abstractions", "RedBird.Backends.NativeX64",
            "RedBird.Core", "RedBird.X64", "Iced"
        };
        private static readonly string[] TruceHookAssemblySha256 = {
            "339cece116f66f59ecc7da5e9a5c0b2dfe24f4e7a5e7efc005864fa77c027a1e",
            "0843dd4c381a3e77dd6d8b51d5ccf95465b3fb49bfdf2980f39a212d774aadb0",
            "ee4b036c486077f7d8898ae054f124edde73e6ae1a059e8991c361e2b720d29f",
            "e085b83b2b87b5d2142c980090d8d9ec616a90a443bd125c17b41e0bb47a44eb",
            "cc915d1c2e7be60933c5b129842ca3d08d1fe3cda6c6d6ade8824dcdde16191f"
        };

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        [SuppressUnmanagedCodeSecurity]
        private delegate int NativeTrucePairFilter(
            IntPtr unitManager, int attackerId, int targetId, byte mode);

        // A retired stub may reach its callback after a new map has installed
        // another detour. Original must therefore belong to this hook instance,
        // never to a replaceable field on DiplomacyFeature.
        private sealed class NativeTruceDetourState
        {
            private readonly DiplomacyFeature _owner;
            internal NativeTrucePairFilter Original;
            internal int Active;

            internal NativeTruceDetourState(DiplomacyFeature owner)
            {
                _owner = owner;
            }

            internal int Invoke(IntPtr manager, int attackerId, int targetId,
                byte mode)
            {
                return _owner.NativeTrucePairFilterCallback(this, manager,
                    attackerId, targetId, mode);
            }
        }

        private sealed class NativeTruceRetirement
        {
            internal readonly WeakReference Identity;
            internal object Transaction;
            internal readonly NativeTrucePairFilter Callback;
            internal readonly NativeTrucePairFilter Original;

            internal NativeTruceRetirement(object transaction,
                NativeTrucePairFilter callback, NativeTrucePairFilter original)
            {
                Identity = new WeakReference(transaction);
                Transaction = transaction;
                Callback = callback;
                Original = original;
            }
        }

        private static readonly object RetiredNativeTruceGate = new object();
        private static readonly List<NativeTruceRetirement> RetiredNativeTruceTransactions =
            new List<NativeTruceRetirement>();

        // LibraryLoaded may invoke a late subscriber synchronously. Installation
        // and rollback must be one lifecycle transaction, while the native
        // callback itself never enters this monitor.
        private readonly object _nativeTruceLifecycleGate = new object();
        private bool _nativeTruceSubscribed;
        private object _nativeTruceTransaction;
        private IntPtr _nativeTruceEntryAddress;
        private NativeTruceDetourState _nativeTruceState;
        private NativeTrucePairFilter _nativeTruceCallback;
        private int _nativeTruceActive;
        private int _nativeTruceCalls;
        private int _nativeTruceBlocks;
        private int _nativeTruceReportedCalls;
        private int _nativeTruceReportedBlocks;

        private void ApplyNativeTruceAdmission()
        {
            lock (_nativeTruceLifecycleGate)
            {
                if (_nativeTruceSubscribed) return;
                _nativeTruceSubscribed = true;
                try
                {
                    // A late subscriber is invoked synchronously by SE. The
                    // monitor is reentrant on that same thread; a concurrent
                    // rollback waits until installation has finished.
                    CrusaderLibrary.Instance.LibraryLoaded += OnNativeTruceLibraryLoaded;
                }
                catch (Exception exception)
                {
                    _nativeTruceSubscribed = false;
                    Log("visible_truce", "status=unavailable|reason="
                        + exception.GetType().Name);
                }
            }
        }

        private void OnNativeTruceLibraryLoaded(CrusaderLibraryLoadContext context)
        {
            lock (_nativeTruceLifecycleGate)
            {
                if (!_nativeTruceSubscribed) return;
                OnNativeTruceLibraryLoadedSerialized(context);
            }
        }

        private void OnNativeTruceLibraryLoadedSerialized(
            CrusaderLibraryLoadContext context)
        {
            try
            {
                // A library notification can be repeated across map lifecycles.
                // Never overwrite the transaction that owns a live detour.
                if (_nativeTruceTransaction != null) return;
                string reason;
                if (!PinnedTruceImageMatches(context, out reason)
                    || !PinnedTruceHookRuntimeMatches(out reason))
                {
                    Log("visible_truce", "status=unavailable|reason=" + reason);
                    return;
                }
                object transaction = CreateNativeTruceTransaction(context);
                IntPtr entryAddress = IntPtr.Add(context.ModuleHandle,
                    TrucePairFilterRva);
                var detourState = new NativeTruceDetourState(this);
                _nativeTruceState = detourState;
                try
                {
                    Assembly abstractions = Assembly.Load("RedBird.Abstractions");
                    Type handleType = RequireType(abstractions,
                        "RedBird.Abstractions.Hooks.Transaction.DetourHandle`1")
                        .MakeGenericType(typeof(NativeTrucePairFilter));
                    object handle = Activator.CreateInstance(handleType);
                    Type targetType = RequireType(abstractions,
                        "RedBird.Abstractions.Hooks.HookTarget");
                    object target = targetType.GetMethod("FromRva",
                        BindingFlags.Public | BindingFlags.Static,
                        null, new[] { typeof(ulong), typeof(int) }, null)
                        .Invoke(null, new object[] { (ulong)TrucePairFilterRva, 0 });
                    NativeTrucePairFilter callback = detourState.Invoke;
                    _nativeTruceCallback = callback;
                    MethodInfo add = transaction.GetType().GetMethods()
                        .Single(method => method.Name == "AddDetour"
                            && method.IsGenericMethodDefinition
                            && method.GetParameters().Length == 4
                            && method.GetParameters()[0].ParameterType.IsGenericType);
                    add.MakeGenericMethod(typeof(NativeTrucePairFilter))
                        .Invoke(transaction, new object[] {
                            handle, target, callback, "diplomacy_truce_pair_filter" });
                    object result = transaction.GetType().GetMethod("Commit",
                        Type.EmptyTypes).Invoke(transaction, null);
                    if (!(bool)result.GetType().GetProperty("IsCompleteSuccess")
                        .GetValue(result, null))
                        throw new InvalidOperationException("detour commit incomplete");
                    NativeTrucePairFilter original = handleType
                        .GetProperty("Original").GetValue(handle, null)
                        as NativeTrucePairFilter;
                    if (original == null)
                        throw new InvalidOperationException("detour trampoline unavailable");
                    Volatile.Write(ref detourState.Original, original);
                    // Commit only prepares and publishes the trampoline. The
                    // callback can be entered only after Original is ready.
                    if (!TrucePairFilterBodyMatches(entryAddress))
                        throw new InvalidOperationException("body changed before enable");
                    object hook = ((System.Collections.IEnumerable)
                        transaction.GetType().GetProperty("Hooks")
                            .GetValue(transaction, null)).Cast<object>().Single();
                    hook.GetType().GetMethod("Enable", Type.EmptyTypes)
                        .Invoke(hook, null);
                    if (!(bool)hook.GetType().GetProperty("IsInstalled")
                        .GetValue(hook, null))
                        throw new InvalidOperationException("detour not installed");
                    _nativeTruceTransaction = transaction;
                    _nativeTruceEntryAddress = entryAddress;
                    Volatile.Write(ref detourState.Active, 1);
                    Volatile.Write(ref _nativeTruceActive, 1);
                    Log("visible_truce", "status=pair_filter_active|engine=1e6d4c2e");
                }
                catch
                {
                    Volatile.Write(ref detourState.Active, 0);
                    Volatile.Write(ref _nativeTruceActive, 0);
                    // A partially committed detour must keep its callback and
                    // trampoline rooted if rollback itself fails.
                    try
                    {
                        DisableNativeTruceTransaction(transaction, entryAddress,
                            _nativeTruceCallback, detourState.Original);
                        _nativeTruceCallback = null;
                        _nativeTruceState = null;
                        _nativeTruceTransaction = null;
                        _nativeTruceEntryAddress = IntPtr.Zero;
                    }
                    catch (Exception rollbackError)
                    {
                        _nativeTruceTransaction = transaction;
                        _nativeTruceEntryAddress = entryAddress;
                        Log("visible_truce", "status=rollback_failed|reason="
                            + rollbackError.GetType().Name);
                    }
                    throw;
                }
            }
            catch (Exception exception)
            {
                Log("visible_truce", "status=unavailable|reason="
                    + exception.GetType().Name);
            }
        }

        private static object CreateNativeTruceTransaction(
            CrusaderLibraryLoadContext context)
        {
            Assembly abstractions = Assembly.Load("RedBird.Abstractions");
            Assembly native = Assembly.Load("RedBird.Backends.NativeX64");
            Assembly x64 = Assembly.Load("RedBird.X64");
            Type nativeOptionsType = RequireType(native,
                "RedBird.Backends.NativeX64.NativeDetourOptions");
            object nativeOptions = Activator.CreateInstance(nativeOptionsType);
            nativeOptionsType.GetProperty("SuspendThreadsDuringPatch")
                .SetValue(nativeOptions, true, null);
            nativeOptionsType.GetProperty("SafeUnhook")
                .SetValue(nativeOptions, true, null);
            Type nativeBackendType = RequireType(native,
                "RedBird.Backends.NativeX64.NativeDetourBackend");
            object backend = Activator.CreateInstance(nativeBackendType,
                new[] { nativeOptions });
            Type transactionOptionsType = RequireType(x64,
                "RedBird.X64.Hooks.Transaction.HookTransactionOptions");
            object options = Activator.CreateInstance(transactionOptionsType);
            Type failureType = RequireType(abstractions,
                "RedBird.Abstractions.Hooks.Transaction.TransactionFailureMode");
            transactionOptionsType.GetProperty("FailureMode").SetValue(options,
                Enum.Parse(failureType, "RollbackAndThrow"), null);
            transactionOptionsType.GetProperty("Backend").SetValue(options,
                backend, null);
            transactionOptionsType.GetProperty("InstallOnCommit").SetValue(
                options, false, null);
            transactionOptionsType.GetProperty("OwnsHooks").SetValue(
                options, true, null);

            // Avoid a static dependency on ScanRegion and ILoggerFactory.
            object region = context.GetType().GetProperty("Region")
                .GetValue(context, null);
            Type pluginType = typeof(CrusaderLibrary).Assembly.GetType(
                "SHCDESE.BepInEx.Bootstrap.Plugin", true);
            object plugin = pluginType.GetField("Instance",
                BindingFlags.Public | BindingFlags.Static).GetValue(null);
            object loggerFactory = pluginType.GetField("LoggerFactory",
                BindingFlags.Public | BindingFlags.Instance).GetValue(plugin);
            Type transactionType = RequireType(x64,
                "RedBird.X64.Hooks.Transaction.HookTransaction");
            return Activator.CreateInstance(transactionType,
                new[] { region, loggerFactory, options, "DIPLOMACY visible truce" });
        }

        private static Type RequireType(Assembly assembly, string name)
        {
            Type result = assembly.GetType(name, false);
            if (result == null) throw new TypeLoadException(name);
            return result;
        }

        private static bool PinnedTruceImageMatches(
            CrusaderLibraryLoadContext context, out string reason)
        {
            reason = "image_unknown";
            if (context == null || context.ModuleHandle == IntPtr.Zero)
                return false;
            var path = new StringBuilder(32768);
            uint length = GetModuleFileName(context.ModuleHandle, path,
                (uint)path.Capacity);
            if (length == 0 || length >= path.Capacity || !File.Exists(path.ToString()))
                return false;
            using (var stream = File.OpenRead(path.ToString()))
            using (var sha = SHA256.Create())
            {
                string actual = BitConverter.ToString(sha.ComputeHash(stream))
                    .Replace("-", "").ToLowerInvariant();
                if (!string.Equals(actual, TruceEngineSha256,
                    StringComparison.Ordinal))
                {
                    reason = "image_unverified";
                    return false;
                }
            }
            IntPtr entryAddress = IntPtr.Add(context.ModuleHandle,
                TrucePairFilterRva);
            if (!TrucePairFilterBytesMatch(entryAddress))
            {
                reason = "entry_already_modified";
                return false;
            }
            if (!TrucePairFilterBodyMatches(entryAddress))
            {
                reason = "body_already_modified";
                return false;
            }
            reason = null;
            return true;
        }

        private static bool PinnedTruceHookRuntimeMatches(out string reason)
        {
            reason = "hook_runtime_unverified";
            for (int i = 0; i < TruceHookAssemblyNames.Length; i++)
            {
                try
                {
                    Assembly assembly = Assembly.Load(TruceHookAssemblyNames[i]);
                    string path = assembly.Location;
                    if (string.IsNullOrEmpty(path) || !File.Exists(path)) return false;
                    using (var stream = File.OpenRead(path))
                    using (var sha = SHA256.Create())
                    {
                        string actual = BitConverter.ToString(sha.ComputeHash(stream))
                            .Replace("-", "").ToLowerInvariant();
                        if (!string.Equals(actual, TruceHookAssemblySha256[i],
                            StringComparison.Ordinal)) return false;
                    }
                }
                catch { return false; }
            }
            reason = null;
            return true;
        }

        private static bool TrucePairFilterBytesMatch(IntPtr entryAddress)
        {
            byte[] entry = new byte[TrucePairFilterEntry.Length];
            Marshal.Copy(entryAddress, entry, 0, entry.Length);
            for (int i = 0; i < entry.Length; i++)
            {
                if (entry[i] == TrucePairFilterEntry[i]) continue;
                return false;
            }
            return true;
        }

        private static bool TrucePairFilterBodyMatches(IntPtr entryAddress)
        {
            return TrucePairFilterBodyMatches(entryAddress,
                TrucePairFilterBodyLength, TrucePairFilterBodySha256);
        }

        private static bool TrucePairFilterBodyMatches(
            IntPtr entryAddress, int length, string expectedSha256)
        {
            if (entryAddress == IntPtr.Zero || length <= 0
                || string.IsNullOrEmpty(expectedSha256)) return false;
            byte[] body = new byte[length];
            Marshal.Copy(entryAddress, body, 0, body.Length);
            using (var sha = SHA256.Create())
            {
                string actual = BitConverter.ToString(sha.ComputeHash(body))
                    .Replace("-", "").ToLowerInvariant();
                return string.Equals(actual, expectedSha256,
                    StringComparison.Ordinal);
            }
        }

        private unsafe int NativeTrucePairFilterCallback(
            NativeTruceDetourState detourState, IntPtr manager,
            int attackerId, int targetId, byte mode)
        {
            Interlocked.Increment(ref _nativeTruceCalls);
            NativeTrucePairFilter original = detourState == null ? null
                : Volatile.Read(ref detourState.Original);
            if (original == null) return 1;
            try
            {
                CombatProtectionSnapshot snapshot = Volatile.Read(
                    ref _combatProtectionSnapshot);
                if (Volatile.Read(ref detourState.Active) != 0
                    && Volatile.Read(ref _nativeTruceActive) != 0
                    && snapshot != null && snapshot.AnyProtection
                    && snapshot.Session == Volatile.Read(ref _sessionGeneration)
                    && IsNativeDiplomacySectionHeld
                    && manager != IntPtr.Zero
                    && attackerId > 0 && attackerId <= MaximumNativeUnitId
                    && targetId > 0 && targetId <= MaximumNativeUnitId
                    && attackerId != targetId)
                {
                    byte* baseAddress = (byte*)manager + NativeUnitArrayOffset;
                    byte* attacker = baseAddress + attackerId * NativeUnitStride;
                    byte* target = baseAddress + targetId * NativeUnitStride;
                    uint attackerLife = *(uint*)(attacker + 0x94);
                    uint targetLife = *(uint*)(target + 0x94);
                    byte attackerPlayer = *(attacker + 0x92);
                    byte targetPlayer = *(target + 0x92);
                    if (attackerLife != 0 && targetLife != 0
                        && *(short*)(attacker + 0x88) == 2
                        && *(short*)(target + 0x88) == 2
                        && snapshot.Protects(attackerPlayer, targetPlayer)
                        && attackerLife == *(uint*)(attacker + 0x94)
                        && targetLife == *(uint*)(target + 0x94)
                        && attackerPlayer == *(attacker + 0x92)
                        && targetPlayer == *(target + 0x92)
                        && snapshot.Session == Volatile.Read(ref _sessionGeneration)
                        && Volatile.Read(ref detourState.Active) != 0
                        && Volatile.Read(ref _nativeTruceActive) != 0)
                    {
                        Interlocked.Increment(ref _nativeTruceBlocks);
                        return 1;
                    }
                }
            }
            catch
            {
                // A managed exception must never unwind into the engine.
            }
            return original(manager, attackerId, targetId, mode);
        }

        // Called on the managed frame, never from the native detour.
        private void ReportNativeTruceAdmission()
        {
            if (Volatile.Read(ref _nativeTruceActive) == 0) return;
            int calls = Volatile.Read(ref _nativeTruceCalls);
            int blocks = Volatile.Read(ref _nativeTruceBlocks);
            if (_nativeTruceReportedCalls == 0 && calls > 0)
            {
                _nativeTruceReportedCalls = calls;
                Log("visible_truce", "status=pair_filter_observed|calls="
                    + calls.ToString(System.Globalization.CultureInfo.InvariantCulture));
            }
            if (blocks > _nativeTruceReportedBlocks
                && (_nativeTruceReportedBlocks == 0
                    || blocks - _nativeTruceReportedBlocks >= 64))
            {
                _nativeTruceReportedBlocks = blocks;
                Log("visible_truce", "status=protected_pair_rejected|count="
                    + blocks.ToString(System.Globalization.CultureInfo.InvariantCulture));
            }
        }

        private void RollbackNativeTruceAdmission()
        {
            lock (_nativeTruceLifecycleGate)
                RollbackNativeTruceAdmissionSerialized();
        }

        private void RollbackNativeTruceAdmissionSerialized()
        {
            _nativeTruceSubscribed = false;
            Volatile.Write(ref _nativeTruceActive, 0);
            NativeTruceDetourState detourState = _nativeTruceState;
            if (detourState != null) Volatile.Write(ref detourState.Active, 0);
            CrusaderLibrary.Instance.LibraryLoaded -= OnNativeTruceLibraryLoaded;
            object transaction = _nativeTruceTransaction;
            if (transaction == null) return;
            try
            {
                DisableNativeTruceTransaction(transaction,
                    _nativeTruceEntryAddress, _nativeTruceCallback,
                    detourState == null ? null : detourState.Original);
                _nativeTruceTransaction = null;
                _nativeTruceEntryAddress = IntPtr.Zero;
                _nativeTruceState = null;
                _nativeTruceCallback = null;
            }
            catch (Exception exception)
            {
                // Preserve the transaction and delegates: a still-installed
                // callback must continue to reach its original trampoline.
                Log("visible_truce", "status=rollback_failed|reason="
                    + exception.GetType().Name);
            }
        }

        private static void DisableNativeTruceTransaction(
            object transaction, IntPtr entryAddress,
            NativeTrucePairFilter callback, NativeTrucePairFilter original)
        {
            NativeTruceRetirement retirement;
            lock (RetiredNativeTruceGate)
            {
                retirement = RetiredNativeTruceTransactions.Find(item =>
                    ReferenceEquals(item.Identity.Target, transaction));
                if (retirement == null)
                {
                    retirement = new NativeTruceRetirement(transaction, callback, original);
                    RetiredNativeTruceTransactions.Add(retirement);
                }
                // A successful prior call already retired this transaction.
                if (retirement.Transaction == null) return;
            }
            // Root before any fallible unhook work: teardown may discard the
            // owner even if DisableAll, verification or Dispose fails.
            // Dispose only after a confirmed disable. Disposing an active
            // trampoline following a failed unhook would be unsafe.
            transaction.GetType().GetMethod("DisableAll", Type.EmptyTypes)
                .Invoke(transaction, null);
            if (entryAddress == IntPtr.Zero
                || !TrucePairFilterBytesMatch(entryAddress))
                throw new InvalidOperationException("detour bytes not restored");
            // The RedBird binaries shipped with SE 2.10.4 and 2.11.0 restore
            // entry bytes but do not wait for a
            // thread already in the stub before Dispose drops delegate roots.
            // Its trampoline is process-lifetime memory. Keep the two managed
            // thunks alive for that same lifetime, including after disposal.
            ((IDisposable)transaction).Dispose();
            lock (RetiredNativeTruceGate)
                retirement.Transaction = null;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode,
            EntryPoint = "GetModuleFileNameW", SetLastError = true)]
        private static extern uint GetModuleFileName(
            IntPtr module, StringBuilder path, uint capacity);
    }
}
