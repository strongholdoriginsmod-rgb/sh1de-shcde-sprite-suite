using System;
using System.Collections.Generic;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Strict parser for the OFFLINE candidate table produced by
    /// tools/building_damage_runtime_preflight.py.
    ///
    /// This class intentionally has no I/O and performs no asset/renderer
    /// registration. The caller must verify the table's approved provenance
    /// and the ZIP digest separately; a candidate is NOT a runnable game mod.
    /// </summary>
    internal static class BuildingDamageProfileTable
    {
        internal const string Schema = "stronghold-building-damage-runtime-table-v1";
        private const string Header =
            "building_type\tbuilding_group\tdamage_kind\thp_le\tstage_id\tscene_id";
        private const string Warning =
            "# Generated from SHA-verified damage library; not an active game mod";

        internal sealed class Document
        {
            internal readonly string PackageSha256;
            internal readonly BuildingDamageStageSelector.Profile[] Profiles;
            internal Document(string digest, BuildingDamageStageSelector.Profile[] profiles)
            {
                PackageSha256 = digest;
                Profiles = profiles;
            }
        }

        private static bool Identity(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length > 80) return false;
            foreach (char ch in value)
            {
                if (!((ch >= 'A' && ch <= 'Z') ||
                    (ch >= 'a' && ch <= 'z') ||
                    (ch >= '0' && ch <= '9') || ch == '_' || ch == '-'))
                    return false;
            }
            return true;
        }

        private static int ParseInteger(string raw, int min, int max)
        {
            int parsed;
            if (raw == null || raw.Length == 0 ||
                (raw.Length > 1 && raw[0] == '0') ||
                !int.TryParse(raw, NumberStyles.None, CultureInfo.InvariantCulture, out parsed) ||
                parsed < min || parsed > max)
                throw new FormatException("Invalid building damage integer in candidate table.");
            return parsed;
        }

        private static bool HexSha256(string value)
        {
            if (value == null || value.Length != 64) return false;
            foreach (char ch in value)
                if (!((ch >= 'a' && ch <= 'f') || (ch >= '0' && ch <= '9')))
                    return false;
            return true;
        }

        internal static Document Parse(string table)
        {
            if (string.IsNullOrEmpty(table) || table.Length > 1024 * 1024)
                throw new FormatException("Empty or oversized building damage candidate table.");
            if (table.IndexOf('\r') >= 0 || table.IndexOf('\0') >= 0)
                throw new FormatException("Candidate table requires normalized UTF-8/LF.");
            string[] lines = table.Split('\n');
            if (lines.Length < 5 || lines[lines.Length - 1] != "" ||
                lines[0] != "# " + Schema || lines[1] != Warning ||
                lines[3] != Header)
                throw new FormatException("Unknown damage candidate table format.");
            const string digestPrefix = "# package-sha256 ";
            if (!lines[2].StartsWith(digestPrefix, StringComparison.Ordinal) ||
                !HexSha256(lines[2].Substring(digestPrefix.Length)))
                throw new FormatException("Invalid candidate table package SHA-256.");
            string digest = lines[2].Substring(digestPrefix.Length);
            var data = new Dictionary<int, List<BuildingDamageStageSelector.Stage>>();
            var groupByType = new Dictionary<int, string>();
            var visited = new HashSet<string>(StringComparer.Ordinal);
            for (int i = 4; i < lines.Length - 1; i++)
            {
                string[] fields = lines[i].Split('\t');
                if (fields.Length != 6)
                    throw new FormatException("Candidate table column count mismatch.");
                int type = ParseInteger(fields[0], 0, 4095);
                string group = fields[1], kind = fields[2];
                int hp = ParseInteger(fields[3], 0, 99);
                string id = fields[4], sceneId = fields[5];
                if (!Identity(group) || !Identity(id) || !Identity(sceneId) ||
                    (kind != "mechanical" && kind != "fire") ||
                    !visited.Add(type.ToString(CultureInfo.InvariantCulture) + ":" + kind +
                        ":" + hp.ToString(CultureInfo.InvariantCulture)))
                    throw new FormatException("Duplicate or invalid building damage stage.");
                string existing;
                if (groupByType.TryGetValue(type, out existing))
                {
                    if (existing != group)
                        throw new FormatException("A building type cannot reference two groups.");
                }
                else groupByType.Add(type, group);
                List<BuildingDamageStageSelector.Stage> stages;
                if (!data.TryGetValue(type, out stages))
                {
                    stages = new List<BuildingDamageStageSelector.Stage>();
                    data.Add(type, stages);
                }
                stages.Add(new BuildingDamageStageSelector.Stage(
                    id, sceneId, kind == "fire" ?
                    BuildingDamageStageSelector.Cause.Fire :
                    BuildingDamageStageSelector.Cause.Mechanical, hp));
                if (stages.Count > BuildingDamageStageSelector.MaximumStagesPerProfile ||
                    data.Count > BuildingDamageStageSelector.MaximumProfiles)
                    throw new FormatException("Too many entries in candidate table.");
            }

            var keys = new List<int>(data.Keys);
            keys.Sort();
            var profiles = new List<BuildingDamageStageSelector.Profile>();
            foreach (int type in keys)
                profiles.Add(new BuildingDamageStageSelector.Profile(
                    type, groupByType[type], data[type]));
            return new Document(digest, profiles.ToArray());
        }

        /// <summary>
        /// Compare the authoritative source ZIP digest, not just a string in
        /// a hand-edited TSV. No global state and no game paths are touched.
        /// </summary>
        internal static bool MatchesPackage(Document document, byte[] package)
        {
            if (document == null || package == null) return false;
            using (SHA256 digest = SHA256.Create())
            {
                byte[] bytes = digest.ComputeHash(package);
                var text = new StringBuilder(64);
                for (int i = 0; i < bytes.Length; i++)
                    text.Append(bytes[i].ToString("x2", CultureInfo.InvariantCulture));
                return string.Equals(document.PackageSha256, text.ToString(),
                    StringComparison.Ordinal);
            }
        }
    }
}
