using System;
using System.IO;
using System.Text;
using System.Security.Cryptography;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
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
            internal string LastStageId;
            internal SpriteBinding Binding;
            internal int BuildingId;
            internal int GlobalId;
            internal int BuildingType;
            internal int X;
            internal int Y;
        }

        private static BuildingDamageRuntime _active;
        private readonly ManualLogSource _log;
        private readonly Dictionary<string, ObservedTile> _observed =
            new Dictionary<string, ObservedTile>(StringComparer.Ordinal);
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
            if (GameMap.instance != _currentMap)
            {
                _observed.Clear();
                _fire.Clear();
                _currentMap = GameMap.instance;
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
                if (global <= 0) continue;
                int type = (int)buildings.GetType(id);
                if (b.buildingType != 0 && b.buildingType != type) continue;
                if (!HasBuilding(b.buildingGroupId, type)) continue;
                if (!buildings.IsValid(id) || buildings.GetGlobalId(id) != global) continue;
                // A render tile has one owner; different sprite variants of
                // the same tile must update its existing original reference.
                string key = global.ToString(CultureInfo.InvariantCulture) + ":" +
                    x.ToString(CultureInfo.InvariantCulture) + ":" +
                    y.ToString(CultureInfo.InvariantCulture);
                ObservedTile tracked;
                if (!_observed.TryGetValue(key, out tracked))
                {
                    tracked = new ObservedTile();
                    _observed[key] = tracked;
                }
                tracked.Tile = tile;
                tracked.Original = tile.tileImage; // fresh vanilla post-SpriteMapping sprite
                tracked.Applied = null;
                tracked.Binding = b;
                tracked.BuildingId = id;
                tracked.GlobalId = global;
                tracked.BuildingType = type;
                tracked.X = x;
                tracked.Y = y;
                UpdateTile(tracked, buildings);
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
            string artwork = Path.Combine(_artRoot,
                tile.image.Replace('/', Path.DirectorySeparatorChar));
            if (!File.Exists(artwork)) return null;
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

        private void UpdateTile(ObservedTile t, GameBuildingManagerAPI buildings)
        {
            if (t.Tile == null) return;
            if (buildings == null || !buildings.IsValid(t.BuildingId) ||
                buildings.GetGlobalId(t.BuildingId) != t.GlobalId)
            {
                Restore(t);
                _fire.Remove(t.GlobalId);
                return;
            }
            // Do not stomp engine-controlled image changes that happened without
            // the SpriteMapping hook. Only retain our own original/replacement.
            if (t.Applied != null && t.Tile.tileImage != t.Applied &&
                t.Tile.tileImage != t.Original)
            {
                t.Original = t.Tile.tileImage;
                t.Applied = null;
                if (t.Binding.sourceSprite != "*" &&
                    !string.IsNullOrEmpty(t.Binding.sourceSprite) &&
                    t.Original != null && t.Original.name != t.Binding.sourceSprite)
                    return;
            }
            int health = buildings.GetCurrentHealth(t.BuildingId);
            int maximum = buildings.GetMaxHealth(t.BuildingId);
            int fireTicks = buildings.GetOnFireTicks(t.BuildingId);
            if (maximum <= 0 || health < 0) return;
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
                bool previouslyChanged = t.Applied != null;
                Restore(t);
                if (previouslyChanged && t.Applied == null && ++_changeReports <= 400)
                    _log.LogInfo("SPRITESUITE_DAMAGE|event=restored|global_id=" +
                        t.GlobalId + "|building_id=" + t.BuildingId +
                        "|x=" + t.X + "|y=" + t.Y);
                t.LastStageId = null;
            }
            else if (t.Tile.tileImage != replacement)
            {
                _mutating = true;
                try
                {
                    t.Tile.tileImage = replacement;
                    t.Applied = replacement;
                    Refresh(t);
                    t.LastStageId = stage.id;
                    if (++_changeReports <= 400)
                        _log.LogInfo("SPRITESUITE_DAMAGE|event=stage_applied|global_id=" +
                            t.GlobalId + "|building_id=" + t.BuildingId +
                            "|type=" + t.BuildingType + "|x=" + t.X + "|y=" + t.Y +
                            "|stage=" + stage.id + "|kind=" + stage.damageKind +
                            "|slot=" + t.Binding.slot + "|live_hp=" + health +
                            "|live_max=" + maximum + "|live_fire_ticks=" + fireTicks +
                            "|preview=" + _settings.previewEnabled +
                            "|renderer_modified=true");
                }
                finally { _mutating = false; }
            }
        }

        private static void Refresh(ObservedTile t)
        {
            if (t.Tile != null && t.Tile.tilemapRef != null)
                t.Tile.tilemapRef.RefreshTile(new Vector3Int(t.X, t.Y, 0));
        }

        private void Restore(ObservedTile t)
        {
            if (t.Tile == null || t.Original == null || t.Applied == null) return;
            // If the game has replaced the tile since our mod did, do not
            // overwrite the game's new sprite with a stale backup.
            if (t.Tile.tileImage != t.Applied) { t.Applied = null; return; }
            _mutating = true;
            try
            {
                t.Tile.tileImage = t.Original;
                t.Applied = null;
                Refresh(t);
            }
            finally { _mutating = false; }
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
                if (GameMap.instance != _currentMap)
                {
                    // Scene/Map storage was recreated. Do not dereference old
                    // Unity objects after destruction; clear instance history.
                    _observed.Clear();
                    _fire.Clear();
                    _currentMap = GameMap.instance;
                }
                ++_frames;
                if (_frames % 60 == 0)
                    try { ReloadCreativeControls(); }
                    catch (Exception reloadError) { Report("reload_controls", reloadError); }
                if (_frames % Math.Max(1, _settings.pollFrames) != 0) return;
                GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                if (buildings == null) return;
                List<string> remove = new List<string>();
                foreach (KeyValuePair<string, ObservedTile> pair in _observed)
                {
                    ObservedTile t = pair.Value;
                    if (t.Tile == null || !buildings.IsValid(t.BuildingId) ||
                        buildings.GetGlobalId(t.BuildingId) != t.GlobalId)
                    {
                        Restore(t);
                        _fire.Remove(t.GlobalId);
                        remove.Add(pair.Key);
                        continue;
                    }
                    try { UpdateTile(t, buildings); }
                    catch (Exception ex) { Report("update_tile", ex); }
                }
                foreach (string key in remove) _observed.Remove(key);
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
                    bool owned = t.Tile != null && t.Applied != null &&
                        t.Tile.tileImage == t.Applied;
                    Restore(t);
                    if (owned && t.Applied == null && t.Tile != null &&
                        t.Tile.tileImage == t.Original) restored++;
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
