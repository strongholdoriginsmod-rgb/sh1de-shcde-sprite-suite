using System;
using System.Collections.Generic;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Read-only building-damage observation boundary.
    /// Must be polled from a proven game/main-thread context after map load.
    /// No installation, sprite write, event subscription or Unity side effects.
    /// </summary>
    internal static class BuildingDamageReadOnlyProbe
    {
        internal struct Snapshot
        {
            internal readonly int BuildingId;
            internal readonly int GlobalId;
            internal readonly int BuildingType;
            internal readonly int CurrentHealth;
            internal readonly int MaximumHealth;
            internal readonly int FireTicks;
            internal Snapshot(int buildingId, int globalId, int buildingType,
                int currentHealth, int maximumHealth, int fireTicks)
            {
                BuildingId = buildingId;
                GlobalId = globalId;
                BuildingType = buildingType;
                CurrentHealth = currentHealth;
                MaximumHealth = maximumHealth;
                FireTicks = fireTicks;
            }
        }

        internal interface ISource
        {
            int[] GetAliveBuildingIds();
            bool TryRead(int buildingId, out Snapshot snapshot);
        }

        internal sealed class PollReport
        {
            internal readonly bool Ready;
            internal readonly string Reason;
            internal readonly BuildingDamageStageSelector.Result[] Buildings;
            internal PollReport(bool ready, string reason,
                BuildingDamageStageSelector.Result[] buildings)
            {
                Ready = ready;
                Reason = reason;
                Buildings = buildings;
            }
        }

        internal sealed class Monitor
        {
            private readonly ISource _source;
            private readonly BuildingDamageStageSelector.Observer _observer;
            private bool _faulted;
            private int _pollCount;

            internal Monitor(ISource source, BuildingDamageStageSelector.Observer observer)
            {
                if (source == null || observer == null)
                    throw new ArgumentNullException(
                        source == null ? "source" : "observer");
                _source = source;
                _observer = observer;
            }

            internal bool Faulted { get { return _faulted; } }
            internal int PollCount { get { return _pollCount; } }

            internal PollReport Poll()
            {
                if (_faulted)
                    return new PollReport(false, "observer_faulted",
                        new BuildingDamageStageSelector.Result[0]);
                try
                {
                    int[] ids = _source.GetAliveBuildingIds();
                    if (ids == null || ids.Length > BuildingDamageStageSelector.MaximumBuildings)
                        return Fail("invalid_building_list");
                    var unique = new HashSet<int>();
                    foreach (int id in ids)
                        if (id <= 0 || !unique.Add(id))
                            return Fail("invalid_or_duplicate_building_id");

                    Array.Sort(ids);
                    // Read the ENTIRE current pass first. An inconsistent
                    // source never partially advances the observer state.
                    var snapshots = new Snapshot[ids.Length];
                    for (int i = 0; i < ids.Length; i++)
                    {
                        Snapshot sample;
                        if (!_source.TryRead(ids[i], out sample) ||
                            sample.BuildingId != ids[i] || sample.GlobalId <= 0 ||
                            sample.BuildingType < 0 || sample.BuildingType > 4095 ||
                            sample.CurrentHealth < 0 || sample.MaximumHealth <= 0 ||
                            sample.CurrentHealth > sample.MaximumHealth || sample.FireTicks < 0)
                            return Fail("inconsistent_building_snapshot");
                        snapshots[i] = sample;
                    }

                    _observer.RetainAlive(ids);
                    var items = new BuildingDamageStageSelector.Result[ids.Length];
                    for (int i = 0; i < ids.Length; i++)
                    {
                        Snapshot s = snapshots[i];
                        items[i] = _observer.Observe(s.BuildingId, s.GlobalId,
                            s.BuildingType, s.CurrentHealth, s.MaximumHealth,
                            s.FireTicks);
                    }
                    _pollCount++;
                    return new PollReport(true, "observed", items);
                }
                catch (Exception)
                {
                    return Fail("building_api_exception");
                }
            }

            internal void Reset()
            {
                _faulted = false;
                _pollCount = 0;
                _observer.Clear();
            }

            private PollReport Fail(string reason)
            {
                // A failed source must not continue to advertise stale stage
                // selections. Only an explicit map/session reset can recover.
                _faulted = true;
                _observer.Clear();
                return new PollReport(false, reason,
                    new BuildingDamageStageSelector.Result[0]);
            }
        }
    }
}
