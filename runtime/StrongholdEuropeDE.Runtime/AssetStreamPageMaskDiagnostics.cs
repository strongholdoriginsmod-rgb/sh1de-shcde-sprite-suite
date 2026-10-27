using System;
using System.Collections.Generic;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Immutable, Unity-free observation taken immediately before or after the
    /// SetBodySprite postfix applies the exact Sprite-to-page-mask route.
    /// </summary>
    internal sealed class AssetStreamPageMaskProbeSnapshot
    {
        internal AssetStreamPageMaskProbeSnapshot(
            long epoch,
            int rendererId,
            object renderer,
            bool rendererUnityNull,
            string fileGroup,
            bool maskRequired,
            string routeGroup,
            string spriteIdentity,
            string materialIdentity,
            string shaderIdentity,
            string expectedMaskIdentity,
            bool expectedMaskOwned,
            bool blockHasMask,
            string blockMaskIdentity,
            bool materialHasMask,
            string materialMaskIdentity,
            int file,
            int image,
            int colour,
            bool altFrame,
            int chopFeet,
            int transparency)
        {
            if (epoch < 1) throw new ArgumentOutOfRangeException("epoch");
            Epoch = epoch;
            RendererId = rendererId;
            Renderer = renderer ?? throw new ArgumentNullException("renderer");
            RendererUnityNull = rendererUnityNull;
            FileGroup = fileGroup ?? string.Empty;
            MaskRequired = maskRequired;
            RouteGroup = routeGroup ?? string.Empty;
            SpriteIdentity = spriteIdentity ?? "null";
            MaterialIdentity = materialIdentity ?? "null";
            ShaderIdentity = shaderIdentity ?? "null";
            ExpectedMaskIdentity = expectedMaskIdentity ?? "null";
            ExpectedMaskOwned = expectedMaskOwned;
            BlockHasMask = blockHasMask;
            BlockMaskIdentity = blockMaskIdentity ?? "null";
            MaterialHasMask = materialHasMask;
            MaterialMaskIdentity = materialMaskIdentity ?? "null";
            File = file;
            Image = image;
            Colour = colour;
            AltFrame = altFrame;
            ChopFeet = chopFeet;
            Transparency = transparency;
        }

        internal long Epoch { get; private set; }
        internal int RendererId { get; private set; }
        internal object Renderer { get; private set; }
        internal bool RendererUnityNull { get; private set; }
        internal string FileGroup { get; private set; }
        internal bool MaskRequired { get; private set; }
        internal string RouteGroup { get; private set; }
        internal string SpriteIdentity { get; private set; }
        internal string MaterialIdentity { get; private set; }
        internal string ShaderIdentity { get; private set; }
        internal string ExpectedMaskIdentity { get; private set; }
        internal bool ExpectedMaskOwned { get; private set; }
        internal bool BlockHasMask { get; private set; }
        internal string BlockMaskIdentity { get; private set; }
        internal bool MaterialHasMask { get; private set; }
        internal string MaterialMaskIdentity { get; private set; }
        internal int File { get; private set; }
        internal int Image { get; private set; }
        internal int Colour { get; private set; }
        internal bool AltFrame { get; private set; }
        internal int ChopFeet { get; private set; }
        internal int Transparency { get; private set; }

        internal bool WatchesMaskRoute
        {
            get
            {
                return MaskRequired
                    || ExpectedMaskOwned
                    || RouteGroup.Length != 0;
            }
        }
    }

    internal sealed class AssetStreamPageMaskProbeEvent
    {
        internal AssetStreamPageMaskProbeEvent(
            string reason,
            bool anomaly,
            bool correction,
            bool rendererIdReused,
            string exceptionType,
            AssetStreamPageMaskProbeSnapshot before,
            AssetStreamPageMaskProbeSnapshot after)
        {
            Reason = reason ?? throw new ArgumentNullException("reason");
            Anomaly = anomaly;
            Correction = correction;
            RendererIdReused = rendererIdReused;
            ExceptionType = exceptionType ?? string.Empty;
            Before = before ?? throw new ArgumentNullException("before");
            After = after ?? throw new ArgumentNullException("after");
        }

        internal string Reason { get; private set; }
        internal bool Anomaly { get; private set; }
        internal bool Correction { get; private set; }
        internal bool RendererIdReused { get; private set; }
        internal string ExceptionType { get; private set; }
        internal AssetStreamPageMaskProbeSnapshot Before { get; private set; }
        internal AssetStreamPageMaskProbeSnapshot After { get; private set; }
    }

    /// <summary>
    /// Group-agnostic, bounded transition detector for required page-mask
    /// routes. Every correction and every remaining postfix mismatch is
    /// counted even after detailed log output reaches its per-epoch cap.
    /// Rendering decisions stay in AssetStreamPageMaskOwnership.
    /// </summary>
    internal sealed class AssetStreamPageMaskProbeDiagnostics
    {
        internal const int MaximumLogsPerEpoch = 128;

        private sealed class State
        {
            internal State(
                object renderer,
                AssetStreamPageMaskProbeSnapshot last)
            {
                Renderer = new WeakReference(renderer);
                Last = new Observation(last);
            }

            internal WeakReference Renderer { get; private set; }
            internal Observation Last { get; private set; }
        }

        // Never retain the transient snapshot here: it deliberately carries
        // the renderer strongly so one postfix can prove before/after identity.
        // Persistent state keeps only scalar/string observations; the weak
        // reference above remains the sole renderer reference.
        private sealed class Observation
        {
            internal Observation(AssetStreamPageMaskProbeSnapshot snapshot)
            {
                WatchesMaskRoute = snapshot.WatchesMaskRoute;
                FileGroup = snapshot.FileGroup;
                MaskRequired = snapshot.MaskRequired;
                RouteGroup = snapshot.RouteGroup;
                ExpectedMaskIdentity = snapshot.ExpectedMaskIdentity;
                MaterialIdentity = snapshot.MaterialIdentity;
                ShaderIdentity = snapshot.ShaderIdentity;
                BlockHasMask = snapshot.BlockHasMask;
                BlockMaskIdentity = snapshot.BlockMaskIdentity;
                MaterialHasMask = snapshot.MaterialHasMask;
                MaterialMaskIdentity = snapshot.MaterialMaskIdentity;
            }

            internal bool WatchesMaskRoute { get; private set; }
            internal string FileGroup { get; private set; }
            internal bool MaskRequired { get; private set; }
            internal string RouteGroup { get; private set; }
            internal string ExpectedMaskIdentity { get; private set; }
            internal string MaterialIdentity { get; private set; }
            internal string ShaderIdentity { get; private set; }
            internal bool BlockHasMask { get; private set; }
            internal string BlockMaskIdentity { get; private set; }
            internal bool MaterialHasMask { get; private set; }
            internal string MaterialMaskIdentity { get; private set; }
        }

        private readonly Dictionary<int, State> _states =
            new Dictionary<int, State>();
        private readonly HashSet<string> _observedGroups =
            new HashSet<string>(StringComparer.Ordinal);
        private long _epoch;
        private int _operations;

        internal long Epoch { get { return _epoch; } }
        internal int Events { get; private set; }
        internal int Corrections { get; private set; }
        internal int PostfixMismatches { get; private set; }
        internal int Anomalies { get; private set; }
        internal int Dropped { get; private set; }

        internal void Reset(long epoch)
        {
            if (epoch < 1) throw new ArgumentOutOfRangeException("epoch");
            _epoch = epoch;
            Events = 0;
            Corrections = 0;
            PostfixMismatches = 0;
            Anomalies = 0;
            Dropped = 0;
            _operations = 0;
            _states.Clear();
            _observedGroups.Clear();
        }

        internal bool ShouldObserve(
            int rendererId,
            object renderer,
            bool fileMaskRequired,
            string routeGroup)
        {
            if (renderer == null) return false;
            if (fileMaskRequired || !string.IsNullOrEmpty(routeGroup))
            {
                return true;
            }
            State previous;
            return _states.TryGetValue(rendererId, out previous)
                && ReferenceEquals(previous.Renderer.Target, renderer)
                && previous.Last.WatchesMaskRoute;
        }

        internal bool TryObserve(
            AssetStreamPageMaskProbeSnapshot before,
            AssetStreamPageMaskProbeSnapshot after,
            string routeExceptionType,
            out AssetStreamPageMaskProbeEvent observed)
        {
            observed = null;
            if (before == null) throw new ArgumentNullException("before");
            if (after == null) throw new ArgumentNullException("after");
            if (before.Epoch != after.Epoch
                || before.RendererId != after.RendererId
                || !ReferenceEquals(before.Renderer, after.Renderer))
            {
                throw new InvalidOperationException(
                    "Page-mask probe before/after identity changed inside one postfix");
            }
            if (_epoch != after.Epoch)
            {
                Reset(after.Epoch);
            }

            State previous;
            bool rendererIdReused = false;
            if (_states.TryGetValue(after.RendererId, out previous)
                && !ReferenceEquals(previous.Renderer.Target, after.Renderer))
            {
                _states.Remove(after.RendererId);
                previous = null;
                rendererIdReused = true;
            }

            bool watchedBefore = before.WatchesMaskRoute;
            bool watchedAfter = after.WatchesMaskRoute;
            bool watchedPreviously = previous != null
                && previous.Last.WatchesMaskRoute;
            if (!watchedBefore && !watchedAfter && !watchedPreviously)
            {
                PruneIfDue();
                return false;
            }

            bool beforeMatches = PostfixMatches(before);
            bool afterMatches = PostfixMatches(after);
            bool correction = before.MaskRequired
                && before.ExpectedMaskOwned
                && !beforeMatches
                && afterMatches;
            if (correction)
            {
                Corrections++;
            }

            bool postfixMismatch = after.MaskRequired && !afterMatches;
            if (postfixMismatch)
            {
                PostfixMismatches++;
            }

            string exceptionType = routeExceptionType ?? string.Empty;
            bool routeException = exceptionType.Length != 0;
            bool groupChanged = previous != null
                && (previous.Last.MaskRequired != before.MaskRequired
                    || !Same(previous.Last.FileGroup, before.FileGroup)
                    || !Same(previous.Last.RouteGroup, before.RouteGroup));
            bool routeChanged = previous != null
                && !Same(
                    previous.Last.ExpectedMaskIdentity,
                    before.ExpectedMaskIdentity);
            bool materialChanged = previous != null
                && (!Same(
                        previous.Last.MaterialIdentity,
                        before.MaterialIdentity)
                    || !Same(
                        previous.Last.ShaderIdentity,
                        before.ShaderIdentity));
            bool externalDrift = previous != null
                && !groupChanged
                && !routeChanged
                && !materialChanged
                && (previous.Last.BlockHasMask != before.BlockHasMask
                    || !Same(
                        previous.Last.BlockMaskIdentity,
                        before.BlockMaskIdentity)
                    || previous.Last.MaterialHasMask != before.MaterialHasMask
                    || !Same(
                        previous.Last.MaterialMaskIdentity,
                        before.MaterialMaskIdentity));

            string observedGroup = after.MaskRequired
                ? after.FileGroup
                : after.RouteGroup;
            bool firstGroup = watchedAfter
                && observedGroup.Length != 0
                && _observedGroups.Add(observedGroup);

            string reason = null;
            bool anomaly = false;
            if (routeException)
            {
                reason = "route_exception";
                anomaly = true;
            }
            else if (postfixMismatch)
            {
                reason = "postfix_mismatch";
                anomaly = true;
            }
            else if (externalDrift)
            {
                reason = "external_drift_between_calls";
                anomaly = true;
            }
            else if (groupChanged)
            {
                reason = "group_change";
            }
            else if (rendererIdReused)
            {
                reason = "renderer_id_reused";
            }
            else if (firstGroup)
            {
                reason = "group_first_observed";
            }
            else if (correction)
            {
                reason = "mask_corrected";
            }

            if (watchedAfter)
            {
                _states[after.RendererId] = new State(after.Renderer, after);
            }
            else
            {
                _states.Remove(after.RendererId);
            }
            PruneIfDue();

            if (reason == null)
            {
                return false;
            }
            Events++;
            if (anomaly) Anomalies++;
            if (Events > MaximumLogsPerEpoch)
            {
                Dropped++;
                return false;
            }
            observed = new AssetStreamPageMaskProbeEvent(
                reason,
                anomaly,
                correction,
                rendererIdReused,
                exceptionType,
                before,
                after);
            return true;
        }

        private static bool PostfixMatches(
            AssetStreamPageMaskProbeSnapshot snapshot)
        {
            return !snapshot.MaskRequired
                || (snapshot.ExpectedMaskOwned
                    && snapshot.BlockHasMask
                    && Same(
                        snapshot.ExpectedMaskIdentity,
                        snapshot.BlockMaskIdentity));
        }

        private void PruneIfDue()
        {
            _operations++;
            if ((_operations & 127) != 0) return;
            var dead = new List<int>();
            foreach (KeyValuePair<int, State> pair in _states)
            {
                if (!pair.Value.Renderer.IsAlive
                    || pair.Value.Renderer.Target == null)
                {
                    dead.Add(pair.Key);
                }
            }
            for (int index = 0; index < dead.Count; index++)
            {
                _states.Remove(dead[index]);
            }
        }

        private static bool Same(string left, string right)
        {
            return string.Equals(left, right, StringComparison.Ordinal);
        }
    }
}
