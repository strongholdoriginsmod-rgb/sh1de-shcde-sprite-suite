using System;
using System.Collections.Generic;

namespace SpriteSuite.BuildingDamage
{
    // No game or Unity dependencies: identical rules are testable outside SHCDE.
    public sealed class StageDefinition
    {
        public string Id;
        public string Kind;
        public int Threshold;
    }

    public static class BuildingDamageStageLogic
    {
        public static string Choose(IList<StageDefinition> stages, int currentHp,
            int maximumHp, bool fireHistory)
        {
            if (stages == null || maximumHp <= 0 || currentHp < 0)
                return null;
            int hp = Math.Min(currentHp, maximumHp);
            int percent = (int)((100L * hp) / maximumHp);
            bool fireAvailable = false;
            int highestFireThreshold = -1;
            for (int i = 0; i < stages.Count; ++i)
            {
                StageDefinition s = stages[i];
                if (s == null || s.Kind != "fire" || s.Threshold < 0 ||
                    s.Threshold > 99) continue;
                fireAvailable = true;
                highestFireThreshold = Math.Max(highestFireThreshold, s.Threshold);
            }
            string kind = fireHistory && fireAvailable ? "fire" : "mechanical";
            // A burning but still fully healthy building may already show the
            // mildest fire artwork, rather than displaying the intact sprite.
            if (fireHistory && percent >= 100)
            {
                int max = -1;
                for (int i = 0; i < stages.Count; ++i)
                    if (stages[i] != null && stages[i].Kind == kind)
                        max = Math.Max(max, stages[i].Threshold);
                if (max >= 0) percent = max;
            }
            string selected = null;
            int selectedThreshold = 101;
            for (int i = 0; i < stages.Count; ++i)
            {
                StageDefinition s = stages[i];
                if (s == null || s.Kind != kind || s.Threshold < 0 ||
                    s.Threshold > 99 || percent > s.Threshold) continue;
                // Choose the *smallest* threshold that still covers this HP.
                if (s.Threshold < selectedThreshold)
                {
                    selected = s.Id;
                    selectedThreshold = s.Threshold;
                }
            }
            return selected; // null = untouched / restored original sprite
        }
    }

    public sealed class BuildingFireHistory
    {
        private readonly Dictionary<long, bool> _burned = new Dictionary<long, bool>();

        public bool Update(long globalIdentity, int currentHp, int maximumHp,
            int activeFireTicks)
        {
            if (maximumHp <= 0 || globalIdentity <= 0) return false;
            bool onFire = activeFireTicks > 0;
            bool history;
            _burned.TryGetValue(globalIdentity, out history);
            if (!onFire && currentHp >= maximumHp)
                history = false;
            else if (onFire)
                history = true;
            if (history) _burned[globalIdentity] = true;
            else _burned.Remove(globalIdentity);
            return history;
        }

        public void Remove(long globalIdentity) { _burned.Remove(globalIdentity); }
        public void Clear() { _burned.Clear(); }
    }
}
