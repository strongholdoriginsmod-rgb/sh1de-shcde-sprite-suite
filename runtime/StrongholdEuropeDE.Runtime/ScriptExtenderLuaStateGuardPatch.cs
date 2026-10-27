using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;
using HarmonyLib;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Serializes every SHCDE-SE/NLua boundary that can overlap a native timer
    /// callback. SHCDE-SE owns one Lua 5.4 state, while its simulation ticker,
    /// Unity input and debug console can enter that state from different
    /// operating-system threads.
    ///
    /// This patch deliberately owns an independent Harmony instance for the
    /// lifetime of the process. A rollback of an unrelated Europe runtime lane
    /// must never remove the state guard while SHCDE-SE keeps running.
    /// </summary>
    internal static class ScriptExtenderLuaStateGuardPatch
    {
        private const string HarmonyOwnerId =
            "com.strongholdeuropede.runtime.lua-state-guard.v1";
        private const string NLuaAssemblyName = "NLua";
        private const string KeraLuaAssemblyName = "KeraLua";
        private const string LuaTypeName = "NLua.Lua";
        private const string TimerEngineTypeName =
            "SHCDESE.API.Components.Timer.TimerEngine";
        private const string GameTimeManagerTypeName =
            "SHCDESE.API.GameTimeManagerAPI";
        private const string LuaManagerTypeName =
            "SHCDESE.Lua.LuaManager";
        private const string MapUnloadEventArgsTypeName =
            "SHCDESE.EventAPI.MapLoader.MapUnloadEventArgs";
        private const string EventHookPhaseTypeName =
            "SHCDESE.EventAPI.EventHookPhase";

        private static Action<string> _information;
        private static Action<string> _warning;
        private static Harmony _patchOwner;
        private static PropertyInfo _gameTimeManagerInstanceProperty;
        private static MethodInfo _getTimerEngine;
        private static MethodInfo _removeAllTimers;
        private static PropertyInfo _mapUnloadPhaseProperty;
        private static object _preUnloadPhase;
        private static int _installState;
        private static int _contentionReported;

        internal static bool Installed => Volatile.Read(ref _installState) == 2;

        internal static void Install(
            Action<string> information,
            Action<string> warning)
        {
            if (Interlocked.CompareExchange(ref _installState, 1, 0) != 0)
            {
                if (Installed)
                {
                    return;
                }
                throw new InvalidOperationException(
                    "NLua state guard installation was already attempted");
            }

            _information = information;
            _warning = warning;
            var patchOwner = new Harmony(HarmonyOwnerId);
            var originals = new List<MethodBase>();
            var prefixes = new List<MethodInfo>();
            var finalizers = new List<MethodInfo>();
            MethodInfo gateFinalizer = RequireOwnMethod("GateFinalizer");
            MethodInfo unloadFinalizer = RequireOwnMethod(
                "LuaUnloadFinalizer");
            try
            {
                // SHCDE-SE does not create its Lua state in the menu. Resolve
                // the two already file-attested managed bridges explicitly so
                // guard installation does not depend on a previous map load.
                Assembly nlua = RequireVerifiedAssembly(
                    NLuaAssemblyName,
                    "nlua");
                Assembly keralua = RequireVerifiedAssembly(
                    KeraLuaAssemblyName,
                    "keralua");
                Assembly shcdese = RequireUniqueLoadedAssembly("SHCDESE");
                RuntimeBuildGuard.VerifyEarlyLoadedAssemblyReportingDrift(
                    shcdese,
                    "shcdese");

                Type luaType = nlua.GetType(LuaTypeName, true, false);
                MethodInfo callFunction = RequireMethod(
                    luaType,
                    "CallFunction",
                    BindingFlags.Instance
                        | BindingFlags.NonPublic
                        | BindingFlags.DeclaredOnly,
                    typeof(object[]),
                    new[]
                    {
                        typeof(object),
                        typeof(object[]),
                        typeof(Type[]),
                    });
                MethodInfo disposeInternal = RequireMethod(
                    luaType,
                    "DisposeInternal",
                    BindingFlags.Instance
                        | BindingFlags.NonPublic
                        | BindingFlags.DeclaredOnly,
                    typeof(void),
                    new[] { typeof(int), typeof(bool) });
                MethodInfo doStringBytes = RequireMethod(
                    luaType,
                    "DoString",
                    BindingFlags.Instance
                        | BindingFlags.Public
                        | BindingFlags.DeclaredOnly,
                    typeof(object[]),
                    new[] { typeof(byte[]), typeof(string) });
                MethodInfo doStringText = RequireMethod(
                    luaType,
                    "DoString",
                    BindingFlags.Instance
                        | BindingFlags.Public
                        | BindingFlags.DeclaredOnly,
                    typeof(object[]),
                    new[] { typeof(string), typeof(string) });

                Type timerEngineType = shcdese.GetType(
                    TimerEngineTypeName,
                    true,
                    false);
                MethodInfo handleAction = RequireMethod(
                    timerEngineType,
                    "HandleAction",
                    BindingFlags.Instance
                        | BindingFlags.NonPublic
                        | BindingFlags.DeclaredOnly,
                    typeof(void),
                    new[] { typeof(Action), typeof(string), typeof(bool) });
                _removeAllTimers = RequireMethod(
                    timerEngineType,
                    "RemoveAllTimers",
                    BindingFlags.Instance
                        | BindingFlags.Public
                        | BindingFlags.DeclaredOnly,
                    typeof(void),
                    Type.EmptyTypes);

                Type gameTimeManagerType = shcdese.GetType(
                    GameTimeManagerTypeName,
                    true,
                    false);
                _gameTimeManagerInstanceProperty = RequireProperty(
                    gameTimeManagerType,
                    "Instance",
                    BindingFlags.Static
                        | BindingFlags.Public
                        | BindingFlags.DeclaredOnly,
                    gameTimeManagerType);
                _getTimerEngine = RequireMethod(
                    gameTimeManagerType,
                    "GetTimerEngine",
                    BindingFlags.Instance
                        | BindingFlags.Public
                        | BindingFlags.DeclaredOnly,
                    timerEngineType,
                    Type.EmptyTypes);

                Type mapUnloadEventArgsType = shcdese.GetType(
                    MapUnloadEventArgsTypeName,
                    true,
                    false);
                Type eventHookPhaseType = shcdese.GetType(
                    EventHookPhaseTypeName,
                    true,
                    false);
                _mapUnloadPhaseProperty = RequireProperty(
                    mapUnloadEventArgsType,
                    "Phase",
                    BindingFlags.Instance | BindingFlags.Public,
                    eventHookPhaseType);
                _preUnloadPhase = Enum.Parse(
                    eventHookPhaseType,
                    "Pre",
                    false);
                Type luaManagerType = shcdese.GetType(
                    LuaManagerTypeName,
                    true,
                    false);
                Type luaLoadModeType = luaManagerType.GetNestedType(
                    "LuaLoadMode",
                    BindingFlags.Public);
                if (luaLoadModeType == null || !luaLoadModeType.IsEnum)
                {
                    throw new TypeLoadException(
                        "Pinned LuaManager.LuaLoadMode enum changed");
                }
                MethodInfo tryInitState = RequireMethod(
                    luaManagerType,
                    "TryInitState",
                    BindingFlags.Instance
                        | BindingFlags.NonPublic
                        | BindingFlags.DeclaredOnly,
                    typeof(void),
                    Type.EmptyTypes);
                MethodInfo tryRunInit = RequireMethod(
                    luaManagerType,
                    "TryRunInit",
                    BindingFlags.Instance
                        | BindingFlags.NonPublic
                        | BindingFlags.DeclaredOnly,
                    typeof(bool),
                    new[] { luaLoadModeType });
                MethodInfo tryUnload = RequireMethod(
                    luaManagerType,
                    "TryUnload",
                    BindingFlags.Instance
                        | BindingFlags.NonPublic
                        | BindingFlags.DeclaredOnly,
                    typeof(void),
                    Type.EmptyTypes);
                MethodInfo luaOnUnloadMap = RequireMethod(
                    luaManagerType,
                    "OnUnloadMap",
                    BindingFlags.Static
                        | BindingFlags.NonPublic
                        | BindingFlags.DeclaredOnly,
                    typeof(void),
                    new[] { mapUnloadEventArgsType });

                PatchOne(
                    patchOwner,
                    handleAction,
                    RequireOwnMethod("TimerActionPrefix"),
                    gateFinalizer,
                    originals,
                    prefixes,
                    finalizers);
                PatchOne(
                    patchOwner,
                    callFunction,
                    RequireOwnMethod("LuaCallPrefix"),
                    gateFinalizer,
                    originals,
                    prefixes,
                    finalizers);
                PatchOne(
                    patchOwner,
                    disposeInternal,
                    RequireOwnMethod("LuaReferenceDisposePrefix"),
                    gateFinalizer,
                    originals,
                    prefixes,
                    finalizers);
                PatchOne(
                    patchOwner,
                    doStringBytes,
                    RequireOwnMethod("LuaScriptExecutionPrefix"),
                    gateFinalizer,
                    originals,
                    prefixes,
                    finalizers);
                PatchOne(
                    patchOwner,
                    doStringText,
                    RequireOwnMethod("LuaScriptExecutionPrefix"),
                    gateFinalizer,
                    originals,
                    prefixes,
                    finalizers);
                PatchOne(
                    patchOwner,
                    tryInitState,
                    RequireOwnMethod("LuaScriptExecutionPrefix"),
                    gateFinalizer,
                    originals,
                    prefixes,
                    finalizers);
                PatchOne(
                    patchOwner,
                    tryRunInit,
                    RequireOwnMethod("LuaScriptExecutionPrefix"),
                    gateFinalizer,
                    originals,
                    prefixes,
                    finalizers);
                PatchOne(
                    patchOwner,
                    tryUnload,
                    RequireOwnMethod("LuaUnloadMethodPrefix"),
                    unloadFinalizer,
                    originals,
                    prefixes,
                    finalizers);
                PatchOne(
                    patchOwner,
                    luaOnUnloadMap,
                    RequireOwnMethod("LuaUnloadPrefix"),
                    unloadFinalizer,
                    originals,
                    prefixes,
                    finalizers);

                _patchOwner = patchOwner;
                Volatile.Write(ref _installState, 2);
                Emit(
                    _information,
                    "SEDE_LUA_GUARD_V1|event=install|status=active"
                    + "|targets=9|nlua=" + AssemblyVersionToken(nlua)
                    + "|keralua=" + AssemblyVersionToken(keralua)
                    + "|shcdese=" + AssemblyVersionToken(shcdese)
                    + "|owner=process_lifetime"
                    + "|mode=reentrant_cross_thread_serialization");
            }
            catch (Exception exception)
            {
                for (int index = originals.Count - 1; index >= 0; index--)
                {
                    try
                    {
                        patchOwner.Unpatch(
                            originals[index],
                            prefixes[index]);
                        patchOwner.Unpatch(
                            originals[index],
                            finalizers[index]);
                    }
                    catch
                    {
                    }
                }
                Volatile.Write(ref _installState, 3);
                Emit(
                    _warning,
                    "SEDE_LUA_GUARD_V1|event=install|status=failed_closed"
                    + "|reason=" + Token(exception.GetType().Name));
                throw new InvalidOperationException(
                    "Pinned SHCDE-SE/NLua state guard could not be installed",
                    exception);
            }
        }

        internal static string SummaryEvent()
        {
            LuaStateGateSnapshot snapshot = LuaStateSerializationGate.Snapshot();
            return "SEDE_LUA_GUARD_V1|event=summary|status="
                + (Installed ? "active" : "inactive")
                + "|lua_calls=" + snapshot.LuaCalls.ToString()
                + "|lua_reference_disposals="
                + snapshot.LuaReferenceDisposals.ToString()
                + "|timer_actions=" + snapshot.TimerActions.ToString()
                + "|lua_script_executions="
                + snapshot.LuaScriptExecutions.ToString()
                + "|lua_unloads=" + snapshot.LuaUnloads.ToString()
                + "|contentions=" + snapshot.Contentions.ToString()
                + "|maximum_wait_us="
                + ToMicroseconds(snapshot.MaximumWaitTicks).ToString();
        }

        private static void PatchOne(
            Harmony harmony,
            MethodBase original,
            MethodInfo prefix,
            MethodInfo finalizer,
            List<MethodBase> originals,
            List<MethodInfo> prefixes,
            List<MethodInfo> finalizers)
        {
            harmony.Patch(
                original,
                prefix: new HarmonyMethod(prefix),
                finalizer: new HarmonyMethod(finalizer));
            originals.Add(original);
            prefixes.Add(prefix);
            finalizers.Add(finalizer);
        }

        private static void TimerActionPrefix(out LuaStateGateLease __state)
        {
            Enter(LuaStateGatePath.TimerAction, out __state);
        }

        private static void LuaCallPrefix(out LuaStateGateLease __state)
        {
            Enter(LuaStateGatePath.LuaCall, out __state);
        }

        private static void LuaReferenceDisposePrefix(
            out LuaStateGateLease __state)
        {
            Enter(LuaStateGatePath.LuaReferenceDispose, out __state);
        }

        private static void LuaScriptExecutionPrefix(
            out LuaStateGateLease __state)
        {
            Enter(LuaStateGatePath.LuaScriptExecution, out __state);
        }

        private static void LuaUnloadPrefix(
            object __0,
            out LuaStateGateLease __state)
        {
            __state = default(LuaStateGateLease);
            if (!IsPreUnload(__0))
            {
                return;
            }

            BeginLuaUnload(out __state);
        }

        private static void LuaUnloadMethodPrefix(
            out LuaStateGateLease __state)
        {
            BeginLuaUnload(out __state);
        }

        private static void BeginLuaUnload(
            out LuaStateGateLease state)
        {
            Enter(LuaStateGatePath.LuaUnload, out state);
            try
            {
                RemoveAllTimers();
            }
            catch
            {
                LuaStateSerializationGate.Exit(state);
                state = default(LuaStateGateLease);
                throw;
            }
        }

        private static Exception GateFinalizer(
            Exception __exception,
            LuaStateGateLease __state)
        {
            LuaStateSerializationGate.Exit(__state);
            return __exception;
        }

        private static Exception LuaUnloadFinalizer(
            Exception __exception,
            LuaStateGateLease __state)
        {
            if (!__state.Held)
            {
                return __exception;
            }

            try
            {
                // unload() itself may schedule a final timer. Remove again
                // before releasing the gate so no callback can outlive Lua.Close.
                RemoveAllTimers();
            }
            catch (Exception cleanupException)
            {
                Emit(
                    _warning,
                    "SEDE_LUA_GUARD_V1|event=unload_cleanup"
                    + "|status=failed_closed|reason="
                    + Token(cleanupException.GetType().Name));
            }
            finally
            {
                LuaStateSerializationGate.Exit(__state);
            }
            return __exception;
        }

        private static bool IsPreUnload(object eventArgs)
        {
            if (eventArgs == null)
            {
                throw new ArgumentNullException("eventArgs");
            }
            object phase = _mapUnloadPhaseProperty.GetValue(
                eventArgs,
                null);
            return Equals(phase, _preUnloadPhase);
        }

        private static void RemoveAllTimers()
        {
            object gameTimeManager =
                _gameTimeManagerInstanceProperty.GetValue(null, null);
            if (gameTimeManager == null)
            {
                throw new InvalidOperationException(
                    "SHCDE-SE game-time manager is unavailable");
            }
            object timerEngine = _getTimerEngine.Invoke(
                gameTimeManager,
                null);
            if (timerEngine == null)
            {
                throw new InvalidOperationException(
                    "SHCDE-SE timer engine is unavailable");
            }
            _removeAllTimers.Invoke(timerEngine, null);
        }

        private static void Enter(
            LuaStateGatePath path,
            out LuaStateGateLease state)
        {
            state = default(LuaStateGateLease);
            state = LuaStateSerializationGate.Enter(path);
            if (!state.Contended
                || Interlocked.CompareExchange(
                    ref _contentionReported,
                    1,
                    0) != 0)
            {
                return;
            }
            Emit(
                _information,
                "SEDE_LUA_GUARD_V1|event=contention|status=serialized"
                + "|path=" + PathToken(state.Path)
                + "|waiter_thread=" + state.WaiterThreadId.ToString()
                + "|observed_owner_thread="
                + state.ObservedOwnerThreadId.ToString()
                + "|wait_us=" + ToMicroseconds(state.WaitTicks).ToString());
        }

        private static MethodInfo RequireOwnMethod(string name)
        {
            MethodInfo method = typeof(
                ScriptExtenderLuaStateGuardPatch).GetMethod(
                    name,
                    BindingFlags.Static | BindingFlags.NonPublic);
            if (method == null)
            {
                throw new MissingMethodException(
                    "Lua state guard method is unavailable: " + name);
            }
            return method;
        }

        private static MethodInfo RequireMethod(
            Type type,
            string name,
            BindingFlags flags,
            Type returnType,
            Type[] parameters)
        {
            MethodInfo method = type.GetMethod(
                name,
                flags,
                null,
                parameters,
                null);
            if (method == null || method.ReturnType != returnType)
            {
                throw new MissingMethodException(
                    "Pinned Lua guard target changed: "
                    + type.FullName
                    + "."
                    + name);
            }
            return method;
        }

        private static PropertyInfo RequireProperty(
            Type type,
            string name,
            BindingFlags flags,
            Type propertyType)
        {
            PropertyInfo property = type.GetProperty(name, flags);
            if (property == null
                || property.PropertyType != propertyType
                || property.GetGetMethod(true) == null)
            {
                throw new MissingMemberException(
                    "Pinned Lua guard property changed: "
                    + type.FullName
                    + "."
                    + name);
            }
            return property;
        }

        private static Assembly RequireUniqueLoadedAssembly(string simpleName)
        {
            Assembly match = FindUniqueLoadedAssembly(simpleName);
            if (match == null)
            {
                throw new InvalidOperationException(
                    "Required loaded assembly is absent: " + simpleName);
            }
            return match;
        }

        private static Assembly RequireVerifiedAssembly(
            string simpleName,
            string dependencyId)
        {
            Assembly match = FindUniqueLoadedAssembly(simpleName);
            if (match == null)
            {
                string exactPath =
                    RuntimeBuildGuard.GetVerifiedPrerequisitePath(
                        dependencyId);
                Assembly.LoadFrom(exactPath);
                match = FindUniqueLoadedAssembly(simpleName);
            }
            if (match == null)
            {
                throw new InvalidOperationException(
                    "Required assembly could not be loaded: " + simpleName);
            }
            RuntimeBuildGuard.VerifyEarlyLoadedAssemblyReportingDrift(
                match,
                dependencyId);
            return match;
        }

        private static Assembly FindUniqueLoadedAssembly(string simpleName)
        {
            Assembly match = null;
            foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (!string.Equals(
                        assembly.GetName().Name,
                        simpleName,
                        StringComparison.Ordinal))
                {
                    continue;
                }
                if (match != null && !ReferenceEquals(match, assembly))
                {
                    throw new InvalidOperationException(
                        "Multiple loaded assemblies named " + simpleName);
                }
                match = assembly;
            }
            return match;
        }

        private static long ToMicroseconds(long ticks)
        {
            if (ticks <= 0 || LuaStateSerializationGate.StopwatchFrequency <= 0)
            {
                return 0;
            }
            if (ticks <= long.MaxValue / 1000000L)
            {
                return ticks * 1000000L
                    / LuaStateSerializationGate.StopwatchFrequency;
            }
            return ticks / LuaStateSerializationGate.StopwatchFrequency
                * 1000000L;
        }

        private static string PathToken(LuaStateGatePath path)
        {
            switch (path)
            {
                case LuaStateGatePath.LuaCall:
                    return "lua_call";
                case LuaStateGatePath.LuaReferenceDispose:
                    return "lua_reference_dispose";
                case LuaStateGatePath.TimerAction:
                    return "timer_action";
                case LuaStateGatePath.LuaScriptExecution:
                    return "lua_script_execution";
                case LuaStateGatePath.LuaUnload:
                    return "lua_unload";
                default:
                    return "unknown";
            }
        }

        private static string AssemblyVersionToken(Assembly assembly)
        {
            Version version = assembly.GetName().Version;
            if (version == null)
            {
                throw new InvalidOperationException(
                    "Verified assembly has no version: "
                    + assembly.GetName().Name);
            }
            return Token(version.ToString());
        }

        private static string Token(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "unknown";
            }
            return value.Replace('|', '_').Replace('\r', '_').Replace('\n', '_');
        }

        private static void Emit(Action<string> sink, string message)
        {
            if (sink == null)
            {
                return;
            }
            try
            {
                sink(message);
            }
            catch
            {
            }
        }
    }
}
