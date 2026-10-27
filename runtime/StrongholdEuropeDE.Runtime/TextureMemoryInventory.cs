using System;
using System.Globalization;
using System.Threading;
using UnityEngine;
using UnityEngine.Profiling;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// One-shot, read-only inventory used to distinguish compressed Unity
    /// textures from accidental readable/RGBA residency. It deliberately runs
    /// before the first Europe GM can be admitted and never changes gameplay,
    /// texture state, or loader state.
    /// </summary>
    internal static class TextureMemoryInventory
    {
        private const int MaximumBuckets = 128;
        private const int MaximumTopEntries = 20;
        private const string Phase = "post_ui_baseline_pre_gm";
        private static int _state;

        internal static void TryCaptureOnce(
            Action<string> information,
            Action<string> warning)
        {
            if (Interlocked.CompareExchange(ref _state, 1, 0) != 0)
            {
                return;
            }

            try
            {
                Capture(information);
            }
            catch (Exception exception)
            {
                Emit(
                    warning,
                    "SEDE_RUNTIME_V1|event=texture_inventory"
                    + "|status=unavailable|phase=" + Phase
                    + "|reason=" + Token(exception.GetType().Name));
            }
            finally
            {
                Volatile.Write(ref _state, 2);
            }
        }

        private static void Capture(Action<string> information)
        {
            Texture2D[] textures = Resources.FindObjectsOfTypeAll<Texture2D>();
            if (textures == null)
            {
                throw new InvalidOperationException(
                    "Unity returned no Texture2D inventory array");
            }

            var buckets = new Bucket[MaximumBuckets];
            var top = new TopEntry[MaximumTopEntries];
            int bucketCount = 0;
            int topCount = 0;
            int observed = 0;
            int readableTextures = 0;
            int unknownSizeCount = 0;
            int failedObjects = 0;
            long totalRuntimeBytes = 0;
            long readableRuntimeBytes = 0;

            for (int index = 0; index < textures.Length; index++)
            {
                Texture2D texture = textures[index];
                try
                {
                    if (ReferenceEquals(texture, null) || texture == null)
                    {
                        continue;
                    }
                    int width = texture.width;
                    int height = texture.height;
                    int mipmaps = texture.mipmapCount;
                    TextureFormat format = texture.format;
                    bool readable = texture.isReadable;
                    int instanceId = texture.GetInstanceID();
                    long runtimeBytes = Profiler.GetRuntimeMemorySizeLong(texture);
                    long pixels = checked((long)width * height);

                    observed = checked(observed + 1);
                    if (runtimeBytes <= 0)
                    {
                        unknownSizeCount = checked(unknownSizeCount + 1);
                        runtimeBytes = 0;
                    }
                    totalRuntimeBytes = checked(totalRuntimeBytes + runtimeBytes);
                    if (readable)
                    {
                        readableTextures = checked(readableTextures + 1);
                        readableRuntimeBytes = checked(
                            readableRuntimeBytes + runtimeBytes);
                    }

                    int bucket = FindOrAddBucket(
                        buckets,
                        ref bucketCount,
                        format,
                        readable);
                    buckets[bucket].Count = checked(buckets[bucket].Count + 1);
                    buckets[bucket].Pixels = checked(
                        buckets[bucket].Pixels + pixels);
                    buckets[bucket].UnityRuntimeBytes = checked(
                        buckets[bucket].UnityRuntimeBytes + runtimeBytes);
                    ConsiderTop(
                        top,
                        ref topCount,
                        texture,
                        instanceId,
                        format,
                        readable,
                        width,
                        height,
                        mipmaps,
                        runtimeBytes);
                }
                catch (Exception)
                {
                    failedObjects = checked(failedObjects + 1);
                }
            }

            SortBuckets(buckets, bucketCount);
            SortTop(top, topCount);
            for (int index = 0; index < bucketCount; index++)
            {
                Bucket bucket = buckets[index];
                Emit(
                    information,
                    "SEDE_RUNTIME_V1|event=texture_inventory_bucket"
                    + "|phase=" + Phase
                    + "|format=" + bucket.Format.ToString()
                    + "|format_id=" + ((int)bucket.Format).ToString(
                        CultureInfo.InvariantCulture)
                    + "|readable=" + Boolean(bucket.Readable)
                    + "|count=" + bucket.Count.ToString(
                        CultureInfo.InvariantCulture)
                    + "|pixels=" + bucket.Pixels.ToString(
                        CultureInfo.InvariantCulture)
                    + "|unity_runtime_bytes="
                    + bucket.UnityRuntimeBytes.ToString(
                        CultureInfo.InvariantCulture));
            }

            for (int index = 0; index < topCount; index++)
            {
                TopEntry entry = top[index];
                string name;
                try
                {
                    name = Token(entry.Texture.name);
                }
                catch (Exception)
                {
                    failedObjects = checked(failedObjects + 1);
                    name = "unavailable";
                }
                Emit(
                    information,
                    "SEDE_RUNTIME_V1|event=texture_inventory_top"
                    + "|phase=" + Phase
                    + "|rank=" + (index + 1).ToString(
                        CultureInfo.InvariantCulture)
                    + "|name=" + name
                    + "|instance_id=" + entry.InstanceId.ToString(
                        CultureInfo.InvariantCulture)
                    + "|format=" + entry.Format.ToString()
                    + "|format_id=" + ((int)entry.Format).ToString(
                        CultureInfo.InvariantCulture)
                    + "|readable=" + Boolean(entry.Readable)
                    + "|width=" + entry.Width.ToString(
                        CultureInfo.InvariantCulture)
                    + "|height=" + entry.Height.ToString(
                        CultureInfo.InvariantCulture)
                    + "|mips=" + entry.Mipmaps.ToString(
                        CultureInfo.InvariantCulture)
                    + "|unity_runtime_bytes=" + entry.UnityRuntimeBytes.ToString(
                        CultureInfo.InvariantCulture));
                top[index].Texture = null;
            }

            ulong currentTextureBytes = Texture.currentTextureMemory;
            ulong totalTextureBytes = Texture.totalTextureMemory;
            ulong nonStreamingTextureBytes = Texture.nonStreamingTextureMemory;
            Emit(
                information,
                "SEDE_RUNTIME_V1|event=texture_inventory|status=complete"
                + "|phase=" + Phase
                + "|textures=" + observed.ToString(CultureInfo.InvariantCulture)
                + "|unity_runtime_bytes=" + totalRuntimeBytes.ToString(
                    CultureInfo.InvariantCulture)
                + "|readable_textures=" + readableTextures.ToString(
                    CultureInfo.InvariantCulture)
                + "|readable_unity_runtime_bytes="
                + readableRuntimeBytes.ToString(CultureInfo.InvariantCulture)
                + "|unknown_size_count=" + unknownSizeCount.ToString(
                    CultureInfo.InvariantCulture)
                + "|failed_objects=" + failedObjects.ToString(
                    CultureInfo.InvariantCulture)
                + "|current_texture_bytes=" + currentTextureBytes.ToString(
                    CultureInfo.InvariantCulture)
                + "|total_texture_bytes=" + totalTextureBytes.ToString(
                    CultureInfo.InvariantCulture)
                + "|nonstreaming_texture_bytes="
                + nonStreamingTextureBytes.ToString(
                    CultureInfo.InvariantCulture));
        }

        private static int FindOrAddBucket(
            Bucket[] buckets,
            ref int count,
            TextureFormat format,
            bool readable)
        {
            for (int index = 0; index < count; index++)
            {
                if (buckets[index].Format == format
                    && buckets[index].Readable == readable)
                {
                    return index;
                }
            }
            if (count >= buckets.Length)
            {
                throw new InvalidOperationException(
                    "Texture inventory exceeded the fixed bucket capacity");
            }
            int result = count;
            buckets[result].Format = format;
            buckets[result].Readable = readable;
            count = checked(count + 1);
            return result;
        }

        private static void ConsiderTop(
            TopEntry[] top,
            ref int count,
            Texture2D texture,
            int instanceId,
            TextureFormat format,
            bool readable,
            int width,
            int height,
            int mipmaps,
            long runtimeBytes)
        {
            var candidate = new TopEntry
            {
                Texture = texture,
                InstanceId = instanceId,
                Format = format,
                Readable = readable,
                Width = width,
                Height = height,
                Mipmaps = mipmaps,
                UnityRuntimeBytes = runtimeBytes,
            };
            if (count < top.Length)
            {
                top[count] = candidate;
                count = checked(count + 1);
                return;
            }

            int worst = 0;
            for (int index = 1; index < count; index++)
            {
                if (Better(top[worst], top[index]))
                {
                    worst = index;
                }
            }
            if (Better(candidate, top[worst]))
            {
                top[worst] = candidate;
            }
        }

        private static void SortTop(TopEntry[] top, int count)
        {
            for (int left = 0; left < count - 1; left++)
            {
                int best = left;
                for (int right = left + 1; right < count; right++)
                {
                    if (Better(top[right], top[best]))
                    {
                        best = right;
                    }
                }
                if (best != left)
                {
                    TopEntry temporary = top[left];
                    top[left] = top[best];
                    top[best] = temporary;
                }
            }
        }

        private static bool Better(TopEntry candidate, TopEntry existing)
        {
            if (candidate.UnityRuntimeBytes != existing.UnityRuntimeBytes)
            {
                return candidate.UnityRuntimeBytes > existing.UnityRuntimeBytes;
            }
            return candidate.InstanceId < existing.InstanceId;
        }

        private static void SortBuckets(Bucket[] buckets, int count)
        {
            for (int left = 0; left < count - 1; left++)
            {
                int best = left;
                for (int right = left + 1; right < count; right++)
                {
                    if (BucketBefore(buckets[right], buckets[best]))
                    {
                        best = right;
                    }
                }
                if (best != left)
                {
                    Bucket temporary = buckets[left];
                    buckets[left] = buckets[best];
                    buckets[best] = temporary;
                }
            }
        }

        private static bool BucketBefore(Bucket candidate, Bucket existing)
        {
            int candidateFormat = (int)candidate.Format;
            int existingFormat = (int)existing.Format;
            if (candidateFormat != existingFormat)
            {
                return candidateFormat < existingFormat;
            }
            return !candidate.Readable && existing.Readable;
        }

        private static string Boolean(bool value)
        {
            return value ? "true" : "false";
        }

        private static string Token(string value)
        {
            string sanitized = AssetStreamText.Sanitize(value, 128);
            return sanitized.Replace('|', '_').Replace('=', '_');
        }

        private static void Emit(Action<string> output, string value)
        {
            if (output == null)
            {
                return;
            }
            try
            {
                output(value);
            }
            catch
            {
                // Diagnostics cannot own or disable a runtime lane.
            }
        }

        private struct Bucket
        {
            internal TextureFormat Format;
            internal bool Readable;
            internal int Count;
            internal long Pixels;
            internal long UnityRuntimeBytes;
        }

        private struct TopEntry
        {
            internal Texture2D Texture;
            internal int InstanceId;
            internal TextureFormat Format;
            internal bool Readable;
            internal int Width;
            internal int Height;
            internal int Mipmaps;
            internal long UnityRuntimeBytes;
        }
    }
}
