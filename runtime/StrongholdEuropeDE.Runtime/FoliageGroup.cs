using System;
using System.IO;
using UnityEngine;
using UnityObject = UnityEngine.Object;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// One vegetation GM group whose material the atlas loader gets wrong.
    /// </summary>
    /// <remarks>
    /// `spriteLoader` draws vegetation with Unlit/Foliage, but the 1.39 atlas
    /// loader hard-codes Unlit/TeamColour for every group it overrides. Left
    /// alone, an overridden tree renders through the wrong shader. This type
    /// owns the corrected material for exactly one group and can hand the
    /// original array back untouched.
    ///
    /// Everything is verified before anything is written: the slot must hold
    /// the expected number of TeamColour materials, all sharing one mask
    /// texture; every sprite in the slot must come from one main texture; main
    /// and mask must be distinct, named as our atlas writes them, and still
    /// CPU-readable so the GPU upload can be finalised.
    /// </remarks>
    internal sealed class FoliageGroup
    {
        private const string TeamColourShader = "Unlit/TeamColour";
        private const string TeamMaskProperty = "_TeamMask";
        private const string AtlasTextureName = "atlas";
        private const string MaskTextureName = "atlas_m";

        internal string Name { get; }
        internal int GmIndex { get; }
        internal string AtlasJsonPath { get; }

        private Material[] _original;
        private Material[] _replacement;
        private Material _owned;

        internal FoliageGroup(string name, int gmIndex, string atlasJsonPath)
        {
            Name = name;
            GmIndex = gmIndex;
            AtlasJsonPath = atlasJsonPath;
        }

        internal bool Applied
        {
            get { return _owned != null; }
        }

        internal bool ShipsAtlas
        {
            get { return File.Exists(AtlasJsonPath); }
        }

        /// <summary>
        /// Replace the slot's materials, or report that the loader has not
        /// finished applying our override yet.
        /// </summary>
        /// <remarks>
        /// `spriteLoader.spritesLoaded` turns true before the extender has
        /// applied registered atlas overrides, so vanilla materials in this
        /// slot are a normal transient state - not a failure. Returning false
        /// means "ask again later"; throwing means the shape is wrong.
        /// </remarks>
        internal bool TryApply(Material[][] materials, Sprite[][] sprites, int materialSlotCount)
        {
            if (_owned != null)
            {
                return true;
            }
            Material[] current = materials[GmIndex];
            Sprite[] currentSprites = sprites[GmIndex];
            if (current == null || current.Length != materialSlotCount)
            {
                return false;
            }

            Texture teamMask = null;
            for (int index = 0; index < current.Length; index++)
            {
                Material material = current[index];
                if (material == null
                    || material.shader == null
                    || !string.Equals(
                        material.shader.name, TeamColourShader, StringComparison.Ordinal)
                    || !material.HasProperty(TeamMaskProperty))
                {
                    return false;
                }
                Texture candidate = material.GetTexture(TeamMaskProperty);
                if (candidate == null)
                {
                    return false;
                }
                if (index == 0)
                {
                    teamMask = candidate;
                }
                else if (!ReferenceEquals(teamMask, candidate))
                {
                    return false;
                }
            }

            if (currentSprites == null || currentSprites.Length == 0)
            {
                return false;
            }
            Texture2D mainAtlas = null;
            for (int index = 0; index < currentSprites.Length; index++)
            {
                Sprite sprite = currentSprites[index];
                Texture2D candidate = sprite == null ? null : sprite.texture;
                if (candidate == null)
                {
                    return false;
                }
                if (index == 0)
                {
                    mainAtlas = candidate;
                }
                else if (!ReferenceEquals(mainAtlas, candidate))
                {
                    return false;
                }
            }

            Texture2D maskAtlas = teamMask as Texture2D;
            if (mainAtlas == null
                || maskAtlas == null
                || ReferenceEquals(mainAtlas, maskAtlas)
                || !string.Equals(mainAtlas.name, AtlasTextureName, StringComparison.Ordinal)
                || !string.Equals(maskAtlas.name, MaskTextureName, StringComparison.Ordinal)
                || !mainAtlas.isReadable
                || !maskAtlas.isReadable)
            {
                return false;
            }

            Shader foliage = Shader.Find("Unlit/Foliage");
            if (foliage == null)
            {
                throw new InvalidOperationException(
                    "Unlit/Foliage shader is unavailable for " + Name);
            }

            Material owned = null;
            try
            {
                owned = new Material(foliage);
                owned.name = "StrongholdEuropeDE " + Name + " foliage";
                owned.SetTexture(TeamMaskProperty, maskAtlas);
                Material[] replacement = new Material[materialSlotCount];
                for (int index = 0; index < replacement.Length; index++)
                {
                    replacement[index] = owned;
                }
                if (!ReferenceEquals(materials[GmIndex], current))
                {
                    throw new InvalidOperationException(
                        Name + " material array changed during validation");
                }
                // Drop the CPU copies: they exist only so the override could be
                // uploaded, and holding them wastes memory for every group.
                mainAtlas.Apply(false, true);
                maskAtlas.Apply(false, true);
                if (mainAtlas.isReadable || maskAtlas.isReadable)
                {
                    throw new InvalidOperationException(
                        Name + " atlas CPU copies remained readable after finalization");
                }
                materials[GmIndex] = replacement;
                _original = current;
                _replacement = replacement;
                _owned = owned;
                owned = null;
                return true;
            }
            finally
            {
                if (owned != null)
                {
                    UnityObject.Destroy(owned);
                }
            }
        }

        internal void Rollback(Material[][] materials, bool applicationQuitting)
        {
            if (_owned == null)
            {
                return;
            }
            if (materials != null
                && GmIndex < materials.Length
                && RuntimeDecision.ShouldRestoreOwnedReference(
                    materials[GmIndex], _replacement))
            {
                materials[GmIndex] = _original;
            }
            if (!applicationQuitting)
            {
                UnityObject.Destroy(_owned);
            }
            _owned = null;
            _original = null;
            _replacement = null;
        }
    }
}
