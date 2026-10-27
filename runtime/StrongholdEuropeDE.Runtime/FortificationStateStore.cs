using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed class FortificationTileState
    {
        internal FortificationTileState(
            int tileId,
            string variantId,
            int ownerPlayerId,
            int damageRemainder = 0)
        {
            FortificationStateStore.ValidateTileId(tileId, nameof(tileId));
            FortificationStateStore.ValidatePlayerId(
                ownerPlayerId,
                nameof(ownerPlayerId));
            FortificationVariantDefinition variant =
                FortificationVariantCatalog.GetRequired(variantId);
            if (variant.Role != FortificationVariantRole.AdditionalWall)
            {
                throw new ArgumentException(
                    "Tile state requires an additional wall variant.",
                    nameof(variantId));
            }
            FortificationDamageScaler.ValidateRemainder(
                variant.Durability,
                damageRemainder);

            TileId = tileId;
            VariantId = variant.Id;
            OwnerPlayerId = ownerPlayerId;
            DamageRemainder = damageRemainder;
        }

        internal int TileId { get; }
        internal string VariantId { get; }
        internal int OwnerPlayerId { get; }
        internal int DamageRemainder { get; }

        internal FortificationTileState WithDamageRemainder(int remainder)
        {
            return new FortificationTileState(
                TileId,
                VariantId,
                OwnerPlayerId,
                remainder);
        }
    }

    internal sealed class FortificationGateState
    {
        private readonly ReadOnlyCollection<int> _occupiedTileIds;

        internal FortificationGateState(
            int anchorTileId,
            string variantId,
            int ownerPlayerId,
            int routeIndex,
            IEnumerable<int> occupiedTileIds,
            int damageRemainder = 0)
        {
            FortificationStateStore.ValidateTileId(
                anchorTileId,
                nameof(anchorTileId));
            FortificationStateStore.ValidatePlayerId(
                ownerPlayerId,
                nameof(ownerPlayerId));
            FortificationVariantDefinition variant =
                FortificationVariantCatalog.GetRequired(variantId);
            if (variant.Role != FortificationVariantRole.Gatehouse)
            {
                throw new ArgumentException(
                    "Gate state requires a gatehouse variant.",
                    nameof(variantId));
            }
            if (routeIndex < 0 || routeIndex >= variant.MapperRouteIds.Count)
            {
                throw new ArgumentOutOfRangeException(nameof(routeIndex));
            }
            if (occupiedTileIds == null)
            {
                throw new ArgumentNullException(nameof(occupiedTileIds));
            }

            var occupied = new List<int>();
            var unique = new HashSet<int>();
            foreach (int tileId in occupiedTileIds)
            {
                FortificationStateStore.ValidateTileId(
                    tileId,
                    nameof(occupiedTileIds));
                if (!unique.Add(tileId))
                {
                    throw new ArgumentException(
                        "Gate occupied tiles must be unique.",
                        nameof(occupiedTileIds));
                }
                occupied.Add(tileId);
            }
            if (occupied.Count < 1
                || occupied.Count
                    > FortificationStateStore.MaximumGateFootprintTiles
                || !unique.Contains(anchorTileId))
            {
                throw new ArgumentException(
                    "Gate footprint must contain its anchor and remain within "
                    + "the V1 footprint bound.",
                    nameof(occupiedTileIds));
            }
            occupied.Sort();
            FortificationDamageScaler.ValidateRemainder(
                variant.Durability,
                damageRemainder);

            AnchorTileId = anchorTileId;
            VariantId = variant.Id;
            OwnerPlayerId = ownerPlayerId;
            RouteIndex = routeIndex;
            _occupiedTileIds = occupied.AsReadOnly();
            DamageRemainder = damageRemainder;
        }

        internal int AnchorTileId { get; }
        internal string VariantId { get; }
        internal int OwnerPlayerId { get; }
        internal int RouteIndex { get; }
        internal IReadOnlyList<int> OccupiedTileIds => _occupiedTileIds;
        internal int DamageRemainder { get; }

        internal int MapperRouteId =>
            FortificationVariantCatalog
                .GetRequired(VariantId)
                .MapperRouteForIndex(RouteIndex);

        internal FortificationGateState WithDamageRemainder(int remainder)
        {
            return new FortificationGateState(
                AnchorTileId,
                VariantId,
                OwnerPlayerId,
                RouteIndex,
                _occupiedTileIds,
                remainder);
        }
    }

    /// <summary>
    /// Owns only mod sidecar identity and rational-damage remainders. Native
    /// hit points and native battlements remain game-owned and are not copied.
    /// </summary>
    internal sealed class FortificationStateStore
    {
        internal const int MapWidth = 800;
        internal const int MapHeight = 800;
        internal const int MaximumTileCount = MapWidth * MapHeight;
        internal const int MaximumGateFootprintTiles = 64;
        internal const int MinimumPlayerId = 1;
        internal const int MaximumPlayerId = 8;

        private readonly Dictionary<int, FortificationTileState> _tiles =
            new Dictionary<int, FortificationTileState>();
        private readonly Dictionary<int, FortificationGateState> _gates =
            new Dictionary<int, FortificationGateState>();
        private readonly Dictionary<int, int> _gateAnchorByOccupiedTile =
            new Dictionary<int, int>();
        private readonly int[,] _creditQuarters =
            new int[MaximumPlayerId + 1, 3];

        internal int TileCount => _tiles.Count;
        internal int GateCount => _gates.Count;

        internal IReadOnlyList<FortificationEconomyCreditRecord>
            SnapshotEconomyCredits()
        {
            var result = new List<FortificationEconomyCreditRecord>(
                MaximumPlayerId * 2);
            for (int playerId = MinimumPlayerId;
                playerId <= MaximumPlayerId;
                playerId++)
            {
                result.Add(new FortificationEconomyCreditRecord(
                    playerId,
                    FortificationResource.Wood,
                    _creditQuarters[
                        playerId,
                        (int)FortificationResource.Wood]));
                result.Add(new FortificationEconomyCreditRecord(
                    playerId,
                    FortificationResource.Stone,
                    _creditQuarters[
                        playerId,
                        (int)FortificationResource.Stone]));
            }
            return new ReadOnlyCollection<FortificationEconomyCreditRecord>(
                result);
        }

        internal FortificationCreditBalance GetEconomyCredit(int playerId)
        {
            ValidatePlayerId(playerId, nameof(playerId));
            return new FortificationCreditBalance(
                _creditQuarters[
                    playerId,
                    (int)FortificationResource.Wood],
                _creditQuarters[
                    playerId,
                    (int)FortificationResource.Stone]);
        }

        internal void SetEconomyCredit(
            int playerId,
            FortificationCreditBalance credit)
        {
            ValidatePlayerId(playerId, nameof(playerId));
            _creditQuarters[
                playerId,
                (int)FortificationResource.Wood] = credit.WoodQuarters;
            _creditQuarters[
                playerId,
                (int)FortificationResource.Stone] = credit.StoneQuarters;
        }

        internal void SetEconomyCredit(
            FortificationEconomyCreditRecord credit)
        {
            ValidatePlayerId(credit.PlayerId, nameof(credit));
            FortificationCreditBalance.ValidateResource(
                credit.Resource,
                nameof(credit));
            FortificationCreditBalance.ValidateCredit(
                credit.CreditQuarters,
                nameof(credit));
            _creditQuarters[
                credit.PlayerId,
                (int)credit.Resource] = credit.CreditQuarters;
        }

        internal void CommitPurchaseCredit(
            int playerId,
            FortificationPurchaseQuote quote)
        {
            ValidatePlayerId(playerId, nameof(playerId));
            if (!quote.Affordable)
            {
                throw new InvalidOperationException(
                    "Cannot commit credit for an unaffordable purchase.");
            }
            if (!GetEconomyCredit(playerId).Equals(quote.CreditBefore))
            {
                throw new InvalidOperationException(
                    "Prepaid fortification credit changed after the quote.");
            }
            SetEconomyCredit(playerId, quote.CreditAfter);
        }

        internal IReadOnlyList<FortificationTileState> SnapshotTiles()
        {
            return new ReadOnlyCollection<FortificationTileState>(
                _tiles.Values
                    .OrderBy(value => value.TileId)
                    .ToList());
        }

        internal IReadOnlyList<FortificationGateState> SnapshotGates()
        {
            return new ReadOnlyCollection<FortificationGateState>(
                _gates.Values
                    .OrderBy(value => value.AnchorTileId)
                    .ToList());
        }

        internal bool TryGetTile(
            int tileId,
            out FortificationTileState state)
        {
            return _tiles.TryGetValue(tileId, out state);
        }

        internal bool TryGetGate(
            int anchorTileId,
            out FortificationGateState state)
        {
            return _gates.TryGetValue(anchorTileId, out state);
        }

        internal void AddTile(FortificationTileState state)
        {
            ValidateTileState(state);
            if (_tiles.ContainsKey(state.TileId))
            {
                throw new InvalidDataException(
                    "Duplicate fortification tile id: " + state.TileId);
            }
            if (_gateAnchorByOccupiedTile.ContainsKey(state.TileId))
            {
                throw new InvalidDataException(
                    "Fortification tile overlaps a gate footprint: "
                    + state.TileId);
            }
            _tiles.Add(state.TileId, state);
        }

        internal void SetTile(FortificationTileState state)
        {
            ValidateTileState(state);
            if (_gateAnchorByOccupiedTile.ContainsKey(state.TileId))
            {
                throw new InvalidDataException(
                    "Fortification tile overlaps a gate footprint: "
                    + state.TileId);
            }
            _tiles[state.TileId] = state;
        }

        internal bool RemoveTile(int tileId)
        {
            return _tiles.Remove(tileId);
        }

        internal void AddGate(FortificationGateState state)
        {
            ValidateGateState(state);
            if (_gates.ContainsKey(state.AnchorTileId))
            {
                throw new InvalidDataException(
                    "Duplicate fortification gate anchor: "
                    + state.AnchorTileId);
            }
            ValidateGateFootprintConflicts(state, replacedAnchor: null);
            CommitGate(state);
        }

        internal void SetGate(FortificationGateState state)
        {
            ValidateGateState(state);
            int? replacedAnchor = _gates.ContainsKey(state.AnchorTileId)
                ? state.AnchorTileId
                : (int?)null;
            ValidateGateFootprintConflicts(state, replacedAnchor);
            if (replacedAnchor.HasValue)
            {
                RemoveGate(replacedAnchor.Value);
            }
            CommitGate(state);
        }

        internal bool RemoveGate(int anchorTileId)
        {
            FortificationGateState existing;
            if (!_gates.TryGetValue(anchorTileId, out existing))
            {
                return false;
            }
            foreach (int tileId in existing.OccupiedTileIds)
            {
                int recordedAnchor;
                if (_gateAnchorByOccupiedTile.TryGetValue(
                        tileId,
                        out recordedAnchor)
                    && recordedAnchor == anchorTileId)
                {
                    _gateAnchorByOccupiedTile.Remove(tileId);
                }
            }
            _gates.Remove(anchorTileId);
            return true;
        }

        internal FortificationDamageResult ScaleTileDamage(
            int tileId,
            int incomingDamage)
        {
            FortificationTileState state;
            if (!_tiles.TryGetValue(tileId, out state))
            {
                throw new KeyNotFoundException(
                    "Unknown fortification tile: " + tileId);
            }
            FortificationVariantDefinition variant =
                FortificationVariantCatalog.GetRequired(state.VariantId);
            FortificationDamageResult result =
                FortificationDamageScaler.ScaleIncomingDamage(
                    variant,
                    incomingDamage,
                    state.DamageRemainder);
            _tiles[tileId] = state.WithDamageRemainder(result.Remainder);
            return result;
        }

        internal FortificationDamageResult ScaleGateDamage(
            int anchorTileId,
            int incomingDamage)
        {
            FortificationGateState state;
            if (!_gates.TryGetValue(anchorTileId, out state))
            {
                throw new KeyNotFoundException(
                    "Unknown fortification gate: " + anchorTileId);
            }
            FortificationVariantDefinition variant =
                FortificationVariantCatalog.GetRequired(state.VariantId);
            FortificationDamageResult result =
                FortificationDamageScaler.ScaleIncomingDamage(
                    variant,
                    incomingDamage,
                    state.DamageRemainder);
            _gates[anchorTileId] =
                state.WithDamageRemainder(result.Remainder);
            return result;
        }

        internal void ValidateInvariants()
        {
            if (_tiles.Count > MaximumTileCount
                || _gates.Count > MaximumTileCount)
            {
                throw new InvalidDataException(
                    "Fortification state exceeds map bounds.");
            }

            var occupied = new Dictionary<int, int>();
            foreach (FortificationTileState tile in _tiles.Values)
            {
                ValidateTileState(tile);
            }
            foreach (FortificationGateState gate in _gates.Values)
            {
                ValidateGateState(gate);
                foreach (int tileId in gate.OccupiedTileIds)
                {
                    if (_tiles.ContainsKey(tileId))
                    {
                        throw new InvalidDataException(
                            "Fortification tile overlaps a gate footprint: "
                            + tileId);
                    }
                    int previousAnchor;
                    if (occupied.TryGetValue(tileId, out previousAnchor))
                    {
                        throw new InvalidDataException(
                            "Gate footprints overlap at tile " + tileId
                            + " (anchors " + previousAnchor + " and "
                            + gate.AnchorTileId + ").");
                    }
                    occupied.Add(tileId, gate.AnchorTileId);
                }
            }
            if (occupied.Count != _gateAnchorByOccupiedTile.Count
                || occupied.Any(pair =>
                    !_gateAnchorByOccupiedTile.TryGetValue(
                        pair.Key,
                        out int anchor)
                    || anchor != pair.Value))
            {
                throw new InvalidDataException(
                    "Gate footprint index disagrees with gate state.");
            }
            foreach (FortificationEconomyCreditRecord credit
                in SnapshotEconomyCredits())
            {
                ValidatePlayerId(credit.PlayerId, nameof(credit));
                FortificationCreditBalance.ValidateResource(
                    credit.Resource,
                    nameof(credit));
                FortificationCreditBalance.ValidateCredit(
                    credit.CreditQuarters,
                    nameof(credit));
            }
        }

        internal static bool IsValidTileId(int tileId)
        {
            return tileId >= 0 && tileId < MaximumTileCount;
        }

        internal static void ValidateTileId(int tileId, string parameterName)
        {
            if (!IsValidTileId(tileId))
            {
                throw new ArgumentOutOfRangeException(parameterName);
            }
        }

        internal static void ValidatePlayerId(
            int playerId,
            string parameterName)
        {
            if (playerId < MinimumPlayerId || playerId > MaximumPlayerId)
            {
                throw new ArgumentOutOfRangeException(parameterName);
            }
        }

        private static void ValidateTileState(FortificationTileState state)
        {
            if (state == null)
            {
                throw new ArgumentNullException(nameof(state));
            }
            ValidateTileId(state.TileId, nameof(state));
            ValidatePlayerId(state.OwnerPlayerId, nameof(state));
            FortificationVariantDefinition variant =
                FortificationVariantCatalog.GetRequired(state.VariantId);
            if (variant.Role != FortificationVariantRole.AdditionalWall)
            {
                throw new InvalidDataException(
                    "Tile state contains a non-wall variant.");
            }
            FortificationDamageScaler.ValidateRemainder(
                variant.Durability,
                state.DamageRemainder);
        }

        private static void ValidateGateState(FortificationGateState state)
        {
            if (state == null)
            {
                throw new ArgumentNullException(nameof(state));
            }
            ValidateTileId(state.AnchorTileId, nameof(state));
            ValidatePlayerId(state.OwnerPlayerId, nameof(state));
            FortificationVariantDefinition variant =
                FortificationVariantCatalog.GetRequired(state.VariantId);
            if (variant.Role != FortificationVariantRole.Gatehouse
                || state.RouteIndex < 0
                || state.RouteIndex >= variant.MapperRouteIds.Count
                || state.OccupiedTileIds.Count < 1
                || state.OccupiedTileIds.Count > MaximumGateFootprintTiles
                || !state.OccupiedTileIds.Contains(state.AnchorTileId)
                || state.OccupiedTileIds.Distinct().Count()
                    != state.OccupiedTileIds.Count)
            {
                throw new InvalidDataException(
                    "Gate state shape is invalid.");
            }
            foreach (int tileId in state.OccupiedTileIds)
            {
                ValidateTileId(tileId, nameof(state));
            }
            FortificationDamageScaler.ValidateRemainder(
                variant.Durability,
                state.DamageRemainder);
        }

        private void ValidateGateFootprintConflicts(
            FortificationGateState state,
            int? replacedAnchor)
        {
            foreach (int tileId in state.OccupiedTileIds)
            {
                if (_tiles.ContainsKey(tileId))
                {
                    throw new InvalidDataException(
                        "Gate footprint overlaps a fortification tile: "
                        + tileId);
                }
                int existingAnchor;
                if (_gateAnchorByOccupiedTile.TryGetValue(
                        tileId,
                        out existingAnchor)
                    && (!replacedAnchor.HasValue
                        || existingAnchor != replacedAnchor.Value))
                {
                    throw new InvalidDataException(
                        "Gate footprints overlap at tile " + tileId + ".");
                }
            }
        }

        private void CommitGate(FortificationGateState state)
        {
            _gates.Add(state.AnchorTileId, state);
            foreach (int tileId in state.OccupiedTileIds)
            {
                _gateAnchorByOccupiedTile.Add(tileId, state.AnchorTileId);
            }
        }
    }
}
