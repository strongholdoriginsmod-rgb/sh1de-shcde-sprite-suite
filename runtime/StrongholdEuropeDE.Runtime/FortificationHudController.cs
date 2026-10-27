using System;
using System.Collections.Generic;
using CrusaderDE;
using Noesis;
using SHCDESE.API;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Rebinds the castle/gate layout after every native page setup.
    /// It never changes HUD_Main's fixed button arrays and never duplicates the
    /// native ButtonBuildCrenalatedWall action.
    ///
    /// Layout contract since 2026-09-02 (vanilla look):
    /// - Castle page (buildScreenID 1): the two category buttons occupy exactly
    ///   the native wooden-wall and stone-wall slots with the native icons;
    ///   stairs, crenellated wall, barracks, armoury and the four sub-menu
    ///   buttons stay untouched.
    /// - Wall sub-pages follow the native tower/gate sub-page geometry: the
    ///   return button at 10,22 (36x35), then the wall kinds from x=80 in an
    ///   80 px grid, bottom-aligned around y=80 with their natural aspect.
    /// </summary>
    internal sealed class FortificationHudController
    {
        private sealed class NativeLayout
        {
            internal float Width;
            internal float Height;
            internal Thickness Margin;
            internal Visibility Visibility;
            internal bool IsEnabled;
        }

        private static readonly string[] CastleNativeWithoutReplacedWalls =
        {
            "ButtonBuildStairs",
            "ButtonBuildCrenalatedWall",
            "ButtonBuildStoneBarracks",
            "ButtonBuildWoodenBarracks",
            "ButtonBuildWoodenBedouinStockade",
            "ButtonBuildArmoury",
            "ButtonBuildSubTowers",
            "ButtonBuildSubGates",
            "ButtonBuildSubMilitaryBuildings",
            "ButtonBuildSubKeeps",
        };

        private static readonly string[] GateNative =
        {
            "ButtonBuildSubGatesReturn",
            "ButtonBuildSmallGate",
            "ButtonBuildLargeGate",
            "ButtonBuildDrawbridge",
            "ButtonBuildDogCage",
            "ButtonBuildPitchDitch",
            "ButtonBuildKillingPit",
            "ButtonBuildBrazier",
            "ButtonBuildMoat",
            "ButtonBuildAntiMoat",
        };

        private static readonly string[] TowerNative =
        {
            "ButtonBuildSubTowersReturn",
            "ButtonBuildTowerA",
            "ButtonBuildTowerB",
            "ButtonBuildTowerC",
            "ButtonBuildTowerD",
            "ButtonBuildTowerE",
        };

        private static readonly string[] WallButtonNames =
        {
            "EuropeFortificationPointedPalisade",
            "EuropeFortificationPlatformPalisade",
            "EuropeFortificationLowStoneWall",
            "EuropeFortificationNormalStoneWall",
            "EuropeFortificationExtraHighStoneWall",
            "EuropeFortificationWoodenStairs",
        };

        private static readonly string[] WallVariantIds =
        {
            "pointed_palisade",
            "platform_palisade",
            "low_stone_wall",
            "normal_stone_wall",
            "extra_high_stone_wall",
            "wooden_stairs",
        };

        private static readonly string[] GateOrientationButtonNames =
        {
            "EuropeFortificationWoodGateNorth",
            "EuropeFortificationWoodGateEast",
            "EuropeFortificationWoodGateSouth",
            "EuropeFortificationWoodGateWest",
        };

        // Native geometry of the two replaced castle-page slots
        // (HUD_Main.xaml 2.80: ButtonBuildWoodenWall / ButtonBuildStoneWall).
        private const float WoodSlotWidth = 52.0f;
        private const float WoodSlotHeight = 52.0f;
        private const float WoodSlotLeft = 36.0f;
        private const float StoneSlotWidth = 59.0f;
        private const float StoneSlotHeight = 67.0f;
        private const float StoneSlotLeft = 96.0f;
        private const float SlotTop = 5.0f;

        // Native sub-page return button (ButtonBuildSubTowersReturn).
        private const float ReturnLeft = 10.0f;
        private const float ReturnTop = 22.0f;
        private const float ReturnWidth = 36.0f;
        private const float ReturnHeight = 35.0f;

        // Sub-page item grid: first column at 80, then every 80 px, all items
        // bottom-aligned on the same baseline as the native tower row.
        private const float ItemFirstLeft = 80.0f;
        private const float ItemPitch = 80.0f;
        private const float ItemBaseline = 80.0f;

        private readonly FortificationFeature _owner;
        private readonly Dictionary<string, NativeLayout> _originals =
            new Dictionary<string, NativeLayout>(StringComparer.Ordinal);
        private readonly Dictionary<Button, string> _wallVariants =
            new Dictionary<Button, string>();
        private readonly Dictionary<Button, int> _gateRoutes =
            new Dictionary<Button, int>();

        private HUD_Main _hud;
        private Grid _wallPanel;
        private Button _woodWallsCategory;
        private Button _stoneWallsCategory;
        private Button _wallReturn;
        private Button _woodenStairs;
        private Button _woodenPlatform;
        private Button _woodGateCategory;
        private Grid _woodGatePanel;
        private Button _woodGateReturn;
        private bool _woodGateSubPage;
        private int _wallSubPage;
        private int _capturedPage = int.MinValue;
        private bool _active;

        internal FortificationHudController(FortificationFeature owner)
        {
            _owner = owner ?? throw new ArgumentNullException(nameof(owner));
        }

        internal void Activate()
        {
            _active = true;
        }

        internal void RebindAndLayout(HUD_Main hud)
        {
            if (!_active || hud == null)
            {
                return;
            }
            if (!ReferenceEquals(_hud, hud))
            {
                DetachCustomHandlers();
                RestoreNativeLayouts();
                _originals.Clear();
                _hud = hud;
                BindCustomControls();
            }
            LayoutCurrentPage();
        }

        internal void RefreshCurrentPage()
        {
            if (_active && _hud != null)
            {
                LayoutCurrentPage();
            }
        }

        internal void RollbackOwned()
        {
            _active = false;
            _woodGateSubPage = false;
            _wallSubPage = 0;
            RestoreNativeLayouts();
            CollapseCustomPanels();
            DetachCustomHandlers();
            _originals.Clear();
            _hud = null;
        }

        private void BindCustomControls()
        {
            _wallPanel = Find<Grid>("EuropeFortificationPanel");
            _woodWallsCategory = Find<Button>(
                "EuropeFortificationWoodWallsCategory");
            _stoneWallsCategory = Find<Button>(
                "EuropeFortificationStoneWallsCategory");
            _wallReturn = Find<Button>("EuropeFortificationWallReturn");
            _woodenStairs = Find<Button>(
                "EuropeFortificationWoodenStairs");
            _woodenPlatform = Find<Button>(
                "EuropeFortificationWoodenPlatform");
            _woodGateCategory = Find<Button>(
                "EuropeFortificationWoodGateCategory");
            _woodGatePanel = Find<Grid>("EuropeFortificationWoodGatePanel");
            _woodGateReturn = Find<Button>(
                "EuropeFortificationWoodGateReturn");
            if (_wallPanel == null
                || _woodWallsCategory == null
                || _stoneWallsCategory == null
                || _wallReturn == null
                || _woodenStairs == null
                || _woodenPlatform == null
                || _woodGateCategory == null
                || _woodGatePanel == null
                || _woodGateReturn == null)
            {
                throw new InvalidOperationException(
                    "The pinned fortification XAML controls are incomplete");
            }

            _wallSubPage = 0;
            _woodWallsCategory.Click -= OnWoodWallsCategoryClick;
            _woodWallsCategory.Click += OnWoodWallsCategoryClick;
            _stoneWallsCategory.Click -= OnStoneWallsCategoryClick;
            _stoneWallsCategory.Click += OnStoneWallsCategoryClick;
            _wallReturn.Click -= OnWallReturnClick;
            _wallReturn.Click += OnWallReturnClick;

            _woodenPlatform.Click -= OnWoodenPlatformClick;
            _woodenPlatform.Click += OnWoodenPlatformClick;

            _wallVariants.Clear();
            for (int index = 0; index < WallButtonNames.Length; index++)
            {
                Button button = Find<Button>(WallButtonNames[index]);
                if (button == null)
                {
                    throw new InvalidOperationException(
                        "Missing fortification wall button: "
                        + WallButtonNames[index]);
                }
                _wallVariants.Add(button, WallVariantIds[index]);
                button.Click -= OnWallClick;
                button.Click += OnWallClick;
            }

            _gateRoutes.Clear();
            for (int index = 0;
                index < GateOrientationButtonNames.Length;
                index++)
            {
                Button button = Find<Button>(
                    GateOrientationButtonNames[index]);
                if (button == null)
                {
                    throw new InvalidOperationException(
                        "Missing wooden gate orientation button: "
                        + GateOrientationButtonNames[index]);
                }
                _gateRoutes.Add(button, index);
                button.Click -= OnGateOrientationClick;
                button.Click += OnGateOrientationClick;
            }
            _woodGateCategory.Click -= OnWoodGateCategoryClick;
            _woodGateCategory.Click += OnWoodGateCategoryClick;
            _woodGateReturn.Click -= OnWoodGateReturnClick;
            _woodGateReturn.Click += OnWoodGateReturnClick;
        }

        private void DetachCustomHandlers()
        {
            foreach (Button button in _wallVariants.Keys)
            {
                button.Click -= OnWallClick;
            }
            foreach (Button button in _gateRoutes.Keys)
            {
                button.Click -= OnGateOrientationClick;
            }
            if (_woodGateCategory != null)
            {
                _woodGateCategory.Click -= OnWoodGateCategoryClick;
            }
            if (_woodWallsCategory != null)
            {
                _woodWallsCategory.Click -= OnWoodWallsCategoryClick;
            }
            if (_stoneWallsCategory != null)
            {
                _stoneWallsCategory.Click -= OnStoneWallsCategoryClick;
            }
            if (_wallReturn != null)
            {
                _wallReturn.Click -= OnWallReturnClick;
            }
            if (_woodenStairs != null)
            {
            }
            if (_woodenPlatform != null)
            {
                _woodenPlatform.Click -= OnWoodenPlatformClick;
            }
            if (_woodGateReturn != null)
            {
                _woodGateReturn.Click -= OnWoodGateReturnClick;
            }
            _wallVariants.Clear();
            _gateRoutes.Clear();
            _wallPanel = null;
            _woodWallsCategory = null;
            _stoneWallsCategory = null;
            _wallReturn = null;
            _woodenStairs = null;
            _woodenPlatform = null;
            _woodGateCategory = null;
            _woodGatePanel = null;
            _woodGateReturn = null;
        }

        private void LayoutCurrentPage()
        {
            int page = MainViewModel.Instance == null
                ? -1
                : MainViewModel.Instance.buildScreenID;
            if (page != _capturedPage)
            {
                // SetupNewBuildScreen has just re-enabled the buttons of the
                // new page and disabled every other page; captures from the
                // previous page would restore stale IsEnabled values there.
                _originals.Clear();
                _capturedPage = page;
            }
            RestoreNativeLayouts();
            CollapseCustomPanels();
            if (!_owner.UiScopeAllowed())
            {
                _wallSubPage = 0;
                _woodGateSubPage = false;
                return;
            }
            if (page == 1)
            {
                _woodGateSubPage = false;
                LayoutCastlePage();
            }
            else if (page == 7)
            {
                _wallSubPage = 0;
                _woodGateSubPage = false;
                LayoutTowerPage();
            }
            else if (page == 8)
            {
                _wallSubPage = 0;
                LayoutGatePage();
            }
            else
            {
                _wallSubPage = 0;
                _woodGateSubPage = false;
            }
        }

        private void LayoutCastlePage()
        {
            bool showVariants = _owner.WallVariantUiAllowed();
            Button nativeWood = Find<Button>("ButtonBuildWoodenWall");
            Button nativeStone = Find<Button>("ButtonBuildStoneWall");
            if (showVariants)
            {
                SetNativeVisibility(nativeWood, Visibility.Collapsed);
                SetNativeVisibility(nativeStone, Visibility.Collapsed);
                if (_wallSubPage == 1 || _wallSubPage == 2)
                {
                    LayoutWallSubPage(nativeWood, nativeStone);
                    return;
                }

                // The castle page keeps its native spacing and icon sizes:
                // the two category controls take exactly the two native wall
                // slots, with the native icons, and open their own sub-page.
                ShowWallCategory(_woodWallsCategory,
                    WoodSlotWidth, WoodSlotHeight, WoodSlotLeft, SlotTop);
                ShowWallCategory(_stoneWallsCategory,
                    StoneSlotWidth, StoneSlotHeight, StoneSlotLeft, SlotTop);
            }
            else
            {
                // RestoreNativeLayouts already ran. Until a measured wall
                // route is available outside the editor, vanilla controls
                // must remain byte-for-byte in their native layout.
                return;
            }
        }

        private void LayoutTowerPage()
        {
            if (!_owner.WoodenPlatformProbeUiAllowed())
            {
                return;
            }
            _woodenPlatform.Visibility = Visibility.Visible;
            _woodenPlatform.IsEnabled = true;
            // Slot 120..140 is the native gap between TowerA and TowerB.
            // Keeping every native aspect ratio intact makes the SH1 texture
            // conversion readable and puts the two Mapper-110 controls next
            // to one another for the editor comparison.
            _woodenPlatform.Width = 20.0f;
            _woodenPlatform.Height = 75.0f;
            _woodenPlatform.Margin = new Thickness(120.0f, 20.0f, 0.0f, 0.0f);
        }

        private void LayoutGatePage()
        {
            if (!_owner.WallVariantUiAllowed())
            {
                _woodGateSubPage = false;
                return;
            }
            if (_woodGateSubPage
                && GeneratedFortificationContract.WoodenGateMeasured
                && _owner.WoodenGateUiAllowed())
            {
                foreach (string name in GateNative)
                {
                    SetNativeVisibility(Find<Button>(name), Visibility.Collapsed);
                }
                _woodGatePanel.Visibility = Visibility.Visible;
                _woodGatePanel.IsEnabled = true;
                return;
            }

            _woodGateSubPage = false;
            if (!GeneratedFortificationContract.WoodenGateMeasured
                || !_owner.WoodenGateUiAllowed())
            {
                // Before measurement, even the editor leaves the native gate
                // page in its original layout.
                return;
            }
            for (int index = 0; index < GateNative.Length; index++)
            {
                CompactNative(GateNative[index], index);
            }
            if (GeneratedFortificationContract.WoodenGateMeasured
                && _owner.WoodenGateUiAllowed())
            {
                _woodGateCategory.Visibility = Visibility.Visible;
                _woodGateCategory.IsEnabled = true;
                LayoutCustomControl(_woodGateCategory, GateNative.Length);
            }
        }

        private void CompactNative(string name, int slot)
        {
            LayoutControl(Find<Button>(name), slot);
        }

        private void LayoutControl(Button button, int slot)
        {
            if (button == null)
            {
                return;
            }
            CaptureNative(button);
            ApplyCompactLayout(button, slot);
        }

        private static void LayoutCustomControl(Button button, int slot)
        {
            if (button == null)
            {
                return;
            }
            ApplyCompactLayout(button, slot);
        }

        private void LayoutWallSubPage(Button nativeWood, Button nativeStone)
        {
            // The sub-page replaces the whole castle page, exactly like the
            // native tower and gate sub-pages do: every native castle button
            // is hidden, the return button sits on the native return slot,
            // and the wall kinds follow the native item grid.
            SetNativeVisibility(nativeWood, Visibility.Collapsed);
            SetNativeVisibility(nativeStone, Visibility.Collapsed);
            foreach (string name in CastleNativeWithoutReplacedWalls)
            {
                SetNativeVisibility(Find<Button>(name), Visibility.Collapsed);
            }
            foreach (Button button in _wallVariants.Keys)
            {
                button.Visibility = Visibility.Collapsed;
                button.IsEnabled = false;
            }
            _woodenStairs.Visibility = Visibility.Collapsed;
            _woodenStairs.IsEnabled = false;
            _wallPanel.Visibility = Visibility.Visible;
            _wallPanel.IsEnabled = true;
            _wallReturn.Visibility = Visibility.Visible;
            _wallReturn.IsEnabled = true;
            PlaceWallItem(
                _wallReturn,
                ReturnLeft,
                ReturnTop,
                ReturnWidth,
                ReturnHeight);

            if (_wallSubPage == 1)
            {
                // Wood: pointed palisade, platform palisade and the wooden
                // stairs (the owner removed the battlement palisade on
                // 2026-09-02). Since 2026-09-04 the stairs are a wall kind and
                // share the same 80 px item grid as the other three.
                ShowWallItemInGrid(
                    Find<Button>("EuropeFortificationPointedPalisade"),
                    0, 62.0f, 51.0f);
                ShowWallItemInGrid(
                    Find<Button>("EuropeFortificationPlatformPalisade"),
                    1, 62.0f, 51.0f);
                ShowWallItemInGrid(
                    Find<Button>("EuropeFortificationWoodenStairs"),
                    2, 62.0f, 51.0f);
                return;
            }

            // Stone: low, normal, extra high (the owner removed the wooden
            // spikes wall on 2026-09-02).
            ShowWallItemInGrid(
                Find<Button>("EuropeFortificationLowStoneWall"),
                0, 62.0f, 58.0f);
            ShowWallItemInGrid(
                Find<Button>("EuropeFortificationNormalStoneWall"),
                1, 62.0f, 64.0f);
            ShowWallItemInGrid(
                Find<Button>("EuropeFortificationExtraHighStoneWall"),
                2, 62.0f, 79.0f);
        }

        private static void ShowWallCategory(
            Button button,
            float width,
            float height,
            float left,
            float top)
        {
            button.Visibility = Visibility.Visible;
            button.IsEnabled = true;
            button.Width = width;
            button.Height = height;
            button.Margin = new Thickness(left, top, 0.0f, 0.0f);
        }

        private static void ShowWallItemInGrid(
            Button button,
            int column,
            float width,
            float height)
        {
            if (button == null)
            {
                return;
            }
            float top = ItemBaseline - height;
            if (top < 0.0f)
            {
                top = 0.0f;
            }
            ShowCustomWallItem(
                button,
                ItemFirstLeft + (column * ItemPitch),
                top,
                width,
                height);
        }

        private static void ShowCustomWallItem(
            Button button,
            float left,
            float top,
            float width,
            float height)
        {
            if (button == null)
            {
                return;
            }
            button.Visibility = Visibility.Visible;
            button.IsEnabled = true;
            PlaceWallItem(button, left, top, width, height);
        }

        private static void PlaceWallItem(
            Button button,
            float left,
            float top,
            float width,
            float height)
        {
            button.Width = width;
            button.Height = height;
            button.Margin = new Thickness(left, top, 0.0f, 0.0f);
        }

        private static void ApplyCompactLayout(Button button, int slot)
        {
            button.Width = 36.0f;
            button.Height = 36.0f;
            int column = slot < 9 ? slot : slot - 9;
            int row = slot < 9 ? 0 : 1;
            button.Margin = new Thickness(
                4.0f + (column * 38.0f),
                5.0f + (row * 40.0f),
                0.0f,
                0.0f);
        }

        // The game switches build pages through IsEnabled: BTN_Building's
        // style triggers run FadeInMenu/FadeOutMenu storyboards that animate
        // Opacity and Visibility (HUD_Main.SetupNewBuildScreen sets IsEnabled
        // per page, never Visibility). A directly assigned Collapsed loses
        // against the held FadeIn animation value, which is why the native
        // castle buttons stayed visible under the wall sub-page (2026-09-02).
        // Disabling the button is the engine's own way to hide it.
        private void SetNativeVisibility(Button button, Visibility visibility)
        {
            if (button == null)
            {
                return;
            }
            CaptureNative(button);
            if (visibility == Visibility.Visible)
            {
                button.IsEnabled = true;
                button.Visibility = Visibility.Visible;
            }
            else
            {
                button.IsEnabled = false;
                button.Visibility = visibility;
            }
        }

        private void CaptureNative(Button button)
        {
            if (button == null || _originals.ContainsKey(button.Name))
            {
                return;
            }
            _originals.Add(
                button.Name,
                new NativeLayout
                {
                    Width = button.Width,
                    Height = button.Height,
                    Margin = button.Margin,
                    Visibility = button.Visibility,
                    IsEnabled = button.IsEnabled,
                });
        }

        private void RestoreNativeLayouts()
        {
            if (_hud == null)
            {
                return;
            }
            foreach (KeyValuePair<string, NativeLayout> pair in _originals)
            {
                Button button = Find<Button>(pair.Key);
                if (button == null)
                {
                    continue;
                }
                button.Width = pair.Value.Width;
                button.Height = pair.Value.Height;
                button.Margin = pair.Value.Margin;
                button.Visibility = pair.Value.Visibility;
                button.IsEnabled = pair.Value.IsEnabled;
            }
        }

        private void CollapseCustomPanels()
        {
            if (_wallPanel != null)
            {
                _wallPanel.Visibility = Visibility.Collapsed;
                _wallPanel.IsEnabled = false;
            }
            if (_woodWallsCategory != null)
            {
                _woodWallsCategory.Visibility = Visibility.Collapsed;
                _woodWallsCategory.IsEnabled = false;
            }
            if (_stoneWallsCategory != null)
            {
                _stoneWallsCategory.Visibility = Visibility.Collapsed;
                _stoneWallsCategory.IsEnabled = false;
            }
            if (_woodGateCategory != null)
            {
                _woodGateCategory.Visibility = Visibility.Collapsed;
                _woodGateCategory.IsEnabled = false;
            }
            if (_woodenStairs != null)
            {
                _woodenStairs.Visibility = Visibility.Collapsed;
                _woodenStairs.IsEnabled = false;
            }
            if (_woodenPlatform != null)
            {
                _woodenPlatform.Visibility = Visibility.Collapsed;
                _woodenPlatform.IsEnabled = false;
            }
            if (_woodGatePanel != null)
            {
                _woodGatePanel.Visibility = Visibility.Collapsed;
                _woodGatePanel.IsEnabled = false;
            }
        }

        private T Find<T>(string name) where T : class
        {
            if (_hud == null)
            {
                return null;
            }
            T direct = _hud.FindName(name) as T;
            if (direct != null)
            {
                return direct;
            }
            // SHCDE-SE's own 1.44 binding path uses this recursive visual-tree
            // fallback for injected patch elements that are outside the
            // generated HUD_Main name table.
            return GameXAMLManagerAPI.Instance.FindElementByName(
                _hud,
                name) as T;
        }

        private void OnWallClick(object sender, RoutedEventArgs args)
        {
            Button button = sender as Button;
            string variantId;
            if (button != null
                && _wallVariants.TryGetValue(button, out variantId))
            {
                _owner.TryStartWallVariant(variantId);
            }
        }

        private void OnWoodWallsCategoryClick(
            object sender,
            RoutedEventArgs args)
        {
            _wallSubPage = 1;
            LayoutCurrentPage();
        }

        private void OnStoneWallsCategoryClick(
            object sender,
            RoutedEventArgs args)
        {
            _wallSubPage = 2;
            LayoutCurrentPage();
        }

        private void OnWallReturnClick(object sender, RoutedEventArgs args)
        {
            _wallSubPage = 0;
            LayoutCurrentPage();
        }

        private void OnWoodGateCategoryClick(
            object sender,
            RoutedEventArgs args)
        {
            if (GeneratedFortificationContract.WoodenGateMeasured
                && _owner.WoodenGateUiAllowed())
            {
                _woodGateSubPage = true;
                LayoutCurrentPage();
            }
        }

        private void OnWoodenPlatformClick(object sender, RoutedEventArgs args)
        {
            _owner.TryStartWoodenPlatform();
        }

        private void OnWoodGateReturnClick(object sender, RoutedEventArgs args)
        {
            _woodGateSubPage = false;
            LayoutCurrentPage();
        }

        private void OnGateOrientationClick(
            object sender,
            RoutedEventArgs args)
        {
            Button button = sender as Button;
            int routeIndex;
            if (button != null
                && _gateRoutes.TryGetValue(button, out routeIndex))
            {
                _owner.TryStartWoodenGate(routeIndex);
            }
        }
    }
}
