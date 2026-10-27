using System;
using System.IO;
using System.Security.Cryptography;

namespace StrongholdEuropeDE.Runtime
{
    internal static class Hashing
    {
        internal static string Sha256(byte[] value)
        {
            using (SHA256 algorithm = SHA256.Create())
            {
                return Hex(algorithm.ComputeHash(value));
            }
        }

        internal static string Sha256FileStable(string path, long expectedSize)
        {
            FileInfo before = new FileInfo(path);
            if (!before.Exists || before.Length != expectedSize)
            {
                throw new InvalidDataException(
                    "Unexpected file size for " + path + ": expected=" + expectedSize
                    + " actual=" + (before.Exists ? before.Length.ToString() : "missing"));
            }

            string digest;
            using (FileStream stream = new FileStream(
                path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read))
            using (SHA256 algorithm = SHA256.Create())
            {
                digest = Hex(algorithm.ComputeHash(stream));
            }

            FileInfo after = new FileInfo(path);
            if (!after.Exists
                || before.Length != after.Length
                || before.LastWriteTimeUtc != after.LastWriteTimeUtc)
            {
                throw new IOException("File changed while hashing: " + path);
            }
            return digest;
        }

        private static string Hex(byte[] value)
        {
            char[] output = new char[value.Length * 2];
            const string alphabet = "0123456789abcdef";
            for (int index = 0; index < value.Length; index++)
            {
                output[index * 2] = alphabet[value[index] >> 4];
                output[index * 2 + 1] = alphabet[value[index] & 15];
            }
            return new string(output);
        }
    }
}
