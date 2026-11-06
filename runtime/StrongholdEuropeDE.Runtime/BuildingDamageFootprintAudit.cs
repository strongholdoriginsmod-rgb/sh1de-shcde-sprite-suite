using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Read-only footprint and orientation evidence. Converts an API-provided
    /// set of occupied game tiles into *hypothetical* SpriteSuite grid orders.
    /// Never assumes the engine's occupied-tile array order is visual order.
    /// No Unity objects, game memory, hooks, rendering or disk operations.
    /// </summary>
    internal static class BuildingDamageFootprintAudit
    {
        internal const int MaximumTiles = 4096;
        internal const int MaximumMapCoordinate = 799;

        internal struct Tile
        {
            internal readonly int Id;
            internal readonly int X;
            internal readonly int Y;

            internal Tile(int id, int x, int y)
            {
                Id = id;
                X = x;
                Y = y;
            }
        }

        internal sealed class Observation
        {
            internal readonly int BuildingId;
            internal readonly int GlobalId;
            internal readonly int BuildingType;
            internal readonly int OccupyGridSize;
            internal readonly Tile[] Tiles;

            internal Observation(
                int buildingId,
                int globalId,
                int buildingType,
                int occupyGridSize,
                Tile[] tiles)
            {
                BuildingId = buildingId;
                GlobalId = globalId;
                BuildingType = buildingType;
                OccupyGridSize = occupyGridSize;
                Tiles = tiles;
            }
        }

        internal sealed class Orientation
        {
            internal readonly string Name;
            internal readonly int[] TileIdBySpriteSlot;
            internal Orientation(string name, int[] ids)
            {
                Name = name;
                TileIdBySpriteSlot = ids;
            }
        }

        internal sealed class Report
        {
            internal readonly string Status;
            internal readonly Observation Source;
            internal readonly int SpriteA;
            internal readonly int SpriteB;
            internal readonly int MinX;
            internal readonly int MinY;
            internal readonly int Width;
            internal readonly int Height;
            internal readonly Orientation[] Hypotheses;

            internal Report(
                string status,
                Observation source,
                int spriteA,
                int spriteB,
                int minX,
                int minY,
                int width,
                int height,
                Orientation[] hypotheses)
            {
                Status = status;
                Source = source;
                SpriteA = spriteA;
                SpriteB = spriteB;
                MinX = minX;
                MinY = minY;
                Width = width;
                Height = height;
                Hypotheses = hypotheses;
            }

            internal bool GeometryCompatible
            {
                get { return Status == "orientation_ambiguous"; }
            }

            // This value deliberately cannot become true through geometry
            // analysis alone. Mapping to renderer/mask/slot must be measured
            // against an actual game build and explicitly reviewed.
            internal bool RendererMappingVerified
            {
                get { return false; }
            }

            internal string ToTsv()
            {
                var output = new StringBuilder();
                output.Append("# stronghold-building-footprint-evidence.v1\n");
                output.Append("# diagnostic-only; no renderer mapping or native writes\n");
                output.Append("building_id\tglobal_id\tbuilding_type\tgrid_size\t");
                output.Append("sprite_a\tsprite_b\tstatus\thypothesis_count\n");
                output.Append(Source == null ? 0 : Source.BuildingId).Append('\t');
                output.Append(Source == null ? 0 : Source.GlobalId).Append('\t');
                output.Append(Source == null ? 0 : Source.BuildingType).Append('\t');
                output.Append(Source == null ? 0 : Source.OccupyGridSize).Append('\t');
                output.Append(SpriteA).Append('\t').Append(SpriteB).Append('\t');
                output.Append(Status).Append('\t').Append(Hypotheses.Length).Append('\n');
                output.Append("hypothesis\tsprite_slot\toccupied_tile_id\n");
                foreach (Orientation orientation in Hypotheses)
                    for (int slot = 0; slot < orientation.TileIdBySpriteSlot.Length; slot++)
                        output.Append(orientation.Name).Append('\t')
                            .Append(slot.ToString(CultureInfo.InvariantCulture))
                            .Append('\t').Append(orientation.TileIdBySpriteSlot[slot]
                                .ToString(CultureInfo.InvariantCulture)).Append('\n');
                return output.ToString();
            }
        }

        private static Report Failure(
            string reason,
            Observation source,
            int a,
            int b,
            int minX = 0,
            int minY = 0,
            int width = 0,
            int height = 0)
        {
            return new Report(reason, source, a, b, minX, minY,
                width, height, new Orientation[0]);
        }

        internal static Report Analyse(
            Observation source,
            BuildingDamageStageSelector.Profile profile)
        {
            if (profile == null || profile.SpriteA == 0 || profile.SpriteB == 0)
                return Failure("legacy_profile_missing_sprite_grid", source, 0, 0);
            if (source == null || source.BuildingType != profile.BuildingType)
                return Failure("profile_building_type_mismatch", source,
                    profile.SpriteA, profile.SpriteB);
            return Analyse(source, profile.SpriteA, profile.SpriteB);
        }

        internal static Report Analyse(
            Observation source,
            int spriteA,
            int spriteB)
        {
            if (spriteA < 1 || spriteA > 64 || spriteB < 1 || spriteB > 64)
                return Failure("invalid_sprite_grid", source, spriteA, spriteB);
            if (source == null || source.BuildingId <= 0 ||
                source.GlobalId <= 0 || source.BuildingType < 0 ||
                source.BuildingType > 4095)
                return Failure("invalid_building_identity", source, spriteA, spriteB);
            if (source.OccupyGridSize < 1 || source.OccupyGridSize > 64)
                return Failure("invalid_occupy_grid_size", source, spriteA, spriteB);
            Tile[] tiles = source.Tiles;
            if (tiles == null || tiles.Length == 0 || tiles.Length > MaximumTiles)
                return Failure("invalid_occupied_tile_count", source, spriteA, spriteB);
            var seenIds = new HashSet<int>();
            var seenCoords = new HashSet<long>();
            int minX = int.MaxValue, maxX = int.MinValue;
            int minY = int.MaxValue, maxY = int.MinValue;
            foreach (Tile t in tiles)
            {
                if (t.Id < 0 || t.X < 0 || t.X > MaximumMapCoordinate ||
                    t.Y < 0 || t.Y > MaximumMapCoordinate)
                    return Failure("invalid_tile_coordinate", source, spriteA, spriteB);
                if (!seenIds.Add(t.Id))
                    return Failure("duplicate_occupied_tile_id", source, spriteA, spriteB);
                long xy = ((long)t.Y << 32) | (uint)t.X;
                if (!seenCoords.Add(xy))
                    return Failure("duplicate_occupied_tile_coordinate", source, spriteA, spriteB);
                minX = Math.Min(minX, t.X);
                maxX = Math.Max(maxX, t.X);
                minY = Math.Min(minY, t.Y);
                maxY = Math.Max(maxY, t.Y);
            }
            int width = maxX - minX + 1;
            int height = maxY - minY + 1;
            if (width > source.OccupyGridSize || height > source.OccupyGridSize ||
                tiles.Length > source.OccupyGridSize * source.OccupyGridSize)
                return Failure("occupied_tiles_exceed_game_grid", source, spriteA, spriteB,
                    minX, minY, width, height);
            if (width * height != tiles.Length)
                return Failure("incomplete_or_irregular_footprint", source, spriteA, spriteB,
                    minX, minY, width, height);
            if (spriteA * spriteB != tiles.Length)
                return Failure("sprite_grid_count_mismatch", source, spriteA, spriteB,
                    minX, minY, width, height);

            int[] slotByUv = new int[spriteA * spriteB];
            int nextSlot = 0;
            // SpriteCore.positions() order: diagonal ascending, u descending.
            for (int d = 0; d < spriteA + spriteB - 1; d++)
                for (int u = Math.Min(spriteA - 1, d);
                    u >= Math.Max(0, d - spriteB + 1); u--)
                {
                    int v = d - u;
                    slotByUv[u * spriteB + v] = nextSlot++;
                }
            var hypotheses = new List<Orientation>();
            var keys = new HashSet<string>(StringComparer.Ordinal);
            // Two possible axis assignments with both directional flips.
            // A footprint alone never tells us which orientation matches the
            // game's building-tile visual order.
            for (int swapped = 0; swapped < 2; swapped++)
            {
                int uSpan = swapped == 0 ? width : height;
                int vSpan = swapped == 0 ? height : width;
                if (uSpan != spriteA || vSpan != spriteB)
                    continue;
                for (int reverseU = 0; reverseU < 2; reverseU++)
                    for (int reverseV = 0; reverseV < 2; reverseV++)
                    {
                        int[] ids = new int[tiles.Length];
                        bool[] used = new bool[tiles.Length];
                        foreach (Tile t in tiles)
                        {
                            int u = (swapped == 0 ? t.X - minX : t.Y - minY);
                            int v = (swapped == 0 ? t.Y - minY : t.X - minX);
                            if (reverseU != 0) u = spriteA - 1 - u;
                            if (reverseV != 0) v = spriteB - 1 - v;
                            int slot = slotByUv[u * spriteB + v];
                            if (used[slot])
                                return Failure("duplicate_candidate_slot", source,
                                    spriteA, spriteB, minX, minY, width, height);
                            ids[slot] = t.Id;
                            used[slot] = true;
                        }
                        string fingerprint = string.Join(",", ids);
                        if (keys.Add(fingerprint))
                        {
                            string label = (swapped == 0 ? "xy" : "yx")
                                + (reverseU == 0 ? "+u" : "-u")
                                + (reverseV == 0 ? "+v" : "-v");
                            hypotheses.Add(new Orientation(label, ids));
                        }
                    }
            }
            if (hypotheses.Count == 0)
                return Failure("sprite_grid_shape_mismatch", source,
                    spriteA, spriteB, minX, minY, width, height);
            return new Report("orientation_ambiguous", source, spriteA, spriteB,
                minX, minY, width, height, hypotheses.ToArray());
        }

        /// <summary>
        /// Check for a tile claimed by two different observed global building
        /// identities, without allowing any renderer ownership decision.
        /// </summary>
        internal static int[] SharedTileIds(IEnumerable<Observation> observations)
        {
            if (observations == null)
                throw new ArgumentNullException("observations");
            var ownerByTile = new Dictionary<int, long>();
            var collisions = new HashSet<int>();
            foreach (Observation item in observations)
            {
                if (item == null || item.Tiles == null) continue;
                long owner = ((long)item.GlobalId << 32) | (uint)item.BuildingId;
                foreach (Tile tile in item.Tiles)
                {
                    long previous;
                    if (ownerByTile.TryGetValue(tile.Id, out previous))
                    {
                        if (previous != owner) collisions.Add(tile.Id);
                    }
                    else ownerByTile[tile.Id] = owner;
                }
            }
            int[] result = new int[collisions.Count];
            collisions.CopyTo(result);
            Array.Sort(result);
            return result;
        }
    }
}
