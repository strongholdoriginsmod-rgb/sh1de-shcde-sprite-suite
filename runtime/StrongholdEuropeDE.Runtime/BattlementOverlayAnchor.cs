using System;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Exact dual-anchor contract for the nine European foreground masks in
    /// anim_castle. Their source canvases are shorter than Crusader's slots,
    /// so one static pivot cannot align both the visible battlement top and the
    /// flattened landscape ground edge.
    /// </summary>
    internal static class BattlementOverlayAnchor
    {
        internal const int CastleAnimationsGm = 54;
        private const float HeightTolerance = 0.01f;

        private static readonly FrameSpec[] Frames =
        {
            new FrameSpec(1, 98, 138),
            new FrameSpec(2, 165, 183),
            new FrameSpec(3, 132, 161),
            new FrameSpec(4, 146, 226),
            new FrameSpec(11, 217, 236),
            new FrameSpec(12, 210, 235),
            new FrameSpec(13, 233, 255),
            new FrameSpec(14, 220, 260),
            new FrameSpec(27, 287, 305),
        };

        internal static bool TryResolvePivotY(
            int gm,
            int imageId,
            bool altFrame,
            float sourceHeight,
            bool flattenedLandscape,
            out float pivotY)
        {
            pivotY = 0f;
            if (gm != CastleAnimationsGm || altFrame || sourceHeight <= 0f)
            {
                return false;
            }

            for (int index = 0; index < Frames.Length; index++)
            {
                FrameSpec frame = Frames[index];
                if (frame.ImageId != imageId)
                {
                    continue;
                }
                if (Math.Abs(sourceHeight - frame.SourceHeight)
                    > HeightTolerance)
                {
                    // A different asset generation is not silently forced
                    // through measurements made for the reviewed SH1 frames.
                    return false;
                }
                pivotY = flattenedLandscape
                    ? frame.FlattenedAnchorY / frame.SourceHeight
                    : 1f;
                return true;
            }
            return false;
        }

        private readonly struct FrameSpec
        {
            internal FrameSpec(
                int imageId,
                float sourceHeight,
                float flattenedAnchorY)
            {
                ImageId = imageId;
                SourceHeight = sourceHeight;
                FlattenedAnchorY = flattenedAnchorY;
            }

            internal int ImageId { get; }
            internal float SourceHeight { get; }
            internal float FlattenedAnchorY { get; }
        }
    }
}
