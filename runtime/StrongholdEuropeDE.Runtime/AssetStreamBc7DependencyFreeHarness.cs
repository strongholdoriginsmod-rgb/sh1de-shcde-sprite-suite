#if ASSET_STREAM_HARNESS
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    internal static class AssetStreamBc7DependencyFreeHarness
    {
        private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);

        internal static void Register(Action<string, Action> run)
        {
            run("BC7 V2 canonical index + atlas.v3", TestPositive);
            run("BC7 V2 rejects wrong format and texture policy", TestFormatAndPolicy);
            run("BC7 V2 rejects total GM resident budget 3 GiB + 1", TestThreeGibPlusOne);
            run("BC7 V2 rejects accounting formula drift", TestFormulaDrift);
            run("BC7 V2 rejects overlapping storage cells", TestBlockOverlap);
            run("BC7 V2 rejects missing platform support", TestMissingSupport);
            run("BC7 V2 measurement parses but is nonpromotable", TestMeasurementState);
            run("BC7 V4 hard-private commit-first admission boundaries", TestCommitFirstAdmission);
            run("asset-stream V1 accounting remains unchanged", TestV1Unchanged);
        }

        private static void TestPositive()
        {
            Fixture fixture = Fixture.Create();
            AssetStreamManifest index = AssetStreamManifestParser.ParseIndex(
                fixture.IndexRaw);
            Equal(
                AssetStreamPipelineVersion.Bc7VisualEquivalenceV2,
                index.PipelineVersion,
                "pipeline version");
            Equal(65536L, index.TotalGpuBytes, "total GPU bytes");
            Equal(4194304L, index.TotalResidentChargeBytes, "total charge");
            Equal(
                AssetStreamBc7Contract.ResourcePolicyKind,
                index.ResourcePolicyKind,
                "resource policy");
            AssetStreamAtlasManifest atlas = AssetStreamManifestParser.ParseAtlasV3(
                fixture.AtlasRaw,
                index.Groups[0]);
            Equal("BC7", atlas.MainTextureContract.Format, "main format");
            Equal(25, atlas.MainTextureContract.UnityTextureFormat, "Unity enum");
            Equal(4, atlas.BlockAlignmentPixels, "block alignment");
            Equal(1, atlas.MinimumBorderPixels, "minimum border");
            Equal(8, atlas.Frames[0].StorageCell.Width, "cell width");
        }

        private static void TestFormatAndPolicy()
        {
            Fixture fixture = Fixture.Create();
            string index = Utf8.GetString(fixture.IndexRaw);
            ThrowsContaining<AssetStreamManifestParseException>(
                delegate
                {
                    AssetStreamManifestParser.ParseIndex(Utf8.GetBytes(
                        ReplaceFirst(
                            index,
                            "\"main_format\":\"BC7\"",
                            "\"main_format\":\"RGBA32\"")));
                },
                "main_format",
                "wrong main format");
            ThrowsContaining<AssetStreamManifestParseException>(
                delegate
                {
                    AssetStreamManifestParser.ParseIndex(Utf8.GetBytes(
                        index.Replace(
                            AssetStreamBc7Contract.Bc7MainBc7MaskTexturePolicyId,
                            "bc7-main-invalid-mask-v1")));
                },
                "texture policy",
                "wrong global texture policy");
        }

        private static void TestThreeGibPlusOne()
        {
            Fixture fixture = Fixture.Create(
                rootChargeOverride: AssetStreamBc7Contract
                    .MaximumTotalResidentChargeBytes + 1);
            ThrowsContaining<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseIndex(fixture.IndexRaw); },
                "3-GiB",
                "3 GiB plus one");
        }

        private static void TestFormulaDrift()
        {
            Fixture fixture = Fixture.Create(
                groupChargeOverride: 4194305,
                rootChargeOverride: 4194305);
            ThrowsContaining<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseIndex(fixture.IndexRaw); },
                "ceil(9/8",
                "resident formula drift");
        }

        private static void TestBlockOverlap()
        {
            Fixture fixture = Fixture.Create(overlap: true);
            AssetStreamManifest index = AssetStreamManifestParser.ParseIndex(
                fixture.IndexRaw);
            ThrowsContaining<AssetStreamManifestParseException>(
                delegate
                {
                    AssetStreamManifestParser.ParseAtlasV3(
                        fixture.AtlasRaw,
                        index.Groups[0]);
                },
                "GPU blocks",
                "overlapping storage cells");
        }

        private static void TestMissingSupport()
        {
            ThrowsContaining<InvalidOperationException>(
                delegate
                {
                    AssetStreamManifestRules.RequireBc7RuntimeSupport(true, false);
                },
                "BC7",
                "missing BC7 support");
            AssetStreamManifestRules.RequireBc7RuntimeSupport(true, true);
            AssetStreamManifestRules.RequireBc7RuntimeSupport(false, false);
        }

        private static void TestMeasurementState()
        {
            Fixture fixture = Fixture.Create(measurement: true);
            AssetStreamManifest index = AssetStreamManifestParser.ParseIndex(
                fixture.IndexRaw);
            Equal(
                AssetStreamBc7Contract.MeasurementQualityState,
                index.QualityPolicy.State,
                "measurement state");
            Equal(false, index.QualityPolicy.IsPromotable, "measurement promotable");
        }

        private static void TestV1Unchanged()
        {
            Equal(
                67108864L,
                AssetStreamAccounting.CalculateResidentChargeBytes(262144),
                "V1 charge alignment");
            Equal(
                AssetStreamContract.ResourcePolicyKind,
                AssetStreamResourcePolicy.Windows24GbIgpuSafeV1().Kind,
                "V1 policy kind");
        }

        private static void TestCommitFirstAdmission()
        {
            AssetStreamResourcePolicy policy = AssetStreamResourcePolicy
                .Windows24GbIgpuBc7TwelveGibProcessPrivateV5();
            Equal(
                "windows_24gb_igpu_bc7_12gib_process_private_v5",
                policy.Kind,
                "BC7 V5 policy kind");
            Equal(3L * 1024 * 1024 * 1024, policy.AdditionalGmResidentBytes,
                "BC7 V5 GM budget");
            Equal(12L * 1024 * 1024 * 1024, policy.ProcessPrivateCeilingBytes,
                "BC7 V5 hard process-private ceiling");
            Equal(4L * 1024 * 1024 * 1024, policy.GlobalCommitReserveBytes,
                "BC7 V5 commit reserve");
            Equal(256L * 1024 * 1024, policy.MinimumFreePhysicalBytes,
                "BC7 V5 physical floor");

            AssetStreamGroupManifest group = AssetStreamManifestParser.ParseIndex(
                Fixture.Create().IndexRaw).Groups[0];
            long peak = group.PredictedLoadPeakBytes;
            long physical095Gib = 19L * 1024 * 1024 * 1024 / 20L;
            var usage = new FixedUsageProbe();
            AssetStreamBudgetReservation reservation;
            AssetStreamAdmissionDecision decision;

            var admitted = new AssetStreamBudgetLedger(
                policy,
                new FixedMemoryProbe(
                    6L * 1024 * 1024 * 1024,
                    policy.GlobalCommitReserveBytes + peak,
                    physical095Gib),
                usage);
            Equal(true, admitted.TryReserve(
                group, out reservation, out decision),
                "0.95 GiB physical with valid commit admits");
            Equal(AssetStreamAdmissionFailure.None, decision.Failure,
                "commit-first admitted reason");
            reservation.Cancel();

            var exactPrivateCeiling = new AssetStreamBudgetLedger(
                policy,
                new FixedMemoryProbe(
                    policy.ProcessPrivateCeilingBytes - peak,
                    policy.GlobalCommitReserveBytes + peak,
                    physical095Gib),
                usage);
            Equal(true, exactPrivateCeiling.TryReserve(
                group, out reservation, out decision),
                "exact process-private ceiling admits");
            reservation.Cancel();

            var exactFloor = new AssetStreamBudgetLedger(
                policy,
                new FixedMemoryProbe(
                    6L * 1024 * 1024 * 1024,
                    20L * 1024 * 1024 * 1024,
                    policy.MinimumFreePhysicalBytes),
                usage);
            Equal(true, exactFloor.TryReserve(
                group, out reservation, out decision),
                "absolute physical floor does not add transient peak");
            reservation.Cancel();

            AssertDenied(
                policy,
                group,
                new FixedMemoryProbe(
                    6L * 1024 * 1024 * 1024,
                    20L * 1024 * 1024 * 1024,
                    policy.MinimumFreePhysicalBytes - 1),
                usage,
                AssetStreamAdmissionFailure.MinimumFreePhysical,
                "below absolute physical floor");
            AssertDenied(
                policy,
                group,
                new FixedMemoryProbe(
                    6L * 1024 * 1024 * 1024,
                    policy.GlobalCommitReserveBytes + peak - 1,
                    physical095Gib),
                usage,
                AssetStreamAdmissionFailure.GlobalCommitReserve,
                "insufficient available commit");
            AssertDenied(
                policy,
                group,
                new FixedMemoryProbe(
                    policy.ProcessPrivateCeilingBytes - peak + 1,
                    20L * 1024 * 1024 * 1024,
                    physical095Gib),
                usage,
                AssetStreamAdmissionFailure.ProcessPrivateCeiling,
                "insufficient process-private headroom");
        }

        private static void AssertDenied(
            AssetStreamResourcePolicy policy,
            AssetStreamGroupManifest group,
            IAssetStreamMemoryProbe memory,
            IAssetStreamExternalUsageProbe usage,
            AssetStreamAdmissionFailure expected,
            string label)
        {
            var ledger = new AssetStreamBudgetLedger(policy, memory, usage);
            AssetStreamBudgetReservation reservation;
            AssetStreamAdmissionDecision decision;
            Equal(false, ledger.TryReserve(
                group, out reservation, out decision), label + " denied");
            Equal(expected, decision.Failure, label + " reason");
            Equal<AssetStreamBudgetReservation>(null, reservation,
                label + " has no reservation");
        }

        private sealed class FixedMemoryProbe : IAssetStreamMemoryProbe
        {
            private readonly AssetStreamMemorySnapshot snapshot;

            internal FixedMemoryProbe(
                long processPrivateBytes,
                long globalAvailableCommitBytes,
                long availablePhysicalBytes)
            {
                snapshot = new AssetStreamMemorySnapshot(
                    processPrivateBytes,
                    globalAvailableCommitBytes,
                    availablePhysicalBytes,
                    "BC7 V4 harness");
            }

            public AssetStreamMemorySnapshot Capture()
            {
                return snapshot;
            }
        }

        private sealed class FixedUsageProbe : IAssetStreamExternalUsageProbe
        {
            public AssetStreamExternalUsageSnapshot Capture()
            {
                return new AssetStreamExternalUsageSnapshot(0, 0, "BC7 V4 harness");
            }
        }

        private static void Equal<T>(T expected, T actual, string label)
        {
            if (!EqualityComparer<T>.Default.Equals(expected, actual))
            {
                throw new InvalidOperationException(
                    label + ": expected=" + expected + ", actual=" + actual);
            }
        }

        private static void ThrowsContaining<TException>(
            Action action,
            string text,
            string label)
            where TException : Exception
        {
            try
            {
                action();
            }
            catch (TException exception)
            {
                if (exception.Message.IndexOf(text, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return;
                }
                throw new InvalidOperationException(
                    label + " did not contain '" + text + "': " + exception.Message);
            }
            throw new InvalidOperationException(
                label + " did not throw " + typeof(TException).Name);
        }

        private sealed class Fixture
        {
            private Fixture(byte[] indexRaw, byte[] atlasRaw)
            {
                IndexRaw = indexRaw;
                AtlasRaw = atlasRaw;
            }

            internal byte[] IndexRaw { get; private set; }
            internal byte[] AtlasRaw { get; private set; }

            internal static Fixture Create(
                bool overlap = false,
                bool measurement = false,
                long? groupChargeOverride = null,
                long? rootChargeOverride = null)
            {
                string shaA = new string('a', 64);
                string shaB = new string('b', 64);
                string shaC = new string('c', 64);
                string shaD = new string('d', 64);
                string shaE = new string('e', 64);
                string shaF = new string('f', 64);
                string slug = "anim_castle";
                string bundle = "sede.gm." + slug + AssetStreamBc7Contract.BundleSuffix;

                var frames = new List<object>();
                frames.Add(Frame("anim-castle-0", 0, 1, 3, 0, 0, shaE));
                if (overlap)
                {
                    frames.Add(Frame("anim-castle-1", 1, 5, 3, 4, 0, shaD));
                }
                string framesSha = Hash(Utf8.GetBytes(Canonical(frames)));
                var names = new List<object>();
                names.Add("anim-castle-0");
                if (overlap) names.Add("anim-castle-1");
                string namesSha = Hash(Utf8.GetBytes(Canonical(names)));

                SortedDictionary<string, object> mainContract = TextureContract();
                var atlas = Object(
                    "block_alignment_pixels", 4L,
                    "bundle", bundle,
                    "coordinate_system", "unity_bottom_left",
                    "extrusion_mode", AssetStreamBc7Contract.ExtrusionMode,
                    "frames", frames,
                    "frames_sha256", framesSha,
                    "group", slug,
                    "mask_policy", "forbidden",
                    "material_binding", AssetStreamMaterialBindingContract.PlainShared,
                    "max_page_dimension", 4096L,
                    "minimum_border_pixels", 1L,
                    "pages", new List<object>
                    {
                        Object(
                            "height", 256L,
                            "id", 0L,
                            "main", Object(
                                "address", "sede/gm/" + slug + "/page/000/main",
                                "asset_path", "Assets/Generated/Groups/" + slug
                                    + "/page-000-main.png",
                                "format", "BC7",
                                "gpu_bytes", 65536L,
                                "source_png_sha256", shaB,
                                "source_rgba_bytes", 262144L,
                                "source_rgba_sha256", shaF),
                            "mask", null,
                            "width", 256L),
                    },
                    "schema", AssetStreamBc7Contract.AtlasSchema,
                    "slug", slug,
                    "texture_contracts", Object(
                        "main", mainContract,
                        "mask", null));
                byte[] atlasRaw = Utf8.GetBytes(Canonical(atlas) + "\n");
                string atlasSha = Hash(atlasRaw);

                long exactCharge = 4194304L;
                long groupCharge = groupChargeOverride ?? exactCharge;
                long rootCharge = rootChargeOverride ?? groupCharge;
                long peak = AssetStreamAccounting.CalculatePeakAdmissionBytes(
                    exactCharge,
                    1024);
                var group = Object(
                    "array_size", overlap ? 2L : 1L,
                    "atlas_address", "sede/gm/" + slug + "/atlas.v3.json",
                    "atlas_asset_path", "Assets/Generated/Groups/" + slug
                        + "/atlas.v3.json",
                    "atlas_sha256", atlasSha,
                    "bundle", bundle,
                    "bundle_crc32", "1234abcd",
                    "bundle_path", "Runtime/AssetBundles/win64/" + bundle,
                    "bundle_sha256", shaA,
                    "bundle_size_bytes", 1024L,
                    "dash_format", false,
                    "frame_count", overlap ? 2L : 1L,
                    "frames_sha256", framesSha,
                    "gm_id", 7L,
                    "gpu_bytes", 65536L,
                    "group", slug,
                    "lifetime", "map",
                    "mask_policy", "forbidden",
                    "material_binding", AssetStreamMaterialBindingContract.PlainShared,
                    "names_sha256", namesSha,
                    "page_count", 1L,
                    "pages", new List<object>
                    {
                        Object(
                            "height", 256L,
                            "id", 0L,
                            "main_address", "sede/gm/" + slug + "/page/000/main",
                            "main_format", "BC7",
                            "main_gpu_bytes", 65536L,
                            "main_source_rgba_sha256", shaF,
                            "mask_address", null,
                            "mask_format", null,
                            "mask_gpu_bytes", null,
                            "mask_source_rgba_sha256", null,
                            "width", 256L),
                    },
                    "predicted_load_peak_bytes", peak,
                    "resident_charge_bytes", groupCharge,
                    "slug", slug,
                    "source_rgba_bytes", 262144L,
                    "unity_hash128", new string('c', 32));
                string qualityState = measurement
                    ? AssetStreamBc7Contract.MeasurementQualityState
                    : AssetStreamBc7Contract.FrozenQualityState;
                string qualityId = measurement
                    ? AssetStreamBc7Contract.MeasurementQualityPolicyId
                    : AssetStreamBc7Contract.FrozenQualityPolicyId;
                string qualitySha = measurement
                    ? AssetStreamBc7Contract.MeasurementQualityPolicySha256
                    : shaC;
                var index = Object(
                    "backend_kind", AssetStreamBc7Contract.AtlasBackendKind,
                    "build_id", shaD,
                    "build_target", AssetStreamContract.BuildTarget,
                    "encoder_id", AssetStreamBc7Contract.EncoderId,
                    "groups", new List<object> { group },
                    "max_page_dimension", 4096L,
                    "packer_id", AssetStreamBc7Contract.PackerId,
                    "quality_policy", Object(
                        "id", qualityId,
                        "sha256", qualitySha,
                        "state", qualityState,
                        "verifier_id", AssetStreamBc7Contract.QualityVerifierId),
                    "quality_report_sha256", shaB,
                    "schema", AssetStreamBc7Contract.IndexSchema,
                    "texture_policy", Object(
                        "id", AssetStreamBc7Contract.Bc7MainBc7MaskTexturePolicyId,
                        "main_format", "BC7",
                        "mask_format", "BC7"),
                    "total_gpu_bytes", 65536L,
                    "total_resident_charge_bytes", rootCharge,
                    "total_source_rgba_bytes", 262144L,
                    "unity", Object(
                        "revision", AssetStreamContract.UnityRevision,
                        "version", AssetStreamContract.UnityVersion),
                    "vanilla_omitted_groups", new List<object>());
                return new Fixture(
                    Utf8.GetBytes(Canonical(index) + "\n"),
                    atlasRaw);
            }

            private static SortedDictionary<string, object> Frame(
                string name,
                long index,
                long rectX,
                long rectY,
                long cellX,
                long cellY,
                string sourceSha)
            {
                return Object(
                    "alt", false,
                    "index", index,
                    "main_source_rgba_sha256", sourceSha,
                    "mask_source_rgba_sha256", null,
                    "name", name,
                    "page", 0L,
                    "pivot", Object("x", 0L, "y", 0L),
                    "pixels_per_unit", 1L,
                    "rect", Object(
                        "height", 4L,
                        "width", 4L,
                        "x", rectX,
                        "y", rectY),
                    "storage_cell", Object(
                        "height", 8L,
                        "width", 8L,
                        "x", cellX,
                        "y", cellY));
            }

            private static SortedDictionary<string, object> TextureContract()
            {
                return Object(
                    "allows_alpha_splitting", false,
                    "alpha_is_transparency", false,
                    "alpha_source", "FromInput",
                    "aniso_level", 0L,
                    "compression", "CompressedHQ",
                    "compression_quality", 100L,
                    "crunched_compression", false,
                    "filter_mode", "Point",
                    "force_maximum_compression_quality_bc6h_bc7", true,
                    "format", "BC7",
                    "gpu_block_bytes", 16L,
                    "gpu_block_height", 4L,
                    "gpu_block_width", 4L,
                    "ignore_png_gamma", true,
                    "max_texture_size", 4096L,
                    "mipmaps", false,
                    "npot_scale", "None",
                    "platform_override", true,
                    "readable", false,
                    "s_rgb", true,
                    "streaming_mipmaps", false,
                    "texture_type", "Default",
                    "unity_texture_format", 25L,
                    "wrap_mode", "Clamp");
            }
        }

        private static SortedDictionary<string, object> Object(params object[] values)
        {
            if (values.Length % 2 != 0) throw new ArgumentException("values");
            var result = new SortedDictionary<string, object>(StringComparer.Ordinal);
            for (int index = 0; index < values.Length; index += 2)
            {
                result.Add((string)values[index], values[index + 1]);
            }
            return result;
        }

        private static string Canonical(object value)
        {
            var result = new StringBuilder();
            AppendCanonical(result, value);
            return result.ToString();
        }

        private static void AppendCanonical(StringBuilder result, object value)
        {
            if (value == null)
            {
                result.Append("null");
                return;
            }
            string text = value as string;
            if (text != null)
            {
                AppendString(result, text);
                return;
            }
            if (value is bool)
            {
                result.Append((bool)value ? "true" : "false");
                return;
            }
            if (value is int || value is long)
            {
                result.Append(Convert.ToInt64(value).ToString(CultureInfo.InvariantCulture));
                return;
            }
            IDictionary<string, object> objectValue =
                value as IDictionary<string, object>;
            if (objectValue != null)
            {
                result.Append('{');
                bool first = true;
                foreach (KeyValuePair<string, object> pair in objectValue)
                {
                    if (!first) result.Append(',');
                    first = false;
                    AppendString(result, pair.Key);
                    result.Append(':');
                    AppendCanonical(result, pair.Value);
                }
                result.Append('}');
                return;
            }
            IList<object> array = value as IList<object>;
            if (array != null)
            {
                result.Append('[');
                for (int index = 0; index < array.Count; index++)
                {
                    if (index != 0) result.Append(',');
                    AppendCanonical(result, array[index]);
                }
                result.Append(']');
                return;
            }
            throw new InvalidOperationException("Unsupported fixture JSON value");
        }

        private static void AppendString(StringBuilder result, string value)
        {
            result.Append('"');
            for (int index = 0; index < value.Length; index++)
            {
                char character = value[index];
                if (character == '"' || character == '\\')
                {
                    result.Append('\\').Append(character);
                }
                else if (character < 0x20)
                {
                    result.Append("\\u")
                        .Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                }
                else
                {
                    result.Append(character);
                }
            }
            result.Append('"');
        }

        private static string Hash(byte[] value)
        {
            using (SHA256 sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(value);
                var result = new StringBuilder(64);
                for (int index = 0; index < digest.Length; index++)
                {
                    result.Append(digest[index].ToString("x2", CultureInfo.InvariantCulture));
                }
                return result.ToString();
            }
        }

        private static string ReplaceFirst(
            string value,
            string previous,
            string replacement)
        {
            int index = value.IndexOf(previous, StringComparison.Ordinal);
            if (index < 0) throw new InvalidOperationException("fixture token missing");
            return value.Substring(0, index)
                + replacement
                + value.Substring(index + previous.Length);
        }
    }
}
#endif
