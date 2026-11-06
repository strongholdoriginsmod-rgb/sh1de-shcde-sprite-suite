#if SHCDE_BUILDING_DAMAGE_FOOTPRINT_API
using System;
using SHCDESE.API;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Opt-in, read-only adapter to the published SHCDESE footprint API.
    /// It does not run from the plugin by default, attach Harmony, call Unity
    /// rendering, alter game arrays or install a damage model.
    /// Call only from a separately verified main-thread / map-active scope.
    /// </summary>
    internal sealed class BuildingDamageFootprintGameSource
    {
        internal bool TryCapture(
            BuildingDamageStageSelector.Result selected,
            out BuildingDamageFootprintAudit.Observation observation)
        {
            observation = null;
            try
            {
                return TryCaptureCore(selected, out observation);
            }
            catch (Exception)
            {
                observation = null;
                return false; // Unknown SE build or transient map state: never leak an unsafe capture.
            }
        }

        private static bool TryCaptureCore(
            BuildingDamageStageSelector.Result selected,
            out BuildingDamageFootprintAudit.Observation observation)
        {
            observation = null;
            if (selected == null || selected.UseVanilla ||
                selected.BuildingId <= 0 || selected.BuildingId > ushort.MaxValue ||
                selected.GlobalId <= 0)
                return false;
            GameBuildingManagerAPI buildingApi = GameBuildingManagerAPI.Instance;
            GameTileManagerAPI tileApi = GameTileManagerAPI.Instance;
            if (buildingApi == null || tileApi == null)
                return false;
            int id = selected.BuildingId;
            if (!buildingApi.IsValid(id) ||
                buildingApi.GetGlobalId(id) != selected.GlobalId)
                return false;

            int type = (int)buildingApi.GetType(id);
            if (type != selected.BuildingType)
                return false;
            int gridSize = buildingApi.GetOccupyTileGridSize(id);
            if (gridSize <= 0 || gridSize > 64)
                return false;
            int[] tileIds = buildingApi.GetOccupiedTileIds(id);
            if (tileIds == null || tileIds.Length == 0 ||
                tileIds.Length > BuildingDamageFootprintAudit.MaximumTiles)
                return false;
            var samples = new BuildingDamageFootprintAudit.Tile[tileIds.Length];
            for (int i = 0; i < tileIds.Length; i++)
            {
                int tileId = tileIds[i];
                if (tileId < 0 || !tileApi.IsValidTileId(tileId) ||
                    tileApi.GetTileBuildingId(tileId) != id)
                    return false;
                var xy = tileApi.GetTileVectorFromId(tileId);
                int x = xy.X, y = xy.Y;
                if (x < 0 || x > BuildingDamageFootprintAudit.MaximumMapCoordinate ||
                    y < 0 || y > BuildingDamageFootprintAudit.MaximumMapCoordinate ||
                    !tileApi.IsTileInsideMapBounds(x, y) ||
                    tileApi.GetTileId(x, y) != tileId)
                    return false;
                samples[i] = new BuildingDamageFootprintAudit.Tile(tileId, x, y);
            }
            // Check again after all lookups: an entity might have been removed,
            // reused or replaced while reading native-derived API values.
            if (!Object.ReferenceEquals(buildingApi, GameBuildingManagerAPI.Instance) ||
                !Object.ReferenceEquals(tileApi, GameTileManagerAPI.Instance) ||
                !buildingApi.IsValid(id) ||
                buildingApi.GetGlobalId(id) != selected.GlobalId ||
                (int)buildingApi.GetType(id) != selected.BuildingType ||
                buildingApi.GetOccupyTileGridSize(id) != gridSize)
                return false;
            foreach (int tileId in tileIds)
                if (tileApi.GetTileBuildingId(tileId) != id)
                    return false;
            // Do not assume the array order describes graphics slots.
            observation = new BuildingDamageFootprintAudit.Observation(
                id, selected.GlobalId, selected.BuildingType, gridSize, samples);
            return true;
        }
    }
}
#endif // SHCDE_BUILDING_DAMAGE_FOOTPRINT_API
