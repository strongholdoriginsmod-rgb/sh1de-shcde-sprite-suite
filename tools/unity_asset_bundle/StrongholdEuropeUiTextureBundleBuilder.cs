// Deterministic Unity 2021.3 editor builder for direct, GPU-only UI textures.
//
// The Python pipeline copies this source and only cache-miss PNGs into an
// ephemeral Unity project.  Every input entry becomes one BC7 Texture2D in one
// independently replaceable AssetBundle.  No game payload is embedded here.

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

namespace StrongholdEuropeDE.UiAssetBundles
{
    public static class StrongholdEuropeUiTextureBundleBuilder
    {
        private const string UnityVersion = "2021.3.45f2";
        private const string UnityRevision = "88f88f591b2e";
        private const string UnityFullVersion = "2021.3.45f2 (88f88f591b2e)";
        private const string InputSchema = "stronghold-europe-de.ui-asset-bundle-build-input.v1";
        private const string ReportSchema = "stronghold-europe-de.ui-asset-bundle-build-report.v1";
        private const string BuildTargetName = "StandaloneWindows64";
        private const string InputRelativePath = "../ui-build-input.v1.json";
        private const string OutputRelativePath = "../output/Runtime/UiAssetBundles/win64";
        private const string ReportRelativePath = "../output/ui-build-report.v1.json";
        private const string AssetDirectory = "Assets/Generated/UiTextures";
        private const string ModBundleDirectory = "Runtime/UiAssetBundles/win64";
        private const int MaximumTextureDimension = 8192;
        private const int MaximumEntries = 4096;
        private const int MaximumInputBytes = 16 * 1024 * 1024;
        private const int MaximumReportBytes = 16 * 1024 * 1024;
        private const long MaximumPngBytes = 512L * 1024L * 1024L;

        private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);
        private static readonly Regex Sha256Pattern = new Regex(
            "\\A[0-9a-f]{64}\\z", RegexOptions.CultureInvariant);
        private static readonly Regex Hash16Pattern = new Regex(
            "\\A[0-9a-f]{16}\\z", RegexOptions.CultureInvariant);
        private static readonly Regex IdentifierPattern = new Regex(
            "\\A[a-z0-9](?:[a-z0-9._/-]{0,254}[a-z0-9])?\\z",
            RegexOptions.CultureInvariant);
        private static readonly Regex BundlePattern = new Regex(
            "\\Asede\\.ui\\.[0-9a-f]{16}\\.bc7\\.v1\\z",
            RegexOptions.CultureInvariant);
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
            public string revision;
            public string version;
        }

        [Serializable]
        private sealed class EntryInput
        {
            public string address;
            public bool alpha;
            public string asset_path;
            public string bundle_name;
            public string filter_mode;
            public long gpu_bytes;
            public int height;
            public string id;
            public string noesis_path;
            public string source_png_sha256;
            public string texture_name;
            public int width;
        }

        [Serializable]
        private sealed class BuildInput
        {
            public string build_id;
            public string[] build_options;
            public string build_target;
            public string editor_script_sha256;
            public EntryInput[] entries;
            public string output_relative_path;
            public string report_relative_path;
            public string schema;
            public UnityIdentity unity;
        }

        private sealed class EntryReport
        {
            public EntryInput input;
            public string bundleCrc32;
            public string bundleRelativePath;
            public string bundleSha256;
            public long bundleSizeBytes;
            public string unityHash128;
        }

        private sealed class BuildReport
        {
            public string buildId = new string('0', 64);
            public string buildInputSha256 = new string('0', 64);
            public readonly List<EntryReport> entries = new List<EntryReport>();
            public string error = String.Empty;
            public bool success;
        }

        public static void Build()
        {
            int exitCode = 1;
            BuildReport report = new BuildReport();
            string reportPath = null;
            try
            {
                string projectPath = CanonicalFullPath(
                    Directory.GetParent(Application.dataPath).FullName);
                ValidateProjectPlacement(projectPath);

                string inputPath = CanonicalFullPath(
                    Path.Combine(projectPath, InputRelativePath));
                reportPath = CanonicalFullPath(
                    Path.Combine(projectPath, ReportRelativePath));
                ValidateFixedPaths(projectPath, inputPath, reportPath);
                if (File.Exists(reportPath))
                    throw new IOException("Refusing to overwrite a stale UI build report: " + reportPath);

                byte[] inputBytes = ReadBoundedBytes(
                    inputPath, MaximumInputBytes, "UI AssetBundle build input");
                report.buildInputSha256 = Sha256(inputBytes);
                string inputJson = Utf8.GetString(inputBytes);
                BuildInput input = JsonUtility.FromJson<BuildInput>(inputJson);
                ValidateInput(input, inputBytes, projectPath);
                report.buildId = input.build_id;

                ValidateEditorIdentity();
                ValidateEditorSource(input, projectPath);
                VerifySourceFileSet(projectPath, input.entries);
                if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.StandaloneWindows64)
                    throw new InvalidOperationException("Active Unity build target must be StandaloneWindows64");
                if (EditorUserBuildSettings.overrideTextureCompression !=
                    UnityEditor.Build.OverrideTextureCompression.NoOverride)
                    throw new InvalidOperationException("Unity texture compression override must be NoOverride");

                string outputPath = ResolveProjectRelative(
                    projectPath, input.output_relative_path);
                RequireExactOutputPath(projectPath, outputPath);
                RequireFreshOutputDirectory(outputPath);

                foreach (EntryInput entry in input.entries)
                    ConfigureAndVerifyTexture(projectPath, entry);

                // The complete importer/runtime contract is verified above.  No
                // importer mutation is permitted between this point and the build.
                AssetBundleBuild[] maps = CreateBuildMaps(input.entries);
                AssetBundleManifest manifest = BuildPipeline.BuildAssetBundles(
                    outputPath,
                    maps,
                    BuildAssetBundleOptions.ChunkBasedCompression |
                    BuildAssetBundleOptions.DeterministicAssetBundle |
                    BuildAssetBundleOptions.ForceRebuildAssetBundle |
                    BuildAssetBundleOptions.StrictMode,
                    BuildTarget.StandaloneWindows64);
                if (manifest == null)
                    throw new InvalidOperationException("BuildPipeline.BuildAssetBundles returned null");

                VerifyBundleSet(manifest, input.entries);
                foreach (EntryInput entry in input.entries)
                {
                    string bundlePath = CanonicalFullPath(
                        Path.Combine(outputPath, entry.bundle_name));
                    if (!File.Exists(bundlePath) || !SameParent(bundlePath, outputPath))
                        throw new InvalidOperationException(
                            "Expected UI AssetBundle is missing or escaped output: " + entry.bundle_name);

                    FileInfo info = new FileInfo(bundlePath);
                    string unityHash = manifest.GetAssetBundleHash(entry.bundle_name)
                        .ToString().ToLowerInvariant();
                    if (info.Length <= 0 || !Regex.IsMatch(
                            unityHash, "\\A[0-9a-f]{32}\\z", RegexOptions.CultureInvariant))
                        throw new InvalidOperationException(
                            "Invalid built UI AssetBundle metadata: " + entry.bundle_name);

                    VerifyBuiltBundle(bundlePath, entry);
                    report.entries.Add(new EntryReport
                    {
                        input = entry,
                        bundleCrc32 = Crc32(bundlePath),
                        bundleRelativePath = ModBundleDirectory + "/" + entry.bundle_name,
                        bundleSha256 = Sha256File(bundlePath),
                        bundleSizeBytes = info.Length,
                        unityHash128 = unityHash,
                    });
                }
                VerifyOutputFileSet(outputPath, input.entries);

                report.success = true;
                report.error = String.Empty;
                WriteReport(reportPath, report);
                exitCode = 0;
                Debug.Log(
                    "Stronghold Europe direct UI BC7 AssetBundle build completed: " +
                    input.build_id + " entries=" + input.entries.Length.ToString(CultureInfo.InvariantCulture));
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

        private static void ValidateProjectPlacement(string projectPath)
        {
            DirectoryInfo project = new DirectoryInfo(projectPath);
            DirectoryInfo build = project.Parent;
            if (project.Name != "project" || build == null ||
                !Hash16Pattern.IsMatch(build.Name))
                throw new InvalidOperationException(
                    "UI Unity project must be placed at <build-hash16>/project");
        }

        private static void ValidateFixedPaths(
            string projectPath,
            string inputPath,
            string reportPath)
        {
            string expectedInput = CanonicalFullPath(
                Path.Combine(projectPath, "..", "ui-build-input.v1.json"));
            string expectedReport = CanonicalFullPath(
                Path.Combine(projectPath, "..", "output", "ui-build-report.v1.json"));
            if (!SamePath(inputPath, expectedInput) || !SamePath(reportPath, expectedReport))
                throw new InvalidOperationException("UI input/report path drifted");
        }

        private static void ValidateInput(
            BuildInput input,
            byte[] originalBytes,
            string projectPath)
        {
            if (input == null || input.schema != InputSchema ||
                !Sha256Pattern.IsMatch(input.build_id ?? String.Empty) ||
                input.unity == null || input.unity.version != UnityVersion ||
                input.unity.revision != UnityRevision ||
                input.build_target != BuildTargetName ||
                input.build_options == null ||
                !input.build_options.SequenceEqual(ExactBuildOptions) ||
                !Sha256Pattern.IsMatch(input.editor_script_sha256 ?? String.Empty) ||
                input.output_relative_path != OutputRelativePath ||
                input.report_relative_path != ReportRelativePath ||
                input.entries == null || input.entries.Length == 0 ||
                input.entries.Length > MaximumEntries)
                throw new InvalidDataException("UI build input identity or constants drifted");

            DirectoryInfo buildDirectory = new DirectoryInfo(projectPath).Parent;
            if (buildDirectory == null || !input.build_id.StartsWith(
                    buildDirectory.Name, StringComparison.Ordinal))
                throw new InvalidDataException(
                    "UI build id prefix does not match its ephemeral directory");

            byte[] canonical = CanonicalInput(input);
            if (!originalBytes.SequenceEqual(canonical))
                throw new InvalidDataException(
                    "UI build input is not exact canonical JSON or has unknown/missing fields");

            string[] ids = input.entries.Select(item => item == null ? null : item.id).ToArray();
            if (ids.Any(value => value == null) ||
                !ids.SequenceEqual(ids.OrderBy(value => value, StringComparer.Ordinal)))
                throw new InvalidDataException("UI entries must be non-null and sorted by id");

            HashSet<string> exactIds = new HashSet<string>(StringComparer.Ordinal);
            HashSet<string> foldedIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            HashSet<string> noesisPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            HashSet<string> assetPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            HashSet<string> bundles = new HashSet<string>(StringComparer.Ordinal);
            HashSet<string> addresses = new HashSet<string>(StringComparer.Ordinal);
            HashSet<string> textureNames = new HashSet<string>(StringComparer.Ordinal);

            foreach (EntryInput entry in input.entries)
            {
                if (!IsSafeIdentifier(entry.id) ||
                    !exactIds.Add(entry.id) || !foldedIds.Add(entry.id))
                    throw new InvalidDataException("Invalid or duplicate UI entry id: " + entry.id);
                RequireSafeNoesisPath(entry.noesis_path);
                if (!noesisPaths.Add(entry.noesis_path))
                    throw new InvalidDataException(
                        "Duplicate case-insensitive Noesis path: " + entry.noesis_path);

                string hash16 = Sha256(Utf8.GetBytes(entry.noesis_path)).Substring(0, 16);
                string expectedAssetPath = AssetDirectory + "/" + hash16 + ".png";
                string expectedBundle = "sede.ui." + hash16 + ".bc7.v1";
                string expectedAddress = "sede/ui/" + hash16 + "/texture";
                if (entry.texture_name != hash16 ||
                    entry.asset_path != expectedAssetPath ||
                    entry.bundle_name != expectedBundle ||
                    entry.address != expectedAddress ||
                    !BundlePattern.IsMatch(entry.bundle_name ?? String.Empty))
                    throw new InvalidDataException(
                        "UI stable path hash contract drifted for " + entry.id);

                RequireSafeAssetPath(entry.asset_path);
                if (!assetPaths.Add(entry.asset_path) || !bundles.Add(entry.bundle_name) ||
                    !addresses.Add(entry.address) || !textureNames.Add(entry.texture_name))
                    throw new InvalidDataException(
                        "Duplicate UI asset, bundle, address, or texture name");
                if (!entry.alpha ||
                    (entry.filter_mode != "Point" && entry.filter_mode != "Bilinear") ||
                    entry.width < 1 || entry.width > MaximumTextureDimension ||
                    entry.height < 1 || entry.height > MaximumTextureDimension ||
                    !Sha256Pattern.IsMatch(entry.source_png_sha256 ?? String.Empty) ||
                    entry.gpu_bytes != ExpectedBc7Bytes(entry.width, entry.height))
                    throw new InvalidDataException(
                        "UI texture metadata contract drifted for " + entry.id);
            }
        }

        private static bool IsSafeIdentifier(string value)
        {
            if (!IdentifierPattern.IsMatch(value ?? String.Empty)) return false;
            string[] components = value.Split('/');
            return components.All(part => part.Length != 0 && part != "." && part != "..");
        }

        private static void RequireSafeNoesisPath(string value)
        {
            if (String.IsNullOrEmpty(value) || value.Length > 512 ||
                !value.StartsWith("Assets/", StringComparison.Ordinal) ||
                !value.EndsWith(".png", StringComparison.OrdinalIgnoreCase) ||
                value.Contains("\\") || value.IndexOf(':') >= 0 ||
                value.Any(character => Char.IsControl(character)) ||
                value != value.Trim())
                throw new InvalidDataException("Unsafe Noesis texture path: " + value);
            string[] components = value.Split('/');
            if (components.Any(part => part.Length == 0 || part == "." || part == ".."))
                throw new InvalidDataException("Unsafe Noesis texture path: " + value);
        }

        private static byte[] CanonicalInput(BuildInput input)
        {
            StringBuilder json = new StringBuilder(4096);
            json.Append('{');
            AppendProperty(json, "build_id", input.build_id, true);
            json.Append(",\"build_options\":[");
            for (int i = 0; i < input.build_options.Length; ++i)
            {
                if (i != 0) json.Append(',');
                AppendQuoted(json, input.build_options[i]);
            }
            json.Append(']');
            AppendProperty(json, "build_target", input.build_target, false);
            AppendProperty(json, "editor_script_sha256", input.editor_script_sha256, false);
            json.Append(",\"entries\":[");
            for (int i = 0; i < input.entries.Length; ++i)
            {
                if (i != 0) json.Append(',');
                EntryInput entry = input.entries[i];
                if (entry == null)
                    throw new InvalidDataException("UI entry cannot be null");
                json.Append('{');
                AppendProperty(json, "address", entry.address, true);
                AppendProperty(json, "alpha", entry.alpha, false);
                AppendProperty(json, "asset_path", entry.asset_path, false);
                AppendProperty(json, "bundle_name", entry.bundle_name, false);
                AppendProperty(json, "filter_mode", entry.filter_mode, false);
                AppendProperty(json, "gpu_bytes", entry.gpu_bytes, false);
                AppendProperty(json, "height", entry.height, false);
                AppendProperty(json, "id", entry.id, false);
                AppendProperty(json, "noesis_path", entry.noesis_path, false);
                AppendProperty(json, "source_png_sha256", entry.source_png_sha256, false);
                AppendProperty(json, "texture_name", entry.texture_name, false);
                AppendProperty(json, "width", entry.width, false);
                json.Append('}');
            }
            json.Append(']');
            AppendProperty(json, "output_relative_path", input.output_relative_path, false);
            AppendProperty(json, "report_relative_path", input.report_relative_path, false);
            AppendProperty(json, "schema", input.schema, false);
            json.Append(",\"unity\":{");
            AppendProperty(json, "revision", input.unity.revision, true);
            AppendProperty(json, "version", input.unity.version, false);
            json.Append("}}\n");
            return Utf8.GetBytes(json.ToString());
        }

        private static void ValidateEditorIdentity()
        {
            string full = InternalEditorUtility.GetFullUnityVersion();
            if (Application.unityVersion != UnityVersion || full != UnityFullVersion)
                throw new InvalidOperationException(
                    "Exact Unity editor required: " + UnityFullVersion + "; actual: " + full);
        }

        private static void ValidateEditorSource(BuildInput input, string projectPath)
        {
            string sourcePath = CanonicalFullPath(Path.Combine(
                projectPath,
                "Assets",
                "Editor",
                "StrongholdEuropeUiTextureBundleBuilder.cs"));
            string editorRoot = CanonicalFullPath(Path.Combine(projectPath, "Assets", "Editor"));
            if (!File.Exists(sourcePath) || !SameParent(sourcePath, editorRoot) ||
                Sha256File(sourcePath) != input.editor_script_sha256)
                throw new InvalidDataException("UI editor builder source hash drifted");
        }

        private static void VerifySourceFileSet(string projectPath, EntryInput[] entries)
        {
            string directory = CanonicalFullPath(Path.Combine(
                projectPath, AssetDirectory.Replace('/', Path.DirectorySeparatorChar)));
            if (!Directory.Exists(directory) || Directory.GetDirectories(directory).Length != 0)
                throw new InvalidDataException(
                    "UI staging texture directory is missing or contains subdirectories");

            HashSet<string> expected = new HashSet<string>(StringComparer.Ordinal);
            foreach (EntryInput entry in entries)
            {
                string fileName = entry.texture_name + ".png";
                expected.Add(fileName);
                expected.Add(fileName + ".meta");
            }
            string[] actual = Directory.GetFiles(directory)
                .Select(Path.GetFileName)
                .OrderBy(value => value, StringComparer.Ordinal)
                .ToArray();
            if (!expected.OrderBy(value => value, StringComparer.Ordinal).SequenceEqual(actual))
                throw new InvalidDataException("UI staging texture file set drifted");
        }

        private static void ConfigureAndVerifyTexture(string projectPath, EntryInput entry)
        {
            string sourcePath = ResolveAssetPath(projectPath, entry.asset_path);
            FileInfo sourceInfo = new FileInfo(sourcePath);
            if (!sourceInfo.Exists || sourceInfo.Length <= 0 ||
                sourceInfo.Length > MaximumPngBytes)
                throw new InvalidDataException(
                    "UI staging PNG is missing, empty, or oversized: " + entry.asset_path);
            if (Sha256File(sourcePath) != entry.source_png_sha256)
                throw new InvalidDataException(
                    "UI staging PNG hash drifted: " + entry.asset_path);
            VerifyPngHeader(sourcePath, entry.width, entry.height);

            // The exact .meta is staged before Unity opens the project.  This is
            // deliberately a pure verifier: calling SaveAndReimport or
            // SetPlatformTextureSettings here makes Unity 2021.3 silently clear
            // forceMaximumCompressionQuality_BC6H_BC7 and can decode NPOT inputs
            // back to RGBA32.  A drift therefore fails instead of being repaired.
            FilterMode filter = entry.filter_mode == "Point"
                ? FilterMode.Point
                : FilterMode.Bilinear;
            VerifyImportedTexture(entry, filter);
        }

        private static void VerifyImportedTexture(EntryInput entry, FilterMode filter)
        {
            TextureImporter importer = AssetImporter.GetAtPath(entry.asset_path) as TextureImporter;
            Texture2D imported = AssetDatabase.LoadAssetAtPath<Texture2D>(entry.asset_path);
            UnityEngine.Object[] allAssets = AssetDatabase.LoadAllAssetsAtPath(entry.asset_path);
            if (importer == null || imported == null || allAssets.Length != 1 ||
                !(allAssets[0] is Texture2D))
                throw new InvalidOperationException(
                    "UI path must import as exactly one Texture2D: " + entry.asset_path);

            TextureImporterPlatformSettings defaults =
                importer.GetDefaultPlatformTextureSettings();
            TextureImporterPlatformSettings standalone =
                importer.GetPlatformTextureSettings("Standalone");
            string forceMaximumDetail;
            bool forceMaximum = VerifyForceMaximumCompressionQuality(
                defaults, standalone, 1, out forceMaximumDetail);

            bool valid = imported.name == entry.texture_name &&
                imported.width == entry.width && imported.height == entry.height &&
                imported.format == TextureFormat.BC7 && imported.mipmapCount == 1 &&
                !imported.isReadable && imported.filterMode == filter &&
                imported.wrapMode == TextureWrapMode.Clamp &&
                imported.wrapModeU == TextureWrapMode.Clamp &&
                imported.wrapModeV == TextureWrapMode.Clamp &&
                imported.wrapModeW == TextureWrapMode.Clamp &&
                imported.anisoLevel == 0 &&
                importer.textureType == TextureImporterType.Default &&
                importer.textureShape == TextureImporterShape.Texture2D &&
                importer.sRGBTexture &&
                importer.alphaSource == TextureImporterAlphaSource.FromInput &&
                !importer.alphaIsTransparency && !importer.mipmapEnabled &&
                !importer.streamingMipmaps && !importer.isReadable &&
                importer.filterMode == filter &&
                importer.wrapMode == TextureWrapMode.Clamp &&
                importer.wrapModeU == TextureWrapMode.Clamp &&
                importer.wrapModeV == TextureWrapMode.Clamp &&
                importer.wrapModeW == TextureWrapMode.Clamp &&
                importer.anisoLevel == 0 &&
                importer.npotScale == TextureImporterNPOTScale.None &&
                importer.ignorePngGamma &&
                importer.textureCompression == TextureImporterCompression.CompressedHQ &&
                !importer.crunchedCompression &&
                importer.maxTextureSize == MaximumTextureDimension &&
                String.IsNullOrEmpty(importer.assetBundleName) &&
                String.IsNullOrEmpty(importer.assetBundleVariant) &&
                Bc7PlatformSettingsAreExact(defaults) &&
                Bc7PlatformSettingsAreExact(standalone) && forceMaximum;
            if (!valid)
                throw new InvalidOperationException(
                    "Direct UI BC7 import contract failed for " + entry.asset_path +
                    ": imported={name:" + imported.name + ",size:" +
                    imported.width.ToString(CultureInfo.InvariantCulture) + "x" +
                    imported.height.ToString(CultureInfo.InvariantCulture) +
                    ",format:" + imported.format + ",mips:" +
                    imported.mipmapCount.ToString(CultureInfo.InvariantCulture) +
                    ",readable:" + imported.isReadable + ",filter:" + imported.filterMode +
                    ",wrap:" + imported.wrapMode + ",aniso:" + imported.anisoLevel +
                    "}; forceMaximum={" + forceMaximumDetail + "}");
        }

        private static bool Bc7PlatformSettingsAreExact(
            TextureImporterPlatformSettings settings)
        {
            return settings != null && settings.overridden &&
                settings.maxTextureSize == MaximumTextureDimension &&
                settings.format == TextureImporterFormat.BC7 &&
                settings.textureCompression == TextureImporterCompression.CompressedHQ &&
                !settings.crunchedCompression && settings.compressionQuality == 100 &&
                !settings.allowsAlphaSplitting;
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
                System.Reflection.BindingFlags.Instance |
                System.Reflection.BindingFlags.Public |
                System.Reflection.BindingFlags.NonPublic);
            if (property == null || property.PropertyType != typeof(int) ||
                property.GetIndexParameters().Length != 0 ||
                property.GetGetMethod(true) == null)
            {
                detail = "property=missing-or-drifted,expected=" + expected;
                return false;
            }
            try
            {
                object defaultValue = property.GetValue(defaults, null);
                object standaloneValue = property.GetValue(standalone, null);
                detail = "default=" + defaultValue + ",standalone=" + standaloneValue +
                    ",expected=" + expected;
                return defaultValue is int && standaloneValue is int &&
                    (int)defaultValue == expected && (int)standaloneValue == expected;
            }
            catch (Exception exception)
            {
                detail = "reflectionError=" + exception.GetType().FullName +
                    ",expected=" + expected;
                return false;
            }
        }

        private static AssetBundleBuild[] CreateBuildMaps(EntryInput[] entries)
        {
            AssetBundleBuild[] result = new AssetBundleBuild[entries.Length];
            for (int index = 0; index < entries.Length; ++index)
            {
                EntryInput entry = entries[index];
                UnityEngine.Object[] allAssets = AssetDatabase.LoadAllAssetsAtPath(entry.asset_path);
                if (allAssets.Length != 1 || !(allAssets[0] is Texture2D))
                    throw new InvalidOperationException(
                        "UI bundle entry is not exactly one Texture2D: " + entry.id);
                result[index] = new AssetBundleBuild
                {
                    assetBundleName = entry.bundle_name,
                    assetNames = new[] { entry.asset_path },
                    addressableNames = new[] { entry.address },
                };
            }
            return result;
        }

        private static void VerifyBundleSet(
            AssetBundleManifest manifest,
            EntryInput[] entries)
        {
            string[] expected = entries.Select(item => item.bundle_name)
                .OrderBy(value => value, StringComparer.Ordinal).ToArray();
            string[] actual = manifest.GetAllAssetBundles()
                .OrderBy(value => value, StringComparer.Ordinal).ToArray();
            if (!expected.SequenceEqual(actual))
                throw new InvalidOperationException("Built UI AssetBundle set drifted");
        }

        private static void VerifyBuiltBundle(string bundlePath, EntryInput entry)
        {
            AssetBundle bundle = AssetBundle.LoadFromFile(bundlePath);
            if (bundle == null)
                throw new InvalidOperationException(
                    "Built UI AssetBundle could not be loaded: " + entry.bundle_name);
            try
            {
                string[] names = bundle.GetAllAssetNames();
                UnityEngine.Object[] assets = bundle.LoadAllAssets();
                Texture2D texture = bundle.LoadAsset<Texture2D>(entry.address);
                if (names.Length != 1 || names[0] != entry.address ||
                    assets.Length != 1 || !(assets[0] is Texture2D) ||
                    texture == null || texture.name != entry.texture_name ||
                    texture.width != entry.width || texture.height != entry.height ||
                    texture.format != TextureFormat.BC7 || texture.mipmapCount != 1 ||
                    texture.isReadable ||
                    texture.filterMode != (entry.filter_mode == "Point"
                        ? FilterMode.Point
                        : FilterMode.Bilinear) ||
                    texture.wrapMode != TextureWrapMode.Clamp || texture.anisoLevel != 0)
                    throw new InvalidOperationException(
                        "Built UI AssetBundle payload contract drifted: " + entry.bundle_name);
            }
            finally
            {
                bundle.Unload(true);
            }
        }

        private static void VerifyOutputFileSet(
            string outputPath,
            EntryInput[] entries)
        {
            HashSet<string> expected = new HashSet<string>(StringComparer.Ordinal)
            {
                "win64",
                "win64.manifest",
            };
            foreach (EntryInput entry in entries)
            {
                expected.Add(entry.bundle_name);
                expected.Add(entry.bundle_name + ".manifest");
            }
            string[] actual = Directory.GetFiles(outputPath)
                .Select(Path.GetFileName)
                .OrderBy(value => value, StringComparer.Ordinal)
                .ToArray();
            if (!expected.OrderBy(value => value, StringComparer.Ordinal)
                    .SequenceEqual(actual) || Directory.GetDirectories(outputPath).Length != 0)
                throw new InvalidOperationException("Unity UI output file set drifted");
        }

        private static void WriteReport(string path, BuildReport report)
        {
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
            json.Append(",\"entries\":[");
            for (int i = 0; i < report.entries.Count; ++i)
            {
                if (i != 0) json.Append(',');
                EntryReport item = report.entries[i];
                EntryInput entry = item.input;
                json.Append('{');
                AppendProperty(json, "address", entry.address, true);
                AppendProperty(json, "alpha", entry.alpha, false);
                AppendProperty(json, "asset_path", entry.asset_path, false);
                AppendProperty(json, "bundle_crc32", item.bundleCrc32, false);
                AppendProperty(json, "bundle_name", entry.bundle_name, false);
                AppendProperty(json, "bundle_relative_path", item.bundleRelativePath, false);
                AppendProperty(json, "bundle_sha256", item.bundleSha256, false);
                AppendProperty(json, "bundle_size_bytes", item.bundleSizeBytes, false);
                AppendProperty(json, "filter_mode", entry.filter_mode, false);
                AppendProperty(json, "gpu_bytes", entry.gpu_bytes, false);
                AppendProperty(json, "height", entry.height, false);
                AppendProperty(json, "id", entry.id, false);
                AppendProperty(json, "noesis_path", entry.noesis_path, false);
                AppendProperty(json, "source_png_sha256", entry.source_png_sha256, false);
                AppendProperty(json, "texture_name", entry.texture_name, false);
                AppendProperty(json, "unity_hash128", item.unityHash128, false);
                AppendProperty(json, "width", entry.width, false);
                json.Append('}');
            }
            json.Append(']');
            AppendProperty(json, "error", report.error ?? String.Empty, false);
            AppendProperty(json, "schema", ReportSchema, false);
            AppendProperty(json, "success", report.success, false);
            json.Append(",\"unity\":{");
            AppendProperty(json, "revision", UnityRevision, true);
            AppendProperty(json, "version", UnityVersion, false);
            json.Append("}}\n");
            byte[] payload = Utf8.GetBytes(json.ToString());
            if (payload.Length > MaximumReportBytes)
                throw new InvalidDataException("UI build report exceeds its 16-MiB bound");
            AtomicWriteNew(path, payload);
        }

        private static void VerifyPngHeader(string path, int width, int height)
        {
            byte[] header = new byte[33];
            using (FileStream stream = new FileStream(
                path, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                int offset = 0;
                while (offset < header.Length)
                {
                    int count = stream.Read(header, offset, header.Length - offset);
                    if (count == 0) break;
                    offset += count;
                }
                if (offset != header.Length)
                    throw new InvalidDataException("UI staging PNG header is truncated: " + path);
            }

            byte[] signature = { 137, 80, 78, 71, 13, 10, 26, 10 };
            bool signatureMatches = true;
            for (int i = 0; i < signature.Length; ++i)
                signatureMatches &= header[i] == signature[i];
            int headerLength = ReadBigEndianInt32(header, 8);
            bool ihdr = header[12] == (byte)'I' && header[13] == (byte)'H' &&
                header[14] == (byte)'D' && header[15] == (byte)'R';
            int actualWidth = ReadBigEndianInt32(header, 16);
            int actualHeight = ReadBigEndianInt32(header, 20);
            if (!signatureMatches || headerLength != 13 || !ihdr ||
                actualWidth != width || actualHeight != height ||
                header[24] != 8 || header[25] != 6 || header[26] != 0 ||
                header[27] != 0 || header[28] != 0)
                throw new InvalidDataException(
                    "UI staging image must be exact non-interlaced RGBA8 PNG dimensions: " + path);
        }

        private static int ReadBigEndianInt32(byte[] value, int offset)
        {
            uint result = ((uint)value[offset] << 24) |
                ((uint)value[offset + 1] << 16) |
                ((uint)value[offset + 2] << 8) |
                value[offset + 3];
            if (result > Int32.MaxValue)
                throw new InvalidDataException("PNG dimension exceeded signed integer range");
            return (int)result;
        }

        private static long ExpectedBc7Bytes(int width, int height)
        {
            checked
            {
                return ((long)width + 3L) / 4L *
                    (((long)height + 3L) / 4L) * 16L;
            }
        }

        private static void RequireExactOutputPath(string projectPath, string outputPath)
        {
            string expected = CanonicalFullPath(Path.Combine(
                projectPath,
                "..",
                "output",
                "Runtime",
                "UiAssetBundles",
                "win64"));
            if (!SamePath(outputPath, expected))
                throw new InvalidOperationException("Runtime UI AssetBundle output path drifted");
        }

        private static void RequireFreshOutputDirectory(string outputPath)
        {
            if (Directory.Exists(outputPath) &&
                Directory.EnumerateFileSystemEntries(outputPath).Any())
                throw new InvalidOperationException(
                    "Refusing to build into a non-empty UI output directory: " + outputPath);
            Directory.CreateDirectory(outputPath);
        }

        private static byte[] ReadBoundedBytes(string path, int maximumBytes, string label)
        {
            FileInfo info = new FileInfo(path);
            if (!info.Exists || info.Length <= 0 || info.Length > maximumBytes)
                throw new InvalidDataException(label + " is missing, empty, or oversized");
            return File.ReadAllBytes(path);
        }

        private static string ResolveAssetPath(string projectPath, string assetPath)
        {
            RequireSafeAssetPath(assetPath);
            string resolved = CanonicalFullPath(Path.Combine(
                projectPath, assetPath.Replace('/', Path.DirectorySeparatorChar)));
            string assetsRoot = CanonicalFullPath(Path.Combine(projectPath, "Assets"));
            if (!resolved.StartsWith(
                    assetsRoot + Path.DirectorySeparatorChar,
                    StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("UI asset path escaped Assets/: " + assetPath);
            return resolved;
        }

        private static void RequireSafeAssetPath(string assetPath)
        {
            if (String.IsNullOrEmpty(assetPath) ||
                !assetPath.StartsWith("Assets/", StringComparison.Ordinal) ||
                assetPath.Contains("\\") ||
                assetPath.Split('/').Any(part =>
                    part.Length == 0 || part == "." || part == ".."))
                throw new InvalidDataException("Unsafe Unity UI asset path: " + assetPath);
        }

        private static string ResolveProjectRelative(string projectPath, string relativePath)
        {
            if (String.IsNullOrEmpty(relativePath) || relativePath.Contains("\\") ||
                Path.IsPathRooted(relativePath))
                throw new InvalidDataException("Unsafe project-relative UI output path");
            return CanonicalFullPath(Path.Combine(
                projectPath, relativePath.Replace('/', Path.DirectorySeparatorChar)));
        }

        private static string CanonicalFullPath(string path)
        {
            return Path.GetFullPath(path).TrimEnd(
                Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        }

        private static bool SamePath(string left, string right)
        {
            return String.Equals(
                CanonicalFullPath(left),
                CanonicalFullPath(right),
                StringComparison.OrdinalIgnoreCase);
        }

        private static bool SameParent(string file, string parent)
        {
            DirectoryInfo directory = Directory.GetParent(file);
            return directory != null && SamePath(directory.FullName, parent);
        }

        private static string Sha256(byte[] payload)
        {
            using (SHA256 digest = SHA256.Create())
                return String.Concat(digest.ComputeHash(payload).Select(
                    value => value.ToString("x2", CultureInfo.InvariantCulture)));
        }

        private static string Sha256File(string path)
        {
            using (SHA256 digest = SHA256.Create())
            using (FileStream stream = new FileStream(
                path, FileMode.Open, FileAccess.Read, FileShare.Read))
                return String.Concat(digest.ComputeHash(stream).Select(
                    value => value.ToString("x2", CultureInfo.InvariantCulture)));
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
                            crc = (crc >> 1) ^
                                (0xedb88320U & (uint)-(int)(crc & 1U));
                    }
                }
            }
            return (crc ^ 0xffffffffU).ToString("x8", CultureInfo.InvariantCulture);
        }

        private static void AppendProperty(
            StringBuilder json,
            string key,
            string value,
            bool first)
        {
            if (!first) json.Append(',');
            AppendQuoted(json, key);
            json.Append(':');
            AppendQuoted(json, value);
        }

        private static void AppendProperty(
            StringBuilder json,
            string key,
            long value,
            bool first)
        {
            if (!first) json.Append(',');
            AppendQuoted(json, key);
            json.Append(':').Append(value.ToString(CultureInfo.InvariantCulture));
        }

        private static void AppendProperty(
            StringBuilder json,
            string key,
            bool value,
            bool first)
        {
            if (!first) json.Append(',');
            AppendQuoted(json, key);
            json.Append(value ? ":true" : ":false");
        }

        private static void AppendQuoted(StringBuilder json, string value)
        {
            if (value == null)
                throw new InvalidDataException("Required canonical JSON string is null");
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
                        if (character < 0x20)
                            json.Append("\\u").Append(
                                ((int)character).ToString("x4", CultureInfo.InvariantCulture));
                        else
                            json.Append(character);
                        break;
                }
            }
            json.Append('"');
        }

        private static void AtomicWriteNew(string path, byte[] payload)
        {
            DirectoryInfo parent = Directory.GetParent(path);
            if (parent == null)
                throw new IOException("UI report path has no parent");
            Directory.CreateDirectory(parent.FullName);
            if (File.Exists(path))
                throw new IOException("Refusing to overwrite existing file: " + path);
            string temporary = path + ".tmp-" +
                System.Diagnostics.Process.GetCurrentProcess().Id.ToString(
                    CultureInfo.InvariantCulture);
            using (FileStream stream = new FileStream(
                temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                stream.Write(payload, 0, payload.Length);
                stream.Flush(true);
            }
            File.Move(temporary, path);
        }
    }
}
