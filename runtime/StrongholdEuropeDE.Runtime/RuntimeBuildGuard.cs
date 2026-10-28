using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BepInEx;
using HarmonyLib;
using SHCDESE.API;
using UnityEngine;

namespace StrongholdEuropeDE.Runtime
{
    internal static class RuntimeBuildGuard
    {
        // Strict by default: every check throws, exactly as before. The
        // Diplomatie V2 guard compiles this file and turns those exceptions
        // into its own notices, so the strict paths and their messages stay.
        //
        // The Europe runtime follows the user's rule of 2026-09-25 (every SE /
        // game combination loads, an unverified one is reported in one line)
        // through the *ReportingDrift entry points below. While one of them
        // runs on a thread, identity drift - file size, SHA-256, assembly
        // version, loaded MVID - is recorded instead of thrown. What cannot be
        // the dependency at all still throws: a path outside the game root, a
        // missing file, a different assembly name, a duplicate or foreign
        // loaded copy.
        [ThreadStatic]
        private static bool _reportDrift;

        private static readonly ConcurrentDictionary<string, string> Drift =
            new ConcurrentDictionary<string, string>(StringComparer.Ordinal);

        internal static void VerifyCoreReportingDrift()
        {
            RunReportingDrift(VerifyCore);
        }

        internal static void VerifyOptionalReportingDrift(string dependencyId)
        {
            RunReportingDrift(() => VerifyOptional(dependencyId));
        }

        internal static void VerifyEarlyLoadedAssemblyReportingDrift(
            Assembly assembly,
            string dependencyId)
        {
            RunReportingDrift(
                () => VerifyEarlyLoadedAssembly(assembly, dependencyId));
        }

        /// <summary>
        /// True when no drift was recorded for the dependency.
        /// </summary>
        internal static bool IsExact(string dependencyId)
        {
            return !Drift.ContainsKey(dependencyId);
        }

        /// <summary>
        /// "id:reason,id:reason" of every recorded drift; empty when the
        /// running combination is the verified one.
        /// </summary>
        internal static string DriftReport()
        {
            var parts = new List<string>();
            foreach (KeyValuePair<string, string> entry in Drift)
            {
                parts.Add(entry.Key + ":" + entry.Value);
            }
            parts.Sort(StringComparer.Ordinal);
            return string.Join(",", parts.ToArray());
        }

        private static void RunReportingDrift(Action verify)
        {
            bool previous = _reportDrift;
            _reportDrift = true;
            try
            {
                verify();
            }
            finally
            {
                _reportDrift = previous;
            }
        }

        // True when the caller asked for drift reporting; then the drift is
        // recorded and the check for this dependency ends here.
        private static bool ReportedDrift(string dependencyId, string reason)
        {
            if (!_reportDrift)
            {
                return false;
            }
            Drift.TryAdd(dependencyId, reason);
            return true;
        }
        /// <summary>
        /// Verify everything. Kept so a caller that wants the all-or-nothing
        /// decision still gets it; the plugin now asks per capability instead.
        /// </summary>
        internal static void Verify()
        {
            VerifyCore();
            VerifyOptional("r3");
        }

        /// <summary>
        /// Verify the dependencies without which no lane can run.
        /// </summary>
        /// <remarks>
        /// R3 is deliberately absent here. It serves one lane, and folding it
        /// into the core decision is what turned a missing optional dependency
        /// into a black screen.
        /// </remarks>
        internal static void VerifyCore()
        {
            // The count is not spelled out here on purpose. It used to be a
            // literal 6, and adding R3 as a seventh pinned reference made this
            // throw at startup - the plugin failed closed, correctly, but the
            // game came up with a black screen because the atlas overrides had
            // already been applied without the companion that finishes them.
            // The real protection is per-id: every dependency the guard needs is
            // looked up by name below and throws if the build did not emit it.
            int count = GeneratedAudioContract.PrerequisiteIds.Length;
            if (count < 1
                || count != GeneratedAudioContract.PrerequisiteCount
                || GeneratedAudioContract.PrerequisiteRelativePaths.Length != count
                || GeneratedAudioContract.PrerequisiteSizes.Length != count
                || GeneratedAudioContract.PrerequisiteSha256.Length != count
                || GeneratedAudioContract.PrerequisiteAssemblyNames.Length != count
                || GeneratedAudioContract.PrerequisiteAssemblyVersions.Length != count
                || GeneratedAudioContract.PrerequisiteMvids.Length != count)
            {
                throw new InvalidDataException("Compiled runtime prerequisite contract is malformed");
            }

            for (int index = 0; index < count; index++)
            {
                string dependencyId =
                    GeneratedAudioContract.PrerequisiteIds[index];
                if (IsLaneScopedPrerequisite(dependencyId))
                {
                    continue;
                }
                VerifyPrerequisiteFile(index);
            }

            VerifyLoadedAssembly(typeof(SFXManager).Assembly, "assembly_csharp");
            VerifyLoadedAssembly(typeof(GameAssetManagerAPI).Assembly, "shcdese");
            VerifyLoadedAssemblyIfPresent("nlua");
            VerifyLoadedAssemblyIfPresent("keralua");
            VerifyLoadedAssemblyIfPresent("noesis_gui");
            VerifyLoadedAssembly(typeof(ReadOnlyMemory<byte>).Assembly, "system_memory");
            // The native-field adapter uses Unsafe.As/Add for verified
            // offsets, so do not bind to an untrusted foreign copy.
            VerifyLoadedAssemblyIfPresent("unsafe");
            VerifyLoadedAssembly(typeof(BaseUnityPlugin).Assembly, "bepinex_core");
            VerifyLoadedAssembly(typeof(Harmony).Assembly, "harmony");
            VerifyLoadedAssembly(typeof(Material).Assembly, "unity_engine_core_module");
            VerifyLoadedAssembly(typeof(AssetBundle).Assembly, "unity_engine_asset_bundle_module");
            VerifyLoadedAssembly(typeof(AudioClip).Assembly, "unity_engine_audio_module");
            VerifyLoadedAssemblyIfPresent("unity_engine");
        }

        /// <summary>
        /// Verify one lane-scoped dependency. Throws exactly as the core check
        /// does; the caller decides that only that lane is affected.
        /// </summary>
        internal static void VerifyOptional(string dependencyId)
        {
            VerifyPrerequisiteFile(dependencyId);
            VerifyLoadedAssemblyIfPresent(dependencyId);
        }

        /// <summary>
        /// Verify and return one compiled prerequisite before the normal core
        /// plugin runs. The allocation-prevention plugin uses this boundary to
        /// load and patch the exact Zhuqiaomon binary before SHCDE-SE Awake.
        /// </summary>
        internal static string GetVerifiedPrerequisitePath(string dependencyId)
        {
            int index = Array.IndexOf(
                GeneratedAudioContract.PrerequisiteIds,
                dependencyId);
            if (index < 0)
            {
                throw new InvalidDataException(
                    "Missing compiled prerequisite: " + dependencyId);
            }
            VerifyPrerequisiteFile(index);
            return ExpectedPrerequisitePath(index);
        }

        internal static void VerifyEarlyLoadedAssembly(
            Assembly assembly,
            string dependencyId)
        {
            VerifyPrerequisiteFile(dependencyId);
            VerifyLoadedAssembly(assembly, dependencyId);
        }

        /// <summary>
        /// The ImageConversion module is loaded only when the independent UI
        /// lane is enabled. Verify its exact loaded identity at that boundary
        /// so a failure disables UI streaming without widening the core lane.
        /// </summary>
        internal static void VerifyUiImageConversionAssembly(Assembly assembly)
        {
            if (assembly == null)
            {
                throw new ArgumentNullException("assembly");
            }
            VerifyPrerequisiteFile(
                "unity_engine_image_conversion_module");
            VerifyLoadedAssembly(
                assembly,
                "unity_engine_image_conversion_module");
        }

        private static void VerifyPrerequisiteFile(string dependencyId)
        {
            int index = Array.IndexOf(
                GeneratedAudioContract.PrerequisiteIds,
                dependencyId);
            if (index < 0)
            {
                throw new InvalidDataException(
                    "Missing compiled prerequisite: " + dependencyId);
            }
            VerifyPrerequisiteFile(index);
        }

        private static void VerifyPrerequisiteFile(int index)
        {
            string gameRoot = Path.GetFullPath(Paths.GameRootPath)
                .TrimEnd(
                    Path.DirectorySeparatorChar,
                    Path.AltDirectorySeparatorChar);
            string rootPrefix = gameRoot + Path.DirectorySeparatorChar;
            string relative =
                GeneratedAudioContract.PrerequisiteRelativePaths[index];
            string candidate = Path.GetFullPath(Path.Combine(
                gameRoot,
                relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!candidate.StartsWith(
                    rootPrefix,
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(
                    "Runtime prerequisite escapes game root: " + relative);
            }
            string prerequisiteId = GeneratedAudioContract.PrerequisiteIds[index];
            if (_reportDrift)
            {
                if (!File.Exists(candidate))
                {
                    throw new InvalidDataException(
                        "Runtime prerequisite is missing: " + prerequisiteId);
                }
                AssemblyName found = AssemblyName.GetAssemblyName(candidate);
                if (!string.Equals(
                        found.Name,
                        GeneratedAudioContract.PrerequisiteAssemblyNames[index],
                        StringComparison.Ordinal))
                {
                    throw new InvalidDataException(
                        "Runtime prerequisite is a different assembly: "
                        + prerequisiteId);
                }
                if (!string.Equals(
                        found.Version.ToString(),
                        GeneratedAudioContract.PrerequisiteAssemblyVersions[index],
                        StringComparison.Ordinal)
                    && ReportedDrift(prerequisiteId, "version_" + found.Version))
                {
                    return;
                }
                if (new FileInfo(candidate).Length
                        != GeneratedAudioContract.PrerequisiteSizes[index]
                    && ReportedDrift(prerequisiteId, "size"))
                {
                    return;
                }
            }
            string digest = Hashing.Sha256FileStable(
                candidate,
                GeneratedAudioContract.PrerequisiteSizes[index]);
            if (!string.Equals(
                    digest,
                    GeneratedAudioContract.PrerequisiteSha256[index],
                    StringComparison.Ordinal))
            {
                if (ReportedDrift(prerequisiteId, "sha256"))
                {
                    return;
                }
                throw new InvalidDataException(
                    "Runtime prerequisite SHA-256 mismatch: "
                    + GeneratedAudioContract.PrerequisiteIds[index]);
            }
            AssemblyName identity = AssemblyName.GetAssemblyName(candidate);
            if (!string.Equals(
                    identity.Name,
                    GeneratedAudioContract.PrerequisiteAssemblyNames[index],
                    StringComparison.Ordinal)
                || !string.Equals(
                    identity.Version.ToString(),
                    GeneratedAudioContract.PrerequisiteAssemblyVersions[index],
                    StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Runtime prerequisite assembly identity mismatch: "
                    + GeneratedAudioContract.PrerequisiteIds[index]);
            }
        }

        private static bool IsLaneScopedPrerequisite(string dependencyId)
        {
            return string.Equals(
                    dependencyId,
                    "r3",
                    StringComparison.Ordinal)
                || string.Equals(
                    dependencyId,
                    "unity_engine_image_conversion_module",
                    StringComparison.Ordinal)
                || string.Equals(
                    dependencyId,
                    "noesis_gui",
                    StringComparison.Ordinal);
        }

        private static void VerifyLoadedAssemblyIfPresent(string dependencyId)
        {
            int index = Array.IndexOf(
                GeneratedAudioContract.PrerequisiteIds,
                dependencyId);
            if (index < 0)
            {
                throw new InvalidDataException("Missing compiled prerequisite: " + dependencyId);
            }
            string expectedName = GeneratedAudioContract.PrerequisiteAssemblyNames[index];
            Assembly match = null;
            foreach (Assembly candidate in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (!string.Equals(
                        candidate.GetName().Name,
                        expectedName,
                        StringComparison.Ordinal))
                {
                    continue;
                }
                if (match != null && !ReferenceEquals(match, candidate))
                {
                    throw new InvalidDataException(
                        "Multiple loaded assemblies have pinned name: " + dependencyId);
                }
                match = candidate;
            }
            if (match != null)
            {
                VerifyLoadedAssembly(match, dependencyId);
            }
        }

        private static void VerifyLoadedAssembly(Assembly assembly, string dependencyId)
        {
            int index = Array.IndexOf(
                GeneratedAudioContract.PrerequisiteIds,
                dependencyId);
            if (index < 0)
            {
                throw new InvalidDataException("Missing compiled prerequisite: " + dependencyId);
            }
            string expected = ExpectedPrerequisitePath(index);
            AssemblyName identity = assembly.GetName();
            Guid expectedMvid;
            if (_reportDrift
                && Guid.TryParseExact(
                    GeneratedAudioContract.PrerequisiteMvids[index],
                    "D",
                    out expectedMvid)
                && string.Equals(
                    identity.Name,
                    GeneratedAudioContract.PrerequisiteAssemblyNames[index],
                    StringComparison.Ordinal)
                && (!string.Equals(
                        identity.Version.ToString(),
                        GeneratedAudioContract.PrerequisiteAssemblyVersions[index],
                        StringComparison.Ordinal)
                    || assembly.ManifestModule.ModuleVersionId != expectedMvid))
            {
                // The identity differs, the name does not: drift. The path
                // check below still runs - a foreign copy is never drift.
                ReportedDrift(dependencyId, "loaded_identity");
            }
            else if (!Guid.TryParseExact(
                    GeneratedAudioContract.PrerequisiteMvids[index],
                    "D",
                    out expectedMvid)
                || !string.Equals(
                    identity.Name,
                    GeneratedAudioContract.PrerequisiteAssemblyNames[index],
                    StringComparison.Ordinal)
                || !string.Equals(
                    identity.Version.ToString(),
                    GeneratedAudioContract.PrerequisiteAssemblyVersions[index],
                    StringComparison.Ordinal)
                || assembly.ManifestModule.ModuleVersionId != expectedMvid)
            {
                throw new InvalidDataException(
                    "Loaded assembly identity/MVID mismatch: " + dependencyId
                    + " expectedMvid=" + GeneratedAudioContract.PrerequisiteMvids[index]
                    + " actualMvid=" + assembly.ManifestModule.ModuleVersionId.ToString("D"));
            }

            string location = GetAssemblyLocation(assembly);
            string modulePath = GetModulePath(assembly.ManifestModule);
            bool allowPathlessUnityLoad = IsUnityLoadedAssembly(dependencyId);
            if (!RuntimeDecision.LoadedAssemblyPathsMatch(
                    expected,
                    allowPathlessUnityLoad,
                    location,
                    modulePath))
            {
                throw new InvalidDataException(
                    "Loaded assembly path mismatch or unexpectedly pathless: "
                    + dependencyId);
            }
        }

        private static string ExpectedPrerequisitePath(int index)
        {
            return Path.GetFullPath(Path.Combine(
                Paths.GameRootPath,
                GeneratedAudioContract.PrerequisiteRelativePaths[index]
                    .Replace('/', Path.DirectorySeparatorChar)));
        }

        private static string GetAssemblyLocation(Assembly assembly)
        {
            try
            {
                return assembly.Location;
            }
            catch (NotSupportedException)
            {
                return string.Empty;
            }
        }

        private static string GetModulePath(Module module)
        {
            try
            {
                return module.FullyQualifiedName;
            }
            catch (NotSupportedException)
            {
                return string.Empty;
            }
        }

        private static bool IsUnityLoadedAssembly(string dependencyId)
        {
            return string.Equals(dependencyId, "assembly_csharp", StringComparison.Ordinal)
                || string.Equals(dependencyId, "unity_engine", StringComparison.Ordinal)
                || string.Equals(
                    dependencyId,
                    "unity_engine_core_module",
                    StringComparison.Ordinal)
                || string.Equals(
                    dependencyId,
                    "unity_engine_asset_bundle_module",
                    StringComparison.Ordinal)
                || string.Equals(
                    dependencyId,
                    "unity_engine_audio_module",
                    StringComparison.Ordinal)
                || string.Equals(
                    dependencyId,
                    "unity_engine_image_conversion_module",
                    StringComparison.Ordinal);
        }
    }
}
