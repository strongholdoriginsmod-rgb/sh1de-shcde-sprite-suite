using System;
using System.Collections.Generic;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed class AssetStreamManifestParseException : FormatException
    {
        internal AssetStreamManifestParseException(string message) : base(message) { }
        internal AssetStreamManifestParseException(string message, Exception inner)
            : base(message, inner) { }
    }

    /// <summary>
    /// Dependency-free parser for the canonical external index and the
    /// atlas.v2 TextAsset loaded from an individual group bundle.
    /// </summary>
    internal static class AssetStreamManifestParser
    {
        private static readonly UTF8Encoding StrictUtf8 = new UTF8Encoding(false, true);

        private static readonly string[] IndexKeys =
        {
            "schema", "build_id", "unity", "build_target",
            "max_page_dimension", "groups", "vanilla_omitted_groups",
        };
        private static readonly string[] UnityKeys = { "version", "revision" };
        private static readonly string[] GroupKeys =
        {
            "group", "slug", "gm_id", "dash_format", "array_size", "lifetime",
            "bundle", "bundle_path", "bundle_size_bytes", "bundle_sha256",
            "bundle_crc32", "unity_hash128", "atlas_asset_path", "atlas_address",
            "atlas_sha256", "mask_policy", "material_binding", "page_count",
            "frame_count", "names_sha256", "frames_sha256", "raw_rgba_bytes",
            "resident_charge_bytes", "predicted_load_peak_bytes", "pages",
        };
        private static readonly string[] IndexPageKeys =
        {
            "id", "width", "height", "main_address", "main_rgba_sha256",
            "mask_address", "mask_rgba_sha256",
        };
        private static readonly string[] OmittedGroupKeys =
        {
            "group", "gm_id", "reason", "array_size", "frame_count",
            "names_sha256", "frames_sha256",
        };
        private static readonly string[] AtlasKeys =
        {
            "schema", "group", "slug", "bundle", "mask_policy",
            "material_binding", "coordinate_system", "padding_pixels",
            "max_page_dimension", "texture_contract", "pages", "frames",
            "frames_sha256",
        };
        private static readonly string[] TextureContractKeys =
        {
            "format", "s_rgb", "mipmaps", "readable", "filter_mode", "wrap_mode",
            "alpha_source", "alpha_is_transparency", "npot_scale",
        };
        private static readonly string[] AtlasPageKeys =
        {
            "id", "width", "height", "main", "mask",
        };
        private static readonly string[] PageTextureKeys =
        {
            "asset_path", "address", "png_sha256", "rgba_sha256",
        };
        private static readonly string[] FrameKeys =
        {
            "name", "index", "alt", "page", "rect", "pivot", "pixels_per_unit",
            "main_rgba_sha256", "mask_rgba_sha256",
        };
        private static readonly string[] RectKeys = { "x", "y", "width", "height" };
        private static readonly string[] PivotKeys = { "x", "y" };
        private static readonly string[] IndexV2Keys =
        {
            "backend_kind", "build_id", "build_target", "encoder_id", "groups",
            "max_page_dimension", "packer_id", "quality_policy",
            "quality_report_sha256", "schema", "texture_policy",
            "total_gpu_bytes", "total_resident_charge_bytes",
            "total_source_rgba_bytes", "unity", "vanilla_omitted_groups",
        };
        private static readonly string[] GroupV2Keys =
        {
            "array_size", "atlas_address", "atlas_asset_path", "atlas_sha256",
            "bundle", "bundle_crc32", "bundle_path", "bundle_sha256",
            "bundle_size_bytes", "dash_format", "frame_count", "frames_sha256",
            "gm_id", "gpu_bytes", "group", "lifetime", "mask_policy",
            "material_binding", "names_sha256", "page_count", "pages",
            "predicted_load_peak_bytes", "resident_charge_bytes", "slug",
            "source_rgba_bytes", "unity_hash128",
        };
        private static readonly string[] IndexPageV2Keys =
        {
            "height", "id", "main_address", "main_format", "main_gpu_bytes",
            "main_source_rgba_sha256", "mask_address", "mask_format",
            "mask_gpu_bytes", "mask_source_rgba_sha256", "width",
        };
        private static readonly string[] TexturePolicyKeys =
        {
            "id", "main_format", "mask_format",
        };
        private static readonly string[] QualityPolicyKeys =
        {
            "id", "sha256", "state", "verifier_id",
        };
        private static readonly string[] AtlasV3Keys =
        {
            "block_alignment_pixels", "bundle", "coordinate_system",
            "extrusion_mode", "frames", "frames_sha256", "group", "mask_policy",
            "material_binding", "max_page_dimension", "minimum_border_pixels",
            "pages", "schema", "slug", "texture_contracts",
        };
        private static readonly string[] TextureContractsV3Keys = { "main", "mask" };
        private static readonly string[] TextureContractV3Keys =
        {
            "allows_alpha_splitting", "alpha_is_transparency", "alpha_source",
            "aniso_level", "compression", "compression_quality",
            "crunched_compression", "filter_mode",
            "force_maximum_compression_quality_bc6h_bc7", "format",
            "gpu_block_bytes", "gpu_block_height", "gpu_block_width",
            "ignore_png_gamma", "max_texture_size", "mipmaps", "npot_scale",
            "platform_override", "readable", "s_rgb", "streaming_mipmaps",
            "texture_type", "unity_texture_format", "wrap_mode",
        };
        private static readonly string[] PageTextureV3Keys =
        {
            "address", "asset_path", "format", "gpu_bytes", "source_png_sha256",
            "source_rgba_bytes", "source_rgba_sha256",
        };
        private static readonly string[] FrameV3Keys =
        {
            "alt", "index", "main_source_rgba_sha256",
            "mask_source_rgba_sha256", "name", "page", "pivot",
            "pixels_per_unit", "rect", "storage_cell",
        };

        internal static AssetStreamManifest ParseIndex(byte[] raw)
        {
            StrictJsonValue root = ParseCanonicalFile(
                raw,
                AssetStreamContract.MaximumIndexBytes,
                "index.json");
            if (root.Kind == StrictJsonKind.Object)
            {
                StrictJsonValue schemaValue;
                if (root.ObjectValue.TryGetValue("schema", out schemaValue)
                    && schemaValue.Kind == StrictJsonKind.String
                    && string.Equals(
                        schemaValue.StringValue,
                        AssetStreamBc7Contract.IndexSchema,
                        StringComparison.Ordinal))
                {
                    return ParseIndexV2(raw, root);
                }
            }
            try
            {
                IDictionary<string, StrictJsonValue> value = Object(root, "$", IndexKeys);
                RequireEqual(
                    String(value["schema"], "$.schema"),
                    AssetStreamContract.IndexSchema,
                    "$.schema");
                string buildId = Sha256(value["build_id"], "$.build_id");
                IDictionary<string, StrictJsonValue> unityValue = Object(
                    value["unity"], "$.unity", UnityKeys);
                string version = String(unityValue["version"], "$.unity.version");
                string revision = String(unityValue["revision"], "$.unity.revision");
                RequireEqual(version, AssetStreamContract.UnityVersion, "$.unity.version");
                RequireEqual(revision, AssetStreamContract.UnityRevision, "$.unity.revision");
                string buildTarget = String(value["build_target"], "$.build_target");
                RequireEqual(
                    buildTarget,
                    AssetStreamContract.BuildTarget,
                    "$.build_target");
                int maximum = Integer(
                    value["max_page_dimension"],
                    "$.max_page_dimension",
                    1,
                    int.MaxValue);
                if (maximum != AssetStreamContract.MaximumPageDimension)
                {
                    throw Error("$.max_page_dimension", "must be exactly 4096");
                }

                IList<StrictJsonValue> rawGroups = Array(
                    value["groups"],
                    "$.groups",
                    0,
                    AssetStreamContract.MaximumGroups);
                IList<StrictJsonValue> rawOmitted = Array(
                    value["vanilla_omitted_groups"],
                    "$.vanilla_omitted_groups",
                    0,
                    AssetStreamContract.MaximumGroups);
                if (rawGroups.Count + rawOmitted.Count < 1
                    || rawGroups.Count + rawOmitted.Count
                        > AssetStreamContract.MaximumGroups)
                {
                    throw Error("$", "selected group count is outside v1 limits");
                }
                var groups = new List<AssetStreamGroupManifest>(rawGroups.Count);
                var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var slugs = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var bundles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var gmIds = new HashSet<int>();
                string previous = null;
                for (int index = 0; index < rawGroups.Count; index++)
                {
                    string path = "$.groups[" + index.ToString(CultureInfo.InvariantCulture) + "]";
                    AssetStreamGroupManifest group = ParseIndexGroup(rawGroups[index], path);
                    if (previous != null
                        && string.CompareOrdinal(previous, group.Group) >= 0)
                    {
                        throw Error("$.groups", "must be sorted by group ordinal");
                    }
                    previous = group.Group;
                    RequireUnique(names, group.Group, path + ".group");
                    RequireUnique(slugs, group.Slug, path + ".slug");
                    RequireUnique(bundles, group.Bundle, path + ".bundle");
                    RequireUnique(paths, group.BundlePath, path + ".bundle_path");
                    if (!gmIds.Add(group.GmId))
                    {
                        throw Error(path + ".gm_id", "duplicates another loader GM id");
                    }
                    groups.Add(group);
                }
                var omitted = new List<AssetStreamVanillaOmittedGroup>(
                    rawOmitted.Count);
                previous = null;
                for (int index = 0; index < rawOmitted.Count; index++)
                {
                    string path = "$.vanilla_omitted_groups["
                        + index.ToString(CultureInfo.InvariantCulture)
                        + "]";
                    AssetStreamVanillaOmittedGroup item =
                        ParseOmittedGroup(rawOmitted[index], path);
                    if (previous != null
                        && string.CompareOrdinal(previous, item.Group) >= 0)
                    {
                        throw Error(
                            "$.vanilla_omitted_groups",
                            "must be sorted by group ordinal");
                    }
                    previous = item.Group;
                    RequireUnique(names, item.Group, path + ".group");
                    if (!gmIds.Add(item.GmId))
                    {
                        throw Error(
                            path + ".gm_id",
                            "duplicates another selected GM id");
                    }
                    omitted.Add(item);
                }
                return new AssetStreamManifest(
                    buildId,
                    new AssetStreamUnityIdentity(version, revision),
                    buildTarget,
                    maximum,
                    groups,
                    omitted,
                    Hash(raw));
            }
            catch (AssetStreamManifestParseException) { throw; }
            catch (Exception exception) when (
                exception is ArgumentException || exception is OverflowException)
            {
                throw new AssetStreamManifestParseException(
                    "index.json violates its exact contract: " + exception.Message,
                    exception);
            }
        }

        private static AssetStreamManifest ParseIndexV2(
            byte[] raw,
            StrictJsonValue root)
        {
            try
            {
                IDictionary<string, StrictJsonValue> value = Object(
                    root,
                    "$",
                    IndexV2Keys);
                RequireEqual(
                    String(value["schema"], "$.schema"),
                    AssetStreamBc7Contract.IndexSchema,
                    "$.schema");
                RequireEqual(
                    String(value["backend_kind"], "$.backend_kind"),
                    AssetStreamBc7Contract.AtlasBackendKind,
                    "$.backend_kind");
                string buildId = Sha256(value["build_id"], "$.build_id");
                IDictionary<string, StrictJsonValue> unityValue = Object(
                    value["unity"],
                    "$.unity",
                    UnityKeys);
                string version = String(unityValue["version"], "$.unity.version");
                string revision = String(unityValue["revision"], "$.unity.revision");
                RequireEqual(version, AssetStreamContract.UnityVersion, "$.unity.version");
                RequireEqual(revision, AssetStreamContract.UnityRevision, "$.unity.revision");
                string buildTarget = String(value["build_target"], "$.build_target");
                RequireEqual(
                    buildTarget,
                    AssetStreamContract.BuildTarget,
                    "$.build_target");
                int maximum = Integer(
                    value["max_page_dimension"],
                    "$.max_page_dimension",
                    1,
                    int.MaxValue);
                if (maximum != AssetStreamContract.MaximumPageDimension)
                {
                    throw Error("$.max_page_dimension", "must be exactly 4096");
                }
                RequireEqual(
                    String(value["packer_id"], "$.packer_id"),
                    AssetStreamBc7Contract.PackerId,
                    "$.packer_id");
                RequireEqual(
                    String(value["encoder_id"], "$.encoder_id"),
                    AssetStreamBc7Contract.EncoderId,
                    "$.encoder_id");
                AssetStreamTexturePolicy texturePolicy = ParseTexturePolicy(
                    value["texture_policy"],
                    "$.texture_policy");
                AssetStreamQualityPolicy qualityPolicy = ParseQualityPolicy(
                    value["quality_policy"],
                    "$.quality_policy");
                string qualityReportSha = Sha256(
                    value["quality_report_sha256"],
                    "$.quality_report_sha256");

                IList<StrictJsonValue> rawGroups = Array(
                    value["groups"],
                    "$.groups",
                    1,
                    AssetStreamContract.MaximumGroups);
                IList<StrictJsonValue> rawOmitted = Array(
                    value["vanilla_omitted_groups"],
                    "$.vanilla_omitted_groups",
                    0,
                    AssetStreamContract.MaximumGroups);
                if (rawGroups.Count + rawOmitted.Count
                    > AssetStreamContract.MaximumGroups)
                {
                    throw Error("$", "selected group count is outside V2 limits");
                }
                var groups = new List<AssetStreamGroupManifest>(rawGroups.Count);
                var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var slugs = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var bundles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var gmIds = new HashSet<int>();
                string previous = null;
                long calculatedSource = 0;
                long calculatedGpu = 0;
                long calculatedCharge = 0;
                for (int index = 0; index < rawGroups.Count; index++)
                {
                    string path = "$.groups["
                        + index.ToString(CultureInfo.InvariantCulture)
                        + "]";
                    AssetStreamGroupManifest group = ParseIndexGroupV2(
                        rawGroups[index],
                        path,
                        texturePolicy);
                    if (previous != null
                        && string.CompareOrdinal(previous, group.Group) >= 0)
                    {
                        throw Error("$.groups", "must be sorted by group ordinal");
                    }
                    previous = group.Group;
                    RequireUnique(names, group.Group, path + ".group");
                    RequireUnique(slugs, group.Slug, path + ".slug");
                    RequireUnique(bundles, group.Bundle, path + ".bundle");
                    RequireUnique(paths, group.BundlePath, path + ".bundle_path");
                    if (!gmIds.Add(group.GmId))
                    {
                        throw Error(path + ".gm_id", "duplicates another loader GM id");
                    }
                    calculatedSource = checked(
                        calculatedSource + group.SourceRgbaBytes);
                    calculatedGpu = checked(calculatedGpu + group.GpuBytes);
                    calculatedCharge = checked(
                        calculatedCharge + group.ResidentChargeBytes);
                    groups.Add(group);
                }

                var omitted = new List<AssetStreamVanillaOmittedGroup>(
                    rawOmitted.Count);
                previous = null;
                for (int index = 0; index < rawOmitted.Count; index++)
                {
                    string path = "$.vanilla_omitted_groups["
                        + index.ToString(CultureInfo.InvariantCulture)
                        + "]";
                    AssetStreamVanillaOmittedGroup item = ParseOmittedGroup(
                        rawOmitted[index],
                        path);
                    if (previous != null
                        && string.CompareOrdinal(previous, item.Group) >= 0)
                    {
                        throw Error(
                            "$.vanilla_omitted_groups",
                            "must be sorted by group ordinal");
                    }
                    previous = item.Group;
                    RequireUnique(names, item.Group, path + ".group");
                    if (!gmIds.Add(item.GmId))
                    {
                        throw Error(path + ".gm_id", "duplicates another selected GM id");
                    }
                    omitted.Add(item);
                }

                long declaredSource = LongInteger(
                    value["total_source_rgba_bytes"],
                    "$.total_source_rgba_bytes",
                    1,
                    long.MaxValue);
                long declaredGpu = LongInteger(
                    value["total_gpu_bytes"],
                    "$.total_gpu_bytes",
                    1,
                    long.MaxValue);
                long declaredCharge = LongInteger(
                    value["total_resident_charge_bytes"],
                    "$.total_resident_charge_bytes",
                    1,
                    long.MaxValue);
                if (declaredCharge
                    > AssetStreamBc7Contract.MaximumTotalResidentChargeBytes)
                {
                    throw Error(
                        "$.total_resident_charge_bytes",
                        "exceeds the exact 3-GiB V4 GM resident budget");
                }
                if (declaredSource != calculatedSource
                    || declaredGpu != calculatedGpu
                    || declaredCharge != calculatedCharge)
                {
                    throw Error("$", "declared V2 byte totals do not equal group sums");
                }
                return new AssetStreamManifest(
                    buildId,
                    new AssetStreamUnityIdentity(version, revision),
                    buildTarget,
                    maximum,
                    AssetStreamBc7Contract.AtlasBackendKind,
                    AssetStreamBc7Contract.ResourcePolicyKind,
                    AssetStreamBc7Contract.PackerId,
                    AssetStreamBc7Contract.EncoderId,
                    texturePolicy,
                    qualityPolicy,
                    qualityReportSha,
                    declaredSource,
                    declaredGpu,
                    declaredCharge,
                    groups,
                    omitted,
                    Hash(raw));
            }
            catch (AssetStreamManifestParseException) { throw; }
            catch (Exception exception) when (
                exception is ArgumentException || exception is OverflowException)
            {
                throw new AssetStreamManifestParseException(
                    "index v2 violates its exact contract: " + exception.Message,
                    exception);
            }
        }

        internal static int CompareFrameNamesForContract(string left, string right)
        {
            if (left == null) throw new ArgumentNullException("left");
            if (right == null) throw new ArgumentNullException("right");
            return CompareUnicodeScalars(left, right);
        }

        private static AssetStreamTexturePolicy ParseTexturePolicy(
            StrictJsonValue raw,
            string path)
        {
            IDictionary<string, StrictJsonValue> value = Object(
                raw,
                path,
                TexturePolicyKeys);
            string id = String(value["id"], path + ".id");
            string mainFormat = String(
                value["main_format"],
                path + ".main_format");
            string maskFormat = String(
                value["mask_format"],
                path + ".mask_format");
            string expectedMask;
            if (string.Equals(
                    id,
                    AssetStreamBc7Contract.Bc7MainBc7MaskTexturePolicyId,
                    StringComparison.Ordinal))
            {
                expectedMask = "BC7";
            }
            else if (string.Equals(
                    id,
                    AssetStreamBc7Contract.Bc7MainRgba32MaskTexturePolicyId,
                    StringComparison.Ordinal))
            {
                expectedMask = "RGBA32";
            }
            else
            {
                throw Error(path + ".id", "is not an approved V2 texture policy");
            }
            if (!string.Equals(mainFormat, "BC7", StringComparison.Ordinal)
                || !string.Equals(maskFormat, expectedMask, StringComparison.Ordinal))
            {
                throw Error(path, "format pair does not match its texture policy id");
            }
            return new AssetStreamTexturePolicy(id, mainFormat, maskFormat);
        }

        private static AssetStreamQualityPolicy ParseQualityPolicy(
            StrictJsonValue raw,
            string path)
        {
            IDictionary<string, StrictJsonValue> value = Object(
                raw,
                path,
                QualityPolicyKeys);
            string state = String(value["state"], path + ".state");
            string id = String(value["id"], path + ".id");
            string sha = Sha256(value["sha256"], path + ".sha256");
            string verifier = String(value["verifier_id"], path + ".verifier_id");
            RequireEqual(
                verifier,
                AssetStreamBc7Contract.QualityVerifierId,
                path + ".verifier_id");
            if (string.Equals(
                    state,
                    AssetStreamBc7Contract.MeasurementQualityState,
                    StringComparison.Ordinal))
            {
                RequireEqual(
                    id,
                    AssetStreamBc7Contract.MeasurementQualityPolicyId,
                    path + ".id");
                RequireEqual(
                    sha,
                    AssetStreamBc7Contract.MeasurementQualityPolicySha256,
                    path + ".sha256");
            }
            else if (string.Equals(
                    state,
                    AssetStreamBc7Contract.FrozenQualityState,
                    StringComparison.Ordinal))
            {
                RequireEqual(
                    id,
                    AssetStreamBc7Contract.FrozenQualityPolicyId,
                    path + ".id");
            }
            else
            {
                throw Error(path + ".state", "is not a supported quality state");
            }
            return new AssetStreamQualityPolicy(state, id, sha, verifier);
        }

        private static AssetStreamGroupManifest ParseIndexGroupV2(
            StrictJsonValue raw,
            string path,
            AssetStreamTexturePolicy texturePolicy)
        {
            IDictionary<string, StrictJsonValue> value = Object(raw, path, GroupV2Keys);
            string group = Group(
                String(value["group"], path + ".group"),
                path + ".group");
            string slug = Slug(
                String(value["slug"], path + ".slug"),
                group,
                path + ".slug");
            int gmId = Integer(
                value["gm_id"],
                path + ".gm_id",
                0,
                AssetStreamContract.MaximumGroups - 1);
            bool dashFormat = Boolean(value["dash_format"], path + ".dash_format");
            int arraySize = Integer(
                value["array_size"],
                path + ".array_size",
                1,
                AssetStreamContract.MaximumFramesPerGroup);
            RequireEqual(
                String(value["lifetime"], path + ".lifetime"),
                "map",
                path + ".lifetime");
            string bundle = String(value["bundle"], path + ".bundle");
            RequireEqual(
                bundle,
                "sede.gm." + slug + AssetStreamBc7Contract.BundleSuffix,
                path + ".bundle");
            string bundlePath = RelativePath(
                value["bundle_path"],
                path + ".bundle_path");
            RequireEqual(
                bundlePath,
                AssetStreamContract.BundleRelativePrefix + bundle,
                path + ".bundle_path");
            long bundleSize = LongInteger(
                value["bundle_size_bytes"],
                path + ".bundle_size_bytes",
                1,
                long.MaxValue);
            string bundleSha = Sha256(
                value["bundle_sha256"],
                path + ".bundle_sha256");
            string bundleCrc = String(
                value["bundle_crc32"],
                path + ".bundle_crc32");
            if (!AssetStreamManifestRules.IsCanonicalCrc32(bundleCrc))
            {
                throw Error(path + ".bundle_crc32", "expected lowercase CRC32 hex");
            }
            string unityHash = String(
                value["unity_hash128"],
                path + ".unity_hash128");
            if (!AssetStreamManifestRules.IsCanonicalHash128(unityHash))
            {
                throw Error(path + ".unity_hash128", "expected lowercase Hash128 hex");
            }
            string atlasPath = RelativePath(
                value["atlas_asset_path"],
                path + ".atlas_asset_path");
            RequireEqual(
                atlasPath,
                "Assets/Generated/Groups/" + slug + "/"
                    + AssetStreamBc7Contract.AtlasFileName,
                path + ".atlas_asset_path");
            string atlasAddress = RelativePath(
                value["atlas_address"],
                path + ".atlas_address");
            RequireEqual(
                atlasAddress,
                "sede/gm/" + slug + "/" + AssetStreamBc7Contract.AtlasFileName,
                path + ".atlas_address");
            string atlasSha = Sha256(
                value["atlas_sha256"],
                path + ".atlas_sha256");
            AssetStreamMaskPolicy maskPolicy = MaskPolicy(
                String(value["mask_policy"], path + ".mask_policy"),
                path + ".mask_policy");
            string binding = String(
                value["material_binding"],
                path + ".material_binding");
            int pageCount = Integer(
                value["page_count"],
                path + ".page_count",
                1,
                AssetStreamContract.MaximumPagesPerGroup);
            RequireBinding(
                maskPolicy,
                slug,
                pageCount,
                binding,
                path + ".material_binding");
            int frameCount = Integer(
                value["frame_count"],
                path + ".frame_count",
                1,
                AssetStreamContract.MaximumFramesPerGroup);
            string namesSha = Sha256(
                value["names_sha256"],
                path + ".names_sha256");
            string framesSha = Sha256(
                value["frames_sha256"],
                path + ".frames_sha256");
            long sourceBytes = LongInteger(
                value["source_rgba_bytes"],
                path + ".source_rgba_bytes",
                1,
                long.MaxValue);
            long gpuBytes = LongInteger(
                value["gpu_bytes"],
                path + ".gpu_bytes",
                1,
                long.MaxValue);
            long charge = LongInteger(
                value["resident_charge_bytes"],
                path + ".resident_charge_bytes",
                1,
                long.MaxValue);
            long predictedPeak = LongInteger(
                value["predicted_load_peak_bytes"],
                path + ".predicted_load_peak_bytes",
                1,
                long.MaxValue);

            IList<StrictJsonValue> rawPages = Array(
                value["pages"],
                path + ".pages",
                pageCount,
                pageCount);
            var pages = new List<AssetStreamIndexPageSummary>(rawPages.Count);
            long calculatedSource = 0;
            long calculatedGpu = 0;
            for (int index = 0; index < rawPages.Count; index++)
            {
                string pagePath = path + ".pages["
                    + index.ToString(CultureInfo.InvariantCulture)
                    + "]";
                IDictionary<string, StrictJsonValue> page = Object(
                    rawPages[index],
                    pagePath,
                    IndexPageV2Keys);
                int id = Integer(page["id"], pagePath + ".id", 0, int.MaxValue);
                if (id != index)
                {
                    throw Error(pagePath + ".id", "pages must be contiguous from zero");
                }
                int width = PageDimension(page["width"], pagePath + ".width");
                int height = PageDimension(page["height"], pagePath + ".height");
                string mainAddress = RelativePath(
                    page["main_address"],
                    pagePath + ".main_address");
                RequireEqual(
                    mainAddress,
                    "sede/gm/" + slug + "/page/"
                        + id.ToString("000", CultureInfo.InvariantCulture)
                        + "/main",
                    pagePath + ".main_address");
                string mainFormat = String(
                    page["main_format"],
                    pagePath + ".main_format");
                RequireEqual(
                    mainFormat,
                    texturePolicy.MainFormat,
                    pagePath + ".main_format");
                long mainGpu = LongInteger(
                    page["main_gpu_bytes"],
                    pagePath + ".main_gpu_bytes",
                    1,
                    long.MaxValue);
                long expectedMainGpu = TextureGpuBytes(width, height, mainFormat);
                if (mainGpu != expectedMainGpu)
                {
                    throw Error(
                        pagePath + ".main_gpu_bytes",
                        "does not equal the exact block payload");
                }
                string mainSourceSha = Sha256(
                    page["main_source_rgba_sha256"],
                    pagePath + ".main_source_rgba_sha256");
                string maskAddress = NullableRelativePath(
                    page["mask_address"],
                    pagePath + ".mask_address");
                string maskFormat = NullableString(
                    page["mask_format"],
                    pagePath + ".mask_format");
                long? maskGpu = NullablePositiveLong(
                    page["mask_gpu_bytes"],
                    pagePath + ".mask_gpu_bytes");
                string maskSourceSha = NullableSha256(
                    page["mask_source_rgba_sha256"],
                    pagePath + ".mask_source_rgba_sha256");
                if (maskPolicy == AssetStreamMaskPolicy.Required)
                {
                    if (maskAddress == null || maskFormat == null
                        || !maskGpu.HasValue || maskSourceSha == null)
                    {
                        throw Error(pagePath + ".mask_address", "mask is required");
                    }
                    RequireEqual(
                        maskAddress,
                        "sede/gm/" + slug + "/page/"
                            + id.ToString("000", CultureInfo.InvariantCulture)
                            + "/mask",
                        pagePath + ".mask_address");
                    RequireEqual(
                        maskFormat,
                        texturePolicy.MaskFormat,
                        pagePath + ".mask_format");
                    if (maskGpu.Value != TextureGpuBytes(width, height, maskFormat))
                    {
                        throw Error(
                            pagePath + ".mask_gpu_bytes",
                            "does not equal the exact block payload");
                    }
                }
                else if (maskAddress != null || maskFormat != null
                    || maskGpu.HasValue || maskSourceSha != null)
                {
                    throw Error(pagePath + ".mask_address", "mask fields must be null");
                }
                int planes = maskPolicy == AssetStreamMaskPolicy.Required ? 2 : 1;
                calculatedSource = checked(
                    calculatedSource + checked((long)width * height * 4 * planes));
                calculatedGpu = checked(
                    calculatedGpu + mainGpu + (maskGpu.HasValue ? maskGpu.Value : 0));
                pages.Add(new AssetStreamIndexPageSummary(
                    id,
                    width,
                    height,
                    mainAddress,
                    mainFormat,
                    mainGpu,
                    mainSourceSha,
                    maskAddress,
                    maskFormat,
                    maskGpu,
                    maskSourceSha));
            }
            if (calculatedSource != sourceBytes || calculatedGpu != gpuBytes)
            {
                throw Error(path, "declared source/GPU bytes do not equal page sums");
            }
            long calculatedCharge =
                AssetStreamAccounting.CalculateBc7ResidentChargeBytes(gpuBytes);
            if (charge != calculatedCharge)
            {
                throw Error(
                    path + ".resident_charge_bytes",
                    "does not equal ceil(9/8 * GPU bytes), aligned once to 4 MiB");
            }
            long calculatedPeak = AssetStreamAccounting.CalculatePeakAdmissionBytes(
                charge,
                bundleSize);
            if (predictedPeak != calculatedPeak)
            {
                throw Error(
                    path + ".predicted_load_peak_bytes",
                    "does not equal 2*charge + align64MiB(bundle) + 256MiB");
            }
            return new AssetStreamGroupManifest(
                group,
                slug,
                gmId,
                dashFormat,
                arraySize,
                bundle,
                bundlePath,
                bundleSize,
                bundleSha,
                bundleCrc,
                unityHash,
                atlasPath,
                atlasAddress,
                atlasSha,
                maskPolicy,
                binding,
                pageCount,
                frameCount,
                namesSha,
                framesSha,
                sourceBytes,
                gpuBytes,
                charge,
                predictedPeak,
                pages);
        }

        internal static AssetStreamAtlasManifest ParseAtlasV2(
            byte[] raw,
            AssetStreamGroupManifest expectedGroup)
        {
            if (expectedGroup == null)
            {
                throw new ArgumentNullException("expectedGroup");
            }
            ValidateCanonicalFileEnvelope(
                raw,
                AssetStreamContract.MaximumAtlasBytes,
                expectedGroup.AtlasAssetPath);
            // Fail before decoding or allocating any atlas metadata. The index
            // binds the complete TextAsset, including its one LF terminator.
            string actualFileHash = Hash(raw);
            if (!string.Equals(
                actualFileHash,
                expectedGroup.AtlasSha256,
                StringComparison.Ordinal))
            {
                throw Error("$.atlas_sha256", "raw atlas TextAsset hash mismatch");
            }
            try
            {
                string actualNamesHash;
                var reader = new AtlasUtf8Reader(raw, raw.Length - 1);
                AssetStreamAtlasManifest atlas = reader.Parse(
                    actualFileHash,
                    out actualNamesHash);
                ValidateAtlasAgainstIndex(expectedGroup, atlas, actualNamesHash);
                return atlas;
            }
            catch (AssetStreamManifestParseException) { throw; }
            catch (Exception exception) when (
                exception is ArgumentException || exception is OverflowException)
            {
                throw new AssetStreamManifestParseException(
                    "atlas.v2 violates its exact contract: " + exception.Message,
                    exception);
            }
        }

        internal static AssetStreamAtlasManifest ParseAtlasV3(
            byte[] raw,
            AssetStreamGroupManifest expectedGroup)
        {
            if (expectedGroup == null)
            {
                throw new ArgumentNullException("expectedGroup");
            }
            if (expectedGroup.PipelineVersion
                != AssetStreamPipelineVersion.Bc7VisualEquivalenceV2)
            {
                throw new ArgumentException(
                    "atlas.v3 requires a V2 index group",
                    "expectedGroup");
            }
            ValidateCanonicalFileEnvelope(
                raw,
                AssetStreamContract.MaximumAtlasBytes,
                expectedGroup.AtlasAssetPath);
            string actualFileHash = Hash(raw);
            if (!string.Equals(
                    actualFileHash,
                    expectedGroup.AtlasSha256,
                    StringComparison.Ordinal))
            {
                throw Error("$.atlas_sha256", "raw atlas TextAsset hash mismatch");
            }
            try
            {
                StrictJsonValue root = ParseCanonicalFile(
                    raw,
                    AssetStreamContract.MaximumAtlasBytes,
                    expectedGroup.AtlasAssetPath);
                IDictionary<string, StrictJsonValue> value = Object(
                    root,
                    "$",
                    AtlasV3Keys);
                RequireEqual(
                    String(value["schema"], "$.schema"),
                    AssetStreamBc7Contract.AtlasSchema,
                    "$.schema");
                string group = Group(
                    String(value["group"], "$.group"),
                    "$.group");
                string slug = Slug(
                    String(value["slug"], "$.slug"),
                    group,
                    "$.slug");
                string bundle = String(value["bundle"], "$.bundle");
                RequireEqual(
                    bundle,
                    "sede.gm." + slug + AssetStreamBc7Contract.BundleSuffix,
                    "$.bundle");
                AssetStreamMaskPolicy maskPolicy = MaskPolicy(
                    String(value["mask_policy"], "$.mask_policy"),
                    "$.mask_policy");
                string binding = String(
                    value["material_binding"],
                    "$.material_binding");
                RequireEqual(
                    String(value["coordinate_system"], "$.coordinate_system"),
                    "unity_bottom_left",
                    "$.coordinate_system");
                RequireEqual(
                    String(value["extrusion_mode"], "$.extrusion_mode"),
                    AssetStreamBc7Contract.ExtrusionMode,
                    "$.extrusion_mode");
                int border = Integer(
                    value["minimum_border_pixels"],
                    "$.minimum_border_pixels",
                    1,
                    int.MaxValue);
                if (border != AssetStreamBc7Contract.MinimumBorderPixels)
                {
                    throw Error("$.minimum_border_pixels", "must be exactly 1");
                }
                int blockAlignment = Integer(
                    value["block_alignment_pixels"],
                    "$.block_alignment_pixels",
                    1,
                    int.MaxValue);
                if (blockAlignment != AssetStreamBc7Contract.BlockAlignmentPixels)
                {
                    throw Error("$.block_alignment_pixels", "must be exactly 4");
                }
                int maximum = Integer(
                    value["max_page_dimension"],
                    "$.max_page_dimension",
                    1,
                    int.MaxValue);
                if (maximum != AssetStreamContract.MaximumPageDimension)
                {
                    throw Error("$.max_page_dimension", "must be exactly 4096");
                }

                IDictionary<string, StrictJsonValue> contracts = Object(
                    value["texture_contracts"],
                    "$.texture_contracts",
                    TextureContractsV3Keys);
                string expectedMainFormat = expectedGroup.Pages[0].MainFormat;
                AssetStreamTextureContract mainContract = ParseTextureContractV3(
                    contracts["main"],
                    "$.texture_contracts.main",
                    expectedMainFormat,
                    null);
                AssetStreamTextureContract maskContract = null;
                if (maskPolicy == AssetStreamMaskPolicy.Required)
                {
                    if (contracts["mask"].Kind == StrictJsonKind.Null)
                    {
                        throw Error("$.texture_contracts.mask", "is required");
                    }
                    string expectedMaskFormat = expectedGroup.Pages[0].MaskFormat;
                    maskContract = ParseTextureContractV3(
                        contracts["mask"],
                        "$.texture_contracts.mask",
                        expectedMaskFormat,
                        "Point");
                }
                else if (contracts["mask"].Kind != StrictJsonKind.Null)
                {
                    throw Error(
                        "$.texture_contracts.mask",
                        "must be null for forbidden masks");
                }

                IList<StrictJsonValue> rawPages = Array(
                    value["pages"],
                    "$.pages",
                    1,
                    AssetStreamContract.MaximumPagesPerGroup);
                var pages = new List<AssetStreamAtlasPage>(rawPages.Count);
                var texturePaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var textureAddresses = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                for (int index = 0; index < rawPages.Count; index++)
                {
                    pages.Add(ParseAtlasPageV3(
                        rawPages[index],
                        index,
                        slug,
                        maskPolicy,
                        mainContract,
                        maskContract,
                        texturePaths,
                        textureAddresses));
                }
                RequireBinding(maskPolicy, slug, pages.Count, binding, "$.material_binding");

                IList<StrictJsonValue> rawFrames = Array(
                    value["frames"],
                    "$.frames",
                    1,
                    AssetStreamContract.MaximumFramesPerGroup);
                string framesSha = Sha256(
                    value["frames_sha256"],
                    "$.frames_sha256");
                string actualFramesSha = Hash(
                    StrictUtf8.GetBytes(CanonicalJson(value["frames"])));
                RequireEqual(actualFramesSha, framesSha, "$.frames_sha256");
                var frames = new List<AssetStreamAtlasFrame>(rawFrames.Count);
                var frameNames = new List<string>(rawFrames.Count);
                var seenNames = new HashSet<string>(StringComparer.Ordinal);
                var seenSlots = new HashSet<FrameSlot>();
                var referencedPages = new HashSet<int>();
                AssetStreamAtlasFrame previous = null;
                bool hasMain = false;
                for (int index = 0; index < rawFrames.Count; index++)
                {
                    string framePath = "$.frames["
                        + index.ToString(CultureInfo.InvariantCulture)
                        + "]";
                    AssetStreamAtlasFrame frame = ParseFrameV3(
                        rawFrames[index],
                        framePath,
                        maskPolicy);
                    if (frame.Page >= pages.Count)
                    {
                        throw Error(framePath + ".page", "references a missing page");
                    }
                    if (previous != null && CompareFrame(previous, frame) >= 0)
                    {
                        throw Error("$.frames", "must be sorted by (index, alt, name)");
                    }
                    previous = frame;
                    if (!seenNames.Add(frame.Name))
                    {
                        throw Error(framePath + ".name", "duplicates another name");
                    }
                    if (!seenSlots.Add(new FrameSlot(frame.Index, frame.Alt)))
                    {
                        throw Error(framePath, "duplicates another loader slot");
                    }
                    referencedPages.Add(frame.Page);
                    hasMain |= !frame.Alt;
                    frameNames.Add(frame.Name);
                    frames.Add(frame);
                }
                if (!hasMain)
                {
                    throw Error("$.frames", "must contain at least one main frame");
                }
                if (referencedPages.Count != pages.Count)
                {
                    throw Error("$.pages", "every page must be referenced");
                }
                ValidateStorageCellsV3(pages, frames);
                string namesSha = Hash(
                    StrictUtf8.GetBytes(CanonicalStringArray(frameNames)));
                var atlas = new AssetStreamAtlasManifest(
                    group,
                    slug,
                    bundle,
                    maskPolicy,
                    binding,
                    "unity_bottom_left",
                    AssetStreamBc7Contract.ExtrusionMode,
                    border,
                    blockAlignment,
                    maximum,
                    mainContract,
                    maskContract,
                    pages,
                    frames,
                    framesSha,
                    actualFileHash);
                ValidateAtlasV3AgainstIndex(expectedGroup, atlas, namesSha);
                return atlas;
            }
            catch (AssetStreamManifestParseException) { throw; }
            catch (Exception exception) when (
                exception is ArgumentException || exception is OverflowException)
            {
                throw new AssetStreamManifestParseException(
                    "atlas.v3 violates its exact contract: " + exception.Message,
                    exception);
            }
        }

        private static AssetStreamTextureContract ParseTextureContractV3(
            StrictJsonValue raw,
            string path,
            string expectedFormat,
            string expectedFilterMode)
        {
            IDictionary<string, StrictJsonValue> value = Object(
                raw,
                path,
                TextureContractV3Keys);
            string filter = String(value["filter_mode"], path + ".filter_mode");
            if (expectedFilterMode != null)
            {
                RequireEqual(filter, expectedFilterMode, path + ".filter_mode");
            }
            else if (!string.Equals(filter, "Point", StringComparison.Ordinal)
                && !string.Equals(filter, "Bilinear", StringComparison.Ordinal))
            {
                throw Error(path + ".filter_mode", "must be Point or Bilinear");
            }
            var result = new AssetStreamTextureContract(
                String(value["format"], path + ".format"),
                Boolean(value["s_rgb"], path + ".s_rgb"),
                Boolean(value["mipmaps"], path + ".mipmaps"),
                Boolean(value["readable"], path + ".readable"),
                filter,
                String(value["wrap_mode"], path + ".wrap_mode"),
                String(value["alpha_source"], path + ".alpha_source"),
                Boolean(
                    value["alpha_is_transparency"],
                    path + ".alpha_is_transparency"),
                String(value["npot_scale"], path + ".npot_scale"),
                Boolean(
                    value["allows_alpha_splitting"],
                    path + ".allows_alpha_splitting"),
                Integer(value["aniso_level"], path + ".aniso_level", 0, 16),
                String(value["compression"], path + ".compression"),
                Integer(
                    value["compression_quality"],
                    path + ".compression_quality",
                    0,
                    100),
                Boolean(
                    value["crunched_compression"],
                    path + ".crunched_compression"),
                Boolean(
                    value["force_maximum_compression_quality_bc6h_bc7"],
                    path + ".force_maximum_compression_quality_bc6h_bc7"),
                Integer(
                    value["gpu_block_bytes"],
                    path + ".gpu_block_bytes",
                    1,
                    int.MaxValue),
                Integer(
                    value["gpu_block_height"],
                    path + ".gpu_block_height",
                    1,
                    int.MaxValue),
                Integer(
                    value["gpu_block_width"],
                    path + ".gpu_block_width",
                    1,
                    int.MaxValue),
                Boolean(value["ignore_png_gamma"], path + ".ignore_png_gamma"),
                Integer(
                    value["max_texture_size"],
                    path + ".max_texture_size",
                    1,
                    int.MaxValue),
                Boolean(value["platform_override"], path + ".platform_override"),
                Boolean(
                    value["streaming_mipmaps"],
                    path + ".streaming_mipmaps"),
                String(value["texture_type"], path + ".texture_type"),
                Integer(
                    value["unity_texture_format"],
                    path + ".unity_texture_format",
                    0,
                    int.MaxValue));
            if (!result.IsExactV3(expectedFormat, filter))
            {
                throw Error(
                    path,
                    "does not match the exact qualified " + expectedFormat
                        + " Texture2D import contract");
            }
            return result;
        }

        private static AssetStreamAtlasPage ParseAtlasPageV3(
            StrictJsonValue raw,
            int ordinal,
            string slug,
            AssetStreamMaskPolicy maskPolicy,
            AssetStreamTextureContract mainContract,
            AssetStreamTextureContract maskContract,
            HashSet<string> paths,
            HashSet<string> addresses)
        {
            string path = "$.pages["
                + ordinal.ToString(CultureInfo.InvariantCulture)
                + "]";
            IDictionary<string, StrictJsonValue> value = Object(
                raw,
                path,
                AtlasPageKeys);
            int id = Integer(value["id"], path + ".id", 0, int.MaxValue);
            if (id != ordinal)
            {
                throw Error(path + ".id", "pages must be contiguous from zero");
            }
            int width = PageDimension(value["width"], path + ".width");
            int height = PageDimension(value["height"], path + ".height");
            AssetStreamPageTexture main = ParsePageTextureV3(
                value["main"],
                path + ".main",
                width,
                height,
                mainContract);
            RequireEqual(
                main.AssetPath,
                "Assets/Generated/Groups/" + slug + "/page-"
                    + id.ToString("000", CultureInfo.InvariantCulture)
                    + "-main.png",
                path + ".main.asset_path");
            RequireEqual(
                main.Address,
                "sede/gm/" + slug + "/page/"
                    + id.ToString("000", CultureInfo.InvariantCulture)
                    + "/main",
                path + ".main.address");
            AssetStreamPageTexture mask = null;
            if (maskPolicy == AssetStreamMaskPolicy.Required)
            {
                if (value["mask"].Kind == StrictJsonKind.Null || maskContract == null)
                {
                    throw Error(path + ".mask", "is required");
                }
                mask = ParsePageTextureV3(
                    value["mask"],
                    path + ".mask",
                    width,
                    height,
                    maskContract);
                RequireEqual(
                    mask.AssetPath,
                    "Assets/Generated/Groups/" + slug + "/page-"
                        + id.ToString("000", CultureInfo.InvariantCulture)
                        + "-mask.png",
                    path + ".mask.asset_path");
                RequireEqual(
                    mask.Address,
                    "sede/gm/" + slug + "/page/"
                        + id.ToString("000", CultureInfo.InvariantCulture)
                        + "/mask",
                    path + ".mask.address");
            }
            else if (value["mask"].Kind != StrictJsonKind.Null)
            {
                throw Error(path + ".mask", "must be null for forbidden masks");
            }
            RequireTextureUnique(main, paths, addresses, path + ".main");
            if (mask != null)
            {
                RequireTextureUnique(mask, paths, addresses, path + ".mask");
            }
            return new AssetStreamAtlasPage(id, width, height, main, mask);
        }

        private static AssetStreamPageTexture ParsePageTextureV3(
            StrictJsonValue raw,
            string path,
            int width,
            int height,
            AssetStreamTextureContract contract)
        {
            IDictionary<string, StrictJsonValue> value = Object(
                raw,
                path,
                PageTextureV3Keys);
            string format = String(value["format"], path + ".format");
            RequireEqual(format, contract.Format, path + ".format");
            long gpuBytes = LongInteger(
                value["gpu_bytes"],
                path + ".gpu_bytes",
                1,
                long.MaxValue);
            long expectedGpu = AssetStreamAccounting.CalculateTextureGpuBytes(
                width,
                height,
                contract.GpuBlockWidth,
                contract.GpuBlockHeight,
                contract.GpuBlockBytes);
            if (gpuBytes != expectedGpu)
            {
                throw Error(path + ".gpu_bytes", "does not equal the exact block payload");
            }
            long sourceBytes = LongInteger(
                value["source_rgba_bytes"],
                path + ".source_rgba_bytes",
                1,
                long.MaxValue);
            long expectedSource = checked((long)width * height * 4);
            if (sourceBytes != expectedSource)
            {
                throw Error(
                    path + ".source_rgba_bytes",
                    "does not equal width * height * 4");
            }
            return new AssetStreamPageTexture(
                RelativePath(value["asset_path"], path + ".asset_path"),
                RelativePath(value["address"], path + ".address"),
                format,
                gpuBytes,
                sourceBytes,
                Sha256(value["source_png_sha256"], path + ".source_png_sha256"),
                Sha256(value["source_rgba_sha256"], path + ".source_rgba_sha256"));
        }

        private static AssetStreamAtlasFrame ParseFrameV3(
            StrictJsonValue raw,
            string path,
            AssetStreamMaskPolicy maskPolicy)
        {
            IDictionary<string, StrictJsonValue> value = Object(
                raw,
                path,
                FrameV3Keys);
            string name = String(value["name"], path + ".name");
            if (name.Length == 0)
            {
                throw Error(path + ".name", "must not be empty");
            }
            for (int index = 0; index < name.Length; index++)
            {
                if (name[index] < 0x20)
                {
                    throw Error(path + ".name", "contains NUL/control characters");
                }
            }
            AssetStreamFrameRect rect = ParseRectV3(value["rect"], path + ".rect");
            AssetStreamFrameRect cell = ParseRectV3(
                value["storage_cell"],
                path + ".storage_cell");
            IDictionary<string, StrictJsonValue> pivotValue = Object(
                value["pivot"],
                path + ".pivot",
                PivotKeys);
            var pivot = new AssetStreamFramePivot(
                Number(
                    pivotValue["x"],
                    path + ".pivot.x",
                    -AssetStreamContract.MaximumAbsoluteSpritePivot,
                    AssetStreamContract.MaximumAbsoluteSpritePivot),
                Number(
                    pivotValue["y"],
                    path + ".pivot.y",
                    -AssetStreamContract.MaximumAbsoluteSpritePivot,
                    AssetStreamContract.MaximumAbsoluteSpritePivot));
            string maskSha = NullableSha256(
                value["mask_source_rgba_sha256"],
                path + ".mask_source_rgba_sha256");
            if (maskPolicy == AssetStreamMaskPolicy.Required && maskSha == null)
            {
                throw Error(path + ".mask_source_rgba_sha256", "is required");
            }
            if (maskPolicy == AssetStreamMaskPolicy.Forbidden && maskSha != null)
            {
                throw Error(path + ".mask_source_rgba_sha256", "must be null");
            }
            return new AssetStreamAtlasFrame(
                name,
                Integer(value["index"], path + ".index", 0, 2000000000),
                Boolean(value["alt"], path + ".alt"),
                Integer(
                    value["page"],
                    path + ".page",
                    0,
                    AssetStreamContract.MaximumPagesPerGroup - 1),
                rect,
                cell,
                pivot,
                Number(
                    value["pixels_per_unit"],
                    path + ".pixels_per_unit",
                    1.0 / 1024.0,
                    4096),
                Sha256(
                    value["main_source_rgba_sha256"],
                    path + ".main_source_rgba_sha256"),
                maskSha);
        }

        private static AssetStreamFrameRect ParseRectV3(
            StrictJsonValue raw,
            string path)
        {
            IDictionary<string, StrictJsonValue> value = Object(raw, path, RectKeys);
            return new AssetStreamFrameRect(
                Integer(value["x"], path + ".x", 0, int.MaxValue),
                Integer(value["y"], path + ".y", 0, int.MaxValue),
                Integer(value["width"], path + ".width", 1, int.MaxValue),
                Integer(value["height"], path + ".height", 1, int.MaxValue));
        }

        private static void ValidateStorageCellsV3(
            IList<AssetStreamAtlasPage> pages,
            IList<AssetStreamAtlasFrame> frames)
        {
            const int BucketSize = 64;
            int alignment = AssetStreamBc7Contract.BlockAlignmentPixels;
            int border = AssetStreamBc7Contract.MinimumBorderPixels;
            var buckets = new Dictionary<RectBucket, List<int>>();
            var representatives = new Dictionary<RectIdentity, int>();
            for (int number = 0; number < frames.Count; number++)
            {
                AssetStreamAtlasFrame frame = frames[number];
                AssetStreamFrameRect rect = frame.Rect;
                AssetStreamFrameRect cell = frame.StorageCell;
                string path = "$.frames["
                    + number.ToString(CultureInfo.InvariantCulture)
                    + "].storage_cell";
                if (cell.X % alignment != 0 || cell.Y % alignment != 0
                    || cell.Width % alignment != 0
                    || cell.Height % alignment != 0)
                {
                    throw Error(
                        path,
                        "origin and dimensions must align to the 4x4 BC7 block grid");
                }
                int expectedWidth = checked((int)AssetStreamAccounting.AlignUp(
                    checked((long)rect.Width + 2 * border),
                    alignment));
                int expectedHeight = checked((int)AssetStreamAccounting.AlignUp(
                    checked((long)rect.Height + 2 * border),
                    alignment));
                if (rect.X != checked(cell.X + border)
                    || rect.Y != checked(
                        cell.Y + cell.Height - rect.Height - border)
                    || cell.Width != expectedWidth
                    || cell.Height != expectedHeight)
                {
                    throw Error(
                        path,
                        "must be the minimal block-aligned cell with a 1px content-origin border");
                }
                AssetStreamAtlasPage page = pages[frame.Page];
                if (checked((long)cell.X + cell.Width) > page.Width
                    || checked((long)cell.Y + cell.Height) > page.Height)
                {
                    throw Error(path, "escapes its page");
                }
                var identity = new RectIdentity(
                    frame.Page,
                    cell.X,
                    cell.Y,
                    cell.Width,
                    cell.Height);
                int representative;
                if (representatives.TryGetValue(identity, out representative))
                {
                    AssetStreamAtlasFrame other = frames[representative];
                    if (!SameRect(frame.Rect, other.Rect)
                        || !string.Equals(
                            frame.MainSourceRgbaSha256,
                            other.MainSourceRgbaSha256,
                            StringComparison.Ordinal)
                        || !string.Equals(
                            frame.MaskSourceRgbaSha256,
                            other.MaskSourceRgbaSha256,
                            StringComparison.Ordinal))
                    {
                        throw Error(
                            path,
                            "shared cell requires identical rect and source digests");
                    }
                    continue;
                }
                int x0 = cell.X / BucketSize;
                int x1 = checked((cell.X + cell.Width - 1) / BucketSize);
                int y0 = cell.Y / BucketSize;
                int y1 = checked((cell.Y + cell.Height - 1) / BucketSize);
                var candidates = new HashSet<int>();
                for (int x = x0; x <= x1; x++)
                {
                    for (int y = y0; y <= y1; y++)
                    {
                        List<int> values;
                        if (buckets.TryGetValue(
                                new RectBucket(frame.Page, x, y),
                                out values))
                        {
                            for (int index = 0; index < values.Count; index++)
                            {
                                candidates.Add(values[index]);
                            }
                        }
                    }
                }
                foreach (int candidate in candidates)
                {
                    if (RectanglesOverlap(cell, frames[candidate].StorageCell))
                    {
                        throw Error(path, "shares one or more GPU blocks with another cell");
                    }
                }
                for (int x = x0; x <= x1; x++)
                {
                    for (int y = y0; y <= y1; y++)
                    {
                        var key = new RectBucket(frame.Page, x, y);
                        List<int> values;
                        if (!buckets.TryGetValue(key, out values))
                        {
                            values = new List<int>();
                            buckets.Add(key, values);
                        }
                        values.Add(number);
                    }
                }
                representatives.Add(identity, number);
            }
        }

        private static bool SameRect(
            AssetStreamFrameRect left,
            AssetStreamFrameRect right)
        {
            return left.X == right.X && left.Y == right.Y
                && left.Width == right.Width && left.Height == right.Height;
        }

        private static bool RectanglesOverlap(
            AssetStreamFrameRect left,
            AssetStreamFrameRect right)
        {
            return !(
                checked((long)left.X + left.Width) <= right.X
                || checked((long)right.X + right.Width) <= left.X
                || checked((long)left.Y + left.Height) <= right.Y
                || checked((long)right.Y + right.Height) <= left.Y);
        }

        private static AssetStreamGroupManifest ParseIndexGroup(
            StrictJsonValue raw,
            string path)
        {
            IDictionary<string, StrictJsonValue> value = Object(raw, path, GroupKeys);
            string group = Group(String(value["group"], path + ".group"), path + ".group");
            string slug = Slug(String(value["slug"], path + ".slug"), group, path + ".slug");
            int gmId = Integer(
                value["gm_id"],
                path + ".gm_id",
                0,
                AssetStreamContract.MaximumGroups - 1);
            bool dashFormat = Boolean(value["dash_format"], path + ".dash_format");
            int arraySize = Integer(
                value["array_size"], path + ".array_size",
                1, AssetStreamContract.MaximumFramesPerGroup);
            RequireEqual(String(value["lifetime"], path + ".lifetime"), "map", path + ".lifetime");
            string bundle = String(value["bundle"], path + ".bundle");
            RequireEqual(bundle, "sede.gm." + slug + ".v2", path + ".bundle");
            string bundlePath = RelativePath(value["bundle_path"], path + ".bundle_path");
            RequireEqual(
                bundlePath,
                AssetStreamContract.BundleRelativePrefix + bundle,
                path + ".bundle_path");
            long bundleSize = LongInteger(
                value["bundle_size_bytes"], path + ".bundle_size_bytes", 1, long.MaxValue);
            string bundleSha = Sha256(value["bundle_sha256"], path + ".bundle_sha256");
            string bundleCrc = String(value["bundle_crc32"], path + ".bundle_crc32");
            if (!AssetStreamManifestRules.IsCanonicalCrc32(bundleCrc))
            {
                throw Error(path + ".bundle_crc32", "expected lowercase CRC32 hex");
            }
            string unityHash = String(value["unity_hash128"], path + ".unity_hash128");
            if (!AssetStreamManifestRules.IsCanonicalHash128(unityHash))
            {
                throw Error(path + ".unity_hash128", "expected lowercase Hash128 hex");
            }
            string atlasPath = RelativePath(value["atlas_asset_path"], path + ".atlas_asset_path");
            RequireEqual(
                atlasPath,
                "Assets/Generated/Groups/" + slug + "/atlas.v2.json",
                path + ".atlas_asset_path");
            string atlasAddress = RelativePath(value["atlas_address"], path + ".atlas_address");
            RequireEqual(
                atlasAddress,
                "sede/gm/" + slug + "/atlas.v2.json",
                path + ".atlas_address");
            string atlasSha = Sha256(value["atlas_sha256"], path + ".atlas_sha256");
            AssetStreamMaskPolicy maskPolicy = MaskPolicy(
                String(value["mask_policy"], path + ".mask_policy"),
                path + ".mask_policy");
            string binding = String(value["material_binding"], path + ".material_binding");
            int pageCount = Integer(
                value["page_count"], path + ".page_count",
                1, AssetStreamContract.MaximumPagesPerGroup);
            RequireBinding(
                maskPolicy,
                slug,
                pageCount,
                binding,
                path + ".material_binding");
            int frameCount = Integer(
                value["frame_count"], path + ".frame_count",
                1, AssetStreamContract.MaximumFramesPerGroup);
            string namesSha = Sha256(value["names_sha256"], path + ".names_sha256");
            string framesSha = Sha256(value["frames_sha256"], path + ".frames_sha256");
            long rawBytes = LongInteger(
                value["raw_rgba_bytes"], path + ".raw_rgba_bytes", 1, long.MaxValue);
            long charge = LongInteger(
                value["resident_charge_bytes"], path + ".resident_charge_bytes",
                1, long.MaxValue);
            long predictedLoadPeak = LongInteger(
                value["predicted_load_peak_bytes"],
                path + ".predicted_load_peak_bytes",
                1,
                long.MaxValue);

            IList<StrictJsonValue> rawPages = Array(
                value["pages"], path + ".pages", pageCount, pageCount);
            var pages = new List<AssetStreamIndexPageSummary>(rawPages.Count);
            long calculatedRaw = 0;
            for (int index = 0; index < rawPages.Count; index++)
            {
                string pagePath = path + ".pages[" + index.ToString(CultureInfo.InvariantCulture) + "]";
                IDictionary<string, StrictJsonValue> page = Object(
                    rawPages[index], pagePath, IndexPageKeys);
                int id = Integer(page["id"], pagePath + ".id", 0, int.MaxValue);
                if (id != index)
                {
                    throw Error(pagePath + ".id", "pages must be contiguous from zero");
                }
                int width = PageDimension(page["width"], pagePath + ".width");
                int height = PageDimension(page["height"], pagePath + ".height");
                string mainAddress = RelativePath(page["main_address"], pagePath + ".main_address");
                RequireEqual(
                    mainAddress,
                    "sede/gm/" + slug + "/page/" + id.ToString("000", CultureInfo.InvariantCulture) + "/main",
                    pagePath + ".main_address");
                string mainSha = Sha256(page["main_rgba_sha256"], pagePath + ".main_rgba_sha256");
                string maskAddress = NullableRelativePath(page["mask_address"], pagePath + ".mask_address");
                string maskSha = NullableSha256(page["mask_rgba_sha256"], pagePath + ".mask_rgba_sha256");
                if (maskPolicy == AssetStreamMaskPolicy.Required)
                {
                    if (maskAddress == null || maskSha == null)
                    {
                        throw Error(pagePath + ".mask_address", "mask is required");
                    }
                    RequireEqual(
                        maskAddress,
                        "sede/gm/" + slug + "/page/" + id.ToString("000", CultureInfo.InvariantCulture) + "/mask",
                        pagePath + ".mask_address");
                }
                else if (maskAddress != null || maskSha != null)
                {
                    throw Error(pagePath + ".mask_address", "mask must be null");
                }
                int planes = maskPolicy == AssetStreamMaskPolicy.Required ? 2 : 1;
                calculatedRaw = checked(calculatedRaw + checked((long)width * height * 4 * planes));
                pages.Add(new AssetStreamIndexPageSummary(
                    id, width, height, mainAddress, mainSha, maskAddress, maskSha));
            }
            if (calculatedRaw != rawBytes)
            {
                throw Error(path + ".raw_rgba_bytes", "does not equal page RGBA bytes");
            }
            long calculatedCharge = AssetStreamAccounting.CalculateResidentChargeBytes(rawBytes);
            if (charge != calculatedCharge)
            {
                throw Error(
                    path + ".resident_charge_bytes",
                    "does not equal the exact 9/8-aligned charge");
            }
            long calculatedLoadPeak = AssetStreamAccounting.CalculatePeakAdmissionBytes(
                charge,
                bundleSize);
            if (predictedLoadPeak != calculatedLoadPeak)
            {
                throw Error(
                    path + ".predicted_load_peak_bytes",
                    "does not equal 2 * resident charge + the 64-MiB-aligned bundle size + 256 MiB");
            }
            return new AssetStreamGroupManifest(
                group, slug, gmId, dashFormat, arraySize, bundle, bundlePath,
                bundleSize, bundleSha, bundleCrc, unityHash, atlasPath, atlasAddress,
                atlasSha, maskPolicy, binding, pageCount, frameCount, namesSha,
                framesSha, rawBytes, charge, predictedLoadPeak, pages);
        }

        private static AssetStreamVanillaOmittedGroup ParseOmittedGroup(
            StrictJsonValue raw,
            string path)
        {
            IDictionary<string, StrictJsonValue> value = Object(
                raw,
                path,
                OmittedGroupKeys);
            string group = Group(
                String(value["group"], path + ".group"),
                path + ".group");
            int gmId = Integer(
                value["gm_id"],
                path + ".gm_id",
                0,
                AssetStreamContract.MaximumGroups - 1);
            string reason = String(value["reason"], path + ".reason");
            bool knownReason = reason == "v1_frame_count_exceeded"
                || reason == "v1_slot_count_exceeded"
                || reason == "v1_frame_dimension_exceeded"
                || reason == "v1_page_count_exceeded"
                || reason == "v1_foliage_multipage";
            if (!knownReason)
            {
                throw Error(path + ".reason", "is not a canonical v1 reason");
            }
            int arraySize = Integer(
                value["array_size"], path + ".array_size", 1, int.MaxValue);
            int frameCount = Integer(
                value["frame_count"],
                path + ".frame_count",
                1,
                AssetStreamContract.MaximumPreflightFramesPerGroup);
            if (reason == "v1_frame_count_exceeded")
            {
                if (frameCount <= AssetStreamContract.MaximumFramesPerGroup)
                    throw Error(path + ".reason", "is not justified by frame_count");
            }
            else if (reason == "v1_slot_count_exceeded")
            {
                if (frameCount > AssetStreamContract.MaximumFramesPerGroup
                    || arraySize <= AssetStreamContract.MaximumFramesPerGroup)
                    throw Error(path + ".reason", "contradicts bound precedence");
            }
            else if (frameCount > AssetStreamContract.MaximumFramesPerGroup
                || arraySize > AssetStreamContract.MaximumFramesPerGroup)
            {
                throw Error(path + ".reason", "contradicts bound precedence");
            }
            return new AssetStreamVanillaOmittedGroup(
                group,
                gmId,
                reason,
                arraySize,
                frameCount,
                Sha256(value["names_sha256"], path + ".names_sha256"),
                Sha256(value["frames_sha256"], path + ".frames_sha256"));
        }

        private static AssetStreamAtlasPage ParseAtlasPage(
            StrictJsonValue raw,
            int ordinal,
            string slug,
            AssetStreamMaskPolicy maskPolicy,
            HashSet<string> paths,
            HashSet<string> addresses)
        {
            string path = "$.pages[" + ordinal.ToString(CultureInfo.InvariantCulture) + "]";
            IDictionary<string, StrictJsonValue> value = Object(raw, path, AtlasPageKeys);
            int id = Integer(value["id"], path + ".id", 0, int.MaxValue);
            if (id != ordinal)
            {
                throw Error(path + ".id", "pages must be contiguous from zero");
            }
            int width = PageDimension(value["width"], path + ".width");
            int height = PageDimension(value["height"], path + ".height");
            AssetStreamPageTexture main = ParsePageTexture(value["main"], path + ".main");
            RequireEqual(
                main.AssetPath,
                "Assets/Generated/Groups/" + slug + "/page-" + id.ToString("000", CultureInfo.InvariantCulture) + "-main.png",
                path + ".main.asset_path");
            RequireEqual(
                main.Address,
                "sede/gm/" + slug + "/page/" + id.ToString("000", CultureInfo.InvariantCulture) + "/main",
                path + ".main.address");
            AssetStreamPageTexture mask = null;
            if (maskPolicy == AssetStreamMaskPolicy.Required)
            {
                if (value["mask"].Kind == StrictJsonKind.Null)
                {
                    throw Error(path + ".mask", "is required");
                }
                mask = ParsePageTexture(value["mask"], path + ".mask");
                RequireEqual(
                    mask.AssetPath,
                    "Assets/Generated/Groups/" + slug + "/page-" + id.ToString("000", CultureInfo.InvariantCulture) + "-mask.png",
                    path + ".mask.asset_path");
                RequireEqual(
                    mask.Address,
                    "sede/gm/" + slug + "/page/" + id.ToString("000", CultureInfo.InvariantCulture) + "/mask",
                    path + ".mask.address");
            }
            else if (value["mask"].Kind != StrictJsonKind.Null)
            {
                throw Error(path + ".mask", "must be null for forbidden masks");
            }
            RequireTextureUnique(main, paths, addresses, path + ".main");
            if (mask != null)
            {
                RequireTextureUnique(mask, paths, addresses, path + ".mask");
            }
            return new AssetStreamAtlasPage(id, width, height, main, mask);
        }

        private static AssetStreamPageTexture ParsePageTexture(
            StrictJsonValue raw,
            string path)
        {
            IDictionary<string, StrictJsonValue> value = Object(raw, path, PageTextureKeys);
            return new AssetStreamPageTexture(
                RelativePath(value["asset_path"], path + ".asset_path"),
                RelativePath(value["address"], path + ".address"),
                Sha256(value["png_sha256"], path + ".png_sha256"),
                Sha256(value["rgba_sha256"], path + ".rgba_sha256"));
        }

        private static AssetStreamTextureContract ParseTextureContract(
            StrictJsonValue raw,
            string path)
        {
            IDictionary<string, StrictJsonValue> value = Object(raw, path, TextureContractKeys);
            var result = new AssetStreamTextureContract(
                String(value["format"], path + ".format"),
                Boolean(value["s_rgb"], path + ".s_rgb"),
                Boolean(value["mipmaps"], path + ".mipmaps"),
                Boolean(value["readable"], path + ".readable"),
                String(value["filter_mode"], path + ".filter_mode"),
                String(value["wrap_mode"], path + ".wrap_mode"),
                String(value["alpha_source"], path + ".alpha_source"),
                Boolean(value["alpha_is_transparency"], path + ".alpha_is_transparency"),
                String(value["npot_scale"], path + ".npot_scale"));
            if (!result.IsExactV2())
            {
                throw Error(path, "does not match the exact lossless Texture2D contract");
            }
            return result;
        }

        private static AssetStreamAtlasFrame ParseFrame(
            StrictJsonValue raw,
            string path,
            AssetStreamMaskPolicy maskPolicy)
        {
            IDictionary<string, StrictJsonValue> value = Object(raw, path, FrameKeys);
            string name = String(value["name"], path + ".name");
            if (name.Length == 0)
            {
                throw Error(path + ".name", "must not be empty");
            }
            for (int nameIndex = 0; nameIndex < name.Length; nameIndex++)
            {
                if (name[nameIndex] < 0x20)
                {
                    throw Error(path + ".name", "contains NUL/control characters");
                }
            }
            IDictionary<string, StrictJsonValue> rectValue = Object(
                value["rect"], path + ".rect", RectKeys);
            var rect = new AssetStreamFrameRect(
                Integer(rectValue["x"], path + ".rect.x", int.MinValue, int.MaxValue),
                Integer(rectValue["y"], path + ".rect.y", int.MinValue, int.MaxValue),
                Integer(rectValue["width"], path + ".rect.width", 1, int.MaxValue),
                Integer(rectValue["height"], path + ".rect.height", 1, int.MaxValue));
            IDictionary<string, StrictJsonValue> pivotValue = Object(
                value["pivot"], path + ".pivot", PivotKeys);
            var pivot = new AssetStreamFramePivot(
                Number(
                    pivotValue["x"],
                    path + ".pivot.x",
                    -AssetStreamContract.MaximumAbsoluteSpritePivot,
                    AssetStreamContract.MaximumAbsoluteSpritePivot),
                Number(
                    pivotValue["y"],
                    path + ".pivot.y",
                    -AssetStreamContract.MaximumAbsoluteSpritePivot,
                    AssetStreamContract.MaximumAbsoluteSpritePivot));
            string maskSha = NullableSha256(
                value["mask_rgba_sha256"], path + ".mask_rgba_sha256");
            if (maskPolicy == AssetStreamMaskPolicy.Required && maskSha == null)
            {
                throw Error(path + ".mask_rgba_sha256", "is required");
            }
            if (maskPolicy == AssetStreamMaskPolicy.Forbidden && maskSha != null)
            {
                throw Error(path + ".mask_rgba_sha256", "must be null");
            }
            return new AssetStreamAtlasFrame(
                name,
                Integer(value["index"], path + ".index", 0, 2000000000),
                Boolean(value["alt"], path + ".alt"),
                Integer(value["page"], path + ".page", 0, AssetStreamContract.MaximumPagesPerGroup - 1),
                rect,
                pivot,
                Number(value["pixels_per_unit"], path + ".pixels_per_unit", 1.0 / 1024.0, 4096),
                Sha256(value["main_rgba_sha256"], path + ".main_rgba_sha256"),
                maskSha);
        }

        private static void ValidateAtlasV3AgainstIndex(
            AssetStreamGroupManifest group,
            AssetStreamAtlasManifest atlas,
            string actualNamesHash)
        {
            RequireEqual(atlas.Group, group.Group, "$.group");
            RequireEqual(atlas.Slug, group.Slug, "$.slug");
            RequireEqual(atlas.Bundle, group.Bundle, "$.bundle");
            if (atlas.MaskPolicy != group.MaskPolicy)
            {
                throw Error("$.mask_policy", "differs from external index");
            }
            RequireEqual(
                atlas.MaterialBinding,
                group.MaterialBinding,
                "$.material_binding");
            if (atlas.Pages.Count != group.PageCount
                || atlas.Frames.Count != group.FrameCount)
            {
                throw Error("$", "page/frame count differs from external index");
            }
            RequireEqual(atlas.FramesSha256, group.FramesSha256, "$.frames_sha256");
            long source = 0;
            long gpu = 0;
            for (int index = 0; index < atlas.Pages.Count; index++)
            {
                AssetStreamAtlasPage page = atlas.Pages[index];
                source = checked(source + page.Main.SourceRgbaBytes);
                gpu = checked(gpu + page.Main.GpuBytes);
                if (page.Mask != null)
                {
                    source = checked(source + page.Mask.SourceRgbaBytes);
                    gpu = checked(gpu + page.Mask.GpuBytes);
                }
                AssetStreamIndexPageSummary summary = group.Pages[index];
                if (summary.Id != page.Id
                    || summary.Width != page.Width
                    || summary.Height != page.Height
                    || !string.Equals(
                        summary.MainAddress,
                        page.Main.Address,
                        StringComparison.Ordinal)
                    || !string.Equals(
                        summary.MainFormat,
                        page.Main.Format,
                        StringComparison.Ordinal)
                    || summary.MainGpuBytes != page.Main.GpuBytes
                    || !string.Equals(
                        summary.MainSourceRgbaSha256,
                        page.Main.SourceRgbaSha256,
                        StringComparison.Ordinal)
                    || !string.Equals(
                        summary.MaskAddress,
                        page.Mask == null ? null : page.Mask.Address,
                        StringComparison.Ordinal)
                    || !string.Equals(
                        summary.MaskFormat,
                        page.Mask == null ? null : page.Mask.Format,
                        StringComparison.Ordinal)
                    || summary.MaskGpuBytes
                        != (page.Mask == null ? (long?)null : page.Mask.GpuBytes)
                    || !string.Equals(
                        summary.MaskSourceRgbaSha256,
                        page.Mask == null ? null : page.Mask.SourceRgbaSha256,
                        StringComparison.Ordinal))
                {
                    throw Error(
                        "$.pages[" + index.ToString(CultureInfo.InvariantCulture) + "]",
                        "differs from external index summary");
                }
            }
            if (source != group.SourceRgbaBytes || gpu != group.GpuBytes
                || AssetStreamAccounting.CalculateBc7ResidentChargeBytes(gpu)
                    != group.ResidentChargeBytes)
            {
                throw Error(
                    "$.pages",
                    "source/GPU bytes or resident charge differs from index");
            }
            for (int index = 0; index < atlas.Frames.Count; index++)
            {
                if (atlas.Frames[index].Index >= group.ArraySize)
                {
                    throw Error("$.frames", "frame index is outside array_size");
                }
            }
            RequireEqual(actualNamesHash, group.NamesSha256, "$.frames.names_sha256");
        }

        private static void ValidateAtlasAgainstIndex(
            AssetStreamGroupManifest group,
            AssetStreamAtlasManifest atlas,
            string actualNamesHash)
        {
            RequireEqual(atlas.Group, group.Group, "$.group");
            RequireEqual(atlas.Slug, group.Slug, "$.slug");
            RequireEqual(atlas.Bundle, group.Bundle, "$.bundle");
            if (atlas.MaskPolicy != group.MaskPolicy)
            {
                throw Error("$.mask_policy", "differs from external index");
            }
            RequireEqual(atlas.MaterialBinding, group.MaterialBinding, "$.material_binding");
            if (atlas.Pages.Count != group.PageCount || atlas.Frames.Count != group.FrameCount)
            {
                throw Error("$", "page/frame count differs from external index");
            }
            RequireEqual(atlas.FramesSha256, group.FramesSha256, "$.frames_sha256");
            long raw = 0;
            for (int index = 0; index < atlas.Pages.Count; index++)
            {
                AssetStreamAtlasPage page = atlas.Pages[index];
                int planes = page.Mask == null ? 1 : 2;
                raw = checked(raw + checked((long)page.Width * page.Height * 4 * planes));
                AssetStreamIndexPageSummary summary = group.Pages[index];
                if (summary.Id != page.Id || summary.Width != page.Width
                    || summary.Height != page.Height
                    || !string.Equals(summary.MainAddress, page.Main.Address, StringComparison.Ordinal)
                    || !string.Equals(summary.MainRgbaSha256, page.Main.RgbaSha256, StringComparison.Ordinal)
                    || !string.Equals(summary.MaskAddress, page.Mask == null ? null : page.Mask.Address, StringComparison.Ordinal)
                    || !string.Equals(summary.MaskRgbaSha256, page.Mask == null ? null : page.Mask.RgbaSha256, StringComparison.Ordinal))
                {
                    throw Error("$.pages[" + index.ToString(CultureInfo.InvariantCulture) + "]", "differs from external index summary");
                }
            }
            if (raw != group.RawRgbaBytes
                || AssetStreamAccounting.CalculateResidentChargeBytes(raw)
                    != group.ResidentChargeBytes)
            {
                throw Error("$.pages", "raw bytes or resident charge differs from index");
            }
            for (int index = 0; index < atlas.Frames.Count; index++)
            {
                if (atlas.Frames[index].Index >= group.ArraySize)
                {
                    throw Error("$.frames", "frame index is outside array_size");
                }
            }
            RequireEqual(actualNamesHash, group.NamesSha256, "$.frames.names_sha256");
        }

        private static void ValidateRectangles(
            IList<AssetStreamAtlasPage> pages,
            IList<AssetStreamAtlasFrame> frames,
            int padding)
        {
            const int BucketSize = 64;
            var buckets = new Dictionary<RectBucket, List<int>>();
            var representatives = new Dictionary<RectIdentity, int>();
            for (int number = 0; number < frames.Count; number++)
            {
                AssetStreamAtlasFrame frame = frames[number];
                AssetStreamAtlasPage page = pages[frame.Page];
                AssetStreamFrameRect rect = frame.Rect;
                long px = (long)rect.X - padding;
                long py = (long)rect.Y - padding;
                long pw = (long)rect.Width + 2 * padding;
                long ph = (long)rect.Height + 2 * padding;
                if (px < 0 || py < 0 || px + pw > page.Width || py + ph > page.Height)
                {
                    throw Error("$.frames[" + number.ToString(CultureInfo.InvariantCulture) + "].rect", "escapes its page after one-pixel padding");
                }
                var identity = new RectIdentity(
                    frame.Page, rect.X, rect.Y, rect.Width, rect.Height);
                int representative;
                if (representatives.TryGetValue(identity, out representative))
                {
                    AssetStreamAtlasFrame other = frames[representative];
                    if (!string.Equals(frame.MainRgbaSha256, other.MainRgbaSha256, StringComparison.Ordinal)
                        || !string.Equals(frame.MaskRgbaSha256, other.MaskRgbaSha256, StringComparison.Ordinal))
                    {
                        throw Error("$.frames[" + number.ToString(CultureInfo.InvariantCulture) + "].rect", "shared rectangle has different RGBA digests");
                    }
                    continue;
                }
                int x0 = checked((int)(px / BucketSize));
                int x1 = checked((int)((px + pw - 1) / BucketSize));
                int y0 = checked((int)(py / BucketSize));
                int y1 = checked((int)((py + ph - 1) / BucketSize));
                var candidates = new HashSet<int>();
                for (int x = x0; x <= x1; x++)
                {
                    for (int y = y0; y <= y1; y++)
                    {
                        List<int> values;
                        if (buckets.TryGetValue(new RectBucket(frame.Page, x, y), out values))
                        {
                            for (int index = 0; index < values.Count; index++)
                            {
                                candidates.Add(values[index]);
                            }
                        }
                    }
                }
                foreach (int candidate in candidates)
                {
                    AssetStreamFrameRect other = frames[candidate].Rect;
                    long ox = (long)other.X - padding;
                    long oy = (long)other.Y - padding;
                    long ow = (long)other.Width + 2 * padding;
                    long oh = (long)other.Height + 2 * padding;
                    if (!(px + pw <= ox || ox + ow <= px || py + ph <= oy || oy + oh <= py))
                    {
                        throw Error("$.frames[" + number.ToString(CultureInfo.InvariantCulture) + "].rect", "overlaps another padded allocation");
                    }
                }
                for (int x = x0; x <= x1; x++)
                {
                    for (int y = y0; y <= y1; y++)
                    {
                        var key = new RectBucket(frame.Page, x, y);
                        List<int> values;
                        if (!buckets.TryGetValue(key, out values))
                        {
                            values = new List<int>();
                            buckets.Add(key, values);
                        }
                        values.Add(number);
                    }
                }
                representatives.Add(identity, number);
            }
        }

        private static StrictJsonValue ParseCanonicalFile(byte[] raw, int maximum, string label)
        {
            ValidateCanonicalFileEnvelope(raw, maximum, label);
            string body;
            try { body = StrictUtf8.GetString(raw, 0, raw.Length - 1); }
            catch (DecoderFallbackException exception)
            {
                throw new AssetStreamManifestParseException(label + ": invalid UTF-8", exception);
            }
            StrictJsonValue root = new StrictJsonReader(body).ParseDocument();
            EnsureNfc(root, label);
            if (!string.Equals(CanonicalJson(root), body, StringComparison.Ordinal))
                throw Error(label, "bytes are not canonical compact sorted-key JSON");
            return root;
        }

        private static void ValidateCanonicalFileEnvelope(
            byte[] raw,
            int maximum,
            string label)
        {
            if (raw == null) throw new ArgumentNullException("raw");
            if (raw.Length == 0 || raw.Length > maximum)
                throw Error(label, "byte size is outside the contract limit");
            if (raw.Length >= 3 && raw[0] == 0xef && raw[1] == 0xbb && raw[2] == 0xbf)
                throw Error(label, "UTF-8 BOM is forbidden");
            if (raw[raw.Length - 1] != 0x0a
                || (raw.Length >= 2 && raw[raw.Length - 2] == 0x0a))
                throw Error(label, "requires exactly one LF terminator");
            for (int index = 0; index < raw.Length; index++)
                if (raw[index] == 0x0d) throw Error(label, "CR is forbidden");
        }

        private static IDictionary<string, StrictJsonValue> Object(
            StrictJsonValue value,
            string path,
            string[] exactKeys)
        {
            if (value.Kind != StrictJsonKind.Object) throw Error(path, "expected object");
            IDictionary<string, StrictJsonValue> result = value.ObjectValue;
            foreach (string key in result.Keys)
            {
                bool found = false;
                for (int index = 0; index < exactKeys.Length; index++)
                    found |= string.Equals(key, exactKeys[index], StringComparison.Ordinal);
                if (!found) throw Error(path, "unknown property '" + Safe(key) + "'");
            }
            for (int index = 0; index < exactKeys.Length; index++)
                if (!result.ContainsKey(exactKeys[index]))
                    throw Error(path, "missing property '" + exactKeys[index] + "'");
            return result;
        }

        private static IList<StrictJsonValue> Array(
            StrictJsonValue value, string path, int minimum, int maximum)
        {
            if (value.Kind != StrictJsonKind.Array) throw Error(path, "expected array");
            if (value.ArrayValue.Count < minimum || value.ArrayValue.Count > maximum)
                throw Error(path, "array length is outside the allowed range");
            return value.ArrayValue;
        }

        private static string String(StrictJsonValue value, string path)
        {
            if (value.Kind != StrictJsonKind.String) throw Error(path, "expected string");
            return value.StringValue;
        }

        private static bool Boolean(StrictJsonValue value, string path)
        {
            if (value.Kind != StrictJsonKind.Boolean) throw Error(path, "expected boolean");
            return value.BooleanValue;
        }

        private static long LongInteger(
            StrictJsonValue value, string path, long minimum, long maximum)
        {
            if (value.Kind != StrictJsonKind.Number
                || value.NumberToken.IndexOf('.') >= 0
                || value.NumberToken.IndexOf('e') >= 0
                || value.NumberToken.IndexOf('E') >= 0)
                throw Error(path, "expected integral JSON number");
            long result;
            if (!long.TryParse(value.NumberToken, NumberStyles.AllowLeadingSign,
                CultureInfo.InvariantCulture, out result)
                || result < minimum || result > maximum)
                throw Error(path, "integer is outside the allowed range");
            if (!string.Equals(
                value.NumberToken,
                result.ToString(CultureInfo.InvariantCulture),
                StringComparison.Ordinal))
                throw Error(path, "integer token is not Python-canonical JSON");
            return result;
        }

        private static int Integer(
            StrictJsonValue value, string path, int minimum, int maximum)
        {
            return checked((int)LongInteger(value, path, minimum, maximum));
        }

        private static long? NullablePositiveLong(
            StrictJsonValue value,
            string path)
        {
            return value.Kind == StrictJsonKind.Null
                ? (long?)null
                : LongInteger(value, path, 1, long.MaxValue);
        }

        private static string NullableString(StrictJsonValue value, string path)
        {
            return value.Kind == StrictJsonKind.Null ? null : String(value, path);
        }

        private static long TextureGpuBytes(int width, int height, string format)
        {
            if (string.Equals(format, "BC7", StringComparison.Ordinal))
            {
                return AssetStreamAccounting.CalculateTextureGpuBytes(
                    width,
                    height,
                    4,
                    4,
                    16);
            }
            if (string.Equals(format, "RGBA32", StringComparison.Ordinal))
            {
                return AssetStreamAccounting.CalculateTextureGpuBytes(
                    width,
                    height,
                    1,
                    1,
                    4);
            }
            throw Error("$.format", "must be BC7 or RGBA32");
        }

        private static double Number(
            StrictJsonValue value, string path, double minimum, double maximum)
        {
            if (value.Kind != StrictJsonKind.Number) throw Error(path, "expected number");
            double result;
            if (!double.TryParse(value.NumberToken, NumberStyles.Float,
                CultureInfo.InvariantCulture, out result)
                || double.IsNaN(result) || double.IsInfinity(result)
                || result < minimum || result > maximum)
                throw Error(path, "number is outside the finite allowed range");
            return result;
        }

        private static int PageDimension(StrictJsonValue value, string path)
        {
            int result = Integer(value, path, AssetStreamContract.MinimumPageDimension,
                AssetStreamContract.MaximumPageDimension);
            if (!AssetStreamManifestRules.IsPowerOfTwoPageDimension(result))
                throw Error(path, "must be a power of two from 256 through 4096");
            return result;
        }

        private static string Sha256(StrictJsonValue value, string path)
        {
            string result = String(value, path);
            if (!AssetStreamManifestRules.IsCanonicalSha256(result))
                throw Error(path, "expected lowercase SHA-256 hex");
            return result;
        }

        private static string NullableSha256(StrictJsonValue value, string path)
        {
            return value.Kind == StrictJsonKind.Null ? null : Sha256(value, path);
        }

        private static string RelativePath(StrictJsonValue value, string path)
        {
            string result = String(value, path);
            if (!AssetStreamManifestRules.IsSafeRelativePath(result))
                throw Error(path, "expected canonical safe relative path/address");
            return result;
        }

        private static string NullableRelativePath(StrictJsonValue value, string path)
        {
            return value.Kind == StrictJsonKind.Null ? null : RelativePath(value, path);
        }

        private static string Group(string value, string path)
        {
            if (!AssetStreamManifestRules.IsSafeGroup(value))
                throw Error(path, "unsupported group identity");
            return value;
        }

        private static string Slug(string value, string group, string path)
        {
            string expected = AssetStreamManifestRules.GroupSlug(group);
            if (!AssetStreamManifestRules.IsSafeSlug(value)
                || !string.Equals(value, expected, StringComparison.Ordinal))
                throw Error(
                    path,
                    "must equal the canonical lowercased/underscore group slug");
            return value;
        }

        private static AssetStreamMaskPolicy MaskPolicy(string value, string path)
        {
            if (value == "required") return AssetStreamMaskPolicy.Required;
            if (value == "forbidden") return AssetStreamMaskPolicy.Forbidden;
            throw Error(path, "must be 'required' or 'forbidden'");
        }

        private static void RequireBinding(
            AssetStreamMaskPolicy policy,
            string slug,
            int pageCount,
            string binding,
            string path)
        {
            if (!AssetStreamMaterialBindingContract.IsExact(
                    policy,
                    slug,
                    pageCount,
                    binding))
            {
                throw Error(
                    path,
                    "does not match the exact group/page material route");
            }
        }

        private static void RequireEqual(string actual, string expected, string path)
        {
            if (!string.Equals(actual, expected, StringComparison.Ordinal))
                throw Error(path, "expected '" + expected + "'");
        }

        private static void RequireUnique(HashSet<string> values, string value, string path)
        {
            if (!values.Add(value)) throw Error(path, "duplicates or case-collides");
        }

        private static void RequireTextureUnique(
            AssetStreamPageTexture texture,
            HashSet<string> paths,
            HashSet<string> addresses,
            string path)
        {
            if (!paths.Add(texture.AssetPath) || !addresses.Add(texture.Address))
                throw Error(path, "duplicates or case-collides with another texture");
        }

        private static int CompareFrame(
            AssetStreamAtlasFrame left, AssetStreamAtlasFrame right)
        {
            int result = left.Index.CompareTo(right.Index);
            if (result != 0) return result;
            result = left.Alt.CompareTo(right.Alt);
            return result != 0 ? result : CompareUnicodeScalars(left.Name, right.Name);
        }

        private static int CompareUnicodeScalars(string left, string right)
        {
            int leftIndex = 0;
            int rightIndex = 0;
            while (leftIndex < left.Length && rightIndex < right.Length)
            {
                int leftScalar = char.ConvertToUtf32(left, leftIndex);
                int rightScalar = char.ConvertToUtf32(right, rightIndex);
                if (leftScalar != rightScalar)
                {
                    return leftScalar < rightScalar ? -1 : 1;
                }
                leftIndex += leftScalar > 0xffff ? 2 : 1;
                rightIndex += rightScalar > 0xffff ? 2 : 1;
            }
            if (leftIndex == left.Length && rightIndex == right.Length) return 0;
            return leftIndex == left.Length ? -1 : 1;
        }

        private static string Hash(byte[] bytes)
        {
            return Hash(bytes, 0, bytes.Length);
        }

        private static string Hash(byte[] bytes, int offset, int count)
        {
            using (SHA256 sha = SHA256.Create())
            {
                return DigestToHex(sha.ComputeHash(bytes, offset, count));
            }
        }

        private static string DigestToHex(byte[] digest)
        {
            var text = new StringBuilder(64);
            for (int index = 0; index < digest.Length; index++)
                text.Append(digest[index].ToString("x2", CultureInfo.InvariantCulture));
            return text.ToString();
        }

        private static void EnsureNfc(StrictJsonValue value, string path)
        {
            if (value.Kind == StrictJsonKind.String)
            {
                if (!string.Equals(value.StringValue, value.StringValue.Normalize(), StringComparison.Ordinal))
                    throw Error(path, "string is not NFC-normalized");
                return;
            }
            if (value.Kind == StrictJsonKind.Array)
            {
                for (int index = 0; index < value.ArrayValue.Count; index++)
                    EnsureNfc(value.ArrayValue[index], path + "[]");
                return;
            }
            if (value.Kind == StrictJsonKind.Object)
            {
                foreach (KeyValuePair<string, StrictJsonValue> item in value.ObjectValue)
                {
                    if (!string.Equals(item.Key, item.Key.Normalize(), StringComparison.Ordinal))
                        throw Error(path, "object key is not NFC-normalized");
                    EnsureNfc(item.Value, path + "." + item.Key);
                }
            }
        }

        private static string CanonicalJson(StrictJsonValue value)
        {
            var result = new StringBuilder();
            AppendCanonical(result, value);
            return result.ToString();
        }

        private static void AppendCanonical(StringBuilder result, StrictJsonValue value)
        {
            switch (value.Kind)
            {
                case StrictJsonKind.Null: result.Append("null"); return;
                case StrictJsonKind.Boolean: result.Append(value.BooleanValue ? "true" : "false"); return;
                case StrictJsonKind.Number: result.Append(value.NumberToken); return;
                case StrictJsonKind.String: AppendString(result, value.StringValue); return;
                case StrictJsonKind.Array:
                    result.Append('[');
                    for (int index = 0; index < value.ArrayValue.Count; index++)
                    {
                        if (index != 0) result.Append(',');
                        AppendCanonical(result, value.ArrayValue[index]);
                    }
                    result.Append(']');
                    return;
                case StrictJsonKind.Object:
                    var keys = new List<string>(value.ObjectValue.Keys);
                    keys.Sort(StringComparer.Ordinal);
                    result.Append('{');
                    for (int index = 0; index < keys.Count; index++)
                    {
                        if (index != 0) result.Append(',');
                        AppendString(result, keys[index]);
                        result.Append(':');
                        AppendCanonical(result, value.ObjectValue[keys[index]]);
                    }
                    result.Append('}');
                    return;
                default: throw new InvalidOperationException("Unknown JSON kind");
            }
        }

        private static string CanonicalStringArray(IList<string> values)
        {
            var result = new StringBuilder();
            result.Append('[');
            for (int index = 0; index < values.Count; index++)
            {
                if (index != 0) result.Append(',');
                AppendString(result, values[index]);
            }
            result.Append(']');
            return result.ToString();
        }

        private static void AppendString(StringBuilder result, string value)
        {
            result.Append('"');
            for (int index = 0; index < value.Length; index++)
            {
                char character = value[index];
                switch (character)
                {
                    case '"': result.Append("\\\""); break;
                    case '\\': result.Append("\\\\"); break;
                    case '\b': result.Append("\\b"); break;
                    case '\f': result.Append("\\f"); break;
                    case '\n': result.Append("\\n"); break;
                    case '\r': result.Append("\\r"); break;
                    case '\t': result.Append("\\t"); break;
                    default:
                        if (character < 0x20)
                            result.Append("\\u").Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                        else result.Append(character);
                        break;
                }
            }
            result.Append('"');
        }

        private static AssetStreamManifestParseException Error(string path, string detail)
        {
            return new AssetStreamManifestParseException(path + ": " + detail);
        }

        private static string Safe(string value)
        {
            if (value == null) return "null";
            var result = new StringBuilder();
            for (int index = 0; index < value.Length && result.Length < 80; index++)
                result.Append(char.IsControl(value[index]) ? ' ' : value[index]);
            return result.ToString();
        }

        /// <summary>
        /// Single-pass canonical UTF-8 reader for atlas.v2. It retains only the
        /// typed page/frame records required by the runtime. Fixed property names
        /// are matched in-place, frames_sha256 hashes the original array span,
        /// and names_sha256 is accumulated from canonical name token spans.
        /// </summary>
        private sealed class AtlasUtf8Reader
        {
            private static readonly byte[] OpenArray = { (byte)'[' };
            private static readonly byte[] CloseArray = { (byte)']' };
            private static readonly byte[] Comma = { (byte)',' };

            private readonly byte[] bytes;
            private readonly int end;
            private int position;

            internal AtlasUtf8Reader(byte[] raw, int contentLength)
            {
                bytes = raw;
                end = contentLength;
            }

            internal AssetStreamAtlasManifest Parse(
                string contentSha256,
                out string namesSha256)
            {
                Require((byte)'{');
                Property("bundle", true);
                string bundle = ReadString("$.bundle");
                Property("coordinate_system", false);
                string coordinateSystem = ReadString("$.coordinate_system");
                Property("frames", false);
                string actualFramesSha;
                List<AssetStreamAtlasFrame> frames = ReadFrames(
                    out actualFramesSha,
                    out namesSha256);
                Property("frames_sha256", false);
                string framesSha = ReadSha256("$.frames_sha256");
                Property("group", false);
                string group = ReadString("$.group");
                Property("mask_policy", false);
                string maskText = ReadString("$.mask_policy");
                Property("material_binding", false);
                string materialBinding = ReadString("$.material_binding");
                Property("max_page_dimension", false);
                int maximum = ReadInteger(
                    "$.max_page_dimension",
                    1,
                    int.MaxValue);
                Property("padding_pixels", false);
                int padding = ReadInteger("$.padding_pixels", 0, 64);
                Property("pages", false);
                List<AssetStreamAtlasPage> pages = ReadPages();
                Property("schema", false);
                string schema = ReadString("$.schema");
                Property("slug", false);
                string slug = ReadString("$.slug");
                Property("texture_contract", false);
                AssetStreamTextureContract textureContract = ReadTextureContract();
                Require((byte)'}');
                if (position != end)
                {
                    throw ReaderError("trailing data or whitespace");
                }

                RequireEqual(schema, AssetStreamContract.AtlasSchema, "$.schema");
                group = Group(group, "$.group");
                slug = Slug(slug, group, "$.slug");
                RequireEqual(bundle, "sede.gm." + slug + ".v2", "$.bundle");
                AssetStreamMaskPolicy maskPolicy = MaskPolicy(maskText, "$.mask_policy");
                RequireBinding(
                    maskPolicy,
                    slug,
                    pages.Count,
                    materialBinding,
                    "$.material_binding");
                RequireEqual(
                    coordinateSystem,
                    "unity_bottom_left",
                    "$.coordinate_system");
                if (padding != 1)
                {
                    throw Error("$.padding_pixels", "must be exactly 1");
                }
                if (maximum != AssetStreamContract.MaximumPageDimension)
                {
                    throw Error("$.max_page_dimension", "must be exactly 4096");
                }
                if (!textureContract.IsExactV2())
                {
                    throw Error(
                        "$.texture_contract",
                        "does not match the exact lossless Texture2D contract");
                }
                RequireEqual(
                    actualFramesSha,
                    framesSha,
                    "$.frames_sha256");
                ValidatePages(pages, slug, maskPolicy);
                ValidateFrames(pages, frames, maskPolicy);

                return new AssetStreamAtlasManifest(
                    group,
                    slug,
                    bundle,
                    maskPolicy,
                    materialBinding,
                    coordinateSystem,
                    padding,
                    maximum,
                    textureContract,
                    pages,
                    frames,
                    framesSha,
                    contentSha256);
            }

            private List<AssetStreamAtlasFrame> ReadFrames(
                out string framesSha256,
                out string namesSha256)
            {
                int framesStart = position;
                Require((byte)'[');
                var frames = new List<AssetStreamAtlasFrame>();
                using (SHA256 namesHash = SHA256.Create())
                {
                    Feed(namesHash, OpenArray, 0, OpenArray.Length);
                    if (!Consume((byte)']'))
                    {
                        while (true)
                        {
                            if (frames.Count != 0)
                            {
                                Require((byte)',');
                                Feed(namesHash, Comma, 0, Comma.Length);
                            }
                            int nameStart;
                            int nameEnd;
                            frames.Add(ReadFrame(
                                frames.Count,
                                out nameStart,
                                out nameEnd));
                            if (frames.Count > AssetStreamContract.MaximumFramesPerGroup)
                            {
                                throw Error(
                                    "$.frames",
                                    "frame count is outside the v1 limits");
                            }
                            Feed(namesHash, bytes, nameStart, nameEnd - nameStart);
                            if (Consume((byte)']')) break;
                            if (Peek() != (byte)',')
                            {
                                throw ReaderError("expected ',' or ']'");
                            }
                        }
                    }
                    if (frames.Count == 0)
                    {
                        throw Error("$.frames", "must contain at least one frame");
                    }
                    namesHash.TransformFinalBlock(CloseArray, 0, CloseArray.Length);
                    namesSha256 = DigestToHex(namesHash.Hash);
                }
                framesSha256 = Hash(bytes, framesStart, position - framesStart);
                return frames;
            }

            private AssetStreamAtlasFrame ReadFrame(
                int ordinal,
                out int nameTokenStart,
                out int nameTokenEnd)
            {
                string path = "$.frames["
                    + ordinal.ToString(CultureInfo.InvariantCulture)
                    + "]";
                Require((byte)'{');
                Property("alt", true);
                bool alt = ReadBoolean(path + ".alt");
                Property("index", false);
                int index = ReadInteger(path + ".index", 0, 2000000000);
                Property("main_rgba_sha256", false);
                string mainSha = ReadSha256(path + ".main_rgba_sha256");
                Property("mask_rgba_sha256", false);
                string maskSha = ReadNullableSha256(path + ".mask_rgba_sha256");
                Property("name", false);
                string name = ReadString(path + ".name", out nameTokenStart, out nameTokenEnd);
                if (name.Length == 0)
                {
                    throw Error(path + ".name", "must not be empty");
                }
                for (int nameIndex = 0; nameIndex < name.Length; nameIndex++)
                {
                    if (name[nameIndex] < 0x20)
                    {
                        throw Error(path + ".name", "contains NUL/control characters");
                    }
                }
                Property("page", false);
                int page = ReadInteger(
                    path + ".page",
                    0,
                    AssetStreamContract.MaximumPagesPerGroup - 1);
                Property("pivot", false);
                AssetStreamFramePivot pivot = ReadPivot(path + ".pivot");
                Property("pixels_per_unit", false);
                double pixelsPerUnit = ReadPythonNumber(
                    path + ".pixels_per_unit",
                    1.0 / 1024.0,
                    4096);
                Property("rect", false);
                AssetStreamFrameRect rect = ReadRect(path + ".rect");
                Require((byte)'}');
                return new AssetStreamAtlasFrame(
                    name,
                    index,
                    alt,
                    page,
                    rect,
                    pivot,
                    pixelsPerUnit,
                    mainSha,
                    maskSha);
            }

            private AssetStreamFramePivot ReadPivot(string path)
            {
                Require((byte)'{');
                Property("x", true);
                double x = ReadPythonNumber(
                    path + ".x",
                    -AssetStreamContract.MaximumAbsoluteSpritePivot,
                    AssetStreamContract.MaximumAbsoluteSpritePivot);
                Property("y", false);
                double y = ReadPythonNumber(
                    path + ".y",
                    -AssetStreamContract.MaximumAbsoluteSpritePivot,
                    AssetStreamContract.MaximumAbsoluteSpritePivot);
                Require((byte)'}');
                return new AssetStreamFramePivot(x, y);
            }

            private AssetStreamFrameRect ReadRect(string path)
            {
                Require((byte)'{');
                Property("height", true);
                int height = ReadInteger(path + ".height", 1, int.MaxValue);
                Property("width", false);
                int width = ReadInteger(path + ".width", 1, int.MaxValue);
                Property("x", false);
                int x = ReadInteger(path + ".x", 0, int.MaxValue);
                Property("y", false);
                int y = ReadInteger(path + ".y", 0, int.MaxValue);
                Require((byte)'}');
                return new AssetStreamFrameRect(x, y, width, height);
            }

            private List<AssetStreamAtlasPage> ReadPages()
            {
                Require((byte)'[');
                var pages = new List<AssetStreamAtlasPage>();
                if (!Consume((byte)']'))
                {
                    while (true)
                    {
                        if (pages.Count != 0) Require((byte)',');
                        pages.Add(ReadPage(pages.Count));
                        if (pages.Count > AssetStreamContract.MaximumPagesPerGroup)
                        {
                            throw Error(
                                "$.pages",
                                "page count is outside the v1 limits");
                        }
                        if (Consume((byte)']')) break;
                        if (Peek() != (byte)',')
                        {
                            throw ReaderError("expected ',' or ']'");
                        }
                    }
                }
                if (pages.Count == 0)
                {
                    throw Error("$.pages", "must contain at least one page");
                }
                return pages;
            }

            private AssetStreamAtlasPage ReadPage(int ordinal)
            {
                string path = "$.pages["
                    + ordinal.ToString(CultureInfo.InvariantCulture)
                    + "]";
                Require((byte)'{');
                Property("height", true);
                int height = ReadPageDimension(path + ".height");
                Property("id", false);
                int id = ReadInteger(path + ".id", 0, int.MaxValue);
                if (id != ordinal)
                {
                    throw Error(path + ".id", "pages must be contiguous from zero");
                }
                Property("main", false);
                AssetStreamPageTexture main = ReadPageTexture(path + ".main");
                Property("mask", false);
                AssetStreamPageTexture mask = Peek() == (byte)'n'
                    ? ReadNullPageTexture(path + ".mask")
                    : ReadPageTexture(path + ".mask");
                Property("width", false);
                int width = ReadPageDimension(path + ".width");
                Require((byte)'}');
                return new AssetStreamAtlasPage(id, width, height, main, mask);
            }

            private AssetStreamPageTexture ReadNullPageTexture(string path)
            {
                ReadNull(path);
                return null;
            }

            private AssetStreamPageTexture ReadPageTexture(string path)
            {
                Require((byte)'{');
                Property("address", true);
                string address = ReadRelativePath(path + ".address");
                Property("asset_path", false);
                string assetPath = ReadRelativePath(path + ".asset_path");
                Property("png_sha256", false);
                string pngSha = ReadSha256(path + ".png_sha256");
                Property("rgba_sha256", false);
                string rgbaSha = ReadSha256(path + ".rgba_sha256");
                Require((byte)'}');
                return new AssetStreamPageTexture(
                    assetPath,
                    address,
                    pngSha,
                    rgbaSha);
            }

            private AssetStreamTextureContract ReadTextureContract()
            {
                const string path = "$.texture_contract";
                Require((byte)'{');
                Property("alpha_is_transparency", true);
                bool alphaIsTransparency = ReadBoolean(path + ".alpha_is_transparency");
                Property("alpha_source", false);
                string alphaSource = ReadString(path + ".alpha_source");
                Property("filter_mode", false);
                string filterMode = ReadString(path + ".filter_mode");
                Property("format", false);
                string format = ReadString(path + ".format");
                Property("mipmaps", false);
                bool mipmaps = ReadBoolean(path + ".mipmaps");
                Property("npot_scale", false);
                string npotScale = ReadString(path + ".npot_scale");
                Property("readable", false);
                bool readable = ReadBoolean(path + ".readable");
                Property("s_rgb", false);
                bool sRgb = ReadBoolean(path + ".s_rgb");
                Property("wrap_mode", false);
                string wrapMode = ReadString(path + ".wrap_mode");
                Require((byte)'}');
                return new AssetStreamTextureContract(
                    format,
                    sRgb,
                    mipmaps,
                    readable,
                    filterMode,
                    wrapMode,
                    alphaSource,
                    alphaIsTransparency,
                    npotScale);
            }

            private void ValidatePages(
                IList<AssetStreamAtlasPage> pages,
                string slug,
                AssetStreamMaskPolicy maskPolicy)
            {
                var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var addresses = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                for (int index = 0; index < pages.Count; index++)
                {
                    string path = "$.pages["
                        + index.ToString(CultureInfo.InvariantCulture)
                        + "]";
                    AssetStreamAtlasPage page = pages[index];
                    string number = page.Id.ToString("000", CultureInfo.InvariantCulture);
                    RequireEqual(
                        page.Main.AssetPath,
                        "Assets/Generated/Groups/" + slug + "/page-" + number + "-main.png",
                        path + ".main.asset_path");
                    RequireEqual(
                        page.Main.Address,
                        "sede/gm/" + slug + "/page/" + number + "/main",
                        path + ".main.address");
                    if (maskPolicy == AssetStreamMaskPolicy.Required)
                    {
                        if (page.Mask == null)
                        {
                            throw Error(path + ".mask", "is required");
                        }
                        RequireEqual(
                            page.Mask.AssetPath,
                            "Assets/Generated/Groups/" + slug + "/page-" + number + "-mask.png",
                            path + ".mask.asset_path");
                        RequireEqual(
                            page.Mask.Address,
                            "sede/gm/" + slug + "/page/" + number + "/mask",
                            path + ".mask.address");
                    }
                    else if (page.Mask != null)
                    {
                        throw Error(path + ".mask", "must be null for forbidden masks");
                    }
                    RequireTextureUnique(page.Main, paths, addresses, path + ".main");
                    if (page.Mask != null)
                    {
                        RequireTextureUnique(page.Mask, paths, addresses, path + ".mask");
                    }
                }
            }

            private void ValidateFrames(
                IList<AssetStreamAtlasPage> pages,
                IList<AssetStreamAtlasFrame> frames,
                AssetStreamMaskPolicy maskPolicy)
            {
                var names = new HashSet<string>(StringComparer.Ordinal);
                var slots = new HashSet<FrameSlot>();
                var referencedPages = new bool[pages.Count];
                bool hasMain = false;
                AssetStreamAtlasFrame previous = null;
                for (int index = 0; index < frames.Count; index++)
                {
                    string path = "$.frames["
                        + index.ToString(CultureInfo.InvariantCulture)
                        + "]";
                    AssetStreamAtlasFrame frame = frames[index];
                    if (frame.Page >= pages.Count)
                    {
                        throw Error(path + ".page", "references a missing page");
                    }
                    if (previous != null && CompareFrame(previous, frame) >= 0)
                    {
                        throw Error("$.frames", "must be sorted by (index, alt, name)");
                    }
                    previous = frame;
                    if (!names.Add(frame.Name))
                    {
                        throw Error(path + ".name", "duplicates another frame name");
                    }
                    if (!slots.Add(new FrameSlot(frame.Index, frame.Alt)))
                    {
                        throw Error(path, "duplicates a loader slot");
                    }
                    if (maskPolicy == AssetStreamMaskPolicy.Required
                        && frame.MaskRgbaSha256 == null)
                    {
                        throw Error(path + ".mask_rgba_sha256", "is required");
                    }
                    if (maskPolicy == AssetStreamMaskPolicy.Forbidden
                        && frame.MaskRgbaSha256 != null)
                    {
                        throw Error(path + ".mask_rgba_sha256", "must be null");
                    }
                    hasMain |= !frame.Alt;
                    referencedPages[frame.Page] = true;
                }
                if (!hasMain)
                {
                    throw Error("$.frames", "must contain at least one main frame");
                }
                for (int index = 0; index < referencedPages.Length; index++)
                {
                    if (!referencedPages[index])
                    {
                        throw Error("$.pages", "every page must be referenced");
                    }
                }
                ValidateRectangles(pages, frames, 1);
            }

            private int ReadPageDimension(string path)
            {
                int value = ReadInteger(
                    path,
                    AssetStreamContract.MinimumPageDimension,
                    AssetStreamContract.MaximumPageDimension);
                if (!AssetStreamManifestRules.IsPowerOfTwoPageDimension(value))
                {
                    throw Error(path, "must be a power of two from 256 through 4096");
                }
                return value;
            }

            private string ReadRelativePath(string path)
            {
                string value = ReadString(path);
                if (!AssetStreamManifestRules.IsSafeRelativePath(value))
                {
                    throw Error(path, "expected canonical safe relative path/address");
                }
                return value;
            }

            private string ReadSha256(string path)
            {
                string value = ReadString(path);
                if (!AssetStreamManifestRules.IsCanonicalSha256(value))
                {
                    throw Error(path, "expected lowercase SHA-256 hex");
                }
                return value;
            }

            private string ReadNullableSha256(string path)
            {
                if (Peek() == (byte)'n')
                {
                    ReadNull(path);
                    return null;
                }
                return ReadSha256(path);
            }

            private void ReadNull(string path)
            {
                if (!ConsumeAscii("null"))
                {
                    throw Error(path, "expected null");
                }
            }

            private bool ReadBoolean(string path)
            {
                if (ConsumeAscii("true")) return true;
                if (ConsumeAscii("false")) return false;
                throw Error(path, "expected boolean");
            }

            private int ReadInteger(string path, int minimum, int maximum)
            {
                int start = position;
                bool negative = Consume((byte)'-');
                if (position >= end)
                {
                    throw Error(path, "incomplete integer");
                }
                ulong magnitude = 0;
                int digits = 0;
                if (bytes[position] == (byte)'0')
                {
                    position++;
                    digits = 1;
                    if (position < end && IsDigit(bytes[position]))
                    {
                        throw Error(path, "integer has a leading zero");
                    }
                }
                else
                {
                    while (position < end && IsDigit(bytes[position]))
                    {
                        int digit = bytes[position++] - (byte)'0';
                        if (++digits > 19
                            || magnitude > ((ulong)long.MaxValue - (uint)digit) / 10)
                        {
                            throw Error(path, "integer is outside signed 64-bit range");
                        }
                        magnitude = magnitude * 10 + (uint)digit;
                    }
                    if (digits == 0)
                    {
                        throw Error(path, "expected integer");
                    }
                }
                if (negative && magnitude == 0)
                {
                    throw Error(path, "integer token is not Python-canonical JSON");
                }
                if (position < end
                    && (bytes[position] == (byte)'.'
                        || bytes[position] == (byte)'e'
                        || bytes[position] == (byte)'E'))
                {
                    throw Error(path, "expected integral JSON number");
                }
                long value = negative
                    ? -checked((long)magnitude)
                    : checked((long)magnitude);
                if (value < minimum || value > maximum)
                {
                    throw Error(path, "integer is outside the allowed range");
                }
                // start participates in diagnostics and makes it explicit that
                // the complete canonical token, rather than a numeric prefix,
                // was consumed.
                if (position == start)
                {
                    throw Error(path, "expected integer");
                }
                return checked((int)value);
            }

            private double ReadPythonNumber(
                string path,
                double minimum,
                double maximum)
            {
                int start = position;
                ScanNumber(path);
                int length = position - start;
                if (length > 128)
                {
                    throw Error(path, "number token is too long");
                }
                string token = Encoding.ASCII.GetString(bytes, start, length);
                double value;
                if (!double.TryParse(
                    token,
                    NumberStyles.Float,
                    CultureInfo.InvariantCulture,
                    out value)
                    || double.IsNaN(value)
                    || double.IsInfinity(value)
                    || value < minimum
                    || value > maximum)
                {
                    throw Error(path, "number is outside the finite allowed range");
                }
                if (!IsPythonCanonicalNumber(token, value))
                {
                    throw Error(path, "number token is not Python-canonical JSON");
                }
                return value;
            }

            private void ScanNumber(string path)
            {
                Consume((byte)'-');
                if (position >= end)
                {
                    throw Error(path, "incomplete number");
                }
                if (bytes[position] == (byte)'0')
                {
                    position++;
                    if (position < end && IsDigit(bytes[position]))
                    {
                        throw Error(path, "number has a leading zero");
                    }
                }
                else
                {
                    RequireDigit(path);
                    while (position < end && IsDigit(bytes[position])) position++;
                }
                if (Consume((byte)'.'))
                {
                    RequireDigit(path);
                    while (position < end && IsDigit(bytes[position])) position++;
                }
                if (position < end
                    && (bytes[position] == (byte)'e' || bytes[position] == (byte)'E'))
                {
                    position++;
                    if (position < end
                        && (bytes[position] == (byte)'+' || bytes[position] == (byte)'-'))
                    {
                        position++;
                    }
                    RequireDigit(path);
                    while (position < end && IsDigit(bytes[position])) position++;
                }
            }

            private static bool IsPythonCanonicalNumber(string token, double value)
            {
                int exponentMarker = token.IndexOfAny(new[] { 'e', 'E' });
                int dot = token.IndexOf('.');
                if (exponentMarker < 0 && dot < 0)
                {
                    long integer;
                    return long.TryParse(
                            token,
                            NumberStyles.AllowLeadingSign,
                            CultureInfo.InvariantCulture,
                            out integer)
                        && string.Equals(
                            token,
                            integer.ToString(CultureInfo.InvariantCulture),
                            StringComparison.Ordinal);
                }
                if (token.IndexOf('E') >= 0) return false;

                int sign = token[0] == '-' ? 1 : 0;
                string unsigned = token.Substring(sign);
                if (exponentMarker >= 0)
                {
                    int localExponent = exponentMarker - sign;
                    string mantissa = unsigned.Substring(0, localExponent);
                    string exponent = unsigned.Substring(localExponent + 1);
                    if (mantissa.Length == 0
                        || mantissa[0] < '1'
                        || mantissa[0] > '9'
                        || (mantissa.Length > 1 && mantissa[1] != '.')
                        || (mantissa.Length > 2 && mantissa[mantissa.Length - 1] == '0')
                        || exponent.Length < 3
                        || (exponent[0] != '+' && exponent[0] != '-'))
                    {
                        return false;
                    }
                    string exponentDigits = exponent.Substring(1);
                    if (exponentDigits.Length < 2
                        || (exponentDigits.Length > 2 && exponentDigits[0] == '0'))
                    {
                        return false;
                    }
                    int exponentValue;
                    if (!int.TryParse(
                        exponent,
                        NumberStyles.AllowLeadingSign,
                        CultureInfo.InvariantCulture,
                        out exponentValue))
                    {
                        return false;
                    }
                    if (exponentValue >= -4 && exponentValue < 16)
                    {
                        return false;
                    }
                    return !LastSignificandDigitIsRedundant(token, value, exponentMarker)
                        && MatchesCorrectlyRoundedSignificand(token, value);
                }

                if (dot < sign + 1 || dot == token.Length - 1) return false;
                string integerPart = token.Substring(sign, dot - sign);
                string fraction = token.Substring(dot + 1);
                if (integerPart.Length > 1 && integerPart[0] == '0') return false;
                if (fraction[fraction.Length - 1] == '0' && fraction.Length != 1)
                    return false;
                int decimalExponent;
                if (integerPart != "0")
                {
                    decimalExponent = integerPart.Length - 1;
                }
                else
                {
                    int first = 0;
                    while (first < fraction.Length && fraction[first] == '0') first++;
                    decimalExponent = first == fraction.Length ? 0 : -(first + 1);
                }
                if (decimalExponent < -4 || decimalExponent >= 16) return false;
                // json.loads preserves the floating-point type and json.dumps
                // therefore keeps the mandatory .0 for integral floats,
                // including signed zero.
                if (fraction == "0") return true;
                return !LastSignificandDigitIsRedundant(token, value, -1)
                    && MatchesCorrectlyRoundedSignificand(token, value);
            }

            private static bool MatchesCorrectlyRoundedSignificand(
                string token,
                double value)
            {
                bool negative;
                string digits;
                int scale;
                if (!TryNormalizeDecimal(token, out negative, out digits, out scale)
                    || digits == "0"
                    || digits.Length > 17)
                {
                    return digits == "0";
                }
                string rounded = value.ToString(
                    "G" + digits.Length.ToString(CultureInfo.InvariantCulture),
                    CultureInfo.InvariantCulture);
                bool roundedNegative;
                string roundedDigits;
                int roundedScale;
                return TryNormalizeDecimal(
                        rounded,
                        out roundedNegative,
                        out roundedDigits,
                        out roundedScale)
                    && negative == roundedNegative
                    && scale == roundedScale
                    && string.Equals(digits, roundedDigits, StringComparison.Ordinal);
            }

            private static bool TryNormalizeDecimal(
                string token,
                out bool negative,
                out string digits,
                out int scale)
            {
                negative = token.Length != 0 && token[0] == '-';
                int start = negative || (token.Length != 0 && token[0] == '+') ? 1 : 0;
                int marker = token.IndexOfAny(new[] { 'e', 'E' }, start);
                int mantissaEnd = marker < 0 ? token.Length : marker;
                int dot = token.IndexOf('.', start, mantissaEnd - start);
                int fractionDigits = dot < 0 ? 0 : mantissaEnd - dot - 1;
                var result = new StringBuilder(mantissaEnd - start);
                for (int index = start; index < mantissaEnd; index++)
                {
                    char current = token[index];
                    if (current != '.') result.Append(current);
                }
                int explicitExponent = 0;
                if (marker >= 0
                    && !int.TryParse(
                        token.Substring(marker + 1),
                        NumberStyles.AllowLeadingSign,
                        CultureInfo.InvariantCulture,
                        out explicitExponent))
                {
                    digits = null;
                    scale = 0;
                    return false;
                }
                digits = result.ToString().TrimStart('0');
                if (digits.Length == 0)
                {
                    digits = "0";
                    scale = 0;
                    return true;
                }
                try
                {
                    scale = checked(explicitExponent - fractionDigits);
                    int trailing = 0;
                    while (trailing < digits.Length - 1
                        && digits[digits.Length - trailing - 1] == '0')
                    {
                        trailing++;
                    }
                    if (trailing != 0)
                    {
                        digits = digits.Substring(0, digits.Length - trailing);
                        scale = checked(scale + trailing);
                    }
                    return true;
                }
                catch (OverflowException)
                {
                    scale = 0;
                    return false;
                }
            }

            private static bool LastSignificandDigitIsRedundant(
                string token,
                double value,
                int exponentMarker)
            {
                int signLength = token[0] == '-' ? 1 : 0;
                int mantissaEnd = exponentMarker >= 0
                    ? exponentMarker
                    : token.Length;
                int dot = token.IndexOf('.');
                if (dot < 0 || dot >= mantissaEnd) return false;
                int fractionDigits = mantissaEnd - dot - 1;
                var digitsBuilder = new StringBuilder(mantissaEnd - signLength - 1);
                for (int index = signLength; index < mantissaEnd; index++)
                {
                    if (token[index] != '.') digitsBuilder.Append(token[index]);
                }
                string digits = digitsBuilder.ToString().TrimStart('0');
                if (digits.Length <= 1) return false;

                int explicitExponent = 0;
                if (exponentMarker >= 0
                    && !int.TryParse(
                        token.Substring(exponentMarker + 1),
                        NumberStyles.AllowLeadingSign,
                        CultureInfo.InvariantCulture,
                        out explicitExponent))
                {
                    return false;
                }
                int shorterScale;
                try
                {
                    shorterScale = checked(explicitExponent - fractionDigits + 1);
                }
                catch (OverflowException)
                {
                    return false;
                }
                string prefix = digits.Substring(0, digits.Length - 1);
                string sign = signLength == 0 ? string.Empty : "-";
                return MapsToSameDouble(
                        sign + prefix + "e"
                        + shorterScale.ToString(CultureInfo.InvariantCulture),
                        value)
                    || MapsToSameDouble(
                        sign + IncrementDecimal(prefix) + "e"
                        + shorterScale.ToString(CultureInfo.InvariantCulture),
                        value);
            }

            private static bool MapsToSameDouble(string token, double expected)
            {
                double actual;
                return double.TryParse(
                        token,
                        NumberStyles.Float,
                        CultureInfo.InvariantCulture,
                        out actual)
                    && BitConverter.DoubleToInt64Bits(actual)
                        == BitConverter.DoubleToInt64Bits(expected);
            }

            private static string IncrementDecimal(string digits)
            {
                char[] result = digits.ToCharArray();
                for (int index = result.Length - 1; index >= 0; index--)
                {
                    if (result[index] != '9')
                    {
                        result[index]++;
                        return new string(result);
                    }
                    result[index] = '0';
                }
                return "1" + new string(result);
            }

            private string ReadString(string path)
            {
                int ignoredStart;
                int ignoredEnd;
                return ReadString(path, out ignoredStart, out ignoredEnd);
            }

            private string ReadString(
                string path,
                out int tokenStart,
                out int tokenEnd)
            {
                tokenStart = position;
                Require((byte)'"');
                int chunkStart = position;
                StringBuilder builder = null;
                while (position < end)
                {
                    byte current = bytes[position++];
                    if (current == (byte)'"')
                    {
                        string value;
                        if (builder == null)
                        {
                            value = DecodeUtf8(chunkStart, position - chunkStart - 1, path);
                        }
                        else
                        {
                            AppendUtf8(
                                builder,
                                chunkStart,
                                position - chunkStart - 1,
                                path);
                            value = builder.ToString();
                        }
                        if (!value.IsNormalized())
                        {
                            throw Error(path, "string is not NFC-normalized");
                        }
                        tokenEnd = position;
                        return value;
                    }
                    if (current < 0x20)
                    {
                        throw Error(path, "contains an unescaped control character");
                    }
                    if (current != (byte)'\\') continue;

                    if (builder == null) builder = new StringBuilder();
                    AppendUtf8(builder, chunkStart, position - chunkStart - 1, path);
                    if (position >= end)
                    {
                        throw Error(path, "contains an unterminated escape");
                    }
                    byte escape = bytes[position++];
                    switch (escape)
                    {
                        case (byte)'"': builder.Append('"'); break;
                        case (byte)'\\': builder.Append('\\'); break;
                        case (byte)'b': builder.Append('\b'); break;
                        case (byte)'f': builder.Append('\f'); break;
                        case (byte)'n': builder.Append('\n'); break;
                        case (byte)'r': builder.Append('\r'); break;
                        case (byte)'t': builder.Append('\t'); break;
                        case (byte)'u':
                            builder.Append(ReadCanonicalControlEscape(path));
                            break;
                        default:
                            throw Error(path, "contains a noncanonical string escape");
                    }
                    chunkStart = position;
                }
                throw Error(path, "contains an unterminated string");
            }

            private char ReadCanonicalControlEscape(string path)
            {
                if (position + 4 > end)
                {
                    throw Error(path, "contains an incomplete Unicode escape");
                }
                int value = 0;
                for (int index = 0; index < 4; index++)
                {
                    byte digit = bytes[position++];
                    int hex;
                    if (digit >= (byte)'0' && digit <= (byte)'9')
                        hex = digit - (byte)'0';
                    else if (digit >= (byte)'a' && digit <= (byte)'f')
                        hex = digit - (byte)'a' + 10;
                    else
                        throw Error(path, "contains a noncanonical Unicode escape");
                    value = (value << 4) | hex;
                }
                if (value >= 0x20
                    || value == 0x08
                    || value == 0x09
                    || value == 0x0a
                    || value == 0x0c
                    || value == 0x0d)
                {
                    throw Error(path, "contains an unnecessarily escaped character");
                }
                return (char)value;
            }

            private string DecodeUtf8(int offset, int count, string path)
            {
                try
                {
                    return StrictUtf8.GetString(bytes, offset, count);
                }
                catch (DecoderFallbackException exception)
                {
                    throw new AssetStreamManifestParseException(
                        path + ": invalid UTF-8",
                        exception);
                }
            }

            private void AppendUtf8(
                StringBuilder builder,
                int offset,
                int count,
                string path)
            {
                if (count != 0) builder.Append(DecodeUtf8(offset, count, path));
            }

            private void Property(string name, bool first)
            {
                if (!first) Require((byte)',');
                RequireAsciiString(name);
                Require((byte)':');
            }

            private void RequireAsciiString(string value)
            {
                Require((byte)'"');
                for (int index = 0; index < value.Length; index++)
                {
                    if (position >= end || bytes[position++] != (byte)value[index])
                    {
                        throw ReaderError("unexpected or unsorted object property");
                    }
                }
                Require((byte)'"');
            }

            private bool ConsumeAscii(string value)
            {
                if (position + value.Length > end) return false;
                for (int index = 0; index < value.Length; index++)
                {
                    if (bytes[position + index] != (byte)value[index]) return false;
                }
                position += value.Length;
                return true;
            }

            private void RequireDigit(string path)
            {
                if (position >= end || !IsDigit(bytes[position]))
                {
                    throw Error(path, "number has no digit");
                }
                position++;
            }

            private byte Peek()
            {
                if (position >= end) throw ReaderError("unexpected end of document");
                return bytes[position];
            }

            private bool Consume(byte value)
            {
                if (position < end && bytes[position] == value)
                {
                    position++;
                    return true;
                }
                return false;
            }

            private void Require(byte value)
            {
                if (!Consume(value))
                {
                    throw ReaderError("expected '" + (char)value + "'");
                }
            }

            private AssetStreamManifestParseException ReaderError(string detail)
            {
                return new AssetStreamManifestParseException(
                    "atlas.v2 JSON byte offset "
                    + position.ToString(CultureInfo.InvariantCulture)
                    + ": "
                    + detail);
            }

            private static bool IsDigit(byte value)
            {
                return value >= (byte)'0' && value <= (byte)'9';
            }

            private static void Feed(
                HashAlgorithm hash,
                byte[] source,
                int offset,
                int count)
            {
                hash.TransformBlock(source, offset, count, source, offset);
            }
        }

        private struct FrameSlot : IEquatable<FrameSlot>
        {
            internal FrameSlot(int index, bool alt) { Index = index; Alt = alt; }
            private int Index { get; set; }
            private bool Alt { get; set; }
            public bool Equals(FrameSlot other) { return Index == other.Index && Alt == other.Alt; }
            public override bool Equals(object obj) { return obj is FrameSlot && Equals((FrameSlot)obj); }
            public override int GetHashCode() { return (Index * 397) ^ Alt.GetHashCode(); }
        }

        private struct RectBucket : IEquatable<RectBucket>
        {
            internal RectBucket(int page, int x, int y) { Page = page; X = x; Y = y; }
            private int Page { get; set; }
            private int X { get; set; }
            private int Y { get; set; }
            public bool Equals(RectBucket other) { return Page == other.Page && X == other.X && Y == other.Y; }
            public override bool Equals(object obj) { return obj is RectBucket && Equals((RectBucket)obj); }
            public override int GetHashCode() { unchecked { return ((Page * 397) ^ X) * 397 ^ Y; } }
        }

        private struct RectIdentity : IEquatable<RectIdentity>
        {
            internal RectIdentity(int page, int x, int y, int width, int height)
            { Page = page; X = x; Y = y; Width = width; Height = height; }
            private int Page { get; set; }
            private int X { get; set; }
            private int Y { get; set; }
            private int Width { get; set; }
            private int Height { get; set; }
            public bool Equals(RectIdentity other)
            { return Page == other.Page && X == other.X && Y == other.Y && Width == other.Width && Height == other.Height; }
            public override bool Equals(object obj) { return obj is RectIdentity && Equals((RectIdentity)obj); }
            public override int GetHashCode()
            { unchecked { int hash = Page; hash = hash * 397 ^ X; hash = hash * 397 ^ Y; hash = hash * 397 ^ Width; return hash * 397 ^ Height; } }
        }
    }

    internal enum StrictJsonKind
    {
        Null = 0, Boolean = 1, Number = 2, String = 3, Array = 4, Object = 5,
    }

    internal sealed class StrictJsonValue
    {
        private StrictJsonValue(StrictJsonKind kind) { Kind = kind; }
        internal StrictJsonKind Kind { get; private set; }
        internal bool BooleanValue { get; private set; }
        internal string NumberToken { get; private set; }
        internal string StringValue { get; private set; }
        internal IList<StrictJsonValue> ArrayValue { get; private set; }
        internal IDictionary<string, StrictJsonValue> ObjectValue { get; private set; }
        internal static StrictJsonValue Null() { return new StrictJsonValue(StrictJsonKind.Null); }
        internal static StrictJsonValue Boolean(bool value)
        { return new StrictJsonValue(StrictJsonKind.Boolean) { BooleanValue = value }; }
        internal static StrictJsonValue Number(string value)
        { return new StrictJsonValue(StrictJsonKind.Number) { NumberToken = value }; }
        internal static StrictJsonValue String(string value)
        { return new StrictJsonValue(StrictJsonKind.String) { StringValue = value }; }
        internal static StrictJsonValue Array(IList<StrictJsonValue> value)
        { return new StrictJsonValue(StrictJsonKind.Array) { ArrayValue = value }; }
        internal static StrictJsonValue Object(IDictionary<string, StrictJsonValue> value)
        { return new StrictJsonValue(StrictJsonKind.Object) { ObjectValue = value }; }
    }

    internal sealed class StrictJsonReader
    {
        private const int MaximumDepth = 64;
        private const int MaximumNodes = 32000000;
        private const int MaximumStringCharacters = AssetStreamContract.MaximumAtlasBytes;
        private readonly string json;
        private int position;
        private int nodes;

        internal StrictJsonReader(string jsonValue)
        {
            if (string.IsNullOrEmpty(jsonValue))
                throw new AssetStreamManifestParseException("JSON document is empty");
            json = jsonValue;
        }

        internal StrictJsonValue ParseDocument()
        {
            StrictJsonValue result = ParseValue(0);
            if (position != json.Length) throw Error("trailing data or whitespace");
            return result;
        }

        private StrictJsonValue ParseValue(int depth)
        {
            if (depth > MaximumDepth) throw Error("maximum nesting depth exceeded");
            if (++nodes > MaximumNodes) throw Error("maximum JSON value count exceeded");
            if (position >= json.Length) throw Error("unexpected end of document");
            char character = json[position];
            if (character == '{') return ParseObject(depth + 1);
            if (character == '[') return ParseArray(depth + 1);
            if (character == '"') return StrictJsonValue.String(ParseString());
            if (character == 't') { ConsumeLiteral("true"); return StrictJsonValue.Boolean(true); }
            if (character == 'f') { ConsumeLiteral("false"); return StrictJsonValue.Boolean(false); }
            if (character == 'n') { ConsumeLiteral("null"); return StrictJsonValue.Null(); }
            if (character == '-' || (character >= '0' && character <= '9'))
                return StrictJsonValue.Number(ParseNumber());
            throw Error("unexpected character");
        }

        private StrictJsonValue ParseObject(int depth)
        {
            position++;
            var result = new Dictionary<string, StrictJsonValue>(StringComparer.Ordinal);
            if (ConsumeIf('}')) return StrictJsonValue.Object(result);
            while (true)
            {
                if (position >= json.Length || json[position] != '"')
                    throw Error("object key must be a string");
                string key = ParseString();
                Require(':');
                StrictJsonValue value = ParseValue(depth);
                if (result.ContainsKey(key)) throw Error("duplicate object key");
                result.Add(key, value);
                if (ConsumeIf('}')) return StrictJsonValue.Object(result);
                Require(',');
                if (position < json.Length && json[position] == '}')
                    throw Error("trailing object comma");
            }
        }

        private StrictJsonValue ParseArray(int depth)
        {
            position++;
            var result = new List<StrictJsonValue>();
            if (ConsumeIf(']')) return StrictJsonValue.Array(result);
            while (true)
            {
                result.Add(ParseValue(depth));
                if (ConsumeIf(']')) return StrictJsonValue.Array(result);
                Require(',');
                if (position < json.Length && json[position] == ']')
                    throw Error("trailing array comma");
            }
        }

        private string ParseString()
        {
            Require('"');
            var result = new StringBuilder();
            while (position < json.Length)
            {
                char character = json[position++];
                if (character == '"') return result.ToString();
                if (character == '\\') AppendEscape(result);
                else
                {
                    if (character < 0x20) throw Error("unescaped control character");
                    AppendCharacter(result, character, false);
                }
                if (result.Length > MaximumStringCharacters) throw Error("string is too long");
            }
            throw Error("unterminated string");
        }

        private void AppendEscape(StringBuilder result)
        {
            if (position >= json.Length) throw Error("unterminated escape");
            switch (json[position++])
            {
                case '"': result.Append('"'); return;
                case '\\': result.Append('\\'); return;
                case '/': result.Append('/'); return;
                case 'b': result.Append('\b'); return;
                case 'f': result.Append('\f'); return;
                case 'n': result.Append('\n'); return;
                case 'r': result.Append('\r'); return;
                case 't': result.Append('\t'); return;
                case 'u': AppendCharacter(result, ReadUnicodeEscape(), true); return;
                default: throw Error("unknown string escape");
            }
        }

        private void AppendCharacter(StringBuilder result, char character, bool escaped)
        {
            if (char.IsHighSurrogate(character))
            {
                char low;
                if (escaped)
                {
                    if (position + 1 >= json.Length || json[position] != '\\' || json[position + 1] != 'u')
                        throw Error("high surrogate is not followed by low surrogate");
                    position += 2;
                    low = ReadUnicodeEscape();
                }
                else
                {
                    if (position >= json.Length) throw Error("incomplete surrogate pair");
                    low = json[position++];
                }
                if (!char.IsLowSurrogate(low)) throw Error("invalid surrogate pair");
                result.Append(character).Append(low);
                return;
            }
            if (char.IsLowSurrogate(character)) throw Error("unpaired low surrogate");
            result.Append(character);
        }

        private char ReadUnicodeEscape()
        {
            if (position + 4 > json.Length) throw Error("incomplete unicode escape");
            int value = 0;
            for (int index = 0; index < 4; index++) value = (value << 4) | Hex(json[position++]);
            return (char)value;
        }

        private string ParseNumber()
        {
            int start = position;
            ConsumeIf('-');
            if (position >= json.Length) throw Error("incomplete number");
            if (json[position] == '0')
            {
                position++;
                if (position < json.Length && char.IsDigit(json[position])) throw Error("leading zero");
            }
            else
            {
                RequireDigit('1', '9', "expected number");
                while (position < json.Length && char.IsDigit(json[position])) position++;
            }
            if (ConsumeIf('.'))
            {
                RequireDigit('0', '9', "fraction has no digits");
                while (position < json.Length && char.IsDigit(json[position])) position++;
            }
            if (position < json.Length && (json[position] == 'e' || json[position] == 'E'))
            {
                position++;
                if (position < json.Length && (json[position] == '+' || json[position] == '-')) position++;
                RequireDigit('0', '9', "exponent has no digits");
                while (position < json.Length && char.IsDigit(json[position])) position++;
            }
            return json.Substring(start, position - start);
        }

        private void RequireDigit(char minimum, char maximum, string detail)
        {
            if (position >= json.Length || json[position] < minimum || json[position] > maximum)
                throw Error(detail);
            position++;
        }

        private void ConsumeLiteral(string literal)
        {
            if (position + literal.Length > json.Length
                || !string.Equals(json.Substring(position, literal.Length), literal, StringComparison.Ordinal))
                throw Error("invalid literal");
            position += literal.Length;
        }

        private bool ConsumeIf(char character)
        {
            if (position < json.Length && json[position] == character) { position++; return true; }
            return false;
        }

        private void Require(char character)
        {
            if (!ConsumeIf(character)) throw Error("expected '" + character + "'");
        }

        private int Hex(char character)
        {
            if (character >= '0' && character <= '9') return character - '0';
            if (character >= 'a' && character <= 'f') return character - 'a' + 10;
            if (character >= 'A' && character <= 'F') return character - 'A' + 10;
            throw Error("invalid unicode escape");
        }

        private AssetStreamManifestParseException Error(string detail)
        {
            return new AssetStreamManifestParseException(
                "JSON offset " + position.ToString(CultureInfo.InvariantCulture) + ": " + detail);
        }
    }
}
