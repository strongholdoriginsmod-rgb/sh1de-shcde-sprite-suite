using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Runtime.CompilerServices;
using StrongholdEuropeDE.Runtime.Audio;
using UnityEngine;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Small adapter around the generated build anchor. Keeping the generated
    /// type out of the backend makes the ownership code independently testable.
    /// </summary>
    internal sealed class AssetStreamCompiledContract
    {
        internal AssetStreamCompiledContract(
            bool enabled,
            string indexSha256,
            long indexSize,
            int groupCount,
            int vanillaOmittedGroupCount,
            bool uiStreamingExpected,
            bool pcmStreamingExpected,
            IEnumerable<string> foliageGroups)
            : this(
                enabled,
                indexSha256,
                indexSize,
                groupCount,
                vanillaOmittedGroupCount,
                enabled ? AssetStreamContract.AtlasBackendKind : string.Empty,
                enabled ? AssetStreamContract.IndexSchema : string.Empty,
                enabled ? "v1" : string.Empty,
                enabled,
                uiStreamingExpected,
                pcmStreamingExpected,
                foliageGroups)
        {
        }

        internal AssetStreamCompiledContract(
            bool enabled,
            string indexSha256,
            long indexSize,
            int groupCount,
            int vanillaOmittedGroupCount,
            string backendKind,
            string indexSchema,
            string qualityState,
            bool promotable,
            bool uiStreamingExpected,
            bool pcmStreamingExpected,
            IEnumerable<string> foliageGroups)
        {
            Enabled = enabled;
            IndexSha256 = indexSha256 ?? string.Empty;
            IndexSize = indexSize;
            GroupCount = groupCount;
            VanillaOmittedGroupCount = vanillaOmittedGroupCount;
            BackendKind = backendKind ?? string.Empty;
            IndexSchema = indexSchema ?? string.Empty;
            QualityState = qualityState ?? string.Empty;
            Promotable = promotable;
            UiStreamingExpected = uiStreamingExpected;
            PcmStreamingExpected = pcmStreamingExpected;
            FoliageGroups = new HashSet<string>(StringComparer.Ordinal);
            if (foliageGroups != null)
            {
                foreach (string group in foliageGroups)
                {
                    if (!AssetStreamManifestRules.IsSafeGroup(group)
                        || !FoliageGroups.Add(group))
                    {
                        throw new ArgumentException(
                            "Compiled foliage group list is malformed");
                    }
                }
            }
            Validate();
        }

        internal bool Enabled { get; private set; }

        internal string IndexSha256 { get; private set; }

        internal long IndexSize { get; private set; }

        internal int GroupCount { get; private set; }

        internal int VanillaOmittedGroupCount { get; private set; }

        internal string BackendKind { get; private set; }

        internal string IndexSchema { get; private set; }

        internal string QualityState { get; private set; }

        internal bool Promotable { get; private set; }

        internal bool UiStreamingExpected { get; private set; }

        internal bool PcmStreamingExpected { get; private set; }

        internal HashSet<string> FoliageGroups { get; private set; }

        private void Validate()
        {
            if (!Enabled)
            {
                if (IndexSha256.Length != 0 || IndexSize != 0 || GroupCount != 0
                    || VanillaOmittedGroupCount != 0 || BackendKind.Length != 0
                    || IndexSchema.Length != 0 || QualityState.Length != 0
                    || Promotable)
                {
                    throw new ArgumentException(
                        "Disabled asset-stream contract must have empty anchors");
                }
                return;
            }
            if (!AssetStreamManifestRules.IsCanonicalSha256(IndexSha256))
            {
                throw new ArgumentException(
                    "Enabled asset-stream contract has no canonical index SHA-256");
            }
            if (IndexSize < 2 || IndexSize > AssetStreamContract.MaximumIndexBytes)
            {
                throw new ArgumentOutOfRangeException("indexSize");
            }
            if (GroupCount < 0 || VanillaOmittedGroupCount < 0
                || GroupCount + VanillaOmittedGroupCount < 1
                || GroupCount + VanillaOmittedGroupCount
                    > AssetStreamContract.MaximumGroups)
            {
                throw new ArgumentOutOfRangeException("groupCount");
            }
            bool v1 = string.Equals(
                    BackendKind,
                    AssetStreamContract.AtlasBackendKind,
                    StringComparison.Ordinal)
                && string.Equals(
                    IndexSchema,
                    AssetStreamContract.IndexSchema,
                    StringComparison.Ordinal)
                && string.Equals(QualityState, "v1", StringComparison.Ordinal)
                && Promotable;
            bool v2 = string.Equals(
                    BackendKind,
                    AssetStreamBc7Contract.AtlasBackendKind,
                    StringComparison.Ordinal)
                && string.Equals(
                    IndexSchema,
                    AssetStreamBc7Contract.IndexSchema,
                    StringComparison.Ordinal)
                && (string.Equals(
                        QualityState,
                        AssetStreamBc7Contract.FrozenQualityState,
                        StringComparison.Ordinal)
                    || string.Equals(
                        QualityState,
                        AssetStreamBc7Contract.MeasurementQualityState,
                        StringComparison.Ordinal))
                && Promotable == string.Equals(
                    QualityState,
                    AssetStreamBc7Contract.FrozenQualityState,
                    StringComparison.Ordinal);
            if (!v1 && !v2)
            {
                throw new ArgumentException(
                    "Compiled asset-stream backend/schema/quality anchor is inconsistent");
            }
        }
    }

    /// <summary>
    /// The five central loader fields are captured only from the exact
    /// ApplyRuntimeOverrides postfix. Per-group inner references are retained
    /// so later publication can distinguish our baseline from a foreign owner.
    /// </summary>
    internal sealed class AssetStreamUnityBaseline
    {
        internal AssetStreamUnityBaseline(
            spriteLoader loader,
            Dictionary<string, Sprite> allSprites,
            Sprite[][] gmSprites,
            Sprite[][] gmAltSprites,
            Material[][] gmMaterials,
            Color[][] gmColors,
            Sprite[] groupSprites,
            Sprite[] groupAltSprites,
            Material[] groupMaterials,
            Color[] groupColors,
            bool usesPlainMaterials,
            ReadOnlyDictionary<string, Sprite> frozenAllSprites)
        {
            Loader = loader ?? throw new ArgumentNullException("loader");
            AllSprites = allSprites ?? throw new ArgumentNullException("allSprites");
            GmSprites = gmSprites ?? throw new ArgumentNullException("gmSprites");
            GmAltSprites = gmAltSprites ?? throw new ArgumentNullException("gmAltSprites");
            GmMaterials = gmMaterials ?? throw new ArgumentNullException("gmMaterials");
            GmColors = gmColors ?? throw new ArgumentNullException("gmColors");
            GroupSprites = groupSprites;
            GroupAltSprites = groupAltSprites;
            GroupMaterials = groupMaterials;
            GroupColors = groupColors;
            UsesPlainMaterials = usesPlainMaterials;
            FrozenAllSprites = frozenAllSprites
                ?? throw new ArgumentNullException("frozenAllSprites");
            FrozenGroupSprites = Clone(groupSprites);
            FrozenGroupAltSprites = Clone(groupAltSprites);
            FrozenGroupMaterials = Clone(groupMaterials);
            FrozenGroupColors = Clone(groupColors);
        }

        internal spriteLoader Loader { get; private set; }
        internal Dictionary<string, Sprite> AllSprites { get; private set; }
        internal Sprite[][] GmSprites { get; private set; }
        internal Sprite[][] GmAltSprites { get; private set; }
        internal Material[][] GmMaterials { get; private set; }
        internal Color[][] GmColors { get; private set; }
        internal Sprite[] GroupSprites { get; private set; }
        internal Sprite[] GroupAltSprites { get; private set; }
        internal Material[] GroupMaterials { get; private set; }
        internal Color[] GroupColors { get; private set; }
        internal bool UsesPlainMaterials { get; private set; }

        /// <summary>
        /// Immutable-by-construction values captured in the exact
        /// ApplyRuntimeOverrides postfix. The live Group* references above are
        /// retained only as ownership-aware restore anchors; staging and worker
        /// fallback must use these frozen copies.
        /// </summary>
        internal ReadOnlyDictionary<string, Sprite> FrozenAllSprites
        {
            get;
            private set;
        }

        internal Sprite[] FrozenGroupSprites { get; private set; }
        internal Sprite[] FrozenGroupAltSprites { get; private set; }
        internal Material[] FrozenGroupMaterials { get; private set; }
        internal Color[] FrozenGroupColors { get; private set; }

        internal bool TryGetFrozenSprite(
            int imageId,
            bool altFrame,
            out Sprite sprite)
        {
            sprite = null;
            if (FrozenGroupSprites == null
                || imageId < 0
                || imageId >= FrozenGroupSprites.Length)
            {
                return false;
            }
            if (altFrame
                && FrozenGroupAltSprites != null
                && imageId < FrozenGroupAltSprites.Length)
            {
                sprite = FrozenGroupAltSprites[imageId];
                if (!ReferenceEquals(sprite, null))
                {
                    return true;
                }
            }
            sprite = FrozenGroupSprites[imageId];
            // A null result is still the exact baseline result for a valid GM.
            return true;
        }

        internal bool TryGetFrozenMaterial(
            int colourOffset,
            int chopFeet,
            int transparency,
            out Color outputColour,
            out Material material)
        {
            outputColour = Color.white;
            material = null;
            if (FrozenGroupMaterials == null
                || FrozenGroupMaterials.Length != 7)
            {
                return false;
            }
            if (!UsesPlainMaterials)
            {
                if (FrozenGroupColors == null
                    || colourOffset < 0
                    || colourOffset >= FrozenGroupColors.Length)
                {
                    return false;
                }
                outputColour = FrozenGroupColors[colourOffset];
            }
            outputColour.a = (float)(32 - transparency) / 32f;
            int slot = chopFeet <= 0 ? 0 : Math.Min(6, chopFeet / 4);
            material = FrozenGroupMaterials[slot];
            return true;
        }

        private static T[] Clone<T>(T[] value)
        {
            return value == null ? null : (T[])value.Clone();
        }
    }

    internal sealed class AssetStreamUnityPage
    {
        internal AssetStreamUnityPage(
            int id,
            Texture2D main,
            Texture2D mask,
            Material[] materials)
        {
            Id = id;
            Main = main ?? throw new ArgumentNullException("main");
            Mask = mask;
            Materials = materials;
        }

        internal int Id { get; private set; }
        internal Texture2D Main { get; set; }
        internal Texture2D Mask { get; set; }
        internal Material[] Materials { get; set; }
    }

    internal struct AssetStreamOriginalSpriteEntry
    {
        internal AssetStreamOriginalSpriteEntry(bool existed, Sprite value)
        {
            Existed = existed;
            Value = value;
        }

        internal bool Existed { get; private set; }
        internal Sprite Value { get; private set; }
    }

    /// <summary>All native/managed objects owned by one committed group.</summary>
    internal sealed class AssetStreamUnityCommitted
        : IAssetStreamGlobalUnloadParticipant
    {
        private readonly object _gate = new object();
        private bool _released;
        private bool _unsafeCentralReferences;

        internal AssetStreamUnityCommitted(
            AssetStreamOwnershipToken ownership,
            spriteLoader loader,
            AssetBundle bundle,
            AssetStreamAtlasManifest atlas,
            AssetStreamUnityPage[] pages,
            Sprite[] mainSprites,
            Sprite[] altSprites,
            Material[] publishedGroupMaterials,
            IDictionary<string, AssetStreamOriginalSpriteEntry> originalSprites,
            IList<Sprite> createdSprites,
            IList<Material> createdMaterials,
            AssetStreamCleanupCompletion cleanupCompletion)
        {
            Ownership = ownership;
            Loader = loader ?? throw new ArgumentNullException("loader");
            Bundle = bundle ?? throw new ArgumentNullException("bundle");
            CleanupCompletion = cleanupCompletion
                ?? throw new ArgumentNullException("cleanupCompletion");
            Atlas = atlas ?? throw new ArgumentNullException("atlas");
            Pages = pages ?? throw new ArgumentNullException("pages");
            MainSprites = mainSprites ?? throw new ArgumentNullException("mainSprites");
            AltSprites = altSprites ?? throw new ArgumentNullException("altSprites");
            PublishedGroupMaterials = publishedGroupMaterials
                ?? throw new ArgumentNullException("publishedGroupMaterials");
            OriginalSprites = new Dictionary<string, AssetStreamOriginalSpriteEntry>(
                originalSprites
                    ?? throw new ArgumentNullException("originalSprites"),
                StringComparer.Ordinal);
            CreatedSprites = new List<Sprite>(
                createdSprites ?? throw new ArgumentNullException("createdSprites"));
            CreatedMaterials = new List<Material>(
                createdMaterials ?? throw new ArgumentNullException("createdMaterials"));
            CreatedSpriteSet = new HashSet<Sprite>(
                CreatedSprites,
                AssetStreamReferenceComparer<Sprite>.Instance);
            CreatedMaterialSet = new HashSet<Material>(
                CreatedMaterials,
                AssetStreamReferenceComparer<Material>.Instance);
        }

        internal AssetStreamOwnershipToken Ownership { get; private set; }
        internal spriteLoader Loader { get; private set; }
        internal AssetBundle Bundle { get; set; }
        internal AssetStreamCleanupCompletion CleanupCompletion { get; private set; }
        internal AssetStreamAtlasManifest Atlas { get; private set; }
        internal AssetStreamUnityPage[] Pages { get; private set; }
        internal Sprite[] MainSprites { get; private set; }
        internal Sprite[] AltSprites { get; private set; }
        internal Material[] PublishedGroupMaterials { get; private set; }
        internal Dictionary<string, AssetStreamOriginalSpriteEntry> OriginalSprites
        {
            get;
            private set;
        }
        internal List<Sprite> CreatedSprites { get; private set; }
        internal List<Material> CreatedMaterials { get; private set; }
        internal HashSet<Sprite> CreatedSpriteSet { get; private set; }
        internal HashSet<Material> CreatedMaterialSet { get; private set; }
        internal AssetStreamLoaderGenerationSnapshot PublishExpected { get; set; }
        internal AssetStreamLoaderSnapshot PublishReplacement { get; set; }
        internal bool CleanupStarted { get; set; }
        internal bool ManagedTextureReferencesCleared { get; set; }
        public bool GlobalUnloadCompleted { get; set; }

        internal bool Released
        {
            get { lock (_gate) { return _released; } }
        }

        internal bool UnsafeCentralReferences
        {
            get { lock (_gate) { return _unsafeCentralReferences; } }
            set { lock (_gate) { _unsafeCentralReferences = value; } }
        }

        internal bool TryMarkReleased()
        {
            lock (_gate)
            {
                if (_released)
                {
                    return false;
                }
                _released = true;
                return true;
            }
        }

        internal void ClearManagedTextureReferences()
        {
            for (int index = 0; index < Pages.Length; index++)
            {
                Pages[index].Main = null;
                Pages[index].Mask = null;
                Pages[index].Materials = null;
            }
            ManagedTextureReferencesCleared = true;
        }

        internal void ClearOwnedObjectReferences()
        {
            CreatedSprites.Clear();
            CreatedMaterials.Clear();
            CreatedSpriteSet.Clear();
            CreatedMaterialSet.Clear();
        }

        internal void ClearPublicationPlan()
        {
            PublishExpected = null;
            PublishReplacement = null;
        }
    }

    internal sealed class AssetStreamPageMaterialRoute
    {
        internal AssetStreamPageMaterialRoute(
            AssetStreamOwnershipToken ownership,
            Texture mask)
        {
            Ownership = ownership;
            Mask = mask ?? throw new ArgumentNullException("mask");
        }

        internal AssetStreamOwnershipToken Ownership { get; private set; }
        internal Texture Mask { get; private set; }
    }

    /// <summary>
    /// Main-thread registry for every bundle-owned page mask plus the exact
    /// Sprite-to-page-mask route for every required-mask frame. Material
    /// binding remains group/page specific, but pooled SetBodySprite renderers
    /// can therefore recover the current mask across every masked group.
    /// </summary>
    internal sealed class AssetStreamPageMaterialRegistry
    {
        private sealed class Registration
        {
            internal Registration(
                Texture[] masks,
                Material[] materials,
                int[] routeIds)
            {
                Masks = masks;
                Materials = materials;
                RouteIds = routeIds;
            }

            internal Texture[] Masks { get; private set; }
            internal Material[] Materials { get; private set; }
            internal int[] RouteIds { get; private set; }
            internal bool RoutesDetached { get; set; }
        }

        private readonly object _gate = new object();
        private readonly Dictionary<int, AssetStreamPageMaterialRoute> _routes =
            new Dictionary<int, AssetStreamPageMaterialRoute>();
        private readonly AssetStreamReferenceCountSet<Texture> _ownedMasks =
            new AssetStreamReferenceCountSet<Texture>();
        // The page materials this lane created. A mask sitting on one of these
        // is not foreign state: we made the material, we own its lifetime and
        // we destroy it in the same release. Blocking on it is a self-block.
        private readonly AssetStreamReferenceCountSet<Material> _ownedMaterials =
            new AssetStreamReferenceCountSet<Material>();
        private readonly Dictionary<AssetStreamOwnershipToken, Registration>
            _registrations =
                new Dictionary<AssetStreamOwnershipToken, Registration>();

        internal void Register(
            AssetStreamOwnershipToken ownership,
            AssetStreamAtlasManifest atlas,
            AssetStreamUnityPage[] pages,
            IList<Sprite> sprites)
        {
            if (atlas == null) throw new ArgumentNullException("atlas");
            if (pages == null) throw new ArgumentNullException("pages");
            if (sprites == null) throw new ArgumentNullException("sprites");
            if (sprites.Count != atlas.Frames.Count)
            {
                throw new InvalidOperationException(
                    "Runtime sprite count does not match atlas frames");
            }
            if (!ownership.IsValid)
            {
                throw new ArgumentException(
                    "Runtime page-mask ownership token is invalid",
                    "ownership");
            }
            if (pages.Length != atlas.Pages.Count)
            {
                throw new InvalidOperationException(
                    "Runtime page count does not match atlas pages");
            }

            bool masksRequired =
                AssetStreamMaterialBindingContract.RequiresExactSpriteMaskRoute(
                    atlas.MaskPolicy);
            if (masksRequired && pages.Length == 0)
            {
                throw new InvalidOperationException(
                    "Required runtime atlas has no pages to register");
            }
            var masks = new List<Texture>(pages.Length);
            for (int index = 0; index < pages.Length; index++)
            {
                Texture mask = pages[index] == null ? null : pages[index].Mask;
                if (masksRequired)
                {
                    if (mask == null)
                    {
                        throw new InvalidOperationException(
                            "Required runtime atlas page has no live mask");
                    }
                    masks.Add(mask);
                }
                else if (mask != null)
                {
                    throw new InvalidOperationException(
                        "Forbidden runtime atlas page unexpectedly has a mask");
                }
            }

            var candidates = new List<
                KeyValuePair<int, AssetStreamPageMaterialRoute>>(
                    masksRequired ? sprites.Count : 0);
            var candidateIds = new HashSet<int>();
            if (masksRequired)
            {
                for (int index = 0; index < sprites.Count; index++)
                {
                    Sprite sprite = sprites[index];
                    if (ReferenceEquals(sprite, null) || sprite == null)
                    {
                        throw new InvalidOperationException(
                            "Required page route received a missing runtime Sprite");
                    }
                    AssetStreamAtlasFrame frame = atlas.Frames[index];
                    Texture mask = pages[frame.Page].Mask;
                    int instanceId = sprite.GetInstanceID();
                    if (!candidateIds.Add(instanceId))
                    {
                        throw new InvalidOperationException(
                            "Required page route contains a duplicate Sprite instance id");
                    }
                    candidates.Add(
                        new KeyValuePair<int, AssetStreamPageMaterialRoute>(
                            instanceId,
                            new AssetStreamPageMaterialRoute(ownership, mask)));
                }
            }

            var routeIds = new int[candidates.Count];
            for (int index = 0; index < candidates.Count; index++)
            {
                routeIds[index] = candidates[index].Key;
            }
            var materials = new List<Material>(pages.Length);
            for (int index = 0; index < pages.Length; index++)
            {
                Material[] pageMaterials =
                    pages[index] == null ? null : pages[index].Materials;
                if (pageMaterials == null)
                {
                    continue;
                }
                for (int inner = 0; inner < pageMaterials.Length; inner++)
                {
                    if (!ReferenceEquals(pageMaterials[inner], null))
                    {
                        materials.Add(pageMaterials[inner]);
                    }
                }
            }
            var registration = new Registration(
                masks.ToArray(),
                materials.ToArray(),
                routeIds);
            lock (_gate)
            {
                if (_registrations.ContainsKey(ownership))
                {
                    throw new InvalidOperationException(
                        "Runtime page-mask ownership is already registered");
                }
                for (int index = 0; index < candidates.Count; index++)
                {
                    if (_routes.ContainsKey(candidates[index].Key))
                    {
                        throw new InvalidOperationException(
                            "Runtime Sprite instance id already owns a page route");
                    }
                }

                int masksAdded = 0;
                int materialsAdded = 0;
                int routesAdded = 0;
                try
                {
                    for (; masksAdded < registration.Masks.Length; masksAdded++)
                    {
                        _ownedMasks.Add(registration.Masks[masksAdded]);
                    }
                    for (; materialsAdded < registration.Materials.Length;
                        materialsAdded++)
                    {
                        _ownedMaterials.Add(registration.Materials[materialsAdded]);
                    }
                    for (; routesAdded < candidates.Count; routesAdded++)
                    {
                        _routes.Add(
                            candidates[routesAdded].Key,
                            candidates[routesAdded].Value);
                    }
                    _registrations.Add(ownership, registration);
                }
                catch (Exception exception)
                {
                    Exception rollbackFailure = null;
                    for (int index = routesAdded - 1; index >= 0; index--)
                    {
                        if (!_routes.Remove(candidates[index].Key)
                            && rollbackFailure == null)
                        {
                            rollbackFailure = new InvalidOperationException(
                                "Runtime page-route registration rollback failed");
                        }
                    }
                    for (int index = materialsAdded - 1; index >= 0; index--)
                    {
                        if (!_ownedMaterials.Remove(registration.Materials[index])
                            && rollbackFailure == null)
                        {
                            rollbackFailure = new InvalidOperationException(
                                "Runtime page-material registration rollback failed");
                        }
                    }
                    for (int index = masksAdded - 1; index >= 0; index--)
                    {
                        if (!_ownedMasks.Remove(registration.Masks[index])
                            && rollbackFailure == null)
                        {
                            rollbackFailure = new InvalidOperationException(
                                "Runtime mask registration rollback failed");
                        }
                    }
                    if (rollbackFailure != null)
                    {
                        throw new InvalidOperationException(
                            "Runtime page-mask registration and rollback failed",
                            new AggregateException(exception, rollbackFailure));
                    }
                    throw;
                }
            }
        }

        /// <summary>
        /// Stops new Sprite-mask acquisitions after central detach while the
        /// exact page-mask identities remain registered for renderer and
        /// central-material release audits.
        /// </summary>
        internal void DetachRoutes(AssetStreamOwnershipToken ownership)
        {
            lock (_gate)
            {
                Registration registration;
                if (!_registrations.TryGetValue(ownership, out registration))
                {
                    throw new InvalidOperationException(
                        "Runtime page-mask ownership is not registered");
                }
                if (registration.RoutesDetached)
                {
                    return;
                }
                RequireAttachedRoutesLocked(ownership, registration);
                RemoveAttachedRoutesLocked(registration);
            }
        }

        internal void Unregister(AssetStreamOwnershipToken ownership)
        {
            lock (_gate)
            {
                Registration registration;
                if (!_registrations.TryGetValue(ownership, out registration))
                {
                    return;
                }

                if (!registration.RoutesDetached)
                {
                    RequireAttachedRoutesLocked(ownership, registration);
                }
                for (int index = 0; index < registration.Masks.Length; index++)
                {
                    Texture mask = registration.Masks[index];
                    int required = 1;
                    for (int previous = 0; previous < index; previous++)
                    {
                        if (ReferenceEquals(registration.Masks[previous], mask))
                        {
                            required++;
                        }
                    }
                    if (_ownedMasks.Count(mask) < required)
                    {
                        throw new InvalidOperationException(
                            "Runtime page-mask ownership count is inconsistent");
                    }
                }

                if (!registration.RoutesDetached)
                {
                    RemoveAttachedRoutesLocked(registration);
                }
                for (int index = 0; index < registration.Masks.Length; index++)
                {
                    if (!_ownedMasks.Remove(registration.Masks[index]))
                    {
                        throw new InvalidOperationException(
                            "Runtime page-mask ownership removal failed");
                    }
                }
                for (int index = 0; index < registration.Materials.Length; index++)
                {
                    if (!_ownedMaterials.Remove(registration.Materials[index]))
                    {
                        throw new InvalidOperationException(
                            "Runtime page-material ownership removal failed");
                    }
                }
                _registrations.Remove(ownership);
            }
        }

        /// <summary>
        /// Adds every registration that owns this exact Texture wrapper. A
        /// shared page identity can conservatively block more than one owner;
        /// UnityEngine.Object value equality is intentionally never used.
        /// </summary>
        internal void MarkOwnersOfMask(
            Texture mask,
            ISet<AssetStreamOwnershipToken> owners)
        {
            if (owners == null)
            {
                throw new ArgumentNullException("owners");
            }
            if (ReferenceEquals(mask, null))
            {
                return;
            }
            lock (_gate)
            {
                foreach (KeyValuePair<
                    AssetStreamOwnershipToken,
                    Registration> pair in _registrations)
                {
                    Texture[] masks = pair.Value.Masks;
                    for (int index = 0; index < masks.Length; index++)
                    {
                        if (ReferenceEquals(mask, masks[index]))
                        {
                            owners.Add(pair.Key);
                            break;
                        }
                    }
                }
            }
        }

        private void RequireAttachedRoutesLocked(
            AssetStreamOwnershipToken ownership,
            Registration registration)
        {
            for (int index = 0; index < registration.RouteIds.Length; index++)
            {
                AssetStreamPageMaterialRoute route;
                if (!_routes.TryGetValue(
                        registration.RouteIds[index],
                        out route)
                    || !route.Ownership.Equals(ownership))
                {
                    throw new InvalidOperationException(
                        "Runtime page-route ownership is inconsistent");
                }
            }
        }

        private void RemoveAttachedRoutesLocked(Registration registration)
        {
            for (int index = 0; index < registration.RouteIds.Length; index++)
            {
                if (!_routes.Remove(registration.RouteIds[index]))
                {
                    throw new InvalidOperationException(
                        "Runtime page-route removal failed");
                }
            }
            registration.RoutesDetached = true;
        }

        /// <summary>
        /// True when this lane created the material, i.e. it is a page clone
        /// from a published group rather than game- or extender-owned state.
        /// </summary>
        internal bool OwnsMaterial(Material material)
        {
            if (ReferenceEquals(material, null))
            {
                return false;
            }
            lock (_gate)
            {
                return _ownedMaterials.Contains(material);
            }
        }

        internal bool OwnsMask(Texture mask)
        {
            if (ReferenceEquals(mask, null))
            {
                return false;
            }
            lock (_gate)
            {
                return _ownedMasks.Contains(mask);
            }
        }

        internal bool TryGet(Sprite sprite, out Texture mask)
        {
            string group;
            return TryGet(sprite, out mask, out group);
        }

        internal bool TryGet(Sprite sprite, out Texture mask, out string group)
        {
            mask = null;
            group = null;
            if (ReferenceEquals(sprite, null) || sprite == null)
            {
                return false;
            }
            lock (_gate)
            {
                AssetStreamPageMaterialRoute route;
                if (!_routes.TryGetValue(sprite.GetInstanceID(), out route))
                {
                    return false;
                }
                mask = route.Mask;
                group = route.Ownership.GroupId;
                return mask != null;
            }
        }
    }

    internal sealed class AssetStreamReferenceComparer<T> : IEqualityComparer<T>
        where T : class
    {
        internal static readonly AssetStreamReferenceComparer<T> Instance =
            new AssetStreamReferenceComparer<T>();

        private AssetStreamReferenceComparer() { }

        public bool Equals(T left, T right)
        {
            return ReferenceEquals(left, right);
        }

        public int GetHashCode(T value)
        {
            return value == null ? 0 : RuntimeHelpers.GetHashCode(value);
        }
    }

    /// <summary>
    /// Explicit accounting bridge. A compiled-in PCM lane that is not ready is
    /// an unavailable metric, never an implicit zero.
    /// </summary>
    internal sealed class AssetStreamExternalUsageBridge
        : IAssetStreamExternalUsageProbe
    {
        private readonly bool _uiStreamingExpected;
        private readonly bool _pcmStreamingExpected;

        internal AssetStreamExternalUsageBridge(
            bool uiStreamingExpected,
            bool pcmStreamingExpected)
        {
            _uiStreamingExpected = uiStreamingExpected;
            _pcmStreamingExpected = pcmStreamingExpected;
        }

        public AssetStreamExternalUsageSnapshot Capture()
        {
            long? ui = _uiStreamingExpected
                ? UiTextureLoadTexturePatch.CurrentTrackedBytes
                : (long?)0L;
            long? audio = _pcmStreamingExpected
                ? PcmAudioStreamingLane.CurrentBufferBytes
                : (long?)0L;
            return new AssetStreamExternalUsageSnapshot(
                ui,
                audio,
                !ui.HasValue
                    ? "compiled UI streaming lane is not ready"
                    : (!audio.HasValue
                        ? "compiled PCM streaming lane is not ready"
                        : "UI/audio usage captured"));
        }
    }

    internal sealed class AssetStreamLogEventSink : IAssetStreamEventSink
    {
        private readonly Action<string> _information;
        private readonly Action<string> _warning;

        internal AssetStreamLogEventSink(
            Action<string> information,
            Action<string> warning)
        {
            _information = information;
            _warning = warning;
        }

        public void Emit(AssetStreamEvent value)
        {
            if (value == null)
            {
                return;
            }
            // Controller transition diagnostics are intentionally outside the
            // stable SEDE_RUNTIME_V1 terminal-event schema. The lane emits the
            // one initialized/group/scene_reset/summary record that validators
            // consume; exposing every internal transition there would create
            // duplicate and non-terminal group events.
            string message = "AssetStream diagnostic"
                + "|kind=" + AssetStreamText.Sanitize(value.Kind.ToString(), 64)
                + "|group=" + AssetStreamText.Sanitize(value.GroupId, 96)
                + "|epoch=" + value.Epoch
                + "|detail=" + AssetStreamText.Sanitize(value.Detail, 192);
            Action<string> sink = value.Kind == AssetStreamEventKind.BudgetDenied
                    || value.Kind == AssetStreamEventKind.SecondAdmissionDenied
                    || value.Kind == AssetStreamEventKind.LoadFailed
                    || value.Kind == AssetStreamEventKind.ReleaseBlocked
                ? _warning
                : _information;
            if (sink != null)
            {
                sink(message);
            }
        }
    }
}
