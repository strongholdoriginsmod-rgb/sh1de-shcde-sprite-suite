using System;
using System.IO;

namespace StrongholdEuropeDE.Runtime.Audio
{
    internal sealed class PcmWaveLayout
    {
        internal PcmWaveLayout(
            int audioFormat,
            int channels,
            int sampleRate,
            int bitsPerSample,
            int blockAlign,
            long dataOffset,
            long dataSize)
        {
            AudioFormat = audioFormat;
            Channels = channels;
            SampleRate = sampleRate;
            BitsPerSample = bitsPerSample;
            BlockAlign = blockAlign;
            DataOffset = dataOffset;
            DataSize = dataSize;
            SampleFrames = checked(dataSize / blockAlign);
        }

        internal int AudioFormat { get; private set; }

        internal int Channels { get; private set; }

        internal int SampleRate { get; private set; }

        internal int BitsPerSample { get; private set; }

        internal int BlockAlign { get; private set; }

        internal long DataOffset { get; private set; }

        internal long DataSize { get; private set; }

        internal long SampleFrames { get; private set; }
    }

    internal sealed class PcmVerifiedWave
    {
        internal PcmVerifiedWave(PcmWaveLayout layout, long lastWriteUtcTicks)
        {
            Layout = layout;
            LastWriteUtcTicks = lastWriteUtcTicks;
        }

        internal PcmWaveLayout Layout { get; private set; }

        internal long LastWriteUtcTicks { get; private set; }
    }

    internal static class PcmWaveFile
    {
        private const uint Riff = 0x46464952U;
        private const uint Wave = 0x45564157U;
        private const uint Format = 0x20746d66U;
        private const uint Data = 0x61746164U;

        internal static PcmVerifiedWave Verify(PcmStreamTrack expected)
        {
            if (expected == null)
            {
                throw new ArgumentNullException("expected");
            }
            var before = new FileInfo(expected.FullPath);
            if (!before.Exists || before.Length != expected.FileSize)
            {
                throw new InvalidDataException("PCM WAV size does not match its manifest");
            }
            if ((before.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException("PCM WAV must not be a reparse point");
            }
            long lastWriteTicks = before.LastWriteTimeUtc.Ticks;
            PcmWaveLayout layout;
            using (var stream = new FileStream(
                expected.FullPath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                4096,
                FileOptions.SequentialScan))
            {
                if (stream.Length != expected.FileSize)
                {
                    throw new InvalidDataException("PCM WAV changed before validation");
                }
                byte[] hashBuffer = new byte[64 * 1024];
                string digest = PcmHash.Sha256(stream, hashBuffer);
                if (!string.Equals(digest, expected.Sha256, StringComparison.Ordinal))
                {
                    throw new InvalidDataException("PCM WAV SHA-256 mismatch");
                }
                stream.Position = 0;
                layout = Parse(stream, expected.FileSize);
                RequireExpectedLayout(layout, expected);
                if (stream.Length != expected.FileSize)
                {
                    throw new InvalidDataException("PCM WAV changed during validation");
                }
            }
            var after = new FileInfo(expected.FullPath);
            if (!after.Exists
                || after.Length != expected.FileSize
                || after.LastWriteTimeUtc.Ticks != lastWriteTicks)
            {
                throw new InvalidDataException("PCM WAV changed during validation");
            }
            return new PcmVerifiedWave(layout, lastWriteTicks);
        }

        internal static FileStream OpenPinned(PcmStreamTrack expected)
        {
            if (expected == null
                || expected.Wave == null
                || string.IsNullOrEmpty(expected.FullPath))
            {
                throw new InvalidOperationException("PCM WAV was not prepared");
            }
            var before = new FileInfo(expected.FullPath);
            if (!before.Exists
                || before.Length != expected.FileSize
                || before.LastWriteTimeUtc.Ticks != expected.LastWriteUtcTicks
                || (before.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException("Prepared PCM WAV identity changed");
            }
            var stream = new FileStream(
                expected.FullPath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                1,
                FileOptions.RandomAccess);
            try
            {
                if (stream.Length != expected.FileSize
                    || File.GetLastWriteTimeUtc(expected.FullPath).Ticks
                        != expected.LastWriteUtcTicks)
                {
                    throw new InvalidDataException("Prepared PCM WAV changed while opening");
                }
                // Size/mtime are only a fast identity prefilter. They can be
                // restored after a same-size payload mutation, so every first
                // use and reuse hashes the pinned handle before the audio
                // callback can observe a byte from it.
                string digest = PcmHash.Sha256(
                    stream,
                    new byte[64 * 1024]);
                if (!string.Equals(
                        digest,
                        expected.Sha256,
                        StringComparison.Ordinal))
                {
                    throw new InvalidDataException(
                        "Prepared PCM WAV SHA-256 changed while opening");
                }
                if (stream.Length != expected.FileSize
                    || File.GetLastWriteTimeUtc(expected.FullPath).Ticks
                        != expected.LastWriteUtcTicks)
                {
                    throw new InvalidDataException(
                        "Prepared PCM WAV changed during pinned SHA-256 verification");
                }
                stream.Position = 0;
                return stream;
            }
            catch
            {
                stream.Dispose();
                throw;
            }
        }

        internal static bool IdentityStillMatches(PcmStreamTrack expected)
        {
            if (expected == null
                || expected.Wave == null
                || string.IsNullOrEmpty(expected.FullPath))
            {
                return false;
            }
            try
            {
                var current = new FileInfo(expected.FullPath);
                return current.Exists
                    && current.Length == expected.FileSize
                    && current.LastWriteTimeUtc.Ticks == expected.LastWriteUtcTicks
                    && (current.Attributes & FileAttributes.ReparsePoint) == 0;
            }
            catch
            {
                return false;
            }
        }

        internal static PcmWaveLayout Parse(Stream stream, long expectedLength)
        {
            if (stream == null)
            {
                throw new ArgumentNullException("stream");
            }
            if (!stream.CanRead
                || !stream.CanSeek
                || expectedLength < 44
                || stream.Length != expectedLength)
            {
                throw new InvalidDataException("PCM WAV stream is not readable/seekable");
            }
            stream.Position = 0;
            if (ReadUInt32(stream) != Riff
                || ReadUInt32(stream) != checked((uint)(expectedLength - 8))
                || ReadUInt32(stream) != Wave)
            {
                throw new InvalidDataException("PCM WAV RIFF/WAVE header is not canonical");
            }

            bool sawFormat = false;
            bool sawData = false;
            int audioFormat = -1;
            int channels = -1;
            int sampleRate = -1;
            long byteRate = -1;
            int blockAlign = -1;
            int bitsPerSample = -1;
            long dataOffset = -1;
            long dataSize = -1;

            while (stream.Position < expectedLength)
            {
                if (expectedLength - stream.Position < 8)
                {
                    throw new InvalidDataException("PCM WAV has a truncated chunk header");
                }
                uint chunkId = ReadUInt32(stream);
                uint chunkSize = ReadUInt32(stream);
                long chunkStart = stream.Position;
                long chunkEnd = checked(chunkStart + chunkSize);
                long paddedEnd = checked(chunkEnd + (chunkSize & 1U));
                if (chunkEnd > expectedLength || paddedEnd > expectedLength)
                {
                    throw new InvalidDataException("PCM WAV chunk exceeds file bounds");
                }

                if (chunkId == Format)
                {
                    if (sawFormat || chunkSize < 16)
                    {
                        throw new InvalidDataException("PCM WAV has a duplicate/short fmt chunk");
                    }
                    sawFormat = true;
                    audioFormat = ReadUInt16(stream);
                    channels = ReadUInt16(stream);
                    sampleRate = checked((int)ReadUInt32(stream));
                    byteRate = ReadUInt32(stream);
                    blockAlign = ReadUInt16(stream);
                    bitsPerSample = ReadUInt16(stream);
                }
                else if (chunkId == Data)
                {
                    if (sawData)
                    {
                        throw new InvalidDataException("PCM WAV has duplicate data chunks");
                    }
                    sawData = true;
                    dataOffset = chunkStart;
                    dataSize = chunkSize;
                }

                stream.Position = paddedEnd;
            }

            if (!sawFormat
                || !sawData
                || audioFormat != 1
                || channels <= 0
                || sampleRate <= 0
                || bitsPerSample != 16
                || blockAlign != channels * 2
                || byteRate != (long)sampleRate * blockAlign
                || dataSize <= 0
                || dataSize % blockAlign != 0
                || dataOffset < 0
                || dataOffset + dataSize > expectedLength)
            {
                throw new InvalidDataException("PCM WAV format/data contract is invalid");
            }
            return new PcmWaveLayout(
                audioFormat,
                channels,
                sampleRate,
                bitsPerSample,
                blockAlign,
                dataOffset,
                dataSize);
        }

        private static void RequireExpectedLayout(
            PcmWaveLayout actual,
            PcmStreamTrack expected)
        {
            if (actual.AudioFormat != expected.AudioFormat
                || actual.Channels != expected.Channels
                || actual.SampleRate != expected.SampleRate
                || actual.BitsPerSample != expected.BitsPerSample
                || actual.BlockAlign != expected.BlockAlign
                || actual.DataSize != expected.DataSize
                || actual.SampleFrames > int.MaxValue)
            {
                throw new InvalidDataException("PCM WAV metadata differs from its manifest");
            }
        }

        private static int ReadUInt16(Stream stream)
        {
            int first = stream.ReadByte();
            int second = stream.ReadByte();
            if (first < 0 || second < 0)
            {
                throw new EndOfStreamException("PCM WAV integer is truncated");
            }
            return first | (second << 8);
        }

        private static uint ReadUInt32(Stream stream)
        {
            int first = stream.ReadByte();
            int second = stream.ReadByte();
            int third = stream.ReadByte();
            int fourth = stream.ReadByte();
            if (first < 0 || second < 0 || third < 0 || fourth < 0)
            {
                throw new EndOfStreamException("PCM WAV integer is truncated");
            }
            return (uint)(first
                | (second << 8)
                | (third << 16)
                | (fourth << 24));
        }
    }
}
