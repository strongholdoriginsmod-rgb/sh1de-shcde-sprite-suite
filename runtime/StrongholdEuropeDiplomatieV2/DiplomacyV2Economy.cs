#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using SHCDESE.API;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        // One valuation for both the human and AI coalitions. Native API names
        // and cost fields are the same ones already used by RefreshCoalition.
        private long V2ProductionEconomy(HashSet<int> owners)
        {
            GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
            long economy = 0L;
            foreach (int buildingId in buildings.GetAllAliveBuildings())
            {
                if (!owners.Contains(buildings.GetOwner(buildingId))
                    || buildings.IsSleeping(buildingId)
                    || buildings.GetRequiredWorkers(buildingId) <= 0
                    || buildings.GetCurrentlyProducedGood(buildingId) == eGoods.STORED_NULL)
                    continue;
                BuildingCost cost = buildings.GetDefaultCost(buildings.GetType(buildingId));
                long materials = 0L;
                materials = SaturatingAdd(materials,
                    SaturatingMultiply(Math.Max(0, cost.Wood), _frozenPrices[2]));
                materials = SaturatingAdd(materials,
                    SaturatingMultiply(Math.Max(0, cost.Stone), _frozenPrices[4]));
                materials = SaturatingAdd(materials,
                    SaturatingMultiply(Math.Max(0, cost.Iron), _frozenPrices[6]));
                materials = SaturatingAdd(materials,
                    SaturatingMultiply(Math.Max(0, cost.Pitch), _frozenPrices[7]));
                materials = SaturatingAdd(materials, Math.Max(0, cost.Gold));
                economy = SaturatingAdd(economy,
                    ScalePercentSaturating(materials, _rules.EconomyBuildingMaterialPercent));
            }
            return economy;
        }
    }
}
#endif
