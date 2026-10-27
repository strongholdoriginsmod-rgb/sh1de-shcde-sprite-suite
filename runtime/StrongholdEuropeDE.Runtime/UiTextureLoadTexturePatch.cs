using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Process-lifetime SHCDE-SE bridge for manifest-owned UI textures. The
    /// resolver emits nonexistent virtual paths and the loader prefix services
    /// only those paths from verified BC7 AssetBundles. Owned failures are
    /// terminal null results; they never reach the original PNG decoder.
    /// </summary>
    internal static class UiTextureLoadTexturePatch
    {
        internal const string HarmonyOwnerId =
            "de.strongholdeurope.private.ui-texture-load-v2";

        private static readonly object Gate = new object();
        private static readonly HashSet<string> TerminalPaths =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private static UiTextureRuntimeLane _lane;
        private static MethodInfo _target;
        private static MethodInfo _texturePathResolverTarget;
        private static UiTextureModIconBridge _modIconBridge;
        private static Action<string> _information;
        private static Action<string> _warning;
        private static int _ownedRequests;
        private static int _loaded;
        private static int _rejected;
        private static readonly System.Diagnostics.Stopwatch LaneClock =
            System.Diagnostics.Stopwatch.StartNew();
        private static long _lastTerminalMilliseconds = -1L;
        private static bool _summaryLogged;

        internal static long? CurrentTrackedBytes
        {
            get
            {
                lock (Gate)
                {
                    if (_target == null || _lane == null) return null;
                }
                try
                {
                    UiTextureBudgetSnapshot value =
                        UiTextureBudgetLedger.Process.Snapshot();
                    return checked(value.ReservedBytes + value.CommittedBytes);
                }
                catch
                {
                    return null;
                }
            }
        }

        internal static UiTextureRuntimeLane PrepareAndInstall(
            string pluginDirectory,
            UiTextureCompiledContract contract,
            Action<string> information,
            Action<string> warning)
        {
            if (contract == null) throw new ArgumentNullException("contract");
            if (!contract.Enabled) return null;
            try
            {
                UiTextureManifest manifest = UiTextureManifest.Load(
                    pluginDirectory,
                    contract);
                var lane = new UiTextureRuntimeLane(
                    manifest,
                    UiTextureBudgetLedger.Process,
                    new WindowsAssetStreamMemoryProbe(),
                    information,
                    warning);
                lane.RequireInstallationThread();
                Install(lane, information, warning);
                SafeLog(
                    information,
                    "SEDE_RUNTIME_V1|event=ui_texture_stream|status=ready"
                    + "|backend=assetbundle_bc7_v2"
                    + "|entries=" + manifest.Entries.Count
                    + "|resident_charge_bytes="
                    + manifest.DeclaredResidentChargeBytes);
                return lane;
            }
            catch (Exception exception)
            {
                SafeLog(
                    warning,
                    "SEDE_RUNTIME_V1|event=ui_texture_stream|status=unavailable"
                    + "|backend=assetbundle_bc7_v2"
                    + "|reason=" + exception.GetType().Name);
                throw;
            }
        }

        internal static void Install(UiTextureRuntimeLane lane)
        {
            Install(lane, null, null);
        }

        private static void Install(
            UiTextureRuntimeLane lane,
            Action<string> information,
            Action<string> warning)
        {
            if (lane == null) throw new ArgumentNullException("lane");
            lane.RequireInstallationThread();
            lock (Gate)
            {
                if (_lane != null
                    || _target != null
                    || _texturePathResolverTarget != null
                    || _modIconBridge != null)
                {
                    throw new InvalidOperationException(
                        "UI texture BC7 prefixes are already installed for this process");
                }

                MethodInfo target = ResolveExactTarget();
                MethodInfo prefix = ResolvePrefix();
                MethodInfo texturePathResolverTarget =
                    ResolveExactTexturePathTarget();
                MethodInfo texturePathResolverPrefix =
                    ResolveTexturePathPrefix();
                UiTextureModIconBridge modIconBridge =
                    UiTextureModIconBridge.CreateIfPresent(lane.Manifest);
                if (modIconBridge == null)
                {
                    throw new InvalidOperationException(
                        "Enabled UI texture manifest has no URI bridge entries");
                }

                _lane = lane;
                _modIconBridge = modIconBridge;
                _information = information;
                _warning = warning;
                try
                {
                    var harmony = new Harmony(HarmonyOwnerId);
                    UiTexturePatchTransaction.Apply(
                        delegate
                        {
                            harmony.Patch(
                                target,
                                prefix: new HarmonyMethod(prefix));
                        },
                        delegate
                        {
                            harmony.Patch(
                                texturePathResolverTarget,
                                prefix: new HarmonyMethod(
                                    texturePathResolverPrefix));
                        },
                        delegate { harmony.UnpatchSelf(); });
                    _target = target;
                    _texturePathResolverTarget = texturePathResolverTarget;
                }
                catch
                {
                    _lane = null;
                    _target = null;
                    _texturePathResolverTarget = null;
                    _modIconBridge = null;
                    _information = null;
                    _warning = null;
                    throw;
                }
            }
        }

        internal static void LogSummary()
        {
            lock (Gate)
            {
                if (_summaryLogged || _target == null) return;
                _summaryLogged = true;
                SafeLog(
                    _information,
                    "SEDE_RUNTIME_V1|event=ui_texture_summary|status=complete"
                    + "|backend=assetbundle_bc7_v2"
                    + "|requested=" + _ownedRequests
                    + "|loaded=" + _loaded
                    + "|rejected=" + _rejected);
            }
        }

        private static MethodInfo ResolvePrefix()
        {
            MethodInfo prefix = typeof(UiTextureLoadTexturePatch).GetMethod(
                "Prefix",
                BindingFlags.NonPublic
                    | BindingFlags.Static
                    | BindingFlags.DeclaredOnly,
                null,
                new[]
                {
                    typeof(string),
                    typeof(TextureFormat),
                    typeof(bool),
                    typeof(Texture2D).MakeByRefType(),
                },
                null);
            if (prefix == null || prefix.ReturnType != typeof(bool))
            {
                throw new MissingMethodException(
                    "Exact UI BC7 Harmony loader prefix was not found");
            }
            return prefix;
        }

        private static MethodInfo ResolveTexturePathPrefix()
        {
            MethodInfo prefix = typeof(UiTextureLoadTexturePatch).GetMethod(
                "TexturePathResolverPrefix",
                BindingFlags.NonPublic
                    | BindingFlags.Static
                    | BindingFlags.DeclaredOnly,
                null,
                new[]
                {
                    typeof(string),
                    typeof(string).MakeByRefType(),
                    typeof(bool).MakeByRefType(),
                },
                null);
            if (prefix == null || prefix.ReturnType != typeof(bool))
            {
                throw new MissingMethodException(
                    "Exact UI BC7 URI bridge prefix was not found");
            }
            return prefix;
        }

        private static Assembly ResolveExactShcdeseAssembly()
        {
            Assembly shcdese = null;
            Assembly[] loaded = AppDomain.CurrentDomain.GetAssemblies();
            for (int index = 0; index < loaded.Length; index++)
            {
                if (!string.Equals(
                        loaded[index].GetName().Name,
                        "SHCDESE",
                        StringComparison.Ordinal))
                {
                    continue;
                }
                if (shcdese != null && !ReferenceEquals(shcdese, loaded[index]))
                {
                    throw new MissingMethodException(
                        "Multiple SHCDESE assemblies are loaded; exact texture ownership is ambiguous");
                }
                shcdese = loaded[index];
            }
            if (shcdese == null)
            {
                throw new MissingMethodException(
                    "Exact SHCDESE assembly was not found");
            }
            return shcdese;
        }

        internal static MethodInfo ResolveExactTarget()
        {
            Assembly shcdese = ResolveExactShcdeseAssembly();
            Type type = shcdese.GetType(
                "SHCDESE.Extensions.TextureExtensions",
                false,
                false);
            if (type == null
                || !type.IsAbstract
                || !type.IsSealed
                || !string.Equals(
                    type.Assembly.GetName().Name,
                    "SHCDESE",
                    StringComparison.Ordinal))
            {
                throw new MissingMethodException(
                    "Exact SHCDESE.Extensions.TextureExtensions static type was not found");
            }

            MethodInfo method = type.GetMethod(
                "LoadTexture",
                BindingFlags.Public
                    | BindingFlags.Static
                    | BindingFlags.DeclaredOnly,
                null,
                new[] { typeof(string), typeof(TextureFormat), typeof(bool) },
                null);
            if (method == null
                || method.ReturnType != typeof(Texture2D)
                || method.IsGenericMethodDefinition)
            {
                throw new MissingMethodException(
                    "Exact TextureExtensions.LoadTexture(string,TextureFormat,bool) target was not found");
            }

            ParameterInfo[] parameters = method.GetParameters();
            if (parameters.Length != 3
                || !string.Equals(parameters[0].Name, "filePath", StringComparison.Ordinal)
                || !string.Equals(parameters[1].Name, "format", StringComparison.Ordinal)
                || !string.Equals(parameters[2].Name, "mipChain", StringComparison.Ordinal)
                || parameters[0].IsOptional
                || !parameters[1].IsOptional
                || !parameters[2].IsOptional
                || Convert.ToInt32(parameters[1].DefaultValue)
                    != (int)TextureFormat.RGBA32
                || !Equals(parameters[2].DefaultValue, false))
            {
                throw new MissingMethodException(
                    "TextureExtensions.LoadTexture defaults or parameter names differ from the pinned surface");
            }
            return method;
        }

        internal static MethodInfo ResolveExactTexturePathTarget()
        {
            Assembly shcdese = ResolveExactShcdeseAssembly();
            Type type = shcdese.GetType(
                "SHCDESE.API.GameAssetManagerAPI",
                false,
                false);
            if (type == null
                || !type.IsPublic
                || type.IsAbstract
                || !type.IsSealed
                || !string.Equals(
                    type.Assembly.GetName().Name,
                    "SHCDESE",
                    StringComparison.Ordinal))
            {
                throw new MissingMethodException(
                    "Exact SHCDESE.API.GameAssetManagerAPI sealed type was not found");
            }

            MethodInfo method = type.GetMethod(
                "TryResolveTexturePath",
                BindingFlags.NonPublic
                    | BindingFlags.Instance
                    | BindingFlags.DeclaredOnly,
                null,
                new[]
                {
                    typeof(string),
                    typeof(string).MakeByRefType(),
                },
                null);
            if (method == null
                || method.ReturnType != typeof(bool)
                || !method.IsPrivate
                || method.IsStatic
                || method.IsGenericMethodDefinition)
            {
                throw new MissingMethodException(
                    "Exact GameAssetManagerAPI.TryResolveTexturePath(string,out string) target was not found");
            }

            ParameterInfo[] parameters = method.GetParameters();
            if (parameters.Length != 2
                || !string.Equals(parameters[0].Name, "key", StringComparison.Ordinal)
                || parameters[0].IsOptional
                || parameters[0].IsOut
                || parameters[0].ParameterType != typeof(string)
                || !string.Equals(
                    parameters[1].Name,
                    "diskPath",
                    StringComparison.Ordinal)
                || parameters[1].IsOptional
                || !parameters[1].IsOut
                || parameters[1].ParameterType
                    != typeof(string).MakeByRefType())
            {
                throw new MissingMethodException(
                    "TryResolveTexturePath parameter names or out contract differ from the pinned surface");
            }
            return method;
        }

        private static bool TexturePathResolverPrefix(
            string key,
            ref string diskPath,
            ref bool __result)
        {
            UiTextureModIconBridge bridge = _modIconBridge;
            string resolved;
            if (bridge == null || !bridge.TryResolve(key, out resolved))
            {
                return true;
            }
            diskPath = resolved;
            __result = true;
            return false;
        }

        private static bool Prefix(
            string filePath,
            TextureFormat format,
            bool mipChain,
            ref Texture2D __result)
        {
            UiTextureRuntimeLane lane = _lane;
            if (lane == null) return true;
            try
            {
                Texture2D texture;
                UiTextureInterceptDisposition disposition = lane.Intercept(
                    filePath,
                    format,
                    mipChain,
                    out texture);
                if (disposition == UiTextureInterceptDisposition.ContinueOriginal)
                {
                    return true;
                }
                __result = texture;
                RecordTerminal(
                    lane,
                    filePath,
                    disposition
                        == UiTextureInterceptDisposition.SuppliedOwnedTexture);
                return false;
            }
            catch
            {
                return RejectOwnedFailClosed(lane, filePath, ref __result)
                    ? false
                    : true;
            }
        }

        private static bool RejectOwnedFailClosed(
            UiTextureRuntimeLane lane,
            string filePath,
            ref Texture2D result)
        {
            UiTextureManifestEntry entry;
            if (lane == null
                || !lane.Manifest.TryFindOwnedLoadPath(filePath, out entry))
            {
                return false;
            }
            result = null;
            RecordTerminal(entry, false);
            return true;
        }

        private static void RecordTerminal(
            UiTextureRuntimeLane lane,
            string path,
            bool loaded)
        {
            UiTextureManifestEntry entry;
            if (lane != null
                && lane.Manifest.TryFindOwnedLoadPath(path, out entry))
            {
                RecordTerminal(entry, loaded);
            }
        }

        private static void RecordTerminal(
            UiTextureManifestEntry entry,
            bool loaded)
        {
            if (entry == null) return;
            UiTextureRuntimeLane reclaimLane = null;
            Action<string> reclaimInformation = null;
            Action<string> reclaimWarning = null;
            lock (Gate)
            {
                if (!TerminalPaths.Add(entry.NoesisPath)) return;
                _ownedRequests++;
                if (loaded) _loaded++;
                else _rejected++;
                _lastTerminalMilliseconds = LaneClock.ElapsedMilliseconds;
                SafeLog(
                    loaded ? _information : _warning,
                    "SEDE_RUNTIME_V1|event=ui_texture_stream|status="
                    + (loaded ? "lazy_loaded" : "rejected_fail_closed")
                    + "|backend=assetbundle_bc7_v2"
                    + "|path=" + entry.NoesisPath);
                // The reclaim used to require all 114 manifest paths. That can
                // never happen: the mod logo has no Override PNG, so SHCDE-SE
                // never requests it, and one manifest entry short kept the
                // reclaim permanently unarmed. Arm on the first owned load
                // instead and let the host decide when the lane has settled;
                // that also survives a later demand-loading design, which
                // would never reach a fixed count either.
                if (_lane != null && _rejected == 0 && _loaded == 1)
                {
                    reclaimLane = _lane;
                    reclaimInformation = _information;
                    reclaimWarning = _warning;
                }
            }
            if (reclaimLane != null)
            {
                UiTextureBaseTextureReclaimer.Schedule(
                    reclaimLane,
                    reclaimInformation,
                    reclaimWarning);
            }
        }

        /// <summary>
        /// Snapshot of the owned-path tally for the reclaim host's settle
        /// detection. <paramref name="quietMilliseconds"/> is the age of the
        /// most recent terminal owned path.
        /// </summary>
        internal static void SnapshotProgress(
            out int loaded,
            out int rejected,
            out int expected,
            out double quietMilliseconds)
        {
            lock (Gate)
            {
                loaded = _loaded;
                rejected = _rejected;
                expected = _lane == null ? 0 : _lane.Manifest.Entries.Count;
                // Stopwatch, not DateTime: a system clock adjustment must not
                // make the lane look settled (or never settled).
                quietMilliseconds = _lastTerminalMilliseconds < 0
                    ? 0d
                    : LaneClock.ElapsedMilliseconds - _lastTerminalMilliseconds;
            }
        }

        private static void SafeLog(Action<string> sink, string message)
        {
            if (sink == null) return;
            try { sink(message); }
            catch { }
        }
    }
}
