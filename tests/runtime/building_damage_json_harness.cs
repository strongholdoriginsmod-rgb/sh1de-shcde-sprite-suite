// Standalone test for the actual damage-manifest.json and runtime.json.
// Compiled with the pure JSON parser only; Unity and game assemblies not needed.
using System;
using System.Collections.Generic;
using System.IO;

namespace SpriteSuite.BuildingDamage
{
    public sealed class DamageRuntimeSettings
    {
        public string damageArchive = "gebaeudeschaden.zip";
        public string damageDirectory = "DamageAssets";
        public bool enabled = true;
        public bool firePersistsUntilRepaired = true;
        public int pollFrames = 12;
        public bool previewEnabled;
        public int previewHpPercent = 50;
        public bool previewFire;
        public SpriteBinding[] bindings = new SpriteBinding[0];
    }
    public sealed class SpriteBinding
    {
        public int buildingType;
        public string buildingGroupId;
        public string sourceSprite;
        public bool matchGmImage;
        public int gm, image, slot, ownerOffsetX, ownerOffsetY;
        public bool overridePivot, overridePpu;
        public float pivotX = .5f, pivotY, pixelsPerUnit = 100;
    }
    public sealed class DamageArchive
    {
        public string format;
        public int version;
        public DamageBuilding[] buildings;
    }
    public sealed class DamageBuilding
    {
        public string id, name;
        public int gameBuildingType;
        public DamageStage[] stages;
    }
    public sealed class DamageStage
    {
        public string id, damageKind;
        public int hpAtOrBelow;
        public DamageTile[] tiles;
    }
    public sealed class DamageTile
    {
        public int slot;
        public string image, sha256, mask;
    }

    internal static class RuntimeJsonHarness
    {
        private static int count;
        private static void Assert(bool ok, string message)
        {
            count++;
            if (!ok) throw new Exception(message);
        }
        private static void Main(string[] args)
        {
            if (args.Length != 2) throw new ArgumentException("manifest runtime");
            var lib = DamageJsonParser.Library(File.ReadAllText(args[0]));
            var config = DamageJsonParser.Settings(File.ReadAllText(args[1]));
            Assert(lib.format == "stronghold-building-damage-library", "format");
            Assert(lib.buildings.Length == 1, "building count");
            Assert(lib.buildings[0].gameBuildingType == 104, "game type");
            Assert(lib.buildings[0].id == "g_qa_type104_render", "group");
            Assert(lib.buildings[0].stages.Length == 2, "stages");
            Assert(lib.buildings[0].stages[0].tiles.Length == 64, "mechanical tiles");
            Assert(lib.buildings[0].stages[1].tiles.Length == 64, "fire tiles");
            Assert(lib.buildings[0].stages[0].hpAtOrBelow == 75, "mechanical HP");
            Assert(lib.buildings[0].stages[1].hpAtOrBelow == 40, "fire HP");
            Assert(lib.buildings[0].stages[0].damageKind == "mechanical", "mechanical kind");
            Assert(lib.buildings[0].stages[1].damageKind == "fire", "fire kind");
            Assert(lib.buildings[0].stages[0].tiles[0].image.EndsWith(".png"), "PNG path");
            Assert(lib.buildings[0].stages[1].tiles[63].slot == 63, "last slot");
            Assert(config.enabled, "enabled");
            Assert(config.previewEnabled, "preview mode");
            Assert(config.previewHpPercent == 50, "preview HP");
            Assert(!config.previewFire, "preview fire");
            Assert(config.damageDirectory == "DamageAssets", "asset folder");
            Assert(config.bindings.Length == 64, "64 bindings");
            Assert(config.bindings[0].sourceSprite == "tile_buildings1 506", "first original sprite");
            int mapped = 0;
            foreach (var binding in config.bindings)
            {
                if (binding.ownerOffsetX != 0 || binding.ownerOffsetY != 0)
                    mapped++;
            }
            Assert(mapped == 28, "28 out-of-footprint tiles");
            Assert(config.bindings[63].slot >= 0, "last binding");
            bool failed = false;
            try { DamageJsonParser.Library("{\"buildings\": [invalid]}"); }
            catch (FormatException) { failed = true; }
            Assert(failed, "malformed JSON rejected");
            failed = false;
            try { DamageJsonParser.Settings("{\"bindings\": [1]}"); }
            catch (FormatException) { failed = true; }
            Assert(failed, "invalid binding rejected");
            Console.WriteLine("DAMAGE_JSON_CSHARP_ASSERTIONS=" + count);
        }
    }
}
