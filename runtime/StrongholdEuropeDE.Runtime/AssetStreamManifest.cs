using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>Exact constants shared with asset_stream_contract.py.</summary>
    internal static class AssetStreamContract
    {
        internal const string AtlasBackendKind = "unity_assetbundle_lossless_streaming_v1";
        internal const string ResourcePolicyKind = "windows_24gb_igpu_safe_v1";
        internal const string IndexSchema = "stronghold-europe-de.asset-bundle-index.v1";
        internal const string AtlasSchema = "stronghold-europe-de.atlas.v2";
        internal const string UnityVersion = "2021.3.45f2";
        internal const string UnityRevision = "88f88f591b2e";
        internal const string BuildTarget = "StandaloneWindows64";
        internal const string IndexRelativePath = "Runtime/AssetBundles/index.json";
        internal const string BundleRelativePrefix = "Runtime/AssetBundles/win64/";
        internal const int MinimumPageDimension = 256;
        internal const int MaximumPageDimension = 4096;
        internal const int MaximumGroups = 234;
        internal const int MaximumPagesPerGroup = 16;
        internal const int MaximumFramesPerGroup = 4096;
        internal const int MaximumPreflightFramesPerGroup = 65536;
        // Defensive JSON bound, not a Sprite.Create limit.  The pinned games
        // intentionally author pivots as far as 100/-99 (blast3).
        internal const double MaximumAbsoluteSpritePivot = 100.0;
        internal const int MaximumIndexBytes = 4 * 1024 * 1024;
        internal const int MaximumAtlasBytes = 4 * 1024 * 1024;
    }

    /// <summary>
    /// Discriminated BC7 visual-equivalence contract.  These constants are
    /// intentionally separate from AssetStreamContract so historical V1
    /// manifests keep their exact meanings and parser behaviour.
    /// </summary>
    internal static class AssetStreamBc7Contract
    {
        internal const string AtlasBackendKind =
            "unity_assetbundle_bc7_visual_equivalence_v2";
        internal const string ResourcePolicyKind =
            "windows_24gb_igpu_bc7_12gib_process_private_v5";
        internal const string IndexSchema =
            "stronghold-europe-de.asset-bundle-index.v2";
        internal const string AtlasSchema = "stronghold-europe-de.atlas.v3";
        internal const string BundleSuffix = ".bc7.v2";
        internal const string AtlasFileName = "atlas.v3.json";
        internal const string PackerId =
            "maxrects-bssf-no-rotation-cell4-rgba-extrude-v2";
        internal const string EncoderId =
            "unity-2021.3.45f2-bc7-hq100-force-max-v1";
        internal const string ExtrusionMode = "nearest_edge_full_rgba_v1";
        internal const string QualityVerifierId =
            "unitypy-1.25.3-bc7-frame-metrics-v1";
        internal const string FrozenQualityState = "frozen";
        internal const string FrozenQualityPolicyId =
            "bc7_visual_equivalence_v2";
        internal const string MeasurementQualityState =
            "measurement_nonpromotable";
        internal const string MeasurementQualityPolicyId =
            "bc7_visual_equivalence_measurement_v1";
        internal const string MeasurementQualityPolicySha256 =
            "ef1799a23471a41f93df5e9ed8a79839e6051221cd699d988e7b6ae0a34f17e1";
        internal const string Bc7MainBc7MaskTexturePolicyId =
            "bc7-main-bc7-mask-hq100-v1";
        internal const string Bc7MainRgba32MaskTexturePolicyId =
            "bc7-main-rgba32-mask-hq100-v1";
        internal const int BlockAlignmentPixels = 4;
        internal const int MinimumBorderPixels = 1;
        internal const long MaximumTotalResidentChargeBytes =
            3L * 1024 * 1024 * 1024;
    }

    internal enum AssetStreamPipelineVersion
    {
        LosslessRgbaV1 = 1,
        Bc7VisualEquivalenceV2 = 2,
    }

    internal static class AssetStreamMaterialBindingContract
    {
        internal const string PlainShared = "plain_shared_v1";
        internal const string GroupMaskSinglePage =
            "group_mask_single_page_v1";
        internal const string SetBodySpritePageMask =
            "set_body_sprite_postfix_page_mask_v1";

        /// <summary>
        /// Every masked atlas needs an exact runtime Sprite-to-page-mask route.
        /// The material-binding value still describes how the group's shared
        /// materials are built; it must not decide whether a pooled renderer
        /// can recover the mask for its current Sprite.
        /// </summary>
        internal static bool RequiresExactSpriteMaskRoute(
            AssetStreamMaskPolicy maskPolicy)
        {
            return maskPolicy == AssetStreamMaskPolicy.Required;
        }

        internal static bool IsReviewedBodySlug(string slug)
        {
            return string.Equals(slug, "body_trebutchet", StringComparison.Ordinal)
                || string.Equals(slug, "body_archer", StringComparison.Ordinal)
                || string.Equals(
                    slug,
                    "body_battering_ram",
                    StringComparison.Ordinal)
                || string.Equals(slug, "body_catapult", StringComparison.Ordinal)
                || string.Equals(slug, "body_deer", StringComparison.Ordinal)
                || string.Equals(slug, "body_farmer", StringComparison.Ordinal);
        }

        internal static bool IsExact(
            AssetStreamMaskPolicy maskPolicy,
            string slug,
            int pageCount,
            string materialBinding)
        {
            if (maskPolicy == AssetStreamMaskPolicy.Forbidden)
            {
                return string.Equals(
                    materialBinding,
                    PlainShared,
                    StringComparison.Ordinal);
            }
            if (maskPolicy != AssetStreamMaskPolicy.Required)
            {
                return false;
            }
            if (IsReviewedBodySlug(slug))
            {
                return pageCount >= 1
                    && pageCount <= AssetStreamContract.MaximumPagesPerGroup
                    && string.Equals(
                        materialBinding,
                        SetBodySpritePageMask,
                        StringComparison.Ordinal);
            }
            return pageCount == 1
                && string.Equals(
                    materialBinding,
                    GroupMaskSinglePage,
                    StringComparison.Ordinal);
        }
    }

    internal enum AssetStreamMaskPolicy
    {
        Forbidden = 0,
        Required = 1,
    }

    internal sealed class AssetStreamUnityIdentity
    {
        internal AssetStreamUnityIdentity(string version, string revision)
        {
            Version = version;
            Revision = revision;
        }

        internal string Version { get; private set; }
        internal string Revision { get; private set; }
    }

    internal sealed class AssetStreamTexturePolicy
    {
        internal AssetStreamTexturePolicy(
            string id,
            string mainFormat,
            string maskFormat)
        {
            Id = id;
            MainFormat = mainFormat;
            MaskFormat = maskFormat;
        }

        internal string Id { get; private set; }
        internal string MainFormat { get; private set; }
        internal string MaskFormat { get; private set; }
    }

    internal sealed class AssetStreamQualityPolicy
    {
        internal AssetStreamQualityPolicy(
            string state,
            string id,
            string sha256,
            string verifierId)
        {
            State = state;
            Id = id;
            Sha256 = sha256;
            VerifierId = verifierId;
        }

        internal string State { get; private set; }
        internal string Id { get; private set; }
        internal string Sha256 { get; private set; }
        internal string VerifierId { get; private set; }
        internal bool IsPromotable
        {
            get
            {
                return string.Equals(
                    State,
                    AssetStreamBc7Contract.FrozenQualityState,
                    StringComparison.Ordinal);
            }
        }
    }

    internal sealed class AssetStreamTextureContract
    {
        internal AssetStreamTextureContract(
            string format,
            bool sRgb,
            bool mipmaps,
            bool readable,
            string filterMode,
            string wrapMode,
            string alphaSource,
            bool alphaIsTransparency,
            string npotScale)
            : this(
                format,
                sRgb,
                mipmaps,
                readable,
                filterMode,
                wrapMode,
                alphaSource,
                alphaIsTransparency,
                npotScale,
                false,
                0,
                "Uncompressed",
                100,
                false,
                false,
                4,
                1,
                1,
                true,
                AssetStreamContract.MaximumPageDimension,
                true,
                false,
                "Default",
                4)
        {
        }

        internal AssetStreamTextureContract(
            string format,
            bool sRgb,
            bool mipmaps,
            bool readable,
            string filterMode,
            string wrapMode,
            string alphaSource,
            bool alphaIsTransparency,
            string npotScale,
            bool allowsAlphaSplitting,
            int anisoLevel,
            string compression,
            int compressionQuality,
            bool crunchedCompression,
            bool forceMaximumCompressionQualityBc6hBc7,
            int gpuBlockBytes,
            int gpuBlockHeight,
            int gpuBlockWidth,
            bool ignorePngGamma,
            int maxTextureSize,
            bool platformOverride,
            bool streamingMipmaps,
            string textureType,
            int unityTextureFormat)
        {
            Format = format;
            SRgb = sRgb;
            Mipmaps = mipmaps;
            Readable = readable;
            FilterMode = filterMode;
            WrapMode = wrapMode;
            AlphaSource = alphaSource;
            AlphaIsTransparency = alphaIsTransparency;
            NpotScale = npotScale;
            AllowsAlphaSplitting = allowsAlphaSplitting;
            AnisoLevel = anisoLevel;
            Compression = compression;
            CompressionQuality = compressionQuality;
            CrunchedCompression = crunchedCompression;
            ForceMaximumCompressionQualityBc6hBc7 =
                forceMaximumCompressionQualityBc6hBc7;
            GpuBlockBytes = gpuBlockBytes;
            GpuBlockHeight = gpuBlockHeight;
            GpuBlockWidth = gpuBlockWidth;
            IgnorePngGamma = ignorePngGamma;
            MaxTextureSize = maxTextureSize;
            PlatformOverride = platformOverride;
            StreamingMipmaps = streamingMipmaps;
            TextureType = textureType;
            UnityTextureFormat = unityTextureFormat;
        }

        internal string Format { get; private set; }
        internal bool SRgb { get; private set; }
        internal bool Mipmaps { get; private set; }
        internal bool Readable { get; private set; }
        internal string FilterMode { get; private set; }
        internal string WrapMode { get; private set; }
        internal string AlphaSource { get; private set; }
        internal bool AlphaIsTransparency { get; private set; }
        internal string NpotScale { get; private set; }
        internal bool AllowsAlphaSplitting { get; private set; }
        internal int AnisoLevel { get; private set; }
        internal string Compression { get; private set; }
        internal int CompressionQuality { get; private set; }
        internal bool CrunchedCompression { get; private set; }
        internal bool ForceMaximumCompressionQualityBc6hBc7 { get; private set; }
        internal int GpuBlockBytes { get; private set; }
        internal int GpuBlockHeight { get; private set; }
        internal int GpuBlockWidth { get; private set; }
        internal bool IgnorePngGamma { get; private set; }
        internal int MaxTextureSize { get; private set; }
        internal bool PlatformOverride { get; private set; }
        internal bool StreamingMipmaps { get; private set; }
        internal string TextureType { get; private set; }
        internal int UnityTextureFormat { get; private set; }

        internal bool IsExactV2()
        {
            return string.Equals(Format, "RGBA32", StringComparison.Ordinal)
                && SRgb
                && !Mipmaps
                && !Readable
                && string.Equals(FilterMode, "Point", StringComparison.Ordinal)
                && string.Equals(WrapMode, "Clamp", StringComparison.Ordinal)
                && string.Equals(AlphaSource, "FromInput", StringComparison.Ordinal)
                && !AlphaIsTransparency
                && string.Equals(NpotScale, "None", StringComparison.Ordinal);
        }

        internal bool IsExactV3(string expectedFormat, string expectedFilterMode)
        {
            bool bc7 = string.Equals(expectedFormat, "BC7", StringComparison.Ordinal);
            bool rgba32 = string.Equals(expectedFormat, "RGBA32", StringComparison.Ordinal);
            if (!bc7 && !rgba32)
            {
                return false;
            }
            return string.Equals(Format, expectedFormat, StringComparison.Ordinal)
                && SRgb
                && !Mipmaps
                && !Readable
                && string.Equals(FilterMode, expectedFilterMode, StringComparison.Ordinal)
                && (string.Equals(FilterMode, "Point", StringComparison.Ordinal)
                    || string.Equals(FilterMode, "Bilinear", StringComparison.Ordinal))
                && string.Equals(WrapMode, "Clamp", StringComparison.Ordinal)
                && string.Equals(AlphaSource, "FromInput", StringComparison.Ordinal)
                && !AlphaIsTransparency
                && string.Equals(NpotScale, "None", StringComparison.Ordinal)
                && !AllowsAlphaSplitting
                && AnisoLevel == 0
                && CompressionQuality == 100
                && !CrunchedCompression
                && IgnorePngGamma
                && MaxTextureSize == AssetStreamContract.MaximumPageDimension
                && PlatformOverride
                && !StreamingMipmaps
                && string.Equals(TextureType, "Default", StringComparison.Ordinal)
                && (bc7
                    ? string.Equals(Compression, "CompressedHQ", StringComparison.Ordinal)
                        && ForceMaximumCompressionQualityBc6hBc7
                        && GpuBlockBytes == 16
                        && GpuBlockHeight == 4
                        && GpuBlockWidth == 4
                        && UnityTextureFormat == 25
                    : string.Equals(Compression, "Uncompressed", StringComparison.Ordinal)
                        && !ForceMaximumCompressionQualityBc6hBc7
                        && GpuBlockBytes == 4
                        && GpuBlockHeight == 1
                        && GpuBlockWidth == 1
                        && UnityTextureFormat == 4);
        }
    }

    internal sealed class AssetStreamPageTexture
    {
        internal AssetStreamPageTexture(
            string assetPath,
            string address,
            string pngSha256,
            string rgbaSha256)
        {
            AssetPath = assetPath;
            Address = address;
            PngSha256 = pngSha256;
            RgbaSha256 = rgbaSha256;
            Format = "RGBA32";
            SourcePngSha256 = pngSha256;
            SourceRgbaSha256 = rgbaSha256;
        }

        internal AssetStreamPageTexture(
            string assetPath,
            string address,
            string format,
            long gpuBytes,
            long sourceRgbaBytes,
            string sourcePngSha256,
            string sourceRgbaSha256)
        {
            AssetPath = assetPath;
            Address = address;
            Format = format;
            GpuBytes = gpuBytes;
            SourceRgbaBytes = sourceRgbaBytes;
            SourcePngSha256 = sourcePngSha256;
            SourceRgbaSha256 = sourceRgbaSha256;
            PngSha256 = sourcePngSha256;
            RgbaSha256 = sourceRgbaSha256;
        }

        internal string AssetPath { get; private set; }
        internal string Address { get; private set; }
        internal string PngSha256 { get; private set; }
        internal string RgbaSha256 { get; private set; }
        internal string Format { get; private set; }
        internal long GpuBytes { get; private set; }
        internal long SourceRgbaBytes { get; private set; }
        internal string SourcePngSha256 { get; private set; }
        internal string SourceRgbaSha256 { get; private set; }
    }

    internal sealed class AssetStreamIndexPageSummary
    {
        internal AssetStreamIndexPageSummary(
            int id,
            int width,
            int height,
            string mainAddress,
            string mainRgbaSha256,
            string maskAddress,
            string maskRgbaSha256)
        {
            Id = id;
            Width = width;
            Height = height;
            MainAddress = mainAddress;
            MainRgbaSha256 = mainRgbaSha256;
            MaskAddress = maskAddress;
            MaskRgbaSha256 = maskRgbaSha256;
            MainFormat = "RGBA32";
            MainSourceRgbaSha256 = mainRgbaSha256;
            MaskFormat = maskAddress == null ? null : "RGBA32";
            MaskSourceRgbaSha256 = maskRgbaSha256;
        }

        internal AssetStreamIndexPageSummary(
            int id,
            int width,
            int height,
            string mainAddress,
            string mainFormat,
            long mainGpuBytes,
            string mainSourceRgbaSha256,
            string maskAddress,
            string maskFormat,
            long? maskGpuBytes,
            string maskSourceRgbaSha256)
        {
            Id = id;
            Width = width;
            Height = height;
            MainAddress = mainAddress;
            MainFormat = mainFormat;
            MainGpuBytes = mainGpuBytes;
            MainSourceRgbaSha256 = mainSourceRgbaSha256;
            MaskAddress = maskAddress;
            MaskFormat = maskFormat;
            MaskGpuBytes = maskGpuBytes;
            MaskSourceRgbaSha256 = maskSourceRgbaSha256;
            MainRgbaSha256 = mainSourceRgbaSha256;
            MaskRgbaSha256 = maskSourceRgbaSha256;
        }

        internal int Id { get; private set; }
        internal int Width { get; private set; }
        internal int Height { get; private set; }
        internal string MainAddress { get; private set; }
        internal string MainRgbaSha256 { get; private set; }
        internal string MaskAddress { get; private set; }
        internal string MaskRgbaSha256 { get; private set; }
        internal string MainFormat { get; private set; }
        internal long MainGpuBytes { get; private set; }
        internal string MainSourceRgbaSha256 { get; private set; }
        internal string MaskFormat { get; private set; }
        internal long? MaskGpuBytes { get; private set; }
        internal string MaskSourceRgbaSha256 { get; private set; }
    }

    internal sealed class AssetStreamAtlasPage
    {
        internal AssetStreamAtlasPage(
            int id,
            int width,
            int height,
            AssetStreamPageTexture main,
            AssetStreamPageTexture mask)
        {
            Id = id;
            Width = width;
            Height = height;
            Main = main;
            Mask = mask;
        }

        internal int Id { get; private set; }
        internal int Width { get; private set; }
        internal int Height { get; private set; }
        internal AssetStreamPageTexture Main { get; private set; }
        internal AssetStreamPageTexture Mask { get; private set; }
    }

    internal struct AssetStreamFrameRect
    {
        internal AssetStreamFrameRect(int x, int y, int width, int height)
        {
            X = x;
            Y = y;
            Width = width;
            Height = height;
        }

        internal int X { get; private set; }
        internal int Y { get; private set; }
        internal int Width { get; private set; }
        internal int Height { get; private set; }
    }

    internal struct AssetStreamFramePivot
    {
        internal AssetStreamFramePivot(double x, double y)
        {
            X = x;
            Y = y;
        }

        internal double X { get; private set; }
        internal double Y { get; private set; }
    }

    /// <summary>
    /// Sprite metadata only. Bundles contain Texture2D pages plus atlas.v2;
    /// the backend must use this record as Sprite.Create input.
    /// </summary>
    internal sealed class AssetStreamAtlasFrame
    {
        internal AssetStreamAtlasFrame(
            string name,
            int index,
            bool alt,
            int page,
            AssetStreamFrameRect rect,
            AssetStreamFramePivot pivot,
            double pixelsPerUnit,
            string mainRgbaSha256,
            string maskRgbaSha256)
        {
            Name = name;
            Index = index;
            Alt = alt;
            Page = page;
            Rect = rect;
            Pivot = pivot;
            PixelsPerUnit = pixelsPerUnit;
            MainRgbaSha256 = mainRgbaSha256;
            MaskRgbaSha256 = maskRgbaSha256;
            StorageCell = rect;
        }

        internal AssetStreamAtlasFrame(
            string name,
            int index,
            bool alt,
            int page,
            AssetStreamFrameRect rect,
            AssetStreamFrameRect storageCell,
            AssetStreamFramePivot pivot,
            double pixelsPerUnit,
            string mainSourceRgbaSha256,
            string maskSourceRgbaSha256)
            : this(
                name,
                index,
                alt,
                page,
                rect,
                pivot,
                pixelsPerUnit,
                mainSourceRgbaSha256,
                maskSourceRgbaSha256)
        {
            StorageCell = storageCell;
        }

        internal string Name { get; private set; }
        internal int Index { get; private set; }
        internal bool Alt { get; private set; }
        internal int Page { get; private set; }
        internal AssetStreamFrameRect Rect { get; private set; }
        internal AssetStreamFrameRect StorageCell { get; private set; }
        internal AssetStreamFramePivot Pivot { get; private set; }
        internal double PixelsPerUnit { get; private set; }
        internal string MainRgbaSha256 { get; private set; }
        internal string MaskRgbaSha256 { get; private set; }
        internal string MainSourceRgbaSha256 { get { return MainRgbaSha256; } }
        internal string MaskSourceRgbaSha256 { get { return MaskRgbaSha256; } }
    }

    internal sealed class AssetStreamAtlasManifest
    {
        internal AssetStreamAtlasManifest(
            string group,
            string slug,
            string bundle,
            AssetStreamMaskPolicy maskPolicy,
            string materialBinding,
            string coordinateSystem,
            int paddingPixels,
            int maxPageDimension,
            AssetStreamTextureContract textureContract,
            IList<AssetStreamAtlasPage> pages,
            IList<AssetStreamAtlasFrame> frames,
            string framesSha256,
            string contentSha256)
        {
            PipelineVersion = AssetStreamPipelineVersion.LosslessRgbaV1;
            Schema = AssetStreamContract.AtlasSchema;
            Group = group;
            Slug = slug;
            Bundle = bundle;
            MaskPolicy = maskPolicy;
            MaterialBinding = materialBinding;
            CoordinateSystem = coordinateSystem;
            PaddingPixels = paddingPixels;
            MaxPageDimension = maxPageDimension;
            TextureContract = textureContract;
            MainTextureContract = textureContract;
            MaskTextureContract = textureContract;
            Pages = new ReadOnlyCollection<AssetStreamAtlasPage>(
                new List<AssetStreamAtlasPage>(pages));
            Frames = new ReadOnlyCollection<AssetStreamAtlasFrame>(
                new List<AssetStreamAtlasFrame>(frames));
            FramesSha256 = framesSha256;
            ContentSha256 = contentSha256;
        }

        internal AssetStreamAtlasManifest(
            string group,
            string slug,
            string bundle,
            AssetStreamMaskPolicy maskPolicy,
            string materialBinding,
            string coordinateSystem,
            string extrusionMode,
            int minimumBorderPixels,
            int blockAlignmentPixels,
            int maxPageDimension,
            AssetStreamTextureContract mainTextureContract,
            AssetStreamTextureContract maskTextureContract,
            IList<AssetStreamAtlasPage> pages,
            IList<AssetStreamAtlasFrame> frames,
            string framesSha256,
            string contentSha256)
        {
            PipelineVersion = AssetStreamPipelineVersion.Bc7VisualEquivalenceV2;
            Schema = AssetStreamBc7Contract.AtlasSchema;
            Group = group;
            Slug = slug;
            Bundle = bundle;
            MaskPolicy = maskPolicy;
            MaterialBinding = materialBinding;
            CoordinateSystem = coordinateSystem;
            ExtrusionMode = extrusionMode;
            MinimumBorderPixels = minimumBorderPixels;
            PaddingPixels = minimumBorderPixels;
            BlockAlignmentPixels = blockAlignmentPixels;
            MaxPageDimension = maxPageDimension;
            TextureContract = mainTextureContract;
            MainTextureContract = mainTextureContract;
            MaskTextureContract = maskTextureContract;
            Pages = new ReadOnlyCollection<AssetStreamAtlasPage>(
                new List<AssetStreamAtlasPage>(pages));
            Frames = new ReadOnlyCollection<AssetStreamAtlasFrame>(
                new List<AssetStreamAtlasFrame>(frames));
            FramesSha256 = framesSha256;
            ContentSha256 = contentSha256;
        }

        internal string Schema { get; private set; }
        internal AssetStreamPipelineVersion PipelineVersion { get; private set; }
        internal string Group { get; private set; }
        internal string Slug { get; private set; }
        internal string Bundle { get; private set; }
        internal AssetStreamMaskPolicy MaskPolicy { get; private set; }
        internal string MaterialBinding { get; private set; }
        internal string CoordinateSystem { get; private set; }
        internal int PaddingPixels { get; private set; }
        internal string ExtrusionMode { get; private set; }
        internal int MinimumBorderPixels { get; private set; }
        internal int BlockAlignmentPixels { get; private set; }
        internal int MaxPageDimension { get; private set; }
        internal AssetStreamTextureContract TextureContract { get; private set; }
        internal AssetStreamTextureContract MainTextureContract { get; private set; }
        internal AssetStreamTextureContract MaskTextureContract { get; private set; }
        internal ReadOnlyCollection<AssetStreamAtlasPage> Pages { get; private set; }
        internal ReadOnlyCollection<AssetStreamAtlasFrame> Frames { get; private set; }
        internal string FramesSha256 { get; private set; }
        internal string ContentSha256 { get; private set; }
    }

    internal sealed class AssetStreamGroupManifest
    {
        internal AssetStreamGroupManifest(
            string group,
            string slug,
            int gmId,
            bool dashFormat,
            int arraySize,
            string bundle,
            string bundlePath,
            long bundleSizeBytes,
            string bundleSha256,
            string bundleCrc32,
            string unityHash128,
            string atlasAssetPath,
            string atlasAddress,
            string atlasSha256,
            AssetStreamMaskPolicy maskPolicy,
            string materialBinding,
            int pageCount,
            int frameCount,
            string namesSha256,
            string framesSha256,
            long rawRgbaBytes,
            long residentChargeBytes,
            long predictedLoadPeakBytes,
            IList<AssetStreamIndexPageSummary> pages)
        {
            PipelineVersion = AssetStreamPipelineVersion.LosslessRgbaV1;
            Group = group;
            Slug = slug;
            GmId = gmId;
            DashFormat = dashFormat;
            ArraySize = arraySize;
            Bundle = bundle;
            BundlePath = bundlePath;
            BundleSizeBytes = bundleSizeBytes;
            BundleSha256 = bundleSha256;
            BundleCrc32 = bundleCrc32;
            UnityHash128 = unityHash128;
            AtlasAssetPath = atlasAssetPath;
            AtlasAddress = atlasAddress;
            AtlasSha256 = atlasSha256;
            MaskPolicy = maskPolicy;
            MaterialBinding = materialBinding;
            PageCount = pageCount;
            FrameCount = frameCount;
            NamesSha256 = namesSha256;
            FramesSha256 = framesSha256;
            RawRgbaBytes = rawRgbaBytes;
            SourceRgbaBytes = rawRgbaBytes;
            ResidentChargeBytes = residentChargeBytes;
            PredictedLoadPeakBytes = predictedLoadPeakBytes;
            Pages = new ReadOnlyCollection<AssetStreamIndexPageSummary>(
                new List<AssetStreamIndexPageSummary>(pages));
        }

        internal AssetStreamGroupManifest(
            string group,
            string slug,
            int gmId,
            bool dashFormat,
            int arraySize,
            string bundle,
            string bundlePath,
            long bundleSizeBytes,
            string bundleSha256,
            string bundleCrc32,
            string unityHash128,
            string atlasAssetPath,
            string atlasAddress,
            string atlasSha256,
            AssetStreamMaskPolicy maskPolicy,
            string materialBinding,
            int pageCount,
            int frameCount,
            string namesSha256,
            string framesSha256,
            long sourceRgbaBytes,
            long gpuBytes,
            long residentChargeBytes,
            long predictedLoadPeakBytes,
            IList<AssetStreamIndexPageSummary> pages)
        {
            PipelineVersion = AssetStreamPipelineVersion.Bc7VisualEquivalenceV2;
            Group = group;
            Slug = slug;
            GmId = gmId;
            DashFormat = dashFormat;
            ArraySize = arraySize;
            Bundle = bundle;
            BundlePath = bundlePath;
            BundleSizeBytes = bundleSizeBytes;
            BundleSha256 = bundleSha256;
            BundleCrc32 = bundleCrc32;
            UnityHash128 = unityHash128;
            AtlasAssetPath = atlasAssetPath;
            AtlasAddress = atlasAddress;
            AtlasSha256 = atlasSha256;
            MaskPolicy = maskPolicy;
            MaterialBinding = materialBinding;
            PageCount = pageCount;
            FrameCount = frameCount;
            NamesSha256 = namesSha256;
            FramesSha256 = framesSha256;
            RawRgbaBytes = sourceRgbaBytes;
            SourceRgbaBytes = sourceRgbaBytes;
            GpuBytes = gpuBytes;
            ResidentChargeBytes = residentChargeBytes;
            PredictedLoadPeakBytes = predictedLoadPeakBytes;
            Pages = new ReadOnlyCollection<AssetStreamIndexPageSummary>(
                new List<AssetStreamIndexPageSummary>(pages));
        }

        internal AssetStreamPipelineVersion PipelineVersion { get; private set; }
        internal string Group { get; private set; }
        internal string Slug { get; private set; }
        internal int GmId { get; private set; }
        internal bool DashFormat { get; private set; }
        internal int ArraySize { get; private set; }
        internal string Lifetime { get { return "map"; } }
        internal string Bundle { get; private set; }
        internal string BundlePath { get; private set; }
        internal long BundleSizeBytes { get; private set; }
        internal string BundleSha256 { get; private set; }
        internal string BundleCrc32 { get; private set; }
        internal string UnityHash128 { get; private set; }
        internal string AtlasAssetPath { get; private set; }
        internal string AtlasAddress { get; private set; }
        internal string AtlasSha256 { get; private set; }
        internal AssetStreamMaskPolicy MaskPolicy { get; private set; }
        internal string MaterialBinding { get; private set; }
        internal int PageCount { get; private set; }
        internal int FrameCount { get; private set; }
        internal string NamesSha256 { get; private set; }
        internal string FramesSha256 { get; private set; }
        internal long RawRgbaBytes { get; private set; }
        internal long SourceRgbaBytes { get; private set; }
        internal long GpuBytes { get; private set; }
        internal long ResidentChargeBytes { get; private set; }
        internal long PredictedLoadPeakBytes { get; private set; }
        internal ReadOnlyCollection<AssetStreamIndexPageSummary> Pages { get; private set; }

        internal long RecalculateResidentChargeBytes()
        {
            return PipelineVersion == AssetStreamPipelineVersion.Bc7VisualEquivalenceV2
                ? AssetStreamAccounting.CalculateBc7ResidentChargeBytes(GpuBytes)
                : AssetStreamAccounting.CalculateResidentChargeBytes(RawRgbaBytes);
        }

        internal long RecalculatePeakAdmissionBytes()
        {
            return AssetStreamAccounting.CalculatePeakAdmissionBytes(
                RecalculateResidentChargeBytes(),
                BundleSizeBytes);
        }
    }

    internal sealed class AssetStreamVanillaOmittedGroup
    {
        internal AssetStreamVanillaOmittedGroup(
            string group,
            int gmId,
            string reason,
            int arraySize,
            int frameCount,
            string namesSha256,
            string framesSha256)
        {
            Group = group;
            GmId = gmId;
            Reason = reason;
            ArraySize = arraySize;
            FrameCount = frameCount;
            NamesSha256 = namesSha256;
            FramesSha256 = framesSha256;
        }

        internal string Group { get; private set; }
        internal int GmId { get; private set; }
        internal string Reason { get; private set; }
        internal int ArraySize { get; private set; }
        internal int FrameCount { get; private set; }
        internal string NamesSha256 { get; private set; }
        internal string FramesSha256 { get; private set; }
    }

    /// <summary>The external Runtime/AssetBundles/index.json document.</summary>
    internal sealed class AssetStreamManifest
    {
        private readonly Dictionary<string, AssetStreamGroupManifest> byGroup;

        internal AssetStreamManifest(
            string buildId,
            AssetStreamUnityIdentity unity,
            string buildTarget,
            int maxPageDimension,
            IList<AssetStreamGroupManifest> groups,
            IList<AssetStreamVanillaOmittedGroup> vanillaOmittedGroups,
            string contentSha256)
        {
            PipelineVersion = AssetStreamPipelineVersion.LosslessRgbaV1;
            Schema = AssetStreamContract.IndexSchema;
            BackendKind = AssetStreamContract.AtlasBackendKind;
            ResourcePolicyKind = AssetStreamContract.ResourcePolicyKind;
            BuildId = buildId;
            Unity = unity;
            BuildTarget = buildTarget;
            MaxPageDimension = maxPageDimension;
            Groups = new ReadOnlyCollection<AssetStreamGroupManifest>(
                new List<AssetStreamGroupManifest>(groups));
            VanillaOmittedGroups =
                new ReadOnlyCollection<AssetStreamVanillaOmittedGroup>(
                    new List<AssetStreamVanillaOmittedGroup>(
                        vanillaOmittedGroups));
            ContentSha256 = contentSha256;
            byGroup = new Dictionary<string, AssetStreamGroupManifest>(
                StringComparer.Ordinal);
            for (int index = 0; index < Groups.Count; index++)
            {
                byGroup.Add(Groups[index].Group, Groups[index]);
            }
        }

        internal AssetStreamManifest(
            string buildId,
            AssetStreamUnityIdentity unity,
            string buildTarget,
            int maxPageDimension,
            string backendKind,
            string resourcePolicyKind,
            string packerId,
            string encoderId,
            AssetStreamTexturePolicy texturePolicy,
            AssetStreamQualityPolicy qualityPolicy,
            string qualityReportSha256,
            long totalSourceRgbaBytes,
            long totalGpuBytes,
            long totalResidentChargeBytes,
            IList<AssetStreamGroupManifest> groups,
            IList<AssetStreamVanillaOmittedGroup> vanillaOmittedGroups,
            string contentSha256)
        {
            PipelineVersion = AssetStreamPipelineVersion.Bc7VisualEquivalenceV2;
            Schema = AssetStreamBc7Contract.IndexSchema;
            BuildId = buildId;
            Unity = unity;
            BuildTarget = buildTarget;
            MaxPageDimension = maxPageDimension;
            BackendKind = backendKind;
            ResourcePolicyKind = resourcePolicyKind;
            PackerId = packerId;
            EncoderId = encoderId;
            TexturePolicy = texturePolicy;
            QualityPolicy = qualityPolicy;
            QualityReportSha256 = qualityReportSha256;
            TotalSourceRgbaBytes = totalSourceRgbaBytes;
            TotalGpuBytes = totalGpuBytes;
            TotalResidentChargeBytes = totalResidentChargeBytes;
            Groups = new ReadOnlyCollection<AssetStreamGroupManifest>(
                new List<AssetStreamGroupManifest>(groups));
            VanillaOmittedGroups =
                new ReadOnlyCollection<AssetStreamVanillaOmittedGroup>(
                    new List<AssetStreamVanillaOmittedGroup>(vanillaOmittedGroups));
            ContentSha256 = contentSha256;
            byGroup = new Dictionary<string, AssetStreamGroupManifest>(
                StringComparer.Ordinal);
            for (int index = 0; index < Groups.Count; index++)
            {
                byGroup.Add(Groups[index].Group, Groups[index]);
            }
        }

        internal string Schema { get; private set; }
        internal AssetStreamPipelineVersion PipelineVersion { get; private set; }
        internal string BackendKind { get; private set; }
        internal string ResourcePolicyKind { get; private set; }
        internal string PackerId { get; private set; }
        internal string EncoderId { get; private set; }
        internal AssetStreamTexturePolicy TexturePolicy { get; private set; }
        internal AssetStreamQualityPolicy QualityPolicy { get; private set; }
        internal string QualityReportSha256 { get; private set; }
        internal long TotalSourceRgbaBytes { get; private set; }
        internal long TotalGpuBytes { get; private set; }
        internal long TotalResidentChargeBytes { get; private set; }
        internal string BuildId { get; private set; }
        internal AssetStreamUnityIdentity Unity { get; private set; }
        internal string BuildTarget { get; private set; }
        internal int MaxPageDimension { get; private set; }
        internal ReadOnlyCollection<AssetStreamGroupManifest> Groups { get; private set; }
        internal ReadOnlyCollection<AssetStreamVanillaOmittedGroup>
            VanillaOmittedGroups { get; private set; }
        internal string ContentSha256 { get; private set; }

        internal bool TryGetGroup(string group, out AssetStreamGroupManifest manifest)
        {
            return byGroup.TryGetValue(group, out manifest);
        }

        internal bool RequiresBc7
        {
            get
            {
                return PipelineVersion
                    == AssetStreamPipelineVersion.Bc7VisualEquivalenceV2;
            }
        }
    }

    internal static class AssetStreamManifestRules
    {
        internal static bool IsPowerOfTwoPageDimension(int value)
        {
            return value >= AssetStreamContract.MinimumPageDimension
                && value <= AssetStreamContract.MaximumPageDimension
                && (value & (value - 1)) == 0;
        }

        internal static void RequireBc7RuntimeSupport(
            bool requiresBc7,
            bool supportsBc7)
        {
            if (requiresBc7 && !supportsBc7)
            {
                throw new InvalidOperationException(
                    "BC7 Texture2D support is required by the V2 asset stream");
            }
        }

        internal static bool IsCanonicalSha256(string value)
        {
            return IsLowerHex(value, 64);
        }

        internal static bool IsCanonicalCrc32(string value)
        {
            return IsLowerHex(value, 8);
        }

        internal static bool IsCanonicalHash128(string value)
        {
            return IsLowerHex(value, 32);
        }

        internal static bool IsSafeGroup(string value)
        {
            if (string.IsNullOrEmpty(value) || !IsAsciiLetterOrDigit(value[0]))
            {
                return false;
            }
            for (int index = 1; index < value.Length; index++)
            {
                char character = value[index];
                if (character == ' ')
                {
                    if (index + 1 >= value.Length
                        || value[index - 1] == ' '
                        || !IsAsciiLetterOrDigit(value[index + 1]))
                    {
                        return false;
                    }
                    continue;
                }
                if (!IsAsciiLetterOrDigit(character)
                    && character != '.' && character != '_'
                    && character != '-')
                {
                    return false;
                }
            }
            return string.Equals(value, value.Normalize(), StringComparison.Ordinal);
        }

        internal static bool IsSafeSlug(string value)
        {
            return IsSafeGroup(value)
                && value.IndexOf(' ') < 0
                && string.Equals(
                    value,
                    value.ToLowerInvariant(),
                    StringComparison.Ordinal);
        }

        internal static string GroupSlug(string value)
        {
            if (!IsSafeGroup(value))
            {
                return string.Empty;
            }
            return value.ToLowerInvariant().Replace(' ', '_');
        }

        internal static bool IsSafeRelativePath(string value)
        {
            if (string.IsNullOrEmpty(value)
                || value[0] == '/' || value[value.Length - 1] == '/'
                || value.IndexOf('\\') >= 0 || value.IndexOf(':') >= 0
                || value.IndexOf("//", StringComparison.Ordinal) >= 0)
            {
                return false;
            }
            string[] components = value.Split('/');
            for (int index = 0; index < components.Length; index++)
            {
                if (components[index].Length == 0
                    || components[index] == "." || components[index] == "..")
                {
                    return false;
                }
            }
            return string.Equals(value, value.Normalize(), StringComparison.Ordinal);
        }

        private static bool IsLowerHex(string value, int length)
        {
            if (value == null || value.Length != length)
            {
                return false;
            }
            for (int index = 0; index < value.Length; index++)
            {
                char character = value[index];
                if (!((character >= '0' && character <= '9')
                    || (character >= 'a' && character <= 'f')))
                {
                    return false;
                }
            }
            return true;
        }

        private static bool IsAsciiLetterOrDigit(char value)
        {
            return (value >= 'a' && value <= 'z')
                || (value >= 'A' && value <= 'Z')
                || (value >= '0' && value <= '9');
        }
    }
}
