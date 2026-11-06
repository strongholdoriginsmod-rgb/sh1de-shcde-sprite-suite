using System;
using System.Collections.Generic;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Exact, allocation-bounded building-damage stage selection.
    /// No Unity, SHCDESE, filesystem, event hooks or renderer writes.
    /// Caller must acquire a coherent snapshot on a safe game thread.
    /// </summary>
    internal static class BuildingDamageStageSelector
    {
        internal const int MaximumBuildings = 8192;
        internal const int MaximumProfiles = 128;
        internal const int MaximumStagesPerProfile = 32;

        internal enum Cause { Mechanical, Fire }

        internal sealed class Stage
        {
            internal readonly string Id;
            internal readonly string SceneId;
            internal readonly Cause DamageCause;
            internal readonly int HpAtOrBelow;

            internal Stage(string id, string sceneId, Cause cause, int hpAtOrBelow)
            {
                if (string.IsNullOrWhiteSpace(id) || id.Length > 80 ||
                    string.IsNullOrWhiteSpace(sceneId) || sceneId.Length > 80 ||
                    hpAtOrBelow < 0 || hpAtOrBelow > 99)
                    throw new ArgumentException("Invalid building damage stage.");
                Id = id;
                SceneId = sceneId;
                DamageCause = cause;
                HpAtOrBelow = hpAtOrBelow;
            }
        }

        internal sealed class Profile
        {
            internal readonly int BuildingType;
            internal readonly string SourceGroupId;
            internal readonly Stage[] Stages;
            internal readonly bool HasFireStages;

            internal Profile(int buildingType, string sourceGroupId, IEnumerable<Stage> stages)
            {
                if (buildingType < 0 || buildingType > 4095 ||
                    string.IsNullOrWhiteSpace(sourceGroupId))
                    throw new ArgumentException("Unverified or missing game building type.");
                BuildingType = buildingType;
                SourceGroupId = sourceGroupId;
                List<Stage> copy = new List<Stage>();
                HashSet<string> ids = new HashSet<string>(StringComparer.Ordinal);
                HashSet<string> thresholds = new HashSet<string>(StringComparer.Ordinal);
                bool fire = false;
                foreach (Stage stage in stages)
                {
                    if (stage == null || !ids.Add(stage.Id) ||
                        !thresholds.Add(((int)stage.DamageCause).ToString() + ":" +
                            stage.HpAtOrBelow.ToString()))
                        throw new ArgumentException("Duplicate or null damage stage.");
                    copy.Add(stage);
                    if (stage.DamageCause == Cause.Fire) fire = true;
                    if (copy.Count > MaximumStagesPerProfile)
                        throw new ArgumentException("Too many building damage stages.");
                }
                copy.Sort(delegate(Stage a, Stage b)
                {
                    int cause = ((int)a.DamageCause).CompareTo((int)b.DamageCause);
                    return cause != 0 ? cause : b.HpAtOrBelow.CompareTo(a.HpAtOrBelow);
                });
                HasFireStages = fire;
                Stages = copy.ToArray();
            }
        }

        internal sealed class Result
        {
            internal readonly int BuildingId;
            internal readonly int GlobalId;
            internal readonly int BuildingType;
            internal readonly int CurrentHealth;
            internal readonly int MaximumHealth;
            internal readonly bool FireObserved;
            internal readonly Cause EffectiveCause;
            internal readonly Stage Selected;
            internal readonly string Reason;

            internal Result(int id, int global, int type, int current, int maximum,
                bool fire, Cause cause, Stage selected, string reason)
            {
                BuildingId = id;
                GlobalId = global;
                BuildingType = type;
                CurrentHealth = current;
                MaximumHealth = maximum;
                FireObserved = fire;
                EffectiveCause = cause;
                Selected = selected;
                Reason = reason;
            }
            internal bool UseVanilla { get { return Selected == null; } }
        }

        private sealed class Memory
        {
            internal readonly int GlobalId;
            internal readonly int BuildingType;
            internal bool EverOnFire;
            internal Memory(int global, int type)
            {
                GlobalId = global;
                BuildingType = type;
            }
        }

        private readonly static Result Empty = new Result(
            0, 0, 0, 0, 0, false, Cause.Mechanical, null, "unconfigured");

        internal sealed class Observer
        {
            private readonly Dictionary<int, Profile> _profiles =
                new Dictionary<int, Profile>();
            private readonly Dictionary<int, Memory> _memory =
                new Dictionary<int, Memory>();

            internal Observer(IEnumerable<Profile> profiles)
            {
                if (profiles == null) throw new ArgumentNullException("profiles");
                foreach (Profile profile in profiles)
                {
                    if (profile == null || _profiles.ContainsKey(profile.BuildingType))
                        throw new ArgumentException("Duplicate or null building profile.");
                    _profiles.Add(profile.BuildingType, profile);
                    if (_profiles.Count > MaximumProfiles)
                        throw new ArgumentException("Too many building profiles.");
                }
            }

            internal int TrackedCount { get { return _memory.Count; } }
            internal int ProfileCount { get { return _profiles.Count; } }

            internal Result Observe(int buildingId, int globalId, int buildingType,
                int currentHp, int maxHp, int onFireTicks)
            {
                if (buildingId <= 0 || globalId <= 0 ||
                    onFireTicks < 0 || currentHp < 0 || maxHp <= 0 ||
                    currentHp > maxHp)
                {
                    _memory.Remove(buildingId);
                    return new Result(buildingId, globalId, buildingType, currentHp,
                        maxHp, false, Cause.Mechanical, null, "invalid_snapshot");
                }
                Profile profile;
                if (!_profiles.TryGetValue(buildingType, out profile))
                {
                    _memory.Remove(buildingId);
                    return new Result(buildingId, globalId, buildingType, currentHp,
                        maxHp, false, Cause.Mechanical, null, "unconfigured_type");
                }
                Memory state;
                if (!_memory.TryGetValue(buildingId, out state) ||
                    state.GlobalId != globalId || state.BuildingType != buildingType)
                {
                    _memory.Remove(buildingId);
                    if (_memory.Count >= MaximumBuildings)
                        return new Result(buildingId, globalId, buildingType, currentHp,
                            maxHp, false, Cause.Mechanical, null, "capacity_exhausted");
                    state = new Memory(globalId, buildingType);
                    _memory.Add(buildingId, state);
                }

                // GetOnFireTicks proves active burning, not the historical
                // cause of every hit. Retain observed fire appearance until
                // fully healed, so extinguishing cannot magically unchar art.
                if (currentHp == maxHp) state.EverOnFire = false;
                else if (onFireTicks > 0) state.EverOnFire = true;

                Cause cause = state.EverOnFire ? Cause.Fire : Cause.Mechanical;
                Stage stage = Choose(profile, cause, currentHp, maxHp);
                return new Result(buildingId, globalId, buildingType,
                    currentHp, maxHp, state.EverOnFire, cause, stage,
                    stage == null ? "intact_or_no_matching_threshold" : "selected");
            }

            internal void Forget(int buildingId) { _memory.Remove(buildingId); }

            internal void Clear() { _memory.Clear(); }

            internal void RetainAlive(IEnumerable<int> ids)
            {
                if (ids == null) throw new ArgumentNullException("ids");
                HashSet<int> alive = new HashSet<int>(ids);
                List<int> retired = new List<int>();
                foreach (int id in _memory.Keys)
                    if (!alive.Contains(id)) retired.Add(id);
                foreach (int id in retired) _memory.Remove(id);
            }
        }

        internal static Stage Choose(Profile profile, Cause cause,
            int currentHp, int maxHp)
        {
            if (profile == null || currentHp < 0 || maxHp <= 0 ||
                currentHp > maxHp || currentHp == maxHp) return null;

            Cause candidateCause = cause == Cause.Fire && !profile.HasFireStages
                ? Cause.Mechanical : cause;
            Stage result = null;
            foreach (Stage stage in profile.Stages)
            {
                if (stage.DamageCause != candidateCause) continue;
                // Multiply in 64-bit integers to avoid rounding boundaries
                // and overflow. HP == threshold is inclusive.
                if ((long)currentHp * 100 <= (long)stage.HpAtOrBelow * maxHp &&
                    (result == null || stage.HpAtOrBelow < result.HpAtOrBelow))
                    result = stage;
            }
            return result;
        }
    }
}
