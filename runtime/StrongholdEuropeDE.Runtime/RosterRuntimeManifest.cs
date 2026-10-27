using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed class RosterCompiledContract
    {
        internal bool Enabled;
        internal string ManifestSha256;
        internal string SourceSha256;
        internal string EntriesSha256;
        internal string TargetOriginalsSha256;
        internal string TargetTextSha256;
        internal long TargetTextSize;
        internal string HudXamlSha256;
        internal long HudXamlSize;
        internal string HudBuildingsXamlSha256;
        internal long HudBuildingsXamlSize;
        internal int EntryCount;
        internal int HudControlCount;

        internal static RosterCompiledContract FromGenerated()
        {
            return new RosterCompiledContract
            {
                Enabled = GeneratedRosterContract.Enabled,
                ManifestSha256 = GeneratedRosterContract.ManifestSha256,
                SourceSha256 = GeneratedRosterContract.SourceSha256,
                EntriesSha256 = GeneratedRosterContract.EntriesSha256,
                TargetOriginalsSha256 = GeneratedRosterContract.TargetOriginalsSha256,
                TargetTextSha256 = GeneratedRosterContract.TargetTextSha256,
                TargetTextSize = GeneratedRosterContract.TargetTextSize,
                HudXamlSha256 = GeneratedRosterContract.HudXamlSha256,
                HudXamlSize = GeneratedRosterContract.HudXamlSize,
                HudBuildingsXamlSha256 =
                    GeneratedRosterContract.HudBuildingsXamlSha256,
                HudBuildingsXamlSize =
                    GeneratedRosterContract.HudBuildingsXamlSize,
                EntryCount = GeneratedRosterContract.EntryCount,
                HudControlCount = GeneratedRosterContract.HudControlCount
            };
        }
    }

    internal sealed class RosterRuntimeManifest
    {
        private const string Signature = "stronghold-europe-unit-roster\t1";
        private const string EntryHeader =
            "entry\tkind\tlogical_id\tsection\traw_index\tinternal_key\tde\ten";
        private const string HudHeader =
            "hud\tlogical_id\tcontrol\tinternal_key";
        private const string TargetTextPath = "Assets/Text/crusader.txt";
        private const string HudXamlPath =
            "BepInEx/plugins/000shcdese/Override/Assets/GUI/XAMLResources/HUD_Main.xaml";
        private const string HudBuildingsXamlPath =
            "BepInEx/plugins/000shcdese/Override/Assets/GUI/XAMLResources/HUD_Buildings.xaml";

        internal string TargetTextRelativePath;
        internal long TargetTextSize;
        internal string TargetTextSha256;
        internal string TargetLocale;
        internal string TargetOriginalsSha256;
        internal string HudXamlRelativePath;
        internal long HudXamlSize;
        internal string HudXamlSha256;
        internal string HudBuildingsXamlRelativePath;
        internal long HudBuildingsXamlSize;
        internal string HudBuildingsXamlSha256;
        internal string EntriesSha256;
        internal string UnitNamesSha256;
        internal RosterTextEntry[] Entries;
        internal RosterHudBinding[] HudBindings;

        internal static RosterRuntimeManifest Load(string path)
        {
            RosterCompiledContract expected = RosterCompiledContract.FromGenerated();
            if (!expected.Enabled)
            {
                throw new InvalidOperationException(
                    "Compiled runtime does not enable the unit roster");
            }
            return Parse(File.ReadAllBytes(path), expected);
        }

        internal static RosterRuntimeManifest Parse(
            byte[] bytes,
            RosterCompiledContract expected)
        {
            if (bytes == null || expected == null || !expected.Enabled)
            {
                throw new ArgumentException(
                    "Roster parser requires an enabled compiled contract");
            }
            string manifestDigest = Hashing.Sha256(bytes);
            if (!string.Equals(
                manifestDigest,
                expected.ManifestSha256,
                StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Roster manifest SHA-256 mismatch: expected="
                    + expected.ManifestSha256
                    + " actual=" + manifestDigest);
            }

            string text = new UTF8Encoding(false, true).GetString(bytes);
            if (text.IndexOf('\r') >= 0
                || text.IndexOf('\0') >= 0
                || !text.EndsWith("\n", StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Roster manifest must be strict canonical UTF-8/LF");
            }
            string[] lines = text.Substring(0, text.Length - 1).Split('\n');
            int expectedLineCount = 19
                + expected.EntryCount
                + expected.HudControlCount;
            if (lines.Length != expectedLineCount || lines[0] != Signature)
            {
                throw new InvalidDataException(
                    "Roster manifest shape/signature is not exact");
            }

            RequirePair(lines[1], "roster_source_sha256", expected.SourceSha256);
            RequirePair(lines[2], "target_text_relative_path", TargetTextPath);
            long targetTextSize = ParseLongPair(lines[3], "target_text_size");
            RequirePair(lines[4], "target_text_sha256", expected.TargetTextSha256);
            RequirePair(lines[5], "target_locale", "dede");
            RequirePair(
                lines[6],
                "target_originals_sha256",
                expected.TargetOriginalsSha256);
            RequirePair(lines[7], "hud_xaml_relative_path", HudXamlPath);
            long hudXamlSize = ParseLongPair(lines[8], "hud_xaml_size");
            RequirePair(lines[9], "hud_xaml_sha256", expected.HudXamlSha256);
            RequirePair(
                lines[10],
                "hud_buildings_xaml_relative_path",
                HudBuildingsXamlPath);
            long hudBuildingsXamlSize = ParseLongPair(
                lines[11],
                "hud_buildings_xaml_size");
            RequirePair(
                lines[12],
                "hud_buildings_xaml_sha256",
                expected.HudBuildingsXamlSha256);
            RequirePair(lines[13], "entries_sha256", expected.EntriesSha256);
            string unitNamesSha256 = PairValue(lines[14], "unit_names_sha256");
            int entryCount = ParseIntPair(lines[15], "entry_count");
            int hudCount = ParseIntPair(lines[16], "hud_control_count");
            if (targetTextSize != expected.TargetTextSize
                || hudXamlSize != expected.HudXamlSize
                || hudBuildingsXamlSize != expected.HudBuildingsXamlSize
                || entryCount != 64
                || entryCount != expected.EntryCount
                || hudCount != 17
                || hudCount != expected.HudControlCount
                || !IsLowerHexSha256(unitNamesSha256)
                || lines[17] != EntryHeader)
            {
                throw new InvalidDataException(
                    "Roster manifest compiled counts/fingerprints are not exact");
            }

            RosterTextEntry[] entries = new RosterTextEntry[entryCount];
            HashSet<string> internalKeys = new HashSet<string>(StringComparer.Ordinal);
            HashSet<string> routeKeys = new HashSet<string>(StringComparer.Ordinal);
            Dictionary<string, int> kindCounts =
                new Dictionary<string, int>(StringComparer.Ordinal);
            StringBuilder digestRows = new StringBuilder();
            for (int index = 0; index < entries.Length; index++)
            {
                string[] fields = lines[18 + index].Split('\t');
                if (fields.Length != 8 || fields[0] != "entry")
                {
                    throw new InvalidDataException(
                        "Malformed roster entry row at index " + index);
                }
                RosterTextEntry entry = new RosterTextEntry
                {
                    Kind = CanonicalField(fields[1], "kind"),
                    LogicalId = CanonicalField(fields[2], "logical_id"),
                    Section = CanonicalField(fields[3], "section"),
                    RawIndex = ParseInt(fields[4], "raw_index"),
                    InternalKey = CanonicalField(fields[5], "internal_key"),
                    German = CanonicalField(fields[6], "de"),
                    English = CanonicalField(fields[7], "en")
                };
                if (entry.RawIndex < 0
                    || !string.Equals(
                        entry.InternalKey,
                        entry.Section + "_" + (entry.RawIndex + 1).ToString("D3"),
                        StringComparison.Ordinal)
                    || !internalKeys.Add(entry.InternalKey)
                    || !routeKeys.Add(entry.RawRouteKey))
                {
                    throw new InvalidDataException(
                        "Roster entry route/key is not exact: " + entry.InternalKey);
                }
                int count;
                kindCounts.TryGetValue(entry.Kind, out count);
                kindCounts[entry.Kind] = count + 1;
                digestRows.Append(entry.Kind).Append('\t')
                    .Append(entry.LogicalId).Append('\t')
                    .Append(entry.Section).Append('\t')
                    .Append(entry.RawIndex.ToString(CultureInfo.InvariantCulture)).Append('\t')
                    .Append(entry.InternalKey).Append('\t')
                    .Append(entry.German).Append('\t')
                    .Append(entry.English).Append('\n');
                entries[index] = entry;
            }
            RequireKindCount(kindCounts, "unit_name", 15);
            RequireKindCount(kindCounts, "unit_bubble", 15);
            RequireKindCount(kindCounts, "unit_rally", 15);
            RequireKindCount(kindCounts, "unit_select", 15);
            RequireKindCount(kindCounts, "building_name", 2);
            RequireKindCount(kindCounts, "building_description", 2);
            if (kindCounts.Count != 6
                || !string.Equals(
                    Hashing.Sha256(Encoding.UTF8.GetBytes(digestRows.ToString())),
                    expected.EntriesSha256,
                    StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Roster entry semantic digest/kinds are not exact");
            }

            int hudHeaderIndex = 18 + entryCount;
            if (lines[hudHeaderIndex] != HudHeader)
            {
                throw new InvalidDataException("Roster HUD header is not exact");
            }
            RosterHudBinding[] bindings = new RosterHudBinding[hudCount];
            HashSet<string> controls = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (int index = 0; index < bindings.Length; index++)
            {
                string[] fields = lines[hudHeaderIndex + 1 + index].Split('\t');
                if (fields.Length != 4 || fields[0] != "hud")
                {
                    throw new InvalidDataException(
                        "Malformed roster HUD row at index " + index);
                }
                RosterHudBinding binding = new RosterHudBinding
                {
                    LogicalId = CanonicalField(fields[1], "logical_id"),
                    Control = CanonicalField(fields[2], "control"),
                    InternalKey = CanonicalField(fields[3], "internal_key")
                };
                if (!binding.Control.StartsWith("Button", StringComparison.Ordinal)
                    || !controls.Add(binding.Control)
                    || !internalKeys.Contains(binding.InternalKey))
                {
                    throw new InvalidDataException(
                        "Roster HUD binding is not exact: " + binding.Control);
                }
                bindings[index] = binding;
            }

            return new RosterRuntimeManifest
            {
                TargetTextRelativePath = TargetTextPath,
                TargetTextSize = targetTextSize,
                TargetTextSha256 = expected.TargetTextSha256,
                TargetLocale = "dede",
                TargetOriginalsSha256 = expected.TargetOriginalsSha256,
                HudXamlRelativePath = HudXamlPath,
                HudXamlSize = hudXamlSize,
                HudXamlSha256 = expected.HudXamlSha256,
                HudBuildingsXamlRelativePath = HudBuildingsXamlPath,
                HudBuildingsXamlSize = hudBuildingsXamlSize,
                HudBuildingsXamlSha256 = expected.HudBuildingsXamlSha256,
                EntriesSha256 = expected.EntriesSha256,
                UnitNamesSha256 = unitNamesSha256,
                Entries = entries,
                HudBindings = bindings
            };
        }

        private static void RequireKindCount(
            IDictionary<string, int> counts,
            string kind,
            int expected)
        {
            int actual;
            if (!counts.TryGetValue(kind, out actual) || actual != expected)
            {
                throw new InvalidDataException(
                    "Roster kind count mismatch: " + kind);
            }
        }

        private static string CanonicalField(string value, string label)
        {
            if (string.IsNullOrEmpty(value)
                || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Roster field is not canonical: " + label);
            }
            return value;
        }

        private static void RequirePair(string line, string key, string expected)
        {
            if (!string.Equals(line, key + "\t" + expected, StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Roster manifest field is not exact: " + key);
            }
        }

        private static string PairValue(string line, string key)
        {
            string prefix = key + "\t";
            if (!line.StartsWith(prefix, StringComparison.Ordinal)
                || line.Length == prefix.Length
                || line.IndexOf('\t', prefix.Length) >= 0)
            {
                throw new InvalidDataException(
                    "Malformed roster manifest field: " + key);
            }
            return line.Substring(prefix.Length);
        }

        private static int ParseIntPair(string line, string key)
        {
            return ParseInt(PairValue(line, key), key);
        }

        private static long ParseLongPair(string line, string key)
        {
            long value;
            if (!long.TryParse(
                PairValue(line, key),
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out value)
                || value <= 0)
            {
                throw new InvalidDataException(
                    "Malformed roster manifest integer: " + key);
            }
            return value;
        }

        private static int ParseInt(string value, string label)
        {
            int result;
            if (!int.TryParse(
                value,
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out result))
            {
                throw new InvalidDataException(
                    "Malformed roster integer: " + label);
            }
            return result;
        }

        private static bool IsLowerHexSha256(string value)
        {
            if (value == null || value.Length != 64)
            {
                return false;
            }
            foreach (char character in value)
            {
                if (!((character >= '0' && character <= '9')
                    || (character >= 'a' && character <= 'f')))
                {
                    return false;
                }
            }
            return true;
        }
    }
}
