using System;
using System.IO;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    internal static class WavValidator
    {
        internal static void Validate(string path, AudioTrack expected)
        {
            string digest = Hashing.Sha256FileStable(path, expected.FileSize);
            if (!string.Equals(digest, expected.Sha256, StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "WAV SHA-256 mismatch for " + expected.OutputFile
                    + ": expected=" + expected.Sha256 + " actual=" + digest);
            }

            using (FileStream stream = new FileStream(
                path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read))
            using (BinaryReader reader = new BinaryReader(stream, Encoding.ASCII, true))
            {
                if (stream.Length < 44
                    || ReadFourCc(reader) != "RIFF"
                    || reader.ReadUInt32() != checked((uint)(stream.Length - 8))
                    || ReadFourCc(reader) != "WAVE")
                {
                    throw new InvalidDataException("Invalid canonical RIFF/WAVE header: " + path);
                }

                bool foundFormat = false;
                bool foundData = false;
                int audioFormat = -1;
                int channels = -1;
                int sampleRate = -1;
                int byteRate = -1;
                int blockAlign = -1;
                int bitsPerSample = -1;
                long dataSize = -1;

                while (stream.Position < stream.Length)
                {
                    if (stream.Length - stream.Position < 8)
                    {
                        throw new InvalidDataException("Truncated WAV chunk header: " + path);
                    }
                    string chunkId = ReadFourCc(reader);
                    uint chunkSize = reader.ReadUInt32();
                    long chunkStart = stream.Position;
                    long chunkEnd = checked(chunkStart + chunkSize);
                    if (chunkEnd > stream.Length)
                    {
                        throw new InvalidDataException("WAV chunk exceeds file bounds: " + path);
                    }

                    if (chunkId == "fmt ")
                    {
                        if (foundFormat || chunkSize < 16)
                        {
                            throw new InvalidDataException("Invalid duplicate/short WAV fmt chunk: " + path);
                        }
                        foundFormat = true;
                        audioFormat = reader.ReadUInt16();
                        channels = reader.ReadUInt16();
                        sampleRate = checked((int)reader.ReadUInt32());
                        byteRate = checked((int)reader.ReadUInt32());
                        blockAlign = reader.ReadUInt16();
                        bitsPerSample = reader.ReadUInt16();
                    }
                    else if (chunkId == "data")
                    {
                        if (foundData)
                        {
                            throw new InvalidDataException("Duplicate WAV data chunk: " + path);
                        }
                        foundData = true;
                        dataSize = chunkSize;
                    }

                    stream.Position = chunkEnd;
                    if ((chunkSize & 1U) != 0U)
                    {
                        if (stream.Position >= stream.Length)
                        {
                            throw new InvalidDataException("Missing WAV chunk padding byte: " + path);
                        }
                        stream.Position++;
                    }
                }

                if (!foundFormat
                    || !foundData
                    || audioFormat != expected.AudioFormat
                    || channels != expected.Channels
                    || sampleRate != expected.SampleRate
                    || bitsPerSample != expected.BitsPerSample
                    || blockAlign != expected.BlockAlign
                    || byteRate != checked(sampleRate * blockAlign)
                    || dataSize != expected.DataSize)
                {
                    throw new InvalidDataException(
                        "WAV PCM metadata mismatch for " + expected.OutputFile);
                }
            }
        }

        private static string ReadFourCc(BinaryReader reader)
        {
            byte[] bytes = reader.ReadBytes(4);
            if (bytes.Length != 4)
            {
                throw new EndOfStreamException("Truncated FourCC");
            }
            return Encoding.ASCII.GetString(bytes);
        }
    }
}
