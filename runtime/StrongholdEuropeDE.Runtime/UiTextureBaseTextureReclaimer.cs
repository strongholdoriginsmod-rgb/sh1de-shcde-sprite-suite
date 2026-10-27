using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Threading;
using UnityEngine;
using UnityEngine.Profiling;
using UnityObject = UnityEngine.Object;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Rewires built-in NoesisXaml Texture dependencies to the verified BC7
    /// replacements before running one unused-assets scan. Provider reference
    /// counts and dependency URIs remain untouched, so later Noesis teardown
    /// still balances exactly the registrations made by Noesis itself.
    /// </summary>
    internal static class UiTextureBaseTextureReclaimer
    {
        private const string HostName =
            "StrongholdEuropeDE.UiBaseTextureReclaimHost";
        private const int ExpectedManifestEntries = 114;
        private const int ExpectedBaseUris = 113;
        private const int ExpectedDependencies = 116;
        private const int ExpectedXamlOwners = 18;
        private const int ExpectedReadableRgba32 = 98;
        private const int ExpectedReadableRgb24 = 7;
        private const int ExpectedReadableBc7 = 8;

        private static UiTextureNoesisBridge _bridge;
        private static List<UnityObject> _retainedXamls;
        private static int _scheduleState;
        private static Dictionary<string, Texture2D> _watchedOverrides;
        private static List<UnityEngine.Texture> _displacedBaseTextures;

        internal static void Schedule(
            UiTextureRuntimeLane lane,
            Action<string> information,
            Action<string> warning)
        {
            if (lane == null) throw new ArgumentNullException("lane");
            lane.RequireInstallationThread();
            // The 1.44 editor canary keeps the direct BC7 loader active but
            // does not rewrite Noesis-owned base-texture lifetime until that
            // teardown path has been measured. This is an optional memory
            // optimization, not part of texture replacement.
            if (GeneratedFortificationContract.IsolatedCanary
                && string.Equals(
                    GeneratedAudioContract.ScriptExtenderVersion,
                    "1.44.0.0",
                    StringComparison.Ordinal))
            {
                if (Interlocked.CompareExchange(ref _scheduleState, 2, 0) == 0)
                {
                    Emit(
                        information,
                        "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                        + "|status=disabled"
                        + "|reason=shcdese_1_44_canary"
                        + "|bc7_loader=active");
                }
                return;
            }
            if (Interlocked.CompareExchange(ref _scheduleState, 1, 0) != 0)
            {
                return;
            }

            GameObject hostObject = null;
            try
            {
                hostObject = new GameObject(HostName);
                UnityObject.DontDestroyOnLoad(hostObject);
                hostObject.hideFlags = HideFlags.HideAndDontSave;
                UiTextureBaseTextureReclaimHost host =
                    hostObject.AddComponent<UiTextureBaseTextureReclaimHost>();
                host.Bind(lane, information, warning);
                Emit(
                    information,
                    "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                    + "|status=scheduled"
                    + "|owned_entries="
                    + lane.Manifest.Entries.Count.ToString(
                        CultureInfo.InvariantCulture)
                    + "|delay_late_frames=2");
                hostObject = null;
            }
            catch (Exception exception)
            {
                Volatile.Write(ref _scheduleState, 2);
                Emit(
                    warning,
                    "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                    + "|status=unavailable"
                    + "|phase=schedule"
                    + "|reason=" + Describe(exception));
            }
            finally
            {
                if (hostObject != null)
                {
                    try { UnityObject.Destroy(hostObject); }
                    catch { }
                }
            }
        }

        /// <summary>
        /// Requires that Noesis has already drained its own pending
        /// texture-info requests.
        /// </summary>
        /// <remarks>
        /// This replaces an earlier <c>UpdateTextures()</c> call that was
        /// labelled a "native pointer flush". It was not one. UpdateTextures
        /// stores nothing when <c>_texturesRequested</c> is empty and ends in
        /// an unconditional Clear(), and its only legitimate caller is
        /// NoesisRenderer.UpdateRenderTree. Calling it out of band could
        /// consume a request that Noesis raised in this very frame and clear
        /// it before the render-tree update that was going to use it — the
        /// LateUpdate order between NoesisView and this host is undefined.
        /// Observing that the queue is already empty proves the same property
        /// without touching Noesis' state.
        /// </remarks>
        internal static bool TryRequireQuiescentRequests(out string failure)
        {
            failure = null;
            try
            {
                int pending = ResolveBridge().GetPendingRequestCount();
                if (pending != 0)
                {
                    failure = "Noesis still has "
                        + pending.ToString(CultureInfo.InvariantCulture)
                        + " pending texture-info requests";
                    return false;
                }
                return true;
            }
            catch (Exception exception)
            {
                failure = "Noesis pending-request probe failed: "
                    + Describe(exception);
                return false;
            }
        }

        internal static bool TryRewireBaseDependencies(
            UiTextureRuntimeLane lane,
            out UiTextureBaseReclaimResult result,
            out string failure,
            out bool retryable)
        {
            result = null;
            failure = null;
            // Safe by default: every early rejection below leaves the XAML
            // arrays untouched, so a later attempt starts from a clean state.
            retryable = true;
            if (lane == null)
            {
                failure = "UI texture lane is unavailable";
                return false;
            }
            if (!lane.IsMainThread)
            {
                failure = "base dependency release was requested off the Unity main thread";
                return false;
            }
            if (lane.Manifest.Entries.Count < ExpectedBaseUris)
            {
                failure = "UI manifest is smaller than the pinned base provenance";
                return false;
            }

            UiTextureNoesisBridge bridge;
            IDictionary providerTextures;
            try
            {
                bridge = ResolveBridge();
                providerTextures = bridge.GetProviderTextures();
            }
            catch (Exception exception)
            {
                failure = "Noesis provider dictionary read failed: "
                    + Describe(exception);
                return false;
            }

            // A manifest entry that is never requested (the mod logo has no
            // Override PNG, so SHCDE-SE never asks for it) must not veto the
            // reclaim. Skip what is not loaded; the provenance pin below still
            // requires the full 113/116/18 base shape, so an entry that WAS
            // expected and is missing still fails closed there.
            var loaded = new Dictionary<string, Texture2D>(StringComparer.Ordinal);
            int skipped = 0;
            for (int index = 0; index < lane.Manifest.Entries.Count; index++)
            {
                UiTextureManifestEntry entry = lane.Manifest.Entries[index];
                Texture2D texture;
                if (!lane.TryGetLoadedTexture(entry.NoesisPath, out texture)
                    || texture == null)
                {
                    skipped++;
                    continue;
                }
                loaded.Add(entry.NoesisPath, texture);
            }
            if (loaded.Count < ExpectedBaseUris)
            {
                failure = "fewer owned BC7 textures are loaded than the pinned base provenance requires";
                return false;
            }

            UnityObject[] xamls;
            try
            {
                xamls = bridge.FindLoadedXamls();
            }
            catch (Exception exception)
            {
                failure = "NoesisXaml inventory failed: " + Describe(exception);
                return false;
            }
            if (xamls == null || xamls.Length == 0)
            {
                failure = "no loaded NoesisXaml assets were found";
                return false;
            }

            var groups = new Dictionary<string, UiTextureBaseUriPlan>(
                StringComparer.Ordinal);
            var ownerIds = new HashSet<int>();
            var ownerObjects = new List<UnityObject>();
            var baseTextureIds = new HashSet<int>();
            var displacedBaseTextures = new List<UnityEngine.Texture>();
            long candidateRuntimeBytes = 0;
            int readableRgba32 = 0;
            int readableRgb24 = 0;
            int readableBc7 = 0;
            for (int xamlIndex = 0; xamlIndex < xamls.Length; xamlIndex++)
            {
                UnityObject owner = xamls[xamlIndex];
                if (owner == null) continue;

                Array dependencies;
                try
                {
                    dependencies = bridge.GetTextures(owner);
                }
                catch (Exception exception)
                {
                    failure = "NoesisXaml texture dependency read failed: "
                        + Describe(exception);
                    return false;
                }
                if (dependencies == null) continue;

                for (int dependencyIndex = 0;
                    dependencyIndex < dependencies.Length;
                    dependencyIndex++)
                {
                    object dependency = dependencies.GetValue(dependencyIndex);
                    string dependencyUri = bridge.GetDependencyUri(dependency);
                    UiTextureManifestEntry entry;
                    string ignored;
                    if (!lane.Manifest.TryResolveNoesisPath(
                            dependencyUri,
                            out entry,
                            out ignored))
                    {
                        continue;
                    }

                    Texture2D ownedOverride;
                    if (!loaded.TryGetValue(entry.NoesisPath, out ownedOverride))
                    {
                        failure = "owned Noesis dependency resolved without a loaded slot";
                        return false;
                    }
                    UiTextureBaseUriPlan group;
                    if (!groups.TryGetValue(entry.NoesisPath, out group))
                    {
                        group = new UiTextureBaseUriPlan(
                            entry.NoesisPath,
                            ownedOverride);
                        groups.Add(entry.NoesisPath, group);
                    }
                    UnityEngine.Texture baseTexture =
                        bridge.GetDependencyTexture(dependency);
                    group.Dependencies.Add(
                        new UiTextureBaseDependency(
                            owner,
                            dependencyIndex,
                            dependency,
                            dependencyUri,
                            baseTexture));
                    int ownerId = owner.GetInstanceID();
                    if (ownerIds.Add(ownerId)) ownerObjects.Add(owner);
                    if (baseTexture != null
                        && !ReferenceEquals(baseTexture, ownedOverride))
                    {
                        int instanceId = baseTexture.GetInstanceID();
                        if (baseTextureIds.Add(instanceId))
                        {
                            displacedBaseTextures.Add(baseTexture);
                            Texture2D baseTexture2D = baseTexture as Texture2D;
                            if (baseTexture2D == null || !baseTexture2D.isReadable)
                            {
                                failure = "matched built-in UI base texture is not a readable Texture2D";
                                return false;
                            }
                            // The override is BC7 and therefore padded up to
                            // the 4-px block grid; 49 of the 113 are exactly
                            // +2 px in both axes. Equality would be wrong here,
                            // ceil4 is the actual contract.
                            if (Ceil4(baseTexture2D.width) != ownedOverride.width
                                || Ceil4(baseTexture2D.height) != ownedOverride.height)
                            {
                                failure = "base texture does not match the owned override under the 4-px block contract";
                                return false;
                            }
                            if (baseTexture2D.format == TextureFormat.RGBA32)
                            {
                                readableRgba32++;
                            }
                            else if (baseTexture2D.format == TextureFormat.RGB24)
                            {
                                readableRgb24++;
                            }
                            else if (baseTexture2D.format == TextureFormat.BC7)
                            {
                                readableBc7++;
                            }
                            else
                            {
                                failure = "matched built-in UI base texture has an unexpected format";
                                return false;
                            }
                            try
                            {
                                candidateRuntimeBytes = checked(
                                    candidateRuntimeBytes
                                    + Profiler.GetRuntimeMemorySizeLong(baseTexture));
                            }
                            catch
                            {
                                // The rewire contract does not depend on this
                                // diagnostic byte estimate.
                            }
                        }
                    }
                }
            }
            if (groups.Count == 0)
            {
                failure = "no manifest-owned built-in Noesis dependencies were found";
                return false;
            }

            int dependencyCount = 0;
            foreach (UiTextureBaseUriPlan group in groups.Values)
            {
                dependencyCount += group.Dependencies.Count;
            }
            // No shipped NoesisXaml declares sprite dependencies, and the
            // Sprite overload of Register uses a sub-rect. If a future game
            // patch introduces one, fail closed instead of silently rewiring
            // under the wrong rect semantics.
            for (int ownerIndex = 0; ownerIndex < ownerObjects.Count; ownerIndex++)
            {
                int spriteCount;
                try
                {
                    spriteCount = bridge.GetSpriteCount(ownerObjects[ownerIndex]);
                }
                catch (Exception exception)
                {
                    failure = "NoesisXaml sprite dependency read failed: "
                        + Describe(exception);
                    return false;
                }
                if (spriteCount != 0)
                {
                    failure = "a rewired NoesisXaml declares sprite dependencies";
                    return false;
                }
            }

            if (groups.Count != ExpectedBaseUris
                || dependencyCount != ExpectedDependencies
                || ownerIds.Count != ExpectedXamlOwners
                || baseTextureIds.Count != ExpectedBaseUris
                || readableRgba32 != ExpectedReadableRgba32
                || readableRgb24 != ExpectedReadableRgb24
                || readableBc7 != ExpectedReadableBc7)
            {
                failure = "loaded Noesis UI base provenance differs from the pinned target";
                return false;
            }

            long providerRefsPreserved = 0;
            foreach (UiTextureBaseUriPlan group in groups.Values)
            {
                UiTextureProviderSnapshot providerValue;
                if (!bridge.TryGetProviderValue(
                        providerTextures,
                        group.Uri,
                        out providerValue))
                {
                    failure = "Noesis provider has no entry for an owned URI";
                    return false;
                }
                string contractFailure;
                if (!UiTextureBaseReclaimContract.TryValidateProviderState(
                        providerValue.Refs,
                        ReferenceEquals(
                            providerValue.Texture,
                            group.OwnedOverride),
                        out contractFailure))
                {
                    failure = contractFailure;
                    return false;
                }
                group.ProviderBefore = providerValue;
                try
                {
                    providerRefsPreserved = checked(
                        providerRefsPreserved + providerValue.Refs);
                }
                catch (OverflowException)
                {
                    failure = "Noesis provider reference total overflowed";
                    return false;
                }
            }

            var changed = new List<UiTextureBaseDependency>();
            try
            {
                foreach (UiTextureBaseUriPlan group in groups.Values)
                {
                    for (int index = 0;
                        index < group.Dependencies.Count;
                        index++)
                    {
                        UiTextureBaseDependency dependency =
                            group.Dependencies[index];
                        Array current = bridge.GetTextures(dependency.Owner);
                        if (current == null
                            || dependency.Index < 0
                            || dependency.Index >= current.Length)
                        {
                            throw new InvalidOperationException(
                                "NoesisXaml dependency array changed during the rewire transaction");
                        }
                        object currentDependency =
                            current.GetValue(dependency.Index);
                        if (!string.Equals(
                                bridge.GetDependencyUri(currentDependency),
                                dependency.OriginalUri,
                                StringComparison.Ordinal)
                            || !ReferenceEquals(
                                bridge.GetDependencyTexture(currentDependency),
                                dependency.OriginalTexture))
                        {
                            throw new InvalidOperationException(
                                "NoesisXaml dependency changed during the rewire transaction");
                        }
                        object rewired = RuntimeHelpers.GetObjectValue(
                            currentDependency);
                        bridge.SetDependencyTexture(
                            rewired,
                            group.OwnedOverride);
                        current.SetValue(rewired, dependency.Index);
                        changed.Add(dependency);
                    }
                    RequireProviderState(bridge, providerTextures, group);
                }
                RetainXamls(ownerObjects);
            }
            catch (Exception exception)
            {
                // A restore that silently fails must not report the same
                // string as a complete rollback: the XAML arrays would be left
                // in a mixed state with no diagnostic.
                int restored = 0;
                int failedRestores = 0;
                for (int index = changed.Count - 1; index >= 0; index--)
                {
                    UiTextureBaseDependency dependency = changed[index];
                    try
                    {
                        Array current = bridge.GetTextures(dependency.Owner);
                        if (current != null
                            && dependency.Index >= 0
                            && dependency.Index < current.Length)
                        {
                            current.SetValue(
                                dependency.Original,
                                dependency.Index);
                            restored++;
                        }
                        else
                        {
                            failedRestores++;
                        }
                    }
                    catch
                    {
                        failedRestores++;
                    }
                }
                // A complete rollback restores the pre-rewire state, so a
                // retry is safe. An incomplete one leaves the arrays mixed:
                // the rewire is not idempotent (a second pass would see
                // already-rewired entries, find no base textures and fail the
                // provenance pin), so that case must be terminal.
                retryable = failedRestores == 0;
                failure = (failedRestores == 0
                        ? "base dependency rewire rolled back"
                        : "base dependency rewire ROLLBACK INCOMPLETE")
                    + " restored:"
                    + restored.ToString(CultureInfo.InvariantCulture)
                    + " failed:"
                    + failedRestores.ToString(CultureInfo.InvariantCulture)
                    + " cause:"
                    + Describe(exception);
                return false;
            }

            var watched = new Dictionary<string, Texture2D>(StringComparer.Ordinal);
            long minimumProviderRefs = long.MaxValue;
            foreach (UiTextureBaseUriPlan plan in groups.Values)
            {
                watched[plan.Uri] = plan.OwnedOverride;
                if (plan.ProviderBefore.Refs < minimumProviderRefs)
                {
                    minimumProviderRefs = plan.ProviderBefore.Refs;
                }
            }
            _watchedOverrides = watched;
            _displacedBaseTextures = displacedBaseTextures;

            result = new UiTextureBaseReclaimResult(
                groups.Count,
                dependencyCount,
                ownerIds.Count,
                baseTextureIds.Count,
                candidateRuntimeBytes,
                providerRefsPreserved,
                minimumProviderRefs == long.MaxValue ? 0L : minimumProviderRefs,
                readableRgba32,
                readableRgb24,
                readableBc7);
            return true;
        }

        /// <summary>
        /// Re-verifies that every rewired URI still resolves to its owned BC7
        /// override and repairs the provider entry in place when it does not.
        /// </summary>
        /// <remarks>
        /// SHCDE-SE registers each mod texture exactly once per process
        /// (_attemptedTextureUris) and never unregisters, so any displacement
        /// - a XAML re-running _RegisterDependencies, a third-party write - is
        /// permanent and silent without this. The repair writes the boxed
        /// provider Value directly instead of calling Register(), which would
        /// increment refs and unbalance the ledger forever.
        /// </remarks>
        internal static bool TryVerifyAndRepair(
            out int checkedUris,
            out int repaired,
            out string failure)
        {
            checkedUris = 0;
            repaired = 0;
            failure = null;
            Dictionary<string, Texture2D> watched = _watchedOverrides;
            if (watched == null || watched.Count == 0)
            {
                failure = "no rewired URIs are being watched";
                return false;
            }
            try
            {
                UiTextureNoesisBridge bridge = ResolveBridge();
                IDictionary providerTextures = bridge.GetProviderTextures();
                foreach (KeyValuePair<string, Texture2D> pair in watched)
                {
                    checkedUris++;
                    Texture2D owned = pair.Value;
                    if (owned == null)
                    {
                        // Unity fake-null: the override itself is gone. There
                        // is nothing left to repair with.
                        failure = "an owned BC7 override was destroyed";
                        return false;
                    }
                    UiTextureProviderSnapshot current;
                    bool present = bridge.TryGetProviderValue(
                        providerTextures,
                        pair.Key,
                        out current);
                    if (present
                        && current.Refs >= 1
                        && ReferenceEquals(current.Texture, owned))
                    {
                        continue;
                    }
                    if (!present)
                    {
                        failure = "a watched provider entry disappeared";
                        return false;
                    }
                    bridge.RepairProviderTexture(
                        providerTextures,
                        pair.Key,
                        owned);
                    repaired++;
                }
                return true;
            }
            catch (Exception exception)
            {
                failure = "provider watchdog failed: " + Describe(exception);
                return false;
            }
        }

        /// <summary>
        /// Releases exactly the base textures the rewire displaced, one by one.
        /// </summary>
        /// <remarks>
        /// Resources.UnloadAsset only ever touches the object it is given, so
        /// unlike a process-global scan it cannot collect an AssetStream
        /// baseline, a page mask, or anything else this lane does not own. Each
        /// candidate is re-verified immediately before release: it must still be
        /// a live Texture2D, and no manifest-owned override may point at it.
        /// </remarks>
        internal static bool TryReleaseDisplacedBaseTextures(
            out int released,
            out int skipped,
            out string failure)
        {
            released = 0;
            skipped = 0;
            failure = null;
            List<UnityEngine.Texture> candidates = _displacedBaseTextures;
            Dictionary<string, Texture2D> owned = _watchedOverrides;
            if (candidates == null || candidates.Count == 0)
            {
                failure = "no displaced base textures were recorded";
                return false;
            }
            if (owned == null || owned.Count == 0)
            {
                failure = "no owned overrides are being watched";
                return false;
            }

            var ownedIds = new HashSet<int>();
            foreach (KeyValuePair<string, Texture2D> pair in owned)
            {
                if (pair.Value != null)
                {
                    ownedIds.Add(pair.Value.GetInstanceID());
                }
            }

            for (int index = 0; index < candidates.Count; index++)
            {
                UnityEngine.Texture candidate = candidates[index];
                if (candidate == null)
                {
                    // Unity fake-null: already gone.
                    skipped++;
                    continue;
                }
                if (ownedIds.Contains(candidate.GetInstanceID()))
                {
                    // Would destroy one of our own overrides. Never.
                    skipped++;
                    continue;
                }
                try
                {
                    Resources.UnloadAsset(candidate);
                    released++;
                }
                catch (Exception exception)
                {
                    skipped++;
                    if (failure == null)
                    {
                        failure = Describe(exception);
                    }
                }
            }
            _displacedBaseTextures = null;
            if (released == 0)
            {
                failure = failure ?? "no base texture could be released";
                return false;
            }
            failure = null;
            return true;
        }

        internal static void MarkTerminal()
        {
            Volatile.Write(ref _scheduleState, 2);
        }

        private static int Ceil4(int value)
        {
            return value <= 0 ? value : (value + 3) & ~3;
        }

        private static UiTextureNoesisBridge ResolveBridge()
        {
            UiTextureNoesisBridge bridge = _bridge;
            if (bridge != null) return bridge;
            bridge = UiTextureNoesisBridge.CreateExact();
            _bridge = bridge;
            return bridge;
        }

        private static void RetainXamls(List<UnityObject> owners)
        {
            if (owners == null || owners.Count == 0)
            {
                throw new InvalidOperationException(
                    "no rewired NoesisXaml owner can be retained");
            }
            // Resources.UnloadUnusedAssets considers managed static roots. Keep
            // rewired ScriptableObjects alive so an unregistered duplicate XAML
            // cannot reload its serialized base Texture PPtr later.
            _retainedXamls = new List<UnityObject>(owners);
        }

        private static void RequireProviderState(
            UiTextureNoesisBridge bridge,
            IDictionary providerTextures,
            UiTextureBaseUriPlan group)
        {
            UiTextureProviderSnapshot current;
            if (!bridge.TryGetProviderValue(
                    providerTextures,
                    group.Uri,
                    out current)
                || current.Refs != group.ProviderBefore.Refs
                || !ReferenceEquals(current.Texture, group.OwnedOverride))
            {
                throw new InvalidOperationException(
                    "Noesis provider state changed during the rewire transaction");
            }
        }

        internal static string Describe(Exception exception)
        {
            if (exception == null) return "unknown";
            if (exception is TargetInvocationException
                && exception.InnerException != null)
            {
                exception = exception.InnerException;
            }
            string value = exception.GetType().Name;
            if (!string.IsNullOrWhiteSpace(exception.Message))
            {
                value += ":" + exception.Message;
            }
            value = value.Replace('|', '/').Replace('\r', ' ').Replace('\n', ' ');
            return value.Length <= 192 ? value : value.Substring(0, 192);
        }

        internal static void Emit(Action<string> sink, string value)
        {
            if (sink == null) return;
            try { sink(value); }
            catch { }
        }

        private sealed class UiTextureBaseUriPlan
        {
            internal UiTextureBaseUriPlan(string uri, Texture2D ownedOverride)
            {
                Uri = uri;
                OwnedOverride = ownedOverride;
                Dependencies = new List<UiTextureBaseDependency>();
            }

            internal string Uri { get; private set; }
            internal Texture2D OwnedOverride { get; private set; }
            internal List<UiTextureBaseDependency> Dependencies { get; private set; }
            internal UiTextureProviderSnapshot ProviderBefore { get; set; }
        }

        private sealed class UiTextureBaseDependency
        {
            internal UiTextureBaseDependency(
                UnityObject owner,
                int index,
                object original,
                string originalUri,
                UnityEngine.Texture originalTexture)
            {
                Owner = owner;
                Index = index;
                Original = original;
                OriginalUri = originalUri;
                OriginalTexture = originalTexture;
            }

            internal UnityObject Owner { get; private set; }
            internal int Index { get; private set; }
            internal object Original { get; private set; }
            internal string OriginalUri { get; private set; }
            internal UnityEngine.Texture OriginalTexture { get; private set; }
        }
    }

    internal sealed class UiTextureNoesisBridge
    {
        private const string NoesisAssemblyName = "Noesis.NoesisGUI";

        private readonly Type _xamlType;
        private readonly Type _dependencyType;
        private readonly Type _providerValueType;
        private readonly object _provider;
        private readonly FieldInfo _xamlTexturesField;
        private readonly FieldInfo _xamlSpritesField;
        private readonly FieldInfo _dependencyUriField;
        private readonly FieldInfo _dependencyTextureField;
        private readonly FieldInfo _providerTexturesField;
        private readonly FieldInfo _providerRefsField;
        private readonly FieldInfo _providerTextureField;
        private readonly FieldInfo _providerRectField;
        private readonly FieldInfo _providerRequestedField;
        private readonly MethodInfo _providerUpdateTextures;

        private UiTextureNoesisBridge(
            Type xamlType,
            Type dependencyType,
            Type providerValueType,
            object provider,
            FieldInfo xamlTexturesField,
            FieldInfo xamlSpritesField,
            FieldInfo dependencyUriField,
            FieldInfo dependencyTextureField,
            FieldInfo providerTexturesField,
            FieldInfo providerRefsField,
            FieldInfo providerTextureField,
            FieldInfo providerRectField,
            FieldInfo providerRequestedField,
            MethodInfo providerUpdateTextures)
        {
            _xamlType = xamlType;
            _dependencyType = dependencyType;
            _providerValueType = providerValueType;
            _provider = provider;
            _xamlTexturesField = xamlTexturesField;
            _xamlSpritesField = xamlSpritesField;
            _dependencyUriField = dependencyUriField;
            _dependencyTextureField = dependencyTextureField;
            _providerTexturesField = providerTexturesField;
            _providerRefsField = providerRefsField;
            _providerTextureField = providerTextureField;
            _providerRectField = providerRectField;
            _providerRequestedField = providerRequestedField;
            _providerUpdateTextures = providerUpdateTextures;
        }

        internal static UiTextureNoesisBridge CreateExact()
        {
            Type xamlType = Type.GetType(
                "NoesisXaml, " + NoesisAssemblyName,
                false);
            Type providerType = Type.GetType(
                "NoesisTextureProvider, " + NoesisAssemblyName,
                false);
            if (xamlType == null || providerType == null)
            {
                throw new TypeLoadException(
                    "pinned NoesisXaml/NoesisTextureProvider types were not found");
            }
            if (!typeof(UnityObject).IsAssignableFrom(xamlType))
            {
                throw new TypeLoadException(
                    "NoesisXaml is not a UnityEngine.Object");
            }

            FieldInfo xamlTexturesField = RequireField(
                xamlType,
                "textures",
                BindingFlags.Instance
                    | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            if (!xamlTexturesField.FieldType.IsArray)
            {
                throw new MissingFieldException(
                    "exact NoesisXaml.textures array was not found");
            }
            FieldInfo xamlSpritesField = RequireField(
                xamlType,
                "sprites",
                BindingFlags.Instance
                    | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            if (!xamlSpritesField.FieldType.IsArray)
            {
                throw new MissingFieldException(
                    "exact NoesisXaml.sprites array was not found");
            }
            Type dependencyType =
                xamlTexturesField.FieldType.GetElementType();
            if (dependencyType == null || !dependencyType.IsValueType)
            {
                throw new TypeLoadException(
                    "NoesisXaml.Texture value type was not found");
            }
            FieldInfo dependencyUriField = RequireField(
                dependencyType,
                "uri",
                BindingFlags.Instance
                    | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            FieldInfo dependencyTextureField = RequireField(
                dependencyType,
                "texture",
                BindingFlags.Instance
                    | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            if (dependencyUriField.FieldType != typeof(string)
                || dependencyTextureField.FieldType != typeof(UnityEngine.Texture))
            {
                throw new MissingFieldException(
                    "NoesisXaml.Texture uri/texture field contract differs");
            }

            FieldInfo providerInstanceField = RequireField(
                providerType,
                "instance",
                BindingFlags.Static
                    | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            if (providerInstanceField.FieldType != providerType)
            {
                throw new MissingFieldException(
                    "exact NoesisTextureProvider.instance field was not found");
            }
            object provider = providerInstanceField.GetValue(null);
            if (provider == null)
            {
                throw new InvalidOperationException(
                    "NoesisTextureProvider.instance is null");
            }
            FieldInfo providerTexturesField = RequireField(
                providerType,
                "_textures",
                BindingFlags.Instance
                    | BindingFlags.NonPublic
                    | BindingFlags.DeclaredOnly);
            Type dictionaryType = providerTexturesField.FieldType;
            if (!typeof(IDictionary).IsAssignableFrom(dictionaryType)
                || !dictionaryType.IsGenericType)
            {
                throw new MissingFieldException(
                    "exact NoesisTextureProvider._textures dictionary was not found");
            }
            Type[] dictionaryArguments = dictionaryType.GetGenericArguments();
            if (dictionaryArguments.Length != 2
                || dictionaryArguments[0] != typeof(string))
            {
                throw new TypeLoadException(
                    "Noesis provider dictionary key contract differs");
            }
            Type providerValueType = dictionaryArguments[1];
            FieldInfo providerRefsField = RequireField(
                providerValueType,
                "refs",
                BindingFlags.Instance
                    | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            FieldInfo providerTextureField = RequireField(
                providerValueType,
                "texture",
                BindingFlags.Instance
                    | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            if (providerRefsField.FieldType != typeof(int)
                || providerTextureField.FieldType != typeof(UnityEngine.Texture))
            {
                throw new MissingFieldException(
                    "Noesis provider Value refs/texture contract differs");
            }
            FieldInfo providerRectField = RequireField(
                providerValueType,
                "rect",
                BindingFlags.Instance
                    | BindingFlags.Public
                    | BindingFlags.DeclaredOnly);
            FieldInfo providerRequestedField = RequireField(
                providerType,
                "_texturesRequested",
                BindingFlags.Instance
                    | BindingFlags.NonPublic
                    | BindingFlags.DeclaredOnly);
            if (!typeof(ICollection).IsAssignableFrom(
                    providerRequestedField.FieldType))
            {
                throw new MissingFieldException(
                    "exact NoesisTextureProvider._texturesRequested list was not found");
            }
            MethodInfo updateTextures = providerType.GetMethod(
                "UpdateTextures",
                BindingFlags.Instance
                    | BindingFlags.Public
                    | BindingFlags.DeclaredOnly,
                null,
                Type.EmptyTypes,
                null);
            if (updateTextures == null || updateTextures.ReturnType != typeof(void))
            {
                throw new MissingMethodException(
                    "exact NoesisTextureProvider.UpdateTextures() was not found");
            }

            return new UiTextureNoesisBridge(
                xamlType,
                dependencyType,
                providerValueType,
                provider,
                xamlTexturesField,
                xamlSpritesField,
                dependencyUriField,
                dependencyTextureField,
                providerTexturesField,
                providerRefsField,
                providerTextureField,
                providerRectField,
                providerRequestedField,
                updateTextures);
        }

        internal UnityObject[] FindLoadedXamls()
        {
            return Resources.FindObjectsOfTypeAll(_xamlType);
        }

        internal Array GetTextures(UnityObject owner)
        {
            if (owner == null || !_xamlType.IsInstanceOfType(owner))
            {
                throw new ArgumentException("object is not an exact NoesisXaml");
            }
            return _xamlTexturesField.GetValue(owner) as Array;
        }

        internal int GetSpriteCount(UnityObject owner)
        {
            if (owner == null || !_xamlType.IsInstanceOfType(owner))
            {
                throw new ArgumentException("object is not an exact NoesisXaml");
            }
            var sprites = _xamlSpritesField.GetValue(owner) as Array;
            return sprites == null ? 0 : sprites.Length;
        }

        internal string GetDependencyUri(object dependency)
        {
            RequireDependency(dependency);
            return _dependencyUriField.GetValue(dependency) as string;
        }

        internal UnityEngine.Texture GetDependencyTexture(object dependency)
        {
            RequireDependency(dependency);
            return _dependencyTextureField.GetValue(dependency)
                as UnityEngine.Texture;
        }

        internal void SetDependencyTexture(
            object dependency,
            UnityEngine.Texture texture)
        {
            RequireDependency(dependency);
            if (texture == null) throw new ArgumentNullException("texture");
            _dependencyTextureField.SetValue(dependency, texture);
        }

        internal IDictionary GetProviderTextures()
        {
            IDictionary textures = _providerTexturesField.GetValue(_provider)
                as IDictionary;
            if (textures == null)
            {
                throw new InvalidOperationException(
                    "Noesis provider dictionary is unavailable");
            }
            return textures;
        }

        internal bool TryGetProviderValue(
            IDictionary textures,
            string uri,
            out UiTextureProviderSnapshot snapshot)
        {
            snapshot = default(UiTextureProviderSnapshot);
            if (textures == null || string.IsNullOrEmpty(uri)) return false;
            if (!textures.Contains(uri)) return false;
            object value = textures[uri];
            if (value == null || value.GetType() != _providerValueType)
            {
                throw new InvalidOperationException(
                    "Noesis provider dictionary Value type differs");
            }
            snapshot = new UiTextureProviderSnapshot(
                (int)_providerRefsField.GetValue(value),
                _providerTextureField.GetValue(value) as UnityEngine.Texture);
            return true;
        }

        internal int GetPendingRequestCount()
        {
            var requested = _providerRequestedField.GetValue(_provider)
                as ICollection;
            if (requested == null)
            {
                throw new InvalidOperationException(
                    "Noesis provider request list is unavailable");
            }
            return requested.Count;
        }

        /// <summary>
        /// Repairs one provider entry in place, preserving <c>refs</c>.
        /// Noesis' own Register() would increment the reference count on every
        /// repair (decompiled Register: refs++ before assigning texture/rect),
        /// which would permanently unbalance the ledger against the
        /// _UnregisterDependencies side and pin the URI forever.
        /// </summary>
        internal void RepairProviderTexture(
            IDictionary textures,
            string uri,
            Texture2D ownedOverride)
        {
            if (textures == null) throw new ArgumentNullException("textures");
            if (string.IsNullOrEmpty(uri)) throw new ArgumentNullException("uri");
            if (ownedOverride == null) throw new ArgumentNullException("ownedOverride");
            if (!textures.Contains(uri))
            {
                throw new InvalidOperationException(
                    "Noesis provider has no entry for the owned URI");
            }
            object value = textures[uri];
            if (value == null || value.GetType() != _providerValueType)
            {
                throw new InvalidOperationException(
                    "Noesis provider dictionary Value type differs");
            }
            object boxed = RuntimeHelpers.GetObjectValue(value);
            _providerTextureField.SetValue(boxed, ownedOverride);
            if (_providerRectField != null)
            {
                _providerRectField.SetValue(
                    boxed,
                    CreateRect(ownedOverride.width, ownedOverride.height));
            }
            textures[uri] = boxed;
        }

        private object CreateRect(int width, int height)
        {
            // Noesis' Int32Rect exposes a public (x, y, width, height)
            // constructor; use it rather than poking members, so the clamping
            // it applies to width/height stays in one place.
            ConstructorInfo constructor = _providerRectField.FieldType.GetConstructor(
                new[] { typeof(int), typeof(int), typeof(int), typeof(int) });
            if (constructor == null)
            {
                throw new MissingMethodException(
                    "exact Noesis Int32Rect(int,int,int,int) constructor was not found");
            }
            return constructor.Invoke(new object[] { 0, 0, width, height });
        }

        private void RequireDependency(object dependency)
        {
            if (dependency == null || dependency.GetType() != _dependencyType)
            {
                throw new InvalidOperationException(
                    "NoesisXaml.Texture dependency type differs");
            }
        }

        private static FieldInfo RequireField(
            Type owner,
            string name,
            BindingFlags bindingFlags)
        {
            FieldInfo field = owner.GetField(name, bindingFlags);
            if (field == null)
            {
                throw new MissingFieldException(owner.FullName, name);
            }
            return field;
        }
    }

    internal struct UiTextureProviderSnapshot
    {
        internal UiTextureProviderSnapshot(
            int refs,
            UnityEngine.Texture texture)
        {
            Refs = refs;
            Texture = texture;
        }

        internal int Refs { get; private set; }
        internal UnityEngine.Texture Texture { get; private set; }
    }

    internal sealed class UiTextureBaseReclaimResult
    {
        internal UiTextureBaseReclaimResult(
            int ownedUriCount,
            int dependencyCount,
            int xamlCount,
            int candidateTextureCount,
            long candidateRuntimeBytes,
            long providerRefsPreserved,
            long minimumProviderRefs,
            int readableRgba32,
            int readableRgb24,
            int readableBc7)
        {
            OwnedUriCount = ownedUriCount;
            DependencyCount = dependencyCount;
            XamlCount = xamlCount;
            CandidateTextureCount = candidateTextureCount;
            CandidateRuntimeBytes = candidateRuntimeBytes;
            ProviderRefsPreserved = providerRefsPreserved;
            MinimumProviderRefs = minimumProviderRefs;
            ReadableRgba32 = readableRgba32;
            ReadableRgb24 = readableRgb24;
            ReadableBc7 = readableBc7;
        }

        internal int OwnedUriCount { get; private set; }
        internal int DependencyCount { get; private set; }
        internal int XamlCount { get; private set; }
        internal int CandidateTextureCount { get; private set; }
        internal long CandidateRuntimeBytes { get; private set; }
        internal long ProviderRefsPreserved { get; private set; }
        internal long MinimumProviderRefs { get; private set; }
        internal int ReadableRgba32 { get; private set; }
        internal int ReadableRgb24 { get; private set; }
        internal int ReadableBc7 { get; private set; }
    }

    internal sealed class UiTextureBaseTextureReclaimHost : MonoBehaviour
    {
        private UiTextureRuntimeLane _lane;
        private Action<string> _information;
        private Action<string> _warning;
        private int _lateFrames;
        private bool _rewired;
        private bool _applicationQuitting;
        private UiTextureBaseReclaimResult _result;
        private long _beforePrivateBytes;
        private long _beforeTextureBytes;
        private bool _watching;
        private int _watchFrames;
        private int _repairedTotal;
        private int _releasedCount;
        private int _skippedCount;
        private int _scanWaitFrames;
        private int _rewireAttempts;
        private int _retryAfterFrame;
        private int _quietFrames;
        private int _lastObservedLoaded = -1;

        // ~5 s at 60 fps. The watchdog only reads a dictionary, so the cost is
        // negligible either way; the interval exists to keep the log quiet.
        private const int WatchIntervalFrames = 300;

        internal void Bind(
            UiTextureRuntimeLane lane,
            Action<string> information,
            Action<string> warning)
        {
            if (lane == null) throw new ArgumentNullException("lane");
            if (_lane != null)
            {
                throw new InvalidOperationException(
                    "UI base texture reclaim host is already bound");
            }
            _lane = lane;
            _information = information;
            _warning = warning;
        }

        // The lane is considered settled once no further owned path has become
        // terminal for this long. Noesis requests every URI of a parsed XAML
        // tree in one contiguous burst, so this only has to outlast the gaps
        // inside that burst, not the burst itself.
        private const double SettleMilliseconds = 750d;
        private const int MinimumLateFrames = 2;
        private const int GiveUpLateFrames = 3600;
        private const int MaximumRewireAttempts = 8;
        private const int RetryIntervalFrames = 120;
        // ~0,75 s at 60 fps, matched to SettleMilliseconds.
        private const int MinimumQuietFrames = 45;

        /// <summary>
        /// How the displaced base textures are released after the rewire.
        /// </summary>
        /// <remarks>
        /// A process-global <c>Resources.UnloadUnusedAssets</c> was tried first
        /// and is NOT used any more. It collected 86 objects where the session
        /// had previously run one scan taking 10, and it landed inside the
        /// window in which the AssetStream lane registers its 152 per-group
        /// baselines - before those are rooted; the next map transition failed
        /// closed. Archer colour flicker was seen in the same session, but a
        /// later A/B check reproduced it without this scan, so the scan is not
        /// treated as its cause.
        ///
        /// The targeted release below can only touch the 113 base textures the
        /// rewire just displaced, so the entire class of collateral damage is
        /// gone. It still waits for the baseline capture, because releasing
        /// asset lifetime at all inside that window is not worth the risk.
        /// </remarks>
        private static readonly bool TargetedReleaseEnabled = true;

        private void LateUpdate()
        {
            if (_applicationQuitting || _lane == null) return;
            if (!_rewired)
            {
                _lateFrames++;
                if (_lateFrames < MinimumLateFrames) return;

                int loaded;
                int rejected;
                int expected;
                double quietMilliseconds;
                UiTextureLoadTexturePatch.SnapshotProgress(
                    out loaded,
                    out rejected,
                    out expected,
                    out quietMilliseconds);

                if (rejected != 0)
                {
                    UiTextureBaseTextureReclaimer.Emit(
                        _warning,
                        "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                        + "|status=never_armed"
                        + "|reason=owned_path_rejected"
                        + "|loaded=" + Integer(loaded)
                        + "|rejected=" + Integer(rejected)
                        + "|expected=" + Integer(expected));
                    Stop();
                    return;
                }
                // The clock alone is not enough: it keeps running while the
                // game is minimised or stalled, and "Noesis stopped asking"
                // only advances in rendered frames. Require both.
                if (loaded != _lastObservedLoaded)
                {
                    _lastObservedLoaded = loaded;
                    _quietFrames = 0;
                }
                else
                {
                    _quietFrames++;
                }
                if (_lateFrames < _retryAfterFrame) return;
                if (_quietFrames < MinimumQuietFrames
                    || quietMilliseconds < SettleMilliseconds)
                {
                    if (_lateFrames >= GiveUpLateFrames)
                    {
                        UiTextureBaseTextureReclaimer.Emit(
                            _warning,
                            "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                            + "|status=never_armed"
                            + "|reason=lane_never_settled"
                            + "|loaded=" + Integer(loaded)
                            + "|expected=" + Integer(expected)
                            + "|late_frames=" + Integer(_lateFrames));
                        Stop();
                    }
                    return;
                }
                TryRewireAndStartUnload(loaded, expected);
                return;
            }
            if (!_watching)
            {
                // The rewire is durable. Targeted release may still be
                // waiting for AssetStream baseline capture, so retry it here.
                TryStartScan();
                return;
            }
            Watch();
        }

        private void Watch()
        {
            _watchFrames++;
            if (_watchFrames < WatchIntervalFrames) return;
            _watchFrames = 0;

            int checkedUris;
            int repaired;
            string failure;
            if (!UiTextureBaseTextureReclaimer.TryVerifyAndRepair(
                    out checkedUris,
                    out repaired,
                    out failure))
            {
                UiTextureBaseTextureReclaimer.Emit(
                    _warning,
                    "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                    + "|status=watchdog_stopped"
                    + "|checked=" + Integer(checkedUris)
                    + "|repaired=" + Integer(_repairedTotal)
                    + "|reason=" + Token(failure));
                _watching = false;
                Stop();
                return;
            }
            if (repaired > 0)
            {
                _repairedTotal += repaired;
                UiTextureBaseTextureReclaimer.Emit(
                    _warning,
                    "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                    + "|status=watchdog_repaired"
                    + "|checked=" + Integer(checkedUris)
                    + "|repaired_now=" + Integer(repaired)
                    + "|repaired_total=" + Integer(_repairedTotal)
                    + "|note=managed_only_native_pointer_needs_a_new_GetTextureInfo");
            }
        }

        private void TryRewireAndStartUnload(int loadedPaths, int expectedPaths)
        {
            try
            {
                // Do not call UpdateTextures() here. Require instead that
                // Noesis has already drained its own request queue, so the
                // rewire cannot race the render-tree update of this frame.
                string quiesceFailure;
                if (!UiTextureBaseTextureReclaimer.TryRequireQuiescentRequests(
                        out quiesceFailure))
                {
                    // A non-empty request queue is transient by definition:
                    // Noesis drains it on its own next render-tree update.
                    // Retry on the same bounded schedule as the rewire itself.
                    _rewireAttempts++;
                    if (_rewireAttempts < MaximumRewireAttempts)
                    {
                        _retryAfterFrame = _lateFrames + RetryIntervalFrames;
                        return;
                    }
                    UiTextureBaseTextureReclaimer.Emit(
                        _warning,
                        "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                        + "|status=skipped_fail_closed"
                        + "|phase=request_queue_quiescent"
                        + "|attempts=" + Integer(_rewireAttempts)
                        + "|reason=" + Token(quiesceFailure));
                    Stop();
                    return;
                }
                _beforePrivateBytes = ReadPrivateBytes();
                _beforeTextureBytes = ReadTextureBytes();
                string failure;
                bool retryable;
                if (!UiTextureBaseTextureReclaimer.TryRewireBaseDependencies(
                        _lane,
                        out _result,
                        out failure,
                        out retryable))
                {
                    // Several rejection reasons are inherently transient - an
                    // owner XAML not yet materialised, an entry still loading.
                    // Retry a bounded number of times before giving up for
                    // good, otherwise one unlucky frame costs the whole reclaim.
                    _rewireAttempts++;
                    if (retryable && _rewireAttempts < MaximumRewireAttempts)
                    {
                        UiTextureBaseTextureReclaimer.Emit(
                            _warning,
                            "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                            + "|status=deferred"
                            + "|attempt=" + Integer(_rewireAttempts)
                            + "|of=" + Integer(MaximumRewireAttempts)
                            + "|reason=" + Token(failure));
                        _retryAfterFrame = _lateFrames + RetryIntervalFrames;
                        return;
                    }
                    UiTextureBaseTextureReclaimer.Emit(
                        _warning,
                        "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                        + "|status=skipped_fail_closed"
                        + "|attempts=" + Integer(_rewireAttempts)
                        + "|reason=" + Token(failure));
                    Stop();
                    return;
                }
                _rewired = true;
                UiTextureBaseTextureReclaimer.Emit(
                    _information,
                    "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                    + "|status=rewired"
                    + "|loaded_paths=" + Integer(loadedPaths)
                    + "|expected_paths=" + Integer(expectedPaths)
                    + "|owned_uris=" + Integer(_result.OwnedUriCount)
                    + "|dependencies=" + Integer(_result.DependencyCount)
                    + "|provider_refs_preserved="
                    + Long(_result.ProviderRefsPreserved)
                    + "|provider_refs_min="
                    + Long(_result.MinimumProviderRefs)
                    + "|xamls=" + Integer(_result.XamlCount)
                    + "|candidate_textures="
                    + Integer(_result.CandidateTextureCount)
                    + "|readable_rgba32=" + Integer(_result.ReadableRgba32)
                    + "|readable_rgb24=" + Integer(_result.ReadableRgb24)
                    + "|readable_bc7=" + Integer(_result.ReadableBc7)
                    + "|candidate_runtime_bytes="
                    + Long(_result.CandidateRuntimeBytes)
                    + "|process_private_before=" + Long(_beforePrivateBytes)
                    + "|texture_current_before=" + Long(_beforeTextureBytes));
                TryStartScan();
            }
            catch (Exception exception)
            {
                UiTextureBaseTextureReclaimer.Emit(
                    _warning,
                    "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                    + "|status="
                    + (_rewired ? "rewired_no_scan" : "skipped_fail_closed")
                    + "|reason="
                    + Token(UiTextureBaseTextureReclaimer.Describe(exception)));
                Stop();
            }
        }

        private void Complete()
        {
            long afterPrivateBytes = ReadPrivateBytes();
            long afterTextureBytes = ReadTextureBytes();
            UiTextureBaseTextureReclaimer.Emit(
                _information,
                "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                + "|status=complete"
                + "|candidate_runtime_bytes="
                + Long(_result == null ? 0L : _result.CandidateRuntimeBytes)
                + "|process_private_before=" + Long(_beforePrivateBytes)
                + "|process_private_after=" + Long(afterPrivateBytes)
                + "|process_private_delta="
                + Long(afterPrivateBytes - _beforePrivateBytes)
                + "|texture_current_before=" + Long(_beforeTextureBytes)
                + "|texture_current_after=" + Long(afterTextureBytes)
                + "|texture_current_delta="
                + Long(afterTextureBytes - _beforeTextureBytes)
                + "|released_base_textures=" + Integer(_releasedCount)
                + "|skipped_base_textures=" + Integer(_skippedCount)
                + "|watchdog=armed");
            _watching = true;
            _watchFrames = 0;
        }

        private void TryStartScan()
        {
            if (!TargetedReleaseEnabled)
            {
                UiTextureBaseTextureReclaimer.Emit(
                    _information,
                    "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                    + "|status=rewired_release_disabled"
                    + "|note=rewire_is_active_no_bytes_reclaimed");
                _watching = true;
                _watchFrames = 0;
                return;
            }

            // Never touch asset lifetime before the AssetStream lane has rooted
            // all 152 group baselines.
            if (!AssetStreamRuntimeLane.AnyBaselineCaptured)
            {
                _scanWaitFrames++;
                if (_scanWaitFrames == 1)
                {
                    UiTextureBaseTextureReclaimer.Emit(
                        _information,
                        "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                        + "|status=release_waiting"
                        + "|reason=assetstream_baseline_capture_pending");
                }
                if (_scanWaitFrames >= GiveUpLateFrames)
                {
                    UiTextureBaseTextureReclaimer.Emit(
                        _warning,
                        "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                        + "|status=rewired_no_release"
                        + "|reason=baseline_capture_never_completed"
                        + "|waited_frames=" + Integer(_scanWaitFrames));
                    _watching = true;
                    _watchFrames = 0;
                }
                return;
            }

            int released;
            int skipped;
            string releaseFailure;
            if (!UiTextureBaseTextureReclaimer.TryReleaseDisplacedBaseTextures(
                    out released,
                    out skipped,
                    out releaseFailure))
            {
                UiTextureBaseTextureReclaimer.Emit(
                    _warning,
                    "SEDE_RUNTIME_V1|event=ui_base_texture_reclaim"
                    + "|status=rewired_no_release"
                    + "|reason=" + Token(releaseFailure));
                _watching = true;
                _watchFrames = 0;
                return;
            }
            _releasedCount = released;
            _skippedCount = skipped;
            Complete();
        }

        private void Stop()
        {
            UiTextureBaseTextureReclaimer.MarkTerminal();
            _lane = null;
            try { UnityObject.Destroy(gameObject); }
            catch { }
        }

        private void OnApplicationQuit()
        {
            _applicationQuitting = true;
            UiTextureBaseTextureReclaimer.MarkTerminal();
        }

        private static readonly WindowsAssetStreamMemoryProbe MemoryProbe =
            new WindowsAssetStreamMemoryProbe();

        /// <summary>
        /// Reads Process Private Bytes, or -1 when unavailable.
        /// </summary>
        /// <remarks>
        /// Deliberately NOT Process.PrivateMemorySize64: under this Mono it
        /// returns 0, which made the reclaim log
        /// process_private_before/after/delta=0 and silently destroyed the one
        /// measurement that decides whether the freed base textures also
        /// carried a system-memory shadow copy. The AssetStream lane's
        /// GetProcessMemoryInfo probe returns real values in the same process.
        /// </remarks>
        private static long ReadPrivateBytes()
        {
            try
            {
                AssetStreamMemorySnapshot snapshot = MemoryProbe.Capture();
                if (snapshot != null && snapshot.ProcessPrivateBytes.HasValue)
                {
                    return snapshot.ProcessPrivateBytes.Value;
                }
            }
            catch { }
            try
            {
                using (Process process = Process.GetCurrentProcess())
                {
                    process.Refresh();
                    long value = process.PrivateMemorySize64;
                    if (value > 0) return value;
                }
            }
            catch { }
            return -1L;
        }

        private static long ReadTextureBytes()
        {
            try
            {
                ulong value = UnityEngine.Texture.currentTextureMemory;
                return value > long.MaxValue ? long.MaxValue : (long)value;
            }
            catch { return -1L; }
        }

        private static string Token(string value)
        {
            if (string.IsNullOrEmpty(value)) return "unknown";
            value = value.Replace('|', '/').Replace('=', ':')
                .Replace('\r', ' ').Replace('\n', ' ');
            return value.Length <= 192 ? value : value.Substring(0, 192);
        }

        private static string Integer(int value)
        {
            return value.ToString(CultureInfo.InvariantCulture);
        }

        private static string Long(long value)
        {
            return value.ToString(CultureInfo.InvariantCulture);
        }
    }
}
