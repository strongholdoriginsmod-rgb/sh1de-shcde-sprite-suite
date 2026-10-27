#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using R3;
using SHCDESE.API;
using SHCDESE.EventAPI;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    // Pure, immutable geometric result. Native tile IDs are never treated as
    // x+y*mapSize: the raster key below belongs only to this managed 800 grid.
    internal sealed class DiplomacyCastleBoundary
    {
        internal struct Point
        {
            internal int X, Y;
            internal Point(int x, int y) { X = x; Y = y; }
        }
        private readonly Point[] _hull;
        internal DiplomacyCastleBoundary(List<Point> points) { _hull = Hull(points); }
        internal bool ContainsWorld(int worldX, int worldY)
        {
            double x = worldX / 8.0 - 0.5, y = worldY / 8.0 - 0.5;
            if (_hull.Length == 0) return false;
            bool inside = _hull.Length >= 3;
            for (int index = 0; index < _hull.Length; index++)
            {
                Point a = _hull[index], b = _hull[(index + 1) % _hull.Length];
                double dx = b.X - a.X, dy = b.Y - a.Y;
                if (dx * (y - a.Y) - dy * (x - a.X) < 0) inside = false;
                double length = dx * dx + dy * dy;
                double t = length == 0 ? 0 : Math.Max(0, Math.Min(1, ((x - a.X) * dx + (y - a.Y) * dy) / length));
                double distanceX = x - (a.X + t * dx), distanceY = y - (a.Y + t * dy);
                // Three tiles beyond the outside edge of the last wall tile.
                if (distanceX * distanceX + distanceY * distanceY <= 3.5 * 3.5) return true;
            }
            return inside;
        }
        internal static long Cross(Point a, Point b, Point c)
        { return (long)(b.X - a.X) * (c.Y - a.Y) - (long)(b.Y - a.Y) * (c.X - a.X); }
        internal static Point[] Hull(List<Point> source)
        {
            if (source.Count == 0) return new Point[0];
            var points = new List<Point>(source);
            points.Sort((a, b) => a.X != b.X ? a.X.CompareTo(b.X) : a.Y.CompareTo(b.Y));
            var hull = new List<Point>();
            foreach (Point p in points)
            {
                if (hull.Count > 0 && hull[hull.Count - 1].X == p.X && hull[hull.Count - 1].Y == p.Y) continue;
                while (hull.Count >= 2 && Cross(hull[hull.Count - 2], hull[hull.Count - 1], p) <= 0) hull.RemoveAt(hull.Count - 1);
                hull.Add(p);
            }
            int lower = hull.Count;
            for (int index = points.Count - 2; index >= 0; index--)
            {
                Point p = points[index];
                while (hull.Count > lower && Cross(hull[hull.Count - 2], hull[hull.Count - 1], p) <= 0) hull.RemoveAt(hull.Count - 1);
                hull.Add(p);
            }
            if (hull.Count > 1) hull.RemoveAt(hull.Count - 1);
            return hull.ToArray();
        }
        internal static bool Encloses(Point[] hull, Point keep)
        {
            if (hull.Length < 3) return false;
            for (int i = 0; i < hull.Length; i++)
                if (Cross(hull[i], hull[(i + 1) % hull.Length], keep) < 0) return false;
            return true;
        }
    }

    internal sealed class DiplomacyCastleBoundaryBuilder
    {
        internal const int Width = 800;
        private sealed class Component
        {
            internal int Owner, MinX = Width, MinY = Width, MaxX, MaxY;
            internal long KeepDistance = long.MaxValue;
            // Two endpoints per occupied row preserve the convex hull while
            // limiting a single component's geometry to at most 1600 points.
            internal readonly Dictionary<int, int[]> Rows = new Dictionary<int, int[]>();
        }
        private readonly byte[] _owners = new byte[Width * Width];
        private readonly int[] _parents = new int[Width * Width];
        private readonly DiplomacyCastleBoundary.Point?[] _keeps;
        private readonly Dictionary<int, Component> _components = new Dictionary<int, Component>();
        private readonly List<DiplomacyCastleBoundary.Point>[] _chosen = new List<DiplomacyCastleBoundary.Point>[9];
        private IEnumerator<Component> _componentIterator;
        private int _geometryCursor, _finishPlayer = 1;
        internal readonly DiplomacyCastleBoundary[] Result = new DiplomacyCastleBoundary[9];
        internal int NativeCursor;
        internal bool Complete { get; private set; }
        internal DiplomacyCastleBoundaryBuilder(DiplomacyCastleBoundary.Point?[] keeps)
        {
            _keeps = (DiplomacyCastleBoundary.Point?[])keeps.Clone();
            for (int player = 1; player <= 8; player++) _chosen[player] = new List<DiplomacyCastleBoundary.Point>();
        }
        internal void Observe(int x, int y, int owner)
        {
            if (owner < 1 || owner > 8 || x < 0 || y < 0 || x >= Width || y >= Width) return;
            int index = y * Width + x;
            _owners[index] = (byte)owner; _parents[index] = index + 1;
            // Observations arrive in row order. Four already observed neighbours
            // give eight-way connectivity, including diagonal wall corners.
            if (x > 0) Join(index, index - 1);
            if (y > 0)
            {
                Join(index, index - Width);
                if (x > 0) Join(index, index - Width - 1);
                if (x + 1 < Width) Join(index, index - Width + 1);
            }
        }
        private int Root(int index)
        {
            int parent = _parents[index] - 1;
            while (parent != index)
            {
                int next = _parents[parent] - 1;
                _parents[index] = next + 1; index = parent; parent = next;
            }
            return index;
        }
        private void Join(int first, int second)
        {
            if (_owners[first] != _owners[second]) return;
            int a = Root(first), b = Root(second);
            if (a != b) _parents[Math.Max(a, b)] = Math.Min(a, b) + 1;
        }
        internal void StepGeometry(int budget)
        {
            if (Complete || NativeCursor < Width * Width) return;
            if (_geometryCursor < Width * Width)
            {
                int end = Math.Min(Width * Width, _geometryCursor + Math.Max(1, budget));
                while (_geometryCursor < end)
                {
                    int index = _geometryCursor++, owner = _owners[index];
                    if (owner == 0 || !_keeps[owner].HasValue) continue;
                    int root = Root(index), x = index % Width, y = index / Width;
                    Component c;
                    if (!_components.TryGetValue(root, out c))
                    { c = new Component { Owner = owner }; _components.Add(root, c); }
                    c.MinX = Math.Min(c.MinX, x); c.MaxX = Math.Max(c.MaxX, x);
                    c.MinY = Math.Min(c.MinY, y); c.MaxY = Math.Max(c.MaxY, y);
                    DiplomacyCastleBoundary.Point keep = _keeps[owner].Value;
                    long dx = x - keep.X, dy = y - keep.Y;
                    c.KeepDistance = Math.Min(c.KeepDistance, dx * dx + dy * dy);
                    int[] row;
                    if (!c.Rows.TryGetValue(y, out row)) c.Rows.Add(y, new[] { x, x });
                    else { row[0] = Math.Min(row[0], x); row[1] = Math.Max(row[1], x); }
                }
                return;
            }
            if (_componentIterator == null) _componentIterator = _components.Values.GetEnumerator();
            // Bounded component work, including a hostile map full of isolated
            // walls. Distant outposts fail before any hull allocation/sort.
            for (int item = 0; item < 16; item++)
            {
                if (!_componentIterator.MoveNext())
                {
                    if (_finishPlayer <= 8)
                    {
                        int player = _finishPlayer++;
                        if (_chosen[player].Count > 0) Result[player] = new DiplomacyCastleBoundary(_chosen[player]);
                        return;
                    }
                    Complete = true; _componentIterator.Dispose(); return;
                }
                Component c = _componentIterator.Current;
                DiplomacyCastleBoundary.Point keep = _keeps[c.Owner].Value;
                bool nearKeep = c.KeepDistance <= 24L * 24L;
                if (!nearKeep && (keep.X < c.MinX || keep.X > c.MaxX || keep.Y < c.MinY || keep.Y > c.MaxY)) continue;
                var points = new List<DiplomacyCastleBoundary.Point>();
                foreach (KeyValuePair<int, int[]> row in c.Rows)
                { points.Add(new DiplomacyCastleBoundary.Point(row.Value[0], row.Key)); points.Add(new DiplomacyCastleBoundary.Point(row.Value[1], row.Key)); }
                DiplomacyCastleBoundary.Point[] hull = DiplomacyCastleBoundary.Hull(points);
                if (nearKeep || DiplomacyCastleBoundary.Encloses(hull, keep)) _chosen[c.Owner].AddRange(hull);
            }
        }
    }

    internal sealed partial class DiplomacyFeature
    {
        private DiplomacyCastleBoundary[] _v2CastleBoundaries = new DiplomacyCastleBoundary[9];
        private DiplomacyCastleBoundaryBuilder _v2CastleBuilder;
        private long _v2CastleEpoch = -1, _v2CastleNextScanTick;
        private int _v2CastleRefreshRequested;
        private bool _v2CastleSnapshotReady;
        private IDisposable _v2CastleSpawn, _v2CastleWall, _v2CastleDelete, _v2CastleBulldoze;

        private void ApplyV2CastleBoundaryEvents()
        {
            _v2CastleSpawn = ObservableSubscribeExtensions.Subscribe(BuildingR3EventHooks.OnBuildingSpawn.Observable,
                e => { if (e.Phase == EventHookPhase.Post) Interlocked.Exchange(ref _v2CastleRefreshRequested, 1); });
            _v2CastleWall = ObservableSubscribeExtensions.Subscribe(BuildingR3EventHooks.OnBuildWall.Observable,
                e => { if (e.Phase == EventHookPhase.Post) Interlocked.Exchange(ref _v2CastleRefreshRequested, 1); });
            _v2CastleDelete = ObservableSubscribeExtensions.Subscribe(BuildingR3EventHooks.OnBuildingDelete.Observable,
                e => { if (e.Phase == EventHookPhase.Post) Interlocked.Exchange(ref _v2CastleRefreshRequested, 1); });
            _v2CastleBulldoze = ObservableSubscribeExtensions.Subscribe(BuildingR3EventHooks.OnWallBulldoze.Observable,
                e => { if (e.Phase == EventHookPhase.Post) Interlocked.Exchange(ref _v2CastleRefreshRequested, 1); });
        }
        private void RollbackV2CastleBoundaryEvents()
        {
            Dispose(ref _v2CastleSpawn); Dispose(ref _v2CastleWall);
            Dispose(ref _v2CastleDelete); Dispose(ref _v2CastleBulldoze);
            ClearV2CastleBoundaries();
        }
        private void ClearV2CastleBoundaries()
        {
            _v2CastleBuilder = null;
            Volatile.Write(ref _v2CastleBoundaries, new DiplomacyCastleBoundary[9]);
            _v2CastleEpoch = -1; _v2CastleNextScanTick = 0;
            _v2CastleSnapshotReady = false;
            Interlocked.Exchange(ref _v2CastleRefreshRequested, 0);
        }
        private static bool V2IsCastleStructure(eStructs type)
        {
            switch (type)
            {
                case eStructs.STRUCT_KEEP_ONE: case eStructs.STRUCT_KEEP_TWO: case eStructs.STRUCT_KEEP_THREE:
                case eStructs.STRUCT_KEEP_FOUR: case eStructs.STRUCT_KEEP_FIVE:
                case eStructs.STRUCT_GATE_MAIN: case eStructs.STRUCT_GATE_INNER: case eStructs.STRUCT_GATE_WOOD:
                case eStructs.STRUCT_GATE_POSTERN: case eStructs.STRUCT_GATEHOUSE: case eStructs.STRUCT_TOWER:
                case eStructs.STRUCT_KEEPDOOR_LEFT: case eStructs.STRUCT_KEEPDOOR_RIGHT: case eStructs.STRUCT_KEEPDOOR:
                case eStructs.STRUCT_TOWER1: case eStructs.STRUCT_TOWER2: case eStructs.STRUCT_TOWER3:
                case eStructs.STRUCT_TOWER4: case eStructs.STRUCT_TOWER5:
                case eStructs.STRUCT_GATE_WOOD1A: case eStructs.STRUCT_GATE_WOOD1B:
                case eStructs.STRUCT_GATE_WOOD1C: case eStructs.STRUCT_GATE_WOOD1D:
                case eStructs.STRUCT_GATE_STONE1A: case eStructs.STRUCT_GATE_STONE1B:
                case eStructs.STRUCT_GATE_STONE2A: case eStructs.STRUCT_GATE_STONE2B: return true;
                default: return false;
            }
        }
        private unsafe void TickV2CastleBoundaries()
        {
            if (!_mapActive || _mapDisabled || !_v2TreatyStandoffActive
                && !_relations.Values.Any(r => r.V2 != null && !r.Allied)) return;
            try
            {
                if (_v2CastleEpoch != _mapEpoch) { ClearV2CastleBoundaries(); _v2CastleEpoch = _mapEpoch; }
                if (_v2CastleBuilder == null && ReadSimulationTick() < _v2CastleNextScanTick
                    && Volatile.Read(ref _v2CastleRefreshRequested) == 0) return;
                if (_v2CastleBuilder != null && _v2CastleBuilder.NativeCursor >= 800 * 800)
                {
                    // No native access or engine monitor during geometry work.
                    _v2CastleBuilder.StepGeometry(8192);
                    if (_v2CastleBuilder.Complete)
                    {
                        Volatile.Write(ref _v2CastleBoundaries, (DiplomacyCastleBoundary[])_v2CastleBuilder.Result.Clone());
                        _v2CastleSnapshotReady = true;
                        _v2CastleBuilder = null;
                        _v2CastleNextScanTick = ReadSimulationTick() + 128;
                    }
                    return;
                }
                IDisposable lease;
                if (!TryEnterNativeInventorySection(out lease)) return;
                using (lease)
                {
                    GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
                    if (_v2CastleBuilder == null)
                    {
                        var keeps = new DiplomacyCastleBoundary.Point?[9];
                        foreach (int player in _roster)
                        {
                            UnmanagedVector2<int> keep = GamePlayerManagerAPI.Instance.GetPlayerKeepDoorPosition(player);
                            if (tiles.IsTileInsideMapBounds(keep.X, keep.Y))
                                keeps[player] = new DiplomacyCastleBoundary.Point(keep.X, keep.Y);
                        }
                        _v2CastleBuilder = new DiplomacyCastleBoundaryBuilder(keeps);
                        Interlocked.Exchange(ref _v2CastleRefreshRequested, 0);
                    }
                    GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                    int end = Math.Min(800 * 800, _v2CastleBuilder.NativeCursor + 4096);
                    while (_v2CastleBuilder.NativeCursor < end)
                    {
                        int index = _v2CastleBuilder.NativeCursor++, x = index % 800, y = index / 800;
                        if (!tiles.IsTileInsideMapBounds(x, y)) continue;
                        int tileId = tiles.GetTileId(x, y);
                        if (!tiles.IsValidTileId(tileId)) continue;
                        int owner = 0, buildingId = tiles.GetTileBuildingId(tileId);
                        GameBuilding* building;
                        if (buildingId > 0 && buildings.IsValidId(buildingId)
                            && buildings.TryGetBuildingById(buildingId, out building) && building != null
                            && building->r_AliveState == AliveState.IsAlive && V2IsCastleStructure(building->r_BuildingType))
                            owner = building->r_PlayerIdOwner;
                        else
                        {
                            TilePropertyFlag flags = tiles.GetTilePropertyFlag(tileId);
                            if ((flags & (TilePropertyFlag.IsWall | TilePropertyFlag.GoodsyardRelated)) == TilePropertyFlag.IsWall)
                                owner = tiles.GetTilePlayerOwnerId(tileId);
                        }
                        if (owner >= 1 && owner <= 8) _v2CastleBuilder.Observe(x, y, owner);
                    }
                }
            }
            catch (Exception exception)
            {
                _v2CastleBuilder = null; _v2CastleNextScanTick = ReadSimulationTick() + 128;
                _v2CastleSnapshotReady = false;
                V2NoteVassalOrderFault("castle_boundary", exception);
            }
        }
        private static bool V2InsideTreatyZone(V2TreatyZone zone, int worldX, int worldY)
        {
            return DiplomacyV2CombatRules.InsideZone(worldX, worldY, zone.X, zone.Y,
                    DiplomacyV2CombatRules.IntimateZoneSquaredRadiusWorld)
                || zone.Boundary != null && zone.Boundary.ContainsWorld(worldX, worldY);
        }
    }
}
#endif
