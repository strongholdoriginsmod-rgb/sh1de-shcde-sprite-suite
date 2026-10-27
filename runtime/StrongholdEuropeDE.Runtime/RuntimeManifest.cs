using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed class AudioTrack
    {
        internal int Id;
        internal string SourceFile;
        internal string OutputFile;
        internal string ExpectedOriginal;
        internal string Replacement;
        internal int VolumeRaw;
        internal long FileSize;
        internal string Sha256;
        internal int AudioFormat;
        internal int Channels;
        internal int SampleRate;
        internal int BitsPerSample;
        internal int BlockAlign;
        internal long DataSize;
    }

    internal sealed class RuntimeManifest
    {
        private const string Signature = "stronghold-europe-audio-profile\t1";
        private const string TrackHeader =
            "track\tid\tsource_file\toutput_file\texpected_original\treplacement"
            + "\tvolume_raw\tfile_size\tsha256\taudio_format\tchannels\tsample_rate"
            + "\tbits_per_sample\tblock_align\tdata_size";

        internal bool AudioPayload;
        internal bool FoliageTreeApple;
        internal AudioTrack[] Tracks;

        internal static RuntimeManifest Load(string path)
        {
            byte[] bytes = File.ReadAllBytes(path);
            string digest = Hashing.Sha256(bytes);
            if (!string.Equals(
                digest,
                GeneratedAudioContract.ManifestSha256,
                StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Runtime manifest SHA-256 mismatch: expected="
                    + GeneratedAudioContract.ManifestSha256 + " actual=" + digest);
            }

            string text = new UTF8Encoding(false, true).GetString(bytes);
            if (text.IndexOf('\r') >= 0 || !text.EndsWith("\n", StringComparison.Ordinal))
            {
                throw new InvalidDataException("Runtime manifest must be canonical UTF-8/LF with a final newline");
            }
            string[] lines = text.Substring(0, text.Length - 1).Split('\n');
            int expectedLineCount = 11 + GeneratedAudioContract.TrackIds.Length;
            if (lines.Length != expectedLineCount || lines[0] != Signature)
            {
                throw new InvalidDataException(
                    "Runtime manifest shape mismatch: expectedLines=" + expectedLineCount
                    + " actualLines=" + lines.Length);
            }

            RequirePair(lines[1], "plugin_id", GeneratedAudioContract.PluginId);
            RequirePair(lines[2], "source_build_id", GeneratedAudioContract.SourceBuildId);
            RequirePair(lines[3], "target_build_id", GeneratedAudioContract.TargetBuildId);
            RequirePair(
                lines[4],
                "target_assembly_sha256",
                GeneratedAudioContract.TargetAssemblySha256);
            RequirePair(
                lines[5],
                "script_extender_version",
                GeneratedAudioContract.ScriptExtenderVersion);
            RequirePair(
                lines[6],
                "script_extender_sha256",
                GeneratedAudioContract.ScriptExtenderSha256);
            bool audioPayload = ParseBooleanPair(lines[7], "audio_payload");
            bool foliageTreeApple = ParseBooleanPair(lines[8], "foliage_tree_apple");
            RequirePair(
                lines[9],
                "track_count",
                GeneratedAudioContract.TrackIds.Length.ToString(CultureInfo.InvariantCulture));
            if (lines[10] != TrackHeader)
            {
                throw new InvalidDataException("Runtime manifest track header is not exact");
            }

            AudioTrack[] tracks = new AudioTrack[GeneratedAudioContract.TrackIds.Length];
            HashSet<string> outputs = new HashSet<string>(StringComparer.Ordinal);
            HashSet<string> replacements = new HashSet<string>(StringComparer.Ordinal);
            for (int index = 0; index < tracks.Length; index++)
            {
                string[] fields = lines[11 + index].Split('\t');
                if (fields.Length != 15 || fields[0] != "track")
                {
                    throw new InvalidDataException("Malformed runtime track row at index " + index);
                }
                AudioTrack track = new AudioTrack
                {
                    Id = ParseInt(fields[1], "id"),
                    SourceFile = fields[2],
                    OutputFile = fields[3],
                    ExpectedOriginal = fields[4],
                    Replacement = fields[5],
                    VolumeRaw = ParseInt(fields[6], "volume_raw"),
                    FileSize = ParseLong(fields[7], "file_size"),
                    Sha256 = fields[8],
                    AudioFormat = ParseInt(fields[9], "audio_format"),
                    Channels = ParseInt(fields[10], "channels"),
                    SampleRate = ParseInt(fields[11], "sample_rate"),
                    BitsPerSample = ParseInt(fields[12], "bits_per_sample"),
                    BlockAlign = ParseInt(fields[13], "block_align"),
                    DataSize = ParseLong(fields[14], "data_size")
                };
                ValidateTrack(track, GeneratedAudioContract.TrackIds[index]);
                if (!outputs.Add(track.OutputFile) || !replacements.Add(track.Replacement))
                {
                    throw new InvalidDataException("Duplicate runtime audio output or replacement path");
                }
                tracks[index] = track;
            }

            return new RuntimeManifest
            {
                AudioPayload = audioPayload,
                FoliageTreeApple = foliageTreeApple,
                Tracks = tracks
            };
        }

        private static void ValidateTrack(AudioTrack track, int expectedId)
        {
            if (track.Id != expectedId)
            {
                throw new InvalidDataException(
                    "Runtime track ID/order mismatch: expected=" + expectedId + " actual=" + track.Id);
            }
            RequireFlatWaveName(track.SourceFile, false);
            RequireFlatWaveName(track.OutputFile, true);
            string derivedReplacement = "fx\\music\\"
                + Path.GetFileNameWithoutExtension(track.OutputFile) + ".raw";
            if (!string.Equals(track.Replacement, derivedReplacement, StringComparison.Ordinal)
                || !IsMusicRawPath(track.ExpectedOriginal))
            {
                throw new InvalidDataException("Invalid music-table path for ID " + track.Id);
            }
            if (track.VolumeRaw < 0 || track.VolumeRaw > 127
                || track.FileSize <= 44
                || track.DataSize <= 0
                || track.DataSize > track.FileSize
                || !IsLowerHexSha256(track.Sha256)
                || track.AudioFormat != 1
                || track.Channels != 2
                || track.SampleRate != 44100
                || track.BitsPerSample != 16
                || track.BlockAlign != 4)
            {
                throw new InvalidDataException("Invalid PCM contract for ID " + track.Id);
            }
        }

        private static void RequireFlatWaveName(string value, bool output)
        {
            if (string.IsNullOrEmpty(value)
                || !string.Equals(Path.GetFileName(value), value, StringComparison.Ordinal)
                || !value.EndsWith(".wav", StringComparison.OrdinalIgnoreCase)
                || value.IndexOf('\t') >= 0)
            {
                throw new InvalidDataException("Unsafe WAV filename: " + value);
            }
            if (output
                && (!value.StartsWith("eu_", StringComparison.Ordinal)
                    || !string.Equals(value, value.ToLowerInvariant(), StringComparison.Ordinal)))
            {
                throw new InvalidDataException("Runtime output WAV name is not canonical: " + value);
            }
        }

        private static bool IsMusicRawPath(string value)
        {
            return !string.IsNullOrEmpty(value)
                && value.StartsWith("fx\\music\\", StringComparison.Ordinal)
                && value.EndsWith(".raw", StringComparison.Ordinal)
                && value.IndexOf('/') < 0
                && value.IndexOf('\t') < 0;
        }

        private static bool IsLowerHexSha256(string value)
        {
            if (value == null || value.Length != 64)
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

        private static void RequirePair(string line, string key, string value)
        {
            if (!string.Equals(line, key + "\t" + value, StringComparison.Ordinal))
            {
                throw new InvalidDataException("Runtime manifest field is not exact: " + key);
            }
        }

        private static bool ParseBooleanPair(string line, string key)
        {
            if (line == key + "\t0")
            {
                return false;
            }
            if (line == key + "\t1")
            {
                return true;
            }
            throw new InvalidDataException("Runtime manifest boolean is not exact: " + key);
        }

        private static int ParseInt(string value, string label)
        {
            int result;
            if (!int.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out result))
            {
                throw new InvalidDataException("Invalid integer " + label + ": " + value);
            }
            return result;
        }

        private static long ParseLong(string value, string label)
        {
            long result;
            if (!long.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out result))
            {
                throw new InvalidDataException("Invalid integer " + label + ": " + value);
            }
            return result;
        }
    }
}
