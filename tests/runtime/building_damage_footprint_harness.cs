using System;
using System.Collections.Generic;
using System.Linq;
using StrongholdEuropeDE.Runtime;

namespace SHCDESE.API
{
    // Compile-only facade with deliberately non-linear, synthetic tile IDs.
    public struct MapXY
    {
        public ushort X;
        public ushort Y;
        public MapXY(int x, int y)
        {
            X = (ushort)x;
            Y = (ushort)y;
        }
    }
    public class GameBuildingManagerAPI
    {
        public static GameBuildingManagerAPI Instance { get; set; }
        public bool Alive = true;
        public int Id = 11, Global = 8801, Type = 108, GridSize = 3;
        public int[] Tiles;
        public bool SwapGlobalAfterRead = false;
        public bool SwapInstanceAfterRead = false;
        public bool ThrowOnOccupiedRead = false;
        private int _globalReads;
        public bool IsValid(int id) { return Alive && id == Id; }
        public int GetGlobalId(int id)
        {
            _globalReads++;
            return SwapGlobalAfterRead && _globalReads > 1 ? Global + 1 : Global;
        }
        public int GetType(int id) { return Type; }
        public int GetOccupyTileGridSize(int id) { return GridSize; }
        public int[] GetOccupiedTileIds(int id)
        {
            if (ThrowOnOccupiedRead) throw new InvalidOperationException("synthetic bad footprint getter");
            if (SwapInstanceAfterRead)
                Instance = new GameBuildingManagerAPI();
            return Tiles;
        }
    }

    public class GameTileManagerAPI
    {
        public static GameTileManagerAPI Instance { get; set; }
        public readonly Dictionary<int, MapXY> Coordinates =
            new Dictionary<int, MapXY>();
        public bool InvalidRoundtrip;
        public ushort OwnerBuildingId = 11;
        public ushort GetTileBuildingId(int tileId) { return OwnerBuildingId; }
        public int GetTileId(int x, int y)
        {
            foreach (var item in Coordinates)
                if (item.Value.X == x && item.Value.Y == y)
                    return InvalidRoundtrip ? item.Key + 1 : item.Key;
            return -1;
        }
        public bool IsValidTileId(int id) { return Coordinates.ContainsKey(id); }
        public bool IsTileInsideMapBounds(int x, int y)
        {
            return x >= 0 && y >= 0 && x <= 799 && y <= 799;
        }
        public MapXY GetTileVectorFromId(int id) { return Coordinates[id]; }
    }
}

internal static class BuildingDamageFootprintHarness
{
    private static int _tests;
    private static void Check(bool condition, string label)
    {
        _tests++;
        if (!condition) throw new Exception("FAIL " + label);
    }
    private static BuildingDamageFootprintAudit.Observation MakeFootprint(
        int a, int b, int type = 108)
    {
        var tiles = new List<BuildingDamageFootprintAudit.Tile>();
        for (int y = 0; y < b; y++)
            for (int x = 0; x < a; x++)
                tiles.Add(new BuildingDamageFootprintAudit.Tile(
                    30011 + x * 67 + y * 109, 398 + x, 412 + y));
        tiles.Reverse();
        return new BuildingDamageFootprintAudit.Observation(
            11, 8801, type, Math.Max(a, b), tiles.ToArray());
    }
    private static BuildingDamageStageSelector.Result Selected(int global = 8801)
    {
        var profile = new BuildingDamageStageSelector.Profile(108, "g_abbey",
            new [] {
                new BuildingDamageStageSelector.Stage("ruin", "damage_75",
                    BuildingDamageStageSelector.Cause.Mechanical, 75)
            });
        var state = new BuildingDamageStageSelector.Observer(new[] {profile});
        return state.Observe(11, global, 108, 50, 100, 0);
    }

    public static void Main(string[] args)
    {
        var three = MakeFootprint(3, 3);
        var report = BuildingDamageFootprintAudit.Analyse(three, 3, 3);
        Check(report.GeometryCompatible, "3x3 geometry compatible");
        Check(!report.RendererMappingVerified, "3x3 is never a renderer proof");
        Check(report.Hypotheses.Length == 8, "square footprint 8 orientations");
        Check(report.Width == 3 && report.Height == 3, "3x3 dimensions");
        var candidate = report.Hypotheses.Single(p => p.Name == "xy+u+v");
        Check(candidate.TileIdBySpriteSlot.Length == 9, "9 logical slots");
        Check(candidate.TileIdBySpriteSlot[0] == 30011, "front slot correct");
        Check(candidate.TileIdBySpriteSlot[1] == 30011 + 67,
            "isometric diagonal u desc");
        Check(candidate.TileIdBySpriteSlot[2] == 30011 + 109,
            "isometric diagonal v next");
        Check(candidate.TileIdBySpriteSlot.Distinct().Count() == 9,
            "no duplicate target tiles");
        Check(report.ToTsv().StartsWith("# stronghold-building-footprint-evidence.v1\n",
            StringComparison.Ordinal), "evidence versioned");
        Check(report.ToTsv().Contains("orientation_ambiguous\t8\n"),
            "evidence labels ambiguity");

        var mismatch = BuildingDamageFootprintAudit.Analyse(three, 5, 5);
        Check(mismatch.Status == "sprite_grid_count_mismatch",
            "5x5 SpriteSuite sprite cannot be equated to a 3x3 game building");
        Check(mismatch.Hypotheses.Length == 0 &&
            !mismatch.RendererMappingVerified,
            "no incorrect tile mappings for mismatched raster");

        var rotated = BuildingDamageFootprintAudit.Analyse(
            MakeFootprint(2, 3), 3, 2);
        Check(rotated.GeometryCompatible && rotated.Hypotheses.Length == 4,
            "transposed rectangular footprint four orientations");
        var plain = BuildingDamageFootprintAudit.Analyse(
            MakeFootprint(2, 3), 2, 3);
        Check(plain.GeometryCompatible && plain.Hypotheses.Length == 4,
            "straight rectangular footprint four orientations");
        Check(BuildingDamageFootprintAudit.Analyse(
            MakeFootprint(2, 3), 2, 2).Status ==
            "sprite_grid_count_mismatch", "rectangular count mismatch");
        var single = BuildingDamageFootprintAudit.Analyse(
            MakeFootprint(1, 1), 1, 1);
        Check(single.Hypotheses.Length == 1 &&
            !single.RendererMappingVerified,
            "single tile never automatically verified for renderer");

        var reverse = MakeFootprint(3, 3);
        Array.Reverse(reverse.Tiles);
        var other = BuildingDamageFootprintAudit.Analyse(reverse, 3, 3);
        Check(other.GeometryCompatible &&
            other.Hypotheses.Single(p => p.Name == "xy+u+v")
                .TileIdBySpriteSlot.SequenceEqual(candidate.TileIdBySpriteSlot),
            "occupied ID order never determines sprite slots");

        var missing = MakeFootprint(3, 3);
        // A copied native array with one element missing must not be mapped.
        missing = new BuildingDamageFootprintAudit.Observation(
            11, 8801, 108, 3, missing.Tiles.Take(8).ToArray());
        Check(BuildingDamageFootprintAudit.Analyse(missing, 3, 3).Status ==
            "incomplete_or_irregular_footprint", "incomplete occupied array");

        var duplicate = MakeFootprint(3, 3);
        duplicate.Tiles[0] = duplicate.Tiles[1];
        Check(BuildingDamageFootprintAudit.Analyse(duplicate, 3, 3).Status ==
            "duplicate_occupied_tile_id", "duplicate occupied ID rejected");

        var duplicateXY = MakeFootprint(3, 3);
        duplicateXY.Tiles[0] = new BuildingDamageFootprintAudit.Tile(
            123345, duplicateXY.Tiles[1].X, duplicateXY.Tiles[1].Y);
        Check(BuildingDamageFootprintAudit.Analyse(duplicateXY, 3, 3).Status ==
            "duplicate_occupied_tile_coordinate", "duplicate coordinate rejected");

        var badTile = MakeFootprint(3, 3);
        badTile.Tiles[0] = new BuildingDamageFootprintAudit.Tile(42, 801, 412);
        Check(BuildingDamageFootprintAudit.Analyse(badTile, 3, 3).Status ==
            "invalid_tile_coordinate", "coordinate outside map rejected");

        var incompatibleGrid = MakeFootprint(3, 3);
        incompatibleGrid = new BuildingDamageFootprintAudit.Observation(
            11, 8801, 108, 2, incompatibleGrid.Tiles);
        Check(BuildingDamageFootprintAudit.Analyse(incompatibleGrid, 3, 3).Status ==
            "occupied_tiles_exceed_game_grid", "exceed native game grid");

        var noIdentity = new BuildingDamageFootprintAudit.Observation(
            11, 0, 108, 3, MakeFootprint(3, 3).Tiles);
        Check(BuildingDamageFootprintAudit.Analyse(noIdentity, 3, 3).Status ==
            "invalid_building_identity", "global identity mandatory");

        var a = MakeFootprint(3, 3);
        var b = MakeFootprint(3, 3);
        b = new BuildingDamageFootprintAudit.Observation(
            12, 8802, 108, 3, b.Tiles);
        var shared = BuildingDamageFootprintAudit.SharedTileIds(new[]{a,b});
        Check(shared.Length == 9 && shared.SequenceEqual(shared.OrderBy(x=>x)),
            "overlapping game building footprints explicitly reported");
        Check(BuildingDamageFootprintAudit.SharedTileIds(new[]{a,a}).Length == 0,
            "same building identity not mistaken for different owner");

        // Verify the actual API-adapter contract against a fake non-linear
        // coordinate mapping that deliberately has no y*800+x relationship.
        var manager = new SHCDESE.API.GameBuildingManagerAPI();
        var tiles = new SHCDESE.API.GameTileManagerAPI();
        manager.Tiles = a.Tiles.Select(t=>t.Id).ToArray();
        foreach (var tile in a.Tiles)
            tiles.Coordinates.Add(tile.Id, new SHCDESE.API.MapXY(tile.X,tile.Y));
        SHCDESE.API.GameBuildingManagerAPI.Instance = manager;
        SHCDESE.API.GameTileManagerAPI.Instance = tiles;
        var adapter = new BuildingDamageFootprintGameSource();
        BuildingDamageFootprintAudit.Observation captured;
        Check(adapter.TryCapture(Selected(),out captured),
            "documented SHCDESE footprint API captured");
        Check(captured.OccupyGridSize == 3 &&
            captured.Tiles.Length == 9, "API returned grid and exact tile count");
        Check(BuildingDamageFootprintAudit.Analyse(captured, 3, 3)
            .GeometryCompatible, "adapter observation feeds pure matcher");
        Check(!adapter.TryCapture(Selected(999),out captured),
            "global ID mismatch refused");
        Check(!adapter.TryCapture(null,out captured),
            "null stage selection refused");
        manager.SwapGlobalAfterRead = true;
        Check(!adapter.TryCapture(Selected(),out captured),
            "building global ID switched mid-capture");
        manager.SwapGlobalAfterRead = false;
        manager = new SHCDESE.API.GameBuildingManagerAPI();
        manager.Tiles = a.Tiles.Select(t=>t.Id).ToArray();
        SHCDESE.API.GameBuildingManagerAPI.Instance = manager;
        tiles.InvalidRoundtrip = true;
        Check(!adapter.TryCapture(Selected(),out captured),
            "nonlinear game map tile lookup round-trip checked");
        tiles.InvalidRoundtrip = false;
        manager.SwapInstanceAfterRead = true;
        Check(!adapter.TryCapture(Selected(),out captured),
            "building API singleton replacement fails closed");
        manager.SwapInstanceAfterRead = false;
        SHCDESE.API.GameBuildingManagerAPI.Instance = manager;
        Check(adapter.TryCapture(Selected(),out captured),
            "recover only when singleton stable");
        manager.GridSize = 65;
        Check(!adapter.TryCapture(Selected(),out captured),
            "unbounded game footprints are refused");
        manager.GridSize = 3;
        tiles.OwnerBuildingId = 12;
        Check(!adapter.TryCapture(Selected(),out captured),
            "independent tile owner check prevents foreign building footprint");
        tiles.OwnerBuildingId = 11;
        Check(adapter.TryCapture(Selected(),out captured),
            "read-only matching tile ownership confirmed");
        manager.Tiles = new int[]{999999};
        Check(!adapter.TryCapture(Selected(),out captured),
            "invalid game tile ID refuses capture");
        manager.Tiles = a.Tiles.Select(t=>t.Id).ToArray();
        manager.ThrowOnOccupiedRead = true;
        Check(!adapter.TryCapture(Selected(),out captured) && captured == null,
            "native API exception fails closed without leaking a partial snapshot");
        manager.ThrowOnOccupiedRead = false;
        var hp = new BuildingDamageStageSelector.Stage("damage75", "g_damage75",
            BuildingDamageStageSelector.Cause.Mechanical, 75);
        var knownProfile = new BuildingDamageStageSelector.Profile(108, "g_abbey",
            new [] {hp}, 3, 3);
        Check(BuildingDamageFootprintAudit.Analyse(three, knownProfile)
            .GeometryCompatible, "typed sprite profile can be assessed");
        var oldProfile = new BuildingDamageStageSelector.Profile(108, "g_abbey",
            new [] {hp});
        Check(BuildingDamageFootprintAudit.Analyse(three, oldProfile).Status ==
            "legacy_profile_missing_sprite_grid", "legacy profiles cannot be treated as mapped");
        var wrongProfile = new BuildingDamageStageSelector.Profile(109, "g_tower",
            new [] {hp}, 3, 3);
        Check(BuildingDamageFootprintAudit.Analyse(three, wrongProfile).Status ==
            "profile_building_type_mismatch", "building type must match visual contract");
        if (args.Length != 0)
        {
            Check(args.Length == 2, "integration accepts verified table and ZIP only");
            var document = BuildingDamageProfileTable.Parse(
                System.IO.File.ReadAllText(args[0], System.Text.Encoding.UTF8));
            Check(BuildingDamageProfileTable.MatchesPackage(document,
                System.IO.File.ReadAllBytes(args[1])), "real project ZIP digest verified");
            Check(document.Profiles.Length == 1 &&
                document.Profiles[0].SpriteA == 5 &&
                document.Profiles[0].SpriteB == 5,
                "real SpriteSuite 5x5 grid survives runtime table");
            var game5x5 = BuildingDamageFootprintAudit.Analyse(
                MakeFootprint(5, 5), document.Profiles[0]);
            Check(game5x5.GeometryCompatible &&
                game5x5.Hypotheses.Length == 8 &&
                !game5x5.RendererMappingVerified,
                "matching synthetic 5x5 footprint still has unverified renderer");
            var game3x3 = BuildingDamageFootprintAudit.Analyse(
                MakeFootprint(3, 3), document.Profiles[0]);
            Check(game3x3.Status == "sprite_grid_count_mismatch" &&
                !game3x3.RendererMappingVerified,
                "real 5x5 sprite cannot be forced onto synthetic 3x3 game occupancy");
        }
        Check(_tests >= 30, "minimum adversarial test coverage");

        Console.WriteLine("PASS SHCDE read-only building footprint: " +
            _tests + " assertions; per-building renderer not installed.");
    }
}
