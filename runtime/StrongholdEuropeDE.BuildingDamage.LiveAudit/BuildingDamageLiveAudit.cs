using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using BepInEx;
using HarmonyLib;
using CrusaderDE;
using SHCDESE.API;

namespace StrongholdEuropeDE.BuildingDamage.LiveAudit
{
    /// <summary>
    /// QA-only, version-locked, observation-only BepInEx probe.
    /// NEVER sets tileImage, changes HP, patches the native game or loads mod art.
    /// Can be enabled only on an isolated QA clone with confirmed assembly hashes.
    /// </summary>
    [BepInPlugin("org.spritesuite.shcde.damage.liveaudit",
                 "SpriteSuite SHCDE Building Damage Read-only QA",
                 "0.1.0")]
    public sealed class BuildingDamageLiveAudit : BaseUnityPlugin
    {
        private const string ApprovedSeSha256 = "__SE_SHA256__";
        private const string ApprovedGameSha256 = "__GAME_SHA256__";
        private const string QaMarker = "SpriteSuite isolated Steam build 24816905 QA clone; originals are read-only.";
        private const int MaximumTileReports = 240;
        private const int MaximumFootprintReports = 80;
        private const int FootprintPollInterval = 300;
        private const int MaximumBuildingScan = 2048;
        private const int MaximumTilesPerBuilding = 4096;

        private Harmony _harmony;
        private int _mainThread;
        private int _frames;
        private int _tileReports;
        private int _footprintReports;
        private int _errorReports;
        private bool _enabled;
        private readonly HashSet<string> _seenTiles = new HashSet<string>(StringComparer.Ordinal);
        private readonly HashSet<string> _seenFootprints = new HashSet<string>(StringComparer.Ordinal);
        private static BuildingDamageLiveAudit _active;

        private static string Hex(byte[] bytes)
        {
            var output = new StringBuilder(bytes.Length * 2);
            foreach (byte b in bytes)
                output.Append(b.ToString("x2", CultureInfo.InvariantCulture));
            return output.ToString();
        }

        private static string FileSha256(string path)
        {
            if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
                throw new InvalidOperationException("Assembly file is unavailable");
            using (FileStream file = File.OpenRead(path))
            using (SHA256 hasher = SHA256.Create())
                return Hex(hasher.ComputeHash(file));
        }

        private void Awake()
        {
            _mainThread = Thread.CurrentThread.ManagedThreadId;
            try
            {
                // The game changes Unity scenes while loading. Keep this
                // QA-only observer alive for the map session, mirroring the
                // existing persistent runtime host. No renderer is modified.
                UnityEngine.Object.DontDestroyOnLoad(gameObject);
                string root = Paths.GameRootPath;
                if (string.IsNullOrWhiteSpace(root))
                    throw new InvalidOperationException("game_root_missing");
                string marker = Path.Combine(root, ".sprite-suite-qa-copy.marker");
                if (!File.Exists(marker) || !string.Equals(
                        File.ReadAllText(marker).Trim(), QaMarker, StringComparison.Ordinal))
                {
                    Logger.LogWarning("SHCDE_DAMAGE_QA|event=start|status=disabled|reason=unmarked_game_root");
                    return;
                }
                string se = FileSha256(Path.Combine(root, "BepInEx", "plugins",
                    "000shcdese", "SHCDESE.dll"));
                string game = FileSha256(Path.Combine(root,
                    "Stronghold Crusader Definitive Edition_Data", "Managed",
                    "Assembly-CSharp.dll"));
                AssemblyName loadedSe = typeof(GameBuildingManagerAPI).Assembly.GetName();
                AssemblyName loadedGame = typeof(SpriteMapping).Assembly.GetName();
                if (loadedSe.Name != "SHCDESE" ||
                    loadedSe.Version.ToString() != "2.14.3.0" ||
                    loadedGame.Name != "Assembly-CSharp")
                    throw new InvalidOperationException("loaded_assembly_identity_mismatch");
                if (!string.Equals(se, ApprovedSeSha256, StringComparison.Ordinal) ||
                    !string.Equals(game, ApprovedGameSha256, StringComparison.Ordinal))
                {
                    Logger.LogWarning("SHCDE_DAMAGE_QA|event=start|status=disabled|reason=assembly_hash_mismatch");
                    return;
                }

                MethodInfo target = typeof(SpriteMapping).GetMethod(
                    "setGenericBuildingTileGraphic",
                    BindingFlags.Instance | BindingFlags.Static |
                    BindingFlags.Public | BindingFlags.NonPublic,
                    null,
                    new Type[] { typeof(GameMapTile), typeof(int), typeof(int), typeof(int) },
                    null);
                MethodInfo postfix = typeof(BuildingDamageLiveAudit).GetMethod(
                    "ObserveTilePostfix",
                    BindingFlags.Static | BindingFlags.NonPublic);
                if (target == null || target.ReturnType != typeof(void) || postfix == null)
                {
                    Logger.LogWarning("SHCDE_DAMAGE_QA|event=start|status=disabled|reason=tile_graphic_abi_mismatch");
                    return;
                }

                _active = this;
                _harmony = new Harmony("org.spritesuite.shcde.damage.liveaudit");
                _harmony.Patch(target, postfix: new HarmonyMethod(postfix));
                _enabled = true;
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=start|status=read_only|se_sha256=" +
                    se + "|game_sha256=" + game + "|renderer_modified=false");
            }
            catch (Exception e)
            {
                _active = null;
                if (_harmony != null)
                {
                    try { _harmony.UnpatchSelf(); } catch (Exception) { }
                }
                _enabled = false;
                Logger.LogError("SHCDE_DAMAGE_QA|event=start|status=disabled|error=" +
                    e.GetType().Name + "|reason=" + Sanitize(e.Message, 96));
            }
        }

        private static void ObserveTilePostfix(GameMapTile tile, int file, int image)
        {
            BuildingDamageLiveAudit app = _active;
            if (app == null || !app._enabled || tile == null ||
                Thread.CurrentThread.ManagedThreadId != app._mainThread ||
                app._tileReports >= MaximumTileReports)
                return;

            try
            {
                GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
                GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                if (tiles == null || buildings == null) return;

                int x = tile.gameMapX, y = tile.gameMapY;
                if (!tiles.IsTileInsideMapBounds(x, y)) return;
                int tileId = tiles.GetTileId(x, y);
                if (tileId < 0 || !tiles.IsValidTileId(tileId)) return;
                int buildingId = tiles.GetTileBuildingId(tileId);
                if (buildingId <= 0 || !buildings.IsValid(buildingId)) return;

                int globalBefore = buildings.GetGlobalId(buildingId);
                if (globalBefore <= 0) return;
                int buildingType = (int)buildings.GetType(buildingId);
                int current = buildings.GetCurrentHealth(buildingId);
                int maximum = buildings.GetMaxHealth(buildingId);
                int fire = buildings.GetOnFireTicks(buildingId);
                if (maximum <= 0 || current < 0 || current > maximum) return;
                if (!buildings.IsValid(buildingId) ||
                    buildings.GetGlobalId(buildingId) != globalBefore ||
                    tiles.GetTileBuildingId(tileId) != buildingId)
                    return;

                string sprite = tile.tileImage == null ? "null" :
                    Sanitize(tile.tileImage.name, 64);
                string key = globalBefore.ToString(CultureInfo.InvariantCulture) +
                    ":" + tileId.ToString(CultureInfo.InvariantCulture) +
                    ":" + file.ToString(CultureInfo.InvariantCulture) +
                    ":" + image.ToString(CultureInfo.InvariantCulture) +
                    ":" + sprite;
                if (!app._seenTiles.Add(key)) return;
                app._tileReports++;
                app.Logger.LogInfo("SHCDE_DAMAGE_QA|event=tile_graphic|building_id=" +
                    buildingId + "|global_id=" + globalBefore + "|type=" + buildingType +
                    "|hp=" + current + "|max_hp=" + maximum + "|fire_ticks=" + fire +
                    "|tile_id=" + tileId + "|x=" + x + "|y=" + y +
                    "|gm=" + file + "|image=" + image + "|sprite=" + sprite +
                    "|renderer_modified=false");
            }
            catch (Exception e)
            {
                app.ReportFailure("tile_graphic", e);
            }
        }

        private static string Sanitize(string input, int maximum)
        {
            if (string.IsNullOrEmpty(input)) return "none";
            input = input.Replace('|', '_').Replace('=', '_')
                .Replace('\r', ' ').Replace('\n', ' ');
            return input.Length <= maximum ? input : input.Substring(0, maximum);
        }

        private void ReportFailure(string context, Exception ex)
        {
            if (++_errorReports <= 5)
                Logger.LogWarning("SHCDE_DAMAGE_QA|event=read_error|context=" +
                    context + "|exception=" + ex.GetType().Name);
        }

        private void Update()
        {
            if (!_enabled || Thread.CurrentThread.ManagedThreadId != _mainThread)
                return;
            _frames++;
            if (_frames % FootprintPollInterval != 0 ||
                _footprintReports >= MaximumFootprintReports)
                return;

            try
            {
                GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
                if (buildings == null || tiles == null) return;
                int[] ids = buildings.GetAllAliveBuildings();
                if (ids == null || ids.Length > MaximumBuildingScan) return;

                int scanned = 0;
                foreach (int id in ids)
                {
                    if (scanned++ > 256 || id <= 0 || !buildings.IsValid(id)) continue;
                    int global = buildings.GetGlobalId(id);
                    if (global <= 0) continue;
                    int type = (int)buildings.GetType(id);
                    int width = buildings.GetOccupyTileGridSize(id);
                    int[] occupied = buildings.GetOccupiedTileIds(id);
                    if (occupied == null || occupied.Length == 0 ||
                        occupied.Length > MaximumTilesPerBuilding ||
                        width < 1 || width > 64) continue;

                    var footprint = new StringBuilder();
                    bool valid = true;
                    for (int j = 0; j < occupied.Length; j++)
                    {
                        int tileId = occupied[j];
                        if (!tiles.IsValidTileId(tileId) ||
                            tiles.GetTileBuildingId(tileId) != id)
                        {
                            valid = false;
                            break;
                        }
                        var xy = tiles.GetTileVectorFromId(tileId);
                        if (tiles.GetTileId(xy.X, xy.Y) != tileId)
                        {
                            valid = false;
                            break;
                        }
                        if (j > 0) footprint.Append(';');
                        footprint.Append(tileId).Append(':')
                            .Append(xy.X).Append(',').Append(xy.Y);
                    }
                    if (!valid || !buildings.IsValid(id) ||
                        buildings.GetGlobalId(id) != global) continue;

                    string key = global + ":" + type + ":" + footprint;
                    if (!_seenFootprints.Add(key)) continue;
                    _footprintReports++;
                    Logger.LogInfo("SHCDE_DAMAGE_QA|event=building_footprint|building_id=" +
                        id + "|global_id=" + global + "|type=" + type +
                        "|grid=" + width + "|tile_count=" + occupied.Length +
                        "|tiles=" + footprint.ToString() +
                        "|renderer_mapping_verified=false|renderer_modified=false");
                    if (_footprintReports >= MaximumFootprintReports) break;
                }
            }
            catch (Exception e)
            {
                ReportFailure("footprint", e);
            }
        }

        private void OnDestroy()
        {
            _enabled = false;
            _active = null;
            if (_harmony != null)
            {
                try { _harmony.UnpatchSelf(); } catch (Exception e) { ReportFailure("unpatch", e); }
                _harmony = null;
            }
            Logger.LogInfo("SHCDE_DAMAGE_QA|event=shutdown|status=unpatched|sprite_writes=0");
        }
    }
}
