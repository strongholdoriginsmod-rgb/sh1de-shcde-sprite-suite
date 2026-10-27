using System;
using System.Diagnostics;
using System.Threading;

namespace StrongholdEuropeDE.Runtime
{
    internal enum LuaStateGatePath
    {
        LuaCall = 1,
        LuaReferenceDispose = 2,
        TimerAction = 3,
        LuaScriptExecution = 4,
        LuaUnload = 5,
    }

    internal struct LuaStateGateLease
    {
        internal bool Held;
        internal bool Contended;
        internal int WaiterThreadId;
        internal int ObservedOwnerThreadId;
        internal long WaitTicks;
        internal LuaStateGatePath Path;
    }

    internal readonly struct LuaStateGateSnapshot
    {
        internal LuaStateGateSnapshot(
            long luaCalls,
            long luaReferenceDisposals,
            long timerActions,
            long luaScriptExecutions,
            long luaUnloads,
            long contentions,
            long maximumWaitTicks)
        {
            LuaCalls = luaCalls;
            LuaReferenceDisposals = luaReferenceDisposals;
            TimerActions = timerActions;
            LuaScriptExecutions = luaScriptExecutions;
            LuaUnloads = luaUnloads;
            Contentions = contentions;
            MaximumWaitTicks = maximumWaitTicks;
        }

        internal long LuaCalls { get; }
        internal long LuaReferenceDisposals { get; }
        internal long TimerActions { get; }
        internal long LuaScriptExecutions { get; }
        internal long LuaUnloads { get; }
        internal long Contentions { get; }
        internal long MaximumWaitTicks { get; }
    }

    /// <summary>
    /// One process-wide, re-entrant gate for SHCDE-SE's single NLua state.
    /// Lua 5.4 has no built-in protection against two operating-system threads
    /// changing the same stack. Monitor recursion deliberately remains legal:
    /// a Lua callback can synchronously enter another C#-to-Lua callback.
    /// </summary>
    internal static class LuaStateSerializationGate
    {
        private static readonly object Gate = new object();

        [ThreadStatic]
        private static int _threadDepth;

        private static int _ownerThreadId;
        private static long _luaCalls;
        private static long _luaReferenceDisposals;
        private static long _timerActions;
        private static long _luaScriptExecutions;
        private static long _luaUnloads;
        private static long _contentions;
        private static long _maximumWaitTicks;

        internal static int CurrentThreadDepth => _threadDepth;
        internal static long StopwatchFrequency => Stopwatch.Frequency;

        internal static LuaStateGateLease Enter(LuaStateGatePath path)
        {
            if (path != LuaStateGatePath.LuaCall
                && path != LuaStateGatePath.LuaReferenceDispose
                && path != LuaStateGatePath.TimerAction
                && path != LuaStateGatePath.LuaScriptExecution
                && path != LuaStateGatePath.LuaUnload)
            {
                throw new ArgumentOutOfRangeException(nameof(path));
            }

            int waiterThreadId = Thread.CurrentThread.ManagedThreadId;
            bool entered = Monitor.TryEnter(Gate);
            bool contended = !entered;
            int observedOwnerThreadId = 0;
            long waitStarted = 0;
            if (!entered)
            {
                observedOwnerThreadId = Volatile.Read(ref _ownerThreadId);
                waitStarted = Stopwatch.GetTimestamp();
                Monitor.Enter(Gate, ref entered);
            }
            if (!entered)
            {
                throw new SynchronizationLockException(
                    "NLua serialization gate was not acquired");
            }

            long waitTicks = contended
                ? Math.Max(0L, Stopwatch.GetTimestamp() - waitStarted)
                : 0L;
            if (_threadDepth == 0)
            {
                Volatile.Write(ref _ownerThreadId, waiterThreadId);
            }
            _threadDepth++;

            switch (path)
            {
                case LuaStateGatePath.LuaCall:
                    Interlocked.Increment(ref _luaCalls);
                    break;
                case LuaStateGatePath.LuaReferenceDispose:
                    Interlocked.Increment(ref _luaReferenceDisposals);
                    break;
                case LuaStateGatePath.TimerAction:
                    Interlocked.Increment(ref _timerActions);
                    break;
                case LuaStateGatePath.LuaScriptExecution:
                    Interlocked.Increment(ref _luaScriptExecutions);
                    break;
                case LuaStateGatePath.LuaUnload:
                    Interlocked.Increment(ref _luaUnloads);
                    break;
            }
            if (contended)
            {
                Interlocked.Increment(ref _contentions);
                UpdateMaximum(ref _maximumWaitTicks, waitTicks);
            }

            return new LuaStateGateLease
            {
                Held = true,
                Contended = contended,
                WaiterThreadId = waiterThreadId,
                ObservedOwnerThreadId = observedOwnerThreadId,
                WaitTicks = waitTicks,
                Path = path,
            };
        }

        internal static void Exit(LuaStateGateLease lease)
        {
            if (!lease.Held)
            {
                return;
            }
            if (_threadDepth < 1)
            {
                throw new SynchronizationLockException(
                    "NLua serialization gate depth underflow");
            }

            _threadDepth--;
            if (_threadDepth == 0)
            {
                Volatile.Write(ref _ownerThreadId, 0);
            }
            Monitor.Exit(Gate);
        }

        internal static LuaStateGateSnapshot Snapshot()
        {
            return new LuaStateGateSnapshot(
                Interlocked.Read(ref _luaCalls),
                Interlocked.Read(ref _luaReferenceDisposals),
                Interlocked.Read(ref _timerActions),
                Interlocked.Read(ref _luaScriptExecutions),
                Interlocked.Read(ref _luaUnloads),
                Interlocked.Read(ref _contentions),
                Interlocked.Read(ref _maximumWaitTicks));
        }

        private static void UpdateMaximum(ref long location, long value)
        {
            long observed = Interlocked.Read(ref location);
            while (value > observed)
            {
                long prior = Interlocked.CompareExchange(
                    ref location,
                    value,
                    observed);
                if (prior == observed)
                {
                    return;
                }
                observed = prior;
            }
        }
    }
}
