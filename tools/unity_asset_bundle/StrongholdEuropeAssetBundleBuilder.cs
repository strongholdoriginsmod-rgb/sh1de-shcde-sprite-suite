// Deterministic, generic Unity 2021.3 AssetBundle builder for generated RGBA atlases.
// This file intentionally contains no game payload and is copied into an ephemeral
// project below work/unity-ab/<build-id-prefix>/project by the Python preparer.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditorInternal;
using UnityEngine;

namespace StrongholdEuropeDE.AssetBundles
{
    public static class BuildFromCommandLine
    {
        private const string UnityVersion = "2021.3.45f2";
        private const string UnityRevision = "88f88f591b2e";
        private const string UnityFullVersion = "2021.3.45f2 (88f88f591b2e)";
        private const string BuildInputSchema = "stronghold-europe-de.asset-bundle-build-input.v1";
        private const string IndexTemplateSchema = "stronghold-europe-de.asset-bundle-index-template.v1";
        private const string IndexSchema = "stronghold-europe-de.asset-bundle-index.v1";
        private const string BuildReportSchema = "stronghold-europe-de.asset-bundle-build-report.v1";
        private const string BuildInputSchemaV2 = "stronghold-europe-de.asset-bundle-build-input.v2";
        private const string UnityBuildReportSchemaV2 = "stronghold-europe-de.asset-bundle-build-report.v2";
        private const string BackendKindV2 = "unity_assetbundle_bc7_visual_equivalence_v2";
        private const string PackerIdV2 = "maxrects-bssf-no-rotation-cell4-rgba-extrude-v2";
        private const string EncoderIdV2 = "unity-2021.3.45f2-bc7-hq100-force-max-v1";
        private const string BuildTargetName = "StandaloneWindows64";
        private const int MaximumPageDimension = 4096;
        private const int MaximumGroups = 234;
        private const int MaximumPagesPerGroup = 16;
        private const int MaximumFramesPerGroup = 4096;
        private const int MaximumPreflightFramesPerGroup = 65536;
        private const int MaximumAtlasDocumentBytes = 4 * 1024 * 1024;
        private const int MaximumIndexBytes = 4 * 1024 * 1024;
        private const int MaximumReportBytes = 64 * 1024 * 1024;
        private const string ModBundleDirectory = "Runtime/AssetBundles/win64";
        private const string ModIndexPath = "Runtime/AssetBundles/index.json";

        private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);
        private static readonly Regex Sha256Pattern = new Regex("\\A[0-9a-f]{64}\\z", RegexOptions.CultureInvariant);
        private static readonly Regex BuildIdPattern = new Regex("\\A[0-9a-f]{64}\\z", RegexOptions.CultureInvariant);
        private static readonly Regex BuildDirectoryPattern = new Regex("\\A[0-9a-f]{16}\\z", RegexOptions.CultureInvariant);
        private static readonly Regex BundlePattern = new Regex("\\Asede\\.gm\\.[a-z0-9][a-z0-9._-]*\\.v2\\z", RegexOptions.CultureInvariant);
        private static readonly Regex BundlePatternV2 = new Regex("\\Asede\\.gm\\.[a-z0-9][a-z0-9._-]*\\.bc7\\.v2\\z", RegexOptions.CultureInvariant);
        private static readonly Regex TextureContractIdPattern = new Regex(
            "\\A(?:main-bc7-(?:point|bilinear)-v1|mask-(?:bc7|rgba32)-point-v1)\\z",
            RegexOptions.CultureInvariant);
        private static readonly Regex GroupPattern = new Regex(
            "\\A[A-Za-z0-9](?:[A-Za-z0-9._-]| [A-Za-z0-9])*\\z",
            RegexOptions.CultureInvariant);
        private static readonly Regex SlugPattern = new Regex(
            "\\A[a-z0-9][a-z0-9._-]*\\z",
            RegexOptions.CultureInvariant);
        private static readonly HashSet<string> OmissionReasons =
            new HashSet<string>(StringComparer.Ordinal)
            {
                "v1_frame_count_exceeded",
                "v1_slot_count_exceeded",
                "v1_frame_dimension_exceeded",
                "v1_page_count_exceeded",
                "v1_foliage_multipage",
            };
        private static readonly HashSet<string> PostfixMaterialGroups =
            new HashSet<string>(StringComparer.Ordinal)
            {
                "body_trebutchet",
                "body_archer",
                "body_battering_ram",
                "body_catapult",
                "body_deer",
                "body_farmer",
            };
        private static readonly string[] ExactBuildOptions =
        {
            "ChunkBasedCompression",
            "DeterministicAssetBundle",
            "ForceRebuildAssetBundle",
            "StrictMode",
        };

        [Serializable]
        private sealed class UnityIdentity
        {
            public string version;
            public string revision;
        }

        [Serializable]
        private sealed class TextureInput
        {
            public string asset_path;
            public int width;
            public int height;
            public string png_sha256;
            public long gpu_bytes;
            public string plane;
            public string source_png_sha256;
            public long source_rgba_bytes;
            public string source_rgba_sha256;
            public string texture_contract_id;
        }

        [Serializable]
        private sealed class TextureContract
        {
            public bool alpha_is_transparency;
            public string alpha_source;
            public bool allows_alpha_splitting;
            public int aniso_level;
            public string compression;
            public int compression_quality;
            public bool crunched_compression;
            public string filter_mode;
            public bool force_maximum_compression_quality_bc6h_bc7;
            public string format;
            public int gpu_block_bytes;
            public int gpu_block_height;
            public int gpu_block_width;
            public bool ignore_png_gamma;
            public int max_texture_size;
            public bool mipmaps;
            public string npot_scale;
            public bool platform_override;
            public bool readable;
            public bool s_rgb;
            public bool streaming_mipmaps;
            public string texture_type;
            public int unity_texture_format;
            public string wrap_mode;
        }

        [Serializable]
        private sealed class TextureContractBinding
        {
            public string id;
            public TextureContract texture_contract;
        }

        [Serializable]
        private sealed class TexturePolicyV2
        {
            public string id;
            public string main_format;
            public string mask_format;
        }

        [Serializable]
        private sealed class QualityPolicyV2
        {
            public string id;
            public string sha256;
            public string state;
            public string verifier_id;
        }

        [Serializable]
        private sealed class BundleAssetInput
        {
            public string asset_path;
            public string address;
        }

        [Serializable]
        private sealed class BundleInput
        {
            public string name;
            public BundleAssetInput[] assets;
        }

        [Serializable]
        private sealed class BuildInput
        {
            public string schema;
            public string build_id;
            public UnityIdentity unity;
            public string build_target;
            public string[] build_options;
            public int max_page_dimension;
            public string output_relative_path;
            public string index_template_asset_path;
            public string index_output_relative_path;
            public string editor_script_sha256;
            public BundleInput[] bundles;
            public TextureInput[] textures;
            public string backend_kind;
            public string editor_texture_compression_override;
            public string encoder_id;
            public string packer_id;
            public QualityPolicyV2 quality_policy;
            public string quality_report_output_relative_path;
            public TextureContractBinding[] texture_contracts;
            public TexturePolicyV2 texture_policy;
        }

        [Serializable]
        private sealed class IndexPage
        {
            public int id;
            public int width;
            public int height;
            public string main_address;
            public string main_rgba_sha256;
            public string mask_address;
            public string mask_rgba_sha256;
        }

        [Serializable]
        private sealed class IndexGroupTemplate
        {
            public string group;
            public string slug;
            public int gm_id;
            public bool dash_format;
            public int array_size;
            public string lifetime;
            public string bundle;
            public string atlas_asset_path;
            public string atlas_address;
            public string atlas_sha256;
            public string mask_policy;
            public string material_binding;
            public int page_count;
            public int frame_count;
            public string names_sha256;
            public string frames_sha256;
            public long raw_rgba_bytes;
            public long resident_charge_bytes;
            public IndexPage[] pages;
        }

        [Serializable]
        private sealed class OmittedGroupTemplate
        {
            public string group;
            public int gm_id;
            public string reason;
            public int array_size;
            public int frame_count;
            public string names_sha256;
            public string frames_sha256;
        }

        [Serializable]
        private sealed class IndexTemplate
        {
            public string schema;
            public string build_id;
            public UnityIdentity unity;
            public string build_target;
            public int max_page_dimension;
            public IndexGroupTemplate[] groups;
            public OmittedGroupTemplate[] vanilla_omitted_groups;
        }

        private sealed class TextureReport
        {
            public string assetPath;
            public int width;
            public int height;
            public string pngSha256;
            public long gpuBytes;
            public string plane;
            public long sourceRgbaBytes;
            public string sourceRgbaSha256;
            public string textureContractId;
        }

        private sealed class BundleArtifact
        {
            public string name;
            public string modRelativePath;
            public long sizeBytes;
            public string sha256;
            public string crc32;
            public string manifestHash;
        }

        private sealed class Report
        {
            public bool success;
            public string error = string.Empty;
            public string buildId = new string('0', 64);
            public string buildInputSha256 = new string('0', 64);
            public readonly List<TextureReport> textures = new List<TextureReport>();
            public readonly List<BundleArtifact> bundles = new List<BundleArtifact>();
            public bool v2;
        }

        public static void Build()
        {
            int exitCode = 1;
            string reportPath = null;
            Report report = new Report();
            try
            {
                Dictionary<string, string> arguments = ParseArguments(Environment.GetCommandLineArgs());
                string projectPath = CanonicalFullPath(Directory.GetParent(Application.dataPath).FullName);
                ValidateProjectPlacement(projectPath);
                string buildInputPath = RequiredArgument(arguments, "-sedeBuildInput");
                reportPath = RequiredArgument(arguments, "-sedeBuildReport");
                ValidateCommandPaths(projectPath, buildInputPath, reportPath);
                report.v2 = String.Equals(
                    Path.GetFileName(buildInputPath),
                    "build-input.v2.json",
                    StringComparison.Ordinal);
                if (File.Exists(reportPath))
                {
                    throw new InvalidOperationException("Refusing to overwrite a stale build report: " + reportPath);
                }

                byte[] buildInputBytes = File.ReadAllBytes(buildInputPath);
                report.buildInputSha256 = Sha256(buildInputBytes);
                BuildInput input = JsonUtility.FromJson<BuildInput>(Utf8.GetString(buildInputBytes));
                if (report.v2)
                {
                    if (input == null || input.schema != BuildInputSchemaV2)
                        throw new InvalidDataException("V2 build-input path/schema discriminator drifted");
                    ValidateInputV2(input, projectPath);
                }
                else ValidateInput(input, projectPath);
                report.buildId = input.build_id;
                ValidateEditorIdentity();
                ValidateEditorSource(input, projectPath);

                string outputPath = ResolveProjectRelative(projectPath, input.output_relative_path);
                string indexOutputPath = ResolveProjectRelative(projectPath, input.index_output_relative_path);
                RequireExactOutputPaths(projectPath, outputPath, indexOutputPath);
                RequireFreshOutputDirectory(outputPath);

                foreach (TextureInput texture in input.textures.OrderBy(item => item.asset_path, StringComparer.Ordinal))
                {
                    if (report.v2)
                    {
                        TextureContract contract = FindTextureContract(input, texture.texture_contract_id);
                        VerifyTextureV2(projectPath, texture, contract);
                    }
                    else
                    {
                        ConfigureAndVerifyTexture(projectPath, texture);
                    }
                    report.textures.Add(new TextureReport
                    {
                        assetPath = texture.asset_path,
                        width = texture.width,
                        height = texture.height,
                        pngSha256 = report.v2 ? texture.source_png_sha256 : texture.png_sha256,
                        gpuBytes = texture.gpu_bytes,
                        plane = texture.plane,
                        sourceRgbaBytes = texture.source_rgba_bytes,
                        sourceRgbaSha256 = texture.source_rgba_sha256,
                        textureContractId = texture.texture_contract_id,
                    });
                }

                AssetBundleBuild[] maps = CreateBuildMaps(input);
                AssetBundleManifest manifest = null;
                if (maps.Length != 0)
                {
                    manifest = BuildPipeline.BuildAssetBundles(
                        outputPath,
                        maps,
                        BuildAssetBundleOptions.ChunkBasedCompression |
                        BuildAssetBundleOptions.DeterministicAssetBundle |
                        BuildAssetBundleOptions.ForceRebuildAssetBundle |
                        BuildAssetBundleOptions.StrictMode,
                        BuildTarget.StandaloneWindows64);
                    if (manifest == null)
                    {
                        throw new InvalidOperationException("BuildPipeline.BuildAssetBundles returned null");
                    }
                    VerifyBundleSet(manifest, input.bundles);
                    foreach (BundleInput bundle in input.bundles.OrderBy(item => item.name, StringComparer.Ordinal))
                    {
                        string bundlePath = CanonicalFullPath(Path.Combine(outputPath, bundle.name));
                        if (!File.Exists(bundlePath) || !SameParent(bundlePath, outputPath))
                        {
                            throw new InvalidOperationException("Expected bundle is missing or escaped output: " + bundle.name);
                        }
                        BundleArtifact artifact = new BundleArtifact
                        {
                            name = bundle.name,
                            modRelativePath = ModBundleDirectory + "/" + bundle.name,
                            sizeBytes = new FileInfo(bundlePath).Length,
                            sha256 = Sha256(File.ReadAllBytes(bundlePath)),
                            crc32 = Crc32(bundlePath),
                            manifestHash = manifest.GetAssetBundleHash(bundle.name).ToString().ToLowerInvariant(),
                        };
                        if (artifact.sizeBytes <= 0 || artifact.manifestHash.Length != 32)
                        {
                            throw new InvalidOperationException("Invalid built bundle metadata: " + bundle.name);
                        }
                        report.bundles.Add(artifact);
                    }
                    VerifyOutputFileSet(outputPath, input.bundles);
                }
                else if (Directory.EnumerateFileSystemEntries(outputPath).Any())
                {
                    throw new InvalidOperationException("Empty build emitted unexpected AssetBundle files");
                }

                if (!report.v2)
                {
                    string templatePath = ResolveAssetPath(projectPath, input.index_template_asset_path);
                    IndexTemplate indexTemplate = JsonUtility.FromJson<IndexTemplate>(
                        Utf8.GetString(ReadBoundedBytes(templatePath, MaximumIndexBytes, "index template")));
                    ValidateIndexTemplate(indexTemplate, input, projectPath);
                    WriteFinalIndex(indexOutputPath, indexTemplate, report.bundles);
                }
                else if (File.Exists(indexOutputPath))
                {
                    throw new InvalidOperationException("V2 final index must be created only after quality verification");
                }

                report.success = true;
                report.error = string.Empty;
                WriteReport(reportPath, report);
                exitCode = 0;
                Debug.Log("Stronghold Europe deterministic AssetBundle build completed: " + input.build_id);
            }
            catch (Exception exception)
            {
                report.success = false;
                report.error = exception.ToString();
                Debug.LogException(exception);
                if (!String.IsNullOrEmpty(reportPath) && !File.Exists(reportPath))
                {
                    try
                    {
                        WriteReport(reportPath, report);
                    }
                    catch (Exception reportException)
                    {
                        Debug.LogException(reportException);
                    }
                }
            }
            finally
            {
                EditorApplication.Exit(exitCode);
            }
        }

        private static Dictionary<string, string> ParseArguments(string[] commandLine)
        {
            Dictionary<string, string> result = new Dictionary<string, string>(StringComparer.Ordinal);
            for (int i = 0; i < commandLine.Length; ++i)
            {
                string key = commandLine[i];
                if (key != "-sedeBuildInput" && key != "-sedeBuildReport")
                {
                    continue;
                }
                if (result.ContainsKey(key) || i + 1 >= commandLine.Length)
                {
                    throw new ArgumentException("Missing or duplicate command-line argument: " + key);
                }
                result.Add(key, CanonicalFullPath(commandLine[++i]));
            }
            return result;
        }

        private static string RequiredArgument(Dictionary<string, string> arguments, string key)
        {
            string value;
            if (!arguments.TryGetValue(key, out value))
            {
                throw new ArgumentException("Required command-line argument is missing: " + key);
            }
            return value;
        }

        private static void ValidateProjectPlacement(string projectPath)
        {
            DirectoryInfo project = new DirectoryInfo(projectPath);
            DirectoryInfo build = project.Parent;
            DirectoryInfo container = build == null ? null : build.Parent;
            DirectoryInfo work = container == null ? null : container.Parent;
            if (project.Name != "project" || build == null || !BuildDirectoryPattern.IsMatch(build.Name) ||
                container == null || container.Name != "unity-ab" || work == null || work.Name != "work")
            {
                throw new InvalidOperationException("Unity project is not in work/unity-ab/<build-id-prefix>/project");
            }
        }

        private static void ValidateCommandPaths(string projectPath, string inputPath, string reportPath)
        {
            string expectedInput = CanonicalFullPath(Path.Combine(projectPath, "Assets", "Generated", "build-input.json"));
            string expectedReport = CanonicalFullPath(Path.Combine(projectPath, "..", "output", "build-report.json"));
            string expectedInputV2 = CanonicalFullPath(Path.Combine(projectPath, "Assets", "Generated", "build-input.v2.json"));
            string expectedReportV2 = CanonicalFullPath(Path.Combine(projectPath, "..", "output", "unity-build-report.v2.json"));
            bool v1 = SamePath(inputPath, expectedInput) && SamePath(reportPath, expectedReport);
            bool v2 = SamePath(inputPath, expectedInputV2) && SamePath(reportPath, expectedReportV2);
            if (!v1 && !v2)
            {
                throw new InvalidOperationException("Build input or report path is not the exact ephemeral-project path");
            }
        }

        private static void ValidateInput(BuildInput input, string projectPath)
        {
            if (input == null || input.schema != BuildInputSchema || !BuildIdPattern.IsMatch(input.build_id ?? "") ||
                input.unity == null || input.unity.version != UnityVersion || input.unity.revision != UnityRevision ||
                input.build_target != BuildTargetName || input.max_page_dimension != MaximumPageDimension ||
                input.output_relative_path != "../output/Runtime/AssetBundles/win64" ||
                input.index_template_asset_path != "Assets/Generated/index.template.json" ||
                input.index_output_relative_path != "../output/Runtime/AssetBundles/index.json" ||
                !Sha256Pattern.IsMatch(input.editor_script_sha256 ?? "") ||
                input.build_options == null || !input.build_options.SequenceEqual(ExactBuildOptions) ||
                input.bundles == null || input.bundles.Length > MaximumGroups ||
                input.textures == null ||
                input.textures.Length > MaximumGroups * MaximumPagesPerGroup * 2 ||
                (input.bundles.Length == 0) != (input.textures.Length == 0))
            {
                throw new InvalidDataException("Build input identity or constants drifted");
            }
            if (!input.build_id.StartsWith(
                    new DirectoryInfo(projectPath).Parent.Name,
                    StringComparison.Ordinal))
            {
                throw new InvalidDataException("Build id prefix does not match project directory");
            }
            string[] names = input.bundles.Select(item => item == null ? null : item.name).ToArray();
            if (names.Any(name => name == null || !BundlePattern.IsMatch(name)) ||
                !names.SequenceEqual(names.OrderBy(name => name, StringComparer.Ordinal)) ||
                names.Distinct(StringComparer.Ordinal).Count() != names.Length)
            {
                throw new InvalidDataException("Bundle names are invalid, duplicated, or unsorted");
            }
        }

        private static void ValidateInputV2(BuildInput input, string projectPath)
        {
            if (input == null || input.schema != BuildInputSchemaV2 ||
                input.backend_kind != BackendKindV2 ||
                !BuildIdPattern.IsMatch(input.build_id ?? "") ||
                input.unity == null || input.unity.version != UnityVersion || input.unity.revision != UnityRevision ||
                input.build_target != BuildTargetName || input.max_page_dimension != MaximumPageDimension ||
                input.output_relative_path != "../output/Runtime/AssetBundles/win64" ||
                input.index_template_asset_path != "Assets/Generated/index.v2.template.json" ||
                input.index_output_relative_path != "../output/Runtime/AssetBundles/index.json" ||
                input.quality_report_output_relative_path != "../output/bc7-quality-report.v1.json" ||
                input.editor_texture_compression_override != "NoOverride" ||
                input.encoder_id != EncoderIdV2 || input.packer_id != PackerIdV2 ||
                !Sha256Pattern.IsMatch(input.editor_script_sha256 ?? "") ||
                input.build_options == null || !input.build_options.SequenceEqual(ExactBuildOptions) ||
                input.bundles == null || input.bundles.Length <= 0 || input.bundles.Length > MaximumGroups ||
                input.textures == null || input.textures.Length <= 0 ||
                input.textures.Length > MaximumGroups * MaximumPagesPerGroup * 2 ||
                input.texture_contracts == null || input.texture_contracts.Length <= 0 ||
                input.texture_policy == null || input.quality_policy == null)
            {
                throw new InvalidDataException("V2 build input identity or constants drifted");
            }
            if (!input.build_id.StartsWith(new DirectoryInfo(projectPath).Parent.Name, StringComparison.Ordinal))
                throw new InvalidDataException("V2 build id prefix does not match project directory");
            if (input.texture_policy.main_format != "BC7" ||
                (input.texture_policy.id != "bc7-main-bc7-mask-hq100-v1" &&
                 input.texture_policy.id != "bc7-main-rgba32-mask-hq100-v1") ||
                (input.texture_policy.id == "bc7-main-bc7-mask-hq100-v1" && input.texture_policy.mask_format != "BC7") ||
                (input.texture_policy.id == "bc7-main-rgba32-mask-hq100-v1" && input.texture_policy.mask_format != "RGBA32"))
                throw new InvalidDataException("V2 global texture policy drifted");
            if (!Sha256Pattern.IsMatch(input.quality_policy.sha256 ?? "") ||
                input.quality_policy.verifier_id != "unitypy-1.25.3-bc7-frame-metrics-v1" ||
                (input.quality_policy.state != "measurement_nonpromotable" && input.quality_policy.state != "frozen"))
                throw new InvalidDataException("V2 quality policy drifted");

            string[] names = input.bundles.Select(item => item == null ? null : item.name).ToArray();
            if (names.Any(name => name == null || !BundlePatternV2.IsMatch(name)) ||
                !names.SequenceEqual(names.OrderBy(name => name, StringComparer.Ordinal)) ||
                names.Distinct(StringComparer.Ordinal).Count() != names.Length)
                throw new InvalidDataException("V2 bundle names are invalid, duplicated, or unsorted");

            string[] contractIds = input.texture_contracts.Select(item => item == null ? null : item.id).ToArray();
            if (contractIds.Any(id => id == null || !TextureContractIdPattern.IsMatch(id)) ||
                !contractIds.SequenceEqual(contractIds.OrderBy(id => id, StringComparer.Ordinal)) ||
                contractIds.Distinct(StringComparer.Ordinal).Count() != contractIds.Length)
                throw new InvalidDataException("V2 texture contracts are invalid, duplicated, or unsorted");
            foreach (TextureContractBinding binding in input.texture_contracts)
                ValidateTextureContract(binding.id, binding.texture_contract);

            string[] texturePaths = input.textures.Select(item => item == null ? null : item.asset_path).ToArray();
            if (texturePaths.Any(path => path == null) ||
                !texturePaths.SequenceEqual(texturePaths.OrderBy(path => path, StringComparer.Ordinal)) ||
                texturePaths.Distinct(StringComparer.Ordinal).Count() != texturePaths.Length)
                throw new InvalidDataException("V2 texture inputs are duplicated or unsorted");
            HashSet<string> usedContracts = new HashSet<string>(StringComparer.Ordinal);
            foreach (TextureInput texture in input.textures)
            {
                TextureContract contract = FindTextureContract(input, texture.texture_contract_id);
                usedContracts.Add(texture.texture_contract_id);
                if ((texture.plane != "main" && texture.plane != "mask") ||
                    !texture.texture_contract_id.StartsWith(texture.plane + "-", StringComparison.Ordinal) ||
                    texture.width < 256 || texture.width > MaximumPageDimension ||
                    texture.height < 256 || texture.height > MaximumPageDimension ||
                    (texture.width & (texture.width - 1)) != 0 || (texture.height & (texture.height - 1)) != 0 ||
                    texture.source_rgba_bytes != checked((long)texture.width * texture.height * 4L) ||
                    texture.gpu_bytes != ExpectedGpuBytes(texture.width, texture.height, contract.format) ||
                    !Sha256Pattern.IsMatch(texture.source_png_sha256 ?? "") ||
                    !Sha256Pattern.IsMatch(texture.source_rgba_sha256 ?? "") ||
                    (texture.plane == "main" && contract.format != input.texture_policy.main_format) ||
                    (texture.plane == "mask" && contract.format != input.texture_policy.mask_format))
                    throw new InvalidDataException("V2 texture input contract drifted: " + texture.asset_path);
            }
            if (!usedContracts.SetEquals(contractIds))
                throw new InvalidDataException("V2 texture contracts contain unused or missing ids");
            if (EditorUserBuildSettings.overrideTextureCompression !=
                UnityEditor.Build.OverrideTextureCompression.NoOverride)
                throw new InvalidOperationException("Unity texture compression override must be NoOverride");
        }

        private static TextureContract FindTextureContract(BuildInput input, string id)
        {
            TextureContractBinding[] matches = input.texture_contracts.Where(item => item != null && item.id == id).ToArray();
            if (matches.Length != 1 || matches[0].texture_contract == null)
                throw new InvalidDataException("Unknown or duplicate V2 texture contract: " + id);
            return matches[0].texture_contract;
        }

        private static void ValidateTextureContract(string id, TextureContract contract)
        {
            Match match = Regex.Match(
                id ?? "",
                "\\A(main|mask)-(bc7|rgba32)-(point|bilinear)-v1\\z",
                RegexOptions.CultureInvariant);
            if (!TextureContractIdPattern.IsMatch(id ?? "") || !match.Success || contract == null)
                throw new InvalidDataException("Malformed V2 texture contract: " + id);
            string format = match.Groups[2].Value == "bc7" ? "BC7" : "RGBA32";
            string filter = match.Groups[3].Value == "point" ? "Point" : "Bilinear";
            bool compressed = format == "BC7";
            int blockBytes = compressed ? 16 : 4;
            int blockDimension = compressed ? 4 : 1;
            int unityFormat = compressed ? 25 : 4;
            if (match.Groups[1].Value == "main" && !compressed)
                throw new InvalidDataException("V2 main texture contract is not BC7");
            if (contract.alpha_is_transparency || contract.alpha_source != "FromInput" ||
                contract.allows_alpha_splitting || contract.aniso_level != 0 ||
                contract.compression_quality != 100 || contract.crunched_compression ||
                contract.filter_mode != filter ||
                contract.force_maximum_compression_quality_bc6h_bc7 != compressed ||
                contract.format != format || contract.gpu_block_bytes != blockBytes ||
                contract.gpu_block_height != blockDimension || contract.gpu_block_width != blockDimension ||
                !contract.ignore_png_gamma || contract.max_texture_size != MaximumPageDimension ||
                contract.mipmaps || contract.npot_scale != "None" || !contract.platform_override ||
                contract.readable || !contract.s_rgb ||
                contract.streaming_mipmaps || contract.texture_type != "Default" ||
                contract.unity_texture_format != unityFormat ||
                contract.compression != (compressed ? "CompressedHQ" : "Uncompressed") ||
                contract.wrap_mode != "Clamp")
                throw new InvalidDataException("V2 texture contract values drifted: " + id);
        }

        private static long ExpectedGpuBytes(int width, int height, string format)
        {
            checked
            {
                if (format == "BC7") return ((long)(width + 3) / 4L) * ((long)(height + 3) / 4L) * 16L;
                if (format == "RGBA32") return (long)width * height * 4L;
            }
            throw new InvalidDataException("Unknown V2 texture format: " + format);
        }

        private static void ValidateEditorIdentity()
        {
            string full = InternalEditorUtility.GetFullUnityVersion();
            if (Application.unityVersion != UnityVersion || full != UnityFullVersion)
            {
                throw new InvalidOperationException("Exact Unity editor required: " + UnityFullVersion + "; actual: " + full);
            }
        }

        private static void ValidateEditorSource(BuildInput input, string projectPath)
        {
            string editorSource = Path.Combine(projectPath, "Assets", "Editor", "StrongholdEuropeAssetBundleBuilder.cs");
            if (Sha256(File.ReadAllBytes(editorSource)) != input.editor_script_sha256)
            {
                throw new InvalidDataException("Editor builder source hash drifted");
            }
        }

        private static void RequireExactOutputPaths(string projectPath, string outputPath, string indexOutputPath)
        {
            string expectedOutput = CanonicalFullPath(Path.Combine(projectPath, "..", "output", "Runtime", "AssetBundles", "win64"));
            string expectedIndex = CanonicalFullPath(Path.Combine(projectPath, "..", "output", "Runtime", "AssetBundles", "index.json"));
            if (!SamePath(outputPath, expectedOutput) || !SamePath(indexOutputPath, expectedIndex))
            {
                throw new InvalidOperationException("Runtime AssetBundle output path drifted");
            }
        }

        private static void RequireFreshOutputDirectory(string outputPath)
        {
            if (Directory.Exists(outputPath) && Directory.EnumerateFileSystemEntries(outputPath).Any())
            {
                throw new InvalidOperationException("Refusing to build into a non-empty output directory: " + outputPath);
            }
            Directory.CreateDirectory(outputPath);
        }

        private static void ConfigureAndVerifyTexture(string projectPath, TextureInput texture)
        {
            if (texture == null || texture.width <= 0 || texture.height <= 0 ||
                texture.width > MaximumPageDimension || texture.height > MaximumPageDimension ||
                !Sha256Pattern.IsMatch(texture.png_sha256 ?? ""))
            {
                throw new InvalidDataException("Invalid texture build input");
            }
            string filePath = ResolveAssetPath(projectPath, texture.asset_path);
            if (Sha256(File.ReadAllBytes(filePath)) != texture.png_sha256)
            {
                throw new InvalidDataException("Texture PNG hash drifted: " + texture.asset_path);
            }
            TextureImporter importer = AssetImporter.GetAtPath(texture.asset_path) as TextureImporter;
            if (importer == null)
            {
                AssetDatabase.ImportAsset(texture.asset_path, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
                importer = AssetImporter.GetAtPath(texture.asset_path) as TextureImporter;
            }
            if (importer == null)
            {
                throw new InvalidOperationException("TextureImporter unavailable: " + texture.asset_path);
            }

            importer.textureType = TextureImporterType.Default;
            importer.textureShape = TextureImporterShape.Texture2D;
            importer.sRGBTexture = true;
            importer.alphaSource = TextureImporterAlphaSource.FromInput;
            importer.alphaIsTransparency = false;
            importer.mipmapEnabled = false;
            importer.streamingMipmaps = false;
            importer.isReadable = false;
            importer.filterMode = FilterMode.Point;
            importer.wrapMode = TextureWrapMode.Clamp;
            importer.anisoLevel = 0;
            importer.npotScale = TextureImporterNPOTScale.None;
            importer.ignorePngGamma = true;
            importer.textureCompression = TextureImporterCompression.Uncompressed;
            importer.crunchedCompression = false;
            importer.maxTextureSize = MaximumPageDimension;

            TextureImporterPlatformSettings defaults = importer.GetDefaultPlatformTextureSettings();
            defaults.maxTextureSize = MaximumPageDimension;
            defaults.format = TextureImporterFormat.RGBA32;
            defaults.textureCompression = TextureImporterCompression.Uncompressed;
            defaults.crunchedCompression = false;
            defaults.compressionQuality = 100;
            importer.SetPlatformTextureSettings(defaults);

            TextureImporterPlatformSettings standalone = importer.GetPlatformTextureSettings("Standalone");
            standalone.name = "Standalone";
            standalone.overridden = true;
            standalone.maxTextureSize = MaximumPageDimension;
            standalone.format = TextureImporterFormat.RGBA32;
            standalone.textureCompression = TextureImporterCompression.Uncompressed;
            standalone.crunchedCompression = false;
            standalone.compressionQuality = 100;
            standalone.allowsAlphaSplitting = false;
            importer.SetPlatformTextureSettings(standalone);
            importer.SaveAndReimport();

            Texture2D imported = AssetDatabase.LoadAssetAtPath<Texture2D>(texture.asset_path);
            TextureImporterPlatformSettings verified = importer.GetPlatformTextureSettings("Standalone");
            if (imported == null || imported.width != texture.width || imported.height != texture.height ||
                imported.format != TextureFormat.RGBA32 || imported.mipmapCount != 1 || imported.isReadable ||
                imported.filterMode != FilterMode.Point || imported.wrapMode != TextureWrapMode.Clamp ||
                imported.anisoLevel != 0 || !importer.sRGBTexture || importer.mipmapEnabled ||
                importer.streamingMipmaps || importer.isReadable || !importer.ignorePngGamma ||
                importer.alphaSource != TextureImporterAlphaSource.FromInput || importer.alphaIsTransparency ||
                importer.npotScale != TextureImporterNPOTScale.None || importer.textureCompression != TextureImporterCompression.Uncompressed ||
                !verified.overridden || verified.format != TextureImporterFormat.RGBA32 ||
                verified.textureCompression != TextureImporterCompression.Uncompressed || verified.maxTextureSize != MaximumPageDimension)
            {
                throw new InvalidOperationException("Lossless RGBA32 import contract failed: " + texture.asset_path);
            }
        }

        private static void VerifyTextureV2(string projectPath, TextureInput texture, TextureContract contract)
        {
            if (texture == null || contract == null || texture.width <= 0 || texture.height <= 0 ||
                texture.width > MaximumPageDimension || texture.height > MaximumPageDimension ||
                !Sha256Pattern.IsMatch(texture.source_png_sha256 ?? "") ||
                !Sha256Pattern.IsMatch(texture.source_rgba_sha256 ?? ""))
                throw new InvalidDataException("Invalid V2 texture build input");
            string filePath = ResolveAssetPath(projectPath, texture.asset_path);
            if (Sha256(File.ReadAllBytes(filePath)) != texture.source_png_sha256)
                throw new InvalidDataException("V2 source PNG hash drifted: " + texture.asset_path);

            // Deliberately no ImportAsset, property assignment, SetPlatformTextureSettings,
            // Apply, or SaveAndReimport here.  The exact .meta existed before Unity loaded
            // the project; this method is a pure, fail-closed verifier.
            TextureImporter importer = AssetImporter.GetAtPath(texture.asset_path) as TextureImporter;
            Texture2D imported = AssetDatabase.LoadAssetAtPath<Texture2D>(texture.asset_path);
            if (importer == null || imported == null)
                throw new InvalidOperationException("V2 texture was not imported before ExecuteMethod: " + texture.asset_path);

            bool compressed = contract.format == "BC7";
            TextureImporterFormat expectedImporterFormat = compressed ? TextureImporterFormat.BC7 : TextureImporterFormat.RGBA32;
            TextureFormat expectedRuntimeFormat = compressed ? TextureFormat.BC7 : TextureFormat.RGBA32;
            TextureImporterCompression expectedCompression = compressed
                ? TextureImporterCompression.CompressedHQ
                : TextureImporterCompression.Uncompressed;
            FilterMode expectedFilter = contract.filter_mode == "Point" ? FilterMode.Point : FilterMode.Bilinear;
            TextureImporterPlatformSettings defaults = importer.GetDefaultPlatformTextureSettings();
            TextureImporterPlatformSettings standalone = importer.GetPlatformTextureSettings("Standalone");
            string forceMaximumDetail;
            bool forceMaximumValid = VerifyForceMaximumCompressionQuality(
                defaults, standalone, compressed ? 1 : 0, out forceMaximumDetail);
            bool valid = !(imported.width != texture.width || imported.height != texture.height ||
                imported.format != expectedRuntimeFormat || imported.mipmapCount != 1 || imported.isReadable ||
                imported.filterMode != expectedFilter || imported.wrapMode != TextureWrapMode.Clamp ||
                imported.anisoLevel != 0 || importer.textureType != TextureImporterType.Default ||
                importer.textureShape != TextureImporterShape.Texture2D || !importer.sRGBTexture ||
                importer.alphaSource != TextureImporterAlphaSource.FromInput || importer.alphaIsTransparency ||
                importer.mipmapEnabled || importer.streamingMipmaps || importer.isReadable ||
                importer.filterMode != expectedFilter || importer.wrapMode != TextureWrapMode.Clamp ||
                importer.anisoLevel != 0 || importer.npotScale != TextureImporterNPOTScale.None ||
                !importer.ignorePngGamma || importer.textureCompression != expectedCompression ||
                importer.crunchedCompression || importer.maxTextureSize != MaximumPageDimension ||
                !defaults.overridden || defaults.maxTextureSize != MaximumPageDimension ||
                defaults.format != expectedImporterFormat || defaults.textureCompression != expectedCompression ||
                defaults.crunchedCompression || defaults.compressionQuality != 100 || defaults.allowsAlphaSplitting ||
                !standalone.overridden || standalone.maxTextureSize != MaximumPageDimension ||
                standalone.format != expectedImporterFormat || standalone.textureCompression != expectedCompression ||
                standalone.crunchedCompression || standalone.compressionQuality != 100 || standalone.allowsAlphaSplitting ||
                !forceMaximumValid);
            if (!valid)
            {
                throw new InvalidOperationException(
                    "BC7 V2 import contract failed: " + texture.asset_path +
                    " imported={size:" + imported.width + "x" + imported.height +
                    ",format:" + imported.format + ",mips:" + imported.mipmapCount +
                    ",readable:" + imported.isReadable + ",filter:" + imported.filterMode +
                    ",wrap:" + imported.wrapMode + ",aniso:" + imported.anisoLevel + "}" +
                    " importer={type:" + importer.textureType + ",shape:" + importer.textureShape +
                    ",srgb:" + importer.sRGBTexture + ",alphaSource:" + importer.alphaSource +
                    ",alphaTransparency:" + importer.alphaIsTransparency + ",mips:" + importer.mipmapEnabled +
                    ",streaming:" + importer.streamingMipmaps + ",readable:" + importer.isReadable +
                    ",filter:" + importer.filterMode + ",wrap:" + importer.wrapMode +
                    ",aniso:" + importer.anisoLevel + ",npot:" + importer.npotScale +
                    ",ignoreGamma:" + importer.ignorePngGamma + ",compression:" + importer.textureCompression +
                    ",crunch:" + importer.crunchedCompression + ",max:" + importer.maxTextureSize + "}" +
                    " default={override:" + defaults.overridden + ",max:" + defaults.maxTextureSize +
                    ",format:" + defaults.format + ",compression:" + defaults.textureCompression +
                    ",crunch:" + defaults.crunchedCompression + ",quality:" + defaults.compressionQuality +
                    ",alphaSplit:" + defaults.allowsAlphaSplitting + "}" +
                    " standalone={override:" + standalone.overridden + ",max:" + standalone.maxTextureSize +
                    ",format:" + standalone.format + ",compression:" + standalone.textureCompression +
                    ",crunch:" + standalone.crunchedCompression + ",quality:" + standalone.compressionQuality +
                    ",alphaSplit:" + standalone.allowsAlphaSplitting + "}" +
                    " forceMaximum={" + forceMaximumDetail + "}");
            }
        }

        private static bool VerifyForceMaximumCompressionQuality(
            TextureImporterPlatformSettings defaults,
            TextureImporterPlatformSettings standalone,
            int expected,
            out string detail)
        {
            const string PropertyName = "forceMaximumCompressionQuality_BC6H_BC7";
            Type settingsType = typeof(TextureImporterPlatformSettings);
            System.Reflection.PropertyInfo property = settingsType.GetProperty(
                PropertyName,
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            if (property == null || property.PropertyType != typeof(int) ||
                property.GetIndexParameters().Length != 0 || property.GetGetMethod(true) == null)
            {
                detail = "property=" + (property == null ? "missing" : property.PropertyType.FullName) +
                    ",getter=" + (property != null && property.GetGetMethod(true) != null) +
                    ",expected=" + expected;
                return false;
            }

            object defaultRaw;
            object standaloneRaw;
            try
            {
                defaultRaw = property.GetValue(defaults, null);
                standaloneRaw = property.GetValue(standalone, null);
            }
            catch (Exception exception)
            {
                detail = "reflectionError=" + exception.GetType().FullName + ",expected=" + expected;
                return false;
            }

            if (!(defaultRaw is int) || !(standaloneRaw is int))
            {
                detail = "defaultType=" + (defaultRaw == null ? "null" : defaultRaw.GetType().FullName) +
                    ",standaloneType=" + (standaloneRaw == null ? "null" : standaloneRaw.GetType().FullName) +
                    ",expected=" + expected;
                return false;
            }

            int defaultValue = (int)defaultRaw;
            int standaloneValue = (int)standaloneRaw;
            detail = "default=" + defaultValue + ",standalone=" + standaloneValue + ",expected=" + expected;
            return defaultValue == expected && standaloneValue == expected;
        }

        private static AssetBundleBuild[] CreateBuildMaps(BuildInput input)
        {
            HashSet<string> assetPaths = new HashSet<string>(StringComparer.Ordinal);
            HashSet<string> addresses = new HashSet<string>(StringComparer.Ordinal);
            List<AssetBundleBuild> result = new List<AssetBundleBuild>();
            foreach (BundleInput bundle in input.bundles)
            {
                if (bundle.assets == null || bundle.assets.Length == 0 ||
                    !bundle.assets.Select(item => item.address).SequenceEqual(
                        bundle.assets.Select(item => item.address).OrderBy(value => value, StringComparer.Ordinal)))
                {
                    throw new InvalidDataException("Bundle assets are empty or unsorted: " + bundle.name);
                }
                foreach (BundleAssetInput asset in bundle.assets)
                {
                    RequireSafeAssetPath(asset.asset_path);
                    if (String.IsNullOrEmpty(asset.address) || !assetPaths.Add(asset.asset_path) || !addresses.Add(asset.address))
                    {
                        throw new InvalidDataException("Duplicate asset path/address in build input");
                    }
                    if (AssetDatabase.LoadMainAssetAtPath(asset.asset_path) == null)
                    {
                        throw new InvalidOperationException("Bundle asset could not be imported: " + asset.asset_path);
                    }
                }
                result.Add(new AssetBundleBuild
                {
                    assetBundleName = bundle.name,
                    assetNames = bundle.assets.Select(item => item.asset_path).ToArray(),
                    addressableNames = bundle.assets.Select(item => item.address).ToArray(),
                });
            }
            return result.ToArray();
        }

        private static void VerifyBundleSet(AssetBundleManifest manifest, BundleInput[] bundles)
        {
            string[] expected = bundles.Select(item => item.name).OrderBy(value => value, StringComparer.Ordinal).ToArray();
            string[] actual = manifest.GetAllAssetBundles().OrderBy(value => value, StringComparer.Ordinal).ToArray();
            if (!expected.SequenceEqual(actual))
            {
                throw new InvalidOperationException("Built AssetBundle set drifted");
            }
        }

        private static void VerifyOutputFileSet(string outputPath, BundleInput[] bundles)
        {
            HashSet<string> expected = new HashSet<string>(StringComparer.Ordinal)
            {
                "win64",
                "win64.manifest",
            };
            foreach (BundleInput bundle in bundles)
            {
                expected.Add(bundle.name);
                expected.Add(bundle.name + ".manifest");
            }
            string[] actual = Directory.GetFiles(outputPath).Select(Path.GetFileName).OrderBy(value => value, StringComparer.Ordinal).ToArray();
            if (!expected.OrderBy(value => value, StringComparer.Ordinal).SequenceEqual(actual) || Directory.GetDirectories(outputPath).Length != 0)
            {
                throw new InvalidOperationException("Unity output file set drifted");
            }
        }

        private static void ValidateIndexTemplate(
            IndexTemplate template,
            BuildInput input,
            string projectPath)
        {
            if (template == null || template.schema != IndexTemplateSchema || template.build_id != input.build_id ||
                template.unity == null || template.unity.version != UnityVersion || template.unity.revision != UnityRevision ||
                template.build_target != BuildTargetName || template.max_page_dimension != MaximumPageDimension ||
                template.groups == null ||
                template.groups.Length > MaximumGroups ||
                template.vanilla_omitted_groups == null ||
                template.groups.Length + template.vanilla_omitted_groups.Length <= 0 ||
                template.groups.Length + template.vanilla_omitted_groups.Length > MaximumGroups ||
                template.groups.Length != input.bundles.Length)
            {
                throw new InvalidDataException("Index template identity drifted");
            }
            string[] templateBundles = template.groups.Select(group => group.bundle).ToArray();
            string[] inputBundles = input.bundles.Select(bundle => bundle.name).ToArray();
            if (!templateBundles.OrderBy(value => value, StringComparer.Ordinal).SequenceEqual(
                    inputBundles.OrderBy(value => value, StringComparer.Ordinal)))
            {
                throw new InvalidDataException("Index template bundle order/set drifted");
            }
            string[] groupOrder = template.groups.Select(group => group == null ? null : group.group).ToArray();
            string[] omittedOrder = template.vanilla_omitted_groups.Select(
                group => group == null ? null : group.group).ToArray();
            if (groupOrder.Any(value => value == null) || omittedOrder.Any(value => value == null) ||
                !groupOrder.SequenceEqual(groupOrder.OrderBy(value => value, StringComparer.Ordinal)) ||
                !omittedOrder.SequenceEqual(omittedOrder.OrderBy(value => value, StringComparer.Ordinal)))
            {
                throw new InvalidDataException("Index selected groups are null or unsorted");
            }
            HashSet<string> selectedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            HashSet<string> selectedSlugs = new HashSet<string>(StringComparer.Ordinal);
            HashSet<int> selectedIds = new HashSet<int>();
            foreach (OmittedGroupTemplate omitted in template.vanilla_omitted_groups)
            {
                bool frameReason = omitted.reason == "v1_frame_count_exceeded";
                bool slotReason = omitted.reason == "v1_slot_count_exceeded";
                bool reasonFieldsAgree = frameReason
                    ? omitted.frame_count > MaximumFramesPerGroup
                    : slotReason
                        ? omitted.frame_count <= MaximumFramesPerGroup && omitted.array_size > MaximumFramesPerGroup
                        : omitted.frame_count <= MaximumFramesPerGroup && omitted.array_size <= MaximumFramesPerGroup;
                if (!GroupPattern.IsMatch(omitted.group ?? "") ||
                    omitted.gm_id < 0 || omitted.gm_id >= MaximumGroups ||
                    omitted.array_size <= 0 ||
                    omitted.frame_count <= 0 || omitted.frame_count > MaximumPreflightFramesPerGroup ||
                    !OmissionReasons.Contains(omitted.reason ?? "") || !reasonFieldsAgree ||
                    !Sha256Pattern.IsMatch(omitted.names_sha256 ?? "") ||
                    !Sha256Pattern.IsMatch(omitted.frames_sha256 ?? "") ||
                    !selectedNames.Add(omitted.group) || !selectedIds.Add(omitted.gm_id))
                {
                    throw new InvalidDataException("Invalid vanilla omission binding");
                }
            }
            foreach (IndexGroupTemplate group in template.groups)
            {
                string expectedMaterial = group == null ? null : ExpectedMaterialBinding(group.group, group.mask_policy);
                if (group == null ||
                    !GroupPattern.IsMatch(group.group ?? "") ||
                    !SlugPattern.IsMatch(group.slug ?? "") ||
                    group.slug != GroupSlug(group.group) ||
                    group.gm_id < 0 || group.gm_id >= MaximumGroups ||
                    group.array_size <= 0 || group.array_size > MaximumFramesPerGroup || group.lifetime != "map" ||
                    group.page_count <= 0 || group.page_count > MaximumPagesPerGroup ||
                    group.frame_count <= 0 || group.frame_count > MaximumFramesPerGroup ||
                    group.pages == null || group.pages.Length != group.page_count ||
                    group.material_binding != expectedMaterial ||
                    (expectedMaterial == "group_mask_single_page_v1" && group.page_count != 1) ||
                    group.raw_rgba_bytes <= 0 || group.resident_charge_bytes != ResidentCharge(group.raw_rgba_bytes) ||
                    !Sha256Pattern.IsMatch(group.atlas_sha256 ?? "") || !Sha256Pattern.IsMatch(group.names_sha256 ?? "") ||
                    !Sha256Pattern.IsMatch(group.frames_sha256 ?? "") ||
                    !selectedNames.Add(group.group) || !selectedSlugs.Add(group.slug) ||
                    !selectedIds.Add(group.gm_id))
                {
                    throw new InvalidDataException("Index template group contract drifted");
                }
                for (int pageIndex = 0; pageIndex < group.pages.Length; ++pageIndex)
                {
                    IndexPage page = group.pages[pageIndex];
                    string pageOrdinal = pageIndex.ToString("D3", CultureInfo.InvariantCulture);
                    string addressPrefix = "sede/gm/" + group.slug + "/page/" + pageOrdinal + "/";
                    bool hasMaskAddress = page != null && !String.IsNullOrEmpty(page.mask_address);
                    bool hasMaskDigest = page != null && !String.IsNullOrEmpty(page.mask_rgba_sha256);
                    bool maskRequired = group.mask_policy == "required";
                    if (page == null || page.id != pageIndex ||
                        page.width <= 0 || page.width > MaximumPageDimension ||
                        page.height <= 0 || page.height > MaximumPageDimension ||
                        page.main_address != addressPrefix + "main" ||
                        !Sha256Pattern.IsMatch(page.main_rgba_sha256 ?? "") ||
                        hasMaskAddress != hasMaskDigest || hasMaskAddress != maskRequired ||
                        (hasMaskAddress && page.mask_address != addressPrefix + "mask") ||
                        (hasMaskDigest && !Sha256Pattern.IsMatch(page.mask_rgba_sha256 ?? "")))
                    {
                        throw new InvalidDataException(
                            "Index template page contract drifted: " + group.group + "[" + pageIndex + "]");
                    }
                }
                string atlasPath = ResolveAssetPath(projectPath, group.atlas_asset_path);
                FileInfo atlasInfo = new FileInfo(atlasPath);
                if (!atlasInfo.Exists || atlasInfo.Length <= 0 ||
                    atlasInfo.Length > MaximumAtlasDocumentBytes)
                {
                    throw new InvalidDataException(
                        "atlas.v2 document is missing, empty, or oversized: " + group.group);
                }
            }
        }

        private static string ExpectedMaterialBinding(string group, string maskPolicy)
        {
            if (maskPolicy == "forbidden") return "plain_shared_v1";
            if (maskPolicy == "required")
            {
                return PostfixMaterialGroups.Contains((group ?? "").ToLowerInvariant())
                    ? "set_body_sprite_postfix_page_mask_v1"
                    : "group_mask_single_page_v1";
            }
            throw new InvalidDataException("Unknown mask policy: " + maskPolicy);
        }

        private static string GroupSlug(string group)
        {
            return (group ?? String.Empty).ToLowerInvariant().Replace(' ', '_');
        }

        private static long ResidentCharge(long rawBytes)
        {
            checked
            {
                long adjusted = (rawBytes * 9L + 7L) / 8L;
                const long alignment = 64L * 1024L * 1024L;
                return ((adjusted + alignment - 1L) / alignment) * alignment;
            }
        }

        private static long PredictedLoadPeak(long residentChargeBytes, long bundleSizeBytes)
        {
            if (residentChargeBytes <= 0 || bundleSizeBytes <= 0)
                throw new InvalidDataException("Predicted load peak inputs must be positive");
            checked
            {
                const long alignment = 64L * 1024L * 1024L;
                const long fixedOverhead = 256L * 1024L * 1024L;
                long alignedBundle = ((bundleSizeBytes + alignment - 1L) / alignment) * alignment;
                return 2L * residentChargeBytes + alignedBundle + fixedOverhead;
            }
        }

        private static void WriteFinalIndex(string path, IndexTemplate template, List<BundleArtifact> artifacts)
        {
            Dictionary<string, BundleArtifact> byName = artifacts.ToDictionary(item => item.name, StringComparer.Ordinal);
            StringBuilder json = new StringBuilder(16384);
            json.Append('{');
            AppendProperty(json, "build_id", template.build_id, true);
            AppendProperty(json, "build_target", template.build_target, false);
            json.Append(",\"groups\":[");
            for (int i = 0; i < template.groups.Length; ++i)
            {
                if (i != 0) json.Append(',');
                IndexGroupTemplate group = template.groups[i];
                BundleArtifact artifact;
                if (!byName.TryGetValue(group.bundle, out artifact))
                    throw new InvalidDataException("Index template references unbuilt bundle: " + group.bundle);
                AppendFinalGroup(json, group, artifact);
            }
            json.Append(']');
            AppendProperty(json, "max_page_dimension", template.max_page_dimension, false);
            AppendProperty(json, "schema", IndexSchema, false);
            json.Append(",\"unity\":{");
            AppendProperty(json, "revision", template.unity.revision, true);
            AppendProperty(json, "version", template.unity.version, false);
            json.Append('}');
            json.Append(",\"vanilla_omitted_groups\":[");
            for (int i = 0; i < template.vanilla_omitted_groups.Length; ++i)
            {
                if (i != 0) json.Append(',');
                OmittedGroupTemplate omitted = template.vanilla_omitted_groups[i];
                json.Append('{');
                AppendProperty(json, "array_size", omitted.array_size, true);
                AppendProperty(json, "frame_count", omitted.frame_count, false);
                AppendProperty(json, "frames_sha256", omitted.frames_sha256, false);
                AppendProperty(json, "gm_id", omitted.gm_id, false);
                AppendProperty(json, "group", omitted.group, false);
                AppendProperty(json, "names_sha256", omitted.names_sha256, false);
                AppendProperty(json, "reason", omitted.reason, false);
                json.Append('}');
            }
            json.Append("]}\n");
            byte[] payload = Utf8.GetBytes(json.ToString());
            if (payload.Length > MaximumIndexBytes)
                throw new InvalidDataException("Final external index exceeds its 4-MiB bound");
            AtomicWriteNew(path, payload);
        }

        private static void AppendFinalGroup(StringBuilder json, IndexGroupTemplate group, BundleArtifact artifact)
        {
            json.Append('{');
            AppendProperty(json, "array_size", group.array_size, true);
            AppendProperty(json, "atlas_address", group.atlas_address, false);
            AppendProperty(json, "atlas_asset_path", group.atlas_asset_path, false);
            AppendProperty(json, "atlas_sha256", group.atlas_sha256, false);
            AppendProperty(json, "bundle", group.bundle, false);
            AppendProperty(json, "bundle_crc32", artifact.crc32, false);
            AppendProperty(json, "bundle_path", artifact.modRelativePath, false);
            AppendProperty(json, "bundle_sha256", artifact.sha256, false);
            AppendProperty(json, "bundle_size_bytes", artifact.sizeBytes, false);
            AppendProperty(json, "dash_format", group.dash_format, false);
            AppendProperty(json, "frame_count", group.frame_count, false);
            AppendProperty(json, "frames_sha256", group.frames_sha256, false);
            AppendProperty(json, "gm_id", group.gm_id, false);
            AppendProperty(json, "group", group.group, false);
            AppendProperty(json, "lifetime", group.lifetime, false);
            AppendProperty(json, "mask_policy", group.mask_policy, false);
            AppendProperty(json, "material_binding", group.material_binding, false);
            AppendProperty(json, "names_sha256", group.names_sha256, false);
            AppendProperty(json, "page_count", group.page_count, false);
            json.Append(",\"pages\":[");
            for (int i = 0; i < group.pages.Length; ++i)
            {
                if (i != 0) json.Append(',');
                IndexPage page = group.pages[i];
                json.Append('{');
                AppendProperty(json, "height", page.height, true);
                AppendProperty(json, "id", page.id, false);
                AppendProperty(json, "main_address", page.main_address, false);
                AppendProperty(json, "main_rgba_sha256", page.main_rgba_sha256, false);
                AppendNullableProperty(json, "mask_address", page.mask_address, false);
                AppendNullableProperty(json, "mask_rgba_sha256", page.mask_rgba_sha256, false);
                AppendProperty(json, "width", page.width, false);
                json.Append('}');
            }
            json.Append(']');
            AppendProperty(
                json,
                "predicted_load_peak_bytes",
                PredictedLoadPeak(group.resident_charge_bytes, artifact.sizeBytes),
                false);
            AppendProperty(json, "raw_rgba_bytes", group.raw_rgba_bytes, false);
            AppendProperty(json, "resident_charge_bytes", group.resident_charge_bytes, false);
            AppendProperty(json, "slug", group.slug, false);
            AppendProperty(json, "unity_hash128", artifact.manifestHash, false);
            json.Append('}');
        }

        private static void WriteReport(string path, Report report)
        {
            if (report.v2)
            {
                WriteReportV2(path, report);
                return;
            }
            StringBuilder json = new StringBuilder(8192);
            json.Append('{');
            AppendProperty(json, "build_id", report.buildId, true);
            AppendProperty(json, "build_input_sha256", report.buildInputSha256, false);
            json.Append(",\"build_options\":[");
            for (int i = 0; i < ExactBuildOptions.Length; ++i)
            {
                if (i != 0) json.Append(',');
                AppendQuoted(json, ExactBuildOptions[i]);
            }
            json.Append(']');
            AppendProperty(json, "build_target", BuildTargetName, false);
            json.Append(",\"bundles\":[");
            for (int i = 0; i < report.bundles.Count; ++i)
            {
                if (i != 0) json.Append(',');
                BundleArtifact bundle = report.bundles[i];
                json.Append('{');
                AppendProperty(json, "manifest_hash", bundle.manifestHash, true);
                AppendProperty(json, "mod_relative_path", bundle.modRelativePath, false);
                AppendProperty(json, "name", bundle.name, false);
                AppendProperty(json, "sha256", bundle.sha256, false);
                AppendProperty(json, "size_bytes", bundle.sizeBytes, false);
                json.Append('}');
            }
            json.Append(']');
            AppendProperty(json, "error", report.error ?? string.Empty, false);
            AppendProperty(json, "schema", BuildReportSchema, false);
            AppendProperty(json, "success", report.success, false);
            json.Append(",\"textures\":[");
            for (int i = 0; i < report.textures.Count; ++i)
            {
                if (i != 0) json.Append(',');
                TextureReport texture = report.textures[i];
                json.Append('{');
                AppendProperty(json, "alpha_is_transparency", false, true);
                AppendProperty(json, "alpha_source", "FromInput", false);
                AppendProperty(json, "asset_path", texture.assetPath, false);
                AppendProperty(json, "filter_mode", "Point", false);
                AppendProperty(json, "format", "RGBA32", false);
                AppendProperty(json, "height", texture.height, false);
                AppendProperty(json, "mipmaps", false, false);
                AppendProperty(json, "npot_scale", "None", false);
                AppendProperty(json, "png_sha256", texture.pngSha256, false);
                AppendProperty(json, "readable", false, false);
                AppendProperty(json, "s_rgb", true, false);
                AppendProperty(json, "width", texture.width, false);
                AppendProperty(json, "wrap_mode", "Clamp", false);
                json.Append('}');
            }
            json.Append(']');
            json.Append(",\"unity\":{");
            AppendProperty(json, "revision", UnityRevision, true);
            AppendProperty(json, "version", UnityVersion, false);
            json.Append("}}\n");
            byte[] payload = Utf8.GetBytes(json.ToString());
            if (payload.Length > MaximumReportBytes)
                throw new InvalidDataException("Build report exceeds its 64-MiB bound");
            AtomicWriteNew(path, payload);
        }

        private static void WriteReportV2(string path, Report report)
        {
            StringBuilder json = new StringBuilder(16384);
            json.Append('{');
            AppendProperty(json, "build_id", report.buildId, true);
            AppendProperty(json, "build_input_sha256", report.buildInputSha256, false);
            json.Append(",\"build_options\":[");
            for (int i = 0; i < ExactBuildOptions.Length; ++i)
            {
                if (i != 0) json.Append(',');
                AppendQuoted(json, ExactBuildOptions[i]);
            }
            json.Append(']');
            AppendProperty(json, "build_target", BuildTargetName, false);
            json.Append(",\"bundles\":[");
            for (int i = 0; i < report.bundles.Count; ++i)
            {
                if (i != 0) json.Append(',');
                BundleArtifact bundle = report.bundles[i];
                json.Append('{');
                AppendProperty(json, "manifest_hash", bundle.manifestHash, true);
                AppendProperty(json, "mod_relative_path", bundle.modRelativePath, false);
                AppendProperty(json, "name", bundle.name, false);
                AppendProperty(json, "sha256", bundle.sha256, false);
                AppendProperty(json, "size_bytes", bundle.sizeBytes, false);
                json.Append('}');
            }
            json.Append(']');
            AppendProperty(json, "error", report.error ?? String.Empty, false);
            AppendNullProperty(json, "index_sha256", false);
            AppendNullProperty(json, "quality_report_sha256", false);
            AppendProperty(json, "schema", UnityBuildReportSchemaV2, false);
            AppendProperty(json, "success", report.success, false);
            json.Append(",\"textures\":[");
            for (int i = 0; i < report.textures.Count; ++i)
            {
                if (i != 0) json.Append(',');
                TextureReport texture = report.textures[i];
                json.Append('{');
                AppendProperty(json, "asset_path", texture.assetPath, true);
                AppendProperty(json, "gpu_bytes", texture.gpuBytes, false);
                AppendProperty(json, "height", texture.height, false);
                AppendProperty(json, "plane", texture.plane, false);
                AppendProperty(json, "source_png_sha256", texture.pngSha256, false);
                AppendProperty(json, "source_rgba_bytes", texture.sourceRgbaBytes, false);
                AppendProperty(json, "source_rgba_sha256", texture.sourceRgbaSha256, false);
                AppendProperty(json, "texture_contract", texture.textureContractId, false);
                AppendProperty(json, "width", texture.width, false);
                json.Append('}');
            }
            json.Append(']');
            json.Append(",\"unity\":{");
            AppendProperty(json, "revision", UnityRevision, true);
            AppendProperty(json, "version", UnityVersion, false);
            json.Append('}');
            AppendProperty(json, "verified", false, false);
            json.Append("}\n");
            byte[] payload = Utf8.GetBytes(json.ToString());
            if (payload.Length > MaximumReportBytes)
                throw new InvalidDataException("V2 Unity build report exceeds its 64-MiB bound");
            AtomicWriteNew(path, payload);
        }

        private static byte[] ReadBoundedBytes(string path, int maximumBytes, string label)
        {
            FileInfo info = new FileInfo(path);
            if (!info.Exists || info.Length <= 0 || info.Length > maximumBytes)
                throw new InvalidDataException(label + " is missing, empty, or oversized");
            return File.ReadAllBytes(path);
        }

        private static void AppendProperty(StringBuilder json, string key, string value, bool first)
        {
            if (!first) json.Append(',');
            AppendQuoted(json, key);
            json.Append(':');
            AppendQuoted(json, value);
        }

        private static void AppendNullableProperty(StringBuilder json, string key, string value, bool first)
        {
            if (!first) json.Append(',');
            AppendQuoted(json, key);
            json.Append(':');
            // Unity JsonUtility materializes a JSON null string field as an
            // empty string.  Canonicalize both representations back to JSON
            // null so an unmasked template round-trips byte-for-field.
            if (String.IsNullOrEmpty(value)) json.Append("null"); else AppendQuoted(json, value);
        }

        private static void AppendNullProperty(StringBuilder json, string key, bool first)
        {
            if (!first) json.Append(',');
            AppendQuoted(json, key);
            json.Append(":null");
        }

        private static void AppendProperty(StringBuilder json, string key, long value, bool first)
        {
            if (!first) json.Append(',');
            AppendQuoted(json, key);
            json.Append(':').Append(value.ToString(CultureInfo.InvariantCulture));
        }

        private static void AppendProperty(StringBuilder json, string key, bool value, bool first)
        {
            if (!first) json.Append(',');
            AppendQuoted(json, key);
            json.Append(value ? ":true" : ":false");
        }

        private static void AppendQuoted(StringBuilder json, string value)
        {
            if (value == null) throw new InvalidDataException("Required JSON string is null");
            json.Append('"');
            foreach (char character in value)
            {
                switch (character)
                {
                    case '"': json.Append("\\\""); break;
                    case '\\': json.Append("\\\\"); break;
                    case '\b': json.Append("\\b"); break;
                    case '\f': json.Append("\\f"); break;
                    case '\n': json.Append("\\n"); break;
                    case '\r': json.Append("\\r"); break;
                    case '\t': json.Append("\\t"); break;
                    default:
                        if (character < 0x20) json.Append("\\u").Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                        else json.Append(character);
                        break;
                }
            }
            json.Append('"');
        }

        private static void AtomicWriteNew(string path, byte[] payload)
        {
            string parent = Directory.GetParent(path).FullName;
            Directory.CreateDirectory(parent);
            if (File.Exists(path)) throw new IOException("Refusing to overwrite existing file: " + path);
            string temporary = path + ".tmp-" + System.Diagnostics.Process.GetCurrentProcess().Id.ToString(CultureInfo.InvariantCulture);
            using (FileStream stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                stream.Write(payload, 0, payload.Length);
                stream.Flush(true);
            }
            File.Move(temporary, path);
        }

        private static string ResolveAssetPath(string projectPath, string assetPath)
        {
            RequireSafeAssetPath(assetPath);
            string resolved = CanonicalFullPath(Path.Combine(projectPath, assetPath.Replace('/', Path.DirectorySeparatorChar)));
            string assetsRoot = CanonicalFullPath(Path.Combine(projectPath, "Assets"));
            if (!resolved.StartsWith(assetsRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Asset path escaped Assets/: " + assetPath);
            return resolved;
        }

        private static void RequireSafeAssetPath(string assetPath)
        {
            if (String.IsNullOrEmpty(assetPath) || !assetPath.StartsWith("Assets/", StringComparison.Ordinal) ||
                assetPath.Contains("\\") || assetPath.Split('/').Any(part => part.Length == 0 || part == "." || part == ".."))
                throw new InvalidDataException("Unsafe Unity asset path: " + assetPath);
        }

        private static string ResolveProjectRelative(string projectPath, string relativePath)
        {
            if (String.IsNullOrEmpty(relativePath) || relativePath.Contains("\\") || Path.IsPathRooted(relativePath))
                throw new InvalidDataException("Unsafe project-relative output path");
            return CanonicalFullPath(Path.Combine(projectPath, relativePath.Replace('/', Path.DirectorySeparatorChar)));
        }

        private static string CanonicalFullPath(string path)
        {
            return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        }

        private static bool SamePath(string left, string right)
        {
            return String.Equals(CanonicalFullPath(left), CanonicalFullPath(right), StringComparison.OrdinalIgnoreCase);
        }

        private static bool SameParent(string file, string parent)
        {
            return SamePath(Directory.GetParent(file).FullName, parent);
        }

        private static string Sha256(byte[] payload)
        {
            using (SHA256 digest = SHA256.Create())
                return String.Concat(digest.ComputeHash(payload).Select(value => value.ToString("x2", CultureInfo.InvariantCulture)));
        }

        private static string Crc32(string path)
        {
            uint crc = 0xffffffffU;
            byte[] buffer = new byte[1024 * 1024];
            using (FileStream stream = File.OpenRead(path))
            {
                int count;
                while ((count = stream.Read(buffer, 0, buffer.Length)) != 0)
                {
                    for (int i = 0; i < count; ++i)
                    {
                        crc ^= buffer[i];
                        for (int bit = 0; bit < 8; ++bit)
                            crc = (crc >> 1) ^ (0xedb88320U & (uint)-(int)(crc & 1U));
                    }
                }
            }
            return (crc ^ 0xffffffffU).ToString("x8", CultureInfo.InvariantCulture);
        }
    }
}
