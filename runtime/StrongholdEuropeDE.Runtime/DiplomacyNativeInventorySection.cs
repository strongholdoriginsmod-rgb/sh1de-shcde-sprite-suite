using System;
using System.Reflection;
using System.Threading;
using CrusaderDE;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        private static readonly object NativeInventoryBindingGate = new object();
        private static object _nativeInventoryMonitor;

        internal static bool IsNativeDiplomacySectionHeld
        {
            get
            {
                object monitor = Volatile.Read(ref _nativeInventoryMonitor);
                return monitor != null && Monitor.IsEntered(monitor);
            }
        }

        private static void RequireNativeDiplomacySection()
        {
            if (!IsNativeDiplomacySectionHeld)
                throw new InvalidOperationException("Native diplomacy mutation requires the engine monitor.");
        }

        internal static bool NativeDiplomacyIdentityMatches(
            int expectedOwner, uint expectedGlobalId, int owner, uint globalId)
        {
            return expectedOwner > 0 && expectedOwner <= 8
                && expectedOwner == owner && expectedGlobalId == globalId;
        }

        // Assembly-CSharp EngineInterface.cs:3659, 6610, 6744 (COPY 2.80):
        // this private static object serializes native save/load and DLL_RunTick.
        // Bind on the Unity startup lane. Local pause only writes a native flag;
        // reading that flag back does not wait for a running simulation step.
        internal static bool TryResolveNativeInventoryMonitor(out string failure)
        {
            failure = null;
            if (Volatile.Read(ref _nativeInventoryMonitor) != null) return true;
            lock (NativeInventoryBindingGate)
            {
                if (_nativeInventoryMonitor != null) return true;
                try
                {
                    Type engine = typeof(MainViewModel).Assembly.GetType(
                        "EngineInterface", false);
                    FieldInfo field = engine == null ? null : engine.GetField(
                        "threadLock", BindingFlags.NonPublic | BindingFlags.Static
                            | BindingFlags.DeclaredOnly);
                    if (field == null || !field.IsStatic || field.FieldType != typeof(object))
                    {
                        failure = "EngineInterface::threadLock static System.Object missing";
                        return false;
                    }
                    object monitor = field.GetValue(null);
                    if (monitor == null)
                    {
                        failure = "EngineInterface::threadLock is null";
                        return false;
                    }
                    Volatile.Write(ref _nativeInventoryMonitor, monitor);
                    return true;
                }
                catch (Exception exception)
                {
                    failure = "EngineInterface::threadLock " + exception.GetType().Name;
                    return false;
                }
            }
        }

        // Callers hold _gate. Never wait for the engine while holding it:
        // native callbacks may themselves be waiting to enter _gate.
        // A failed acquisition must precede ALL inventory reads and writes;
        // the caller retains its journal and retries on a later Unity frame.
        private static bool TryEnterNativeInventorySection(out IDisposable lease)
        {
            lease = null;
            object monitor = Volatile.Read(ref _nativeInventoryMonitor);
            if (monitor == null) return false;
            // Allocate before entering, so allocation failure cannot leak a lock.
            var candidate = new NativeInventoryLease(monitor);
            bool entered = false;
            try
            {
                Monitor.TryEnter(monitor, 0, ref entered);
                if (!entered) return false;
                lease = candidate;
                return true;
            }
            catch
            {
                if (entered) Monitor.Exit(monitor);
                return false;
            }
        }

        private sealed class NativeInventoryLease : IDisposable
        {
            private object _monitor;
            private readonly int _ownerThreadId;

            internal NativeInventoryLease(object monitor)
            {
                _monitor = monitor;
                _ownerThreadId = Environment.CurrentManagedThreadId;
            }

            public void Dispose()
            {
                if (Volatile.Read(ref _monitor) == null) return;
                // Reject cross-thread disposal without losing the owner's lease.
                if (Environment.CurrentManagedThreadId != _ownerThreadId)
                    throw new InvalidOperationException(
                        "Native inventory lease must be disposed on its acquiring thread.");
                object monitor = Interlocked.Exchange(ref _monitor, null);
                if (monitor != null) Monitor.Exit(monitor);
            }
        }
    }
}
