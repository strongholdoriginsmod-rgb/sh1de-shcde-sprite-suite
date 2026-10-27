using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using CrusaderDE;
using HarmonyLib;
using Noesis;
using SHCDESE.API;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Own group and picture for militia hunters and woodcutters in the troop
    /// panel (user feedback 2026-09-28: they were counted as archers and
    /// macemen and shared their button).
    /// </summary>
    /// <remarks>
    /// <para>
    /// The panel is managed (HUD_Troops): SetupSelectedTroops counts
    /// EditorDirector.getSelectedChimpTypes() per chimp type and shows one
    /// XAML button per type that has one. Hunter (6) and woodcutter (3) have
    /// no button, so the count postfix moves militiamen (and selected plain
    /// workers) to those two indices and the visibility/position postfixes
    /// show two buttons this class adds to TroopSelectionControls.
    /// </para>
    /// <para>
    /// Clicks: the vanilla buttons call GameAction(Troops_DeSelect(Except)Type)
    /// which works per chimp type; a militia hunter IS an archer there. So
    /// the two militia buttons, and the archer/maceman buttons while militia of
    /// that soldier type is selected, deselect per unit. The request is queued
    /// on the UI thread and executed at the militia's engine boundary (engine
    /// thread, under threadLock) with the engine's own per-unit deselect
    /// (0x186B80 marker, 0x19A530 player selection; the per-type path
    /// 0x186C30 + 0x124070 does the same per matching unit).
    /// </para>
    /// <para>
    /// Threads: the panel lives on the Unity main thread, the engine on the
    /// simulation thread (Director runs EngineInterface.run in a loop).
    /// MilitiaKind is written on the engine thread and only read here.
    /// </para>
    /// </remarks>
    internal sealed class WorkerMilitiaTroopPanel
    {
        internal const byte KindNone = 0;
        internal const byte KindHunter = 1;
        internal const byte KindWoodcutter = 2;
        private const int HunterKey = (int)eChimps.CHIMP_TYPE_HUNTER;
        private const int WoodcutterKey = (int)eChimps.CHIMP_TYPE_WOODCUTTER;
        private const int ArcherKey = (int)eChimps.CHIMP_TYPE_ARCHER;
        private const int MacemanKey = (int)eChimps.CHIMP_TYPE_MACEMAN;
        private const int MaxUnitId = 10000;

        /// <summary>Native unit id -> militia kind; engine thread writes.</summary>
        internal static readonly byte[] MilitiaKind = new byte[MaxUnitId + 1];

        private static WorkerMilitiaTroopPanel _instance;

        private readonly Harmony _harmony;
        private readonly Action<string> _info;
        private readonly Action<string> _warning;
        private readonly object _requestGate = new object();
        private readonly Queue<SelectionEdit> _requests = new Queue<SelectionEdit>();
        private readonly HashSet<string> _evidence = new HashSet<string>(StringComparer.Ordinal);
        private readonly List<MethodBase> _patched = new List<MethodBase>();

        private FieldInfo _selectedListField;
        private FieldInfo _listChangedField;
        private FieldInfo _positionsField;
        private Button _hunterButton;
        private Button _woodcutterButton;
        private HUD_Troops _panel;

        internal enum Category
        {
            Other,
            RealArcher,
            RealMaceman,
            Hunter,
            Woodcutter,
        }

        internal struct SelectionEdit
        {
            internal Category Target;
            internal bool KeepOnly;
        }

        internal WorkerMilitiaTroopPanel(Harmony harmony, Action<string> info, Action<string> warning)
        {
            _harmony = harmony;
            _info = info;
            _warning = warning;
        }

        internal bool Prepare(out string failure)
        {
            const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;
            _selectedListField = typeof(EditorDirector).GetField("dllSelectedChimpList", Instance);
            _listChangedField = typeof(EditorDirector).GetField("chimpListChanged", Instance);
            _positionsField = typeof(HUD_Troops).GetField("SelTroopPositions", Instance);
            if (_selectedListField == null || _selectedListField.FieldType != typeof(int[,])
                || _listChangedField == null || _listChangedField.FieldType != typeof(bool)
                || _positionsField == null || _positionsField.FieldType != typeof(TranslateTransform[]))
            {
                failure = "troop panel fields changed (dllSelectedChimpList/chimpListChanged/SelTroopPositions)";
                return false;
            }
            failure = null;
            return true;
        }

        internal void Apply()
        {
            _instance = this;
            Patch(AccessTools.Constructor(typeof(HUD_Troops), Type.EmptyTypes), postfix: "PanelCreatedPostfix");
            Patch(AccessTools.Method(typeof(EditorDirector), "getSelectedChimpTypes"), postfix: "SelectedTypesPostfix");
            Patch(AccessTools.Method(typeof(HUD_Troops), "SetSelectedTroopVisible"), postfix: "VisiblePostfix");
            Patch(AccessTools.Method(typeof(HUD_Troops), "SetSelectedTroopPosition"), postfix: "PositionPostfix");
            Patch(AccessTools.Method(typeof(HUD_Troops), "HideAllSelectedTroops"), postfix: "HideAllPostfix");
            Patch(AccessTools.Method(typeof(MainViewModel), "TroopsLeftClickCommand"), prefix: "LeftClickPrefix");
            Patch(AccessTools.Method(typeof(MainViewModel), "TroopsRightClickCommand"), prefix: "RightClickPrefix");
            // The HUD may already exist (plugin reloaded into a running game).
            try
            {
                MainViewModel model = MainViewModel.Instance;
                if (model != null && model.HUDTroopPanel != null)
                {
                    AttachButtons(model.HUDTroopPanel);
                }
            }
            catch (Exception exception)
            {
                Note("attach_existing", "Militia troop panel could not attach to the running HUD: "
                    + exception.GetType().Name);
            }
        }

        internal void Rollback()
        {
            foreach (MethodBase method in _patched)
            {
                _harmony.Unpatch(method, HarmonyPatchType.All, _harmony.Id);
            }
            _patched.Clear();
            try
            {
                DetachButtons();
            }
            catch (Exception)
            {
            }
            if (ReferenceEquals(_instance, this))
            {
                _instance = null;
            }
            Array.Clear(MilitiaKind, 0, MilitiaKind.Length);
        }

        private void Patch(MethodBase target, string prefix = null, string postfix = null)
        {
            if (target == null)
            {
                throw new InvalidOperationException("troop panel patch target missing: " + (prefix ?? postfix));
            }
            _harmony.Patch(
                target,
                prefix: prefix == null ? null : new HarmonyMethod(typeof(WorkerMilitiaTroopPanel).GetMethod(prefix, BindingFlags.NonPublic | BindingFlags.Static)),
                postfix: postfix == null ? null : new HarmonyMethod(typeof(WorkerMilitiaTroopPanel).GetMethod(postfix, BindingFlags.NonPublic | BindingFlags.Static)));
            _patched.Add(target);
        }

        // ------------------------------------------------------------------
        // Counting: militiamen and selected workers get their own group.
        // ------------------------------------------------------------------

        private static void SelectedTypesPostfix(EditorDirector __instance, int[] __result)
        {
            WorkerMilitiaTroopPanel self = _instance;
            if (self == null || __result == null || __result.Length <= MacemanKey)
            {
                return;
            }
            try
            {
                var list = self._selectedListField.GetValue(__instance) as int[,];
                if (list == null)
                {
                    return;
                }
                int count = list.GetLength(0);
                for (int i = 0; i < count; i++)
                {
                    int id = list[i, 0];
                    int listed = list[i, 1];
                    int key = GroupKey(id, listed);
                    if (key == listed || listed < 0 || listed >= __result.Length)
                    {
                        continue;
                    }
                    if (__result[listed] > 0)
                    {
                        __result[listed]--;
                    }
                    __result[key]++;
                }
            }
            catch (Exception exception)
            {
                self.Note("count." + exception.GetType().Name,
                    "Militia troop panel count skipped: " + exception.GetType().Name);
            }
        }

        /// <summary>
        /// Panel group of a selected unit. The managed list keeps a unit's type
        /// from the moment it was selected (updateDLLSelectedTroops rebuilds it
        /// only when ids change), so the live type decides.
        /// </summary>
        private static int GroupKey(int id, int listed)
        {
            if (id <= 0 || id > MaxUnitId)
            {
                return listed;
            }
            byte kind = MilitiaKind[id];
            if (kind == KindHunter)
            {
                return HunterKey;
            }
            if (kind == KindWoodcutter)
            {
                return WoodcutterKey;
            }
            int live = LiveType(id);
            if (live == HunterKey || live == WoodcutterKey)
            {
                return live;
            }
            return live > 0 ? live : listed;
        }

        private static unsafe int LiveType(int id)
        {
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            if (units == null || !units.IsValidId(id))
            {
                return -1;
            }
            GameUnit* unit;
            if (!units.TryGetUnitById(id, out unit) || unit == null)
            {
                return -1;
            }
            return (int)unit->r_UnitChimp;
        }

        internal static Category Categorize(ref GameUnit unit, int id)
        {
            byte kind = id > 0 && id <= MaxUnitId ? MilitiaKind[id] : KindNone;
            eChimps type = unit.r_UnitChimp;
            if (kind == KindHunter || type == eChimps.CHIMP_TYPE_HUNTER)
            {
                return Category.Hunter;
            }
            if (kind == KindWoodcutter || type == eChimps.CHIMP_TYPE_WOODCUTTER)
            {
                return Category.Woodcutter;
            }
            if (type == eChimps.CHIMP_TYPE_ARCHER)
            {
                return Category.RealArcher;
            }
            if (type == eChimps.CHIMP_TYPE_MACEMAN)
            {
                return Category.RealMaceman;
            }
            return Category.Other;
        }

        // ------------------------------------------------------------------
        // Buttons
        // ------------------------------------------------------------------

        private static void PanelCreatedPostfix(HUD_Troops __instance)
        {
            WorkerMilitiaTroopPanel self = _instance;
            if (self == null)
            {
                return;
            }
            try
            {
                self.AttachButtons(__instance);
            }
            catch (Exception exception)
            {
                self.Note("attach." + exception.GetType().Name,
                    "Militia troop panel buttons not added: " + exception.GetType().Name + ": " + exception.Message);
            }
        }

        private void AttachButtons(HUD_Troops panel)
        {
            if (ReferenceEquals(_panel, panel) && _hunterButton != null)
            {
                return;
            }
            var grid = panel.FindName("TroopSelectionControls") as Grid;
            var archers = panel.FindName("ArchersSelected") as Button;
            if (grid == null || archers == null)
            {
                Note("attach_missing", "Militia troop panel: TroopSelectionControls/ArchersSelected not found");
                return;
            }
            DetachButtons();
            _panel = panel;
            _hunterButton = MakeButton(archers, "MilitiaHuntersSelected", "militia_hunter", Category.Hunter);
            _woodcutterButton = MakeButton(archers, "MilitiaWoodcuttersSelected", "militia_woodcutter", Category.Woodcutter);
            grid.Children.Add(_hunterButton);
            grid.Children.Add(_woodcutterButton);
            _info("SEDE_RUNTIME_V1|event=worker_militia_panel|status=buttons_added");
        }

        private void DetachButtons()
        {
            foreach (Button button in new[] { _hunterButton, _woodcutterButton })
            {
                if (button == null)
                {
                    continue;
                }
                var parent = button.Parent as Panel;
                if (parent != null)
                {
                    parent.Children.Remove(button);
                }
            }
            _hunterButton = null;
            _woodcutterButton = null;
            _panel = null;
        }

        private Button MakeButton(Button template, string name, string art, Category category)
        {
            var button = new Button
            {
                Name = name,
                Width = template.Width,
                Height = template.Height,
                HorizontalAlignment = template.HorizontalAlignment,
                VerticalAlignment = template.VerticalAlignment,
                Margin = template.Margin,
                Style = template.Style,
                Visibility = Visibility.Hidden,
            };
            ImageSource normal = LoadArt(art + "_normal.png");
            ImageSource hover = LoadArt(art + "_hover.png") ?? normal;
            if (normal != null)
            {
                PropEx.SetSprite1(button, normal);
                PropEx.SetSprite2(button, hover);
                PropEx.SetSprite3(button, hover);
            }
            button.Click += (sender, args) => OnMilitiaButton(category, true);
            button.MouseRightButtonDown += (sender, args) => OnMilitiaButton(category, false);
            button.MouseEnter += (sender, args) => ShowRollover(category);
            button.MouseLeave += (sender, args) => HideRollover();
            return button;
        }

        private ImageSource LoadArt(string file)
        {
            try
            {
                Assembly assembly = typeof(WorkerMilitiaTroopPanel).Assembly;
                using (Stream stream = assembly.GetManifestResourceStream("StrongholdEuropeDE.Runtime.Militia." + file))
                {
                    if (stream == null)
                    {
                        Note("art_missing." + file, "Militia troop panel picture missing: " + file);
                        return null;
                    }
                    var buffer = new MemoryStream();
                    stream.CopyTo(buffer);
                    // Same loader the game uses for its own PNGs (premultiplied).
                    return MainViewModel.Instance.LoadImageFile(buffer.ToArray());
                }
            }
            catch (Exception exception)
            {
                Note("art." + file, "Militia troop panel picture " + file + " unreadable: " + exception.GetType().Name);
                return null;
            }
        }

        private void ShowRollover(Category category)
        {
            try
            {
                MainViewModel model = MainViewModel.Instance;
                bool german = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "de";
                string text = category == Category.Hunter
                    ? (german ? "Jäger (Miliz)" : "Hunters (militia)")
                    : (german ? "Holzfäller (Miliz)" : "Woodcutters (militia)");
                Traverse.Create(model).Property("TroopsPanelRollover").SetValue(text);
                model.HUDTroopPanel.RefTroopsPanelRollover.Visibility = Visibility.Visible;
            }
            catch (Exception exception)
            {
                Note("rollover", "Militia troop panel rollover skipped: " + exception.GetType().Name);
            }
        }

        private static void HideRollover()
        {
            try
            {
                MainViewModel.Instance.HUDTroopPanel.RefTroopsPanelRollover.Visibility = Visibility.Hidden;
                MainViewModel.Instance.HUDTroopPanel.RefTroopsPanelRollover2.Visibility = Visibility.Hidden;
            }
            catch (Exception)
            {
            }
        }

        private static void VisiblePostfix(int type)
        {
            WorkerMilitiaTroopPanel self = _instance;
            Button button = self == null ? null : self.ButtonFor(type);
            if (button != null)
            {
                button.Visibility = Visibility.Visible;
            }
        }

        private static void PositionPostfix(HUD_Troops __instance, int type, int slot)
        {
            WorkerMilitiaTroopPanel self = _instance;
            Button button = self == null ? null : self.ButtonFor(type);
            if (button == null)
            {
                return;
            }
            var positions = self._positionsField.GetValue(__instance) as TranslateTransform[];
            if (positions != null && slot >= 0 && slot < positions.Length)
            {
                button.RenderTransform = positions[slot];
            }
        }

        private static void HideAllPostfix()
        {
            WorkerMilitiaTroopPanel self = _instance;
            if (self == null)
            {
                return;
            }
            if (self._hunterButton != null)
            {
                self._hunterButton.Visibility = Visibility.Hidden;
            }
            if (self._woodcutterButton != null)
            {
                self._woodcutterButton.Visibility = Visibility.Hidden;
            }
        }

        private Button ButtonFor(int type)
        {
            return type == HunterKey ? _hunterButton : type == WoodcutterKey ? _woodcutterButton : null;
        }

        // ------------------------------------------------------------------
        // Clicks
        // ------------------------------------------------------------------

        private void OnMilitiaButton(Category category, bool left)
        {
            if (Director.instance != null && Director.instance.Paused)
            {
                return;
            }
            Enqueue(new SelectionEdit { Target = category, KeepOnly = left });
        }

        private static bool LeftClickPrefix(object parameter)
        {
            return VanillaClick(parameter, true);
        }

        private static bool RightClickPrefix(object parameter)
        {
            return VanillaClick(parameter, false);
        }

        /// <summary>
        /// Archer/maceman button while militia of that soldier type is selected:
        /// the per-type engine action would also take the militia, so this
        /// click is done per unit. Everything else stays vanilla.
        /// </summary>
        private static bool VanillaClick(object parameter, bool left)
        {
            WorkerMilitiaTroopPanel self = _instance;
            string name = parameter as string;
            if (self == null || name == null)
            {
                return true;
            }
            Category target;
            byte militia;
            if (name == "CHIMP_TYPE_ARCHER")
            {
                target = Category.RealArcher;
                militia = KindHunter;
            }
            else if (name == "CHIMP_TYPE_MACEMAN")
            {
                target = Category.RealMaceman;
                militia = KindWoodcutter;
            }
            else
            {
                return true;
            }
            try
            {
                if (!self.SelectionHoldsMilitia(militia))
                {
                    return true;
                }
                if (Director.instance != null && Director.instance.Paused)
                {
                    return false;
                }
                self.Enqueue(new SelectionEdit { Target = target, KeepOnly = left });
                return false;
            }
            catch (Exception exception)
            {
                self.Note("vanilla_click." + exception.GetType().Name,
                    "Militia troop panel left a vanilla click alone: " + exception.GetType().Name);
                return true;
            }
        }

        private bool SelectionHoldsMilitia(byte kind)
        {
            var list = _selectedListField.GetValue(EditorDirector.instance) as int[,];
            if (list == null)
            {
                return false;
            }
            int count = list.GetLength(0);
            for (int i = 0; i < count; i++)
            {
                int id = list[i, 0];
                if (id > 0 && id <= MaxUnitId && MilitiaKind[id] == kind)
                {
                    return true;
                }
            }
            return false;
        }

        private void Enqueue(SelectionEdit edit)
        {
            lock (_requestGate)
            {
                if (_requests.Count < 16)
                {
                    _requests.Enqueue(edit);
                }
            }
        }

        /// <summary>
        /// Engine thread, under threadLock (militia boundary). Deselects per
        /// unit with the engine's own routine.
        /// </summary>
        internal void ApplyRequests(Span<GameUnit> array, int localPlayer, Action<int> deselect)
        {
            SelectionEdit edit;
            while (true)
            {
                lock (_requestGate)
                {
                    if (_requests.Count == 0)
                    {
                        return;
                    }
                    edit = _requests.Dequeue();
                }
                if (deselect == null)
                {
                    Note("deselect_unavailable", "Militia troop panel click ignored: per-unit deselect unavailable for this engine");
                    continue;
                }
                int removed = 0;
                int limit = Math.Min(array.Length, MaxUnitId);
                for (int id = 1; id <= limit; id++)
                {
                    ref GameUnit unit = ref array[id - 1];
                    if (unit.r_UnitSelected != localPlayer
                        || unit.r_ControllableForPlayerId != localPlayer)
                    {
                        continue;
                    }
                    bool match = Categorize(ref unit, id) == edit.Target;
                    if (match != edit.KeepOnly)
                    {
                        deselect(id);
                        removed++;
                    }
                }
                RefreshPanel();
                Note("click." + edit.Target + "." + edit.KeepOnly,
                    "SEDE_RUNTIME_V1|event=worker_militia_panel_click|target=" + edit.Target
                    + "|mode=" + (edit.KeepOnly ? "keep_only" : "remove")
                    + "|deselected=" + removed.ToString(CultureInfo.InvariantCulture));
            }
        }

        /// <summary>
        /// Lets the main thread rebuild the panel on its next update
        /// (EditorDirector.updateTick: chimpListChanged -> TroopsSelectedGameAction).
        /// </summary>
        internal void RefreshPanel()
        {
            try
            {
                EditorDirector director = EditorDirector.instance;
                if (director != null)
                {
                    _listChangedField.SetValue(director, true);
                }
            }
            catch (Exception)
            {
            }
        }

        private void Note(string key, string message)
        {
            if (_evidence.Add(key))
            {
                _info(message);
            }
        }
    }
}
