using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace StrongholdEuropeDE.Runtime.Audio
{
    internal static class PcmStreamingLimits
    {
        internal const int MaximumActiveStreams = 2;
        internal const long MaximumBufferBytes = 16L * 1024L * 1024L;
        internal const int BufferBytesPerStream = 1024 * 1024;
        internal const int MaximumManifestBytes = 1024 * 1024;
        internal const int MaximumTrackCount = 512;
        internal const string PayloadRelativeDirectory = "Runtime/Audio";
        internal const string ManifestFileName = "pcm-stream-manifest.tsv";
    }

    internal sealed class PcmStreamTrack
    {
        private int _runtimeFaulted;
        private string _runtimeFailureKind;

        internal PcmStreamTrack(
            string request,
            string fileName,
            long fileSize,
            string sha256,
            int audioFormat,
            int channels,
            int sampleRate,
            int bitsPerSample,
            int blockAlign,
            long dataSize)
        {
            Request = request;
            FileName = fileName;
            FileSize = fileSize;
            Sha256 = sha256;
            AudioFormat = audioFormat;
            Channels = channels;
            SampleRate = sampleRate;
            BitsPerSample = bitsPerSample;
            BlockAlign = blockAlign;
            DataSize = dataSize;
        }

        internal string Request { get; private set; }

        internal string FileName { get; private set; }

        internal long FileSize { get; private set; }

        internal string Sha256 { get; private set; }

        internal int AudioFormat { get; private set; }

        internal int Channels { get; private set; }

        internal int SampleRate { get; private set; }

        internal int BitsPerSample { get; private set; }

        internal int BlockAlign { get; private set; }

        internal long DataSize { get; private set; }

        internal string FullPath { get; set; }

        internal long LastWriteUtcTicks { get; set; }

        internal PcmWaveLayout Wave { get; set; }

        internal bool RuntimeFaulted
        {
            get { return Volatile.Read(ref _runtimeFaulted) != 0; }
        }

        internal string RuntimeFailureKind
        {
            get { return Volatile.Read(ref _runtimeFailureKind); }
        }

        internal void MarkRuntimeFault(Exception exception)
        {
            string failureKind = exception == null
                ? "UnknownFailure"
                : exception.GetType().Name;
            Interlocked.CompareExchange(
                ref _runtimeFailureKind,
                failureKind,
                null);
            Volatile.Write(ref _runtimeFaulted, 1);
        }
    }

    /// <summary>
    /// Exact, digest-pinned contract for the private procedural music payload.
    /// Payload files are deliberately outside SHCDE-SE's Override/Sounds tree.
    /// </summary>
    internal sealed class PcmStreamManifest
    {
        private const string Signature = "stronghold-europe-pcm-stream\t1";
        private const string TrackHeader =
            "track\trequest\tfile\tfile_size\tsha256\taudio_format\tchannels"
            + "\tsample_rate\tbits_per_sample\tblock_align\tdata_size";

        private readonly Dictionary<string, PcmStreamTrack> _byRequest;

        private PcmStreamManifest(PcmStreamTrack[] tracks)
        {
            Tracks = tracks;
            _byRequest = new Dictionary<string, PcmStreamTrack>(
                tracks.Length,
                StringComparer.Ordinal);
            for (int index = 0; index < tracks.Length; index++)
            {
                _byRequest.Add(tracks[index].Request, tracks[index]);
            }
        }

        internal PcmStreamTrack[] Tracks { get; private set; }

        internal bool TryGetTrack(string request, out PcmStreamTrack track)
        {
            track = null;
            return IsCanonicalRequest(request)
                && _byRequest.TryGetValue(request, out track);
        }

        internal static PcmStreamManifest LoadAndValidate(
            string pluginDirectory,
            string expectedManifestSha256)
        {
            if (string.IsNullOrWhiteSpace(pluginDirectory))
            {
                throw new ArgumentException("Plugin directory is required", "pluginDirectory");
            }
            RequireLowerSha256(expectedManifestSha256, "expected manifest SHA-256");

            string pluginRoot = Path.GetFullPath(pluginDirectory);
            string runtimeDirectory = Path.GetFullPath(
                Path.Combine(pluginRoot, "Runtime"));
            string audioDirectory = Path.GetFullPath(
                Path.Combine(runtimeDirectory, "Audio"));
            RequireDirectChild(runtimeDirectory, audioDirectory, "Audio payload directory");
            if (!Directory.Exists(audioDirectory))
            {
                throw new DirectoryNotFoundException(
                    "The canonical Runtime/Audio payload directory is missing");
            }
            RejectReparsePoint(runtimeDirectory, true);
            RejectReparsePoint(audioDirectory, true);

            string manifestPath = Path.Combine(
                audioDirectory,
                PcmStreamingLimits.ManifestFileName);
            RejectReparsePoint(manifestPath, false);
            byte[] manifestBytes = ReadSmallFileStable(manifestPath);
            PcmStreamManifest manifest = Parse(manifestBytes, expectedManifestSha256);

            string[] subdirectories = Directory.GetDirectories(
                audioDirectory,
                "*",
                SearchOption.TopDirectoryOnly);
            if (subdirectories.Length != 0)
            {
                throw new InvalidDataException(
                    "Runtime/Audio must be flat and contain no subdirectories");
            }

            var expectedFiles = new HashSet<string>(StringComparer.Ordinal);
            expectedFiles.Add(PcmStreamingLimits.ManifestFileName);
            for (int index = 0; index < manifest.Tracks.Length; index++)
            {
                expectedFiles.Add(manifest.Tracks[index].FileName);
            }

            string[] actualFiles = Directory.GetFiles(
                audioDirectory,
                "*",
                SearchOption.TopDirectoryOnly);
            if (actualFiles.Length != expectedFiles.Count)
            {
                throw new InvalidDataException(
                    "Runtime/Audio file count differs from the pinned manifest");
            }
            for (int index = 0; index < actualFiles.Length; index++)
            {
                string fileName = Path.GetFileName(actualFiles[index]);
                if (!expectedFiles.Remove(fileName))
                {
                    throw new InvalidDataException(
                        "Runtime/Audio contains an unexpected or case-variant file");
                }
            }
            if (expectedFiles.Count != 0)
            {
                throw new InvalidDataException(
                    "Runtime/Audio is missing one or more manifest files");
            }

            for (int index = 0; index < manifest.Tracks.Length; index++)
            {
                PcmStreamTrack track = manifest.Tracks[index];
                string fullPath = Path.GetFullPath(
                    Path.Combine(audioDirectory, track.FileName));
                RequireDirectChild(audioDirectory, fullPath, "PCM payload file");
                RejectReparsePoint(fullPath, false);
                track.FullPath = fullPath;
                PcmVerifiedWave verified = PcmWaveFile.Verify(track);
                track.Wave = verified.Layout;
                track.LastWriteUtcTicks = verified.LastWriteUtcTicks;
            }
            return manifest;
        }

        internal static PcmStreamManifest Parse(
            byte[] bytes,
            string expectedManifestSha256)
        {
            if (bytes == null)
            {
                throw new ArgumentNullException("bytes");
            }
            if (bytes.Length == 0
                || bytes.Length > PcmStreamingLimits.MaximumManifestBytes)
            {
                throw new InvalidDataException("PCM stream manifest size is invalid");
            }
            RequireLowerSha256(expectedManifestSha256, "expected manifest SHA-256");
            string actualSha256 = PcmHash.Sha256(bytes);
            if (!string.Equals(
                actualSha256,
                expectedManifestSha256,
                StringComparison.Ordinal))
            {
                throw new InvalidDataException("PCM stream manifest SHA-256 mismatch");
            }

            string text;
            try
            {
                text = new UTF8Encoding(false, true).GetString(bytes);
            }
            catch (DecoderFallbackException exception)
            {
                throw new InvalidDataException(
                    "PCM stream manifest is not strict UTF-8",
                    exception);
            }
            if (text.Length == 0
                || text[0] == '\ufeff'
                || text.IndexOf('\r') >= 0
                || !text.EndsWith("\n", StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "PCM stream manifest must be BOM-free UTF-8/LF with a final newline");
            }

            string[] lines = text.Substring(0, text.Length - 1).Split('\n');
            if (lines.Length < 8 || lines[0] != Signature)
            {
                throw new InvalidDataException("PCM stream manifest signature/shape is invalid");
            }
            RequirePair(
                lines[1],
                "payload_root",
                PcmStreamingLimits.PayloadRelativeDirectory);
            RequirePair(
                lines[2],
                "max_active_streams",
                PcmStreamingLimits.MaximumActiveStreams.ToString(
                    CultureInfo.InvariantCulture));
            RequirePair(
                lines[3],
                "buffer_budget_bytes",
                PcmStreamingLimits.MaximumBufferBytes.ToString(
                    CultureInfo.InvariantCulture));
            RequirePair(
                lines[4],
                "buffer_bytes_per_stream",
                PcmStreamingLimits.BufferBytesPerStream.ToString(
                    CultureInfo.InvariantCulture));
            int trackCount = ParseCanonicalIntPair(lines[5], "track_count");
            if (trackCount <= 0 || trackCount > PcmStreamingLimits.MaximumTrackCount)
            {
                throw new InvalidDataException("PCM stream track count is outside its bound");
            }
            if (lines.Length != 7 + trackCount || lines[6] != TrackHeader)
            {
                throw new InvalidDataException("PCM stream manifest row count/header is not exact");
            }

            var requests = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var fileNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var tracks = new PcmStreamTrack[trackCount];
            for (int index = 0; index < trackCount; index++)
            {
                string[] fields = lines[7 + index].Split('\t');
                if (fields.Length != 11 || fields[0] != "track")
                {
                    throw new InvalidDataException(
                        "Malformed PCM stream track row at index " + index);
                }
                string request = fields[1];
                string fileName = fields[2];
                if (!IsCanonicalRequest(request)
                    || !string.Equals(fileName, request, StringComparison.Ordinal))
                {
                    throw new InvalidDataException(
                        "PCM stream request/file path is not canonical at index " + index);
                }
                var track = new PcmStreamTrack(
                    request,
                    fileName,
                    ParseCanonicalLong(fields[3], "file_size"),
                    fields[4],
                    ParseCanonicalInt(fields[5], "audio_format"),
                    ParseCanonicalInt(fields[6], "channels"),
                    ParseCanonicalInt(fields[7], "sample_rate"),
                    ParseCanonicalInt(fields[8], "bits_per_sample"),
                    ParseCanonicalInt(fields[9], "block_align"),
                    ParseCanonicalLong(fields[10], "data_size"));
                ValidateTrack(track);
                if (!requests.Add(track.Request) || !fileNames.Add(track.FileName))
                {
                    throw new InvalidDataException(
                        "PCM stream manifest contains a duplicate request/file");
                }
                tracks[index] = track;
            }
            return new PcmStreamManifest(tracks);
        }

        internal static bool IsCanonicalRequest(string value)
        {
            if (string.IsNullOrEmpty(value)
                || value.Length > 128
                || !value.StartsWith("eu_", StringComparison.Ordinal)
                || !value.EndsWith(".wav", StringComparison.Ordinal)
                || !string.Equals(
                    Path.GetFileName(value),
                    value,
                    StringComparison.Ordinal))
            {
                return false;
            }
            int stemEnd = value.Length - 4;
            if (stemEnd <= 3)
            {
                return false;
            }
            for (int index = 3; index < stemEnd; index++)
            {
                char character = value[index];
                if (!((character >= 'a' && character <= 'z')
                    || (character >= '0' && character <= '9')
                    || character == '_'))
                {
                    return false;
                }
            }
            return true;
        }

        private static void ValidateTrack(PcmStreamTrack track)
        {
            RequireLowerSha256(track.Sha256, "track SHA-256");
            if (track.FileSize <= 44
                || track.FileSize > uint.MaxValue + 8L
                || track.AudioFormat != 1
                || track.Channels != 2
                || track.SampleRate != 44100
                || track.BitsPerSample != 16
                || track.BlockAlign != track.Channels * 2
                || track.DataSize <= 0
                || track.DataSize > uint.MaxValue
                || track.DataSize > track.FileSize
                || track.DataSize % track.BlockAlign != 0
                || track.DataSize / track.BlockAlign > int.MaxValue)
            {
                throw new InvalidDataException(
                    "PCM stream track metadata is outside the supported PCM16 contract");
            }
        }

        private static byte[] ReadSmallFileStable(string path)
        {
            var before = new FileInfo(path);
            if (!before.Exists
                || before.Length <= 0
                || before.Length > PcmStreamingLimits.MaximumManifestBytes)
            {
                throw new InvalidDataException("PCM stream manifest is missing or oversized");
            }
            long expectedLength = before.Length;
            long expectedWriteTicks = before.LastWriteTimeUtc.Ticks;
            byte[] bytes = new byte[checked((int)expectedLength)];
            using (var stream = new FileStream(
                path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                4096,
                FileOptions.SequentialScan))
            {
                int offset = 0;
                while (offset < bytes.Length)
                {
                    int read = stream.Read(bytes, offset, bytes.Length - offset);
                    if (read == 0)
                    {
                        throw new EndOfStreamException("PCM stream manifest was truncated");
                    }
                    offset += read;
                }
                if (stream.ReadByte() != -1 || stream.Length != expectedLength)
                {
                    throw new InvalidDataException("PCM stream manifest size changed while reading");
                }
            }
            var after = new FileInfo(path);
            if (!after.Exists
                || after.Length != expectedLength
                || after.LastWriteTimeUtc.Ticks != expectedWriteTicks)
            {
                throw new InvalidDataException("PCM stream manifest changed while reading");
            }
            return bytes;
        }

        private static void RequireDirectChild(
            string expectedParent,
            string path,
            string label)
        {
            string actualParent = Path.GetDirectoryName(path);
            if (!string.Equals(
                Path.GetFullPath(expectedParent),
                Path.GetFullPath(actualParent ?? string.Empty),
                StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(label + " is not a canonical direct child");
            }
        }

        private static void RejectReparsePoint(string path, bool directory)
        {
            FileAttributes attributes;
            try
            {
                attributes = File.GetAttributes(path);
            }
            catch (Exception exception)
            {
                if (!(exception is IOException)
                    && !(exception is UnauthorizedAccessException))
                {
                    throw;
                }
                throw new InvalidDataException(
                    "PCM stream canonical path cannot be inspected",
                    exception);
            }
            if ((attributes & FileAttributes.ReparsePoint) != 0
                || directory != ((attributes & FileAttributes.Directory) != 0))
            {
                throw new InvalidDataException(
                    "PCM stream canonical path has an unexpected type or reparse point");
            }
        }

        private static void RequirePair(string line, string key, string expectedValue)
        {
            if (!string.Equals(
                line,
                key + "\t" + expectedValue,
                StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "PCM stream manifest field is not exact: " + key);
            }
        }

        private static int ParseCanonicalIntPair(string line, string key)
        {
            string prefix = key + "\t";
            if (!line.StartsWith(prefix, StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "PCM stream manifest field is not exact: " + key);
            }
            return ParseCanonicalInt(line.Substring(prefix.Length), key);
        }

        private static int ParseCanonicalInt(string value, string label)
        {
            int parsed;
            if (!int.TryParse(
                value,
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out parsed)
                || !string.Equals(
                    value,
                    parsed.ToString(CultureInfo.InvariantCulture),
                    StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "PCM stream manifest integer is not canonical: " + label);
            }
            return parsed;
        }

        private static long ParseCanonicalLong(string value, string label)
        {
            long parsed;
            if (!long.TryParse(
                value,
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out parsed)
                || !string.Equals(
                    value,
                    parsed.ToString(CultureInfo.InvariantCulture),
                    StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "PCM stream manifest integer is not canonical: " + label);
            }
            return parsed;
        }

        private static void RequireLowerSha256(string value, string label)
        {
            if (!PcmHash.IsLowerSha256(value))
            {
                throw new InvalidDataException(label + " is not canonical lowercase hex");
            }
        }
    }

    internal static class PcmHash
    {
        internal static string Sha256(byte[] bytes)
        {
            using (SHA256 algorithm = SHA256.Create())
            {
                return ToLowerHex(algorithm.ComputeHash(bytes));
            }
        }

        internal static string Sha256(Stream stream, byte[] buffer)
        {
            if (stream == null)
            {
                throw new ArgumentNullException("stream");
            }
            if (buffer == null || buffer.Length < 4096)
            {
                throw new ArgumentException("Hash buffer is too small", "buffer");
            }
            using (SHA256 algorithm = SHA256.Create())
            {
                int read;
                while ((read = stream.Read(buffer, 0, buffer.Length)) != 0)
                {
                    algorithm.TransformBlock(buffer, 0, read, null, 0);
                }
                algorithm.TransformFinalBlock(new byte[0], 0, 0);
                return ToLowerHex(algorithm.Hash);
            }
        }

        internal static bool IsLowerSha256(string value)
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

        private static string ToLowerHex(byte[] bytes)
        {
            const string alphabet = "0123456789abcdef";
            char[] result = new char[bytes.Length * 2];
            for (int index = 0; index < bytes.Length; index++)
            {
                result[index * 2] = alphabet[bytes[index] >> 4];
                result[index * 2 + 1] = alphabet[bytes[index] & 15];
            }
            return new string(result);
        }
    }
}
