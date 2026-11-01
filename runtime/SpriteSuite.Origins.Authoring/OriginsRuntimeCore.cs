// Dependency-free Origins campaign and season state logic, C# 5 / .NET 4.
// This module does not access games, invoke native APIs, or edit user files.
// A separately audited Script Extender adapter must implement in-game actions.
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Text.RegularExpressions;

namespace SpriteSuite.Origins.Authoring
{
    public enum MenuAction
    {
        Ignored, OpenCampaign, SelectedMission, LaunchRequested,
        BackToMenu, RejectedLocked, RejectedState
    }

    public sealed class MenuResult
    {
        public readonly MenuAction Action;
        public readonly int Mission;
        public readonly string MapFile;
        public MenuResult(MenuAction action, int mission, string mapFile)
        {
            Action = action; Mission = mission; MapFile = mapFile;
        }
    }

    public sealed class Mission
    {
        public readonly int Number;
        public readonly string Title;
        public readonly string MapFile;
        public Mission(int number, string title, string mapFile)
        {
            if (number < 1 || number > 21)
                throw new ArgumentOutOfRangeException("number");
            if (String.IsNullOrWhiteSpace(title) || title.Length > 100 ||
                title.IndexOfAny(new[] {'\r', '\n', '\0'}) >= 0)
                throw new ArgumentException("Invalid title", "title");
            if (String.IsNullOrEmpty(mapFile) || mapFile.Contains("..") ||
                !Regex.IsMatch(mapFile,
                    @"\A[A-Za-z0-9 _().-]{1,115}\.map\z") ||
                mapFile.Trim() != mapFile)
                throw new ArgumentException("Map must be a safe original filename", "mapFile");
            Number = number; Title = title; MapFile = mapFile;
        }
    }

    public sealed class ProgressSnapshot
    {
        public readonly int UnlockedMission;
        public readonly int SelectedMission;
        public readonly int[] CompletedMissions;
        public ProgressSnapshot(int unlocked, int selected, int[] completed)
        {
            UnlockedMission = unlocked; SelectedMission = selected;
            CompletedMissions = completed == null ? new int[0] : (int[])completed.Clone();
        }
    }

    public sealed class CampaignSession
    {
        private readonly ReadOnlyCollection<Mission> _missions;
        private readonly HashSet<int> _completed = new HashSet<int>();
        private int _unlocked = 1, _selected = 1;
        private bool _open;

        public CampaignSession(IList<Mission> missions)
        {
            if (missions == null || missions.Count < 1 || missions.Count > 21)
                throw new ArgumentException("Must have 1 to 21 missions");
            var ordered = new List<Mission>(missions);
            if (ordered.Contains(null)) throw new ArgumentException("Null mission");
            ordered.Sort((a,b) => a.Number.CompareTo(b.Number));
            for (int i=0; i<ordered.Count; ++i)
                if (ordered[i].Number != i + 1)
                    throw new ArgumentException("Mission numbers must be 1..N");
            _missions = ordered.AsReadOnly();
        }

        public int MissionCount { get { return _missions.Count; } }
        public int UnlockedMission { get { return _unlocked; } }
        public int SelectedMission { get { return _selected; } }
        public bool IsCampaignScreenOpen { get { return _open; } }
        public IList<Mission> Missions { get { return _missions; } }

        public MenuResult HandleCommand(string parameter)
        {
            if (parameter == "OriginsLegacyCampaign")
            {
                _open = true;
                return new MenuResult(MenuAction.OpenCampaign, _selected, null);
            }
            if (parameter == "LegacyBack")
            {
                if (!_open) return new MenuResult(MenuAction.RejectedState, 0, null);
                _open = false;
                return new MenuResult(MenuAction.BackToMenu, 0, null);
            }
            if (parameter == "LegacyStart")
            {
                if (!_open || _selected > _unlocked)
                    return new MenuResult(MenuAction.RejectedState, 0, null);
                // The caller must independently attest the game ABI and map
                // before executing this launch request.
                return new MenuResult(MenuAction.LaunchRequested, _selected,
                    _missions[_selected-1].MapFile);
            }
            if (parameter != null &&
                parameter.StartsWith("LegacyM", StringComparison.Ordinal))
            {
                string numeric = parameter.Substring(7);
                int number;
                if (!Int32.TryParse(numeric, out number) ||
                    number < 1 || number > _missions.Count ||
                    numeric != number.ToString())
                    return new MenuResult(MenuAction.Ignored, 0, null);
                if (!_open) return new MenuResult(MenuAction.RejectedState, 0, null);
                if (number > _unlocked)
                    return new MenuResult(MenuAction.RejectedLocked, number, null);
                _selected = number;
                return new MenuResult(MenuAction.SelectedMission, number, null);
            }
            return new MenuResult(MenuAction.Ignored, 0, null);
        }

        public bool MarkCompleted(int number)
        {
            if (number < 1 || number > _missions.Count || number > _unlocked)
                return false;
            bool added = _completed.Add(number);
            if (added && number == _unlocked && number < _missions.Count)
                ++_unlocked;
            return added;
        }

        public ProgressSnapshot ExportProgress()
        {
            var saved = new List<int>(_completed);
            saved.Sort();
            return new ProgressSnapshot(_unlocked, _selected, saved.ToArray());
        }

        public void RestoreProgress(ProgressSnapshot state)
        {
            if (state == null || state.UnlockedMission < 1 ||
                state.UnlockedMission > _missions.Count ||
                state.SelectedMission < 1 ||
                state.SelectedMission > state.UnlockedMission)
                throw new ArgumentException("Invalid progress snapshot");
            var finished = new HashSet<int>();
            foreach (int number in state.CompletedMissions)
            {
                if (number < 1 || number > state.UnlockedMission ||
                    number > _missions.Count || !finished.Add(number))
                    throw new ArgumentException("Invalid completed missions");
            }
            for (int n=1; n<state.UnlockedMission; ++n)
                if (!finished.Contains(n))
                    throw new ArgumentException("Cannot unlock without completion");
            _completed.Clear();
            foreach (int n in finished) _completed.Add(n);
            _unlocked = state.UnlockedMission;
            _selected = state.SelectedMission;
            _open = false;
        }
    }

    public sealed class SeasonGroup
    {
        private static readonly Dictionary<string,int> Known =
            new Dictionary<string,int>(StringComparer.Ordinal)
            {
                {"tile_land8",2}, {"tile_chevrons",3}, {"tile_cliffs",9},
                {"tile_land_macros",55}, {"tree_pine",30}, {"Tree_Chestnut",31}
            };

        public readonly string Name;
        public readonly int GmId;
        public SeasonGroup(string name, int gmId)
        {
            int known;
            if (String.IsNullOrEmpty(name) ||
                !Known.TryGetValue(name, out known) || gmId != known)
                throw new ArgumentException("Unknown or changed native GM ID");
            Name = name; GmId = gmId;
        }
    }

    public sealed class SeasonRoute
    {
        public readonly string MapFile;
        public readonly string PackId;
        public SeasonRoute(string mapFile, string packId)
        {
            if (String.IsNullOrEmpty(mapFile) || mapFile.Contains("..") ||
                !Regex.IsMatch(mapFile, @"\A[A-Za-z0-9 _().-]{1,115}\.map\z"))
                throw new ArgumentException("Invalid map");
            if (String.IsNullOrEmpty(packId) ||
                !Regex.IsMatch(packId, @"\A[a-z][a-z0-9-]{2,52}\z"))
                throw new ArgumentException("Invalid pack ID");
            MapFile = mapFile; PackId = packId;
        }
    }

    public sealed class SeasonSession
    {
        private readonly Dictionary<string,string> _routes =
            new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
        private string _active, _currentMap;

        public SeasonSession(IList<SeasonRoute> routes)
        {
            if (routes == null) throw new ArgumentNullException("routes");
            foreach (SeasonRoute item in routes)
            {
                if (item == null || _routes.ContainsKey(item.MapFile))
                    throw new ArgumentException("Null or duplicate season route");
                _routes.Add(item.MapFile,item.PackId);
            }
        }

        public string ActivePack { get { return _active; } }
        public string CurrentMap { get { return _currentMap; } }

        public string ResolvePack(string mapFile)
        {
            if (String.IsNullOrEmpty(mapFile) || mapFile.Contains("..") ||
                !Regex.IsMatch(mapFile, @"\A[A-Za-z0-9 _().-]{1,115}\.map\z"))
                return null;
            string result;
            return _routes.TryGetValue(mapFile, out result) ? result : null;
        }

        public string OnMapLoaded(string mapFile)
        {
            _active = null; _currentMap = null;
            if (String.IsNullOrEmpty(mapFile) || mapFile.Contains("..") ||
                !Regex.IsMatch(mapFile, @"\A[A-Za-z0-9 _().-]{1,115}\.map\z"))
                return null;
            _currentMap = mapFile;
            _routes.TryGetValue(mapFile,out _active);
            return _active;
        }

        public void OnMapUnloaded()
        {
            _currentMap = null; _active = null;
        }
    }

    // A host implementation is permitted only after checking BOTH the
    // native game binary ABI and the actual Noesis ViewModel bindings.
    // This interface contains no dependency on game DLLs and makes no
    // assumptions about names/offsets in current Steam builds.
    public interface IOriginsVerifiedGameHost
    {
        bool IsNativeGameAbiVerified { get; }
        bool IsNoesisMenuBindingsVerified { get; }
        bool IsSeasonAtlasLoaderVerified { get; }
        bool TryShowCampaignScreen();
        bool TryShowOriginalMainMenu();
        bool TryLaunchMission(string mapFile);
        bool TryActivateSeason(string packId);
        bool TryRestoreOriginalAtlases();
    }

    public sealed class OriginsGameBridge
    {
        private readonly CampaignSession _campaign;
        private readonly SeasonSession _seasons;
        private readonly IOriginsVerifiedGameHost _host;

        public OriginsGameBridge(CampaignSession campaign, SeasonSession seasons,
                                 IOriginsVerifiedGameHost host)
        {
            if (campaign == null || seasons == null || host == null)
                throw new ArgumentNullException("A checked runtime contract is required");
            _campaign = campaign; _seasons = seasons; _host = host;
        }

        public MenuResult OnNoesisCommand(string parameter)
        {
            if (!_host.IsNativeGameAbiVerified ||
                !_host.IsNoesisMenuBindingsVerified)
                return new MenuResult(MenuAction.RejectedState,0,null);

            // Reject an unregistered runtime command before touching UI state.
            if (parameter == "OriginsLegacyCampaign")
            {
                if (!_host.TryShowCampaignScreen())
                    return new MenuResult(MenuAction.RejectedState,0,null);
                return _campaign.HandleCommand(parameter);
            }
            if (parameter == "LegacyBack")
            {
                if (!_campaign.IsCampaignScreenOpen ||
                    !_host.TryShowOriginalMainMenu())
                    return new MenuResult(MenuAction.RejectedState,0,null);
                return _campaign.HandleCommand(parameter);
            }

            MenuResult result = _campaign.HandleCommand(parameter);
            if (result.Action == MenuAction.LaunchRequested &&
                !_host.TryLaunchMission(result.MapFile))
                return new MenuResult(MenuAction.RejectedState,0,null);
            return result;
        }

        public bool OnMapLoaded(string mapFile)
        {
            if (!_host.IsNativeGameAbiVerified ||
                !_host.IsSeasonAtlasLoaderVerified)
                return false;

            // Roll back the previous atlas BEFORE selecting the new map.
            if (_seasons.ActivePack != null)
            {
                if (!_host.TryRestoreOriginalAtlases())
                    return false; // Preserve the failure for supervised QA.
                _seasons.OnMapUnloaded();
            }
            string next = _seasons.ResolvePack(mapFile);
            if (next != null && !_host.TryActivateSeason(next))
                return false;
            _seasons.OnMapLoaded(mapFile);
            return true;
        }

        public bool OnMapUnloaded()
        {
            if (!_host.IsNativeGameAbiVerified ||
                !_host.IsSeasonAtlasLoaderVerified)
                return false;
            if (_seasons.ActivePack != null &&
                !_host.TryRestoreOriginalAtlases())
                return false;
            _seasons.OnMapUnloaded();
            return true;
        }
    }
}
