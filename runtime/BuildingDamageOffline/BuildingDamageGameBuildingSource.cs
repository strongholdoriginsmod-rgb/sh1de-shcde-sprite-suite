#if SHCDE_BUILDING_DAMAGE_READONLY_API
using System;
using SHCDESE.API;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Read-only adapter for the published SHCDE Script Extender building API.
    /// It is deliberately not activated in the Runtime plugin yet:
    /// a main-thread lifecycle and per-instance multi-tile renderer route
    /// must first pass the game/SE-version compatibility gate.
    /// </summary>
    internal sealed class BuildingDamageGameBuildingSource
        : BuildingDamageReadOnlyProbe.ISource
    {
        public int[] GetAliveBuildingIds()
        {
            GameBuildingManagerAPI api = GameBuildingManagerAPI.Instance;
            if (api == null)
                return null;
            return api.GetAllAliveBuildings();
        }

        public bool TryRead(int buildingId,
            out BuildingDamageReadOnlyProbe.Snapshot snapshot)
        {
            snapshot = default(BuildingDamageReadOnlyProbe.Snapshot);
            if (buildingId <= 0)
                return false;
            GameBuildingManagerAPI api = GameBuildingManagerAPI.Instance;
            if (api == null || !api.IsValid(buildingId))
                return false;
            int before = api.GetGlobalId(buildingId);
            if (before <= 0)
                return false;
            // The published API gives these values by building id.
            // Only a second identity check prevents using another building
            // that reused this slot during the observed read interval.
            int type = (int)api.GetType(buildingId);
            int current = api.GetCurrentHealth(buildingId);
            int maximum = api.GetMaxHealth(buildingId);
            int fireTicks = (int)api.GetOnFireTicks(buildingId);
            if (!object.ReferenceEquals(api, GameBuildingManagerAPI.Instance) ||
                !api.IsValid(buildingId) ||
                api.GetGlobalId(buildingId) != before)
                return false;
            if (type < 0 || type > 4095 || maximum <= 0 ||
                current < 0 || current > maximum)
                return false;
            snapshot = new BuildingDamageReadOnlyProbe.Snapshot(
                buildingId, before, type, current, maximum, fireTicks);
            return true;
        }
    }
}
#endif // SHCDE_BUILDING_DAMAGE_READONLY_API
