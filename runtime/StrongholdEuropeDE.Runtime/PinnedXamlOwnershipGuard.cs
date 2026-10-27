using System;
using System.IO;
using BepInEx;
using SHCDESE.API;
using SHCDESE.API.Components.ModManager;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Proves that a logical XAML asset still comes from the pinned 1.44 base
    /// and that at most one, byte-pinned project patch contributes to it.
    /// </summary>
    internal static class PinnedXamlOwnershipGuard
    {
        internal static void Verify(
            string logicalPath,
            string pinnedBaseRelativePath,
            long pinnedBaseSize,
            string pinnedBaseSha256,
            string pluginDirectory,
            string ownedPatchRelativePath,
            long ownedPatchSize,
            string ownedPatchSha256,
            bool requireOwnedPatch)
        {
            string baseFullPath = ResolveBelow(
                Paths.GameRootPath,
                pinnedBaseRelativePath,
                "pinned XAML base");
            RequireDigest(
                baseFullPath,
                pinnedBaseSize,
                pinnedBaseSha256,
                "pinned XAML base");

            GameAssetManagerAPI assetManager = GameAssetManagerAPI.Instance;
            if (assetManager == null
                || assetManager.GetType() != typeof(GameAssetManagerAPI))
            {
                throw new InvalidOperationException(
                    "GameAssetManagerAPI.Instance type is not exact");
            }
            string effectivePath;
            if (!assetManager.GetModifiedFilePath(logicalPath, out effectivePath)
                || string.IsNullOrEmpty(effectivePath)
                || !string.Equals(
                    Path.GetFullPath(effectivePath),
                    baseFullPath,
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(
                    "The effective XAML base is not the pinned SHCDE-SE 1.44 file");
            }

            string ownedFullPath = ResolveBelow(
                pluginDirectory,
                ownedPatchRelativePath,
                "owned XAML patch");
            int ownedMatches = 0;
            GameAssetModManager modManager = GameAssetModManager.Instance;
            if (modManager == null
                || modManager.GetType() != typeof(GameAssetModManager))
            {
                throw new InvalidOperationException(
                    "GameAssetModManager.Instance type is not exact");
            }
            foreach (var assetMod in modManager.GetRegisteredAssetDirectories())
            {
                if (string.IsNullOrEmpty(assetMod.Value))
                {
                    throw new InvalidDataException(
                        "Registered asset-mod root is unavailable");
                }
                string candidate = ResolveBelow(
                    assetMod.Value,
                    "Patches/" + logicalPath,
                    "registered XAML patch");
                if (!File.Exists(candidate) && !Directory.Exists(candidate))
                {
                    continue;
                }
                if (Directory.Exists(candidate)
                    || !string.Equals(
                        candidate,
                        ownedFullPath,
                        StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException(
                        "A foreign or additional XAML patch owns " + logicalPath);
                }
                ownedMatches++;
            }

            if (requireOwnedPatch)
            {
                if (ownedMatches != 1 || !File.Exists(ownedFullPath))
                {
                    throw new FileNotFoundException(
                        "The pinned project XAML patch is not registered exactly once",
                        ownedFullPath);
                }
                RequireDigest(
                    ownedFullPath,
                    ownedPatchSize,
                    ownedPatchSha256,
                    "owned XAML patch");
            }
            else if (ownedMatches != 0)
            {
                throw new InvalidDataException(
                    "An unselected project XAML patch is registered");
            }
        }

        internal static void VerifyRegisteredPatches(
            string logicalPath,
            string pluginDirectory,
            string ownedPatchRelativePath,
            long ownedPatchSize,
            string ownedPatchSha256,
            bool allowOwnedPatch)
        {
            string ownedFullPath = ResolveBelow(
                pluginDirectory,
                ownedPatchRelativePath,
                "owned XAML patch");
            int ownedMatches = 0;
            GameAssetModManager modManager = GameAssetModManager.Instance;
            if (modManager == null
                || modManager.GetType() != typeof(GameAssetModManager))
            {
                throw new InvalidOperationException(
                    "GameAssetModManager.Instance type is not exact");
            }
            foreach (var assetMod in modManager.GetRegisteredAssetDirectories())
            {
                if (string.IsNullOrEmpty(assetMod.Value))
                {
                    throw new InvalidDataException(
                        "Registered asset-mod root is unavailable");
                }
                string candidate = ResolveBelow(
                    assetMod.Value,
                    "Patches/" + logicalPath,
                    "registered XAML patch");
                if (!File.Exists(candidate) && !Directory.Exists(candidate))
                {
                    continue;
                }
                if (!allowOwnedPatch
                    || Directory.Exists(candidate)
                    || !string.Equals(
                        candidate,
                        ownedFullPath,
                        StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException(
                        "A registered XAML patch conflicts with the pinned owner: "
                        + logicalPath);
                }
                ownedMatches++;
            }
            if (allowOwnedPatch)
            {
                if (ownedMatches != 1)
                {
                    throw new InvalidDataException(
                        "The selected project XAML patch is not registered exactly once");
                }
                RequireDigest(
                    ownedFullPath,
                    ownedPatchSize,
                    ownedPatchSha256,
                    "owned XAML patch");
            }
        }

        private static void RequireDigest(
            string path,
            long expectedSize,
            string expectedSha256,
            string label)
        {
            string actual = Hashing.Sha256FileStable(path, expectedSize);
            if (!string.Equals(
                actual,
                expectedSha256,
                StringComparison.Ordinal))
            {
                throw new InvalidDataException(label + " SHA-256 mismatch");
            }
        }

        private static string ResolveBelow(
            string root,
            string relativePath,
            string label)
        {
            if (string.IsNullOrEmpty(root)
                || string.IsNullOrEmpty(relativePath)
                || Path.IsPathRooted(relativePath))
            {
                throw new InvalidDataException(label + " path is unavailable");
            }
            string rootFull = Path.GetFullPath(root).TrimEnd(
                Path.DirectorySeparatorChar,
                Path.AltDirectorySeparatorChar);
            string candidate = Path.GetFullPath(Path.Combine(
                rootFull,
                relativePath.Replace('/', Path.DirectorySeparatorChar)));
            string prefix = rootFull + Path.DirectorySeparatorChar;
            if (!candidate.StartsWith(
                prefix,
                StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(label + " escapes its root");
            }
            return candidate;
        }
    }
}
