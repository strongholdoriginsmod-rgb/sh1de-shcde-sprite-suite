using System;
using System.Collections;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// The native transaction in which a worker may borrow a soldier speech
    /// family. The native speech event itself remains selected by Crusader.
    /// </summary>
    internal enum WorkerMilitiaSpeechPurpose
    {
        Selection = 1,
        GroundOrder = 2,
        TargetOrder = 3,
    }

    /// <summary>
    /// Narrow adapter for CrusaderDE.dll's native unit-speech selector.
    /// </summary>
    /// <remarks>
    /// The selector switches on the raw chimp type, not on the command-class
    /// counters used by worker selection. During one proven native input run
    /// this adapter substitutes only that second argument. The context in RCX,
    /// native speech event in R8D and auxiliary value in R9D are forwarded
    /// unchanged, so Crusader still owns its event category, variant rotation,
    /// speech chore, language, volume, pause and mute behavior. This class does
    /// not call a managed sound API.
    /// </remarks>
    internal sealed class WorkerMilitiaSpeechSelector : IDisposable
    {
        // Engine pins come from the running build's layout record (2.7 and
        // 2.80 both: selector at RVA 0x3BC0, .text RVA 0x1000, raw 0x400).
        internal static long PinnedNativeEngineSize
        {
            get { return WorkerMilitiaNativeLayout.Current.EngineSize; }
        }

        internal static string PinnedNativeEngineSha256
        {
            get { return WorkerMilitiaNativeLayout.Current.EngineSha256; }
        }

        internal static int NativeSelectorRva
        {
            get { return WorkerMilitiaNativeLayout.Current.SpeechSelectorRva; }
        }

        private static int NativeSelectorFileOffset
        {
            get { return WorkerMilitiaNativeLayout.Current.SpeechSelectorFileOffset; }
        }
        private const string NativeModuleName = "CrusaderDE.dll";
        private const int WoodcutterType = 3;
        private const int HunterType = 6;
        private const int ArcherDonorType = 22;
        private const int MacemanDonorType = 26;

        // Native selector event 0 is selection. Events 6/9/10 are the three
        // movement acknowledgements. The target-order call sites choose the
        // pinned archer and maceman attack categories below before calling the
        // selector; automatic militia defense must never arm this adapter.
        private const ulong SelectionEvents = 1UL << 0;
        private const ulong GroundOrderEvents =
            (1UL << 6) | (1UL << 9) | (1UL << 10);
        private const ulong HunterTargetOrderEvents =
            (1UL << 16)
            | (1UL << 25)
            | (1UL << 29)
            | (1UL << 30)
            | (1UL << 32);
        private const ulong WoodcutterTargetOrderEvents =
            (1UL << 17) | (1UL << 21);

        // push rbx/rbp/rsi/rdi; sub rsp,0x78; mov rax,[rip+disp32]. The
        // disp32 differs per build (2.7: 0x332748, 2.80: 0x3337D8) and is
        // already covered by the whole-file SHA-256 check, so it is not part
        // of the pin.
        private static readonly byte[] NativeSelectorPrologue =
        {
            0x40, 0x53, 0x55, 0x56, 0x57, 0x48, 0x83, 0xEC,
            0x78, 0x48, 0x8B, 0x05,
        };

        private readonly object _gate = new object();
        private readonly Action<string> _warning;
        private readonly NativeSpeechSelector _detourCallback;

        private HookApi _hookApi;
        private object _transaction;
        private object _selectorHook;
        private NativeSpeechSelector _trampoline;
        private SpeechTokenLease _activeToken;
        private string _nativeEnginePath;
        private IntPtr _nativeModuleBase;
        private string _failure = string.Empty;
        private long _tokenGeneration;
        private int _callbacksInFlight;
        private bool _prepared;
        private bool _applied;
        private bool _disposing;
        private bool _disposed;
        private bool _faulted;
        private bool _warningEmitted;

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        private delegate void NativeSpeechSelector(
            IntPtr speechContext,
            int rawUnitType,
            int speechEvent,
            int auxiliary);

        internal WorkerMilitiaSpeechSelector(Action<string> warning)
        {
            _warning = warning ?? throw new ArgumentNullException("warning");
            _detourCallback = Detour;
        }

        /// <summary>
        /// Must be included in WorkerMilitiaFeature.ExclusiveClaims before
        /// <see cref="Apply"/> is called.
        /// </summary>
        internal static ExtensionLeaseClaim NativeHookClaim
        {
            get
            {
                return ExtensionLeaseClaim.Hook(
                    "CrusaderDE.dll+0x3BC0");
            }
        }

        internal bool IsPrepared
        {
            get
            {
                lock (_gate)
                {
                    return _prepared;
                }
            }
        }

        internal bool IsApplied
        {
            get
            {
                lock (_gate)
                {
                    return _applied;
                }
            }
        }

        internal bool IsFaulted
        {
            get
            {
                lock (_gate)
                {
                    return _faulted;
                }
            }
        }

        internal string Failure
        {
            get
            {
                lock (_gate)
                {
                    return _failure;
                }
            }
        }

        /// <summary>
        /// Resolves the already-loaded canonical module and performs every
        /// read-only build check. No hook is installed here.
        /// </summary>
        internal bool Prepare(string nativeEnginePath, out string failure)
        {
            lock (_gate)
            {
                if (_disposed || _disposing)
                {
                    failure = "native speech selector is disposing or disposed";
                    return false;
                }
                if (_applied)
                {
                    failure = "native speech selector is already applied";
                    return false;
                }
            }

            IntPtr moduleBase;
            string resolveFailure;
            if (!TryResolveModule(
                    nativeEnginePath,
                    out moduleBase,
                    out resolveFailure))
            {
                failure = resolveFailure;
                return RememberPreparationFailure(failure);
            }
            return Prepare(nativeEnginePath, moduleBase, out failure);
        }

        /// <summary>
        /// Testable preparation overload for an explicitly resolved module.
        /// The address must still identify the matching module in this process.
        /// </summary>
        internal bool Prepare(
            string nativeEnginePath,
            IntPtr nativeModuleBase,
            out string failure)
        {
            lock (_gate)
            {
                if (_disposed || _disposing)
                {
                    failure = "native speech selector is disposing or disposed";
                    return false;
                }
                if (_applied)
                {
                    failure = "native speech selector is already applied";
                    return false;
                }
            }

            string fullPath;
            try
            {
                fullPath = Path.GetFullPath(nativeEnginePath);
            }
            catch (Exception exception)
            {
                failure = "native speech selector path is invalid: "
                    + exception.GetType().Name;
                return RememberPreparationFailure(failure);
            }

            if (!VerifyPinnedBuild(
                    fullPath,
                    nativeModuleBase,
                    out failure))
            {
                return RememberPreparationFailure(failure);
            }

            HookApi hookApi;
            if (!HookApi.TryResolve(out hookApi, out failure))
            {
                return RememberPreparationFailure(failure);
            }

            lock (_gate)
            {
                if (_disposed || _disposing || _applied)
                {
                    failure = "native speech selector lifecycle changed during preparation";
                    return false;
                }
                _nativeEnginePath = fullPath;
                _nativeModuleBase = nativeModuleBase;
                _hookApi = hookApi;
                _failure = string.Empty;
                _faulted = false;
                _prepared = true;
                failure = string.Empty;
                return true;
            }
        }

        /// <summary>
        /// Installs the direct-address detour transactionally. Preparation is
        /// repeated immediately before mutation so a stale proof cannot apply.
        /// </summary>
        internal void Apply()
        {
            string path;
            IntPtr moduleBase;
            HookApi hookApi;
            lock (_gate)
            {
                if (_disposed || _disposing)
                {
                    throw new ObjectDisposedException(
                        nameof(WorkerMilitiaSpeechSelector));
                }
                if (_applied)
                {
                    return;
                }
                if (!_prepared || _nativeModuleBase == IntPtr.Zero)
                {
                    throw new InvalidOperationException(
                        "Native speech selector was not prepared");
                }
                path = _nativeEnginePath;
                moduleBase = _nativeModuleBase;
                hookApi = _hookApi;
            }

            string verificationFailure;
            if (!VerifyPinnedBuild(
                    path,
                    moduleBase,
                    out verificationFailure))
            {
                RememberPreparationFailure(verificationFailure);
                throw new InvalidOperationException(verificationFailure);
            }

            object transaction = hookApi.CreateTransaction(
                unchecked((ulong)moduleBase.ToInt64()));
            object hook = hookApi.CreateHookRef();
            try
            {
                ulong address = unchecked((ulong)moduleBase.ToInt64())
                    + (ulong)NativeSelectorRva;
                hookApi.AddDetour(
                    transaction,
                    ref hook,
                    address,
                    _detourCallback);

                // Publish the handle before Commit. Activation occurs on the
                // Unity thread; publishing also guarantees the callback can
                // reach its trampoline if a foreign native thread races it.
                lock (_gate)
                {
                    _selectorHook = hook;
                }
                hookApi.Commit(transaction);

                NativeSpeechSelector trampoline;
                if (!hookApi.TryGetVerifiedTrampoline(
                        hook,
                        out trampoline)
                    || hookApi.ActiveHookCount(transaction) != 1)
                {
                    throw new InvalidOperationException(
                        "Native speech selector detour has no verified trampoline");
                }

                lock (_gate)
                {
                    if (_disposed || _disposing)
                    {
                        throw new ObjectDisposedException(
                            nameof(WorkerMilitiaSpeechSelector));
                    }
                    _transaction = transaction;
                    _selectorHook = hook;
                    _trampoline = trampoline;
                    _failure = string.Empty;
                    _applied = true;
                }
            }
            catch (Exception exception)
            {
                bool disabled = DisableHook(hookApi, transaction, hook);
                if (disabled)
                {
                    DisposeDisabledHook(hookApi, transaction, hook);
                    lock (_gate)
                    {
                        _transaction = null;
                        _selectorHook = null;
                        _trampoline = null;
                        _applied = false;
                        _prepared = false;
                    }
                }
                else
                {
                    // Never discard the only rooted handle to a detour that
                    // could not be removed. Keep it fail-closed and let the
                    // feature host retry Dispose/RollbackOwned.
                    lock (_gate)
                    {
                        _transaction = transaction;
                        _selectorHook = hook;
                        _applied = true;
                        _prepared = false;
                        _faulted = true;
                        _failure = "native speech selector apply rollback failed: "
                            + exception.GetType().Name;
                    }
                    WarnOnce(_failure);
                }
                throw;
            }
        }

        /// <summary>
        /// Arms exactly one selector substitution on the current native thread.
        /// The returned lease belongs in the matching EngineInterface.run
        /// postfix/finalizer and must be disposed even when no selector call was
        /// made. A false result means speech remains completely Vanilla.
        /// </summary>
        internal bool TryArm(
            long leaseGeneration,
            int workerGlobalId,
            long nativeRunGeneration,
            WorkerMilitiaSpeechPurpose purpose,
            int rawWorkerType,
            out SpeechTokenLease lease)
        {
            lease = null;
            ulong allowedEvents = AllowedEvents(purpose, rawWorkerType);
            if (leaseGeneration <= 0L
                || leaseGeneration == long.MaxValue
                || workerGlobalId <= 0
                || nativeRunGeneration <= 0L
                || nativeRunGeneration == long.MaxValue
                || allowedEvents == 0UL
                || DonorType(rawWorkerType) == rawWorkerType)
            {
                return false;
            }

            uint nativeThreadId = GetCurrentThreadId();
            if (nativeThreadId == 0U)
            {
                return false;
            }

            lock (_gate)
            {
                if (!_applied
                    || _faulted
                    || _disposing
                    || _disposed
                    || _activeToken != null
                    || _tokenGeneration == long.MaxValue)
                {
                    return false;
                }

                lease = new SpeechTokenLease(
                    this,
                    ++_tokenGeneration,
                    leaseGeneration,
                    workerGlobalId,
                    nativeRunGeneration,
                    nativeThreadId,
                    purpose,
                    rawWorkerType,
                    allowedEvents);
                _activeToken = lease;
                return true;
            }
        }

        /// <summary>
        /// Emergency/map-teardown clear. Normal run cleanup should dispose the
        /// exact <see cref="SpeechTokenLease"/> so a stale postfix cannot clear
        /// a newer run's token.
        /// </summary>
        internal void Clear()
        {
            SpeechTokenLease cleared;
            lock (_gate)
            {
                cleared = _activeToken;
                _activeToken = null;
            }
            if (cleared != null)
            {
                cleared.MarkCleared();
            }
        }

        internal static bool IsEventAllowed(
            WorkerMilitiaSpeechPurpose purpose,
            int rawWorkerType,
            int speechEvent)
        {
            if (speechEvent < 0 || speechEvent >= 64)
            {
                return false;
            }
            return (AllowedEvents(purpose, rawWorkerType)
                & (1UL << speechEvent)) != 0UL;
        }

        public void Dispose()
        {
            HookApi hookApi;
            object transaction;
            object hook;
            SpeechTokenLease token;
            lock (_gate)
            {
                if (_disposed || _disposing)
                {
                    return;
                }
                _disposing = true;
                token = _activeToken;
                _activeToken = null;
                hookApi = _hookApi;
                transaction = _transaction;
                hook = _selectorHook;
            }
            if (token != null)
            {
                token.MarkCleared();
            }

            bool disabled = DisableHook(hookApi, transaction, hook);
            if (!disabled)
            {
                lock (_gate)
                {
                    _faulted = true;
                    _failure = "native speech selector detour could not be disabled";
                    _disposing = false;
                }
                WarnOnce(_failure);
                return;
            }

            lock (_gate)
            {
                while (_callbacksInFlight != 0)
                {
                    Monitor.Wait(_gate);
                }
            }

            DisposeDisabledHook(hookApi, transaction, hook);
            lock (_gate)
            {
                _hookApi = null;
                _transaction = null;
                _selectorHook = null;
                _trampoline = null;
                _nativeEnginePath = null;
                _nativeModuleBase = IntPtr.Zero;
                _prepared = false;
                _applied = false;
                _disposing = false;
                _disposed = true;
            }
        }

        private void Detour(
            IntPtr speechContext,
            int rawUnitType,
            int speechEvent,
            int auxiliary)
        {
            NativeSpeechSelector trampoline = EnterCallback();
            if (trampoline == null)
            {
                FailClosed(
                    "native speech selector callback has no trampoline",
                    null);
                return;
            }

            int forwardedType = rawUnitType;
            try
            {
                forwardedType = ConsumeToken(rawUnitType, speechEvent);
            }
            catch (Exception exception)
            {
                FailClosed(
                    "native speech selector token bookkeeping failed",
                    exception);
                forwardedType = rawUnitType;
            }

            try
            {
                // RCX, R8D and R9D are deliberately byte-for-byte unchanged.
                trampoline(
                    speechContext,
                    forwardedType,
                    speechEvent,
                    auxiliary);
            }
            catch (Exception exception)
            {
                // Never let a managed exception unwind through native game
                // code. Speech fails closed for this call and future tokens.
                FailClosed(
                    "native speech selector trampoline failed",
                    exception);
            }
            finally
            {
                ExitCallback();
            }
        }

        private NativeSpeechSelector EnterCallback()
        {
            lock (_gate)
            {
                if (_trampoline == null)
                {
                    return null;
                }
                _callbacksInFlight++;
                return _trampoline;
            }
        }

        private void ExitCallback()
        {
            lock (_gate)
            {
                if (_callbacksInFlight > 0)
                {
                    _callbacksInFlight--;
                }
                if (_callbacksInFlight == 0)
                {
                    Monitor.PulseAll(_gate);
                }
            }
        }

        private int ConsumeToken(int rawUnitType, int speechEvent)
        {
            lock (_gate)
            {
                SpeechTokenLease token = _activeToken;
                if (!_applied
                    || _faulted
                    || _disposing
                    || _disposed
                    || token == null
                    || !token.IsArmed
                    || token.NativeThreadId != GetCurrentThreadId()
                    || token.RawWorkerType != rawUnitType
                    || !token.Allows(speechEvent))
                {
                    return rawUnitType;
                }

                int donorType = DonorType(rawUnitType);
                if (donorType == rawUnitType || !token.MarkConsumed())
                {
                    return rawUnitType;
                }
                _activeToken = null;
                return donorType;
            }
        }

        private void Clear(SpeechTokenLease expected)
        {
            bool cleared = false;
            lock (_gate)
            {
                if (ReferenceEquals(_activeToken, expected))
                {
                    _activeToken = null;
                    cleared = true;
                }
            }
            if (cleared)
            {
                expected.MarkCleared();
            }
        }

        private bool RememberPreparationFailure(string failure)
        {
            lock (_gate)
            {
                _prepared = false;
                _nativeEnginePath = null;
                _nativeModuleBase = IntPtr.Zero;
                _hookApi = null;
                _failure = failure ?? "native speech selector preparation failed";
            }
            return false;
        }

        private void FailClosed(string message, Exception exception)
        {
            SpeechTokenLease token;
            lock (_gate)
            {
                token = _activeToken;
                _activeToken = null;
                _faulted = true;
                _failure = message + (exception == null
                    ? string.Empty
                    : ": " + exception.GetType().Name);
            }
            if (token != null)
            {
                token.MarkCleared();
            }
            WarnOnce(_failure);
        }

        private void WarnOnce(string message)
        {
            lock (_gate)
            {
                if (_warningEmitted)
                {
                    return;
                }
                _warningEmitted = true;
            }
            try
            {
                _warning(message);
            }
            catch
            {
                // Logging is never allowed to escape a native callback or
                // make hook cleanup fail.
            }
        }

        private static ulong AllowedEvents(
            WorkerMilitiaSpeechPurpose purpose,
            int rawWorkerType)
        {
            if (rawWorkerType != HunterType
                && rawWorkerType != WoodcutterType)
            {
                return 0UL;
            }
            switch (purpose)
            {
                case WorkerMilitiaSpeechPurpose.Selection:
                    return SelectionEvents;
                case WorkerMilitiaSpeechPurpose.GroundOrder:
                    return GroundOrderEvents;
                case WorkerMilitiaSpeechPurpose.TargetOrder:
                    return rawWorkerType == HunterType
                        ? HunterTargetOrderEvents
                        : WoodcutterTargetOrderEvents;
                default:
                    return 0UL;
            }
        }

        private static int DonorType(int rawWorkerType)
        {
            if (rawWorkerType == HunterType)
            {
                return ArcherDonorType;
            }
            if (rawWorkerType == WoodcutterType)
            {
                return MacemanDonorType;
            }
            return rawWorkerType;
        }

        private static bool VerifyPinnedBuild(
            string nativeEnginePath,
            IntPtr nativeModuleBase,
            out string failure)
        {
            if (IntPtr.Size != 8)
            {
                failure = "native speech selector requires the pinned x64 process";
                return false;
            }

            string moduleFailure;
            if (!ModuleMatches(
                    nativeEnginePath,
                    nativeModuleBase,
                    out moduleFailure))
            {
                failure = moduleFailure;
                return false;
            }

            FileInfo nativeEngine;
            try
            {
                nativeEngine = new FileInfo(nativeEnginePath);
            }
            catch (Exception exception)
            {
                failure = "pinned CrusaderDE.dll metadata is unreadable: "
                    + exception.GetType().Name;
                return false;
            }
            if (!nativeEngine.Exists
                || nativeEngine.Length != PinnedNativeEngineSize)
            {
                failure = "pinned CrusaderDE.dll size changed";
                return false;
            }

            byte[] image;
            try
            {
                image = File.ReadAllBytes(nativeEnginePath);
            }
            catch (Exception exception)
            {
                failure = "pinned CrusaderDE.dll could not be read: "
                    + exception.GetType().Name;
                return false;
            }

            if (image.LongLength != PinnedNativeEngineSize)
            {
                failure = "pinned CrusaderDE.dll size changed";
                return false;
            }
            if (!string.Equals(
                    Hashing.Sha256(image),
                    PinnedNativeEngineSha256,
                    StringComparison.Ordinal))
            {
                failure = "pinned CrusaderDE.dll SHA-256 changed";
                return false;
            }
            if (!BytesMatch(
                    image,
                    NativeSelectorFileOffset,
                    NativeSelectorPrologue))
            {
                failure = "pinned native speech selector file prologue changed";
                return false;
            }

            byte[] livePrologue = new byte[NativeSelectorPrologue.Length];
            try
            {
                Marshal.Copy(
                    IntPtr.Add(nativeModuleBase, NativeSelectorRva),
                    livePrologue,
                    0,
                    livePrologue.Length);
            }
            catch (Exception exception)
            {
                failure = "native speech selector prologue is unreadable: "
                    + exception.GetType().Name;
                return false;
            }
            if (!BytesMatch(
                    livePrologue,
                    0,
                    NativeSelectorPrologue))
            {
                failure = "live native speech selector prologue changed or is already hooked";
                return false;
            }

            failure = string.Empty;
            return true;
        }

        private static bool TryResolveModule(
            string nativeEnginePath,
            out IntPtr moduleBase,
            out string failure)
        {
            moduleBase = IntPtr.Zero;
            string fullPath;
            try
            {
                fullPath = Path.GetFullPath(nativeEnginePath);
            }
            catch (Exception exception)
            {
                failure = "native speech selector path is invalid: "
                    + exception.GetType().Name;
                return false;
            }

            try
            {
                using (Process process = Process.GetCurrentProcess())
                {
                    foreach (ProcessModule module in process.Modules)
                    {
                        if (string.Equals(
                                module.ModuleName,
                                NativeModuleName,
                                StringComparison.OrdinalIgnoreCase)
                            && string.Equals(
                                Path.GetFullPath(module.FileName),
                                fullPath,
                                StringComparison.OrdinalIgnoreCase))
                        {
                            moduleBase = module.BaseAddress;
                            if (moduleBase == IntPtr.Zero)
                            {
                                failure = "loaded CrusaderDE.dll has no module base";
                                return false;
                            }
                            failure = string.Empty;
                            return true;
                        }
                    }
                }
            }
            catch (Exception exception)
            {
                failure = "loaded CrusaderDE.dll could not be enumerated: "
                    + exception.GetType().Name;
                return false;
            }

            failure = "canonical CrusaderDE.dll is not loaded";
            return false;
        }

        private static bool ModuleMatches(
            string nativeEnginePath,
            IntPtr nativeModuleBase,
            out string failure)
        {
            if (nativeModuleBase == IntPtr.Zero)
            {
                failure = "native CrusaderDE.dll base is unavailable";
                return false;
            }
            try
            {
                string fullPath = Path.GetFullPath(nativeEnginePath);
                using (Process process = Process.GetCurrentProcess())
                {
                    foreach (ProcessModule module in process.Modules)
                    {
                        if (module.BaseAddress == nativeModuleBase
                            && string.Equals(
                                module.ModuleName,
                                NativeModuleName,
                                StringComparison.OrdinalIgnoreCase)
                            && string.Equals(
                                Path.GetFullPath(module.FileName),
                                fullPath,
                                StringComparison.OrdinalIgnoreCase))
                        {
                            failure = string.Empty;
                            return true;
                        }
                    }
                }
            }
            catch (Exception exception)
            {
                failure = "loaded CrusaderDE.dll identity is unreadable: "
                    + exception.GetType().Name;
                return false;
            }
            failure = "native module base does not identify canonical CrusaderDE.dll";
            return false;
        }

        private static bool BytesMatch(
            byte[] source,
            int offset,
            byte[] expected)
        {
            if (source == null
                || expected == null
                || offset < 0
                || source.Length - offset < expected.Length)
            {
                return false;
            }
            for (int index = 0; index < expected.Length; index++)
            {
                if (source[offset + index] != expected[index])
                {
                    return false;
                }
            }
            return true;
        }

        private static bool DisableHook(
            HookApi hookApi,
            object transaction,
            object hook)
        {
            try
            {
                return hookApi == null
                    ? transaction == null && hook == null
                    : hookApi.Disable(transaction, hook);
            }
            catch
            {
                return false;
            }
        }

        private static void DisposeDisabledHook(
            HookApi hookApi,
            object transaction,
            object hook)
        {
            try
            {
                if (hookApi != null)
                {
                    hookApi.DisposeDisabled(transaction, hook);
                }
            }
            catch
            {
                // It is already unhooked. Cleanup must remain idempotent.
            }
        }

        /// <summary>
        /// Reflection boundary for the pinned Zhuqiaomon 1.0 hook surface.
        /// </summary>
        /// <remarks>
        /// HookTransaction's public constructor exposes ILoggerFactory and its
        /// public HookRef graph exposes PolyHook2.Managed. Both assemblies are
        /// existing SHCDESE runtime dependencies, but neither is part of this
        /// companion project's compile contract. Resolving the exact pinned
        /// members here avoids adding a second compile/runtime ownership edge.
        /// Preparation rejects any surface drift before native memory changes.
        /// </remarks>
        private sealed class HookApi
        {
            private const string ZhuqiaomonAssemblyName = "Zhuqiaomon";
            private const string TransactionTypeName =
                "Zhuqiaomon.Hooks.Transaction.HookTransaction";
            private const string FailureModeTypeName =
                "Zhuqiaomon.Hooks.Transaction.TransactionFailureMode";
            private const string HookRefTypeName =
                "Zhuqiaomon.Hooks.Transaction.HookRef`1";
            private const string DetourTypeName =
                "Zhuqiaomon.Hooks.X64ManagedFunctionDetourAOB`1";
            private const string LoggerFactoryTypeName =
                "Microsoft.Extensions.Logging.ILoggerFactory";

            private readonly Type _hookRefType;
            private readonly ConstructorInfo _transactionConstructor;
            private readonly object _rollbackFailureMode;
            private readonly MethodInfo _addDetour;
            private readonly MethodInfo _commit;
            private readonly MethodInfo _unload;
            private readonly MethodInfo _transactionDispose;
            private readonly MethodInfo _getActiveHooks;
            private readonly PropertyInfo _hookRefValue;
            private readonly FieldInfo _initializedSuccessfully;
            private readonly FieldInfo _nativeHook;
            private readonly PropertyInfo _trampolineProperty;
            private readonly FieldInfo _trampolineField;
            private readonly MethodInfo _isHooked;
            private readonly MethodInfo _unhook;
            private readonly MethodInfo _nativeHookDispose;

            private HookApi(
                Type hookRefType,
                ConstructorInfo transactionConstructor,
                object rollbackFailureMode,
                MethodInfo addDetour,
                MethodInfo commit,
                MethodInfo unload,
                MethodInfo transactionDispose,
                MethodInfo getActiveHooks,
                PropertyInfo hookRefValue,
                FieldInfo initializedSuccessfully,
                FieldInfo nativeHook,
                PropertyInfo trampolineProperty,
                FieldInfo trampolineField,
                MethodInfo isHooked,
                MethodInfo unhook,
                MethodInfo nativeHookDispose)
            {
                _hookRefType = hookRefType;
                _transactionConstructor = transactionConstructor;
                _rollbackFailureMode = rollbackFailureMode;
                _addDetour = addDetour;
                _commit = commit;
                _unload = unload;
                _transactionDispose = transactionDispose;
                _getActiveHooks = getActiveHooks;
                _hookRefValue = hookRefValue;
                _initializedSuccessfully = initializedSuccessfully;
                _nativeHook = nativeHook;
                _trampolineProperty = trampolineProperty;
                _trampolineField = trampolineField;
                _isHooked = isHooked;
                _unhook = unhook;
                _nativeHookDispose = nativeHookDispose;
            }

            internal static bool TryResolve(
                out HookApi hookApi,
                out string failure)
            {
                hookApi = null;
                try
                {
                    Assembly assembly = Assembly.Load(ZhuqiaomonAssemblyName);
                    if (assembly.GetName().Version != new Version(1, 0, 0, 0))
                    {
                        failure = "pinned Zhuqiaomon assembly version changed";
                        return false;
                    }

                    Type transactionType = RequireType(
                        assembly,
                        TransactionTypeName);
                    Type failureModeType = RequireType(
                        assembly,
                        FailureModeTypeName);
                    Type hookRefOpenType = RequireType(
                        assembly,
                        HookRefTypeName);
                    Type detourOpenType = RequireType(
                        assembly,
                        DetourTypeName);
                    Type detourType = detourOpenType.MakeGenericType(
                        typeof(NativeSpeechSelector));
                    Type hookRefType = hookRefOpenType.MakeGenericType(
                        detourType);

                    ConstructorInfo transactionConstructor =
                        FindTransactionConstructor(
                            transactionType,
                            failureModeType);
                    object rollbackFailureMode = Enum.Parse(
                        failureModeType,
                        "RollbackAndThrow",
                        false);
                    MethodInfo addDetour = FindDirectAddDetour(
                        transactionType,
                        hookRefType);
                    MethodInfo commit = RequireMethod(
                        transactionType,
                        "Commit");
                    MethodInfo unload = RequireMethod(
                        transactionType,
                        "Unload");
                    MethodInfo transactionDispose = RequireMethod(
                        transactionType,
                        "Dispose");
                    MethodInfo getActiveHooks = RequireMethod(
                        transactionType,
                        "GetActiveHooks");

                    PropertyInfo hookRefValue = hookRefType.GetProperty(
                        "Value",
                        BindingFlags.Public | BindingFlags.Instance);
                    FieldInfo initializedSuccessfully = detourType.GetField(
                        "InitializedSuccessfully",
                        BindingFlags.Public | BindingFlags.Instance);
                    FieldInfo nativeHook = detourType.GetField(
                        "Hook",
                        BindingFlags.Public | BindingFlags.Instance);
                    if (hookRefValue == null
                        || !hookRefValue.CanRead
                        || hookRefValue.PropertyType != detourType
                        || initializedSuccessfully == null
                        || initializedSuccessfully.FieldType != typeof(bool)
                        || nativeHook == null)
                    {
                        throw new MissingMemberException(
                            "Pinned Zhuqiaomon HookRef/detour fields changed");
                    }

                    Type nativeHookType = nativeHook.FieldType;
                    PropertyInfo trampolineProperty = nativeHookType.GetProperty(
                        "Trampoline",
                        BindingFlags.Public | BindingFlags.Instance);
                    FieldInfo trampolineField = nativeHookType.GetField(
                        "Trampoline",
                        BindingFlags.Public | BindingFlags.Instance);
                    Type trampolineType = trampolineProperty != null
                        ? trampolineProperty.PropertyType
                        : trampolineField == null
                            ? null
                            : trampolineField.FieldType;
                    if (trampolineType != typeof(NativeSpeechSelector))
                    {
                        throw new MissingMemberException(
                            "Pinned PolyHook trampoline member changed");
                    }

                    MethodInfo isHooked = RequireMethod(
                        nativeHookType,
                        "IsHooked");
                    MethodInfo unhook = RequireMethod(
                        nativeHookType,
                        "UnHook");
                    MethodInfo nativeHookDispose = RequireMethod(
                        nativeHookType,
                        "Dispose");
                    if (isHooked.ReturnType != typeof(bool))
                    {
                        throw new MissingMemberException(
                            "Pinned PolyHook lifecycle signatures changed");
                    }

                    hookApi = new HookApi(
                        hookRefType,
                        transactionConstructor,
                        rollbackFailureMode,
                        addDetour,
                        commit,
                        unload,
                        transactionDispose,
                        getActiveHooks,
                        hookRefValue,
                        initializedSuccessfully,
                        nativeHook,
                        trampolineProperty,
                        trampolineField,
                        isHooked,
                        unhook,
                        nativeHookDispose);
                    failure = string.Empty;
                    return true;
                }
                catch (Exception exception)
                {
                    Exception root = Unwrap(exception);
                    failure = "pinned Zhuqiaomon speech-hook API changed: "
                        + root.GetType().Name
                        + (string.IsNullOrEmpty(root.Message)
                            ? string.Empty
                            : " (" + root.Message + ")");
                    return false;
                }
            }

            internal object CreateTransaction(ulong moduleBase)
            {
                return _transactionConstructor.Invoke(new object[]
                {
                    ReadOnlyMemory<byte>.Empty,
                    moduleBase,
                    null,
                    _rollbackFailureMode,
                });
            }

            internal object CreateHookRef()
            {
                return Activator.CreateInstance(_hookRefType);
            }

            internal void AddDetour(
                object transaction,
                ref object hook,
                ulong address,
                NativeSpeechSelector callback)
            {
                object[] arguments =
                {
                    hook,
                    address,
                    callback,
                    "WorkerMilitiaSpeechSelector._selectorHook",
                };
                _addDetour.Invoke(transaction, arguments);
                hook = arguments[0];
            }

            internal void Commit(object transaction)
            {
                _commit.Invoke(transaction, null);
            }

            internal int ActiveHookCount(object transaction)
            {
                object active = _getActiveHooks.Invoke(transaction, null);
                ICollection collection = active as ICollection;
                if (collection != null)
                {
                    return collection.Count;
                }
                IEnumerable enumerable = active as IEnumerable;
                if (enumerable == null)
                {
                    return -1;
                }
                int count = 0;
                foreach (object ignored in enumerable)
                {
                    count++;
                }
                return count;
            }

            internal bool TryGetVerifiedTrampoline(
                object hook,
                out NativeSpeechSelector trampoline)
            {
                trampoline = null;
                object wrapper = HookWrapper(hook);
                if (wrapper == null
                    || !(bool)_initializedSuccessfully.GetValue(wrapper))
                {
                    return false;
                }
                object native = _nativeHook.GetValue(wrapper);
                if (native == null)
                {
                    return false;
                }
                trampoline = Trampoline(native) as NativeSpeechSelector;
                return trampoline != null && IsHooked(native);
            }

            internal bool Disable(object transaction, object hook)
            {
                object native = NativeHook(hook);
                if (transaction != null)
                {
                    _unload.Invoke(transaction, null);
                }
                else if (native != null && IsHooked(native))
                {
                    _unhook.Invoke(native, null);
                }
                return native == null || !IsHooked(native);
            }

            internal void DisposeDisabled(object transaction, object hook)
            {
                object native = NativeHook(hook);
                if (native != null)
                {
                    _nativeHookDispose.Invoke(native, null);
                }
                if (transaction != null)
                {
                    _transactionDispose.Invoke(transaction, null);
                }
            }

            private object HookWrapper(object hook)
            {
                return hook == null ? null : _hookRefValue.GetValue(hook, null);
            }

            private object NativeHook(object hook)
            {
                object wrapper = HookWrapper(hook);
                return wrapper == null ? null : _nativeHook.GetValue(wrapper);
            }

            private object Trampoline(object nativeHook)
            {
                return _trampolineProperty != null
                    ? _trampolineProperty.GetValue(nativeHook, null)
                    : _trampolineField.GetValue(nativeHook);
            }

            private bool IsHooked(object nativeHook)
            {
                return (bool)_isHooked.Invoke(nativeHook, null);
            }

            private static Type RequireType(Assembly assembly, string name)
            {
                Type type = assembly.GetType(name, false, false);
                if (type == null)
                {
                    throw new TypeLoadException(name);
                }
                return type;
            }

            private static ConstructorInfo FindTransactionConstructor(
                Type transactionType,
                Type failureModeType)
            {
                foreach (ConstructorInfo candidate in transactionType.GetConstructors(
                    BindingFlags.Public | BindingFlags.Instance))
                {
                    ParameterInfo[] parameters = candidate.GetParameters();
                    if (parameters.Length == 4
                        && parameters[0].ParameterType
                            == typeof(ReadOnlyMemory<byte>)
                        && parameters[1].ParameterType == typeof(ulong)
                        && string.Equals(
                            parameters[2].ParameterType.FullName,
                            LoggerFactoryTypeName,
                            StringComparison.Ordinal)
                        && parameters[3].ParameterType == failureModeType)
                    {
                        return candidate;
                    }
                }
                throw new MissingMethodException(
                    transactionType.FullName,
                    ".ctor(ReadOnlyMemory<byte>,UInt64,ILoggerFactory,TransactionFailureMode)");
            }

            private static MethodInfo FindDirectAddDetour(
                Type transactionType,
                Type hookRefType)
            {
                foreach (MethodInfo definition in transactionType.GetMethods(
                    BindingFlags.Public | BindingFlags.Instance))
                {
                    if (!string.Equals(
                            definition.Name,
                            "AddDetour",
                            StringComparison.Ordinal)
                        || !definition.IsGenericMethodDefinition
                        || definition.GetGenericArguments().Length != 1)
                    {
                        continue;
                    }
                    MethodInfo candidate = definition.MakeGenericMethod(
                        typeof(NativeSpeechSelector));
                    ParameterInfo[] parameters = candidate.GetParameters();
                    if (parameters.Length == 4
                        && parameters[0].ParameterType
                            == hookRefType.MakeByRefType()
                        && parameters[1].ParameterType == typeof(ulong)
                        && parameters[2].ParameterType
                            == typeof(NativeSpeechSelector)
                        && parameters[3].ParameterType == typeof(string))
                    {
                        return candidate;
                    }
                }
                throw new MissingMethodException(
                    transactionType.FullName,
                    "AddDetour<T>(ref HookRef<...>,UInt64,T,String)");
            }

            private static MethodInfo RequireMethod(Type type, string name)
            {
                MethodInfo method = type.GetMethod(
                    name,
                    BindingFlags.Public | BindingFlags.Instance,
                    null,
                    Type.EmptyTypes,
                    null);
                if (method == null)
                {
                    throw new MissingMethodException(type.FullName, name);
                }
                return method;
            }

            private static Exception Unwrap(Exception exception)
            {
                TargetInvocationException invocation =
                    exception as TargetInvocationException;
                return invocation != null && invocation.InnerException != null
                    ? invocation.InnerException
                    : exception;
            }
        }

        [DllImport("kernel32.dll")]
        private static extern uint GetCurrentThreadId();

        /// <summary>
        /// Exact, generation-bound native-run scope. Disposing a stale scope
        /// can clear only its own token, never a token armed by a later run.
        /// </summary>
        internal sealed class SpeechTokenLease : IDisposable
        {
            private readonly WorkerMilitiaSpeechSelector _owner;
            private int _state;
            private int _disposed;

            internal SpeechTokenLease(
                WorkerMilitiaSpeechSelector owner,
                long tokenGeneration,
                long leaseGeneration,
                int workerGlobalId,
                long nativeRunGeneration,
                uint nativeThreadId,
                WorkerMilitiaSpeechPurpose purpose,
                int rawWorkerType,
                ulong allowedEvents)
            {
                _owner = owner;
                TokenGeneration = tokenGeneration;
                LeaseGeneration = leaseGeneration;
                WorkerGlobalId = workerGlobalId;
                NativeRunGeneration = nativeRunGeneration;
                NativeThreadId = nativeThreadId;
                Purpose = purpose;
                RawWorkerType = rawWorkerType;
                AllowedEvents = allowedEvents;
            }

            internal long TokenGeneration { get; private set; }

            internal long LeaseGeneration { get; private set; }

            internal int WorkerGlobalId { get; private set; }

            internal long NativeRunGeneration { get; private set; }

            internal uint NativeThreadId { get; private set; }

            internal WorkerMilitiaSpeechPurpose Purpose { get; private set; }

            internal int RawWorkerType { get; private set; }

            internal ulong AllowedEvents { get; private set; }

            internal bool WasConsumed
            {
                get { return Volatile.Read(ref _state) == 1; }
            }

            internal bool IsArmed
            {
                get
                {
                    return Volatile.Read(ref _state) == 0
                        && Volatile.Read(ref _disposed) == 0;
                }
            }

            internal bool Allows(int speechEvent)
            {
                return speechEvent >= 0
                    && speechEvent < 64
                    && (AllowedEvents & (1UL << speechEvent)) != 0UL;
            }

            internal bool MarkConsumed()
            {
                return Interlocked.CompareExchange(ref _state, 1, 0) == 0;
            }

            internal void MarkCleared()
            {
                Interlocked.CompareExchange(ref _state, 2, 0);
            }

            public void Dispose()
            {
                if (Interlocked.Exchange(ref _disposed, 1) != 0)
                {
                    return;
                }
                _owner.Clear(this);
            }
        }
    }
}
