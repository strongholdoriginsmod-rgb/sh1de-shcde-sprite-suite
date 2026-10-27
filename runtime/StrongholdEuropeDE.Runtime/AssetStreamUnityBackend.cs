using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using Microsoft.Win32.SafeHandles;
using UnityEngine;
using UnityObject = UnityEngine.Object;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed class AssetStreamLoaderSnapshot
    {
        internal AssetStreamLoaderSnapshot(
            Dictionary<string, Sprite> allSprites,
            Sprite[][] gmSprites,
            Sprite[][] gmAltSprites,
            Material[][] gmMaterials,
            Color[][] gmColors)
        {
            AllSprites = allSprites;
            GmSprites = gmSprites;
            GmAltSprites = gmAltSprites;
            GmMaterials = gmMaterials;
            GmColors = gmColors;
        }

        internal Dictionary<string, Sprite> AllSprites { get; private set; }
        internal Sprite[][] GmSprites { get; private set; }
        internal Sprite[][] GmAltSprites { get; private set; }
        internal Material[][] GmMaterials { get; private set; }
        internal Color[][] GmColors { get; private set; }
    }

    /// <summary>
    /// Immutable shallow generation captured after staging. The central field
    /// identities and every replaceable top-level slot/dictionary entry are
    /// frozen so a foreign in-place edit cannot be overwritten by the later
    /// atomic publication swap.
    /// </summary>
    internal sealed class AssetStreamLoaderGenerationSnapshot
    {
        private readonly Dictionary<string, Sprite> _allSpritesIdentity;
        private readonly Sprite[][] _gmSpritesIdentity;
        private readonly Sprite[][] _gmAltSpritesIdentity;
        private readonly Material[][] _gmMaterialsIdentity;
        private readonly Color[][] _gmColorsIdentity;
        private readonly Dictionary<string, Sprite> _allSpritesValues;
        private readonly Sprite[][] _gmSpriteSlots;
        private readonly Sprite[][] _gmAltSpriteSlots;
        private readonly Material[][] _gmMaterialSlots;
        private readonly Color[][] _gmColorSlots;

        internal AssetStreamLoaderGenerationSnapshot(
            AssetStreamLoaderSnapshot current)
        {
            if (current == null) throw new ArgumentNullException("current");
            _allSpritesIdentity = current.AllSprites;
            _gmSpritesIdentity = current.GmSprites;
            _gmAltSpritesIdentity = current.GmAltSprites;
            _gmMaterialsIdentity = current.GmMaterials;
            _gmColorsIdentity = current.GmColors;
            _allSpritesValues = new Dictionary<string, Sprite>(
                current.AllSprites,
                current.AllSprites.Comparer);
            _gmSpriteSlots = (Sprite[][])current.GmSprites.Clone();
            _gmAltSpriteSlots = (Sprite[][])current.GmAltSprites.Clone();
            _gmMaterialSlots = (Material[][])current.GmMaterials.Clone();
            _gmColorSlots = (Color[][])current.GmColors.Clone();
        }

        internal bool Matches(AssetStreamLoaderSnapshot current)
        {
            return current != null
                && ReferenceEquals(current.AllSprites, _allSpritesIdentity)
                && ReferenceEquals(current.GmSprites, _gmSpritesIdentity)
                && ReferenceEquals(current.GmAltSprites, _gmAltSpritesIdentity)
                && ReferenceEquals(current.GmMaterials, _gmMaterialsIdentity)
                && ReferenceEquals(current.GmColors, _gmColorsIdentity)
                && SameDictionaryReferences(
                    current.AllSprites,
                    _allSpritesValues)
                && SameOuterReferences(current.GmSprites, _gmSpriteSlots)
                && SameOuterReferences(
                    current.GmAltSprites,
                    _gmAltSpriteSlots)
                && SameOuterReferences(
                    current.GmMaterials,
                    _gmMaterialSlots)
                && SameOuterReferences(current.GmColors, _gmColorSlots);
        }

        private static bool SameDictionaryReferences(
            IDictionary<string, Sprite> current,
            IDictionary<string, Sprite> frozen)
        {
            if (current == null || frozen == null || current.Count != frozen.Count)
            {
                return false;
            }
            foreach (KeyValuePair<string, Sprite> pair in frozen)
            {
                Sprite value;
                if (!current.TryGetValue(pair.Key, out value)
                    || !ReferenceEquals(value, pair.Value))
                {
                    return false;
                }
            }
            return true;
        }

        private static bool SameOuterReferences<T>(T[][] current, T[][] frozen)
        {
            if (current == null || frozen == null || current.Length != frozen.Length)
            {
                return false;
            }
            for (int index = 0; index < current.Length; index++)
            {
                if (!ReferenceEquals(current[index], frozen[index]))
                {
                    return false;
                }
            }
            return true;
        }
    }

    /// <summary>Exact, pinned spriteLoader field surface.</summary>
    internal sealed class AssetStreamSpriteLoaderSurface
    {
        private const BindingFlags ExactInstance = BindingFlags.Instance
            | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

        private readonly FieldInfo _allSprites;
        private readonly FieldInfo _gmSprites;
        private readonly FieldInfo _gmAltSprites;
        private readonly FieldInfo _gmMaterials;
        private readonly FieldInfo _gmColors;
        private readonly FieldInfo _plainMaterials;

        internal AssetStreamSpriteLoaderSurface()
        {
            Type loader = typeof(spriteLoader);
            if (!string.Equals(loader.FullName, "spriteLoader", StringComparison.Ordinal))
            {
                throw new TypeLoadException("Exact spriteLoader type was not found");
            }
            _allSprites = RequireField(
                loader, "allSprites", typeof(Dictionary<string, Sprite>));
            _gmSprites = RequireField(loader, "gmSprites", typeof(Sprite[][]));
            _gmAltSprites = RequireField(loader, "gmAltSprites", typeof(Sprite[][]));
            _gmMaterials = RequireField(loader, "gmMaterials", typeof(Material[][]));
            _gmColors = RequireField(loader, "gmColors", typeof(Color[][]));
            _plainMaterials = RequireField(
                loader, "plainMaterials", typeof(Material[]));
        }

        internal AssetStreamLoaderSnapshot Read(spriteLoader loader)
        {
            RequireExactLoader(loader);
            var snapshot = new AssetStreamLoaderSnapshot(
                _allSprites.GetValue(loader) as Dictionary<string, Sprite>,
                _gmSprites.GetValue(loader) as Sprite[][],
                _gmAltSprites.GetValue(loader) as Sprite[][],
                _gmMaterials.GetValue(loader) as Material[][],
                _gmColors.GetValue(loader) as Color[][]);
            ValidateCentralShape(snapshot);
            return snapshot;
        }

        internal AssetStreamUnityBaseline CaptureBaseline(
            spriteLoader loader,
            AssetStreamGroupManifest group,
            AssetStreamLoaderSnapshot sharedCentral,
            ReadOnlyDictionary<string, Sprite> frozenAllSprites)
        {
            if (group == null) throw new ArgumentNullException("group");
            if (sharedCentral == null)
                throw new ArgumentNullException("sharedCentral");
            RequireExactLoader(loader);
            AssetStreamLoaderSnapshot value = sharedCentral;
            ValidateCentralShape(value);
            int gm = group.GmId;
            RequireGroupIndex(value, gm);
            Material[] plain = _plainMaterials.GetValue(loader) as Material[];
            if (plain == null || plain.Length != 7)
            {
                throw new InvalidDataException(
                    "spriteLoader.plainMaterials is not the exact seven-slot array");
            }
            return new AssetStreamUnityBaseline(
                loader,
                value.AllSprites,
                value.GmSprites,
                value.GmAltSprites,
                value.GmMaterials,
                value.GmColors,
                value.GmSprites[gm],
                value.GmAltSprites[gm],
                value.GmMaterials[gm],
                value.GmColors[gm],
                ReferenceEquals(value.GmMaterials[gm], plain),
                frozenAllSprites);
        }

        internal void Write(
            spriteLoader loader,
            AssetStreamLoaderSnapshot value)
        {
            RequireExactLoader(loader);
            ValidateCentralShape(value);
            _allSprites.SetValue(loader, value.AllSprites);
            _gmSprites.SetValue(loader, value.GmSprites);
            _gmAltSprites.SetValue(loader, value.GmAltSprites);
            _gmMaterials.SetValue(loader, value.GmMaterials);
            _gmColors.SetValue(loader, value.GmColors);
        }

        internal static void RequireGroupIndex(
            AssetStreamLoaderSnapshot value,
            int gm)
        {
            if (gm < 0
                || gm >= value.GmSprites.Length
                || gm >= value.GmAltSprites.Length
                || gm >= value.GmMaterials.Length
                || gm >= value.GmColors.Length)
            {
                throw new InvalidDataException(
                    "Asset-stream GM id escapes a central spriteLoader array");
            }
        }

        private static FieldInfo RequireField(
            Type loader,
            string name,
            Type fieldType)
        {
            FieldInfo field = loader.GetField(name, ExactInstance);
            if (field == null || field.IsStatic || field.FieldType != fieldType
                || field.DeclaringType != loader)
            {
                throw new MissingFieldException(
                    "Exact spriteLoader." + name + " field was not found");
            }
            return field;
        }

        private static void RequireExactLoader(spriteLoader loader)
        {
            if (ReferenceEquals(loader, null) || loader == null
                || loader.GetType() != typeof(spriteLoader))
            {
                throw new InvalidDataException(
                    "Runtime spriteLoader instance is missing or not exact");
            }
        }

        private static void ValidateCentralShape(AssetStreamLoaderSnapshot value)
        {
            if (value == null
                || value.AllSprites == null
                || value.GmSprites == null
                || value.GmAltSprites == null
                || value.GmMaterials == null
                || value.GmColors == null
                || value.GmSprites.Length != 234
                || value.GmAltSprites.Length != 234
                || value.GmMaterials.Length != 234
                || value.GmColors.Length != 234)
            {
                throw new InvalidDataException(
                    "The five central spriteLoader fields have an unexpected shape");
            }
        }
    }

    internal sealed class AssetStreamPinnedBundle : IDisposable
    {
        internal AssetStreamPinnedBundle(
            string path,
            long length,
            FileStream stream)
        {
            Path = path;
            Length = length;
            Stream = stream;
        }

        internal string Path { get; private set; }
        internal long Length { get; private set; }
        internal FileStream Stream { get; private set; }

        internal void VerifyIdentityStillMatches()
        {
            if (Stream == null || !Stream.CanRead || !Stream.CanSeek
                || Stream.Length != Length)
            {
                throw new IOException(
                    "Verified bundle handle changed while pinned: " + Path);
            }
        }

        public void Dispose()
        {
            FileStream stream = Stream;
            Stream = null;
            if (stream != null)
            {
                stream.Dispose();
            }
        }
    }

    internal static class AssetStreamBundleVerifier
    {
        private const uint CrcPolynomial = 0xedb88320U;
        private const uint GenericRead = 0x80000000U;
        private const uint FileReadAttributes = 0x00000080U;
        private const uint FileFlagOpenReparsePoint = 0x00200000U;
        private const uint FileFlagBackupSemantics = 0x02000000U;
        private const int FileAttributeTagInfoClass = 9;
        private static readonly uint[] CrcTable = BuildCrcTable();

        internal static AssetStreamPinnedBundle OpenVerified(
            string pluginDirectory,
            AssetStreamGroupManifest group)
        {
            string path;
            FileStream stream = null;
            try
            {
                stream = OpenReadOnlyNoFollowUnderRoot(
                    pluginDirectory,
                    group.BundlePath,
                    out path);
                long length = stream.Length;
                if (length != group.BundleSizeBytes)
                {
                    throw new InvalidDataException(
                        "AssetBundle size mismatch: " + group.Group);
                }
                string sha;
                uint crc = uint.MaxValue;
                using (SHA256 algorithm = SHA256.Create())
                {
                    byte[] buffer = new byte[1024 * 1024];
                    int read;
                    while ((read = stream.Read(buffer, 0, buffer.Length)) != 0)
                    {
                        algorithm.TransformBlock(buffer, 0, read, null, 0);
                        for (int index = 0; index < read; index++)
                        {
                            crc = CrcTable[(crc ^ buffer[index]) & 0xff] ^ (crc >> 8);
                        }
                    }
                    algorithm.TransformFinalBlock(new byte[0], 0, 0);
                    sha = Hex(algorithm.Hash);
                }
                string crcHex = (~crc).ToString("x8", CultureInfo.InvariantCulture);
                if (!string.Equals(sha, group.BundleSha256, StringComparison.Ordinal)
                    || !string.Equals(
                        crcHex,
                        group.BundleCrc32,
                        StringComparison.Ordinal))
                {
                    throw new InvalidDataException(
                        "AssetBundle SHA-256/CRC32 mismatch: " + group.Group);
                }
                if (stream.Length != length)
                {
                    throw new IOException(
                        "AssetBundle handle changed during verification: "
                        + group.Group);
                }
                stream.Position = 0;
                var result = new AssetStreamPinnedBundle(
                    path,
                    length,
                    stream);
                stream = null;
                return result;
            }
            finally
            {
                if (stream != null)
                {
                    stream.Dispose();
                }
            }
        }

        /// <summary>
        /// Opens every directory component and the final file itself with
        /// FILE_FLAG_OPEN_REPARSE_POINT. Directory handles remain open until
        /// the final read handle exists, so an attacker cannot replace a
        /// checked ancestor between traversal steps. The returned FileStream
        /// owns the exact no-follow handle; callers must never reopen Path.
        /// </summary>
        internal static FileStream OpenReadOnlyNoFollowUnderRoot(
            string root,
            string relativePath,
            out string path)
        {
            if (Environment.OSVersion.Platform != PlatformID.Win32NT)
            {
                throw new PlatformNotSupportedException(
                    "Asset-stream no-follow opens require Windows");
            }
            path = ResolveUnderRoot(root, relativePath);
            if (path.StartsWith("\\\\", StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Network asset-stream roots are not supported");
            }
            string volumeRoot = Path.GetPathRoot(path);
            if (string.IsNullOrEmpty(volumeRoot)
                || volumeRoot.StartsWith("\\\\", StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Asset-stream root is not a local drive path");
            }
            string suffix = path.Substring(volumeRoot.Length);
            string[] components = suffix.Split(
                new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar },
                StringSplitOptions.RemoveEmptyEntries);
            if (components.Length == 0)
            {
                throw new InvalidDataException(
                    "Asset-stream path has no final file component");
            }

            var directories = new List<SafeFileHandle>(components.Length - 1);
            SafeFileHandle finalHandle = null;
            try
            {
                string current = volumeRoot;
                for (int index = 0; index < components.Length; index++)
                {
                    current = Path.Combine(current, components[index]);
                    bool final = index == components.Length - 1;
                    SafeFileHandle handle = OpenNoFollowHandle(current, final);
                    try
                    {
                        RequireOrdinaryHandle(handle, current, !final);
                    }
                    catch
                    {
                        handle.Dispose();
                        throw;
                    }
                    if (final)
                    {
                        finalHandle = handle;
                    }
                    else
                    {
                        directories.Add(handle);
                    }
                }

                var stream = new FileStream(
                    finalHandle,
                    FileAccess.Read,
                    4096,
                    false);
                finalHandle = null;
                return stream;
            }
            finally
            {
                if (finalHandle != null)
                {
                    finalHandle.Dispose();
                }
                for (int index = directories.Count - 1; index >= 0; index--)
                {
                    directories[index].Dispose();
                }
            }
        }

        internal static string ResolveUnderRoot(string root, string relativePath)
        {
            if (string.IsNullOrEmpty(root))
            {
                throw new ArgumentNullException("root");
            }
            if (!AssetStreamManifestRules.IsSafeRelativePath(relativePath))
            {
                throw new InvalidDataException("Unsafe asset-stream relative path");
            }
            string fullRoot = Path.GetFullPath(root);
            string rootAnchor = Path.GetPathRoot(fullRoot);
            if (!string.IsNullOrEmpty(rootAnchor)
                && fullRoot.Length > rootAnchor.Length)
            {
                fullRoot = fullRoot.TrimEnd(
                    Path.DirectorySeparatorChar,
                    Path.AltDirectorySeparatorChar);
            }
            string candidate = Path.GetFullPath(Path.Combine(
                fullRoot,
                relativePath.Replace('/', Path.DirectorySeparatorChar)));
            string prefix = fullRoot.EndsWith(
                    Path.DirectorySeparatorChar.ToString(),
                    StringComparison.Ordinal)
                ? fullRoot
                : fullRoot + Path.DirectorySeparatorChar;
            if (!candidate.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(
                    "Asset-stream path escapes the plugin directory");
            }
            return candidate;
        }

        private static SafeFileHandle OpenNoFollowHandle(
            string path,
            bool finalFile)
        {
            uint desiredAccess = finalFile ? GenericRead : FileReadAttributes;
            uint flags = FileFlagOpenReparsePoint
                | (finalFile ? 0U : FileFlagBackupSemantics);
            SafeFileHandle handle = CreateFile(
                ToExtendedPath(path),
                desiredAccess,
                FileShare.Read,
                IntPtr.Zero,
                FileMode.Open,
                flags,
                IntPtr.Zero);
            if (handle == null || handle.IsInvalid)
            {
                int error = Marshal.GetLastWin32Error();
                if (handle != null)
                {
                    handle.Dispose();
                }
                throw new IOException(
                    "No-follow asset-stream open failed (win32="
                    + error.ToString(CultureInfo.InvariantCulture) + "): " + path);
            }
            return handle;
        }

        private static void RequireOrdinaryHandle(
            SafeFileHandle handle,
            string path,
            bool expectDirectory)
        {
            FileAttributeTagInformation information;
            if (!GetFileInformationByHandleEx(
                    handle,
                    FileAttributeTagInfoClass,
                    out information,
                    (uint)Marshal.SizeOf(typeof(FileAttributeTagInformation))))
            {
                throw new IOException(
                    "Cannot inspect no-follow asset-stream handle (win32="
                    + Marshal.GetLastWin32Error().ToString(
                        CultureInfo.InvariantCulture)
                    + "): " + path);
            }
            FileAttributes attributes = (FileAttributes)information.FileAttributes;
            if ((attributes & FileAttributes.ReparsePoint) != 0
                || information.ReparseTag != 0)
            {
                throw new InvalidDataException(
                    "Asset-stream path contains a reparse point: " + path);
            }
            bool directory = (attributes & FileAttributes.Directory) != 0;
            if (directory != expectDirectory)
            {
                throw new InvalidDataException(
                    expectDirectory
                        ? "Asset-stream path component is not a directory: " + path
                        : "Asset-stream bundle is not an ordinary file: " + path);
            }
        }

        private static string ToExtendedPath(string path)
        {
            return path.StartsWith("\\\\?\\", StringComparison.Ordinal)
                ? path
                : "\\\\?\\" + path;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct FileAttributeTagInformation
        {
            internal uint FileAttributes;
            internal uint ReparseTag;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFile(
            string fileName,
            uint desiredAccess,
            FileShare shareMode,
            IntPtr securityAttributes,
            FileMode creationDisposition,
            uint flagsAndAttributes,
            IntPtr templateFile);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetFileInformationByHandleEx(
            SafeFileHandle file,
            int informationClass,
            out FileAttributeTagInformation information,
            uint bufferSize);

        private static uint[] BuildCrcTable()
        {
            var table = new uint[256];
            for (uint value = 0; value < table.Length; value++)
            {
                uint current = value;
                for (int bit = 0; bit < 8; bit++)
                {
                    current = (current & 1) != 0
                        ? CrcPolynomial ^ (current >> 1)
                        : current >> 1;
                }
                table[value] = current;
            }
            return table;
        }

        private static string Hex(byte[] value)
        {
            const string alphabet = "0123456789abcdef";
            var output = new char[value.Length * 2];
            for (int index = 0; index < value.Length; index++)
            {
                output[index * 2] = alphabet[value[index] >> 4];
                output[index * 2 + 1] = alphabet[value[index] & 15];
            }
            return new string(output);
        }
    }

    /// <summary>
    /// Unity implementation of the generic two-admission backend. Everything
    /// through Sprite.Create is staged; only Publish writes central fields.
    /// </summary>
    internal sealed class UnityAssetStreamGroupBackend
        : IAssetStreamGroupBackend<AssetStreamUnityBaseline, AssetStreamUnityCommitted>
    {
        private const int MaterialSlotCount = 7;
        private const string TeamColourShader = "Unlit/TeamColour";
        private const string FoliageShader = "Unlit/Foliage";
        private const string TeamMaskProperty = "_TeamMask";
        private const string SpriteCutoffProperty = "_SpriteCutoff";

        private readonly object _gate = new object();
        private readonly string _pluginDirectory;
        private readonly AssetStreamSpriteLoaderSurface _surface;
        private readonly AssetStreamPageMaterialRegistry _routes;
        private readonly HashSet<string> _foliageGroups;
        private readonly Dictionary<string, AssetStreamPinnedBundle> _verified =
            new Dictionary<string, AssetStreamPinnedBundle>(StringComparer.Ordinal);
        private readonly Dictionary<AssetBundle, AssetStreamPinnedBundle>
            _bundleStreams =
                new Dictionary<AssetBundle, AssetStreamPinnedBundle>(
                    AssetStreamReferenceComparer<AssetBundle>.Instance);
        private readonly List<AssetStreamUnityCommitted> _pendingStagedCleanup =
            new List<AssetStreamUnityCommitted>();
        private readonly List<DetachedBundleCleanup> _pendingBundleCleanup =
            new List<DetachedBundleCleanup>();
        private readonly Dictionary<string, PublishedGroupRecord> _published =
            new Dictionary<string, PublishedGroupRecord>(StringComparer.Ordinal);
        private readonly Dictionary<AssetStreamOwnershipToken, AssetStreamRestoreResult>
            _batchRestoreResults =
                new Dictionary<AssetStreamOwnershipToken, AssetStreamRestoreResult>();
        private readonly Dictionary<AssetStreamOwnershipToken, bool>
            _batchReleaseSafety =
                new Dictionary<AssetStreamOwnershipToken, bool>();
        private readonly AssetStreamGlobalUnloadBatch<IAssetStreamGlobalUnloadParticipant>
            _globalUnloadBatch =
                new AssetStreamGlobalUnloadBatch<IAssetStreamGlobalUnloadParticipant>();
        private AsyncOperation _globalUnloadOperation;

        internal UnityAssetStreamGroupBackend(
            string pluginDirectory,
            AssetStreamSpriteLoaderSurface surface,
            AssetStreamPageMaterialRegistry routes,
            IEnumerable<string> foliageGroups)
        {
            _pluginDirectory = pluginDirectory
                ?? throw new ArgumentNullException("pluginDirectory");
            _surface = surface ?? throw new ArgumentNullException("surface");
            _routes = routes ?? throw new ArgumentNullException("routes");
            _foliageGroups = new HashSet<string>(
                foliageGroups ?? throw new ArgumentNullException("foliageGroups"),
                StringComparer.Ordinal);
        }

        public void Verify(AssetStreamGroupManifest group)
        {
            if (group == null) throw new ArgumentNullException("group");
            if (group.PipelineVersion
                == AssetStreamPipelineVersion.Bc7VisualEquivalenceV2)
            {
                bool supported;
                try
                {
                    supported = SystemInfo.SupportsTextureFormat(TextureFormat.BC7);
                }
                catch (Exception exception)
                {
                    throw new AssetStreamLoadException(
                        "BC7 Texture2D support query failed",
                        true,
                        exception);
                }
                try
                {
                    AssetStreamManifestRules.RequireBc7RuntimeSupport(true, supported);
                }
                catch (InvalidOperationException exception)
                {
                    throw new AssetStreamLoadException(
                        "BC7 Texture2D support is unavailable",
                        true,
                        exception);
                }
            }
            AssetStreamPinnedBundle pinned;
            try
            {
                pinned = AssetStreamBundleVerifier.OpenVerified(
                    _pluginDirectory,
                    group);
            }
            catch (InvalidDataException exception)
            {
                // Size/hash/CRC/path contract failures cannot heal within a
                // map epoch and must never be rehashed on every lookup.
                throw new AssetStreamLoadException(
                    "AssetBundle verification contract failed",
                    true,
                    exception);
            }
            catch (UnauthorizedAccessException exception)
            {
                throw new AssetStreamLoadException(
                    "AssetBundle cannot be opened under the compiled root",
                    true,
                    exception);
            }
            catch (IOException exception)
            {
                // File replacement/locking races may heal in a later map epoch.
                throw new AssetStreamLoadException(
                    "AssetBundle verification was interrupted",
                    false,
                    exception);
            }
            lock (_gate)
            {
                AssetStreamPinnedBundle previous;
                if (_verified.TryGetValue(group.Group, out previous))
                {
                    previous.Dispose();
                }
                _verified[group.Group] = pinned;
            }
        }

        public IAssetStreamGroupTransaction<AssetStreamUnityCommitted> BeginTransaction(
            AssetStreamGroupManifest group,
            AssetStreamBaseline<AssetStreamUnityBaseline> baseline,
            AssetStreamOwnershipToken ownership,
            AssetStreamCleanupCompletion cleanupCompletion)
        {
            if (group == null) throw new ArgumentNullException("group");
            if (baseline == null) throw new ArgumentNullException("baseline");
            if (cleanupCompletion == null)
                throw new ArgumentNullException("cleanupCompletion");
            AssetStreamPinnedBundle pinned = TakeVerified(group.Group);
            AssetBundle bundle = null;
            AssetStreamUnityCommitted staged = null;
            try
            {
                ValidateBaseline(group, baseline.Value);
                pinned.VerifyIdentityStillMatches();
                // bundle_crc32 is the raw IEEE/zlib file CRC anchored by the
                // index, not Unity's optional content-CRC argument. It has
                // already been checked above; passing it to Unity would apply
                // a different CRC contract and reject valid bundles.
                pinned.Stream.Position = 0;
                bundle = AssetBundle.LoadFromStream(
                    pinned.Stream,
                    0U,
                    32U * 1024U);
                if (bundle == null)
                {
                    throw Permanent("Unity rejected the verified AssetBundle");
                }
                BindBundleStream(bundle, pinned);
                pinned = null;
                cleanupCompletion.MarkPending();
                staged = Stage(
                    group,
                    baseline.Value,
                    ownership,
                    bundle,
                    cleanupCompletion);
                bundle = null;
                return new AssetStreamUnityTransaction(this, group, baseline, staged);
            }
            catch (Exception exception)
            {
                bool cleanupComplete = true;
                Exception cleanupFailure = null;
                if (bundle != null)
                {
                    try
                    {
                        AssetStreamPinnedBundle cleanupStream = pinned
                            ?? TakeBundleStream(bundle);
                        pinned = null;
                        cleanupComplete = ScheduleDetachedBundleCleanup(
                            bundle,
                            cleanupStream,
                            cleanupCompletion);
                    }
                    catch (Exception cleanupException)
                    {
                        cleanupComplete = false;
                        cleanupFailure = cleanupException;
                    }
                    finally
                    {
                        // Ownership has moved to the retained cleanup record,
                        // including when its first Unity call failed.
                        bundle = null;
                    }
                }

                AssetStreamLoadException known =
                    exception as AssetStreamLoadException;
                if (cleanupComplete && known != null)
                {
                    throw;
                }
                string message = exception is OutOfMemoryException
                    ? "Out of memory while staging the AssetBundle"
                    : (known == null
                        ? "AssetBundle staging failed"
                        : known.Message);
                if (!cleanupComplete)
                {
                    message += "; native cleanup remains asynchronous";
                }
                if (cleanupFailure != null)
                {
                    message += ": " + Describe(cleanupFailure);
                }
                throw new AssetStreamLoadException(
                    message,
                    !cleanupComplete || (known != null && known.Permanent)
                        || !(exception is OutOfMemoryException),
                    !cleanupComplete,
                    exception);
            }
            finally
            {
                if (pinned != null)
                {
                    pinned.Dispose();
                }
            }
        }

        public AssetStreamRestoreResult RestoreBaseline(
            AssetStreamGroupManifest group,
            AssetStreamBaseline<AssetStreamUnityBaseline> baseline,
            AssetStreamOwnedGroup<AssetStreamUnityCommitted> owned)
        {
            if (group == null || baseline == null || owned == null)
            {
                throw new ArgumentNullException("restore input");
            }
            AssetStreamUnityCommitted committed = owned.Value;
            if (!owned.Ownership.Equals(committed.Ownership)
                || !ReferenceEquals(baseline.Value.Loader, committed.Loader))
            {
                return new AssetStreamRestoreResult(
                    AssetStreamRestoreDisposition.UnsafeToRelease,
                    false,
                    "ownership/baseline identity mismatch");
            }
            AssetStreamRestoreResult result;
            lock (_gate)
            {
                if (TryTakeBatchRestoreResultLocked(
                    owned.Ownership,
                    out result))
                {
                    return result;
                }
                PublishedGroupRecord record;
                if (!_published.TryGetValue(group.Group, out record)
                    || !ReferenceEquals(record.Committed, committed)
                    || !ReferenceEquals(record.Baseline, baseline))
                {
                    return new AssetStreamRestoreResult(
                        AssetStreamRestoreDisposition.UnsafeToRelease,
                        false,
                        "published ownership registry does not match controller state");
                }
            }
            BuildBatchRestore(owned.Ownership.Epoch);
            lock (_gate)
            {
                if (TryTakeBatchRestoreResultLocked(
                    owned.Ownership,
                    out result))
                {
                    return result;
                }
            }
            return new AssetStreamRestoreResult(
                AssetStreamRestoreDisposition.RetryRequired,
                false,
                "batch restore produced no result for the requested owner");
        }

        private void BuildBatchRestore(long epoch)
        {
            List<PublishedGroupRecord> records;
            lock (_gate)
            {
                records = new List<PublishedGroupRecord>();
                foreach (PublishedGroupRecord record in _published.Values)
                {
                    if (!record.Detached
                        && record.Committed.Ownership.Epoch == epoch)
                    {
                        records.Add(record);
                    }
                }
            }
            if (records.Count == 0)
            {
                return;
            }

            var results = new Dictionary<
                AssetStreamOwnershipToken,
                AssetStreamRestoreResult>();
            try
            {
                spriteLoader loader = records[0].Committed.Loader;
                AssetStreamLoaderSnapshot current = _surface.Read(loader);
                AssetStreamLoaderSnapshot replacement = CloneCentral(current);
                var changed = new HashSet<AssetStreamOwnershipToken>();
                var unsafeOwners = new HashSet<AssetStreamOwnershipToken>();
                var foreignOwners = new HashSet<AssetStreamOwnershipToken>();

                for (int recordIndex = 0;
                    recordIndex < records.Count;
                    recordIndex++)
                {
                    PublishedGroupRecord record = records[recordIndex];
                    AssetStreamUnityCommitted committed = record.Committed;
                    AssetStreamUnityBaseline baseline = record.Baseline.Value;
                    if (!ReferenceEquals(committed.Loader, loader)
                        || !ReferenceEquals(baseline.Loader, loader))
                    {
                        throw new InvalidOperationException(
                            "Published groups do not share one exact spriteLoader");
                    }
                    int gm = record.Manifest.GmId;
                    AssetStreamSpriteLoaderSurface.RequireGroupIndex(current, gm);
                    if (ReferenceEquals(current.GmSprites[gm], committed.MainSprites))
                    {
                        replacement.GmSprites[gm] = baseline.GroupSprites;
                        changed.Add(committed.Ownership);
                    }
                    if (ReferenceEquals(current.GmAltSprites[gm], committed.AltSprites))
                    {
                        replacement.GmAltSprites[gm] = baseline.GroupAltSprites;
                        changed.Add(committed.Ownership);
                    }
                    if (!ReferenceEquals(
                            committed.PublishedGroupMaterials,
                            baseline.GroupMaterials)
                        && ReferenceEquals(
                            current.GmMaterials[gm],
                            committed.PublishedGroupMaterials))
                    {
                        replacement.GmMaterials[gm] = baseline.GroupMaterials;
                        changed.Add(committed.Ownership);
                    }
                    for (int frameIndex = 0;
                        frameIndex < committed.Atlas.Frames.Count;
                        frameIndex++)
                    {
                        string name = committed.Atlas.Frames[frameIndex].Name;
                        Sprite now;
                        bool hasNow = current.AllSprites.TryGetValue(name, out now);
                        AssetStreamOriginalSpriteEntry original;
                        if (!committed.OriginalSprites.TryGetValue(
                                name,
                                out original))
                        {
                            unsafeOwners.Add(committed.Ownership);
                            continue;
                        }
                        if (hasNow && committed.CreatedSpriteSet.Contains(now))
                        {
                            if (original.Existed)
                            {
                                replacement.AllSprites[name] = original.Value;
                            }
                            else
                            {
                                replacement.AllSprites.Remove(name);
                            }
                            changed.Add(committed.Ownership);
                        }
                        else if (original.Existed != hasNow
                            || (original.Existed
                                && !ReferenceEquals(original.Value, now)))
                        {
                            // The target key no longer belongs to us. Preserve
                            // the foreign value (including a foreign removal)
                            // and report that ownership-aware outcome.
                            foreignOwners.Add(committed.Ownership);
                        }
                    }
                }

                if (changed.Count != 0)
                {
                    WriteWithRollback(loader, current, replacement);
                    current = _surface.Read(loader);
                }
                MarkCentralOwnedReferences(
                    current,
                    records,
                    unsafeOwners);

                for (int index = 0; index < records.Count; index++)
                {
                    PublishedGroupRecord record = records[index];
                    AssetStreamUnityCommitted committed = record.Committed;
                    AssetStreamUnityBaseline baseline = record.Baseline.Value;
                    AssetStreamOwnershipToken ownership = committed.Ownership;
                    if (unsafeOwners.Contains(ownership))
                    {
                        results.Add(
                            ownership,
                            new AssetStreamRestoreResult(
                                AssetStreamRestoreDisposition.UnsafeToRelease,
                                false,
                                "central state still references an owned object"));
                        continue;
                    }
                    int gm = record.Manifest.GmId;
                    bool foreign = !ReferenceEquals(
                            current.GmSprites[gm], baseline.GroupSprites)
                        || !ReferenceEquals(
                            current.GmAltSprites[gm], baseline.GroupAltSprites)
                        || !ReferenceEquals(
                            current.GmMaterials[gm], baseline.GroupMaterials)
                        || foreignOwners.Contains(ownership);
                    // Central ownership is detached now, while native objects
                    // intentionally survive the two-LateUpdate release delay.
                    // Stop new Body acquisitions, but retain every exact mask
                    // identity until the final central/MPB release audit and
                    // native cleanup have become one uninterrupted main-thread
                    // operation.
                    _routes.DetachRoutes(ownership);
                    results.Add(
                        ownership,
                        new AssetStreamRestoreResult(
                            foreign
                                ? AssetStreamRestoreDisposition.ForeignOwnerPreserved
                                : (changed.Contains(ownership)
                                    ? AssetStreamRestoreDisposition.RestoredBaseline
                                    : AssetStreamRestoreDisposition.AlreadyDetached),
                            true,
                            foreign
                                ? "owned references detached; foreign group owner preserved"
                                : "baseline references restored in one batch"));
                }
            }
            catch (Exception exception)
            {
                results.Clear();
                for (int index = 0; index < records.Count; index++)
                {
                    results[records[index].Committed.Ownership] =
                        new AssetStreamRestoreResult(
                            AssetStreamRestoreDisposition.RetryRequired,
                            false,
                            "batch restore failed: " + Describe(exception));
                }
            }

            lock (_gate)
            {
                foreach (KeyValuePair<
                    AssetStreamOwnershipToken,
                    AssetStreamRestoreResult> pair in results)
                {
                    _batchRestoreResults[pair.Key] = pair.Value;
                }
            }
        }

        private bool TryTakeBatchRestoreResultLocked(
            AssetStreamOwnershipToken ownership,
            out AssetStreamRestoreResult result)
        {
            if (!_batchRestoreResults.TryGetValue(ownership, out result))
            {
                return false;
            }
            _batchRestoreResults.Remove(ownership);
            if (result.OwnedReferencesDetached)
            {
                PublishedGroupRecord record;
                if (_published.TryGetValue(ownership.GroupId, out record)
                    && record.Committed.Ownership.Equals(ownership))
                {
                    record.Detached = true;
                }
            }
            return true;
        }

        private void MarkCentralOwnedReferences(
            AssetStreamLoaderSnapshot current,
            IList<PublishedGroupRecord> records,
            HashSet<AssetStreamOwnershipToken> unsafeOwners)
        {
            var sprites = new Dictionary<Sprite, AssetStreamOwnershipToken>(
                AssetStreamReferenceComparer<Sprite>.Instance);
            var materials = new Dictionary<Material, AssetStreamOwnershipToken>(
                AssetStreamReferenceComparer<Material>.Instance);
            for (int index = 0; index < records.Count; index++)
            {
                AssetStreamUnityCommitted committed = records[index].Committed;
                foreach (Sprite sprite in committed.CreatedSpriteSet)
                {
                    sprites[sprite] = committed.Ownership;
                }
                foreach (Material material in committed.CreatedMaterialSet)
                {
                    materials[material] = committed.Ownership;
                }
            }
            foreach (Sprite sprite in current.AllSprites.Values)
            {
                MarkOwner(sprite, sprites, unsafeOwners);
            }
            MarkOwners(current.GmSprites, sprites, unsafeOwners);
            MarkOwners(current.GmAltSprites, sprites, unsafeOwners);
            for (int outer = 0; outer < current.GmMaterials.Length; outer++)
            {
                Material[] inner = current.GmMaterials[outer];
                if (inner == null) continue;
                for (int index = 0; index < inner.Length; index++)
                {
                    MarkOwner(inner[index], materials, unsafeOwners);
                }
            }
            AssetStreamCentralMaterialMaskAudit.MarkOwners(
                current.GmMaterials,
                ReadTeamMask,
                _routes.MarkOwnersOfMask,
                unsafeOwners);
        }

        private static Texture ReadTeamMask(Material material)
        {
            if (ReferenceEquals(material, null)
                || material == null
                || !material.HasProperty(TeamMaskProperty))
            {
                return null;
            }
            return material.GetTexture(TeamMaskProperty);
        }

        private void BuildBatchReleaseSafety(long epoch)
        {
            List<PublishedGroupRecord> records;
            lock (_gate)
            {
                records = new List<PublishedGroupRecord>();
                foreach (PublishedGroupRecord record in _published.Values)
                {
                    if (record.Detached
                        && !record.Committed.Released
                        && record.Committed.Ownership.Epoch == epoch)
                    {
                        records.Add(record);
                    }
                }
            }
            if (records.Count == 0)
            {
                return;
            }
            var unsafeOwners = new HashSet<AssetStreamOwnershipToken>();
            AssetStreamLoaderSnapshot current =
                _surface.Read(records[0].Committed.Loader);
            MarkCentralOwnedReferences(current, records, unsafeOwners);
            lock (_gate)
            {
                for (int index = 0; index < records.Count; index++)
                {
                    AssetStreamOwnershipToken owner =
                        records[index].Committed.Ownership;
                    _batchReleaseSafety[owner] =
                        !unsafeOwners.Contains(owner);
                }
            }
        }

        private bool TryTakeBatchReleaseSafetyLocked(
            AssetStreamOwnershipToken ownership,
            out bool safe)
        {
            if (!_batchReleaseSafety.TryGetValue(ownership, out safe))
            {
                return false;
            }
            _batchReleaseSafety.Remove(ownership);
            return true;
        }

        private static void MarkOwners(
            Sprite[][] outer,
            Dictionary<Sprite, AssetStreamOwnershipToken> owners,
            HashSet<AssetStreamOwnershipToken> unsafeOwners)
        {
            for (int first = 0; first < outer.Length; first++)
            {
                Sprite[] inner = outer[first];
                if (inner == null) continue;
                for (int second = 0; second < inner.Length; second++)
                {
                    MarkOwner(inner[second], owners, unsafeOwners);
                }
            }
        }

        private static void MarkOwner<T>(
            T value,
            Dictionary<T, AssetStreamOwnershipToken> owners,
            HashSet<AssetStreamOwnershipToken> unsafeOwners)
            where T : class
        {
            if (ReferenceEquals(value, null))
            {
                return;
            }
            AssetStreamOwnershipToken owner;
            if (owners.TryGetValue(value, out owner))
            {
                unsafeOwners.Add(owner);
            }
        }

        public AssetStreamReleaseResult Release(
            AssetStreamGroupManifest group,
            AssetStreamOwnedGroup<AssetStreamUnityCommitted> owned)
        {
            if (group == null || owned == null)
            {
                throw new ArgumentNullException("release input");
            }
            AssetStreamUnityCommitted committed = owned.Value;
            if (!owned.Ownership.Equals(committed.Ownership)
                || committed.UnsafeCentralReferences)
            {
                return new AssetStreamReleaseResult(
                    false,
                    false,
                    "owned objects are retained because central detach is unproved");
            }
            if (committed.Released)
            {
                return new AssetStreamReleaseResult(true, false, "already released");
            }

            try
            {
                bool safe;
                // Never consume another owner's earlier batch result as a
                // release proof. A foreign/baseline Material can acquire an
                // owned _TeamMask between main-thread frames, so every native
                // cleanup attempt refreshes the complete central audit first.
                BuildBatchReleaseSafety(committed.Ownership.Epoch);
                lock (_gate)
                {
                    if (!TryTakeBatchReleaseSafetyLocked(
                            committed.Ownership,
                            out safe))
                    {
                        return new AssetStreamReleaseResult(
                            false,
                            true,
                            "central release audit produced no ownership result");
                    }
                }
                if (!safe)
                {
                    return new AssetStreamReleaseResult(
                        false,
                        false,
                        "central loader reacquired an owned object during release delay");
                }
                return AdvanceNativeCleanup(committed);
            }
            catch (Exception exception)
            {
                return new AssetStreamReleaseResult(
                    false,
                    true,
                    "release failed: " + Describe(exception));
            }
        }

        internal AssetStreamUnityCommitted Publish(
            AssetStreamGroupManifest group,
            AssetStreamBaseline<AssetStreamUnityBaseline> baseline,
            AssetStreamUnityCommitted staged)
        {
            AssetStreamLoaderSnapshot current = _surface.Read(staged.Loader);
            AssetStreamLoaderGenerationSnapshot expected = staged.PublishExpected;
            AssetStreamLoaderSnapshot replacement = staged.PublishReplacement;
            if (expected == null || replacement == null
                || !expected.Matches(current))
            {
                throw Permanent(
                    "Central spriteLoader generation drifted after staging");
            }
            ValidatePublishOwnership(group, baseline.Value, current, staged);

            bool pageMasksRegistered = false;
            try
            {
                _routes.Register(
                    staged.Ownership,
                    staged.Atlas,
                    staged.Pages,
                    staged.CreatedSprites);
                pageMasksRegistered = true;
                lock (_gate)
                {
                    if (_published.ContainsKey(group.Group))
                    {
                        throw new InvalidOperationException(
                            "Asset-stream group already has a published owner");
                    }
                    _published.Add(
                        group.Group,
                        new PublishedGroupRecord(group, baseline, staged));
                }
                WriteWithRollback(staged.Loader, current, replacement);
                staged.ClearPublicationPlan();
            }
            catch (Exception exception)
            {
                lock (_gate)
                {
                    PublishedGroupRecord record;
                    if (_published.TryGetValue(group.Group, out record)
                        && ReferenceEquals(record.Committed, staged))
                    {
                        _published.Remove(group.Group);
                    }
                }
                bool safe = false;
                try
                {
                    safe = !HasCentralOwnedReferences(
                        _surface.Read(staged.Loader),
                        staged);
                    if (safe && pageMasksRegistered)
                    {
                        // Keep mask ownership live until the central scan has
                        // proved that even foreign/baseline Materials do not
                        // retain one of this failed publication's textures.
                        _routes.Unregister(staged.Ownership);
                    }
                }
                catch
                {
                    safe = false;
                }
                staged.UnsafeCentralReferences = !safe;
                staged.ClearPublicationPlan();
                throw new AssetStreamLoadException(
                    safe
                        ? "Atomic central publication failed and was rolled back"
                        : "Atomic publication failed; detach could not be proved",
                    true,
                    exception);
            }

            // Publication is now authoritative. Detaching is an optimization,
            // not a correctness precondition, so an unload failure must never
            // turn a successfully published group into a false rollback.
            TryDetachPublishedBundle(staged);
            return staged;
        }

        /// <summary>
        /// Releases a successfully published group's bundle container while
        /// keeping every explicitly loaded Texture2D alive. A failed unload
        /// leaves bundle/stream ownership attached for the normal release path.
        /// </summary>
        private void TryDetachPublishedBundle(AssetStreamUnityCommitted staged)
        {
            AssetBundle bundle = staged.Bundle;
            if (bundle == null)
            {
                return;
            }

            try
            {
                AssetStreamPinnedBundle pinned = UnloadBoundBundle(bundle);
                staged.Bundle = null;
                try
                {
                    pinned.VerifyIdentityStillMatches();
                }
                finally
                {
                    pinned.Dispose();
                }
                int activeLeases;
                lock (_gate)
                {
                    activeLeases = _bundleStreams.Count;
                }
                Debug.Log(
                    "SEDE_RUNTIME_V1|event=bundle_detached|group="
                    + staged.Ownership.GroupId
                    + "|active_bundle_leases="
                    + activeLeases.ToString(CultureInfo.InvariantCulture));
            }
            catch (Exception exception)
            {
                Debug.LogWarning(
                    "SEDE_RUNTIME_V1|event=bundle_detach_deferred|group="
                    + staged.Ownership.GroupId
                    + "|detail="
                    + Describe(exception));
            }
        }

        internal void AbortStaged(AssetStreamUnityCommitted staged)
        {
            if (staged == null || staged.Released)
            {
                return;
            }
            if (staged.UnsafeCentralReferences)
            {
                throw new InvalidOperationException(
                    "Cannot destroy staged objects while a central reference may remain");
            }
            staged.ClearPublicationPlan();
            AssetStreamLoaderSnapshot current = _surface.Read(staged.Loader);
            if (HasCentralOwnedReferences(current, staged))
            {
                staged.UnsafeCentralReferences = true;
                throw new InvalidOperationException(
                    "Cannot abort while central loader references staged objects");
            }
            AssetStreamReleaseResult result;
            try
            {
                result = AdvanceNativeCleanup(staged);
            }
            catch
            {
                RetainPendingStagedCleanup(staged);
                throw;
            }
            if (!result.Released)
            {
                RetainPendingStagedCleanup(staged);
                return;
            }
        }

        /// <summary>
        /// Continues cleanup that could not complete synchronously while a
        /// failed/unpublished transaction returned vanilla. Its reservation is
        /// conservatively retained by the controller until process exit.
        /// </summary>
        internal void AdvancePendingCleanup()
        {
            List<AssetStreamUnityCommitted> staged;
            List<DetachedBundleCleanup> bundles;
            lock (_gate)
            {
                staged = new List<AssetStreamUnityCommitted>(
                    _pendingStagedCleanup);
                bundles = new List<DetachedBundleCleanup>(
                    _pendingBundleCleanup);
            }
            for (int index = 0; index < staged.Count; index++)
            {
                bool completed = false;
                try
                {
                    completed = AdvanceNativeCleanup(staged[index]).Released;
                }
                catch
                {
                    completed = false;
                }
                if (completed)
                {
                    lock (_gate)
                    {
                        _pendingStagedCleanup.Remove(staged[index]);
                    }
                }
            }
            for (int index = 0; index < bundles.Count; index++)
            {
                bool completed = false;
                try
                {
                    completed = bundles[index].Advance();
                }
                catch
                {
                    completed = false;
                }
                if (completed)
                {
                    lock (_gate)
                    {
                        _pendingBundleCleanup.Remove(bundles[index]);
                    }
                }
            }
            AdvanceGlobalUnloadBatch();
        }

        internal bool HasPendingCleanup
        {
            get
            {
                lock (_gate)
                {
                    return _pendingStagedCleanup.Count != 0
                        || _pendingBundleCleanup.Count != 0
                        || _globalUnloadBatch.HasPending
                        || _globalUnloadOperation != null;
                }
            }
        }

        private AssetStreamReleaseResult AdvanceNativeCleanup(
            AssetStreamUnityCommitted committed)
        {
            if (committed.Released)
            {
                return new AssetStreamReleaseResult(
                    true,
                    false,
                    "native cleanup already completed");
            }
            if (!committed.CleanupStarted)
            {
                // Keep the proof adjacent to Unregister/Destroy: no callback
                // or later frame can slip a bundle-owned mask into a foreign
                // central Material after the registry identity disappears.
                AssetStreamLoaderSnapshot current =
                    _surface.Read(committed.Loader);
                if (HasCentralOwnedReferences(current, committed))
                {
                    return new AssetStreamReleaseResult(
                        false,
                        false,
                        "central loader still references an owned object or page mask");
                }
                _routes.Unregister(committed.Ownership);
                DestroyOwnedObjects(committed);
                committed.CleanupStarted = true;
            }

            // Retain the wrapper until Unload succeeds. Losing it on an
            // exception would make a later retry falsely report success.
            if (committed.Bundle != null)
            {
                AssetStreamPinnedBundle pinned = UnloadBoundBundle(
                    committed.Bundle);
                committed.Bundle = null;
                pinned.Dispose();
            }
            if (!committed.ManagedTextureReferencesCleared)
            {
                committed.ClearManagedTextureReferences();
            }
            if (!committed.GlobalUnloadCompleted)
            {
                _globalUnloadBatch.Enqueue(committed);
                return new AssetStreamReleaseResult(
                    false,
                    true,
                    true,
                    "waiting for batched Resources.UnloadUnusedAssets completion");
            }
            committed.ClearOwnedObjectReferences();
            committed.TryMarkReleased();
            committed.CleanupCompletion.Complete();
            lock (_gate)
            {
                PublishedGroupRecord record;
                if (_published.TryGetValue(
                        committed.Ownership.GroupId,
                        out record)
                    && ReferenceEquals(record.Committed, committed))
                {
                    _published.Remove(committed.Ownership.GroupId);
                }
                _batchRestoreResults.Remove(committed.Ownership);
                _batchReleaseSafety.Remove(committed.Ownership);
            }
            return new AssetStreamReleaseResult(
                true,
                false,
                "AssetBundle and unused assets completed after delayed detach");
        }

        private void RetainPendingStagedCleanup(
            AssetStreamUnityCommitted staged)
        {
            lock (_gate)
            {
                if (!_pendingStagedCleanup.Contains(staged))
                {
                    _pendingStagedCleanup.Add(staged);
                }
            }
        }

        private bool ScheduleDetachedBundleCleanup(
            AssetBundle bundle,
            AssetStreamPinnedBundle pinned,
            AssetStreamCleanupCompletion completion)
        {
            var cleanup = new DetachedBundleCleanup(
                this,
                bundle,
                pinned,
                completion);
            bool complete = false;
            try
            {
                complete = cleanup.Advance();
                return complete;
            }
            finally
            {
                if (!complete)
                {
                    lock (_gate)
                    {
                        _pendingBundleCleanup.Add(cleanup);
                    }
                }
            }
        }

        /// <summary>
        /// Starts at most one process-global Unity resource scan for every
        /// cleanup wave. AdvancePendingCleanup runs before the controller's
        /// release loop, so every group detached in one LateUpdate joins the
        /// same scan on the next LateUpdate.
        /// </summary>
        private void AdvanceGlobalUnloadBatch()
        {
            if (_globalUnloadOperation != null)
            {
                if (!_globalUnloadOperation.isDone)
                {
                    return;
                }
                _globalUnloadOperation = null;
                IList<IAssetStreamGlobalUnloadParticipant> completed =
                    _globalUnloadBatch.Complete();
                for (int index = 0; index < completed.Count; index++)
                {
                    completed[index].GlobalUnloadCompleted = true;
                }
            }

            IList<IAssetStreamGlobalUnloadParticipant> participants;
            if (!_globalUnloadBatch.TryBegin(out participants))
            {
                return;
            }
            try
            {
                _globalUnloadOperation = Resources.UnloadUnusedAssets();
                if (_globalUnloadOperation == null)
                {
                    throw new InvalidOperationException(
                        "Resources.UnloadUnusedAssets returned no operation");
                }
            }
            catch
            {
                _globalUnloadOperation = null;
                _globalUnloadBatch.AbortStart();
                throw;
            }
        }

        private AssetStreamUnityCommitted Stage(
            AssetStreamGroupManifest group,
            AssetStreamUnityBaseline baseline,
            AssetStreamOwnershipToken ownership,
            AssetBundle bundle,
            AssetStreamCleanupCompletion cleanupCompletion)
        {
            TextAsset text = bundle.LoadAsset<TextAsset>(group.AtlasAddress);
            if (text == null)
            {
                throw Permanent("Bundle has no exact atlas.v2 TextAsset address");
            }
            string expectedAtlasName = Path.GetFileNameWithoutExtension(
                group.AtlasAssetPath);
            if (!string.Equals(text.name, expectedAtlasName, StringComparison.Ordinal))
            {
                throw Permanent("atlas.v2 TextAsset object name is not exact");
            }
            AssetStreamAtlasManifest atlas;
            byte[] atlasBytes = null;
            try
            {
                atlasBytes = text.bytes;
                if (atlasBytes == null)
                {
                    throw Permanent("atlas.v2 TextAsset returned no raw bytes");
                }
                atlas = group.PipelineVersion
                    == AssetStreamPipelineVersion.Bc7VisualEquivalenceV2
                        ? AssetStreamManifestParser.ParseAtlasV3(atlasBytes, group)
                        : AssetStreamManifestParser.ParseAtlasV2(atlasBytes, group);
            }
            finally
            {
                // The index charge intentionally covers resident RGBA pages,
                // not a process-lifetime copy of atlas.v2. The second resource
                // probe sees this byte[] while staging; release the bundle
                // TextAsset before any group can be published.
                atlasBytes = null;
                Resources.UnloadAsset(text);
            }
            bool foliage = _foliageGroups.Contains(group.Group)
                || IsFoliage(baseline.FrozenGroupMaterials);
            if (foliage && atlas.Pages.Count > 1)
            {
                throw Permanent(
                    "Multi-page foliage is unsupported and was rejected before publication");
            }
            if (foliage && atlas.MaskPolicy != AssetStreamMaskPolicy.Required)
            {
                throw Permanent("Foliage requires a one-page mask binding");
            }
            if (foliage
                && !string.Equals(
                    atlas.MaterialBinding,
                    AssetStreamMaterialBindingContract.GroupMaskSinglePage,
                    StringComparison.Ordinal))
            {
                throw Permanent(
                    "Foliage requires the single-page group material route");
            }

            var pages = new AssetStreamUnityPage[atlas.Pages.Count];
            var createdMaterials = new List<Material>();
            var loadedTextures = new HashSet<Texture2D>(
                AssetStreamReferenceComparer<Texture2D>.Instance);
            try
            {
                for (int index = 0; index < atlas.Pages.Count; index++)
                {
                    AssetStreamAtlasPage page = atlas.Pages[index];
                    Texture2D main = LoadTexture(
                        bundle,
                        page.Main,
                        page,
                        atlas.MainTextureContract);
                    Texture2D mask = page.Mask == null
                        ? null
                        : LoadTexture(
                            bundle,
                            page.Mask,
                            page,
                            atlas.MaskTextureContract);
                    if (!loadedTextures.Add(main)
                        || (mask != null && !loadedTextures.Add(mask)))
                    {
                        throw Permanent(
                            "Distinct atlas addresses resolved to one Texture2D object");
                    }
                    Material[] materials = CreatePageMaterials(
                        group,
                        baseline,
                        page,
                        mask,
                        foliage,
                        createdMaterials);
                    pages[index] = new AssetStreamUnityPage(
                        page.Id,
                        main,
                        mask,
                        materials);
                }

                Sprite[] mainSprites = CloneExactBaselineSprites(
                    baseline.FrozenGroupSprites,
                    group.ArraySize,
                    "gmSprites");
                Sprite[] altSprites = CloneExactBaselineSprites(
                    baseline.FrozenGroupAltSprites,
                    group.ArraySize,
                    "gmAltSprites");
                var sprites = new List<Sprite>(atlas.Frames.Count);
                try
                {
                    for (int index = 0; index < atlas.Frames.Count; index++)
                    {
                        AssetStreamAtlasFrame frame = atlas.Frames[index];
                        Sprite sprite = Sprite.Create(
                            pages[frame.Page].Main,
                            new Rect(
                                frame.Rect.X,
                                frame.Rect.Y,
                                frame.Rect.Width,
                                frame.Rect.Height),
                            new Vector2(
                                (float)frame.Pivot.X,
                                (float)frame.Pivot.Y),
                            (float)frame.PixelsPerUnit,
                            0,
                            SpriteMeshType.FullRect,
                            Vector4.zero,
                            false);
                        if (sprite == null)
                        {
                            throw Permanent("Sprite.Create returned null");
                        }
                        sprite.name = frame.Name;
                        sprites.Add(sprite);
                        if (frame.Alt)
                        {
                            altSprites[frame.Index] = sprite;
                        }
                        else
                        {
                            mainSprites[frame.Index] = sprite;
                        }
                    }
                    // Only the reviewed Body groups use an owned-Sprite
                    // postfix to select per-page materials. Every other masked
                    // renderer path is contractually one-page and receives its
                    // page-0 material through gmMaterials.
                    Material[] published = string.Equals(
                        group.MaterialBinding,
                        AssetStreamMaterialBindingContract.GroupMaskSinglePage,
                        StringComparison.Ordinal)
                            ? pages[0].Materials
                            : baseline.GroupMaterials;
                    Dictionary<string, AssetStreamOriginalSpriteEntry> originals =
                        CaptureOriginalSpriteEntries(
                            baseline.FrozenAllSprites,
                            atlas);
                    var staged = new AssetStreamUnityCommitted(
                        ownership,
                        baseline.Loader,
                        bundle,
                        atlas,
                        pages,
                        mainSprites,
                        altSprites,
                        published,
                        originals,
                        sprites,
                        createdMaterials,
                        cleanupCompletion);
                    PreparePublication(group, baseline, staged);
                    return staged;
                }
                catch
                {
                    for (int index = 0; index < sprites.Count; index++)
                    {
                        Destroy(sprites[index]);
                    }
                    throw;
                }
            }
            catch
            {
                for (int index = 0; index < createdMaterials.Count; index++)
                {
                    Destroy(createdMaterials[index]);
                }
                throw;
            }
        }

        private static Texture2D LoadTexture(
            AssetBundle bundle,
            AssetStreamPageTexture plane,
            AssetStreamAtlasPage page,
            AssetStreamTextureContract contract)
        {
            if (plane == null) throw new ArgumentNullException("plane");
            if (contract == null) throw new ArgumentNullException("contract");
            TextureFormat expectedFormat;
            if (string.Equals(contract.Format, "BC7", StringComparison.Ordinal))
            {
                expectedFormat = TextureFormat.BC7;
            }
            else if (string.Equals(contract.Format, "RGBA32", StringComparison.Ordinal))
            {
                expectedFormat = TextureFormat.RGBA32;
            }
            else
            {
                throw Permanent("Unsupported runtime Texture2D format contract");
            }
            FilterMode expectedFilter;
            if (string.Equals(contract.FilterMode, "Point", StringComparison.Ordinal))
            {
                expectedFilter = FilterMode.Point;
            }
            else if (string.Equals(contract.FilterMode, "Bilinear", StringComparison.Ordinal))
            {
                expectedFilter = FilterMode.Bilinear;
            }
            else
            {
                throw Permanent("Unsupported runtime Texture2D filter contract");
            }
            Texture2D texture = bundle.LoadAsset<Texture2D>(plane.Address);
            if (texture == null
                || texture.width != page.Width
                || texture.height != page.Height
                || texture.format != expectedFormat
                || texture.isDataSRGB != contract.SRgb
                || texture.mipmapCount != 1
                || texture.isReadable != contract.Readable
                || texture.filterMode != expectedFilter
                || texture.wrapMode != TextureWrapMode.Clamp
                || texture.anisoLevel != contract.AnisoLevel
                || !string.Equals(
                    texture.name,
                    Path.GetFileNameWithoutExtension(plane.AssetPath),
                    StringComparison.Ordinal))
            {
                throw Permanent(
                    "Texture2D runtime contract mismatch at " + plane.Address);
            }
            return texture;
        }

        private static Material[] CreatePageMaterials(
            AssetStreamGroupManifest group,
            AssetStreamUnityBaseline baseline,
            AssetStreamAtlasPage page,
            Texture2D mask,
            bool foliage,
            IList<Material> owned)
        {
            if (group.MaskPolicy == AssetStreamMaskPolicy.Forbidden)
            {
                if (mask != null
                    || !string.Equals(
                        group.MaterialBinding,
                        AssetStreamMaterialBindingContract.PlainShared,
                        StringComparison.Ordinal)
                    || !baseline.UsesPlainMaterials)
                {
                    throw Permanent("Plain material binding does not match baseline");
                }
                return null;
            }
            bool bodyRoute = string.Equals(
                group.MaterialBinding,
                AssetStreamMaterialBindingContract.SetBodySpritePageMask,
                StringComparison.Ordinal);
            bool groupRoute = string.Equals(
                group.MaterialBinding,
                AssetStreamMaterialBindingContract.GroupMaskSinglePage,
                StringComparison.Ordinal);
            if (mask == null
                || (!bodyRoute && !groupRoute)
                || baseline.FrozenGroupMaterials == null
                || baseline.FrozenGroupMaterials.Length != MaterialSlotCount
                || baseline.UsesPlainMaterials)
            {
                throw Permanent("Page-mask material binding does not match baseline");
            }
            if (groupRoute && (group.PageCount != 1 || page.Id != 0))
            {
                throw Permanent(
                    "Single-page group material binding received another page");
            }
            if (foliage && !groupRoute)
            {
                throw Permanent(
                    "Foliage cannot use the SetBodySprite page route");
            }

            if (foliage)
            {
                var foliageResult = new Material[MaterialSlotCount];
                Shader shader = Shader.Find(FoliageShader);
                if (shader == null)
                {
                    throw Permanent("Pinned foliage shader is unavailable");
                }
                Material foliageMaterial = new Material(shader);
                foliageMaterial.name = "StrongholdEuropeDE.AssetStream."
                    + group.Slug + ".foliage";
                if (!foliageMaterial.HasProperty(TeamMaskProperty))
                {
                    Destroy(foliageMaterial);
                    throw Permanent("Pinned foliage shader has no team-mask property");
                }
                foliageMaterial.SetTexture(TeamMaskProperty, mask);
                owned.Add(foliageMaterial);
                for (int slot = 0; slot < foliageResult.Length; slot++)
                {
                    foliageResult[slot] = foliageMaterial;
                }
                return foliageResult;
            }
            Material[] result = bodyRoute
                ? null
                : new Material[MaterialSlotCount];
            for (int slot = 0; slot < MaterialSlotCount; slot++)
            {
                Material source = baseline.FrozenGroupMaterials[slot];
                string shaderName = source == null || source.shader == null
                    ? null
                    : source.shader.name;
                string expectedShader = foliage ? FoliageShader : TeamColourShader;
                if (source == null
                    || !string.Equals(shaderName, expectedShader, StringComparison.Ordinal)
                    || !source.HasProperty(TeamMaskProperty))
                {
                    throw Permanent(
                        "Baseline material shader/mask surface is not exact");
                }
                if (bodyRoute)
                {
                    // Body renderers already receive the current vanilla or
                    // extender material before our postfix. Their page mask is
                    // a MaterialPropertyBlock override, so cloning seven
                    // baseline materials per atlas page would only waste native
                    // resources and would reintroduce material-identity drift.
                    continue;
                }
                Material material = new Material(source);
                material.name = "StrongholdEuropeDE.AssetStream."
                    + group.Slug + ".page"
                    + page.Id.ToString("D3", CultureInfo.InvariantCulture)
                    + ".slot" + slot.ToString(CultureInfo.InvariantCulture);
                material.SetTexture(TeamMaskProperty, mask);
                if (material.HasProperty(SpriteCutoffProperty))
                {
                    float cutoff = slot <= 0 ? 0f : (slot + 4f) / 20f;
                    material.SetFloat(SpriteCutoffProperty, cutoff);
                }
                result[slot] = material;
                owned.Add(material);
            }
            return result;
        }

        private static bool IsFoliage(Material[] materials)
        {
            if (materials == null)
            {
                return false;
            }
            for (int index = 0; index < materials.Length; index++)
            {
                Material material = materials[index];
                if (material != null && material.shader != null
                    && string.Equals(
                        material.shader.name,
                        FoliageShader,
                        StringComparison.Ordinal))
                {
                    return true;
                }
            }
            return false;
        }

        private static Sprite[] CloneExactBaselineSprites(
            Sprite[] baseline,
            int expectedLength,
            string field)
        {
            if (baseline == null || baseline.Length != expectedLength)
            {
                throw Permanent(
                    "Baseline " + field + " group length does not match array_size");
            }
            return (Sprite[])baseline.Clone();
        }

        private static void ValidateBaseline(
            AssetStreamGroupManifest group,
            AssetStreamUnityBaseline baseline)
        {
            if (baseline == null)
            {
                throw Permanent("No post-extender baseline was captured");
            }
            if (group.ArraySize < 1
                || baseline.GroupSprites == null
                || baseline.GroupSprites.Length != group.ArraySize
                || baseline.GroupAltSprites == null
                || baseline.GroupAltSprites.Length != group.ArraySize
                || baseline.GroupMaterials == null
                || baseline.GroupMaterials.Length != MaterialSlotCount
                || baseline.GroupColors == null
                || baseline.FrozenGroupSprites == null
                || baseline.FrozenGroupSprites.Length != group.ArraySize
                || baseline.FrozenGroupAltSprites == null
                || baseline.FrozenGroupAltSprites.Length != group.ArraySize
                || baseline.FrozenGroupMaterials == null
                || baseline.FrozenGroupMaterials.Length != MaterialSlotCount
                || baseline.FrozenGroupColors == null)
            {
                throw Permanent("Post-extender group baseline shape is not exact");
            }
        }

        private static void ValidatePublishOwnership(
            AssetStreamGroupManifest group,
            AssetStreamUnityBaseline baseline,
            AssetStreamLoaderSnapshot current,
            AssetStreamUnityCommitted staged)
        {
            AssetStreamSpriteLoaderSurface.RequireGroupIndex(current, group.GmId);
            if (!ReferenceEquals(current.GmSprites[group.GmId], baseline.GroupSprites)
                || !ReferenceEquals(
                    current.GmAltSprites[group.GmId], baseline.GroupAltSprites)
                || !ReferenceEquals(
                    current.GmMaterials[group.GmId], baseline.GroupMaterials)
                || !ReferenceEquals(current.GmColors[group.GmId], baseline.GroupColors))
            {
                throw Permanent(
                    "A foreign owner changed the target GM after baseline capture");
            }
            if (!SameReferences(
                    current.GmSprites[group.GmId],
                    baseline.FrozenGroupSprites)
                || !SameReferences(
                    current.GmAltSprites[group.GmId],
                    baseline.FrozenGroupAltSprites)
                || !SameReferences(
                    current.GmMaterials[group.GmId],
                    baseline.FrozenGroupMaterials)
                || !SameValues(
                    current.GmColors[group.GmId],
                    baseline.FrozenGroupColors))
            {
                throw Permanent(
                    "A foreign owner changed target GM contents after baseline capture");
            }
            for (int index = 0; index < staged.Atlas.Frames.Count; index++)
            {
                string name = staged.Atlas.Frames[index].Name;
                AssetStreamOriginalSpriteEntry original;
                Sprite now;
                bool captured = staged.OriginalSprites.TryGetValue(
                    name,
                    out original);
                bool hasNow = current.AllSprites.TryGetValue(name, out now);
                if (!captured
                    || original.Existed != hasNow
                    || (original.Existed
                        && !ReferenceEquals(original.Value, now)))
                {
                    throw Permanent(
                        "A foreign owner changed a target allSprites key");
                }
            }
        }

        private static AssetStreamLoaderSnapshot CloneCentral(
            AssetStreamLoaderSnapshot current)
        {
            return new AssetStreamLoaderSnapshot(
                new Dictionary<string, Sprite>(
                    current.AllSprites,
                    current.AllSprites.Comparer),
                (Sprite[][])current.GmSprites.Clone(),
                (Sprite[][])current.GmAltSprites.Clone(),
                (Material[][])current.GmMaterials.Clone(),
                (Color[][])current.GmColors.Clone());
        }

        private static Dictionary<string, AssetStreamOriginalSpriteEntry>
            CaptureOriginalSpriteEntries(
                IDictionary<string, Sprite> baseline,
                AssetStreamAtlasManifest atlas)
        {
            var result = new Dictionary<string, AssetStreamOriginalSpriteEntry>(
                atlas.Frames.Count,
                StringComparer.Ordinal);
            for (int index = 0; index < atlas.Frames.Count; index++)
            {
                string name = atlas.Frames[index].Name;
                Sprite value;
                bool existed = baseline.TryGetValue(name, out value);
                result.Add(
                    name,
                    new AssetStreamOriginalSpriteEntry(existed, value));
            }
            return result;
        }

        private static bool SameReferences<T>(T[] current, T[] frozen)
            where T : class
        {
            if (current == null || frozen == null || current.Length != frozen.Length)
            {
                return false;
            }
            for (int index = 0; index < current.Length; index++)
            {
                if (!ReferenceEquals(current[index], frozen[index]))
                {
                    return false;
                }
            }
            return true;
        }

        private static bool SameValues(Color[] current, Color[] frozen)
        {
            if (current == null || frozen == null || current.Length != frozen.Length)
            {
                return false;
            }
            for (int index = 0; index < current.Length; index++)
            {
                if (!current[index].Equals(frozen[index]))
                {
                    return false;
                }
            }
            return true;
        }

        private void PreparePublication(
            AssetStreamGroupManifest group,
            AssetStreamUnityBaseline baseline,
            AssetStreamUnityCommitted staged)
        {
            AssetStreamLoaderSnapshot current = _surface.Read(staged.Loader);
            ValidatePublishOwnership(group, baseline, current, staged);
            AssetStreamLoaderSnapshot replacement = CloneCentral(current);
            replacement.GmSprites[group.GmId] = staged.MainSprites;
            replacement.GmAltSprites[group.GmId] = staged.AltSprites;
            replacement.GmMaterials[group.GmId] = staged.PublishedGroupMaterials;
            for (int index = 0; index < staged.Atlas.Frames.Count; index++)
            {
                replacement.AllSprites[staged.Atlas.Frames[index].Name] =
                    staged.CreatedSprites[index];
            }
            staged.PublishExpected = new AssetStreamLoaderGenerationSnapshot(
                current);
            staged.PublishReplacement = replacement;
        }

        private void WriteWithRollback(
            spriteLoader loader,
            AssetStreamLoaderSnapshot original,
            AssetStreamLoaderSnapshot replacement)
        {
            try
            {
                _surface.Write(loader, replacement);
            }
            catch (Exception writeFailure)
            {
                try
                {
                    _surface.Write(loader, original);
                }
                catch (Exception rollbackFailure)
                {
                    throw new AggregateException(writeFailure, rollbackFailure);
                }
                throw;
            }
        }

        private bool HasCentralOwnedReferences(
            AssetStreamLoaderSnapshot current,
            AssetStreamUnityCommitted committed)
        {
            foreach (Sprite sprite in current.AllSprites.Values)
            {
                if (committed.CreatedSpriteSet.Contains(sprite)) return true;
            }
            if (ContainsAny(current.GmSprites, committed.CreatedSpriteSet)
                || ContainsAny(current.GmAltSprites, committed.CreatedSpriteSet))
            {
                return true;
            }
            for (int outer = 0; outer < current.GmMaterials.Length; outer++)
            {
                Material[] inner = current.GmMaterials[outer];
                if (inner == null) continue;
                for (int index = 0; index < inner.Length; index++)
                {
                    if (committed.CreatedMaterialSet.Contains(inner[index])) return true;
                }
            }
            var maskOwners = new HashSet<AssetStreamOwnershipToken>();
            AssetStreamCentralMaterialMaskAudit.MarkOwners(
                current.GmMaterials,
                ReadTeamMask,
                _routes.MarkOwnersOfMask,
                maskOwners);
            return maskOwners.Contains(committed.Ownership);
        }

        private static bool ContainsAny(
            Sprite[][] outer,
            HashSet<Sprite> owned)
        {
            for (int first = 0; first < outer.Length; first++)
            {
                Sprite[] inner = outer[first];
                if (inner == null) continue;
                for (int second = 0; second < inner.Length; second++)
                {
                    if (owned.Contains(inner[second])) return true;
                }
            }
            return false;
        }

        private static bool OwnsSprite(
            AssetStreamUnityCommitted committed,
            Sprite candidate)
        {
            return committed.CreatedSpriteSet.Contains(candidate);
        }

        private static void DestroyOwnedObjects(AssetStreamUnityCommitted committed)
        {
            for (int index = 0; index < committed.CreatedSprites.Count; index++)
            {
                Destroy(committed.CreatedSprites[index]);
            }
            for (int index = 0; index < committed.CreatedMaterials.Count; index++)
            {
                Destroy(committed.CreatedMaterials[index]);
            }
        }

        private static void Destroy(UnityObject value)
        {
            if (!ReferenceEquals(value, null) && value != null)
            {
                UnityObject.Destroy(value);
            }
        }

        private AssetStreamPinnedBundle TakeVerified(string group)
        {
            lock (_gate)
            {
                AssetStreamPinnedBundle pinned;
                if (!_verified.TryGetValue(group, out pinned))
                {
                    throw new InvalidOperationException(
                        "Bundle transaction began without verified file ownership");
                }
                _verified.Remove(group);
                return pinned;
            }
        }

        private void BindBundleStream(
            AssetBundle bundle,
            AssetStreamPinnedBundle pinned)
        {
            if (bundle == null) throw new ArgumentNullException("bundle");
            if (pinned == null) throw new ArgumentNullException("pinned");
            lock (_gate)
            {
                if (_bundleStreams.ContainsKey(bundle))
                {
                    throw new InvalidOperationException(
                        "AssetBundle already owns a verified stream handle");
                }
                _bundleStreams.Add(bundle, pinned);
            }
        }

        private AssetStreamPinnedBundle TakeBundleStream(AssetBundle bundle)
        {
            lock (_gate)
            {
                AssetStreamPinnedBundle pinned;
                if (!_bundleStreams.TryGetValue(bundle, out pinned))
                {
                    throw new InvalidOperationException(
                        "AssetBundle has no verified stream handle");
                }
                _bundleStreams.Remove(bundle);
                return pinned;
            }
        }

        private AssetStreamPinnedBundle UnloadBoundBundle(AssetBundle bundle)
        {
            AssetStreamPinnedBundle pinned;
            lock (_gate)
            {
                if (!_bundleStreams.TryGetValue(bundle, out pinned))
                {
                    throw new InvalidOperationException(
                        "AssetBundle lost its verified stream handle");
                }
            }
            bundle.Unload(false);
            lock (_gate)
            {
                AssetStreamPinnedBundle current;
                if (!_bundleStreams.TryGetValue(bundle, out current)
                    || !ReferenceEquals(current, pinned))
                {
                    throw new InvalidOperationException(
                        "AssetBundle stream ownership changed during unload");
                }
                _bundleStreams.Remove(bundle);
            }
            return pinned;
        }

        private static AssetStreamLoadException Permanent(string message)
        {
            return new AssetStreamLoadException(message, true);
        }

        private static string Describe(Exception exception)
        {
            return AssetStreamText.Sanitize(
                exception.GetType().Name + ": " + exception.Message,
                220);
        }

        private sealed class PublishedGroupRecord
        {
            internal PublishedGroupRecord(
                AssetStreamGroupManifest manifest,
                AssetStreamBaseline<AssetStreamUnityBaseline> baseline,
                AssetStreamUnityCommitted committed)
            {
                Manifest = manifest;
                Baseline = baseline;
                Committed = committed;
            }

            internal AssetStreamGroupManifest Manifest { get; private set; }
            internal AssetStreamBaseline<AssetStreamUnityBaseline> Baseline
            {
                get;
                private set;
            }
            internal AssetStreamUnityCommitted Committed { get; private set; }
            internal bool Detached { get; set; }
        }

        private sealed class DetachedBundleCleanup
            : IAssetStreamGlobalUnloadParticipant
        {
            private readonly UnityAssetStreamGroupBackend _owner;
            private AssetBundle _bundle;
            private AssetStreamPinnedBundle _pinned;
            private readonly AssetStreamCleanupCompletion _completion;

            internal DetachedBundleCleanup(
                UnityAssetStreamGroupBackend owner,
                AssetBundle bundle,
                AssetStreamPinnedBundle pinned,
                AssetStreamCleanupCompletion completion)
            {
                _owner = owner ?? throw new ArgumentNullException("owner");
                _bundle = bundle ?? throw new ArgumentNullException("bundle");
                _pinned = pinned ?? throw new ArgumentNullException("pinned");
                _completion = completion
                    ?? throw new ArgumentNullException("completion");
            }

            public bool GlobalUnloadCompleted { get; set; }

            internal bool Advance()
            {
                if (_bundle != null)
                {
                    _bundle.Unload(false);
                    _bundle = null;
                }
                if (_pinned != null)
                {
                    _pinned.Dispose();
                    _pinned = null;
                }
                if (!GlobalUnloadCompleted)
                {
                    _owner._globalUnloadBatch.Enqueue(this);
                    return false;
                }
                _completion.Complete();
                return true;
            }
        }

        private sealed class AssetStreamUnityTransaction
            : IAssetStreamGroupTransaction<AssetStreamUnityCommitted>
        {
            private readonly UnityAssetStreamGroupBackend _owner;
            private readonly AssetStreamGroupManifest _group;
            private readonly AssetStreamBaseline<AssetStreamUnityBaseline> _baseline;
            private AssetStreamUnityCommitted _staged;
            private bool _committed;
            private bool _aborted;

            internal AssetStreamUnityTransaction(
                UnityAssetStreamGroupBackend owner,
                AssetStreamGroupManifest group,
                AssetStreamBaseline<AssetStreamUnityBaseline> baseline,
                AssetStreamUnityCommitted staged)
            {
                _owner = owner;
                _group = group;
                _baseline = baseline;
                _staged = staged;
            }

            public AssetStreamUnityCommitted Commit()
            {
                if (_committed || _aborted || _staged == null)
                {
                    throw new InvalidOperationException(
                        "Asset-stream transaction is no longer commit-capable");
                }
                AssetStreamUnityCommitted value = _owner.Publish(
                    _group,
                    _baseline,
                    _staged);
                _committed = true;
                return value;
            }

            public void Abort()
            {
                if (_aborted)
                {
                    return;
                }
                if (_committed)
                {
                    throw new InvalidOperationException(
                        "A committed asset-stream transaction cannot be aborted");
                }
                _owner.AbortStaged(_staged);
                _staged = null;
                _aborted = true;
            }

            public void Dispose()
            {
                if (!_committed && !_aborted && _staged != null)
                {
                    Abort();
                }
            }
        }
    }
}
