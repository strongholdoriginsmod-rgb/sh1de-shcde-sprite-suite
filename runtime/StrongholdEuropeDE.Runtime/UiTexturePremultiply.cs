using System;

namespace StrongholdEuropeDE.Runtime
{
    internal static class UiTexturePremultiply
    {
        internal static byte Component(byte colour, byte alpha)
        {
            return (byte)(((int)colour * (int)alpha + 127) / 255);
        }

        /// <summary>
        /// Dependency-free reference for the builder's pinned offline alpha
        /// contract. The direct BC7 runtime path never calls this helper.
        /// </summary>
        internal static void Rgba32InPlace(byte[] rgba)
        {
            if (rgba == null)
            {
                throw new ArgumentNullException("rgba");
            }
            if ((rgba.Length & 3) != 0)
            {
                throw new ArgumentException(
                    "RGBA32 payload length must be divisible by four",
                    "rgba");
            }
            for (int offset = 0; offset < rgba.Length; offset += 4)
            {
                byte alpha = rgba[offset + 3];
                rgba[offset] = Component(rgba[offset], alpha);
                rgba[offset + 1] = Component(rgba[offset + 1], alpha);
                rgba[offset + 2] = Component(rgba[offset + 2], alpha);
            }
        }
    }
}
