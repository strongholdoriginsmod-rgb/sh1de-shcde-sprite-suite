using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed class UiTextureCompiledContract
    {
        internal const string ManifestRelativePath = "Runtime/ui-textures-v2.tsv";
        internal const long MaximumManifestBytes = 4L * 1024L * 1024L;
        internal const int MaximumEntryCount = 512;

        internal UiTextureCompiledContract(
            bool enabled,
            string manifestSha256,
            long manifestSize,
            int entryCount)
        {
            if (!enabled)
            {
                if (!string.IsNullOrEmpty(manifestSha256)
                    || manifestSize != 0
                    || entryCount != 0)
                {
                    throw new ArgumentException(
                        "A disabled UI texture contract must be empty");
                }
            }
            else
            {
                UiTextureContractRules.RequireSha256(
                    manifestSha256,
                    "manifestSha256");
                if (manifestSize < 1 || manifestSize > MaximumManifestBytes)
                {
                    throw new ArgumentOutOfRangeException("manifestSize");
                }
                if (entryCount < 1 || entryCount > MaximumEntryCount)
                {
                    throw new ArgumentOutOfRangeException("entryCount");
                }
            }

            Enabled = enabled;
            ManifestSha256 = manifestSha256 ?? string.Empty;
            ManifestSize = manifestSize;
            EntryCount = entryCount;
        }

        internal bool Enabled { get; private set; }
        internal string ManifestSha256 { get; private set; }
        internal long ManifestSize { get; private set; }
        internal int EntryCount { get; private set; }
    }

    internal sealed class UiTextureContractException : Exception
    {
        internal UiTextureContractException(string message)
            : base(message)
        {
        }

        internal UiTextureContractException(string message, Exception innerException)
            : base(message, innerException)
        {
        }
    }

    internal enum UiTextureSamplingMode
    {
        Point = 0,
        Bilinear = 1,
    }

    internal sealed class UiTextureManifestProvenance
    {
        internal UiTextureManifestProvenance(
            string sourceManifestSha256,
            string sourceEntrySetSha256,
            string qualityPolicySha256,
            string editorSourceSha256)
        {
            UiTextureContractRules.RequireSha256(
                sourceManifestSha256,
                "source_manifest_sha256");
            UiTextureContractRules.RequireSha256(
                sourceEntrySetSha256,
                "source_entry_set_sha256");
            UiTextureContractRules.RequireSha256(
                qualityPolicySha256,
                "quality_policy_sha256");
            UiTextureContractRules.RequireSha256(
                editorSourceSha256,
                "editor_source_sha256");
            SourceManifestSha256 = sourceManifestSha256;
            SourceEntrySetSha256 = sourceEntrySetSha256;
            QualityPolicySha256 = qualityPolicySha256;
            EditorSourceSha256 = editorSourceSha256;
        }

        internal string SourceManifestSha256 { get; private set; }
        internal string SourceEntrySetSha256 { get; private set; }
        internal string QualityPolicySha256 { get; private set; }
        internal string EditorSourceSha256 { get; private set; }
    }

    internal sealed class UiTextureBundleManifestEntry
    {
        internal const long MaximumBundleBytes = 512L * 1024L * 1024L;

        internal UiTextureBundleManifestEntry(
            string pluginRoot,
            string id,
            string pluginRelativePath,
            string sha256,
            long sizeBytes,
            string crc32,
            string unityHash128)
        {
            PluginRoot = UiTexturePath.CanonicalizePluginRoot(pluginRoot);
            Id = UiTextureContractRules.RequireIdentifier(id, "bundle id");
            PluginRelativePath = UiTexturePath.RequireCanonicalRelativePath(
                pluginRelativePath,
                "bundle plugin_relative_path");
            if (!PluginRelativePath.StartsWith(
                    "Runtime/UiAssetBundles/win64/",
                    StringComparison.Ordinal))
            {
                throw new UiTextureContractException(
                    "bundle plugin_relative_path must be below Runtime/UiAssetBundles/win64/");
            }
            UiTextureContractRules.RequireSha256(sha256, "bundle sha256");
            if (sizeBytes < 1 || sizeBytes > MaximumBundleBytes)
            {
                throw new UiTextureContractException(
                    "bundle size_bytes is outside the exact per-bundle range");
            }
            UiTextureContractRules.RequireLowerHex(crc32, 8, "bundle crc32");
            UiTextureContractRules.RequireLowerHex(
                unityHash128,
                32,
                "bundle unity_hash128");

            Sha256 = sha256;
            SizeBytes = sizeBytes;
            Crc32 = crc32;
            UnityHash128 = unityHash128;
            AbsolutePath = UiTexturePath.CombineOwned(
                PluginRoot,
                PluginRelativePath);
        }

        internal string PluginRoot { get; private set; }
        internal string Id { get; private set; }
        internal string PluginRelativePath { get; private set; }
        internal string AbsolutePath { get; private set; }
        internal string Sha256 { get; private set; }
        internal long SizeBytes { get; private set; }
        internal string Crc32 { get; private set; }
        internal string UnityHash128 { get; private set; }
    }

    internal sealed class UiTextureManifestEntry
    {
        internal const int MaximumDimension = 8192;
        internal const string PointContractId =
            "ui-bc7-point-premultiplied-v1";
        internal const string BilinearContractId =
            "ui-bc7-bilinear-premultiplied-v1";

        internal UiTextureManifestEntry(
            string pluginRoot,
            string noesisPath,
            string virtualRelativePath,
            string bundleId,
            string address,
            string sourcePngSha256,
            string premultipliedRgbaSha256,
            int logicalWidth,
            int logicalHeight,
            int storageWidth,
            int storageHeight,
            long gpuBytes,
            long residentChargeBytes,
            long transientPeakBytes,
            string textureContractId,
            string bcBlockPadding,
            UiTextureBundleManifestEntry bundle)
        {
            PluginRoot = UiTexturePath.CanonicalizePluginRoot(pluginRoot);
            NoesisPath = UiTexturePath.RequireCanonicalNoesisPath(
                noesisPath,
                "noesis_path");
            VirtualRelativePath = UiTexturePath.RequireCanonicalRelativePngPath(
                virtualRelativePath,
                "virtual_relative_path");
            if (!VirtualRelativePath.StartsWith(
                    "Runtime/UiTextures/virtual/",
                    StringComparison.Ordinal))
            {
                throw new UiTextureContractException(
                    "virtual_relative_path must be below Runtime/UiTextures/virtual/");
            }
            BundleId = UiTextureContractRules.RequireIdentifier(
                bundleId,
                "texture bundle_id");
            if (bundle == null
                || !string.Equals(bundle.Id, BundleId, StringComparison.Ordinal)
                || !string.Equals(
                    bundle.PluginRoot,
                    PluginRoot,
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new UiTextureContractException(
                    "texture bundle_id does not resolve inside this manifest");
            }
            if (string.IsNullOrEmpty(address)
                || address.Length > 256
                || !address.IsNormalized(NormalizationForm.FormC)
                || address.IndexOf('\t') >= 0
                || address.IndexOf('\r') >= 0
                || address.IndexOf('\n') >= 0)
            {
                throw new UiTextureContractException(
                    "texture address is empty, non-NFC, or contains controls");
            }
            UiTextureContractRules.RequireSha256(
                sourcePngSha256,
                "source_png_sha256");
            UiTextureContractRules.RequireSha256(
                premultipliedRgbaSha256,
                "premultiplied_rgba_sha256");
            if (logicalWidth < 1 || logicalWidth > MaximumDimension
                || logicalHeight < 1 || logicalHeight > MaximumDimension
                || storageWidth < 1 || storageWidth > MaximumDimension
                || storageHeight < 1 || storageHeight > MaximumDimension)
            {
                throw new UiTextureContractException(
                    "UI logical/storage dimensions are outside 1..8192");
            }
            int expectedStorageWidth = checked(((logicalWidth + 3) / 4) * 4);
            int expectedStorageHeight = checked(((logicalHeight + 3) / 4) * 4);
            if (storageWidth != expectedStorageWidth
                || storageHeight != expectedStorageHeight
                || storageWidth % 4 != 0
                || storageHeight % 4 != 0
                || !string.Equals(
                    bcBlockPadding,
                    UiTextureManifestParser.BlockPaddingMode,
                    StringComparison.Ordinal))
            {
                throw new UiTextureContractException(
                    "UI BC-block storage padding contract changed");
            }

            string pathHash16 = UiTextureHash.Sha256Utf8(NoesisPath)
                .Substring(0, 16);
            string expectedBundleName =
                "sede.ui." + pathHash16 + ".bc7.v1";
            string expectedBundlePath =
                "Runtime/UiAssetBundles/win64/" + expectedBundleName;
            string expectedVirtualPath =
                "Runtime/UiTextures/virtual/" + pathHash16 + ".png";
            string expectedAddress =
                "sede/ui/" + pathHash16 + "/texture";
            if (!string.Equals(
                    bundle.PluginRelativePath,
                    expectedBundlePath,
                    StringComparison.Ordinal)
                || !string.Equals(
                    VirtualRelativePath,
                    expectedVirtualPath,
                    StringComparison.Ordinal)
                || !string.Equals(address, expectedAddress, StringComparison.Ordinal))
            {
                throw new UiTextureContractException(
                    "UI texture path-hash bundle/address binding changed");
            }

            long expectedGpuBytes;
            long expectedResidentBytes;
            long expectedTransientBytes;
            if (!UiTextureFootprint.TryCalculateBc7Bytes(
                    storageWidth,
                    storageHeight,
                    out expectedGpuBytes)
                || !UiTextureFootprint.TryCalculateResidentChargeBytes(
                    expectedGpuBytes,
                    out expectedResidentBytes)
                || !UiTextureTransientAdmission.TryCalculatePeakBytes(
                    expectedGpuBytes,
                    bundle.SizeBytes,
                    out expectedTransientBytes)
                || gpuBytes != expectedGpuBytes
                || residentChargeBytes != expectedResidentBytes
                || transientPeakBytes != expectedTransientBytes)
            {
                throw new UiTextureContractException(
                    "UI BC7 GPU/resident/transient byte formula changed");
            }

            UiTextureSamplingMode samplingMode;
            if (string.Equals(
                    textureContractId,
                    PointContractId,
                    StringComparison.Ordinal))
            {
                samplingMode = UiTextureSamplingMode.Point;
            }
            else if (string.Equals(
                    textureContractId,
                    BilinearContractId,
                    StringComparison.Ordinal))
            {
                samplingMode = UiTextureSamplingMode.Bilinear;
            }
            else
            {
                throw new UiTextureContractException(
                    "Unsupported UI texture_contract_id");
            }

            Bundle = bundle;
            Address = address;
            SourcePngSha256 = sourcePngSha256;
            PremultipliedRgbaSha256 = premultipliedRgbaSha256;
            LogicalWidth = logicalWidth;
            LogicalHeight = logicalHeight;
            StorageWidth = storageWidth;
            StorageHeight = storageHeight;
            GpuBytes = gpuBytes;
            ResidentChargeBytes = residentChargeBytes;
            TransientPeakBytes = transientPeakBytes;
            TextureContractId = textureContractId;
            BcBlockPadding = bcBlockPadding;
            SamplingMode = samplingMode;
            ExpectedTextureName = pathHash16;
            VirtualAbsolutePath = UiTexturePath.CombineOwned(
                PluginRoot,
                VirtualRelativePath);
        }

        internal string PluginRoot { get; private set; }
        internal string NoesisPath { get; private set; }
        internal string VirtualRelativePath { get; private set; }
        internal string VirtualAbsolutePath { get; private set; }
        internal string BundleId { get; private set; }
        internal string Address { get; private set; }
        internal string SourcePngSha256 { get; private set; }
        internal string PremultipliedRgbaSha256 { get; private set; }
        internal int LogicalWidth { get; private set; }
        internal int LogicalHeight { get; private set; }
        internal int StorageWidth { get; private set; }
        internal int StorageHeight { get; private set; }
        internal long GpuBytes { get; private set; }
        internal long ResidentChargeBytes { get; private set; }
        internal long TransientPeakBytes { get; private set; }
        internal string TextureContractId { get; private set; }
        internal string BcBlockPadding { get; private set; }
        internal UiTextureSamplingMode SamplingMode { get; private set; }
        internal string ExpectedTextureName { get; private set; }
        internal UiTextureBundleManifestEntry Bundle { get; private set; }

        internal string AbsolutePath
        {
            get { return VirtualAbsolutePath; }
        }
    }

    internal sealed class UiTextureManifest
    {
        private readonly ReadOnlyCollection<UiTextureBundleManifestEntry> _bundles;
        private readonly ReadOnlyCollection<UiTextureManifestEntry> _entries;
        private readonly Dictionary<string, UiTextureManifestEntry> _byNoesisPath;
        private readonly Dictionary<string, UiTextureManifestEntry> _byNoesisPathFolded;
        private readonly Dictionary<string, UiTextureManifestEntry> _byVirtualPath;

        internal UiTextureManifest(
            string pluginRoot,
            UiTextureManifestProvenance provenance,
            IList<UiTextureBundleManifestEntry> bundles,
            IList<UiTextureManifestEntry> entries,
            long declaredGpuBytes,
            long declaredResidentChargeBytes)
        {
            PluginRoot = UiTexturePath.CanonicalizePluginRoot(pluginRoot);
            Provenance = provenance
                ?? throw new ArgumentNullException("provenance");
            if (bundles == null) throw new ArgumentNullException("bundles");
            if (entries == null) throw new ArgumentNullException("entries");
            if (entries.Count < 1
                || entries.Count > UiTextureCompiledContract.MaximumEntryCount
                || bundles.Count != entries.Count)
            {
                throw new UiTextureContractException(
                    "UI manifest requires exactly one bundle per texture");
            }

            var bundleCopy = new List<UiTextureBundleManifestEntry>(bundles.Count);
            var bundleIds = new HashSet<string>(StringComparer.Ordinal);
            var bundleIdsFolded = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var bundlePaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (int index = 0; index < bundles.Count; index++)
            {
                UiTextureBundleManifestEntry bundle = bundles[index];
                if (bundle == null
                    || !string.Equals(
                        bundle.PluginRoot,
                        PluginRoot,
                        StringComparison.OrdinalIgnoreCase)
                    || !bundleIds.Add(bundle.Id)
                    || !bundleIdsFolded.Add(bundle.Id)
                    || !bundlePaths.Add(bundle.AbsolutePath))
                {
                    throw new UiTextureContractException(
                        "UI manifest contains a null, foreign, duplicate, or case-variant bundle");
                }
                bundleCopy.Add(bundle);
            }

            var entryCopy = new List<UiTextureManifestEntry>(entries.Count);
            _byNoesisPath = new Dictionary<string, UiTextureManifestEntry>(
                StringComparer.Ordinal);
            _byNoesisPathFolded = new Dictionary<string, UiTextureManifestEntry>(
                StringComparer.OrdinalIgnoreCase);
            _byVirtualPath = new Dictionary<string, UiTextureManifestEntry>(
                StringComparer.OrdinalIgnoreCase);
            var usedBundles = new HashSet<string>(StringComparer.Ordinal);
            long actualGpuBytes = 0;
            long actualResidentBytes = 0;
            for (int index = 0; index < entries.Count; index++)
            {
                UiTextureManifestEntry entry = entries[index];
                if (entry == null
                    || !string.Equals(
                        entry.PluginRoot,
                        PluginRoot,
                        StringComparison.OrdinalIgnoreCase)
                    || _byNoesisPath.ContainsKey(entry.NoesisPath)
                    || _byNoesisPathFolded.ContainsKey(entry.NoesisPath)
                    || _byVirtualPath.ContainsKey(entry.VirtualAbsolutePath)
                    || !usedBundles.Add(entry.BundleId))
                {
                    throw new UiTextureContractException(
                        "UI manifest contains a null, foreign, duplicate, or case-variant texture");
                }
                _byNoesisPath.Add(entry.NoesisPath, entry);
                _byNoesisPathFolded.Add(entry.NoesisPath, entry);
                _byVirtualPath.Add(entry.VirtualAbsolutePath, entry);
                try
                {
                    actualGpuBytes = checked(actualGpuBytes + entry.GpuBytes);
                    actualResidentBytes = checked(
                        actualResidentBytes + entry.ResidentChargeBytes);
                }
                catch (OverflowException exception)
                {
                    throw new UiTextureContractException(
                        "UI manifest byte sums overflowed",
                        exception);
                }
                entryCopy.Add(entry);
            }
            if (usedBundles.Count != bundles.Count
                || actualGpuBytes != declaredGpuBytes
                || actualResidentBytes != declaredResidentChargeBytes)
            {
                throw new UiTextureContractException(
                    "UI manifest bundle use or declared byte sums changed");
            }
            if (actualGpuBytes > UiTextureFootprint.MaximumTotalGpuBytes
                || actualResidentBytes
                    > UiTextureBudgetLedger.MaximumProcessResidentBytes)
            {
                throw new UiTextureContractException(
                    "UI manifest exceeds its GPU or 1 GiB resident budget");
            }

            DeclaredGpuBytes = declaredGpuBytes;
            DeclaredResidentChargeBytes = declaredResidentChargeBytes;
            _bundles = new ReadOnlyCollection<UiTextureBundleManifestEntry>(
                bundleCopy);
            _entries = new ReadOnlyCollection<UiTextureManifestEntry>(entryCopy);
        }

        internal string PluginRoot { get; private set; }
        internal UiTextureManifestProvenance Provenance { get; private set; }
        internal long DeclaredGpuBytes { get; private set; }
        internal long DeclaredResidentChargeBytes { get; private set; }
        internal IList<UiTextureBundleManifestEntry> Bundles
        {
            get { return _bundles; }
        }
        internal IList<UiTextureManifestEntry> Entries
        {
            get { return _entries; }
        }

        internal bool TryResolveNoesisPath(
            string key,
            out UiTextureManifestEntry entry,
            out string virtualAbsolutePath)
        {
            entry = null;
            virtualAbsolutePath = null;
            if (string.IsNullOrEmpty(key)) return false;
            string normalized = key.Replace('\\', '/');
            if (!_byNoesisPath.TryGetValue(normalized, out entry)
                && !normalized.EndsWith(".png", StringComparison.Ordinal))
            {
                _byNoesisPath.TryGetValue(normalized + ".png", out entry);
            }
            if (entry == null) return false;
            virtualAbsolutePath = entry.VirtualAbsolutePath;
            return true;
        }

        internal bool TryFindOwnedPath(
            string candidatePath,
            out UiTextureManifestEntry entry)
        {
            return TryFindOwnedLoadPath(candidatePath, out entry);
        }

        internal bool TryFindOwnedLoadPath(
            string candidatePath,
            out UiTextureManifestEntry entry)
        {
            entry = null;
            string canonical;
            if (!UiTexturePath.TryCanonicalizeAbsoluteFile(
                    candidatePath,
                    out canonical))
            {
                return false;
            }
            if (_byVirtualPath.TryGetValue(canonical, out entry))
            {
                return true;
            }

            string forward = canonical.Replace('\\', '/');
            const string marker = "/Override/";
            int markerIndex = forward.LastIndexOf(
                marker,
                StringComparison.OrdinalIgnoreCase);
            if (markerIndex <= 0) return false;
            string noesis = forward.Substring(markerIndex + marker.Length);
            return _byNoesisPathFolded.TryGetValue(noesis, out entry);
        }

        internal static UiTextureManifest Load(
            string pluginRoot,
            UiTextureCompiledContract contract)
        {
            if (contract == null) throw new ArgumentNullException("contract");
            if (!contract.Enabled)
            {
                throw new UiTextureContractException(
                    "Cannot load a disabled UI texture contract");
            }
            string canonicalRoot = UiTexturePath.CanonicalizePluginRoot(pluginRoot);
            string manifestPath = UiTexturePath.CombineOwned(
                canonicalRoot,
                UiTextureCompiledContract.ManifestRelativePath);
            UiTextureFileVerifier.RejectReparsePoints(
                canonicalRoot,
                UiTextureCompiledContract.ManifestRelativePath);
            byte[] bytes = UiTextureFileVerifier.ReadExactFile(
                manifestPath,
                contract.ManifestSize,
                UiTextureCompiledContract.MaximumManifestBytes);
            if (!string.Equals(
                    UiTextureHash.Sha256(bytes),
                    contract.ManifestSha256,
                    StringComparison.Ordinal))
            {
                throw new UiTextureContractException(
                    "UI texture manifest SHA-256 differs from the compiled contract");
            }
            return UiTextureManifestParser.Parse(
                bytes,
                canonicalRoot,
                contract.EntryCount);
        }

    }

    /// <summary>
    /// Generic manifest-owned URI bridge. The historical class name is kept so
    /// generated runtime callers do not need a second transition.
    /// </summary>
    internal sealed class UiTextureModIconBridge
    {
        private readonly UiTextureManifest _manifest;

        private UiTextureModIconBridge(UiTextureManifest manifest)
        {
            _manifest = manifest;
        }

        internal static UiTextureModIconBridge CreateIfPresent(
            UiTextureManifest manifest)
        {
            if (manifest == null) throw new ArgumentNullException("manifest");
            return manifest.Entries.Count == 0
                ? null
                : new UiTextureModIconBridge(manifest);
        }

        internal bool TryResolve(string key, out string absolutePath)
        {
            UiTextureManifestEntry entry;
            return _manifest.TryResolveNoesisPath(
                key,
                out entry,
                out absolutePath);
        }
    }

    internal static class UiTextureManifestParser
    {
        internal const string SourceSchema =
            "stronghold-europe-de.ui-texture-sources.v1";
        internal const string QualityPolicySchema =
            "stronghold-europe-de.ui-bc7-quality-policy.v1";
        internal const string QualityPolicyId =
            "bc7_ui_visual_equivalence_v1";
        internal const string QualityVerifierId =
            "unitypy-1.25.3-ui-bc7-premultiplied-metrics-v1";
        internal const string EncoderId =
            "unity-2021.3.45f2-bc7-hq100-force-max-ui-v1";
        internal const string UnityVersion = "2021.3.45f2";
        internal const string UnityRevision = "88f88f591b2e";
        internal const string AlphaMode =
            "premultiply-u8-round-nearest-v1";
        internal const string BlockPaddingMode =
            "edge-extend-right-bottom-to-bc-block-v1";

        private const string Magic = "stronghold-europe-ui-textures\t2";
        private const string BundleColumns =
            "bundle\tid\tplugin_relative_path\tsha256\tsize_bytes\tcrc32\tunity_hash128";
        private const string TextureColumns =
            "texture\tnoesis_path\tvirtual_relative_path\tbundle_id\taddress"
            + "\tsource_png_sha256\tpremultiplied_rgba_sha256"
            + "\tlogical_width\tlogical_height\tstorage_width\tstorage_height"
            + "\tgpu_bytes\tresident_charge_bytes\ttransient_peak_bytes"
            + "\ttexture_contract_id\tbc_block_padding";

        internal static UiTextureManifest Parse(
            byte[] payload,
            string pluginRoot,
            int expectedEntryCount)
        {
            if (payload == null) throw new ArgumentNullException("payload");
            if (payload.Length < 1
                || payload.LongLength > UiTextureCompiledContract.MaximumManifestBytes)
            {
                throw new UiTextureContractException(
                    "UI texture manifest is empty or too large");
            }
            if (expectedEntryCount < 1
                || expectedEntryCount > UiTextureCompiledContract.MaximumEntryCount)
            {
                throw new ArgumentOutOfRangeException("expectedEntryCount");
            }
            if (payload.Length >= 3
                && payload[0] == 0xef
                && payload[1] == 0xbb
                && payload[2] == 0xbf)
            {
                throw new UiTextureContractException(
                    "UI texture manifest must be BOM-free UTF-8");
            }

            string text;
            try
            {
                text = new UTF8Encoding(false, true).GetString(payload);
            }
            catch (DecoderFallbackException exception)
            {
                throw new UiTextureContractException(
                    "UI texture manifest is not strict UTF-8",
                    exception);
            }
            if (text.IndexOf('\r') >= 0)
            {
                throw new UiTextureContractException(
                    "UI texture manifest must use LF line endings");
            }
            if (!text.EndsWith("\n", StringComparison.Ordinal)
                || text.EndsWith("\n\n", StringComparison.Ordinal))
            {
                throw new UiTextureContractException(
                    "UI texture manifest must end with exactly one LF");
            }

            string[] lines = text.Substring(0, text.Length - 1)
                .Split(new[] { '\n' }, StringSplitOptions.None);
            if (lines.Length < 22)
            {
                throw new UiTextureContractException(
                    "UI texture manifest is truncated");
            }
            RequireExact(lines[0], Magic, "schema header");
            RequireHeaderExact(lines[1], "source_schema", SourceSchema);
            string sourceManifestSha256 = ParseDigestHeader(
                lines[2],
                "source_manifest_sha256");
            string sourceEntrySetSha256 = ParseDigestHeader(
                lines[3],
                "source_entry_set_sha256");
            RequireHeaderExact(
                lines[4],
                "quality_policy_schema",
                QualityPolicySchema);
            RequireHeaderExact(lines[5], "quality_policy_id", QualityPolicyId);
            string qualityPolicySha256 = ParseDigestHeader(
                lines[6],
                "quality_policy_sha256");
            RequireHeaderExact(
                lines[7],
                "quality_verifier_id",
                QualityVerifierId);
            RequireHeaderExact(lines[8], "encoder_id", EncoderId);
            string editorSourceSha256 = ParseDigestHeader(
                lines[9],
                "editor_source_sha256");
            RequireHeaderExact(lines[10], "unity_version", UnityVersion);
            RequireHeaderExact(lines[11], "unity_revision", UnityRevision);
            RequireHeaderExact(lines[12], "alpha_mode", AlphaMode);
            RequireHeaderExact(lines[13], "bc_block_padding", BlockPaddingMode);
            int entryCount = checked((int)ParseHeaderLong(
                lines[14],
                "entry_count",
                1,
                UiTextureCompiledContract.MaximumEntryCount));
            int bundleCount = checked((int)ParseHeaderLong(
                lines[15],
                "bundle_count",
                1,
                UiTextureCompiledContract.MaximumEntryCount));
            long declaredGpuBytes = ParseHeaderLong(
                lines[16],
                "declared_gpu_bytes",
                1,
                UiTextureFootprint.MaximumTotalGpuBytes);
            long declaredResidentBytes = ParseHeaderLong(
                lines[17],
                "declared_resident_charge_bytes",
                1,
                UiTextureBudgetLedger.MaximumProcessResidentBytes);
            if (entryCount != expectedEntryCount || bundleCount != entryCount)
            {
                throw new UiTextureContractException(
                    "compiled entry count or one-bundle-per-texture count changed");
            }
            RequireExact(lines[18], BundleColumns, "bundle columns");
            int expectedLines = checked(20 + bundleCount + entryCount);
            if (lines.Length != expectedLines)
            {
                throw new UiTextureContractException(
                    "UI texture manifest row count differs from its headers");
            }

            string canonicalRoot = UiTexturePath.CanonicalizePluginRoot(pluginRoot);
            var bundles = new List<UiTextureBundleManifestEntry>(bundleCount);
            var bundlesById = new Dictionary<string, UiTextureBundleManifestEntry>(
                StringComparer.Ordinal);
            string previousBundleId = null;
            for (int index = 0; index < bundleCount; index++)
            {
                string label = "bundle row "
                    + index.ToString(CultureInfo.InvariantCulture);
                string[] fields = SplitExact(lines[19 + index], 7, label);
                RequireExact(fields[0], "bundle", label + " kind");
                if (previousBundleId != null
                    && string.CompareOrdinal(previousBundleId, fields[1]) >= 0)
                {
                    throw new UiTextureContractException(
                        "bundle rows must be strictly ordered by id");
                }
                previousBundleId = fields[1];
                var bundle = new UiTextureBundleManifestEntry(
                    canonicalRoot,
                    fields[1],
                    fields[2],
                    fields[3],
                    ParseCanonicalLong(
                        fields[4],
                        1,
                        UiTextureBundleManifestEntry.MaximumBundleBytes,
                        label + " size_bytes"),
                    fields[5],
                    fields[6]);
                if (bundlesById.ContainsKey(bundle.Id))
                {
                    throw new UiTextureContractException("duplicate bundle id");
                }
                bundlesById.Add(bundle.Id, bundle);
                bundles.Add(bundle);
            }

            int textureColumnsIndex = 19 + bundleCount;
            RequireExact(
                lines[textureColumnsIndex],
                TextureColumns,
                "texture columns");
            var entries = new List<UiTextureManifestEntry>(entryCount);
            string previousNoesisPath = null;
            for (int index = 0; index < entryCount; index++)
            {
                string label = "texture row "
                    + index.ToString(CultureInfo.InvariantCulture);
                string[] fields = SplitExact(
                    lines[textureColumnsIndex + 1 + index],
                    16,
                    label);
                RequireExact(fields[0], "texture", label + " kind");
                if (previousNoesisPath != null
                    && string.CompareOrdinal(previousNoesisPath, fields[1]) >= 0)
                {
                    throw new UiTextureContractException(
                        "texture rows must be strictly ordered by noesis_path");
                }
                previousNoesisPath = fields[1];
                UiTextureBundleManifestEntry bundle;
                if (!bundlesById.TryGetValue(fields[3], out bundle))
                {
                    throw new UiTextureContractException(
                        "texture row references an unknown bundle_id");
                }
                entries.Add(new UiTextureManifestEntry(
                    canonicalRoot,
                    fields[1],
                    fields[2],
                    fields[3],
                    fields[4],
                    fields[5],
                    fields[6],
                    ParseCanonicalInt(
                        fields[7],
                        1,
                        UiTextureManifestEntry.MaximumDimension,
                        label + " logical_width"),
                    ParseCanonicalInt(
                        fields[8],
                        1,
                        UiTextureManifestEntry.MaximumDimension,
                        label + " logical_height"),
                    ParseCanonicalInt(
                        fields[9],
                        1,
                        UiTextureManifestEntry.MaximumDimension,
                        label + " storage_width"),
                    ParseCanonicalInt(
                        fields[10],
                        1,
                        UiTextureManifestEntry.MaximumDimension,
                        label + " storage_height"),
                    ParseCanonicalLong(
                        fields[11],
                        1,
                        UiTextureFootprint.MaximumSingleGpuBytes,
                        label + " gpu_bytes"),
                    ParseCanonicalLong(
                        fields[12],
                        1,
                        UiTextureBudgetLedger.MaximumProcessResidentBytes,
                        label + " resident_charge_bytes"),
                    ParseCanonicalLong(
                        fields[13],
                        1,
                        UiTextureTransientAdmission.MaximumTransientPeakBytes,
                        label + " transient_peak_bytes"),
                    fields[14],
                    fields[15],
                    bundle));
            }

            var provenance = new UiTextureManifestProvenance(
                sourceManifestSha256,
                sourceEntrySetSha256,
                qualityPolicySha256,
                editorSourceSha256);
            return new UiTextureManifest(
                canonicalRoot,
                provenance,
                bundles,
                entries,
                declaredGpuBytes,
                declaredResidentBytes);
        }

        private static string ParseDigestHeader(string line, string key)
        {
            string[] fields = SplitExact(line, 2, key);
            RequireExact(fields[0], key, key + " key");
            UiTextureContractRules.RequireSha256(fields[1], key);
            return fields[1];
        }

        private static void RequireHeaderExact(
            string line,
            string key,
            string expectedValue)
        {
            string[] fields = SplitExact(line, 2, key);
            RequireExact(fields[0], key, key + " key");
            RequireExact(fields[1], expectedValue, key + " value");
        }

        private static long ParseHeaderLong(
            string line,
            string key,
            long minimum,
            long maximum)
        {
            string[] fields = SplitExact(line, 2, key);
            RequireExact(fields[0], key, key + " key");
            return ParseCanonicalLong(fields[1], minimum, maximum, key);
        }

        private static string[] SplitExact(
            string line,
            int expectedFields,
            string label)
        {
            string[] fields = line.Split(new[] { '\t' }, StringSplitOptions.None);
            if (fields.Length != expectedFields)
            {
                throw new UiTextureContractException(
                    label + " has an unexpected field count");
            }
            for (int index = 0; index < fields.Length; index++)
            {
                if (fields[index].Length == 0)
                {
                    throw new UiTextureContractException(
                        label + " contains an empty field");
                }
            }
            return fields;
        }

        private static int ParseCanonicalInt(
            string token,
            int minimum,
            int maximum,
            string label)
        {
            return checked((int)ParseCanonicalLong(
                token,
                minimum,
                maximum,
                label));
        }

        private static long ParseCanonicalLong(
            string token,
            long minimum,
            long maximum,
            string label)
        {
            long result;
            if (!long.TryParse(
                    token,
                    NumberStyles.None,
                    CultureInfo.InvariantCulture,
                    out result)
                || result < minimum
                || result > maximum
                || !string.Equals(
                    token,
                    result.ToString(CultureInfo.InvariantCulture),
                    StringComparison.Ordinal))
            {
                throw new UiTextureContractException(
                    label + " is not a canonical in-range integer");
            }
            return result;
        }

        private static void RequireExact(
            string actual,
            string expected,
            string label)
        {
            if (!string.Equals(actual, expected, StringComparison.Ordinal))
            {
                throw new UiTextureContractException(label + " differs");
            }
        }
    }

    internal static class UiTextureFootprint
    {
        internal const long MaximumTotalGpuBytes = 2L * 1024L * 1024L * 1024L;
        internal const long MaximumSingleGpuBytes = 64L * 1024L * 1024L;
        internal const long ResidentFixedBytes = 64L * 1024L;

        internal static bool TryCalculateBc7Bytes(
            int storageWidth,
            int storageHeight,
            out long bytes)
        {
            bytes = 0;
            if (storageWidth < 1
                || storageWidth > UiTextureManifestEntry.MaximumDimension
                || storageHeight < 1
                || storageHeight > UiTextureManifestEntry.MaximumDimension
                || storageWidth % 4 != 0
                || storageHeight % 4 != 0)
            {
                return false;
            }
            try
            {
                bytes = checked(
                    checked((long)(storageWidth / 4) * (storageHeight / 4))
                    * 16L);
                return bytes > 0 && bytes <= MaximumSingleGpuBytes;
            }
            catch (OverflowException)
            {
                bytes = 0;
                return false;
            }
        }

        internal static bool TryCalculateResidentChargeBytes(
            long gpuBytes,
            out long bytes)
        {
            bytes = 0;
            if (gpuBytes < 1 || gpuBytes > MaximumSingleGpuBytes)
            {
                return false;
            }
            try
            {
                bytes = checked(
                    checked(gpuBytes * 9L + 7L) / 8L
                    + ResidentFixedBytes);
                return bytes > 0;
            }
            catch (OverflowException)
            {
                bytes = 0;
                return false;
            }
        }
    }

    internal static class UiTexturePath
    {
        private const int MaximumRelativePathCharacters = 1024;

        internal static string CanonicalizePluginRoot(string pluginRoot)
        {
            if (string.IsNullOrWhiteSpace(pluginRoot))
            {
                throw new ArgumentNullException("pluginRoot");
            }
            string full;
            try
            {
                full = Path.GetFullPath(pluginRoot);
            }
            catch (Exception exception)
            {
                throw new UiTextureContractException(
                    "Plugin root is not a valid absolute path",
                    exception);
            }
            string root = Path.GetPathRoot(full);
            if (string.IsNullOrEmpty(root)
                || string.Equals(full, root, StringComparison.OrdinalIgnoreCase))
            {
                throw new UiTextureContractException(
                    "Plugin root may not be a filesystem root");
            }
            return full.TrimEnd(
                Path.DirectorySeparatorChar,
                Path.AltDirectorySeparatorChar);
        }

        internal static string RequireCanonicalNoesisPath(
            string value,
            string label)
        {
            string result = RequireCanonicalRelativePngPath(value, label);
            if (!result.StartsWith("Assets/GUI/", StringComparison.Ordinal))
            {
                throw new UiTextureContractException(
                    label + " must be below Assets/GUI/");
            }
            return result;
        }

        internal static string RequireCanonicalRelativePngPath(
            string value,
            string label)
        {
            string result = RequireCanonicalRelativePath(value, label);
            if (!result.EndsWith(".png", StringComparison.Ordinal))
            {
                throw new UiTextureContractException(
                    label + " must end in canonical lowercase .png");
            }
            return result;
        }

        internal static string RequireCanonicalRelativePath(
            string value,
            string label)
        {
            if (string.IsNullOrEmpty(value)
                || value.Length > MaximumRelativePathCharacters
                || !value.IsNormalized(NormalizationForm.FormC))
            {
                throw new UiTextureContractException(
                    label + " is empty, too long, or not Unicode NFC");
            }
            if (value[0] == '/'
                || value[value.Length - 1] == '/'
                || value.IndexOf('\\') >= 0
                || value.IndexOf("//", StringComparison.Ordinal) >= 0
                || Path.IsPathRooted(value))
            {
                throw new UiTextureContractException(
                    label + " is not a canonical forward-slash relative path");
            }
            string[] segments = value.Split('/');
            for (int index = 0; index < segments.Length; index++)
            {
                RequireCanonicalSegment(segments[index], label);
            }
            return value;
        }

        internal static string CombineOwned(
            string canonicalPluginRoot,
            string canonicalRelativePath)
        {
            string root = CanonicalizePluginRoot(canonicalPluginRoot);
            string relative = canonicalRelativePath.Replace(
                '/',
                Path.DirectorySeparatorChar);
            string full;
            try
            {
                full = Path.GetFullPath(Path.Combine(root, relative));
            }
            catch (Exception exception)
            {
                throw new UiTextureContractException(
                    "Owned path cannot be canonicalized",
                    exception);
            }
            string prefix = root + Path.DirectorySeparatorChar;
            if (!full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                throw new UiTextureContractException(
                    "Owned path escapes the plugin root");
            }
            return full;
        }

        internal static bool TryCanonicalizeAbsoluteFile(
            string candidatePath,
            out string canonicalPath)
        {
            canonicalPath = null;
            if (string.IsNullOrWhiteSpace(candidatePath)
                || !Path.IsPathRooted(candidatePath))
            {
                return false;
            }
            try
            {
                string full = Path.GetFullPath(candidatePath);
                if (full.EndsWith(
                        Path.DirectorySeparatorChar.ToString(),
                        StringComparison.Ordinal)
                    || full.EndsWith(
                        Path.AltDirectorySeparatorChar.ToString(),
                        StringComparison.Ordinal))
                {
                    return false;
                }
                canonicalPath = full;
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static void RequireCanonicalSegment(string segment, string label)
        {
            if (segment.Length == 0
                || segment.Length > 255
                || string.Equals(segment, ".", StringComparison.Ordinal)
                || string.Equals(segment, "..", StringComparison.Ordinal)
                || segment[0] == ' '
                || segment[segment.Length - 1] == '.'
                || segment[segment.Length - 1] == ' ')
            {
                throw new UiTextureContractException(
                    label + " contains a non-canonical segment");
            }
            for (int index = 0; index < segment.Length; index++)
            {
                char character = segment[index];
                if (character < 0x20
                    || character == 0x7f
                    || character == '<'
                    || character == '>'
                    || character == ':'
                    || character == '"'
                    || character == '\\'
                    || character == '|'
                    || character == '?'
                    || character == '*'
                    || char.IsSurrogate(character))
                {
                    throw new UiTextureContractException(
                        label + " contains a forbidden path character");
                }
            }
            string deviceName = segment;
            int extension = deviceName.IndexOf('.');
            if (extension >= 0) deviceName = deviceName.Substring(0, extension);
            if (IsReservedWindowsDevice(deviceName))
            {
                throw new UiTextureContractException(
                    label + " contains a reserved Windows device name");
            }
        }

        private static bool IsReservedWindowsDevice(string value)
        {
            if (string.Equals(value, "CON", StringComparison.OrdinalIgnoreCase)
                || string.Equals(value, "PRN", StringComparison.OrdinalIgnoreCase)
                || string.Equals(value, "AUX", StringComparison.OrdinalIgnoreCase)
                || string.Equals(value, "NUL", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
            if (value.Length == 4 && value[3] >= '1' && value[3] <= '9')
            {
                string prefix = value.Substring(0, 3);
                return string.Equals(prefix, "COM", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(prefix, "LPT", StringComparison.OrdinalIgnoreCase);
            }
            return false;
        }
    }

    internal static class UiTextureFileVerifier
    {
        internal static byte[] ReadExactFile(
            string path,
            long expectedBytes,
            long maximumBytes)
        {
            if (expectedBytes < 1
                || expectedBytes > maximumBytes
                || expectedBytes > int.MaxValue)
            {
                throw new UiTextureContractException(
                    "Expected file size is outside the readable range");
            }
            try
            {
                using (var stream = new FileStream(
                    path,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.Read,
                    128 * 1024,
                    FileOptions.SequentialScan))
                {
                    if (stream.Length != expectedBytes)
                    {
                        throw new UiTextureContractException(
                            "File size differs from the compiled contract");
                    }
                    var bytes = new byte[checked((int)expectedBytes)];
                    int offset = 0;
                    while (offset < bytes.Length)
                    {
                        int read = stream.Read(bytes, offset, bytes.Length - offset);
                        if (read == 0) throw new EndOfStreamException();
                        offset += read;
                    }
                    if (stream.Length != expectedBytes || stream.ReadByte() != -1)
                    {
                        throw new UiTextureContractException(
                            "File changed while it was being read");
                    }
                    return bytes;
                }
            }
            catch (UiTextureContractException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw new UiTextureContractException(
                    "File could not be read exactly",
                    exception);
            }
        }

        internal static void RejectReparsePoints(
            string pluginRoot,
            string pluginRelativePath)
        {
            string current = pluginRoot;
            RejectReparsePoint(current);
            string[] segments = pluginRelativePath.Split('/');
            for (int index = 0; index < segments.Length; index++)
            {
                current = Path.Combine(current, segments[index]);
                RejectReparsePoint(current);
            }
        }

        private static void RejectReparsePoint(string path)
        {
            FileAttributes attributes;
            try
            {
                attributes = File.GetAttributes(path);
            }
            catch (Exception exception)
            {
                throw new UiTextureContractException(
                    "Owned UI path is missing or unreadable",
                    exception);
            }
            if ((attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new UiTextureContractException(
                    "Owned UI paths may not traverse reparse points");
            }
        }
    }

    internal static class UiTextureHash
    {
        internal static string Sha256(byte[] bytes)
        {
            if (bytes == null) throw new ArgumentNullException("bytes");
            using (SHA256 algorithm = SHA256.Create())
            {
                return Hex(algorithm.ComputeHash(bytes));
            }
        }

        internal static string Sha256Utf8(string value)
        {
            if (value == null) throw new ArgumentNullException("value");
            return Sha256(new UTF8Encoding(false, true).GetBytes(value));
        }

        internal static string Hex(byte[] digest)
        {
            if (digest == null) throw new ArgumentNullException("digest");
            var result = new StringBuilder(digest.Length * 2);
            for (int index = 0; index < digest.Length; index++)
            {
                result.Append(digest[index].ToString(
                    "x2",
                    CultureInfo.InvariantCulture));
            }
            return result.ToString();
        }
    }

    internal static class UiTextureCrc32
    {
        private static readonly uint[] Table = BuildTable();

        internal static uint InitialState
        {
            get { return uint.MaxValue; }
        }

        internal static void Update(
            ref uint state,
            byte[] buffer,
            int offset,
            int count)
        {
            if (buffer == null) throw new ArgumentNullException("buffer");
            if (offset < 0 || count < 0 || offset > buffer.Length - count)
            {
                throw new ArgumentOutOfRangeException("offset");
            }
            for (int index = offset; index < offset + count; index++)
            {
                state = Table[(state ^ buffer[index]) & 0xff] ^ (state >> 8);
            }
        }

        internal static uint Finish(uint state)
        {
            return ~state;
        }

        internal static string ComputeHex(byte[] bytes)
        {
            if (bytes == null) throw new ArgumentNullException("bytes");
            uint state = InitialState;
            Update(ref state, bytes, 0, bytes.Length);
            return Finish(state).ToString("x8", CultureInfo.InvariantCulture);
        }

        private static uint[] BuildTable()
        {
            var table = new uint[256];
            for (uint index = 0; index < table.Length; index++)
            {
                uint value = index;
                for (int bit = 0; bit < 8; bit++)
                {
                    value = (value & 1U) != 0
                        ? 0xedb88320U ^ (value >> 1)
                        : value >> 1;
                }
                table[index] = value;
            }
            return table;
        }
    }

    internal static class UiTextureContractRules
    {
        internal static string RequireIdentifier(string value, string label)
        {
            bool firstValid = !string.IsNullOrEmpty(value)
                && ((value[0] >= 'a' && value[0] <= 'z')
                    || (value[0] >= '0' && value[0] <= '9'));
            if (!firstValid || value.Length > 96)
            {
                throw new UiTextureContractException(
                    label + " is not a canonical identifier");
            }
            for (int index = 0; index < value.Length; index++)
            {
                char character = value[index];
                if (!((character >= 'a' && character <= 'z')
                    || (character >= '0' && character <= '9')
                    || character == '.'
                    || character == '_'
                    || character == '-'))
                {
                    throw new UiTextureContractException(
                        label + " is not a canonical identifier");
                }
            }
            return value;
        }

        internal static void RequireSha256(string value, string label)
        {
            RequireLowerHex(value, 64, label);
        }

        internal static void RequireLowerHex(
            string value,
            int expectedCharacters,
            string label)
        {
            if (value == null || value.Length != expectedCharacters)
            {
                throw new UiTextureContractException(
                    label + " must be lowercase hexadecimal");
            }
            for (int index = 0; index < value.Length; index++)
            {
                char character = value[index];
                if (!((character >= '0' && character <= '9')
                    || (character >= 'a' && character <= 'f')))
                {
                    throw new UiTextureContractException(
                        label + " must be lowercase hexadecimal");
                }
            }
        }
    }
}
