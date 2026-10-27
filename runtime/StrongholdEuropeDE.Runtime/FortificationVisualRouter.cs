using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using CrusaderDE;
using SHCDESE.API;
using UnityEngine;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Applies the recipe catalogue to wall tiles that carry a variant.
    ///
    /// Measured 2026-09-02 (SHCDE 2.80, editor, complete per-tile map): the
    /// wall itself is the raised walkway tile — a GM 12 tile image (97–104)
    /// at ground + 2.813 (low wall + 1.875) whose faces are tile_walls
    /// chevrons. Walls along +x or +y consist of nothing else. Screen-
    /// horizontal walls (+x/-y, corner-touching tiles) add one 64×199
    /// anim_castle strip (49–62) on the front gap tile and the cap 47 on the
    /// back gap tile through GameMap.addUpdateWallFillin; screen-vertical
    /// walls (+x/+y) add the rim pieces 46/48 on the flank tiles.
    ///
    /// The router only works through those calls: prefix/postfix on the
    /// fill-in (adjust, hide or add layer sprites with private object ids,
    /// see <see cref="LayerIdBase"/>), a postfix on the tile image (swap the
    /// walkway tile for a whole wall piece, move the tile, add layers) and a
    /// postfix on the chevron. Tile frames are placed at the grid cell centre
    /// exactly like the game places its own tile images. No grid is written
    /// and no pixel is generated.
    /// </summary>
    internal sealed class FortificationVisualRouter
    {
        internal const int WallFillinGm = 54;
        internal const int WalkwayTileGm = 12;
        internal const int ChevronGm = 10;
        /// <summary>
        /// Engine fill-in ids are tilemap x + y * 800 (&lt; 640000); pool ids
        /// add 0x20000000. Layer ids live far above the engine range and
        /// below the pool offset: base + tileId * 8 + slot (fill-in layers use
        /// slots 0–3, tile layers slots 4–7).
        /// </summary>
        internal const int LayerIdBase = 0x01000000;
        internal const int LayerSlots = 8;
        internal const int TileLayerSlotBase = 4;
        /// <summary>WallGFXGrid values of raised wall tiles carry high flags; gap tiles stay small.</summary>
        internal const int WallTileFlag = 0x10000;
        internal const string WoodenStairsVariantId = "wooden_stairs";
        internal const int StairRunLimit = 16;
        private const float HiddenDropUnits = 256f;
        private const float RaisedTileMinimumHeight = 1.0f;
        private const int MaximumMeasurementLines = 800;
        private const int MaximumReportLines = 96;
        private const float PixelsPerHeightUnit = 32f;

        private readonly FortificationSpriteCatalog _catalog;
        private readonly Action<string> _info;
        private readonly Dictionary<int, string> _tiles = new Dictionary<int, string>();
        private readonly Dictionary<int, int> _fillinLayerCounts = new Dictionary<int, int>();
        private readonly Dictionary<int, int> _tileLayerCounts = new Dictionary<int, int>();
        private readonly HashSet<long> _measuredFillins = new HashSet<long>();
        private readonly HashSet<long> _measuredTiles = new HashSet<long>();
        private readonly HashSet<long> _reported = new HashSet<long>();
        private FieldInfo _wallFillinsField;
        private bool _wallFillinsFieldResolved;
        private bool _reentrant;
        private int _measurementLines;
        private int _reportLines;
        private int _routerFailures;
        private int _fillinCalls;
        private PendingFillin _pending;

        private struct PendingFillin
        {
            internal bool Valid;
            internal int ObjectId;
            internal int TileId;
            internal string VariantId;
            internal FortificationSpriteRecipe Recipe;
            internal float OriginalHeight;
            internal int OriginalImage;
            internal int OriginalXOffset;
        }

        internal FortificationVisualRouter(
            FortificationSpriteCatalog catalog,
            Action<string> info = null)
        {
            _catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
            _info = info;
        }

        internal int TrackedTileCount => _tiles.Count;

        internal int LayerCount
        {
            get
            {
                int total = 0;
                foreach (int count in _fillinLayerCounts.Values)
                {
                    total += count;
                }
                foreach (int count in _tileLayerCounts.Values)
                {
                    total += count;
                }
                return total;
            }
        }

        internal void ApplyTile(int tileId, FortificationVariantDefinition variant)
        {
            if (variant == null || !FortificationStateStore.IsValidTileId(tileId))
            {
                return;
            }
            _tiles[tileId] = variant.Id;
            if (!_catalog.HasRecipes(variant.Id))
            {
                Report(variant.Id, 0, tileId, "missing_recipe");
            }
        }

        internal void Sync(IReadOnlyList<FortificationTileState> tiles)
        {
            var keep = new HashSet<int>();
            if (tiles != null)
            {
                foreach (FortificationTileState tile in tiles)
                {
                    if (tile == null || !FortificationStateStore.IsValidTileId(tile.TileId))
                    {
                        continue;
                    }
                    keep.Add(tile.TileId);
                    _tiles[tile.TileId] = tile.VariantId;
                }
            }
            var stale = new List<int>();
            foreach (int tileId in _tiles.Keys)
            {
                if (!keep.Contains(tileId))
                {
                    stale.Add(tileId);
                }
            }
            foreach (int tileId in stale)
            {
                _tiles.Remove(tileId);
                DeleteLayers(tileId);
            }
        }

        internal void ClearTiles()
        {
            DeleteAllLayers();
            _tiles.Clear();
            _pending = default(PendingFillin);
        }

        internal void RollbackOwned()
        {
            ClearTiles();
            _measuredFillins.Clear();
            _measuredTiles.Clear();
            _reported.Clear();
            _measurementLines = 0;
            _reportLines = 0;
            _routerFailures = 0;
            _fillinCalls = 0;
        }

        /// <summary>Prefix of GameMap.addUpdateWallFillin (x, y in tilemap = game coordinates).</summary>
        internal void OnWallFillinPrefix(
            int objectId,
            int x,
            int y,
            ref float heightAboveGround,
            ref int image,
            ref int xoffset)
        {
            _pending = default(PendingFillin);
            if (_reentrant)
            {
                return;
            }
            try
            {
                GameMap map = GameMap.instance;
                GameTileManagerAPI api = GameTileManagerAPI.Instance;
                if (map == null || api == null)
                {
                    return;
                }
                GameMapTile tile = map.getMapTile(x, y);
                if (tile == null)
                {
                    return;
                }
                int tileId = api.GetTileId(tile.gameMapX, tile.gameMapY);
                if (!FortificationStateStore.IsValidTileId(tileId))
                {
                    return;
                }
                _fillinCalls++;
                Measure(api, tile, tileId, heightAboveGround, image, xoffset);
                string variantId;
                if (!_tiles.TryGetValue(tileId, out variantId))
                {
                    return;
                }
                FortificationSpriteRecipe recipe;
                if (!_catalog.TryGetRecipe(variantId, WallFillinGm, image, 0, out recipe))
                {
                    return;
                }
                _pending = new PendingFillin
                {
                    Valid = true,
                    ObjectId = objectId,
                    TileId = tileId,
                    VariantId = variantId,
                    Recipe = recipe,
                    OriginalHeight = heightAboveGround,
                    OriginalImage = image,
                    OriginalXOffset = xoffset,
                };
                if (recipe.Hidden)
                {
                    // Out of view; rows in front never reach that far down.
                    heightAboveGround -= HiddenDropUnits;
                    return;
                }
                FortificationSpriteRule body = recipe.Body;
                if (body != null)
                {
                    heightAboveGround += body.Dy / PixelsPerHeightUnit;
                    xoffset += body.Dx;
                    if (body.TargetGm == WallFillinGm)
                    {
                        image = body.TargetImage;
                    }
                }
            }
            catch (Exception exception)
            {
                _pending = default(PendingFillin);
                RecordFailure(exception);
            }
        }

        /// <summary>Postfix of GameMap.addUpdateWallFillin: sprite swap and layers.</summary>
        internal void OnWallFillinPostfix(int objectId, int x, int y)
        {
            if (_reentrant || !_pending.Valid || _pending.ObjectId != objectId)
            {
                return;
            }
            PendingFillin pending = _pending;
            _pending = default(PendingFillin);
            try
            {
                GameMap map = GameMap.instance;
                if (map == null)
                {
                    return;
                }
                if (pending.Recipe.Hidden)
                {
                    Report(pending.VariantId, pending.OriginalImage, pending.TileId, "hidden");
                    return;
                }
                WallFillin body = FindFillin(map, objectId);
                if (body == null || body.sprRenderer == null)
                {
                    Report(pending.VariantId, pending.OriginalImage, pending.TileId, "body_unavailable");
                    return;
                }
                Vector3 cell = CellCentre(x, y);
                FortificationSpriteRule bodyRule = pending.Recipe.Body;
                if (bodyRule != null && bodyRule.TargetGm != 0 && bodyRule.TargetGm != WallFillinGm)
                {
                    Vector3 at = cell + new Vector3(
                        (pending.OriginalXOffset + bodyRule.Dx) / PixelsPerHeightUnit,
                        pending.OriginalHeight + bodyRule.Dy / PixelsPerHeightUnit,
                        0f);
                    if (!PlaceTileFrame(body, bodyRule.TargetGm, bodyRule.TargetImage, at))
                    {
                        Report(pending.VariantId, pending.OriginalImage, pending.TileId, "target_unavailable");
                    }
                }
                int baseOrder = body.sprRenderer.sortingOrder;
                int slot = 0;
                foreach (FortificationSpriteRule layer in pending.Recipe.Layers)
                {
                    int layerId = LayerId(pending.TileId, slot);
                    slot++;
                    int layerImage = layer.TargetGm == WallFillinGm ? layer.TargetImage : pending.OriginalImage;
                    float layerHeight = pending.OriginalHeight + layer.Dy / PixelsPerHeightUnit;
                    WallFillin created = AddOwnFillin(
                        map, layerId, x, y, layerHeight, layerImage, pending.OriginalXOffset + layer.Dx);
                    if (created == null)
                    {
                        Report(pending.VariantId, pending.OriginalImage, pending.TileId, "layer_unavailable");
                        continue;
                    }
                    created.sprRenderer.sortingOrder = baseOrder + layer.Order;
                    if (layer.TargetGm != 0 && layer.TargetGm != WallFillinGm)
                    {
                        Vector3 at = cell + new Vector3(
                            (pending.OriginalXOffset + layer.Dx) / PixelsPerHeightUnit,
                            layerHeight,
                            0f);
                        if (!PlaceTileFrame(created, layer.TargetGm, layer.TargetImage, at))
                        {
                            Report(pending.VariantId, pending.OriginalImage, pending.TileId, "target_unavailable");
                        }
                    }
                }
                TrimLayers(map, _fillinLayerCounts, pending.TileId, 0, slot);
                Report(pending.VariantId, pending.OriginalImage, pending.TileId, "applied");
            }
            catch (Exception exception)
            {
                RecordFailure(exception);
            }
        }

        /// <summary>Prefix of GameMap.deleteWallFillin(int): drop the layers with the tile.</summary>
        internal void OnWallFillinDeletePrefix(int objectId)
        {
            if (_reentrant || objectId < 0 || objectId >= LayerIdBase || _fillinLayerCounts.Count == 0)
            {
                return;
            }
            try
            {
                GameMap map = GameMap.instance;
                GameTileManagerAPI api = GameTileManagerAPI.Instance;
                if (map == null || api == null)
                {
                    return;
                }
                GameMapTile tile = map.getMapTile(objectId % 800, objectId / 800);
                if (tile == null)
                {
                    return;
                }
                int tileId = api.GetTileId(tile.gameMapX, tile.gameMapY);
                if (FortificationStateStore.IsValidTileId(tileId))
                {
                    TrimLayers(map, _fillinLayerCounts, tileId, 0, 0);
                }
            }
            catch (Exception exception)
            {
                RecordFailure(exception);
            }
        }

        /// <summary>
        /// Postfix of SpriteMapping.setGenericBuildingTileGraphic. For a raised
        /// walkway tile of a variant wall: the tile image becomes a whole wall
        /// piece chosen by the wall direction, the tile is moved (usually down
        /// to the ground, which also removes the chevrons), and layer sprites
        /// (walkway planks) are placed at the cell. The engine re-sends the
        /// tile on every change and resets the height first, so everything
        /// is re-applied before the Tilemap refresh that follows the call.
        /// </summary>
        internal void OnTileGraphic(GameMapTile tile, int file, int image)
        {
            if (tile == null)
            {
                return;
            }
            try
            {
                GameTileManagerAPI api = GameTileManagerAPI.Instance;
                GameMap map = GameMap.instance;
                if (api == null || map == null)
                {
                    return;
                }
                int x = tile.gameMapX;
                int y = tile.gameMapY;
                int tileId = api.GetTileId(x, y);
                if (!FortificationStateStore.IsValidTileId(tileId))
                {
                    return;
                }
                string variantId;
                bool tracked = _tiles.TryGetValue(tileId, out variantId);
                int shape = 0;
                if (tracked)
                {
                    shape = variantId == WoodenStairsVariantId
                        ? ClassifyStairShape(api, x, y)
                        : ClassifyShape(api, x, y);
                }
                MeasureTile(api, tile, tileId, file, image, tracked, shape);
                if (!tracked)
                {
                    return;
                }
                if (tile.height < RaisedTileMinimumHeight)
                {
                    // Ground tile, construction marker or removed wall: keep the
                    // engine image (2026-09-02: gameplay showed moss/black
                    // tiles on unbuilt wall sites) and drop own layers.
                    TrimLayers(map, _tileLayerCounts, tileId, TileLayerSlotBase, 0);
                    return;
                }
                FortificationSpriteRecipe recipe;
                if (!_catalog.TryGetRecipe(variantId, file, image, shape, out recipe))
                {
                    return;
                }
                float ground = tile.height;
                FortificationSpriteRule body = recipe.Body;
                if (body != null)
                {
                    if (body.TargetGm != 0)
                    {
                        Sprite sprite = LoadSprite(body.TargetGm, body.TargetImage);
                        if (sprite == null)
                        {
                            Report(variantId, image, tileId, "tile_target_unavailable");
                            return;
                        }
                        tile.tileImage = sprite;
                    }
                    if (body.Dy != 0)
                    {
                        tile.height += body.Dy / PixelsPerHeightUnit;
                        tile.chevronChanged = true;
                    }
                    ground = tile.height;
                }
                int slot = 0;
                if (recipe.Layers.Count > 0)
                {
                    Vector3 cell = CellCentre(x, y);
                    foreach (FortificationSpriteRule layer in recipe.Layers)
                    {
                        int layerId = LayerId(tileId, TileLayerSlotBase + slot);
                        slot++;
                        int placeholder = layer.TargetGm == WallFillinGm ? layer.TargetImage : 47;
                        WallFillin created = AddOwnFillin(
                            map, layerId, x, y, ground + layer.Dy / PixelsPerHeightUnit, placeholder, layer.Dx);
                        if (created == null)
                        {
                            Report(variantId, image, tileId, "tile_layer_unavailable");
                            continue;
                        }
                        created.sprRenderer.sortingOrder += layer.Order;
                        if (layer.TargetGm != 0 && layer.TargetGm != WallFillinGm)
                        {
                            Vector3 at = cell + new Vector3(
                                layer.Dx / PixelsPerHeightUnit,
                                ground + layer.Dy / PixelsPerHeightUnit,
                                0f);
                            if (!PlaceTileFrame(created, layer.TargetGm, layer.TargetImage, at))
                            {
                                Report(variantId, image, tileId, "target_unavailable");
                            }
                        }
                    }
                }
                TrimLayers(map, _tileLayerCounts, tileId, TileLayerSlotBase, slot);
                Report(variantId, (file << 12) | image, tileId, "tile_applied_" + FortificationSpriteCatalog.Shapes[shape]);
            }
            catch (Exception exception)
            {
                RecordFailure(exception);
            }
        }

        /// <summary>
        /// Postfix of SpriteMapping.getChevronImage: the side faces of a raised
        /// variant tile (tile_walls strips) may get another strip.
        /// </summary>
        internal void OnChevronImage(GameMapTile tile, int file, int image, ref Sprite result)
        {
            if (tile == null || result == null || _tiles.Count == 0)
            {
                return;
            }
            try
            {
                GameTileManagerAPI api = GameTileManagerAPI.Instance;
                if (api == null)
                {
                    return;
                }
                int tileId = api.GetTileId(tile.gameMapX, tile.gameMapY);
                string variantId;
                if (!FortificationStateStore.IsValidTileId(tileId) || !_tiles.TryGetValue(tileId, out variantId))
                {
                    return;
                }
                FortificationSpriteRecipe recipe;
                if (!_catalog.TryGetRecipe(variantId, file, image, 0, out recipe)
                    || recipe.Body == null || recipe.Body.TargetGm == 0)
                {
                    return;
                }
                Sprite sprite = LoadSprite(recipe.Body.TargetGm, recipe.Body.TargetImage);
                if (sprite == null)
                {
                    Report(variantId, image, tileId, "chevron_target_unavailable");
                    return;
                }
                result = sprite;
                Report(variantId, (file << 12) | (image & 0xFFF), tileId, "chevron_applied");
            }
            catch (Exception exception)
            {
                RecordFailure(exception);
            }
        }

        internal static int LayerId(int tileId, int slot)
        {
            return LayerIdBase + tileId * LayerSlots + slot;
        }

        /// <summary>
        /// Wall direction at a tile from the raised-wall neighbours (WallGFXGrid
        /// with the high flag): 1 = se (+/-x), 2 = sw (+/-y), 3 = h (+x/-y),
        /// 4 = v (+x/+y), 0 = none.
        /// </summary>
        internal static int ClassifyShape(GameTileManagerAPI api, int x, int y)
        {
            bool se = IsWallTile(api, x + 1, y) || IsWallTile(api, x - 1, y);
            bool sw = IsWallTile(api, x, y + 1) || IsWallTile(api, x, y - 1);
            bool h = IsWallTile(api, x + 1, y - 1) || IsWallTile(api, x - 1, y + 1);
            bool v = IsWallTile(api, x + 1, y + 1) || IsWallTile(api, x - 1, y - 1);
            if (se)
            {
                return 1;
            }
            if (sw)
            {
                return 2;
            }
            if (h)
            {
                return 3;
            }
            return v ? 4 : 0;
        }

        /// <summary>
        /// Stair shape at a tile: the wall axis from <see cref="ClassifyShape"/>
        /// plus the ascent direction and the step index 0..3, counted from the
        /// open (ground) end of the stair run. The high end is the one that
        /// touches a raised wall tile; with walls on both sides or none the
        /// stair ascends along the positive axis. A run longer than four tiles
        /// keeps the plain wall shape, so the catalog falls back to the plain
        /// palisade piece for the surplus tiles.
        /// </summary>
        private int ClassifyStairShape(GameTileManagerAPI api, int x, int y)
        {
            int axis = ClassifyShape(api, x, y);
            if (axis != 1 && axis != 2)
            {
                // h/v runs touch at the corners; SH1 has no ramp art for them.
                return axis;
            }
            int dx = axis == 1 ? 1 : 0;
            int dy = axis == 1 ? 0 : 1;
            int before = 0;
            while (before < StairRunLimit
                && IsStairTile(api, x - (before + 1) * dx, y - (before + 1) * dy))
            {
                before++;
            }
            int after = 0;
            while (after < StairRunLimit
                && IsStairTile(api, x + (after + 1) * dx, y + (after + 1) * dy))
            {
                after++;
            }
            bool wallAfter = IsWallTile(
                api, x + (after + 1) * dx, y + (after + 1) * dy);
            bool wallBefore = IsWallTile(
                api, x - (before + 1) * dx, y - (before + 1) * dy);
            return FortificationStairShape.Resolve(
                axis, before, after, wallBefore, wallAfter);
        }

        private bool IsStairTile(GameTileManagerAPI api, int x, int y)
        {
            if (x < 0
                || y < 0
                || x >= FortificationStateStore.MapWidth
                || y >= FortificationStateStore.MapWidth)
            {
                return false;
            }
            int tileId = api.GetTileId(x, y);
            string variantId;
            return FortificationStateStore.IsValidTileId(tileId)
                && _tiles.TryGetValue(tileId, out variantId)
                && variantId == WoodenStairsVariantId;
        }

        private static bool IsWallTile(GameTileManagerAPI api, int x, int y)
        {
            if (x < 0 || y < 0 || x >= FortificationStateStore.MapWidth || y >= FortificationStateStore.MapWidth)
            {
                return false;
            }
            int tileId = api.GetTileId(x, y);
            return FortificationStateStore.IsValidTileId(tileId)
                && api.TileManager.WallGFXGrid[tileId] >= WallTileFlag;
        }

        private static Vector3 CellCentre(int x, int y)
        {
            MainControls controls = MainControls.instance;
            return controls != null ? controls.getCellCentre(x, y) : Vector3.zero;
        }

        private WallFillin AddOwnFillin(GameMap map, int layerId, int x, int y, float height, int image, int xoffset)
        {
            _reentrant = true;
            try
            {
                map.addUpdateWallFillin(layerId, x, y, height, image, xoffset);
            }
            finally
            {
                _reentrant = false;
            }
            WallFillin created = FindFillin(map, layerId);
            return created != null && created.sprRenderer != null ? created : null;
        }

        private void TrimLayers(GameMap map, Dictionary<int, int> counts, int tileId, int slotBase, int keep)
        {
            int previous;
            counts.TryGetValue(tileId, out previous);
            for (int stale = keep; stale < previous; stale++)
            {
                DeleteLayer(map, LayerId(tileId, slotBase + stale));
            }
            if (keep > 0)
            {
                counts[tileId] = keep;
            }
            else
            {
                counts.Remove(tileId);
            }
        }

        private void DeleteLayers(int tileId)
        {
            GameMap map = GameMap.instance;
            if (map == null)
            {
                _fillinLayerCounts.Remove(tileId);
                _tileLayerCounts.Remove(tileId);
                return;
            }
            TrimLayers(map, _fillinLayerCounts, tileId, 0, 0);
            TrimLayers(map, _tileLayerCounts, tileId, TileLayerSlotBase, 0);
        }

        private void DeleteAllLayers()
        {
            var tileIds = new HashSet<int>(_fillinLayerCounts.Keys);
            tileIds.UnionWith(_tileLayerCounts.Keys);
            foreach (int tileId in tileIds)
            {
                try
                {
                    DeleteLayers(tileId);
                }
                catch (Exception exception)
                {
                    RecordFailure(exception);
                }
            }
            _fillinLayerCounts.Clear();
            _tileLayerCounts.Clear();
        }

        private void DeleteLayer(GameMap map, int layerId)
        {
            _reentrant = true;
            try
            {
                map.deleteWallFillin(layerId);
            }
            finally
            {
                _reentrant = false;
            }
        }

        private static Sprite LoadSprite(int gm, int image)
        {
            spriteLoader loader = spriteLoader.instance;
            return loader == null ? null : loader.GetGMSprite((Enums.GM)gm, image);
        }

        /// <summary>
        /// A tile frame carries its pivot in the ground diamond; placing that
        /// pivot at the cell centre (plus offsets) draws it exactly like the
        /// game draws its own tile images.
        /// </summary>
        private static bool PlaceTileFrame(WallFillin fillin, int gm, int image, Vector3 at)
        {
            Sprite sprite = LoadSprite(gm, image);
            if (sprite == null || fillin.gameObject == null)
            {
                return false;
            }
            fillin.sprRenderer.sprite = sprite;
            Vector3 position = fillin.gameObject.transform.position;
            fillin.gameObject.transform.position = new Vector3(at.x, at.y, position.z);
            return true;
        }

        private WallFillin FindFillin(GameMap map, int objectId)
        {
            if (!_wallFillinsFieldResolved)
            {
                _wallFillinsFieldResolved = true;
                _wallFillinsField = typeof(GameMap).GetField(
                    "wallFillins",
                    BindingFlags.NonPublic | BindingFlags.Instance);
            }
            var fillins = _wallFillinsField == null
                ? null
                : _wallFillinsField.GetValue(map) as Dictionary<int, WallFillin>;
            WallFillin value;
            if (fillins == null || !fillins.TryGetValue(objectId, out value))
            {
                return null;
            }
            return value;
        }

        private void Measure(
            GameTileManagerAPI api,
            GameMapTile tile,
            int tileId,
            float heightAboveGround,
            int image,
            int xoffset)
        {
            if (_measurementLines >= MaximumMeasurementLines)
            {
                return;
            }
            int wallGfx = api.TileManager.WallGFXGrid[tileId];
            byte structureWas = api.TileManager.StructureWasGrid[tileId];
            int heightUnits = (int)Math.Round(heightAboveGround * PixelsPerHeightUnit);
            long key = ((long)image << 40)
                | ((long)(uint)(heightUnits & 0xFFFF) << 24)
                | (long)(uint)tileId;
            if (!_measuredFillins.Add(key))
            {
                return;
            }
            _measurementLines++;
            Log("SEDE_RUNTIME_V1|event=fortification_fillin"
                + "|image=" + image.ToString(CultureInfo.InvariantCulture)
                + "|height=" + heightAboveGround.ToString("0.###", CultureInfo.InvariantCulture)
                + "|xoffset=" + xoffset.ToString(CultureInfo.InvariantCulture)
                + "|wall_gfx=" + wallGfx.ToString(CultureInfo.InvariantCulture)
                + "|structure_was=" + structureWas.ToString(CultureInfo.InvariantCulture)
                + "|owner=" + api.GetTilePlayerOwnerId(tileId).ToString(CultureInfo.InvariantCulture)
                + "|tile_height=" + tile.height.ToString("0.###", CultureInfo.InvariantCulture)
                + "|tile=" + tileId.ToString(CultureInfo.InvariantCulture)
                + "|x=" + tile.gameMapX.ToString(CultureInfo.InvariantCulture)
                + "|y=" + tile.gameMapY.ToString(CultureInfo.InvariantCulture)
                + "|tracked=" + (_tiles.ContainsKey(tileId) ? "1" : "0"));
        }

        private void MeasureTile(
            GameTileManagerAPI api,
            GameMapTile tile,
            int tileId,
            int file,
            int image,
            bool tracked,
            int shape)
        {
            if (_measurementLines >= MaximumMeasurementLines)
            {
                return;
            }
            int wallGfx = api.TileManager.WallGFXGrid[tileId];
            if (wallGfx == 0 && !tracked)
            {
                return;
            }
            long key = ((long)file << 40) | ((long)(uint)image << 20) | (long)(uint)tileId;
            if (!_measuredTiles.Add(key))
            {
                return;
            }
            _measurementLines++;
            Log("SEDE_RUNTIME_V1|event=fortification_tile_probe"
                + "|file=" + file.ToString(CultureInfo.InvariantCulture)
                + "|image=" + image.ToString(CultureInfo.InvariantCulture)
                + "|wall_gfx=" + wallGfx.ToString(CultureInfo.InvariantCulture)
                + "|tracked=" + (tracked ? "1" : "0")
                + "|shape=" + FortificationSpriteCatalog.Shapes[shape]
                + "|height=" + tile.height.ToString("0.###", CultureInfo.InvariantCulture)
                + "|x=" + tile.gameMapX.ToString(CultureInfo.InvariantCulture)
                + "|y=" + tile.gameMapY.ToString(CultureInfo.InvariantCulture));
        }

        private void Report(string variantId, int image, int tileId, string status)
        {
            if (_reportLines >= MaximumReportLines)
            {
                return;
            }
            long key = ((long)status.GetHashCode() << 32) | (long)(uint)((image << 8) ^ variantId.GetHashCode());
            if (!_reported.Add(key))
            {
                return;
            }
            _reportLines++;
            Log("SEDE_RUNTIME_V1|event=fortification_visual"
                + "|status=" + status
                + "|variant=" + variantId
                + "|image=" + image.ToString(CultureInfo.InvariantCulture)
                + "|tile=" + tileId.ToString(CultureInfo.InvariantCulture)
                + "|layers=" + LayerCount.ToString(CultureInfo.InvariantCulture));
        }

        private void RecordFailure(Exception exception)
        {
            _routerFailures++;
            if (_routerFailures == 1)
            {
                Log("SEDE_RUNTIME_V1|event=fortification_visual|status=router_error"
                    + "|reason=" + AssetStreamText.Sanitize(
                        exception.GetType().Name + ": " + exception.Message, 160));
            }
        }

        private void Log(string message)
        {
            if (_info == null)
            {
                return;
            }
            try
            {
                _info(message);
            }
            catch
            {
            }
        }
    }
}
