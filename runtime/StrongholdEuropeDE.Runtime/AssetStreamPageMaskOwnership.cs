using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Reference-identity multiset for resources that can be registered by
    /// more than one sprite route. UnityEngine.Object overloads equality, so
    /// neither its operator nor a value comparer is safe for ownership.
    /// </summary>
    internal sealed class AssetStreamReferenceCountSet<T>
        where T : class
    {
        private sealed class ReferenceComparer : IEqualityComparer<T>
        {
            internal static readonly ReferenceComparer Instance =
                new ReferenceComparer();

            private ReferenceComparer() { }

            public bool Equals(T left, T right)
            {
                return ReferenceEquals(left, right);
            }

            public int GetHashCode(T value)
            {
                return ReferenceEquals(value, null)
                    ? 0
                    : RuntimeHelpers.GetHashCode(value);
            }
        }

        private readonly Dictionary<T, int> _counts =
            new Dictionary<T, int>(ReferenceComparer.Instance);

        internal void Add(T value)
        {
            if (ReferenceEquals(value, null))
            {
                throw new ArgumentNullException("value");
            }
            int count;
            _counts.TryGetValue(value, out count);
            _counts[value] = checked(count + 1);
        }

        internal bool Remove(T value)
        {
            if (ReferenceEquals(value, null))
            {
                return false;
            }
            int count;
            if (!_counts.TryGetValue(value, out count))
            {
                return false;
            }
            if (count == 1)
            {
                _counts.Remove(value);
            }
            else
            {
                _counts[value] = count - 1;
            }
            return true;
        }

        internal bool Contains(T value)
        {
            return !ReferenceEquals(value, null)
                && _counts.ContainsKey(value);
        }

        internal int Count(T value)
        {
            if (ReferenceEquals(value, null))
            {
                return 0;
            }
            int count;
            return _counts.TryGetValue(value, out count) ? count : 0;
        }
    }

    /// <summary>
    /// Read-only audit of the complete central material surface. The caller
    /// supplies the shader-specific texture reader and the exact
    /// texture-to-owner resolver; foreign arrays and Material instances are
    /// never replaced or mutated by this contract.
    /// </summary>
    internal static class AssetStreamCentralMaterialMaskAudit
    {
        internal static void MarkOwners<TMaterial, TTexture, TOwner>(
            TMaterial[][] materials,
            Func<TMaterial, TTexture> readMask,
            Action<TTexture, ISet<TOwner>> markOwners,
            ISet<TOwner> unsafeOwners)
            where TMaterial : class
            where TTexture : class
        {
            if (materials == null)
            {
                throw new ArgumentNullException("materials");
            }
            if (readMask == null)
            {
                throw new ArgumentNullException("readMask");
            }
            if (markOwners == null)
            {
                throw new ArgumentNullException("markOwners");
            }
            if (unsafeOwners == null)
            {
                throw new ArgumentNullException("unsafeOwners");
            }

            for (int outer = 0; outer < materials.Length; outer++)
            {
                TMaterial[] inner = materials[outer];
                if (inner == null)
                {
                    continue;
                }
                for (int index = 0; index < inner.Length; index++)
                {
                    TMaterial material = inner[index];
                    if (ReferenceEquals(material, null))
                    {
                        continue;
                    }
                    TTexture mask = readMask(material);
                    if (!ReferenceEquals(mask, null))
                    {
                        markOwners(mask, unsafeOwners);
                    }
                }
            }
        }
    }

    internal struct AssetStreamPageMaskDecision<TTexture>
        where TTexture : class
    {
        internal AssetStreamPageMaskDecision(bool write, TTexture texture)
            : this(write, texture, false)
        {
        }

        internal AssetStreamPageMaskDecision(
            bool write,
            TTexture texture,
            bool releaseBlocked)
        {
            Write = write;
            Texture = texture;
            ReleaseBlocked = releaseBlocked;
        }

        internal bool Write { get; private set; }
        internal TTexture Texture { get; private set; }
        internal bool ReleaseBlocked { get; private set; }
    }

    internal struct AssetStreamTrackedPageMask<TTexture>
        where TTexture : class
    {
        internal AssetStreamTrackedPageMask(
            int rendererId,
            object renderer,
            TTexture lastWritten)
        {
            RendererId = rendererId;
            Renderer = renderer;
            LastWritten = lastWritten;
        }

        internal int RendererId { get; private set; }
        internal object Renderer { get; private set; }
        internal TTexture LastWritten { get; private set; }
    }

    /// <summary>
    /// Tracks only the team-mask value written by the asset-stream lane. The
    /// Unity adapter owns the MaterialPropertyBlock and therefore preserves
    /// every property that is not represented here.
    /// </summary>
    internal sealed class AssetStreamPageMaskOwnership<TTexture>
        where TTexture : class
    {
        private const int PruneInterval = 128;

        private sealed class TrackedRoute
        {
            internal TrackedRoute(
                object renderer,
                TTexture lastWritten,
                bool lastWriteOwned)
            {
                Renderer = new WeakReference(renderer);
                LastWritten = lastWritten;
                LastWriteOwned = lastWriteOwned;
            }

            internal WeakReference Renderer { get; private set; }
            internal TTexture LastWritten { get; set; }
            internal bool LastWriteOwned { get; set; }
        }

        private readonly Dictionary<int, TrackedRoute> _routes =
            new Dictionary<int, TrackedRoute>();
        private int _operations;

        internal bool IsTracked(int rendererId, object renderer)
        {
            if (renderer == null)
            {
                return false;
            }
            TrackedRoute route;
            if (!_routes.TryGetValue(rendererId, out route))
            {
                return false;
            }
            object target = route.Renderer.Target;
            if (!ReferenceEquals(target, renderer))
            {
                _routes.Remove(rendererId);
                return false;
            }
            return true;
        }

        internal AssetStreamPageMaskDecision<TTexture> Route(
            int rendererId,
            object renderer,
            bool owned,
            TTexture ownedMask,
            bool blockHasMask,
            TTexture blockMask,
            bool blockMaskOwned,
            bool materialHasMask,
            TTexture materialMask,
            bool materialMaskOwned,
            bool materialIsLaneOwned,
            TTexture neutralMask)
        {
            if (renderer == null)
            {
                throw new ArgumentNullException("renderer");
            }
            if (neutralMask == null)
            {
                throw new ArgumentNullException("neutralMask");
            }
            PruneIfDue();

            TrackedRoute route;
            if (owned)
            {
                if (ownedMask == null)
                {
                    throw new ArgumentNullException("ownedMask");
                }
                bool ownedWrite = !blockHasMask
                    || !ReferenceEquals(blockMask, ownedMask);
                if (!ownedWrite)
                {
                    RecordWriteSucceeded(
                        rendererId,
                        renderer,
                        ownedMask,
                        true);
                }
                return new AssetStreamPageMaskDecision<TTexture>(
                    ownedWrite,
                    ownedMask);
            }

            if (!_routes.TryGetValue(rendererId, out route)
                || !ReferenceEquals(route.Renderer.Target, renderer))
            {
                _routes.Remove(rendererId);
                return default(AssetStreamPageMaskDecision<TTexture>);
            }

            if (!blockHasMask)
            {
                if (materialMaskOwned && !materialIsLaneOwned)
                {
                    return new AssetStreamPageMaskDecision<TTexture>(
                        false,
                        null,
                        true);
                }
                _routes.Remove(rendererId);
                return default(AssetStreamPageMaskDecision<TTexture>);
            }

            // A different, genuine foreign MPB value owns the property and
            // must not be overwritten. A different mask from any currently
            // registered asset-stream page is still ours, however, and must
            // be replaced before those bundle textures can be released.
            if (!ReferenceEquals(blockMask, route.LastWritten)
                && !blockMaskOwned)
            {
                if (materialMaskOwned && !materialIsLaneOwned)
                {
                    return new AssetStreamPageMaskDecision<TTexture>(
                        false,
                        null,
                        true);
                }
                _routes.Remove(rendererId);
                return default(AssetStreamPageMaskDecision<TTexture>);
            }

            // MaterialPropertyBlock has no per-property removal API in the
            // pinned Unity build and rejects a null texture. A process-stable
            // neutral texture removes every owned bundle reference from the
            // block while a shader without _TeamMask ignores it. An owned
            // texture on a FOREIGN sharedMaterial cannot be removed without
            // mutating state we do not own, so that case still blocks release
            // until the material changes. A mask on one of OUR OWN page clones
            // is different: we created that material and destroy it in the
            // same release, so blocking on it is circular. It made every
            // teardown fail with "retains an owned page mask
            // renderer=simpleSprite
            // material=StrongholdEuropeDE.AssetStream.body_jester.page0".
            // Tracking remains live in either case so a later genuine foreign
            // material can take over.
            TTexture replacement = materialHasMask
                    && materialMask != null
                    && !materialMaskOwned
                    && !(route.LastWriteOwned
                        && ReferenceEquals(materialMask, route.LastWritten))
                ? materialMask
                : neutralMask;
            bool write = !ReferenceEquals(blockMask, replacement);
            if (!write)
            {
                route.LastWritten = replacement;
                route.LastWriteOwned = false;
            }
            return new AssetStreamPageMaskDecision<TTexture>(
                write,
                replacement,
                materialMaskOwned && !materialIsLaneOwned);
        }

        internal void RecordWriteSucceeded(
            int rendererId,
            object renderer,
            TTexture texture,
            bool owned)
        {
            if (renderer == null)
            {
                throw new ArgumentNullException("renderer");
            }
            if (texture == null)
            {
                throw new ArgumentNullException("texture");
            }
            TrackedRoute route;
            if (!_routes.TryGetValue(rendererId, out route)
                || !ReferenceEquals(route.Renderer.Target, renderer))
            {
                _routes[rendererId] =
                    new TrackedRoute(renderer, texture, owned);
                return;
            }
            route.LastWritten = texture;
            route.LastWriteOwned = owned;
        }

        internal IList<AssetStreamTrackedPageMask<TTexture>> SnapshotTracked()
        {
            var result = new List<AssetStreamTrackedPageMask<TTexture>>(
                _routes.Count);
            var dead = new List<int>();
            foreach (KeyValuePair<int, TrackedRoute> pair in _routes)
            {
                object renderer = pair.Value.Renderer.Target;
                if (renderer != null)
                {
                    result.Add(new AssetStreamTrackedPageMask<TTexture>(
                        pair.Key,
                        renderer,
                        pair.Value.LastWritten));
                }
                else
                {
                    dead.Add(pair.Key);
                }
            }
            for (int index = 0; index < dead.Count; index++)
            {
                _routes.Remove(dead[index]);
            }
            return result;
        }

        internal void Forget(int rendererId, object renderer)
        {
            TrackedRoute route;
            if (_routes.TryGetValue(rendererId, out route)
                && ReferenceEquals(route.Renderer.Target, renderer))
            {
                _routes.Remove(rendererId);
            }
        }

        private void PruneIfDue()
        {
            _operations++;
            if (_operations < PruneInterval)
            {
                return;
            }
            _operations = 0;
            var dead = new List<int>();
            foreach (KeyValuePair<int, TrackedRoute> pair in _routes)
            {
                if (!pair.Value.Renderer.IsAlive
                    || pair.Value.Renderer.Target == null)
                {
                    dead.Add(pair.Key);
                }
            }
            for (int index = 0; index < dead.Count; index++)
            {
                _routes.Remove(dead[index]);
            }
        }
    }
}
