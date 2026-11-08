using System;
using System.IO;
using System.Text;
using System.Security.Cryptography;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using SHCDESE.API;
using UnityEngine;

namespace SpriteSuite.BuildingDamage
{
    [BepInPlugin("org.spritesuite.buildingdamage.live", "SpriteSuite HP + Fire Damage", "0.1.0")]
    public sealed class BuildingDamageHost : BaseUnityPlugin
    {
        private void Awake()
        {
            Logger.LogInfo("SPRITESUITE_DAMAGE|event=host_awake|phase=entered");
            try
            {
                // Resolve the runtime lazily. If a game-side dependency cannot
                // load, this host can still report its exact type/assembly error.
                Type runtime = GetType().Assembly.GetType(
                    "SpriteSuite.BuildingDamage.BuildingDamageRuntime", true);
                MethodInfo start = runtime.GetMethod("Start",
                    BindingFlags.NonPublic | BindingFlags.Static);
                if (start == null)
                    throw new MissingMethodException("BuildingDamageRuntime.Start");
                start.Invoke(null, new object[] { Logger });
                Logger.LogInfo("SPRITESUITE_DAMAGE|event=host_awake|phase=returned");
            }
            catch (Exception error)
            {
                Logger.LogError("SPRITESUITE_DAMAGE|event=host_awake|phase=exception|" + error);
            }
        }
        private void OnDestroy()
        {
            // BepInEx can destroy this GameObject during startup. Keep the
            // C# observer alive through subscribed static application events.
            Logger.LogInfo("SpriteSuite damage host destroyed; runtime remains active");
        }
    }

    [Serializable]
    public sealed class DamageRuntimeSettings
    {
        public string damageArchive = "gebaeudeschaden.zip"; // source bundle for the installer
        public string damageDirectory = "DamageAssets"; // unpacked runtime assets
        public bool enabled = true;
        public bool firePersistsUntilRepaired = true;
        public int pollFrames = 12;
        // Optional visual preview: normal operation always uses real game HP.
        public bool previewEnabled;
        public int previewHpPercent = 50;
        public bool previewFire;
        public SpriteBinding[] bindings = new SpriteBinding[0];
    }

    [Serializable]
    public sealed class SpriteBinding
    {
        public int buildingType;         // 0 matches any type in this group
        public int buildingGlobalId;     // 0 matches every instance
        public string buildingGroupId;  // original Sprite Editor building group
        public string sourceSprite;     // exact vanilla sprite.name; empty/* = any
        public bool matchGmImage;       // alternatively match source GM + image index
        public int gm;
        public int image;
        public int slot;                // matching damage tiles[].slot
        public int ownerOffsetX;        // support extra drawn tiles beyond occupancy
        public int ownerOffsetY;
        public bool overridePivot;
        public float pivotX = 0.5f;
        public float pivotY;
        public bool overridePpu;
        public float pixelsPerUnit = 100;
    }

    [Serializable]
    public sealed class DamageArchive
    {
        public string format;
        public int version;
        public DamageBuilding[] buildings;
    }

    [Serializable]
    public sealed class DamageBuilding
    {
        public string id;
        public string name;
        public int gameBuildingType;
        public DamageStage[] stages;
    }

    [Serializable]
    public sealed class DamageStage
    {
        public string id;
        public string damageKind;
        public int hpAtOrBelow;
        public DamageTile[] tiles;
    }

    [Serializable]
    public sealed class DamageTile
    {
        public int slot;
        public string image;
        public string sha256;
        public string mask; // retained by export; team-color layers are separate
    }

    internal sealed class BuildingDamageRuntime
    {
        private sealed class ObservedTile
        {
            internal GameMapTile Tile;
            internal Sprite Original;
            internal Sprite Applied;
            internal Sprite ReadbackVerified;
            internal SpriteBinding Binding;
            internal int BuildingId;
            internal int GlobalId;
            internal int BuildingType;
            internal int X;
            internal int Y;
        }

        private sealed class TileIdentity : IEqualityComparer<GameMapTile>
        {
            public bool Equals(GameMapTile a, GameMapTile b) { return ReferenceEquals(a, b); }
            public int GetHashCode(GameMapTile tile) { return RuntimeHelpers.GetHashCode(tile); }
        }

        private static BuildingDamageRuntime _active;
        private readonly ManualLogSource _log;
        private readonly Dictionary<GameMapTile, ObservedTile> _observed =
            new Dictionary<GameMapTile, ObservedTile>(new TileIdentity());
        private readonly Dictionary<string, Sprite> _createdSprites =
            new Dictionary<string, Sprite>(StringComparer.Ordinal);
        private readonly List<Texture2D> _createdTextures = new List<Texture2D>();
        private readonly BuildingFireHistory _fire = new BuildingFireHistory();
        private DamageRuntimeSettings _settings;
        private DamageArchive _library;
        private string _artRoot;
        private Harmony _patch;
        private GameMap _currentMap;
        private int _mainThread;
        private int _frames;
        private int _errors;
        private int _changeReports;
        private int _tilemapReports;
        private bool _running;
        private bool _mutating;
        private string _root;
        private string _settingsPath;
        private DateTime _settingsModifiedUtc;
        private int _controlReloadReports;

        private BuildingDamageRuntime(ManualLogSource logger) { _log = logger; }

        internal static void Start(ManualLogSource logger)
        {
            if (_active != null) return;
            BuildingDamageRuntime run = new BuildingDamageRuntime(logger);
            _active = run;
            try { run.Initialize(); }
            catch (Exception e)
            {
                logger.LogError("SpriteSuite runtime startup: " + e);
                run.Stop();
            }
        }

        private void Initialize()
        {
            _mainThread = Thread.CurrentThread.ManagedThreadId;
            string root = Paths.GameRootPath;
            string env = Environment.GetEnvironmentVariable("SPRITESUITE_DAMAGE_MOD_DIR");
            _root = string.IsNullOrWhiteSpace(env) ? Path.Combine(root,
                "BepInEx", "plugins", "SpriteSuiteBuildingDamageRuntime") :
                Path.GetFullPath(env);
            LoadSettingsAndArtwork();
            MethodInfo gameMethod = typeof(SpriteMapping).GetMethod(
                "setGenericBuildingTileGraphic",
                BindingFlags.Public | BindingFlags.NonPublic |
                BindingFlags.Instance | BindingFlags.Static, null,
                new Type[] { typeof(GameMapTile), typeof(int), typeof(int), typeof(int) },
                null);
            MethodInfo after = typeof(BuildingDamageRuntime).GetMethod("OnMappedTile",
                BindingFlags.Static | BindingFlags.NonPublic);
            if (gameMethod == null || after == null)
                throw new InvalidOperationException("SpriteMapping signature unavailable");
            _patch = new Harmony("org.spritesuite.buildingdamage.live");
            _patch.Patch(gameMethod, postfix: new HarmonyMethod(after));
            // The engine can replace map layers while retaining the GameMap
            // component. Observe that explicit boundary when the ABI exposes it.
            MethodInfo mapLoaded = typeof(GameMap).GetMethod("newMapLoaded",
                BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance,
                null, new Type[] { typeof(int) }, null);
            if (mapLoaded != null && mapLoaded.ReturnType == typeof(void))
            {
                MethodInfo before = typeof(BuildingDamageRuntime).GetMethod("OnMapLoaded",
                    BindingFlags.Static | BindingFlags.NonPublic);
                _patch.Patch(mapLoaded, prefix: new HarmonyMethod(before));
            }
            Application.onBeforeRender += OnBeforeRender;
            Application.quitting += OnQuit;
            _running = true;
            _log.LogInfo("SpriteSuite HP/Fire active: " + _library.buildings.Length +
                " building profiles; " + _settings.bindings.Length + " sprite bindings");
        }

        private void LoadSettingsAndArtwork()
        {
            string settingsPath = Path.Combine(_root, "runtime.json");
            _settingsPath = settingsPath;
            if (!File.Exists(settingsPath))
                throw new FileNotFoundException("Create runtime.json with archive and sprite bindings", settingsPath);
            DamageRuntimeSettings config = DamageJsonParser.Settings(
                File.ReadAllText(settingsPath, Encoding.UTF8));
            if (config == null) throw new InvalidDataException("Invalid runtime.json");
            if (config.bindings == null) config.bindings = new SpriteBinding[0];
            // The suite's installer expands the ordinary Sprite Editor ZIP.
            // Mono in this SHCDE build does not ship System.IO.Compression;
            // loading files directly avoids copying a foreign Framework DLL.
            string directory = string.IsNullOrWhiteSpace(config.damageDirectory) ?
                "DamageAssets" : config.damageDirectory;
            if (!Path.IsPathRooted(directory))
                directory = Path.Combine(_root, directory);
            directory = Path.GetFullPath(directory);
            string manifestPath = Path.Combine(directory, "damage-manifest.json");
            if (!File.Exists(manifestPath) && !config.enabled && config.bindings.Length == 0)
            {
                _settings = config;
                _settingsModifiedUtc = File.GetLastWriteTimeUtc(settingsPath);
                _library = new DamageArchive {
                    format = "stronghold-building-damage-library",
                    version = 1, buildings = new DamageBuilding[0]
                };
                _artRoot = directory;
                _log.LogInfo("SPRITESUITE_DAMAGE|event=disabled_unconfigured|reason=no_artwork");
                return;
            }
            string json = File.ReadAllText(manifestPath, Encoding.UTF8);
            DamageArchive library = DamageJsonParser.Library(json);
            if (library == null || library.buildings == null)
                throw new InvalidDataException("Invalid building damage library");
            // No approval, game-build or version whitelist. User-authored
            // stages and arbitrary target directories remain valid.
            _settings = config;
            _settingsModifiedUtc = File.GetLastWriteTimeUtc(settingsPath);
            _library = library;
            _artRoot = directory;
        }

        private static void OnMappedTile(GameMapTile tile, int file, int image)
        {
            BuildingDamageRuntime run = _active;
            if (run == null || !run._running || run._mutating || tile == null ||
                Thread.CurrentThread.ManagedThreadId != run._mainThread)
                return;
            try { run.TrackAndApply(tile, file, image); }
            catch (Exception ex) { run.Report("sprite_mapping", ex); }
        }

        private void TrackAndApply(GameMapTile tile, int file, int image)
        {
            ResetForMapChange();
            ObservedTile previous;
            if (_observed.TryGetValue(tile, out previous))
            {
                _observed.Remove(tile);
                // A redraw may keep our replacement or supply a new original.
                // Remove ownership before matching the new mapping either way.
                Restore(previous);
            }
            if (tile.tileImage == null) return;
            GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
            GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
            if (buildings == null || tiles == null) return;
            int x = tile.gameMapX, y = tile.gameMapY;
            string source = tile.tileImage.name;
            for (int i = 0; i < _settings.bindings.Length; ++i)
            {
                SpriteBinding b = _settings.bindings[i];
                if (b == null) continue;
                if (!string.IsNullOrEmpty(b.sourceSprite) && b.sourceSprite != "*" &&
                    b.sourceSprite != source) continue;
                if (b.matchGmImage && (b.gm != file || b.image != image)) continue;
                int ownerX = x + b.ownerOffsetX, ownerY = y + b.ownerOffsetY;
                if (!tiles.IsTileInsideMapBounds(ownerX, ownerY)) continue;
                int tileId = tiles.GetTileId(ownerX, ownerY);
                if (!tiles.IsValidTileId(tileId)) continue;
                int id = tiles.GetTileBuildingId(tileId);
                if (id <= 0 || !buildings.IsValid(id)) continue;
                int global = buildings.GetGlobalId(id);
                if (global <= 0 || (b.buildingGlobalId != 0 &&
                    b.buildingGlobalId != global)) continue;
                int type = (int)buildings.GetType(id);
                if (b.buildingType != 0 && b.buildingType != type) continue;
                if (!HasBuilding(b.buildingGroupId, type)) continue;
                if (!buildings.IsValid(id) || buildings.GetGlobalId(id) != global) continue;
                // Distinct rendering layers can have the same coordinates.
                // Track the tile object that owns the actual sprite reference.
                var tracked = new ObservedTile {
                    Tile = tile, Original = tile.tileImage, Binding = b,
                    BuildingId = id, GlobalId = global, BuildingType = type,
                    X = x, Y = y
                };
                _observed[tile] = tracked;
                if (!UpdateTile(tracked, buildings)) _observed.Remove(tile);
                break;
            }
        }

        private bool HasBuilding(string group, int type)
        {
            foreach (DamageBuilding building in _library.buildings)
                if (building != null && (building.id == group ||
                    (string.IsNullOrEmpty(group) && building.gameBuildingType == type)))
                    return true;
            return false;
        }

        private DamageBuilding FindBuilding(SpriteBinding binding, int type)
        {
            foreach (DamageBuilding building in _library.buildings)
                if (building != null && ((binding.buildingGroupId == building.id) ||
                    (string.IsNullOrEmpty(binding.buildingGroupId) &&
                     building.gameBuildingType == type)))
                    return building;
            return null;
        }

        private DamageStage Select(DamageBuilding building, int current,
            int maximum, bool fired)
        {
            if (building == null || building.stages == null) return null;
            var values = new List<StageDefinition>();
            foreach (DamageStage entry in building.stages)
                if (entry != null)
                    values.Add(new StageDefinition { Id = entry.id, Kind = entry.damageKind,
                        Threshold = entry.hpAtOrBelow });
            string id = BuildingDamageStageLogic.Choose(values, current, maximum, fired);
            if (id == null) return null;
            foreach (DamageStage stage in building.stages)
                if (stage != null && stage.id == id) return stage;
            return null;
        }

        private Sprite FindReplacement(DamageStage stage, int slot, Sprite original,
            SpriteBinding binding)
        {
            if (stage == null || stage.tiles == null || original == null) return null;
            DamageTile tile = null;
            foreach (DamageTile candidate in stage.tiles)
                if (candidate != null && candidate.slot == slot) { tile = candidate; break; }
            if (tile == null || string.IsNullOrEmpty(tile.image)) return null;
            Vector2 pivot = new Vector2(original.pivot.x / original.rect.width,
                original.pivot.y / original.rect.height);
            float ppu = original.pixelsPerUnit;
            if (binding.overridePivot) pivot = new Vector2(binding.pivotX, binding.pivotY);
            if (binding.overridePpu && binding.pixelsPerUnit > 0) ppu = binding.pixelsPerUnit;
            string key = stage.id + ":" + tile.image + ":" +
                pivot.x.ToString("R", CultureInfo.InvariantCulture) + ":" +
                pivot.y.ToString("R", CultureInfo.InvariantCulture) + ":" +
                ppu.ToString("R", CultureInfo.InvariantCulture);
            Sprite sprite;
            if (_createdSprites.TryGetValue(key, out sprite)) return sprite;
            string relativeImage = tile.image.Replace('/', Path.DirectorySeparatorChar);
            if (Path.IsPathRooted(relativeImage)) return null;
            string artwork = Path.GetFullPath(Path.Combine(_artRoot, relativeImage));
            string root = Path.GetFullPath(_artRoot).TrimEnd(
                Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                + Path.DirectorySeparatorChar;
            if (!artwork.StartsWith(root, StringComparison.OrdinalIgnoreCase) ||
                !File.Exists(artwork)) return null;
            byte[] bytes = File.ReadAllBytes(artwork);
            if (!string.IsNullOrEmpty(tile.sha256))
            {
                using (SHA256 hasher = SHA256.Create())
                {
                    byte[] hash = hasher.ComputeHash(bytes);
                    StringBuilder hex = new StringBuilder(hash.Length * 2);
                    foreach (byte b in hash) hex.Append(b.ToString("x2"));
                    if (!string.Equals(hex.ToString(), tile.sha256,
                        StringComparison.OrdinalIgnoreCase))
                    {
                        Report("sprite_hash", new InvalidDataException(tile.image));
                        return null;
                    }
                }
            }
            Texture2D texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            if (!ImageConversion.LoadImage(texture, bytes, false))
            {
                UnityEngine.Object.Destroy(texture);
                return null;
            }
            texture.filterMode = FilterMode.Point;
            texture.wrapMode = TextureWrapMode.Clamp;
            sprite = Sprite.Create(texture,
                new Rect(0, 0, texture.width, texture.height), pivot, ppu);
            sprite.name = "SpriteSuite:" + stage.id + ":" + tile.slot;
            _createdSprites[key] = sprite;
            _createdTextures.Add(texture);
            return sprite;
        }

        private bool UpdateTile(ObservedTile t, GameBuildingManagerAPI buildings)
        {
            if (t.Tile == null) return false;
            if (!buildings.IsValid(t.BuildingId) ||
                buildings.GetGlobalId(t.BuildingId) != t.GlobalId ||
                (int)buildings.GetType(t.BuildingId) != t.BuildingType)
            {
                Restore(t);
                _fire.Remove(t.GlobalId);
                return false;
            }
            // A write outside SpriteMapping invalidates the source match.
            // Wait for a new mapping before applying artwork to this tile.
            if (t.Tile.tileImage != t.Original &&
                (t.Applied == null || t.Tile.tileImage != t.Applied)) return false;
            int health = buildings.GetCurrentHealth(t.BuildingId);
            int maximum = buildings.GetMaxHealth(t.BuildingId);
            int fireTicks = buildings.GetOnFireTicks(t.BuildingId);
            if (maximum <= 0 || health < 0)
            {
                Restore(t);
                return true;
            }
            bool fire = _settings.firePersistsUntilRepaired ?
                _fire.Update(t.GlobalId, health, maximum, fireTicks) : fireTicks > 0;
            // A voluntary preview does not modify the real game's HP or fire.
            int stageHp = _settings.previewEnabled ?
                Math.Max(0, Math.Min(100, _settings.previewHpPercent)) : health;
            int stageMax = _settings.previewEnabled ? 100 : maximum;
            bool stageFire = _settings.previewEnabled ? _settings.previewFire : fire;
            DamageBuilding building = FindBuilding(t.Binding, t.BuildingType);
            DamageStage stage = Select(building, stageHp, stageMax, stageFire);
            Sprite replacement = _settings.enabled ?
                FindReplacement(stage, t.Binding.slot, t.Original, t.Binding) : null;
            if (replacement == null)
            {
                if (Restore(t) && ++_changeReports <= 400)
                    _log.LogInfo("SPRITESUITE_DAMAGE|event=restored|global_id=" +
                        t.GlobalId + "|building_id=" + t.BuildingId +
                        "|x=" + t.X + "|y=" + t.Y + "|live_hp=" + health +
                        "|live_max=" + maximum + "|live_fire_ticks=" + fireTicks +
                        "|preview=" + _settings.previewEnabled);
            }
            else if (t.Tile.tileImage != replacement)
            {
                _mutating = true;
                try
                {
                    t.Tile.tileImage = replacement;
                    t.Applied = replacement;
                    t.ReadbackVerified = null;
                    Refresh(t);
                    if (++_changeReports <= 400)
                        _log.LogInfo("SPRITESUITE_DAMAGE|event=stage_applied|global_id=" +
                            t.GlobalId + "|building_id=" + t.BuildingId +
                            "|type=" + t.BuildingType + "|x=" + t.X + "|y=" + t.Y +
                            "|stage=" + stage.id + "|kind=" + stage.damageKind +
                            "|slot=" + t.Binding.slot + "|live_hp=" + health +
                            "|live_max=" + maximum + "|live_fire_ticks=" + fireTicks +
                            "|preview=" + _settings.previewEnabled +
                            "|sprite_field_written=true|renderer_modified=false");
                }
                finally { _mutating = false; }
            }
            // A field assignment is not evidence of a displayed sprite.
            // Native Tilemap readback can occur on a later frame, and this
            // does not claim that pixels were visually inspected.
            if (t.Applied != null && t.ReadbackVerified != t.Applied &&
                TilemapReadbackMatches(t, t.Applied))
            {
                t.ReadbackVerified = t.Applied;
                if (++_tilemapReports <= 400)
                    _log.LogInfo("SPRITESUITE_DAMAGE|event=stage_tilemap_verified|global_id=" +
                        t.GlobalId + "|building_id=" + t.BuildingId +
                        "|x=" + t.X + "|y=" + t.Y +
                        "|stage=" + (stage == null ? "none" : stage.id) +
                        "|live_hp=" + health + "|live_max=" + maximum +
                        "|live_fire_ticks=" + fireTicks +
                        "|preview=" + _settings.previewEnabled +
                        "|tilemap_readback_matches=true|renderer_modified=true");
            }
            return true;
        }

        private static bool TilemapReadbackMatches(ObservedTile tile, Sprite target)
        {
            if (tile.Tile == null || tile.Tile.tilemapRef == null || target == null)
                return false;
            try
            {
                return tile.Tile.tilemapRef.GetSprite(new Vector3Int(tile.X, tile.Y, 0)) == target;
            }
            catch (Exception) { return false; }
        }

        private static void Refresh(ObservedTile t)
        {
            if (t.Tile != null && t.Tile.tilemapRef != null)
                t.Tile.tilemapRef.RefreshTile(new Vector3Int(t.X, t.Y, 0));
        }

        private bool Restore(ObservedTile t)
        {
            if (t.Tile == null || t.Original == null || t.Applied == null) return false;
            // If the game has replaced the tile since our mod did, do not
            // overwrite the game's new sprite with a stale backup.
            if (t.Tile.tileImage != t.Applied) { t.Applied = null; return false; }
            _mutating = true;
            try
            {
                t.Tile.tileImage = t.Original;
                t.Applied = null;
                t.ReadbackVerified = null;
                Refresh(t);
                return t.Tile.tileImage == t.Original;
            }
            finally { _mutating = false; }
        }

        private static void OnMapLoaded(GameMap __instance)
        {
            BuildingDamageRuntime run = _active;
            if (run == null || !run._running || Thread.CurrentThread.ManagedThreadId != run._mainThread)
                return;
            run.ResetMap(__instance, "new_map_loaded");
        }

        private void ResetForMapChange()
        {
            if (GameMap.instance != _currentMap) ResetMap(GameMap.instance, "map_instance_changed");
        }

        private void ResetMap(GameMap current, string reason)
        {
            int restored = 0;
            foreach (ObservedTile tile in _observed.Values)
                try { if (Restore(tile)) restored++; }
                catch (Exception ex) { Report("restore_previous_map", ex); }
            int tracked = _observed.Count;
            _observed.Clear();
            _fire.Clear();
            _currentMap = current;
            if (tracked > 0)
                _log.LogInfo("SPRITESUITE_DAMAGE|event=map_reset|reason=" + reason +
                    "|tracked=" + tracked + "|restored=" + restored);
        }

        private void ReloadCreativeControls()
        {
            if (string.IsNullOrEmpty(_settingsPath) || !File.Exists(_settingsPath))
                return;
            DateTime modified = File.GetLastWriteTimeUtc(_settingsPath);
            if (modified == _settingsModifiedUtc) return;
            // Any creator can edit the existing runtime.json while the game
            // runs. Changes to HP/Fire preview and enabled status take effect
            // without restarting, and no gameplay values are written.
            DamageRuntimeSettings incoming = DamageJsonParser.Settings(
                File.ReadAllText(_settingsPath, Encoding.UTF8));
            _settings.enabled = incoming.enabled;
            _settings.previewEnabled = incoming.previewEnabled;
            _settings.previewHpPercent = incoming.previewHpPercent;
            _settings.previewFire = incoming.previewFire;
            _settings.pollFrames = incoming.pollFrames;
            _settings.firePersistsUntilRepaired = incoming.firePersistsUntilRepaired;
            _settingsModifiedUtc = modified;
            if (++_controlReloadReports <= 100)
                _log.LogInfo("SPRITESUITE_DAMAGE|event=controls_reloaded|enabled=" +
                    _settings.enabled + "|preview=" + _settings.previewEnabled +
                    "|hp=" + _settings.previewHpPercent +
                    "|fire=" + _settings.previewFire);
        }

        private void OnBeforeRender()
        {
            if (!_running || Thread.CurrentThread.ManagedThreadId != _mainThread) return;
            try
            {
                try
                {
                    if (Input.GetKeyDown(KeyCode.F9))
                    {
                        _settings.enabled = !_settings.enabled;
                        _log.LogInfo("SpriteSuite damage rendering enabled=" + _settings.enabled);
                    }
                }
                catch (Exception) { /* Legacy Input may be unavailable; rendering still runs. */ }
                ResetForMapChange();
                ++_frames;
                if (_frames % 60 == 0)
                    try { ReloadCreativeControls(); }
                    catch (Exception reloadError) { Report("reload_controls", reloadError); }
                if (_frames % Math.Max(1, _settings.pollFrames) != 0) return;
                GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                if (buildings == null) return;
                List<GameMapTile> remove = new List<GameMapTile>();
                foreach (KeyValuePair<GameMapTile, ObservedTile> pair in _observed)
                {
                    try
                    {
                        if (!UpdateTile(pair.Value, buildings)) remove.Add(pair.Key);
                    }
                    catch (Exception ex) { Report("update_tile", ex); }
                }
                foreach (GameMapTile key in remove) _observed.Remove(key);
            }
            catch (Exception ex) { Report("render_poll", ex); }
        }

        private void OnQuit() { Stop(); }

        private void Report(string action, Exception ex)
        {
            // Log events are bounded; the renderer has no stage-count limit.
            if (++_errors <= 30) _log.LogWarning(action + ": " + ex);
        }

        private void Stop()
        {
            _running = false;
            try { Application.onBeforeRender -= OnBeforeRender; } catch (Exception) { }
            try { Application.quitting -= OnQuit; } catch (Exception) { }
            if (_patch != null)
                try { _patch.UnpatchSelf(); } catch (Exception ex) { Report("unpatch", ex); }
            _patch = null;
            int restored = 0;
            int previous = 0;
            foreach (ObservedTile t in _observed.Values)
            {
                try
                {
                    if (t.Applied != null) previous++;
                    if (Restore(t)) restored++;
                }
                catch (Exception ex) { Report("restore", ex); }
            }
            _log.LogInfo("SPRITESUITE_DAMAGE|event=shutdown|previous_modified=" +
                previous + "|original_restored=" + restored);
            _observed.Clear();
            _fire.Clear();
            foreach (Sprite sprite in _createdSprites.Values)
                if (sprite != null) UnityEngine.Object.Destroy(sprite);
            foreach (Texture2D texture in _createdTextures)
                if (texture != null) UnityEngine.Object.Destroy(texture);
            _createdSprites.Clear();
            _createdTextures.Clear();
            _artRoot = null;
            if (ReferenceEquals(_active, this)) _active = null;
        }
    }
}
